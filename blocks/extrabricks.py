"""The interface of bricks and some simple implementations."""
import logging

import numpy
from six import add_metaclass
from theano import tensor
from theano.sandbox.rng_mrg import MRG_RandomStreams
from toolz import interleave
from picklable_itertools.extras import equizip

from blocks.config import config
from blocks.bricks.base import application, _Brick, Brick, lazy
from blocks.roles import add_role, WEIGHT, BIAS
from blocks.utils import pack, shared_floatx_nans

logger = logging.getLogger(__name__)


class Random(Brick):
    """A mixin class for Bricks which need Theano RNGs.

    Parameters
    ----------
    theano_seed : int or list, optional
        Seed to use for a
        :class:`~theano.sandbox.rng_mrg.MRG_RandomStreams` object.

    """
    seed_rng = numpy.random.RandomState(config.default_seed)

    def __init__(self, theano_seed=None, **kwargs):
        super(Random, self).__init__(**kwargs)
        self.theano_seed = theano_seed

    @property
    def theano_seed(self):
        if getattr(self, '_theano_seed', None) is not None:
            return self._theano_seed
        else:
            self._theano_seed = self.seed_rng.randint(
                numpy.iinfo(numpy.int32).max)
            return self._theano_seed

    @theano_seed.setter
    def theano_seed(self, value):
        if hasattr(self, '_theano_seed'):
            raise AttributeError("seed already set")
        self._theano_seed = value

    @property
    def theano_rng(self):
        """Returns Brick's Theano RNG, or a default one.

        The default seed can be set through ``blocks.config``.

        """
        if not hasattr(self, '_theano_rng'):
            self._theano_rng = MRG_RandomStreams(self.theano_seed)
        return self._theano_rng

    @theano_rng.setter
    def theano_rng(self, theano_rng):
        self._theano_rng = theano_rng


class Initializable(Brick):
    """Base class for bricks which push parameter initialization.

    Many bricks will initialize children which perform a linear
    transformation, often with biases. This brick allows the weights
    and biases initialization to be configured in the parent brick and
    pushed down the hierarchy.

    Parameters
    ----------
    weights_init : object
        A `NdarrayInitialization` instance which will be used by to
        initialize the weight matrix. Required by
        :meth:`~.Brick.initialize`.
    biases_init : :obj:`object`, optional
        A `NdarrayInitialization` instance that will be used to initialize
        the biases. Required by :meth:`~.Brick.initialize` when `use_bias`
        is `True`. Only supported by bricks for which :attr:`has_biases` is
        ``True``.
    use_bias : :obj:`bool`, optional
        Whether to use a bias. Defaults to `True`. Required by
        :meth:`~.Brick.initialize`. Only supported by bricks for which
        :attr:`has_biases` is ``True``.
    rng : :class:`numpy.random.RandomState`

    Attributes
    ----------
    has_biases : bool
        ``False`` if the brick does not support biases, and only has
        :attr:`weights_init`.  For an example of this, see
        :class:`.Bidirectional`. If this is ``False``, the brick does not
        support the arguments ``biases_init`` or ``use_bias``.

    """
    has_biases = True
    seed_rng = numpy.random.RandomState(config.default_seed)

    @lazy()
    def __init__(self, weights_init=None, biases_init=None, use_bias=True,
                 seed=None, **kwargs):
        super(Initializable, self).__init__(**kwargs)
        self.weights_init = weights_init
        if self.has_biases:
            self.biases_init = biases_init
        elif biases_init is not None or not use_bias:
            raise ValueError("This brick does not support biases config")
        self.use_bias = use_bias
        self.seed = seed

    @property
    def seed(self):
        if getattr(self, '_seed', None) is not None:
            return self._seed
        else:
            self._seed = self.seed_rng.randint(
                numpy.iinfo(numpy.int32).max)
            return self._seed

    @seed.setter
    def seed(self, value):
        if hasattr(self, '_seed'):
            raise AttributeError("seed already set")
        self._seed = value

    @property
    def rng(self):
        if getattr(self, '_rng', None) is not None:
            return self._rng
        else:
            self._rng = numpy.random.RandomState(self.seed)
            return self._rng

    @rng.setter
    def rng(self, rng):
        self._rng = rng

    def _push_initialization_config(self):
        for child in self.children:
            if isinstance(child, Initializable):
                child.rng = self.rng
                if self.weights_init:
                    child.weights_init = self.weights_init
        if hasattr(self, 'biases_init') and self.biases_init:
            for child in self.children:
                if (isinstance(child, Initializable) and
                        hasattr(child, 'biases_init')):
                    child.biases_init = self.biases_init


class Feedforward(Brick):
    """Declares an interface for bricks with one input and one output.

    Many bricks have just one input and just one output (activations,
    :class:`Linear`, :class:`MLP`). To make such bricks interchangable
    in most contexts they should share an interface for configuring
    their input and output dimensions. This brick declares such an
    interface.

    Attributes
    ----------
    input_dim : int
        The input dimension of the brick.
    output_dim : int
        The output dimension of the brick.

    """
    def __getattr__(self, name):
        message = ("'{}' object does not have an attribute '{}'"
                   .format(self.__class__.__name__, name))
        if name in ('input_dim', 'output_dim'):
            message += (" (which is a part of 'Feedforward' interface it"
                        " claims to support)")
        raise AttributeError(message)


class Linear(Initializable, Feedforward):
    r"""A linear transformation with optional bias.

    Linear brick which applies a linear (affine) transformation by
    multiplying the input with a weight matrix. Optionally a bias is added.

    Parameters
    ----------
    input_dim : int
        The dimension of the input. Required by :meth:`~.Brick.allocate`.
    output_dim : int
        The dimension of the output. Required by :meth:`~.Brick.allocate`.

    Notes
    -----
    See :class:`Initializable` for initialization parameters.

    A linear transformation with bias is a matrix multiplication followed
    by a vector summation.

    .. math:: f(\mathbf{x}) = \mathbf{W}\mathbf{x} + \mathbf{b}

    """
    @lazy(allocation=['input_dim', 'output_dim'])
    def __init__(self, input_dim, output_dim, **kwargs):
        super(Linear, self).__init__(**kwargs)
        self.input_dim = input_dim
        self.output_dim = output_dim

    @property
    def W(self):
        return self.params[0]

    @property
    def b(self):
        return self.params[1]

    def _allocate(self):
        W = shared_floatx_nans((self.input_dim, self.output_dim), name='W')
        add_role(W, WEIGHT)
        self.params.append(W)
        self.add_auxiliary_variable(W.norm(2), name='W_norm')
        if self.use_bias:
            b = shared_floatx_nans((self.output_dim,), name='b')
            add_role(b, BIAS)
            self.params.append(b)
            self.add_auxiliary_variable(b.norm(2), name='b_norm')

    def _initialize(self):
        if self.use_bias:
            W, b = self.params
            self.biases_init.initialize(b, self.rng)
        else:
            W, = self.params
        self.weights_init.initialize(W, self.rng)

    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        """Apply the linear transformation.

        Parameters
        ----------
        input_ : :class:`~tensor.TensorVariable`
            The input on which to apply the transformation

        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            The transformed input plus optional bias

        """
        if self.use_bias:
            W, b = self.params
        else:
            W, = self.params
        output = tensor.dot(input_, W)
        if self.use_bias:
            output += b
        return output

    def get_dim(self, name):
        if name == 'input_':
            return self.input_dim
        if name == 'output':
            return self.output_dim
        super(Linear, self).get_dim(name)


class Bias(Feedforward, Initializable):
    """Add a bias (i.e. sum with a vector)."""
    @lazy(allocation=['dim'])
    def __init__(self, dim, **kwargs):
        super(Bias, self).__init__(**kwargs)
        self.dim = dim

    def _allocate(self):
        b = shared_floatx_nans((self.output_dim,), name='b')
        add_role(b, BIAS)
        self.params.append(b)

    def _initialize(self):
        b, = self.params
        self.biases_init.initialize(b, self.rng)

    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        """Apply the linear transformation.

        Parameters
        ----------
        input_ : :class:`~tensor.TensorVariable`
            The input on which to apply the transformation

        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            The transformed input plus optional bias

        """
        b, = self.params
        return input_ + b

    def get_dim(self, name):
        if name in ['input_', 'output']:
            return self.dim
        super(Linear, self).get_dim(name)

    def _get_dim(self):
        return self.dim

    def _set_dim(self, value):
        self.dim = value

    input_dim = output_dim = property(_get_dim, _set_dim)


class Maxout(Brick):
    """Maxout pooling transformation.

    A brick that does max pooling over groups of input units. If you use
    this code in a research project, please cite [GWFM13]_.

    .. [GWFM13] Ian J. Goodfellow, David Warde-Farley, Mehdi Mirza, Aaron
       Courville, and Yoshua Bengio, *Maxout networks*, ICML (2013), pp.
       1319-1327.

    Parameters
    ----------
    num_pieces : int
        The size of the groups the maximum is taken over.

    Notes
    -----
    Maxout applies a set of linear transformations to a vector and selects
    for each output dimension the result with the highest value.

    """
    @lazy(allocation=['num_pieces'])
    def __init__(self, num_pieces, **kwargs):
        super(Maxout, self).__init__(**kwargs)
        self.num_pieces = num_pieces

    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        """Apply the maxout transformation.

        Parameters
        ----------
        input_ : :class:`~tensor.TensorVariable`
            The input on which to apply the transformation

        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            The transformed input

        """
        last_dim = input_.shape[-1]
        output_dim = last_dim // self.num_pieces
        new_shape = ([input_.shape[i] for i in range(input_.ndim - 1)] +
                     [output_dim, self.num_pieces])
        output = tensor.max(input_.reshape(new_shape, ndim=input_.ndim + 1),
                            axis=input_.ndim)
        return output


class LinearMaxout(Initializable, Feedforward):
    """Maxout pooling following a linear transformation.

    This code combines the :class:`Linear` brick with a :class:`Maxout`
    brick.

    Parameters
    ----------
    input_dim : int
        The dimension of the input. Required by :meth:`~.Brick.allocate`.
    output_dim : int
        The dimension of the output. Required by :meth:`~.Brick.allocate`.
    num_pieces : int
        The number of linear functions. Required by
        :meth:`~.Brick.allocate`.

    Notes
    -----
    See :class:`Initializable` for initialization parameters.

    """
    @lazy(allocation=['input_dim', 'output_dim', 'num_pieces'])
    def __init__(self, input_dim, output_dim, num_pieces, **kwargs):
        super(LinearMaxout, self).__init__(**kwargs)
        self.linear = Linear()
        self.maxout = Maxout()
        self.children = [self.linear,
                         self.maxout]

        self.input_dim = input_dim
        self.output_dim = output_dim
        self.num_pieces = num_pieces

    @property
    def input_dim(self):
        return self.linear.input_dim

    @input_dim.setter
    def input_dim(self, value):
        self.linear.input_dim = value

    def _push_allocation_config(self):
        self.linear.output_dim = self.output_dim * self.num_pieces
        self.maxout.num_pieces = self.num_pieces

    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        """Apply the linear transformation followed by maxout.

        Parameters
        ----------
        input_ : :class:`~tensor.TensorVariable`
            The input on which to apply the transformations

        Returns
        -------
        output : :class:`~tensor.TensorVariable`
            The transformed input

        """
        pre_activation = self.linear.apply(input_)
        output = self.maxout.apply(pre_activation)
        return output


class ActivationDocumentation(_Brick):
    """Dynamically adds documentation to activations.

    Notes
    -----
    See http://bugs.python.org/issue12773.

    """
    def __new__(cls, name, bases, classdict):
        classdict['__doc__'] = \
            """Elementwise application of {0} function.""".format(name.lower())
        if 'apply' in classdict:
            classdict['apply'].__doc__ = \
                """Apply the {0} function element-wise.

                Parameters
                ----------
                input_ : :class:`~tensor.TensorVariable`
                    Theano variable to apply {0} to, element-wise.

                Returns
                -------
                output : :class:`~tensor.TensorVariable`
                    The input with the activation function applied.

                """.format(name.lower())
        return super(ActivationDocumentation, cls).__new__(cls, name, bases,
                                                           classdict)


@add_metaclass(ActivationDocumentation)
class Activation(Brick):
    """A base class for simple, element-wise activation functions.

    This base class ensures that activation functions are automatically
    documented using the :class:`ActivationDocumentation` metaclass.

    """
    pass


class SoftRectifier(Activation):
    @application(inputs=['input_'], outputs=['output'])
    def apply(self, input_):
        thresh = 1.1
        return tensor.log(1 + tensor.exp(input_ - thresh))