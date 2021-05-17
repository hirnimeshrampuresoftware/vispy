# -*- coding: utf-8 -*-
# Copyright (c) Vispy Development Team. All Rights Reserved.
# Distributed under the (new) BSD License. See LICENSE.txt for more info.
import warnings

import numpy as np

from vispy.gloo import Texture2D, Texture3D
from vispy.gloo.texture import should_cast_to_f32


class _ScaledTextureMixin:
    """Mixin class to make a texture aware of color limits.

    This class contains the shared functionality for the CPU and GPU mixin
    classes below. In some cases this class provides a "generic"
    implementation of a specific method and is then overridden by one of the
    subclasses.

    """

    def __init__(self, data=None, **texture_kwargs):
        self._clim = None
        self._data_dtype = None
        data, texture_kwargs = self.init_scaling_texture(data, **texture_kwargs)
        # Call the __init__ of the TextureXD class
        super().__init__(data, **texture_kwargs)

    def init_scaling_texture(self, data=None, format=None, internalformat=None, **texture_kwargs):
        """Initialize scaling properties and create a representative array."""
        self._data_dtype = getattr(data, 'dtype', None)
        data = self._create_rep_array(data, format)
        internalformat = self._get_texture_format_for_data(
            data,
            format,
            internalformat)
        texture_kwargs['internalformat'] = internalformat
        return data, texture_kwargs

    def _get_texture_format_for_data(self, data, format, internalformat):
        return internalformat

    @property
    def clim(self):
        """Color limits of the texture's data."""
        return self._clim

    def set_clim(self, clim):
        """Set clim and return if a texture update is needed."""
        need_texture_upload = False
        if isinstance(clim, str):
            if clim != 'auto':
                raise ValueError('clim must be "auto" if a string')
            need_texture_upload = True
            self._clim = clim
        else:
            try:
                cmin, cmax = clim
            except (ValueError, TypeError):
                raise ValueError('clim must have two elements')
            self._clim = (cmin, cmax)
        return need_texture_upload

    @property
    def clim_normalized(self):
        """Normalize current clims to match texture data inside the shader.

        Scaling only happens on the GPU so we only normalize
        the color limits when needed (for unsigned normalized integer
        internal formats). Otherwise, for internal formats that are not
        normalized such as floating point (ex. r32f) we can leave the ``clim``
        as is.

        """
        # if the internalformat of the texture is normalized we need to
        # also normalize the clims so they match in-shader
        clim_min = self.normalize_value(self.clim[0], self._data_dtype)
        clim_max = self.normalize_value(self.clim[1], self._data_dtype)
        return clim_min, clim_max

    @property
    def is_normalized(self):
        """Whether the in-shader representation of this texture is normalized or not.

        Formats ending in 'f' (float), 'ui' (unsigned integral), or 'i'
        (integral) are not normalized in the GPU. Formats ending in "_snorm"
        are normalized on the range [-1, 1] based on the data type of the
        input data (ex. 0-255 for uint8). Formats with no data type suffix are
        normalized on the range [0, 1]. See
        https://www.khronos.org/opengl/wiki/Image_Format for more information.

        This property can be used to determine if input shader variables
        (uniforms, template variables) need to also be normalized. See
        :meth:`~BaseTexture.normalize_value` below.

        """
        if self.internalformat is None:
            return True
        return self.internalformat[-1] not in ('f', 'i')

    def normalize_value(self, val, input_data_dtype):
        """Normalize values to match in-shader representation of this shader.

        Parameters
        ----------
        val : int | float | ndarray
            Value(s) to normalize.
        input_data_dtype : numpy.dtype
            Data type of input data. The assumption is that the provided
            values to be normalized are in the same range as the input
            texture data and must be normalized in the same way.

        """
        if not self.is_normalized:
            return val
        dtype_info = np.iinfo(input_data_dtype)
        dmin = dtype_info.min
        dmax = dtype_info.max
        val = (val - dmin) / (dmax - dmin)
        # XXX: Do we need to handle _snorm differently?
        #  Not currently supported in vispy.
        return val

    def _data_num_channels(self, data, format=None):
        if format == 'luminance':
            num_channels = 1
        elif data is not None:
            # Ex. (M, N, 3) in Texture2D (ndim=2) -> 3 channels
            num_channels = data.shape[-1] if data.ndim == self._ndim + 1 else 1
        else:
            num_channels = 4
        return num_channels

    def _create_rep_array(self, data, format=None):
        """Get a representative array with an initial shape.

        Data will be filled in and the texture resized later.

        """
        dtype = getattr(data, 'dtype', np.float32)
        num_channels = self._data_num_channels(data, format)
        init_shape = (10,) * self._ndim + (num_channels,)
        return np.zeros(init_shape).astype(dtype)

    def check_data_format(self, data):
        """Check if provided data will cause issues if set later."""
        # this texture type has no limitations
        return

    def _get_default_clims(self, data):
        """Get min and max color limits."""
        # assume floating point data is pre-normalized to 0 and 1
        if np.issubdtype(data.dtype, np.floating):
            return 0, 1
        # assume integer RGBs fill the whole data space
        dtype_info = np.iinfo(data.dtype)
        dmin = dtype_info.min
        dmax = dtype_info.max
        return dmin, dmax

    def scale_and_set_data(self, data, offset=None, copy=False):
        """Upload new data to the GPU."""
        return self.set_data(data, offset=offset, copy=copy)


class CPUScaledTextureMixIn(_ScaledTextureMixin):
    """Texture mixin class for smarter scaling decisions.

    This class wraps the logic to normalize data on the CPU before sending
    it to the GPU (the texture). Pre-scaling on the CPU can be helpful in
    cases where OpenGL 2/ES requirements limit the texture storage to an
    8-bit normalized integer internally.

    This class includes optimizations where image data is not re-normalized
    if the previous normalization can still be used to visualize the data
    with the new color limits.

    This class should only be used internally. For similar features where
    scaling occurs on the GPU see
    :class:`vispy.visuals._scalable_textures.GPUScaledTextureMixin`.

    To use this mixin, a subclass should be created to combine this mixin with
    the texture class being used. Existing subclasses already exist in this
    module. Note that this class **must** appear first in the subclass's parent
    classes so that its ``__init__`` method is called instead of the parent
    Texture class.

    """

    def __init__(self, data=None, **texture_kwargs):
        self._data_limits = None
        # Call the __init__ of the mixin base class
        super().__init__(data, **texture_kwargs)

    def _clim_outside_data_limits(self, cmin, cmax):
        if self._data_limits is None:
            return False
        return cmin < self._data_limits[0] or cmax > self._data_limits[1]

    def set_clim(self, clim):
        """Set clim and return if a texture update is needed."""
        need_texture_upload = False
        # NOTE: Color limits are not checked against data type limits
        if isinstance(clim, str):
            if clim != 'auto':
                raise ValueError('clim must be "auto" if a string')
            need_texture_upload = True
            self._clim = clim
        else:
            try:
                cmin, cmax = clim
            except (ValueError, TypeError):
                raise ValueError('clim must have two elements')
            if self._clim_outside_data_limits(cmin, cmax):
                need_texture_upload = True
            self._clim = (cmin, cmax)
        return need_texture_upload

    @property
    def clim_normalized(self):
        """Normalize current clims to match texture data inside the shader.

        If data is scaled on the CPU then the texture data will be in the range
        0-1 in the _build_texture() method. Inside the fragment shader the
        final contrast adjustment will be applied based on this normalized
        ``clim``.

        """
        range_min, range_max = self._data_limits
        clim_min, clim_max = self.clim
        clim_min = (clim_min - range_min) / (range_max - range_min)
        clim_max = (clim_max - range_min) / (range_max - range_min)
        return clim_min, clim_max

    @staticmethod
    def _scale_data_on_cpu(data, clim, copy=True):
        if copy:
            should_cast_to_f32(data.dtype)
            data = np.array(data, dtype=np.float32, copy=copy)
        elif not copy and not np.issubdtype(data.dtype, np.floating):
            raise ValueError("Data must be of floating type for no copying to occur.")

        if clim[0] == clim[1]:
            if clim[0] != 0:
                data /= clim[0]
        else:
            data -= clim[0]
            data /= clim[1] - clim[0]
        if should_cast_to_f32(data.dtype):
            data = data.astype(np.float32)
        return data

    def scale_and_set_data(self, data, offset=None, copy=True):
        """Upload new data to the GPU, scaling if necessary."""
        self._data_dtype = data.dtype

        clim = self._clim
        is_auto = isinstance(clim, str) and clim == 'auto'
        if data.ndim == self._ndim or data.shape[self._ndim] == 1:
            if is_auto:
                clim = np.min(data), np.max(data)
            clim = (np.float32(clim[0]), np.float32(clim[1]))
            data = self._scale_data_on_cpu(data, clim, copy=copy)
            data_limits = clim
        else:
            data_limits = self._get_default_clims(data)
            if is_auto:
                clim = data_limits

        self._clim = clim
        self._data_limits = data_limits
        return super().scale_and_set_data(data, offset=offset, copy=copy)


class GPUScaledTextureMixin(_ScaledTextureMixin):
    """Texture class for smarter scaling and internalformat decisions.

    This texture class uses internal formats that are not supported by
    strict OpenGL 2/ES drivers without additional extensions. By using
    this texture we upload data to the GPU in a format as close to
    the original data type as possible (32-bit floats on the CPU are 32-bit
    floats on the GPU). No normalization/scaling happens on the CPU and
    all of it happens on the GPU. This should avoid unnecessary data copies
    as well as provide the highest precision for the final visualization.

    The texture format may either be a GL enum string (ex. 'r32f'), a numpy
    dtype object (ex. np.float32), or 'auto' which means the texture will
    try to pick the best format for the provided data. By using 'auto' you
    also give the texture permission to change formats in the future if
    new data is provided with a different data type.


    This class should only be used internally. For similar features where
    scaling occurs on the CPU see
    :class:`vispy.visuals._scalable_textures.CPUScaledTextureMixin`.

    To use this mixin, a subclass should be created to combine this mixin with
    the texture class being used. Existing subclasses already exist in this
    module. Note that this class **must** appear first in the subclass's parent
    classes so that its ``__init__`` method is called instead of the parent
    Texture class.

    """

    # dtype -> internalformat
    # 'r' will be replaced (if needed) with rgb or rgba depending on number of bands
    _texture_dtype_format = {
        np.float32: 'r32f',
        np.float64: 'r32f',
        np.uint8: 'r8',
        np.uint16: 'r16',
        # np.uint32: 'r32ui',  # not supported texture format in vispy
        np.int8: 'r8',
        np.int16: 'r16',
        # np.int32: 'r32i',  # not supported texture format in vispy
    }
    # instance variable that will be used later on
    _auto_texture_format = False

    def _handle_auto_texture_format(self, texture_format, data):
        if isinstance(texture_format, str) and texture_format == 'auto':
            if data is None:
                warnings.warn("'texture_format' set to 'auto' but no data "
                              "provided. Falling back to CPU scaling.")
                texture_format = None
            else:
                texture_format = data.dtype.type
                self._auto_texture_format = True
        return texture_format

    def _get_gl_tex_format(self, texture_format, num_channels):
        if texture_format and not isinstance(texture_format, str):
            texture_format = np.dtype(texture_format).type
            if texture_format not in self._texture_dtype_format:
                raise ValueError("Can't determine internal texture format for '{}'".format(texture_format))
            should_cast_to_f32(texture_format)
            texture_format = self._texture_dtype_format[texture_format]
        # adjust internalformat for format of data (RGBA vs L)
        texture_format = texture_format.replace('r', 'rgba'[:num_channels])
        return texture_format

    def _get_texture_format_for_data(self, data, format, internalformat):
        if internalformat is not None:
            num_channels = self._data_num_channels(data, format)
            texture_format = self._handle_auto_texture_format(internalformat, data)
            texture_format = self._get_gl_tex_format(texture_format, num_channels)
        return texture_format

    def _compute_clim(self, data):
        clim = self._clim
        is_auto = isinstance(clim, str) and clim == 'auto'
        if data.ndim == 2 or data.shape[2] == 1:
            if is_auto:
                clim = np.min(data), np.max(data)
            clim = (np.float32(clim[0]), np.float32(clim[1]))
        elif is_auto:
            # assume that RGB data is already scaled (0, 1)
            clim = self._get_default_clims(data)
        return clim

    def _internalformat_will_change(self, data):
        shape_repr = self._create_rep_array(data)
        new_if = self._get_gl_tex_format(data.dtype, shape_repr.shape[-1])
        return new_if != self.internalformat

    def check_data_format(self, data):
        """Check if provided data will cause issues if set later."""
        if self._internalformat_will_change(data) and not self._auto_texture_format:
            raise ValueError("Data being set would cause a format change "
                             "in the texture. This is only allowed when "
                             "'texture_format' is set to 'auto'.")

    def _reformat_if_necessary(self, data):
        if not self._internalformat_will_change(data):
            return
        if self._auto_texture_format:
            shape_repr = self._create_rep_array(data)
            internalformat = self._get_gl_tex_format(data.dtype, shape_repr.shape[-1])
            self._resize(data.shape, internalformat=internalformat)
        else:
            raise RuntimeError("'internalformat' needs to change but "
                               "'texture_format' was not 'auto'.")

    def scale_and_set_data(self, data, offset=None, copy=False):
        """Upload new data to the GPU, scaling if necessary."""
        self._reformat_if_necessary(data)
        self._data_dtype = np.dtype(data.dtype)
        self._clim = self._compute_clim(data)
        return super().scale_and_set_data(data, offset=offset, copy=copy)


class CPUScaledTexture2D(CPUScaledTextureMixIn, Texture2D):
    """Texture class with clim scaling handling builtin.

    See :class:`vispy.visuals._scalable_textures.CPUScaledTextureMixin` for
    more information.

    """


class GPUScaledTexture2D(GPUScaledTextureMixin, Texture2D):
    """Texture class with clim scaling handling builtin.

    See :class:`vispy.visuals._scalable_textures.GPUScaledTextureMixin` for
    more information.

    """


class CPUScaledTexture3D(CPUScaledTextureMixIn, Texture3D):
    """Texture class with clim scaling handling builtin.

    See :class:`vispy.visuals._scalable_textures.CPUScaledTextureMixin` for
    more information.

    """


class GPUScaledTextured3D(GPUScaledTextureMixin, Texture3D):
    """Texture class with clim scaling handling builtin.

    See :class:`vispy.visuals._scalable_textures.GPUScaledTextureMixin` for
    more information.

    """
