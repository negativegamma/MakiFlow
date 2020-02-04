from __future__ import absolute_import
import tensorflow as tf
from makiflow.generators.pipeline.gen_base import GenLayer
from makiflow.generators.segmentator.map_methods import SegmentIterator
from makiflow.generators.segmentator.pathgenerator import SegmentPathGenerator
from makiflow.generators.pipeline.map_method import MapMethod


class InputGenLayer(GenLayer):
    def __init__(
            self, prefetch_size, batch_size, path_generator: SegmentPathGenerator, name,
            map_operation: MapMethod, num_parallel_calls=None
    ):
        """

        Parameters
        ----------
        prefetch_size : int
            Number of batches to prepare before feeding into the network.
        batch_size : int
            The batch size.
        path_generator : makiflow.generators.segmentation.pathgenerator.SegmentPathGenerator
            The path generator.
        name : str
            Name of the input layer of the model. You can find it in the
            architecture file.
        map_operation : MapMethod
            Method for mapping paths to the actual data.
        num_parallel_calls : int
            Represents the number of elements to process asynchronously in parallel.
            If not specified, elements will be processed sequentially.
        """
        self.prefetch_size = prefetch_size
        self.batch_size = batch_size
        self.iterator = self.build_iterator(path_generator, map_operation, num_parallel_calls)
        super().__init__(
            name=name,
            input_tensor=self.iterator[SegmentIterator.IMAGE]
        )

    def build_iterator(self, gen: SegmentPathGenerator, map_operation: MapMethod, num_parallel_calls):
        dataset = tf.data.Dataset.from_generator(
            gen.next_element,
            output_types={
                SegmentPathGenerator.IMAGE: tf.string,
                SegmentPathGenerator.MASK: tf.string
            }
        )

        dataset = dataset.map(map_func=map_operation.load_data, num_parallel_calls=num_parallel_calls)
        # Set `drop_remainder` to True since otherwise the batch dimension
        # would be None. Example: [None, 1024, 1024, 3]
        dataset = dataset.batch(self.batch_size, drop_remainder=True)
        dataset = dataset.prefetch(self.prefetch_size)
        iterator = dataset.make_one_shot_iterator()
        return iterator.get_next()

    def get_iterator(self):
        return self.iterator
