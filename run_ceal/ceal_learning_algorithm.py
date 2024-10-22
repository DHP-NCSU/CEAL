import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import Caltech256Dataset, Normalize, RandomCrop, SquarifyImage, \
    ToTensor
from utils import get_uncertain_samples, get_high_confidence_samples, \
    update_threshold
from model import AlexNet
from torch.utils.data import DataLoader
from torchvision import transforms
from torch.utils.data.sampler import SubsetRandomSampler

import numpy as np
import torch
import logging

logging.basicConfig(format="%(levelname)s:%(name)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Set device to GPU if available
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
logger.info(f"Using device: {device}")

def ceal_learning_algorithm(du: DataLoader,
                            dl: DataLoader,
                            dtest: DataLoader,
                            k: int = 1000,
                            delta_0: float = 0.005,
                            dr: float = 0.00033,
                            t: int = 1,
                            epochs: int = 10,
                            criteria: str = 'cl',
                            max_iter: int = 45):
    """
    Algorithm1 : Learning algorithm of CEAL.
    For simplicity, I used the same notation in the paper.
    Parameters
    ----------
    du: DataLoader
        Unlabeled samples
    dl : DataLoader
        labeled samples
    dtest : DataLoader
        test data
    k: int, (default = 1000)
        uncertain samples selection
    delta_0: float
        hight confidence samples selection threshold
    dr: float
        threshold decay
    t: int
        fine-tuning interval
    epochs: int
    criteria: str
    max_iter: int
        maximum iteration number.

    Returns
    -------

    """
    logger.info('Initial configuration: len(du): {}, len(dl): {} '.format(
        len(du.sampler.indices),
        len(dl.sampler.indices)))

    # Create the model
    model = AlexNet(n_classes=256, device=device)

    # Initialize the model
    logger.info('Intialize training the model on `dl` and test on `dtest`')

    model.train(epochs=epochs, train_loader=dl, valid_loader=None)

    # Evaluate model on dtest
    acc, sd_acc, class_acc = model.evaluate_per_class(test_loader=dtest)

    # print('====> Initial accuracy: {} '.format(acc))
    print(f"====> Initial accuracy: {acc * 100:.2f}%")
    print(f"====> Initial per-class accuracies: {class_acc}")
    print(f"====> Initial sd of accuracies: {sd_acc:.4f}")

    for iteration in range(max_iter):

        logger.info('Iteration: {}: run prediction on unlabeled data '
                    '`du` '.format(iteration))

        pred_prob = model.predict(test_loader=du)

        # get k uncertain samples
        uncert_samp_idx, _ = get_uncertain_samples(pred_prob=pred_prob, k=k,
                                                   criteria=criteria)

        # get original indices
        uncert_samp_idx = [du.sampler.indices[idx] for idx in uncert_samp_idx]

        # add the uncertain samples selected from `du` to the labeled samples
        #  set `dl`
        dl.sampler.indices.extend(uncert_samp_idx)

        logger.info(
            'Update size of `dl`  and `du` by adding uncertain {} samples'
            ' in `dl`'
            ' len(dl): {}, len(du) {}'.
            format(len(uncert_samp_idx), len(dl.sampler.indices),
                   len(du.sampler.indices)))

        # get high confidence samples `dh`
        hcs_idx, hcs_labels = get_high_confidence_samples(pred_prob=pred_prob,
                                                          delta=delta_0)
        # get the original indices
        hcs_idx = [du.sampler.indices[idx] for idx in hcs_idx]

        # remove the samples that already selected as uncertain samples.
        hcs_idx = [x for x in hcs_idx if
                   x not in list(set(uncert_samp_idx) & set(hcs_idx))]

        # add high confidence samples to the labeled set 'dl'

        # (1) update the indices
        dl.sampler.indices.extend(hcs_idx)
        # (2) update the original labels with the pseudo labels.
        for idx in range(len(hcs_idx)):
            dl.dataset.labels[hcs_idx[idx]] = hcs_labels[idx]
        logger.info(
            'Update size of `dl`  and `du` by adding {} hcs samples in `dl`'
            ' len(dl): {}, len(du) {}'.
            format(len(hcs_idx), len(dl.sampler.indices),
                   len(du.sampler.indices)))

        if iteration % t == 0:
            logger.info('Iteration: {} fine-tune the model on dh U dl'.
                        format(iteration))
            model.train(epochs=epochs, train_loader=dl)

            # update delta_0
            delta_0 = update_threshold(delta=delta_0, dr=dr, t=iteration)

        # remove the uncertain samples from the original `du`
        logger.info('remove {} uncertain samples from du'.
                    format(len(uncert_samp_idx)))
        for val in uncert_samp_idx:
            du.sampler.indices.remove(val)

        acc, sd_acc, class_acc = model.evaluate_per_class(test_loader=dtest)

        print(
            "Iteration: {}, len(dl): {}, len(du): {}, len(dh) {}\n"
            "acc: {}, sd of accuracies: {}, per-class accuracies: {}".format(
                iteration, len(dl.sampler.indices),
                len(du.sampler.indices), len(hcs_idx), acc, sd_acc, class_acc))


if __name__ == "__main__":

    dataset_train = Caltech256Dataset(
        root_dir="../data/256_ObjectCategories",
        transform=transforms.Compose(
            [SquarifyImage(),
             RandomCrop(224),
             Normalize(),
             ToTensor()]))

    dataset_test = Caltech256Dataset(
        root_dir="../data/divided",
        transform=transforms.Compose(
            [SquarifyImage(),
             RandomCrop(224),
             Normalize(),
             ToTensor()]))

    # Creating data indices for training and validation splits:
    random_seed = 123
    validation_split = 0.1  # 10%
    shuffling_dataset = True
    batch_size = 16
    dataset_size = len(dataset_train)

    indices = list(range(dataset_size))
    split = int(np.floor(validation_split * dataset_size))

    if shuffling_dataset:
        np.random.seed(random_seed)
        np.random.shuffle(indices)
    train_indices, val_indices = indices[split:], indices[:split]

    # Creating PT data samplers and loaders:
    train_sampler = SubsetRandomSampler(train_indices)
    valid_sampler = SubsetRandomSampler(val_indices)

    du = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size,
                                     sampler=train_sampler, num_workers=4)
    dl = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size,
                                     sampler=valid_sampler, num_workers=4)
    dtest = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size,
                                        num_workers=4)

    ceal_learning_algorithm(du=du, dl=dl, dtest=dtest)
