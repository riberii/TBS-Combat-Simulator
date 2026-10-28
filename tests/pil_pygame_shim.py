"""Tiny PIL-backed stand-in for the handful of pygame calls ui/r2_assets.py makes.

NOT pygame-ce.  It exists so the asset-slicing/animation logic can be executed against the real PNG files on
a machine where pygame-ce cannot be installed.  A pass here proves the slicing/timing/fallback logic and the
file formats; it does NOT prove that the game renders correctly in a real Pygame window.
"""
from __future__ import annotations

import types

from PIL import Image


class Rect:
    def __init__(self, x, y=None, w=None, h=None):
        if y is None:
            x, y, w, h = x
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)


class Surface:
    def __init__(self, source, flags=0):
        self.im = source if isinstance(source, Image.Image) else Image.new("RGBA", tuple(int(v) for v in source), (0, 0, 0, 0))

    def get_size(self): return self.im.size
    def get_width(self): return self.im.size[0]
    def get_height(self): return self.im.size[1]
    def convert_alpha(self): return self
    def copy(self): return Surface(self.im.copy())
    def set_alpha(self, a): self.alpha = a

    def subsurface(self, rect):
        r = rect if isinstance(rect, Rect) else Rect(rect)
        if r.x < 0 or r.y < 0 or r.x + r.w > self.im.size[0] or r.y + r.h > self.im.size[1]:
            raise ValueError("subsurface rectangle outside surface area")
        return Surface(self.im.crop((r.x, r.y, r.x + r.w, r.y + r.h)))

    def blit(self, src, dest):
        self.im.alpha_composite(src.im, (max(0, dest[0]), max(0, dest[1]))) if dest[0] >= 0 and dest[1] >= 0 \
            else self.im.paste(src.im, (int(dest[0]), int(dest[1])), src.im)


class _Err(Exception):
    pass


def make_module() -> types.ModuleType:
    m = types.ModuleType("pygame")
    m.Rect, m.Surface, m.error, m.SRCALPHA = Rect, Surface, _Err, 0x10000
    m.image = types.SimpleNamespace(load=lambda path: Surface(Image.open(path).convert("RGBA")))
    m.display = types.SimpleNamespace(get_surface=lambda: object())
    m.transform = types.SimpleNamespace(
        scale=lambda s, size: Surface(s.im.resize(tuple(size), Image.NEAREST)),
        smoothscale=lambda s, size: Surface(s.im.resize(tuple(size), Image.LANCZOS)))
    return m
