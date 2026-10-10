#!/usr/bin/env python3
"""Generate the Longrun PWA icons (JAG-390).

Dev-only build script (needs Pillow). Writes the PNG icons referenced by
`webui/manifest.webmanifest` into `webui/assets/`. Run from anywhere:

    python3 webui/assets/make-icons.py

The `.py` extension is NOT in the served asset whitelist, so this script is
never exposed over HTTP.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BG = (10, 12, 20, 255)      # --bg / dark shell
A1 = (139, 123, 240)        # --accent  #8b7bf0
A2 = (181, 108, 255)        # #b56cff

# a classic lightning bolt in a 0..1 unit box
BOLT = [(0.60, 0.04), (0.22, 0.56), (0.44, 0.56),
        (0.36, 0.96), (0.78, 0.42), (0.54, 0.42), (0.64, 0.04)]


def _bolt_mask(size, pad):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    span = size - 2 * pad
    d.polygon([(pad + x * span, pad + y * span) for x, y in BOLT], fill=255)
    return m


def _gradient(size):
    g = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(g)
    for y in range(size):
        t = y / (size - 1)
        d.line([(0, y), (size, y)],
               fill=tuple(int(A1[i] + (A2[i] - A1[i]) * t) for i in range(3)))
    return g


def make(size, pad_frac, rounded, name):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = ImageDraw.Draw(img)
    if rounded:
        bg.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=BG)
    else:
        bg.rectangle([0, 0, size - 1, size - 1], fill=BG)
    img.paste(_gradient(size), (0, 0), _bolt_mask(size, int(size * pad_frac)))
    path = os.path.join(HERE, name)
    img.save(path)
    print("wrote", path, "%dx%d" % (size, size))


make(192, 0.28, True, "icon-192.png")
make(512, 0.28, True, "icon-512.png")
make(512, 0.34, False, "icon-maskable-512.png")
make(180, 0.26, False, "apple-touch-icon.png")
