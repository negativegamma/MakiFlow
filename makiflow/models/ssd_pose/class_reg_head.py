# Copyright (C) 2020  Igor Kilbas, Danil Gribanov, Artem Mukhin
#
# This file is part of MakiFlow.
#
# MakiFlow is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MakiFlow is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Foobar.  If not, see <https://www.gnu.org/licenses/>.

from makiflow.base import MakiTensor
from makiflow.layers import ConvLayer
from makiflow.layers import ReshapeLayer
import tensorflow as tf
import numpy as np


class DCParams:
    TYPE = 'DetectorClassifier'
    NAME = 'name'
    CLASS_NUMBER = 'class_number'
    DBOXES = 'dboxes'

    REG_X_NAME = 'reg_x_name'
    RKW = 'rkw'
    RKH = 'rkh'
    RIN_F = 'rin_f'
    USE_REG_BIAS = 'use_reg_bias'
    REG_INIT_TYPE = 'reg_init_type'

    CLASS_X_NAME = 'class_x_name'
    CKW = 'ckw'
    CKH = 'ckh'
    CIN_F = 'cin_f'
    USE_CLASS_BIAS = 'use_class_bias'
    CLASS_INIT_TYPE = 'class_init_type'


class ClassRegHead:
    """
    This class represents a part of SSD algorithm. It consists of several parts:
    conv layers -> detector -> confidences + localization regression.
    """

    BBOX_OFFSET = np.array([0.5, 0.5], dtype='float32')

    def __init__(
            self,
            reg_f: MakiTensor,
            class_f: MakiTensor,
            human_indicator_f: MakiTensor,
            default_points: np.ndarray, name,
            reg_init_type='he', class_init_type='he'
    ):
        """
        Parameters
        ----------
        reg_f : MakiTensor
            Source of features for the bbox regressor.
        class_f : MakiTensor
            Source of features for the classificator.
        default_points : ndarray of shape (n_points, 2)
            Default points of the skeleton. Their coordinates (x, y) must be centered and normalized
            in the [-1, 1] interval.
        name : str or int
            Will be used as conjugation for the names of the classificator and regressor.
        """
        self._reg_f = reg_f
        self._class_f = class_f
        self._humani_f = human_indicator_f
        self._default_points = default_points
        self.name = str(name)
        self.reg_init_type = reg_init_type
        self.class_init_type = class_init_type

        self._check_dimensionality()
        self._setup_heads()
        self._make_detections()

    def _check_dimensionality(self):
        # Height and width of the feature sources must be the same
        _, CH, CW, _ = self._class_f.get_shape()
        _, RH, RW, _ = self._reg_f.get_shape()
        _, HH, HW, _ = self._humani_f.get_shape()
        msg = 'Dimensionaility of {0} and {1} are not the same. Dim of {0} is {2}, dim of {1} is {3}'
        assert CH == RH and CW == RW, msg.format('class_f', 'reg_f', (CH, CW), (RH, RW))
        assert CH == HH and CW == HW, msg.format('class_f', 'human_indicator_f', (CH, CW), (HH, HW))
        assert RH == HH and RW == HW, msg.format('reg_f', 'human_indicator_f', (RH, RW), (HH, HW))

    def _setup_heads(self):
        # SETUP CLASSIFICATION HEAD
        # Class for each point + class which indicates presence of a human in the bounding box
        n_classes = len(self._default_points)
        B, H, W, C = self._class_f.get_shape()
        self._classification_head = ConvLayer(
            kw=1, kh=1, in_f=C, out_f=n_classes,
            activation=None, padding='SAME', kernel_initializer=self.class_init_type,
            name='PointsClassifier/' + str(self.name)
        )

        # SETUP HUMAN PRESENCE INDICATOR HEAD
        # It classifies each segment of a feature map as 'has human' or 'has no human'
        B, H, W, C = self._humani_f.get_shape()
        self._human_presence_head = ConvLayer(
            kw=1, kh=1, in_f=C, out_f=1,
            activation=None, padding='SAME', kernel_initializer=self.class_init_type,
            name='PointsClassifier/' + str(self.name)
        )

        # SETUP REGRESSION HEAD
        n_points = len(self._default_points)
        B, H, W, C = self._reg_f.get_shape()
        self._regression_head = ConvLayer(
            kw=1, kh=1, in_f=C, out_f=n_points * 2,     # regression of x and y simultaneously
            activation=None, padding='SAME', kernel_initializer=self.reg_init_type,
            name='PointsRegressor/' + str(self.name)
        )

    def _make_detections(self):
        """
        Creates list with "flattened" predicted confidences and regressed localization offsets for each dbox.
        Example: [confidences, offsets]
        """
        self._classification_logits = self._classification_head(self._class_f)
        _, H, W, C = self._classification_logits.get_shape()
        self._flat_classification_logits = ReshapeLayer(new_shape=[H * W, C], name=f'{self.name}/flat_class')(
            self._classification_logits
        )

        self._human_presence_logits = self._human_presence_head(self._humani_f)
        _, H, W, C = self._human_presence_logits.get_shape()
        self._flat_human_presence_logits = ReshapeLayer(new_shape=[H * W, C], name=f'{self.name}/flat_hpi')(
            self._human_presence_logits
        )

        self._points_offsets = self._regression_head(self._reg_f)
        # Will be filled when the getter is called
        self._regressed_points_tensor = None
        self._flat_regressed_points = None

        _, H, W, _ = self._class_f.get_shape()

    def get_classification_logits_tensor(self):
        return self._flat_classification_logits.get_data_tensor()

    def get_human_presence_logits_tensor(self):
        return self._flat_human_presence_logits.get_data_tensor()

    def get_regressed_points_tensor(self, image_shape):
        """
        Applies offsets to the skeleton points and returns ready to use coordinates.

        Parameters
        ----------
        scale : tuple of two ints
            Contains width and height of the image. (width, height)

        Returns
        -------
        tf.Tensor of shape [batch_sz, n_features, n_points * 2]
            Points coordinates with applied offsets.
        """
        points = self._default_points
        B, H, W, C = self._points_offsets.get_shape()

        cell_h = H / image_shape[1]
        cell_w = W / image_shape[0]
        points_map = np.zeros((H, W, len(points), 2), dtype='float32')
        for i in range(H):
            for j in range(W):
                shift = np.array([cell_w * (j + 0.5), cell_h * (i + 0.5)])
                # Move points at the center of the (i, j) cell
                points_map[i, j] = points + shift

        points_map = points_map.reshape([1, H, W, -1])
        regressed_points_tensor = points_map + self._points_offsets.get_data_tensor()

        # In case some of the dimensions is None, we pass a -1
        if B is None:
            B = -1
            print(f'{self.name} / Batch dimension is None. Set it to -1. Full dimensionality is {(B, H, W, C)}')
        if H is None:
            H = -1
            print(f'{self.name} / Height dimension is None. Set it to -1. Full dimensionality is {(B, H, W, C)}')
        if W is None:
            W = -1
            print(f'{self.name} / Width dimension is None. Set it to -1. Full dimensionality is {(B, H, W, C)}')
        if C is None:
            C = -1
            print(f'{self.name} / Channel dimension is None. Set it to -1. Full dimensionality is {(B, H, W, C)}')

        with tf.name_scope(self.name):
            flat_regressed = tf.reshape(regressed_points_tensor, shape=[B, H*W, C])

        return flat_regressed


