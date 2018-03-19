"""Plotting of data in `data.Data` objects."""

from wizardhat.plot import shaders

from itertools import cycle
import math

import numpy as np
from seaborn import color_palette
from vispy import gloo, app, visuals


class Plotter(app.Canvas):
    """Base class for plotting."""
    def __init__(self, data, plot_params=None):
        """Construct a `Plotter` instance.

        Args:
            data (data.Data): Data object managing data to be plotted.
            plot_params (dict): Plot display parameters.
        """
        app.Canvas.__init__(self, keys='interactive')
        self.data = data


class Lines(Plotter):
    """Multiple (stacked) line plots.

    Expects a two-dimensional `data.Data` object (such as `TimeSeries`) where
    all columns after the first give the data used to plot individual lines.

    Multiple data sources may be given in a list, assuming they have the same
    form (number of channels and rows/samples); the user can cycle between
    plots of each data source with the 'D' key.
    """
    def __init__(self, data, plot_params=None, **kwargs):
        """Construct a `Lines` instance.

        Args:
            data (data.Data or List[data.Data]): Data object(s) managing data
                to be plotted. Multiple objects may be passed in a list, in
                which case the plot can cycle through plotting the data in
                each object by pressing 'd'. However, all data objects passed
                should have a similar form (e.g. `TimeSeries` with same number
                of rows/samples and channels).

            plot_params (dict): Plot display parameters.
        """
        super().__init__(data, plot_params=plot_params, **kwargs)

        try:
            self.data.ch_names
            self.data = [self.data]
        except AttributeError:
            pass

        self._cycle = cycle(range(len(self.data)))
        self._data = self.data[next(self._cycle)]

        self._n_lines = self._data.n_chan
        self._n_points = self._data.n_samples

        # plotting parameters (color, font size, etc.)
        if plot_params is None:
            plot_params = {}
        try:
            self.params = dict(
                title='Plotter',
                font_size=48,
                scale=500,
                palette=color_palette("RdBu_r", self._n_lines),
                quality_palette=color_palette("RdYlGn", 11)[::-1],
            )
            self.params.update(plot_params)
        except TypeError:
            raise TypeError("plot_params not a dict or key-value pairs list")

        color = np.repeat(self.params['palette'],
                          self._n_points, axis=0).astype(np.float32)

        self._set_program_params(color)

        # text
        self._names = [visuals.TextVisual(ch_name, bold=True, color='white')
                       for ch_name in self._data.ch_names]
        self._quality = [visuals.TextVisual('', bold=True, color='white')
                         for ch_name in self._data.ch_names]

        self._init_plot()

    def _set_program_params(self, color):

        # Signal 2D index of each vertex (row and col) and x-index (sample
        # index within each signal).
        index = np.c_[np.repeat(np.repeat(np.arange(1), self._n_lines),
                                self._n_points),
                      np.repeat(np.tile(np.arange(self._n_lines), 1),
                                self._n_points),
                      np.tile(np.arange(self._n_points),
                              self._n_lines)].astype(np.float32)

        position = np.zeros((self._n_lines,
                             self._n_points)).astype(np.float32).reshape(-1, 1)

        self.program = gloo.Program(shaders.VERT_SHADER, shaders.FRAG_SHADER)
        self.program['a_position'] = position
        self.program['a_color'] = color
        self.program['a_index'] = index
        self.program['u_scale'] = (1., 1.)
        self.program['u_size'] = (self._n_lines, 1)
        self.program['u_n'] = self._n_points

    def _init_plot(self):
        self._timer = app.Timer('auto', connect=self.update_plot, start=True)
        gloo.set_viewport(0, 0, *self.physical_size)
        gloo.set_state(clear_color='black', blend=True,
                       blend_func=('src_alpha', 'one_minus_src_alpha'))

        self.show()

    def on_key_press(self, event):
        # cycle through available data sources
        if event.key.name == 'D':
            self._data = self.data[next(self._cycle)]

        # time scale
        if event.key.name in ['+', '-']:
            if event.key.name == '+':
                dx = -0.05
            else:
                dx = 0.05
            scale_x, scale_y = self.program['u_scale']
            scale_x_new, scale_y_new = (scale_x * math.exp(1.0*dx),
                                        scale_y * math.exp(0.0*dx))
            self.program['u_scale'] = (max(1, scale_x_new),
                                       max(1, scale_y_new))
            self.update()

    def on_mouse_wheel(self, event):
        dx = np.sign(event.delta[1]) * .05
        scale_x, scale_y = self.program['u_scale']
        scale_x_new, scale_y_new = (scale_x * math.exp(0.0*dx),
                                    scale_y * math.exp(2.0*dx))
        self.program['u_scale'] = (max(1, scale_x_new), max(0.01, scale_y_new))
        self.update()

    def update_plot(self, data):
        plot_data = self._data.unstructured[:, 1:]
        plot_data = (plot_data - plot_data.mean(axis=0)) / self.params['scale']
        sd = np.std(plot_data[-int(256):], axis=0)[::-1]
        #sd = np.std(plot_data[-int(self._data.sfreq):], axis=0)[::-1]
        sd *= self.params['scale']
        co = np.int32(np.tanh((sd - 30) / 15)*5 + 5)

        for l in range(self._n_lines):
            self._quality[l].text = '%.2f' % (sd[l])
            self._quality[l].color = self.params['quality_palette'][co[l]]
            self._quality[l].font_size = 12 + co[l]

            self._names[l].font_size = 12 + co[l]
            self._names[l].color = self.params['quality_palette'][co[l]]

        plot_data = plot_data.T.ravel().astype(np.float32)
        self.program['a_position'].set_data(plot_data)
        self.update()

    def on_resize(self, event):
        # Set canvas viewport and reconfigure visual transforms to match.
        vp = (0, 0, self.physical_size[0], self.physical_size[1])
        self.context.set_viewport(*vp)

        for l, t in enumerate(self._names):
            t.transforms.configure(canvas=self, viewport=vp)
            t.pos = (self.size[0] * 0.025,
                     ((l + 0.5)/self._n_lines) * self.size[1])

        for l, t in enumerate(self._quality):
            t.transforms.configure(canvas=self, viewport=vp)
            t.pos = (self.size[0] * 0.975,
                     ((l + 0.5)/self._n_lines) * self.size[1])

    def on_draw(self, event):
        gloo.clear()
        gloo.set_viewport(0, 0, *self.physical_size)
        self.program.draw('line_strip')
        for t in self._names + self._quality:
            t.draw()