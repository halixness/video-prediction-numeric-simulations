
# coding: utf-8

# In[20]:


from utils.data_lightning import preloading
from utils.data_lightning import otf
import numpy as np

import matplotlib.pyplot as plt
import matplotlib as mat

import argparse

import torch as th
import os
from datetime import datetime
import matplotlib as mpl
import torch.optim as optim
import time

from models.ae import seq2seq_ConvLSTM

mat.use("Agg") # headless mode

# -------------- Functions

def sse_loss(input, target):
    return th.sum((target - input) ** 2)

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

# -------------------------------

parser = argparse.ArgumentParser(description='Trains a given model on a given dataset')

parser.add_argument('-test_size', dest='test_size', default = 0,
                    help='Test size for the split')
parser.add_argument('-val_size', dest='val_size', default = 0,
                    help='Test size for the split')
parser.add_argument('-shuffle', dest='shuffle', default=True, type=str2bool,
                    help='Shuffle the dataset')
parser.add_argument('-root', dest='root',
                    help='root path with the simulation files (cropped and stored in folders)')
parser.add_argument('-past_frames', dest='past_frames', default=4, type=int,
                    help='number of past frames')
parser.add_argument('-future_frames', dest='future_frames', default=1, type=int,
                    help='number of future frames')
parser.add_argument('-partial', dest='partial', default=None, type=float,
                    help='percentage of portion of dataset (to load partial, lighter chunks)')
parser.add_argument('-filters', dest='filters', default=16, type=int,
                    help='Number of network kernels in hidden layers')
parser.add_argument('-image_size', dest='image_size', default=256, type=int,
                    help='Width=height of image')
parser.add_argument('-batch_size', dest='batch_size', default=4, type=int,
                    help='Batch size')
parser.add_argument('-lr', dest='learning_rate', default=0.0001, type=float,
                    help='learning rate')                                              
parser.add_argument('-epochs', dest='epochs', default=200, type=int,
                    help='training iterations')
parser.add_argument('-in_channels', dest='in_channels', default=4, type=int,
                    help='number of input channels')
parser.add_argument('-out_channels', dest='out_channels', default=3, type=int,
                    help='number of input channels')
parser.add_argument('-filtering', dest='filtering', default=True, type=str2bool,
                    help='Enable filtering dynamic sequences only')
parser.add_argument('-workers', dest='workers', default=4, type=int,
                    help='Dataloader threads')

parser.add_argument('-otf', dest='otf', default=False, type=str2bool,
                    help='Use on the fly data loading')

args = parser.parse_args()
   
# -------------- Setting up the run

num_run = len(os.listdir("runs/")) + 1
now = datetime.now()
foldername = "train_{}_{}".format(num_run, now.strftime("%d_%m_%Y_%H_%M_%S"))
os.mkdir("runs/" + foldername)

# -------------------------------
if th.cuda.is_available():  
    dev = "cuda:0" 
else:  
    dev = "cpu"  
device = th.device(dev) 

plotsize = 15

if args.otf:
    dataset = otf.SWEDataModule(
        root=args.root,
        test_size=args.test_size,
        val_size=args.val_size,
        past_frames=args.past_frames,
        future_frames=args.future_frames,
        partial=args.partial,
        filtering=False,
        batch_size=args.batch_size,
        workers=args.workers,
        image_size=args.image_size,
        shuffle=False,
        dynamicity=100,
        caching=False
    )
else:
    dataset = preloading.SWEDataModule(
        root=args.root,
        test_size=args.test_size,
        val_size=args.val_size,
        past_frames=args.past_frames,
        future_frames=args.future_frames,
        partial=args.partial,
        filtering=args.filtering,
        batch_size=args.batch_size,
        workers=args.workers,
        image_size=args.image_size,
        shuffle=False,
        dynamicity=100,
        caching=False
    )

dataset.prepare_data()

# ---- Model
net = seq2seq_ConvLSTM.EncoderDecoderConvLSTM(nf=args.filters, in_chan=args.in_channels, out_chan=args.out_channels).to(device) # False: many to one
optimizer = optim.Adam(net.parameters(), lr=args.learning_rate)

# ---- Training time!
losses = []
avg_losses = []
errors = []
test_errors = []
print("\n[!] It's training time!")

epochs = args.epochs

for epoch in range(epochs):  # loop over the dataset multiple times

    print("---- Epoch {}\tbatches {}\tsequences {}".format(epoch, len(dataset.train_dataloader()), len(dataset.train_dataloader())*args.batch_size))
    epoch_start = time.time()
    training_times = []
    query_times = []
    query_start = time.time()

    for batch in dataset.train_dataloader():
        query_end = time.time()
        query_times.append(query_end-query_start)

        x, y = batch

        optimizer.zero_grad()

        if args.otf: # otf batches have an extra useless dimension
            x = x[:,0]
            y = y[:,0]

        x = x.float().to(device)
        y = y.float().to(device)

        # ---- Predicting

        start = time.time()
        outputs = net(x, args.future_frames)  # 0 for layer index, 0 for h index

        # ---- Batch Loss
        loss = sse_loss(outputs[:, :args.out_channels, 0, :, :], y[:, 0, :args.out_channels, :, :])

        loss.backward()
        optimizer.step()

        end = time.time()
        training_times.append(end - start)

        losses.append(loss.item())
        print(". ", end="", flush=True)
        query_start = time.time()

    epoch_end = time.time()
    print("\nepoch {}\tavg.loss {:.2f}\ttook {:.2f} s\tavg. inference time {:.2f} s\tavg.query time/batch {:.2f} s"
          .format(epoch, np.mean(losses), epoch_end-epoch_start, np.mean(training_times), np.mean(query_times)))
    avg_losses.append(np.mean(losses))

end = time.time()
print(end - start)

print('[!] Finished Training, storing weights...')

weights_path = "runs/" + foldername + "/model.weights"
th.save(net.state_dict(), weights_path)

# Loss plot
mpl.rcParams['text.color'] = 'k'

plt.title("average loss")
plt.plot(range(len(avg_losses)), avg_losses)
plt.savefig("runs/" + foldername + "/avg_loss.png")
plt.clf()

print("Avg.training time: {}".format(np.mean(training_times)))

'''
---- CUT OUT PLOTTING EACH EPOCH
if epoch % 2 == 0:

    k = np.random.randint(len(X_test))

    outputs = net(X_test[k], 1)  # 0 for layer index, 0 for h index

    #test_loss = criterion(outputs[0],  y_test[k,:,:,0,:,:])
    #print("test loss: {}".format(test_loss.item()))

    #------------------------------
    fig, axs = plt.subplots(1, X_test.shape[2] + 2, figsize=(plotsize, plotsize))

    for ax in axs:
        ax.set_yticklabels([])
        ax.set_xticklabels([])

    # pick random datapoint from batch
    x = np.random.randint(X_test[k].shape[0])

    for i, frame in enumerate(X_test[k, x]):
        axs[i].title.set_text('t={}'.format(i))
        axs[i].matshow(frame[0].cpu().detach().numpy())
        rect = patches.Rectangle((256, 256), 256, 256, linewidth=1, edgecolor='r', facecolor='none')
        axs[i].add_patch(rect)

    axs[i+1].matshow(outputs[x][0][0].cpu().detach().numpy())
    rect = patches.Rectangle((256, 256), 256, 256, linewidth=1, edgecolor='r', facecolor='none')
    axs[i+1].add_patch(rect)
    axs[i+1].title.set_text('Predicted')

    axs[i+2].matshow(y_test[k,x][0][0].cpu().detach().numpy())
    rect = patches.Rectangle((256, 256), 256, 256, linewidth=1, edgecolor='r', facecolor='none')
    axs[i+2].add_patch(rect)
    axs[i+2].title.set_text('Ground Truth')

    plt.show()

    if args.test_flight is None:
        plt.savefig("runs/" + foldername + "/{}_{}_plot.png".format(epoch, k))

    plt.clf()

    #------------------------------

    #if epoch % 10 == 0:
    #    print('[%d, %5d] loss: %.3f' %
    #          (epoch + 1, i + 1, running_loss / 2000))
    #    running_loss = 0.0
'''