#!/usr/bin/env python
# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import torch
from ..logger import BaseLogger
from typing import List, Dict, Union


logger = BaseLogger.get_logger(__name__)


@dataclass
class EpochLoss:
    """
    Class to store epoch loss of each label.
    """
    train: List[float] = field(default_factory=list)
    val: List[float] = field(default_factory=list)
    best_val_loss: float = None
    best_epoch: int = None
    update_flag: bool = False

    def append_epoch_loss(self, phase: str, new_epoch_loss: float) -> None:
        """
        Append loss to list depending on phase.

        Args:
            phase (str): train or val
            new_epoch_loss (float): loss value
        """
        getattr(self, phase).append(new_epoch_loss)

    def get_latest_loss(self, phase: str) -> float:
        """
        Return the latest loss of phase.
        Args:
            phase (str): train or val
        Returns:
            float: the latest loss
        """
        latest_loss = getattr(self, phase)[-1]
        return latest_loss

    def get_best_val_loss(self) -> float:
        """
        Return the best val loss.

        Returns:
            float: the base val loss
        """
        return self.best_val_loss

    def set_best_val_loss(self, best_val_loss: float) -> None:
        """
        Set a val loss to keep it as the best loss.

        Args:
            best_val_loss (float): the best val loss
        """
        self.best_val_loss = best_val_loss

    def get_best_epoch(self) -> float:
        """
        Return the epoch at which val loss is the best.

        Returns:
            float: epoch
        """
        return self.best_epoch

    def set_best_epoch(self, best_epoch: int) -> None:
        """
        Set best_epoch to keep it as the best epoch.

        Args:
            best_epoch (int): the best epoch
        """
        self.best_epoch = best_epoch

    def up_update_flag(self) -> None:
        """
        Set flag True to indicate that the best loss is updated.
        """
        self.update_flag = True

    def down_update_flag(self) -> None:
        """
        Set flag False to indicate that the best loss is not updated.
        """
        self.update_flag = False

    def is_val_loss_updated(self) -> bool:
        """
        Check if if val loss is updated.

        Returns:
            bool: True if val loss is updated.
        """
        return self.update_flag

    def check_best_val_loss_epoch(self, epoch: int) -> None:
        """
        Check if val loss is the best at epoch.

        Args:
            epoch (int): epoch at which loss is checked if it is the best.
        """
        if epoch == 0:
            _best_val_loss = self.get_latest_loss('val')
            self.set_best_val_loss(_best_val_loss)
            self.set_best_epoch(epoch + 1)
            self.up_update_flag()
        else:
            _latest_val_loss = self.get_latest_loss('val')
            _best_val_loss = self.get_best_val_loss()
            if _latest_val_loss < _best_val_loss:
                self.set_best_val_loss(_latest_val_loss)
                self.set_best_epoch(epoch + 1)
                self.up_update_flag()
            else:
                self.down_update_flag()


class LossStore(ABC):
    """
    Class for calculating loss and store it.
    First, losses are calculated for each iteration and then are accumulated in EpochLoss class.
    """
    def __init__(self, label_list: List[str]) -> None:
        """
        Args:
            label_list (List[str]): list of internal labels
        """
        self.label_list = label_list
        self.batch_loss = self._init_batch_loss()      # For every batch
        self.running_loss = self._init_running_loss()  # accumulates batch loss
        self.epoch_loss = self._init_epoch_loss()      # For every epoch

    def _init_batch_loss(self) -> Dict[str, None]:
        """
        Initialize dictionary to store loss of each internal label for each batch.

        Returns:
            Dict[str, None]: dictionary to store loss of each internal label for each batch
        """
        _batch_loss = dict()
        for label_name in self.label_list + ['total']:
            _batch_loss[label_name] = None
        return _batch_loss

    def _init_running_loss(self) -> Dict[str, float]:
        """
        Initialize dictionary to store loss of each label for each iteration.

        Returns:
            Dict[str, float]: dictionary to store loss of each label for each iteration
        """
        _running_loss = dict()
        for label_name in self.label_list + ['total']:
            _running_loss[label_name] = 0.0
        return _running_loss

    def _init_epoch_loss(self) -> None:
        """
        Initialize dictionary to store loss of each label for each epoch.

        Returns:
            Dict[str, float]: dictionary to store loss of each label for each epoch
        """
        _epoch_loss = dict()
        for label_name in self.label_list + ['total']:
            _epoch_loss[label_name] = EpochLoss()
        return _epoch_loss

    def cal_running_loss(self, batch_size: int = None) -> None:
        """
        Calculate loss for each iteration.
        batch_loss is accumulated in running_loss.
        This is called in train.py

        Args:
            batch_size (int): batch size. Defaults to None.
        """
        assert (batch_size is not None), 'Invalid batch_size: batch_size=None.'
        for label_name in self.label_list:
            _running_loss = self.running_loss[label_name] + (self.batch_loss[label_name].item() * batch_size)
            self.running_loss[label_name] = _running_loss
            self.running_loss['total'] = self.running_loss['total'] + _running_loss


    #! ------ docstring -----
    def cal_batch_loss(
                self,
                outputs = None,
                labels = None,
                period = None,
                network = None
                ) -> None:

        for label_name in labels.keys():
            _output = outputs[label_name]
            _label = labels[label_name]
            self.batch_loss[label_name] = self.criterion(_output, _label, period, network)

        _total = torch.tensor([0.0]).to(self.device)
        for label_name in labels.keys():
            _total = torch.add(_total, self.batch_loss[label_name])
        self.batch_loss['total'] = _total
    #! ---------------------


    def cal_epoch_loss(self, epoch: int, phase: str, dataset_size: int = None) -> None:
        """
        Calculate loss for each epoch.

        Args:
            epoch (int): epoch number
            phase (str): phase, ie. 'train' or 'val'
            dataset_size (int): dataset size. Defaults to None.
        """
        assert (dataset_size is not None), 'Invalid dataset_size: dataset_size=None.'
        # Update loss list label-wise
        _total = 0.0
        for label_name in self.label_list:
            _new_epoch_loss = self.running_loss[label_name] / dataset_size
            self.epoch_loss[label_name].append_epoch_loss(phase, _new_epoch_loss)
            _total = _total + _new_epoch_loss

        _total = _total / len(self.label_list)
        self.epoch_loss['total'].append_epoch_loss(phase, _total)

        # Updated val_best_loss and best_epoch label-wise when val
        if phase == 'val':
            for label_name in self.label_list + ['total']:
                self.epoch_loss[label_name].check_best_val_loss_epoch(epoch)

        # Initialize
        self.batch_loss = self._init_batch_loss()
        self.running_loss = self._init_running_loss()


class LossMixin:
    """
    Class to print epoch loss.
    """
    def print_epoch_loss(self, num_epochs: int, epoch: int) -> None:
        """
        Print train_loss and val_loss for the ith epoch.

        Args:
            num_epochs (int): ith epoch
            epoch (int): epoch number
        """
        _total_epoch_loss = self.epoch_loss['total']
        train_loss = _total_epoch_loss.get_latest_loss('train')
        val_loss = _total_epoch_loss.get_latest_loss('val')
        epoch_comm = f"epoch [{epoch+1:>3}/{num_epochs:<3}]"
        train_comm = f"train_loss: {train_loss:>8.4f}"
        val_comm = f"val_loss: {val_loss:>8.4f}"

        updated_comment = ''
        if (epoch > 0) and (_total_epoch_loss.is_val_loss_updated()):
            updated_comment = '   Updated best val_loss!'
        comment = epoch_comm + ', ' + train_comm + ', ' + val_comm + updated_comment
        logger.info(comment)


class LossWidget(LossStore, LossMixin):
    """
    Class for a widget to inherit multiple classes simultaneously.
    """
    pass


"""
def create_loss_store(
                    task: str,
                    criterion: torch.nn.Module,
                    label_list: List[str],
                    device: torch.device
                    ) -> LossStore:

    if task == 'classification':
        loss_store = ClsLoss(criterion, label_list, device)
    elif task == 'regression':
        loss_store = RegLoss(criterion, label_list, device)
    elif task == 'deepsurv':
        loss_store = DeepSurvLoss(criterion, label_list, device)
    else:
        raise ValueError(f"Invalid task: {task}.")
    return loss_store
"""