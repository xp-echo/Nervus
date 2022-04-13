#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from collections import OrderedDict

import torch
import torch.nn as nn
import torchvision.models as models

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from lib import *

logger = NervusLogger.get_logger('config.model')


#model = mlp_net(label_num_classes, num_inputs)
# MLP
class MLP(nn.Module):
    def __init__(self, num_inputs, num_outputs):
        super().__init__()
        self.hidden_layers_size = [256, 256, 256]   # Hidden layers of MLP
        self.probability_dropout = 0.2
        self.num_inputs = num_inputs
        self.num_outputs = num_outputs
        self.layers_size = [self.num_inputs] + self.hidden_layers_size + [self.num_outputs]
        self.mlp = self._build()

    # Build MLP
    def _build(self):
        layers = OrderedDict()
        for i in range(len(self.layers_size)-1):
            _input_size = self.layers_size.pop(0)
            _output_size = self.layers_size[0]
            if len(self.layers_size) >=2:
                layers[str(i) + '_linear'] = nn.Linear(_input_size, _output_size)
                layers[str(i) + '_relu'] = nn.ReLU()
                layers[str(i) + '_dropout'] = nn.Dropout(self.probability_dropout)
            else:
                layers['fc'] = nn.Linear(_input_size, _output_size)   # Output layer
        return nn.Sequential(layers)

    def forward(self, inputs):
        return self.mlp(inputs)



DUMMY_LAYER = nn.Identity()  # No paramaters



# For MLP family
class MLP_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.mlp = base_model.mlp
        """
        base_model =
        MLP(
            (mlp): Sequential(
                    (0_linear): Linear(in_features=10, out_features=256, bias=True)
                    (0_relu): ReLU()
                    (0_dropout): Dropout(p=0.2, inplace=False)
                    ...
                    (fc): Linear(in_features=256, out_features=10, bias=True)
                    )
                )
        """
        self.label_num_classes = label_num_classes
        self.label_list = list(self.label_num_classes.keys())
        _prefix_layer = 'fc_'
        self.fc_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct fc layres
        _input_size_fc = self.mlp.fc.in_features
        self.fc_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Linear(_input_size_fc, num_outputs)
                            for label_name, num_outputs in self.label_num_classes.items()
                        })

        # Replace the original fc layer
        self.mlp.fc = DUMMY_LAYER

    def forward(self, inputs):
        inputs = self.mlp(inputs)
        # Fork forwarding
        output_multi = {fc_name: self.fc_multi[fc_name](inputs) for fc_name in self.fc_names}
        return output_multi


# For ResNet family
class ResNet_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.extractor = base_model
        self.label_num_classes = label_num_classes
        self.label_list = list(label_num_classes.keys())
        _prefix_layer = 'fc_'
        self.fc_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct fc layres
        self.input_size_fc = self.extractor.fc.in_features
        self.fc_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Linear(self.input_size_fc, num_outputs)
                            for label_name, num_outputs in self.label_num_classes.items()
                        })

        # Replace the original fc layer
        self.extractor.fc = DUMMY_LAYER

    def forward(self, x):
        x = self.extractor(x)
        # Fork forwarding
        output_multi = {fc_name : self.fc_multi[fc_name](x) for fc_name in self.fc_names}
        return output_multi


# For DenseNet family
class DenseNet_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.extractor = base_model
        self.label_num_classes = label_num_classes
        self.label_list = list(label_num_classes.keys())
        _prefix_layer = 'fc_'
        self.fc_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct fc layres
        self.input_size_fc = self.extractor.classifier.in_features
        self.fc_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Linear(self.input_size_fc, num_outputs)
                            for label_name, num_outputs in self.label_num_classes.items()
                        })

        # Replace the original fc layer
        self.extractor.classifier = DUMMY_LAYER

    def forward(self, x):
        x = self.extractor(x)
        # Fork forwarding
        output_multi = {fc_name : self.fc_multi[fc_name](x) for fc_name in self.fc_names}
        return output_multi


# For EfficientNet family
class EfficientNet_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.extractor = base_model
        self.label_num_classes = label_num_classes
        self.label_list = list(label_num_classes.keys())
        _prefix_layer = 'block_'
        self.block_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct fc layres
        """"
        (classifier): Sequential(
                        (0): Dropout(p=0.2, inplace=True)                             # p changes by variants
                        (1): Linear(in_features=1280, out_features=1000, bias=True)   # in_features changes by variants
                        )
        """
        _probability_dropout = self.extractor.classifier[0].p
        _input_size_fc = self.extractor.classifier[1].in_features
        # Note: If inplace=True of nn.Dropout, cannot backword, because gradients are deleted bue to inplace
        self.fc_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Sequential(
                                                                OrderedDict([
                                                                ('0_' + label_name, nn.Dropout(p=_probability_dropout, inplace=False)),
                                                                ('1_' + label_name, nn.Linear(_input_size_fc, num_outputs))
                                                            ]))
                                                            for label_name, num_outputs in self.label_num_classes.items()
                        })

        # Replace the original classifier
        self.extractor.classifier = DUMMY_LAYER

    def forward(self, x):
       x = self.extractor(x)
       # Fork forwarding
       output_multi = {block_name: self.fc_multi[block_name](x) for block_name in self.block_names}
       return output_multi



# For ConvNeXt family
class ConvNeXt_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.extractor = base_model
        self.label_num_classes = label_num_classes
        self.label_list = list(label_num_classes.keys())
        _prefix_layer = 'block_'
        self.block_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct fc layres
        """"
        (classifier): Sequential(
                        (0): LayerNorm2d((768,), eps=1e-06, elementwise_affine=True)   # models.convnext.LayerNorm2d
                        (1): Flatten(start_dim=1, end_dim=-1)
                        (2): Linear(in_features=768, out_features=1000, bias=True)
                    )
        """
        _input_size_fc = self.extractor.classifier[2].in_features
        self.fc_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Sequential(
                                                                OrderedDict([
                                                                ('0_'+label_name, self.extractor.classifier[0]),    # copy
                                                                ('1_'+label_name, self.extractor.classifier[1]),    # copy
                                                                ('2_'+label_name, nn.Linear(_input_size_fc, num_outputs))
                                                            ]))
                                                            for label_name, num_outputs in self.label_num_classes.items()
                        })

        # Replace the original classifier
        self.extractor.classifier = DUMMY_LAYER

    def forward(self, x):
        x = self.extractor(x)
        # Fork forwarding
        output_multi = {block_name: self.fc_multi[block_name](x) for block_name in self.block_names}
        return output_multi



# For ViT family
class ViT_Multi(nn.Module):
    def __init__(self, base_model, label_num_classes):
        super().__init__()
        self.extractor = base_model
        self.label_num_classes = label_num_classes
        self.label_list = list(label_num_classes.keys())
        _prefix_layer = 'heads_'
        self.head_names = [(_prefix_layer + label_name) for label_name in self.label_list]

        # Construct multi head
        """
        (heads): Sequential(
                    (head): Linear(in_features=768, out_features=1000, bias=True)
                )
        """
        _input_size_fc = self.extractor.heads.head.in_features
        self.head_multi = nn.ModuleDict({
                            (_prefix_layer + label_name) : nn.Sequential(
                                                            OrderedDict([
                                                                ('head' ,nn.Linear(_input_size_fc, num_outputs))
                                                            ]))
                                                            for label_name, num_outputs in self.label_num_classes.items()
                            })

        # Replace the original heads
        self.extractor.heads = DUMMY_LAYER

    def forward(self, x):
        x = self.extractor(x)
        # Fork forwarding
        output_multi = {head_name : self.head_multi[head_name](x) for head_name in self.head_names}
        return output_multi


def mlp_net(num_inputs, label_num_classes):
    label_list = list(label_num_classes.keys())
    num_outputs_first_label = label_num_classes[label_list[0]]
    mlp_base = MLP(num_inputs, num_outputs_first_label)   # Once make MLP with the first label only
    if len(label_list) > 1:
        mlp = MLP_Multi(mlp_base, label_num_classes)  # Make it multi
    else:
        mlp = mlp_base
    return mlp


# Note:
# Supposed that CNN includes ViT.
def conv_net(cnn_name, label_num_classes):
    if cnn_name == 'B0':
        cnn = models.efficientnet_b0

    elif cnn_name == 'B2':
        cnn = models.efficientnet_b2

    elif cnn_name == 'B4':
        cnn = models.efficientnet_b4

    elif cnn_name == 'B6':
        cnn = models.efficientnet_b6

    elif cnn_name == 'ResNet18':
        cnn = models.resnet18

    elif cnn_name == 'ResNet':
        cnn = models.resnet50

    elif cnn_name == 'DenseNet':
        cnn = models.densenet161

    elif cnn_name == 'ConvNeXtTiny':
        cnn = models.convnext_tiny

    elif cnn_name == 'ConvNeXtSmall':
        cnn = models.convnext_small
    
    elif cnn_name == 'ConvNeXtBase':
        cnn = models.convnext_base

    elif cnn_name == 'ConvNeXtLarge':
        cnn = models.convnext_large
        
    elif cnn_name == 'ViTb16':
        cnn = models.vit_b_16

    elif cnn_name == 'ViTb32':
        cnn = models.vit_b_32

    elif cnn_name == 'ViTl16':
        cnn = models.vit_l_16

    elif cnn_name == 'ViTl32':
        cnn = models.vit_l_32

    else:
        logger.error(f"No specified such CNN or ViT: {cnn_name}.")

    # Single-label output or Multi-label output
    label_list = list(label_num_classes.keys())
    if len(label_list) > 1 :
        # When CNN only -> make multi
        if cnn_name.startswith('ResNet'):
            cnn = ResNet_Multi(cnn(), label_num_classes)

        elif cnn_name.startswith('B'):
            cnn = EfficientNet_Multi(cnn(), label_num_classes)

        elif cnn_name.startswith('DenseNet'):
            cnn = DenseNet_Multi(cnn(), label_num_classes)

        elif cnn_name.startswith('ConvNeXt'):
            cnn = ConvNeXt_Multi(cnn(), label_num_classes)

        elif cnn_name.startswith('ViT'):
            cnn = ViT_Multi(cnn(), label_num_classes)

        else:
            logger.error(f"Cannot make multi: {cnn_name}.")

    else:
        # When Single-label output or MLP+CNN
        num_outputs_first_label = label_num_classes[label_list[0]]
        cnn = cnn(num_classes=num_outputs_first_label)
    return cnn



# MLP+CNN
class MLPCNN_Net(nn.Module):
    def __init__(self, cnn_name, num_inputs, label_num_classes):
        super().__init__()
        self.num_inputs = num_inputs    # Not include image
        self.label_num_classes = label_num_classes
        self.label_list = list(self.label_num_classes.keys())
        self.cnn_name = cnn_name
        self.cnn_num_outputs_pass_to_mlp = 1   # only POSITIVE value is passed to MLP.
        self.mlp_cnn_num_inputs = self.num_inputs + self.cnn_num_outputs_pass_to_mlp
        self.dummy_label_num_classes = {'dummy_label': len(['pred_n_label_x', 'pred_p_label_x'])}   # Before passing to MLP, do binary classification

        self.cnn = conv_net(self.cnn_name, self.dummy_label_num_classes)   # Non multi-label output
        self.mlp = mlp_net(self.mlp_cnn_num_inputs, self.label_num_classes)

    def normalize_cnn_output(self, outputs_cnn):
        # Note: Cannot use sklearn.preprocessing.MinMaxScaler() because sklearn does not support GPU.
        max = outputs_cnn.max()
        min = outputs_cnn.min()
        if min == max:
            outputs_cnn_normed = outputs_cnn - min   # ie. outputs_cnn_normed = 0
        else:
            outputs_cnn__normed = (outputs_cnn - min) / (max - min)
        return outputs_cnn_normed

    def forward(self, inputs, images):
        outputs_cnn = self.cnn(images)                                # [64, 256, 256]  -> [64, 2]  batch_size=64

        # Select likelihood of '1'
        outputs_cnn = outputs_cnn[:, self.cnn_num_outputs_pass_to_mlp]   # [64, 2] -> Numpy [64]
        outputs_cnn = outputs_cnn.reshape(len(outputs_cnn), 1)           # Numpy [64] -> Numpy [64, 1]

        # Normalize
        outputs_cnn_normed = self.normalize_cnn_output(outputs_cnn)      # Numpy [64, 1] -> Tensor [64, 1] Normalize bach_size-wise

        # Merge inputs with output from CNN
        inputs_images = torch.cat((inputs, outputs_cnn_normed), dim=1)   # Tensor [64, 24] + Tensor [64, 1] -> Tensor [64, 24+1]
        outputs = self.mlp(inputs_images)
        return outputs



def create_mlp_cnn(mlp, cnn, num_inputs, label_num_classes, gpu_ids=[]):
    """
    num_input: number of inputs of MLP or MLP+CNN
    eg. label_num_classes = {'internal_label_0': 2, 'internal_label_1': 2, 'internal_label_': 2}
    """
    if (mlp is not None) and (cnn is None):
        # When MLP only
        model = mlp_net(num_inputs, label_num_classes)
    elif (mlp is None) and (cnn is not None):
        # When CNN only
        model = conv_net(cnn, label_num_classes)
    else:
        # When MLP+CNN
        # Set the number of outputs from CNN to MLP as 1, then
        # the shape of outputs from CNN is resized to [batgch_size, 1].
        model = MLPCNN_Net(cnn, num_inputs, label_num_classes)

    device = set_device(gpu_ids)
    model.to(device)
    if gpu_ids:
        model = torch.nn.DataParallel(model, gpu_ids)
    else:
        pass
    return model


# Extract outputs of label_name
def get_layer_output(outputs_multi, label_name):
    output_layer_names = outputs_multi.keys()
    layer_name = [output_layer_name for output_layer_name in output_layer_names if output_layer_name.endswith(label_name)][0]
    output_layer = outputs_multi[layer_name]
    return output_layer


def predict_by_model(model, hasMLP, hasCNN, device, inputs_values_normed, images) -> torch.Tensor:
    if hasMLP and hasCNN: # elif not(mlp is None) and not(cnn is None):
    # When MLP+CNN
        inputs_values_normed = inputs_values_normed.to(device)
        images = images.to(device)
        outputs = model(inputs_values_normed, images)
    elif hasMLP:
    # When MLP only
        inputs_values_normed = inputs_values_normed.to(device)
        outputs = model(inputs_values_normed)
    elif hasCNN:
    # When CNN only
        images = images.to(device)
        outputs = model(images)

    return outputs
