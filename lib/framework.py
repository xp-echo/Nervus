#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pathlib import Path
import copy
from abc import ABC, abstractmethod
import pandas as pd
import torch
import torch.nn as nn
from .component import (
                make_split_provider,
                create_dataloader,
                create_net
                )
from .logger import Logger as logger
from typing import Dict, Union
import argparse


class BaseModel(ABC):
    """
    Class to construct model. This class is the base class to construct model.
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Class to define Model

        Args:
            args (argparse.Namespace): options
        """
        self.args = args
        self.sp = make_split_provider(args.csv_name, args.task)

        self.task = args.task
        self.mlp = self.args.mlp
        self.net = self.args.net
        self.internal_label_list = self.sp.internal_label_list
        self.num_classes_in_internal_label = self.sp.num_classes_in_internal_label
        self.mlp_num_inputs = len(self.sp.input_list)
        self.in_channel = self.args.in_channel
        self.vit_image_size = self.args.vit_image_size
        self.gpu_ids = self.args.gpu_ids

        self.device = torch.device(f"cuda:{self.gpu_ids[0]}") if self.gpu_ids != [] else torch.device('cpu')
        self.network = create_net(self.mlp, self.net, self.num_classes_in_internal_label, self.mlp_num_inputs, self.in_channel, self.vit_image_size)

        self.isTrain = self.args.isTrain
        self._init_config_on_phase()

    def _init_config_on_phase(self):
        if self.isTrain:
            from .component import set_criterion, set_optimizer, create_loss_reg
            self.criterion = set_criterion(self.args.criterion, self.device)
            self.optimizer = set_optimizer(self.args.optimizer, self.network, self.args.lr)
            self.loss_reg = create_loss_reg(self.task, self.criterion, self.internal_label_list, self.device)
            self.dataloaders = {split: create_dataloader(self.args, self.sp, split=split) for split in ['train', 'val']}
        else:
            from .component import set_likelihood
            self.likelihood = set_likelihood(self.task, self.sp.class_name_in_raw_label, self.args.test_datetime)
            self.dataloaders = {split: create_dataloader(self.args, self.sp, split=split) for split in ['train', 'val', 'test']}

    def print_dataset_info(self) -> None:
        """
        Print dataset size for each split.
        """
        for split, dataloader in self.dataloaders.items():
            total = len(dataloader.dataset)
            logger.logger.info(f"{split:>5}_data = {total}")
        logger.logger.info('')

    def train(self) -> None:
        """
        Make self.network training mode.
        """
        self.network.train()

    def eval(self) -> None:
        """
        Make self.network evaluation mode.
        """
        self.network.eval()

    def _enable_on_gpu_if_available(self) -> None:
        """
        Make model compute on the GPU.
        """
        if self.gpu_ids != []:
            assert torch.cuda.is_available(), 'No avalibale GPU on this machine.'
            self.network.to(self.device)
            self.network = nn.DataParallel(self.network, device_ids=self.gpu_ids)
        else:
            pass

    @abstractmethod
    def set_data(self, data):
        pass
        # data = {
        #        'Filename': filename,
        #        'ExamID': examid,
        #        'Institution': institution,
        #        'raw_labels': raw_label_dict,
        #        'internal_labels': internal_label_dict,
        #        'inputs': inputs_value,
        #        'image': image,
        #        'period': period,
        #        'split': split
        #        }

    def multi_label_to_device(self, multi_label: Dict[str, Union[int, float]]) -> Dict[str, Union[int, float]]:
        """
        Pass the value of each label to the device

        Args:
            multi_label (Dict[str, Union[int, float]]): dictionary of each label and its value

        Returns:
            Dict[str, Union[int, float]]: dictionary of each label and its value which is on devide
        """
        for internal_label_name, each_data in multi_label.items():
            multi_label[internal_label_name] = each_data.to(self.device)
        return multi_label

    @abstractmethod
    def forward(self):
        pass

    def get_output(self) -> Dict[str, torch.Tensor]:
        """
        Return output of model.

        Returns:
            Dict[str, torch.Tensor]: output of model
        """
        return self.multi_output

    def backward(self) -> None:
        """
        Backward
        """
        self.loss = self.loss_reg.batch_loss['total']
        self.loss.backward()

    def optimize_parameters(self) -> None:
        """
        Update parameters
        """
        self.optimizer.step()

    # Loss
    @abstractmethod
    def cal_batch_loss(self):
        pass

    def cal_running_loss(self, batch_size: int = None) -> None:
        """
        Calculate loss for each iteration.

        Args:
            batch_size (int): batch size. Defaults to None.
        """
        self.loss_reg.cal_running_loss(batch_size)

    def cal_epoch_loss(self, epoch: int, phase: str, dataset_size: int = None) -> None:
        """
        Calculate loss for each epoch.

        Args:
            epoch (int): epoch number
            phase (str): phase, ie. 'train' or 'val'
            dataset_size (int): dataset size. Defaults to None.
        """
        self.loss_reg.cal_epoch_loss(epoch, phase, dataset_size)

    def is_total_val_loss_updated(self) -> bool:
        """
        Check if val loss updated or not.

        Returns:
            bool: True if val loss updated, otherwise False.
        """
        _total_epoch_loss = self.loss_reg.epoch_loss['total']
        is_updated = _total_epoch_loss.is_val_loss_updated()
        return is_updated

    def print_epoch_loss(self, epoch: int) -> None:
        """
        Print loss for each epoch.

        Args:
            epoch (int): epoch number
        """
        self.loss_reg.print_epoch_loss(self.args.epochs, epoch)

    # Lieklihood
    def make_likelihood(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Make DataFrame of likelihood.

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of each label and its value which is on devide
        """
        self.likelihood.make_likehood(data, self.get_output())


class SaveLoadMixin:
    """
    Class including methods for save or load weight, learning_curve, or likelihood.
    """
    # variables to keep best_weight and best_epoch temporarily.
    acting_best_weight = None
    acting_best_epoch = None

    # For weight
    def store_weight(self) -> None:
        """
        Store weight.
        """
        self.acting_best_epoch = self.loss_reg.epoch_loss['total'].get_best_epoch()
        _network = copy.deepcopy(self.network)
        if hasattr(_network, 'module'):
            # When DataParallel used
            self.acting_best_weight = copy.deepcopy(_network.module.to(torch.device('cpu')).state_dict())
        else:
            self.acting_best_weight = copy.deepcopy(_network.state_dict())

    def save_weight(self, date_name: str, as_best: bool = None) -> None:
        """
        Save weight.

        Args:
            date_name (str): save name for weight
            as_best (bool): True if weight is saved as best, otherise False. Defaults to None.
        """
        assert isinstance(as_best, bool), 'Argument as_best should be bool.'

        save_dir = Path(self.args.trainset_dir, 'results/sets', date_name, 'weights')
        save_dir.mkdir(parents=True, exist_ok=True)
        save_name = 'weight_epoch-' + str(self.acting_best_epoch).zfill(3) + '.pt'
        save_path = Path(save_dir, save_name)

        if as_best:
            save_name_as_best = 'weight_epoch-' + str(self.acting_best_epoch).zfill(3) + '_best' + '.pt'
            save_path_as_best = Path(save_dir, save_name_as_best)
            if save_path.exists():
                # Check if best weight already saved. If exists, rename with '_best'
                save_path.rename(save_path_as_best)
            else:
                torch.save(self.acting_best_weight, save_path_as_best)
        else:
            save_name = 'weight_epoch-' + str(self.acting_best_epoch).zfill(3) + '.pt'
            torch.save(self.acting_best_weight, save_path)

    def load_weight(self, weight_path: Path) -> None:
        """
        Load wight from weight_path.

        Args:
            weight_path (Path): path to weight
        """
        weight = torch.load(weight_path)
        self.network.load_state_dict(weight)

        # Make model compute on GPU after loading weight.
        self._enable_on_gpu_if_available()

    # For learning curve
    def save_learning_curve(self, date_name: str) -> None:
        """
        Save leraning curve.

        Args:
            date_name (str): save name for learning curve
        """
        save_dir = Path(self.args.trainset_dir, 'results/sets', date_name, 'learning_curves')
        save_dir.mkdir(parents=True, exist_ok=True)
        epoch_loss = self.loss_reg.epoch_loss
        for internal_label_name in self.internal_label_list + ['total']:
            each_epoch_loss = epoch_loss[internal_label_name]
            df_each_epoch_loss = pd.DataFrame({
                                                'train_loss': each_epoch_loss.train,
                                                'val_loss': each_epoch_loss.val
                                            })
            label_name = internal_label_name.replace('internal_', '') if internal_label_name.startswith('internal') else 'total'
            best_epoch = str(each_epoch_loss.get_best_epoch()).zfill(3)
            best_val_loss = f"{each_epoch_loss.get_best_val_loss():.4f}"
            save_name = 'learning_curve_' + label_name + '_val-best-epoch-' + best_epoch + '_val-best-loss-' + best_val_loss + '.csv'
            save_path = Path(save_dir, save_name)
            df_each_epoch_loss.to_csv(save_path, index=False)

    # For likelihood
    def save_likelihood(self, save_name: str) -> None:
        """
        Save likelihood.

        Args:
            save_name (str): save name for likelihood. Defaults to None.
        """
        self.likelihood.save_likelihood(save_name)


class ModelWidget(BaseModel, SaveLoadMixin):
    """
    Class for a widget to inherit multiple classes simultaneously
    """
    pass


class MLPModel(ModelWidget):
    """
    Class for MLP model
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of MLP.

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.inputs = data['inputs'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.inputs)

    def cal_batch_loss(self) -> None:
        """
        Calculate loss for bach bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label)


class CVModel(ModelWidget):
    """
    Class for CNN or ViT model
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of CNN or ViT Model.

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.image = data['image'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.image)

    def cal_batch_loss(self):
        """
        Calculate loss for each bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label)


class FusionModel(ModelWidget):
    """
    Class for MLP+CNN or MLP+ViT model.
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of MLP+CNN or MLP+ViT.

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.inputs = data['inputs'].to(self.device)
        self.image = data['image'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.inputs, self.image)

    def cal_batch_loss(self) -> None:
        """
        Calculate loss for bach bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label)


class MLPDeepSurv(ModelWidget):
    """
    Class for DeepSurv model with MLP
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of DeepSurv model with MLP

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.inputs = data['inputs'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])
        self.period = data['period'].float().to(self.device)

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.inputs)

    def cal_batch_loss(self) -> None:
        """
        Calculate loss for each bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label, self.period, self.network)


class CVDeepSurv(ModelWidget):
    """
    Class for DeepSurv model with CNN or ViT
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of DeepSurv model with with CNN or ViT

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.image = data['image'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])
        self.period = data['period'].float().to(self.device)

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.image)

    def cal_batch_loss(self) -> None:
        """
        Calculate loss for each bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label, self.period, self.network)


class FusionDeepSurv(ModelWidget):
    """
    Class for DeepSurv model with MLP+CNN or MLP+ViT model.
    """
    def __init__(self, args: argparse.Namespace) -> None:
        """
        Args:
            args (argparse.Namespace): options
        """
        super().__init__(args)

    def set_data(self, data: Dict[str, Union[str, int, Dict[str, int], float]]) -> None:
        """
        Unpack data for forwarding of DeepSurv with MLP+CNN or MLP+ViT.

        Args:
            data (Dict[str, Union[str, int, Dict[str, int], float]]): dictionary of data
        """
        self.inputs = data['inputs'].to(self.device)
        self.image = data['image'].to(self.device)
        self.multi_label = self.multi_label_to_device(data['internal_labels'])
        self.period = data['period'].float().to(self.device)

    def forward(self) -> None:
        """
        Forward.
        """
        self.multi_output = self.network(self.inputs, self.image)

    def cal_batch_loss(self) -> None:
        """
        Calculate loss for bach bach.
        """
        self.loss_reg.cal_batch_loss(self.multi_output, self.multi_label, self.period, self.network)


def create_model(args: argparse.Namespace) -> nn.Module:
    """
    Construct model

    Args:
        args (argparse.Namespace): options

    Returns:
        nn.Module: model
    """
    task = args.task
    mlp = args.mlp
    net = args.net

    if (task == 'classification') or (task == 'regression'):
        if (mlp is not None) and (net is None):
            model = MLPModel(args)
        elif (mlp is None) and (net is not None):
            model = CVModel(args)
        elif (mlp is not None) and (net is not None):
            model = FusionModel(args)
        else:
            raise ValueError(f"Invalid model type: mlp={mlp}, net={net}.")

    elif task == 'deepsurv':
        if (mlp is not None) and (net is None):
            model = MLPDeepSurv(args)
        elif (mlp is None) and (net is not None):
            model = CVDeepSurv(args)
        elif (mlp is not None) and (net is not None):
            model = FusionDeepSurv(args)
        else:
            raise ValueError(f"Invalid model type: mlp={mlp}, net={net}.")

    else:
        raise ValueError(f"Invalid task: {task}.")

    if args.isTrain:
        model._enable_on_gpu_if_available()
    # When test, execute model._enable_on_gpu_if_available() in load_weight(),
    # ie. after loadding weight.

    return model
