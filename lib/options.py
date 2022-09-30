#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pathlib import Path
import re
import argparse
import pandas as pd
from .logger import Logger as logger
from typing import Dict, List, Tuple, Union


class Options:
    """
    Class to parse options.
    """
    def __init__(self, isTrain: bool = None) -> None:
        """
        Args:
            isTrain (bool, optional): Variable indicating whether training. True when traning. Defaults to None.
        """
        assert isinstance(isTrain, bool), 'isTrain should be bool.'

        self.parser = argparse.ArgumentParser(description='Options for training or test')
        self.parser.add_argument('--csv_name',  type=str,   default=None,  help='csv name for training or external test (Default: None)')
        self.parser.add_argument('--image_dir', type=str,   default=None,  help='directory of images for training or external test(Default: None)')

        if isTrain:
            # Dataset to make weight
            self.parser.add_argument('--baseset_dir',    type=str,   default='baseset', help='directory of dataset for training (Default: baseset)')

            # Task
            self.parser.add_argument('--task',            type=str,   choices=['classification', 'regression', 'deepsurv'], default=None, help='Task: classification or regression (Default: None)')

            # Model
            self.parser.add_argument('--model',           type=str,   default=None,   help='model: MLP, CNN, ViT, or MLP+(CNN or ViT) (Default: None)')

            # Training and Internal validation
            self.parser.add_argument('--criterion',       type=str,   default=None,  help='criterion: CEL, MSE, RMSE, MAE, NLL (Default: None)')
            self.parser.add_argument('--optimizer',       type=str,   default=None,  help='optimzer: SGD, Adadelta, RMSprop, Adam, RAdam (Default: None)')
            self.parser.add_argument('--lr',              type=float, default=0.001, metavar='N', help='learning rate: (Default: 0.001)')
            self.parser.add_argument('--epochs',          type=int,   default=10,    metavar='N', help='number of epochs (Default: 10)')

            # Batch size
            self.parser.add_argument('--batch_size',      type=int,   default=None,  metavar='N', help='batch size in training (Default: None)')

            # Preprocess for image
            self.parser.add_argument('--augmentation',    type=str,   choices=['xrayaug', 'trivialaugwide', 'randaug', 'no'], default=None,  help='kind of augmentation')
            self.parser.add_argument('--normalize_image', type=str,   choices=['yes', 'no'], default='yes', help='image nomalization: yes, no (Default: yes)')

            # Sampler
            self.parser.add_argument('--sampler',         type=str,   choices=['yes', 'no'], default=None,  help='sample data in traning or not, yes or no (Default: None)')

            # Input channel
            self.parser.add_argument('--in_channel',      type=int,   choices=[1, 3], default=None,  help='channel of input image (Default: None)')
            self.parser.add_argument('--vit_image_size',  type=int,   default=None,  help='input image size for ViT(Default: None)')

            # Weight saving strategy
            self.parser.add_argument('--save_weight',     type=str,   choices=['best', 'each'], default='best', help='Save weight: best, or each(ie. save each time loss decreases when multi-label output) (Default: best)')

            # GPU
            self.parser.add_argument('--gpu_ids',         type=str,   default='-1',  help='gpu ids: e.g. 0, 0-1-2, 0-2. use -1 for CPU (Default: -1)')
        else:
            # External dataset
            self.parser.add_argument('--testset_dir',      type=str,  default='baseset', help='diretrory of internal dataset or external dataset (Default: baseset)')

            # Directry of weight at traning
            self.parser.add_argument('--weight_dir',       type=str,  default='baseset', help='directory of weight to be used when test. (Default: baseset) This is concatenated with --test_datetime.')

            # Test datatime
            self.parser.add_argument('--test_datetime',   type=str,   default=None,  help='date time when trained(Default: None)')

            # Test bash size
            self.parser.add_argument('--test_batch_size', type=int,   default=64,    metavar='N', help='batch size for test (Default: 64)')

        self.args = self.parser.parse_args()
        setattr(self.args, 'isTrain', isTrain)

    def _parse_model(self, model_name: str) -> Tuple[Union[str, None], Union[str, None]]:
        """
        Parse model name.

        Args:
            model_name (str): model name (eg. MLP, ResNey18, or MLP+ResNet18)

        Returns:
            Tuple[str, str]: MLP, CNN or Vision Transformer name
        """
        assert (model_name is not None), 'Specify model.'
        _model = model_name.split('+')  # 'MLP', 'ResNet18', 'MLP+ResNet18' -> ['MLP'], ['ResNet18'], ['MLP', 'ResNet18']
        mlp = 'MLP' if 'MLP' in _model else None
        _net = [_n for _n in _model if _n != 'MLP']
        net = _net[0] if _net != [] else None
        return mlp, net

    def _parse_gpu_ids(self, gpu_ids: str) -> List[int]:
        """
        Parse comma-separated GPU ids strings to list of integers to list of GPU ids.
        eg. '0,1,2' -> [0, 1, 2], '-1' -> []

        Args:
            gpu_ids (str): comma-separated GPU Ids

        Returns:
            List[int]: list of GPU ids
        """
        str_ids = gpu_ids.split('-') if gpu_ids != '-1' else ['-1']
        _gpu_ids = []
        for str_id in str_ids:
            id = int(str_id)
            if id >= 0:
                _gpu_ids.append(id)
        return _gpu_ids

    def _unparse_gpu_ids(self, gpu_ids_list: List[int]) -> str:
        """
        Unpasrse gpu_ids,
        ie, convert list of integers to list of GPU ids to strings of GPU ids concatenating '-'.
        eg. [0, 1, 2] -> '0-1-2', [] -> '-1'

        Args:
            gpu_ids (List[int]): list of GPU ids

        Returns:
            str : strings of GPU ids concatenating '-'
        """

        if gpu_ids_list == []:
            return '-1'
        else:
            _gpu_ids = [str(i) for i in gpu_ids_list]
            _gpu_ids = '-'.join(_gpu_ids)
            return _gpu_ids

    def _get_latest_test_datetime(self) -> Path:
        """
        Return the latest directory at training,
        which should have weight directory, in addition parameter.csv, too.

        Returns:
            str: directory path to date name like 2022-01-02-13-30-20
        """
        # eg. basesset/result/[csv_name]/sets/[datetime]/weights
        date_names = list(path for path in Path(self.args.weight_dir, 'results').glob('*/sets/*/weights'))
        latest = max(date_names, key=lambda date_name: date_name.stat().st_mtime).parent  # -> PosixPath('baseset/results/int_csv_name_1/sets/2022-09-30-15-56-60')
        return latest

    def _get_path_test_datetime(self, test_datetime: str = None) -> Path:
        """
        Return path to directory of test datetime, which is made at training,
        in which weight directory should exists, in addition parameter.csv, too.

        Args:
            test_datetime (str, optional): test datetime. Defaults to None.

        Returns:
            Path: path to directory of test datetime.
        """

        if test_datetime:
            _pattern = '*/sets/*/weights'
        else:
            _pattern = '*/sets/' + test_datetime + '*/weights'
        date_names = list(path for path in Path(self.args.weight_dir, 'results').glob(_pattern))
        latest = max(date_names, key=lambda date_name: date_name.stat().st_mtime).parent  # -> PosixPath('baseset/results/int_csv_name_1/sets/2022-09-30-15-56-60')
        return latest

    def parse(self) -> None:
        """
        Parse options.
        """
        if self.args.isTrain:
            # split path
            assert (self.args.csv_name is not None), 'Specify csv_name.'
            _csv_name = Path(self.args.baseset_dir, 'splits', self.args.csv_name)
            setattr(self.args, 'csv_name', _csv_name)

            # image directory
            if self.args.net is not None:
                assert (self.args.image_dir is not None), 'Specify image_dir.'
                _image_dir = Path(self.args.baseset_dir, 'images', self.args.image_dir)
                setattr(self.args.image_dir, 'image_dir', _image_dir)

            # model
            _mlp, _net = self._parse_model(self.args.model)
            setattr(self.args, 'mlp', _mlp)
            setattr(self.args, 'net', _net)

            # GPU IDs
            _gpu_ids = self._parse_gpu_ids(self.args.gpu_ids)
            setattr(self.args, 'gpu_ids', _gpu_ids)

        else:
            # datetime to be test, directory contaning parameter
            # path to self.args.test_datetime is used as save name of likelihood.
            if self.args.test_datetime is not None:
                _test_datetime = Path(self.args.testset_dir, 'results',  ... 'sets', self.args.test_datetime)
            else:
                _test_datetime = Path(self.args.testset_dir, 'results', ... 'sets', self._get_latest_test_datetime())
            setattr(self.args, 'test_datetime', _test_datetime)

            # weight for test
            _weight_dir = Path(self.args.weight_dir, 'results/sets', self.args.test_datetime, 'weights')
            setattr(self.args, 'weight_dir',  _weight_dir)





    def _get_args(self) -> Dict[str, Union[str, float, int]]:
        """
        Return dictionary of option name and its parameter.

        Returns:
            Dict[str, Union[str, float, int]]: dictionary of option name and its parameter
        """
        return vars(self.args)

    def print_options(self) -> None:
        """
        Print options.
        """
        ignored = [
                    'mlp',
                    'net',
                    'isTrain'
                    ]
        _args = self._get_args()
        for option in ignored:
            _args = _args.pop(option)

        phase = 'Training' if self.args.isTrain else 'Test'
        message = ''
        message += f"--------------- Options for {phase} --------------------------\n"

        for k, v in _args.items():
            comment = ''
            default = self.parser.get_default(k)
            str_default = str(default) if str(default) != '' else 'None'

            if isinstance(v, Path):
                str_v = Path(v).name
            elif str(v) != '':
                str_v = str(v)
            else:
                str_v = 'Not specified'

            if k == 'gpu_ids':
                if str_v == '[]':
                    str_v = 'CPU selected'
                else:
                    str_v = f"{str_v}  (Primary GPU:{v[0]})"

            comment = f"\t[Default: {str_default}]" if k != 'gpu_ids' else '\t[Default: CPU]'
            message += '{:>25}: {:<40}{}\n'.format(str(k), str_v, comment)

        message += '------------------------ End -------------------------------\n'
        logger.logger.info(message)

    def save_parameter(self, date_name: str) -> None:
        """
        Save parameters.

        Args:
            date_name (str): diractory name for saving
        """
        _args = self._get_args()
        no_need_to_save = ['isTrain']
        for option in no_need_to_save:
            _args = _args.pop(option)

        saved_args = dict()
        for option, parameter in _args.items():
            if option == 'gpu_ids':
                saved_args['gpu_ids'] = self._unparse_gpu_ids(parameter)
            else:
                if isinstance(parameter, Path):
                    saved_args[option] = parameter.name
                elif parameter is not None:
                    saved_args[option] = parameter
                else:
                    saved_args[option] = 'None'

        df_parameter = pd.DataFrame(saved_args.items(), columns=['option', 'parameter'])
        save_dir = Path(self.args.baseset_dir, 'results/sets', date_name)
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = Path(save_dir, 'parameter.csv')
        df_parameter.to_csv(save_path, index=False)

    def setup_parameter_for_test(self) -> None:
        """
        Set up paramters for test by aligning parameters at trainig.

        Note: self.args.weight_dir is directory not only
            in which weights are store but also parameter.csv at training.
        """
        parameter_path = Path(self.args.weight_dir, 'results/sets', self.args.test_datetime, 'parameter.csv')
        df_args = pd.read_csv(parameter_path, index_col=0)
        no_need_at_test = [
                            'criterion',
                            'optimizer',
                            'lr',
                            'epochs',
                            'batch_size',
                            'save_weight'
                            ]
        df_args = df_args.drop(no_need_at_test)

        for option, row in df_args.iterrows():
            parameter = row['parameter']

            if option == 'csv_name':
                _csv_name = Path(self.args.testset_dir, 'splits', parameter)
                setattr(self.args, 'csv_name', _csv_name)

            elif option == 'image_dir':
                _image_dir = Path(self.args.testset_dir, 'images', parameter)
                setattr(self.args, 'image_dir', _image_dir)

            elif option == 'in_channel':
                setattr(self.args, 'in_channel', int(parameter))

            elif option == 'vit_image_size':
                if parameter.isnumeric():
                    setattr(self.args, 'vit_image_size', int(parameter))
                else:
                    setattr(self.args, 'vit_image_size', None)

            elif option == 'gpu_ids':
                _gpu_ids = self._parse_gpu_ids(parameter)
                setattr(self.args, 'gpu_ids', _gpu_ids)

            else:
                if parameter == 'None':
                    setattr(self.args, option, None)
                else:
                    setattr(self.args, option, parameter)

        # The below should be 'no' when test.
        setattr(self.args, 'augmentation', 'no')
        setattr(self.args, 'sampler', 'no')


def check_train_options() -> Options:
    """
    Parse and print options.

    Returns:
        Options: Object of Options
    """
    opt = Options(isTrain=True)
    opt.parse()
    opt.print_options()
    return opt


def check_test_options() -> Options:
    """
    Parse, set up for test and print options.

    Returns:
        Options: Object of Options
    """
    opt = Options(isTrain=False)
    opt.parse()
    opt.setup_parameter_for_test()
    opt.print_options()
    return opt
