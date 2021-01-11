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

from __future__ import absolute_import

import tensorflow as tf
import numpy as np
from tqdm import tqdm
from makiflow.core import MakiTensor, MakiBuilder, MakiModel
from makiflow.layers import InputLayer
from .core import RegressorInterface
from makiflow.generators import data_iterator
EPSILON = np.float32(1e-37)


class Regressor(RegressorInterface):
    INPUT = 'in_x'
    OUTPUT = 'out_x'
    NAME = 'name'

    @staticmethod
    def from_json(path: str, input_tensor: MakiTensor = None):
        """Creates and returns ConvModel from json.json file contains its architecture"""
        model_info, graph_info = MakiModel.load_architecture(path)

        output_tensor_name = model_info[Regressor.OUTPUT]
        input_tensor_name = model_info[Regressor.INPUT]
        model_name = model_info[Regressor.NAME]

        inputs_outputs = MakiBuilder.restore_graph([output_tensor_name], graph_info)
        out_x = inputs_outputs[output_tensor_name]
        in_x = inputs_outputs[input_tensor_name]
        print('Model is restored!')
        return Regressor(in_x=in_x, out_x=out_x, name=model_name)

    def __init__(self, in_x: InputLayer, out_x: MakiTensor, name='MakiClassificator'):
        """
        A classifier model.

        Parameters
        ----------
        in_x : MakiTensor
            Input layer.
        out_x : MakiTensor
            Output layer (logits(.
        name : str
            Name of the model.
        """
        self._input = in_x
        self._output = out_x
        super().__init__([out_x], [in_x])
        self.name = str(name)
        self._init_inference()

    def _init_inference(self):
        self._batch_sz = self._input.get_shape()[0]
        self._tf_input = self._input.get_data_tensor()
        self._tf_logits = self._output.get_data_tensor()

    def get_logits(self):
        return self._output

    def get_feed_dict_config(self) -> dict:
        return {
            self._input: 0
        }

    def _get_model_info(self):
        return {
            Regressor.INPUT: self._input.get_name(),
            Regressor.OUTPUT: self._output.get_name(),
            Regressor.NAME: self.name
        }

    def predict(self, Xtest):
        """
        Performs prediction on the given data.

        Parameters
        ----------
        Xtest : arraylike of shape [n, ...]
            The input data.

        Returns
        -------
        arraylike
            Predictions.

        """
        out = self._tf_logits
        batch_size = self._batch_sz if self._batch_sz is not None else 1
        predictions = []
        for Xbatch in tqdm(data_iterator(Xtest, batch_size=batch_size)):
            predictions += [self._session.run(out, feed_dict={self._tf_input: Xbatch})]
        predictions = np.concatenate(predictions, axis=0)
        return predictions[:len(Xtest)]

    def evaluate(self, Xtest, Ytest):
        """
        Computes mean absolute error between predictions and labels.

        Parameters
        ----------
        Xtest : ndarray
            Test input data.
        Ytest : ndarray
            Test labels.

        Returns
        -------
        float
            Mean absolute error.
        """
        assert len(Xtest) == len(Ytest), 'Number of labels must be equal to the number of data points,' \
                                         f'but received ndata={len(Xtest)} and nlabels={len(Ytest)}'
        preds = self.predict(Xtest)
        loss = np.mean(np.abs(preds - Ytest))
        return loss

