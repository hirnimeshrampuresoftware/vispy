# -*- coding: utf-8 -*-
# vispy: gallery 30
# -----------------------------------------------------------------------------
# Copyright (c) 2014, Vispy Development Team. All Rights Reserved.
# Distributed under the (new) BSD License. See LICENSE.txt for more info.
# -----------------------------------------------------------------------------
"""
Test automatic layout of multiple viewboxes using Grid.
"""

from vispy import scene
from vispy import app
import numpy as np

canvas = scene.SceneCanvas(keys='interactive')
canvas.size = 600, 600
canvas.show()

# This is the top-level widget that will hold three ViewBoxes, which will
# be automatically resized whenever the grid is resized.
grid = canvas.central_widget.add_grid()


# Add 3 ViewBoxes to the grid
b1 = grid.add_view(row=0, col=0, col_span=2)
b1.border_color = (0.5, 0.5, 0.5, 1)
b1.camera.rect = (-0.5, -5), (11, 10)
b1.border = (1, 0, 0, 1)

b2 = grid.add_view(row=1, col=0)
b2.border_color = (0.5, 0.5, 0.5, 1)
b2.camera.rect = (-10, -5), (15, 10)
b2.border = (1, 0, 0, 1)

b3 = grid.add_view(row=1, col=1)
b3.border_color = (0.5, 0.5, 0.5, 1)
b3.camera.rect = (-5, -5), (10, 10)
b3.border = (1, 0, 0, 1)


# Generate some random vertex data and a color gradient
N = 10000
pos = np.empty((N, 2), dtype=np.float32)
pos[:, 0] = np.linspace(0, 10, N)
pos[:, 1] = np.random.normal(size=N)
pos[5000, 1] += 50

color = np.ones((N, 4), dtype=np.float32)
color[:, 0] = np.linspace(0, 1, N)
color[:, 1] = color[::-1, 0]

# Top grid cell shows plot data in a rectangular coordinate system.
l1 = scene.visuals.Line(pos=pos, color=color, mode='gl', antialias=False)
b1.add(l1)
grid1 = scene.visuals.GridLines(parent=b1.scene)

# Bottom-left grid cell shows the same data with log-transformed X
e2 = scene.Entity(parent=b2.scene)
e2.transform = scene.transforms.LogTransform(base=(2, 0, 0))
l2 = scene.visuals.Line(pos=pos, color=color, mode='gl', antialias=False, 
                        parent=e2)
grid2 = scene.visuals.GridLines(parent=e2)

# Bottom-right grid cell shows the same data again, but with a much more
# interesting transformation.
e3 = scene.Entity(parent=b3.scene)
affine = scene.transforms.AffineTransform()
affine.scale((1, 0.1))
affine.rotate(10, (0, 0, 1))
affine.translate((0, 1))
e3.transform = scene.transforms.ChainTransform([
    scene.transforms.PolarTransform(),
    affine,
    ])
l3 = scene.visuals.Line(pos=pos, color=color, mode='gl', antialias=False, 
                        parent=e3)
grid3 = scene.visuals.GridLines(scale=(np.pi/6., 1.0), parent=e3)



import sys
if __name__ == '__main__' and sys.flags.interactive == 0:
    app.run()
