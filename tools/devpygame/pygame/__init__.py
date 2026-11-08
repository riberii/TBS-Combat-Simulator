"""DEV-ONLY, PIL/numpy-backed emulation of the small slice of pygame-ce this game uses.

WHY: the cloud session that produced R2 could not install pygame-ce (PyPI blocked). This module lets the
game's *own* draw code run end-to-end and write PNG previews so layouts and Python errors can be inspected.
WHAT IT IS NOT: it is NOT pygame-ce. Rasterisation (anti-aliasing, text hinting, polygon edges) differs,
there is no window, no input and no audio output. Anything rendered through it is "emulated preview",
never "real Pygame-ce verified". Never ship it as the runtime: it lives under tools/ and is only put on
sys.path by tools/render_preview.py and the emulated test helpers.
"""
from __future__ import annotations

import math
import os
import sys
import time as _time
import types
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

__version__ = "dev-emulation"
ver = "dev-emulation"
IS_EMULATION = True

SRCALPHA = 0x00010000
RESIZABLE = 0x10
FULLSCREEN = 0x80
SCALED = 0x200
BLEND_RGB_ADD, BLEND_RGB_SUB, BLEND_RGB_MULT = 1, 2, 3
BLEND_RGBA_ADD, BLEND_RGBA_SUB, BLEND_RGBA_MULT = 6, 7, 8
BLEND_PREMULTIPLIED = 17
QUIT, KEYDOWN, KEYUP, MOUSEMOTION, MOUSEBUTTONDOWN, MOUSEBUTTONUP, VIDEORESIZE = 256, 768, 769, 1024, 1025, 1026, 32769
TEXTINPUT = 771
SYSTEM_CURSOR_ARROW, SYSTEM_CURSOR_HAND = 0, 11


class error(Exception):
    pass


def _mk_keys() -> None:
    g = globals()
    for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
        g["K_" + ch] = 97 + i
    for d in range(10):
        g[f"K_{d}"] = 48 + d
        g[f"K_KP{d}"] = 1073741913 + d
    for i in range(1, 13):
        g[f"K_F{i}"] = 1073741882 + i - 1
    names = dict(UP=1073741906, DOWN=1073741905, LEFT=1073741904, RIGHT=1073741903, RETURN=13, KP_ENTER=1073741912,
                 SPACE=32, ESCAPE=27, TAB=9, BACKSPACE=8, PAGEUP=1073741899, PAGEDOWN=1073741902, HOME=1073741898,
                 END=1073741901, DELETE=127, LSHIFT=1073742049, RSHIFT=1073742053, MINUS=45, EQUALS=61,
                 COMMA=44, PERIOD=46, SLASH=47, BACKQUOTE=96)
    for k, v in names.items():
        g["K_" + k] = v


_mk_keys()
_KEYNAMES = {globals()[n]: n[2:].lower().replace("_", " ") for n in list(globals()) if n.startswith("K_") and n != "K_F"}
_KEYNAMES.update({13: "return", 32: "space", 27: "escape", 9: "tab", 8: "backspace"})


# ---------------------------------------------------------------------------------------------- Rect
class Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, *a: Any) -> None:
        if len(a) == 1:
            a = tuple(a[0]) if not isinstance(a[0], Rect) else (a[0].x, a[0].y, a[0].w, a[0].h)
        if len(a) == 2:
            (x, y), (w, h) = a
        elif len(a) == 4:
            x, y, w, h = a
        else:
            raise TypeError("Rect needs 1, 2 or 4 arguments")
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    def __iter__(self):
        return iter((self.x, self.y, self.w, self.h))

    def __getitem__(self, i: int) -> int:
        return (self.x, self.y, self.w, self.h)[i]

    def __len__(self) -> int:
        return 4

    def __eq__(self, o: object) -> bool:
        try:
            return tuple(self) == tuple(Rect(o))  # type: ignore[arg-type]
        except Exception:
            return False

    def __hash__(self) -> int:  # pragma: no cover
        return hash(tuple(self))

    def __repr__(self) -> str:
        return f"<rect({self.x}, {self.y}, {self.w}, {self.h})>"

    def copy(self) -> "Rect":
        return Rect(self.x, self.y, self.w, self.h)

    # properties
    width = property(lambda s: s.w, lambda s, v: setattr(s, "w", int(v)))
    height = property(lambda s: s.h, lambda s, v: setattr(s, "h", int(v)))
    left = property(lambda s: s.x, lambda s, v: setattr(s, "x", int(v)))
    top = property(lambda s: s.y, lambda s, v: setattr(s, "y", int(v)))
    right = property(lambda s: s.x + s.w, lambda s, v: setattr(s, "x", int(v) - s.w))
    bottom = property(lambda s: s.y + s.h, lambda s, v: setattr(s, "y", int(v) - s.h))
    centerx = property(lambda s: s.x + s.w // 2, lambda s, v: setattr(s, "x", int(v) - s.w // 2))
    centery = property(lambda s: s.y + s.h // 2, lambda s, v: setattr(s, "y", int(v) - s.h // 2))
    size = property(lambda s: (s.w, s.h), lambda s, v: (setattr(s, "w", int(v[0])), setattr(s, "h", int(v[1]))))

    def _setpair(self, ax: str, ay: str, v: Sequence[float]) -> None:
        setattr(self, ax, v[0])
        setattr(self, ay, v[1])

    topleft = property(lambda s: (s.left, s.top), lambda s, v: s._setpair("left", "top", v))
    topright = property(lambda s: (s.right, s.top), lambda s, v: s._setpair("right", "top", v))
    bottomleft = property(lambda s: (s.left, s.bottom), lambda s, v: s._setpair("left", "bottom", v))
    bottomright = property(lambda s: (s.right, s.bottom), lambda s, v: s._setpair("right", "bottom", v))
    center = property(lambda s: (s.centerx, s.centery), lambda s, v: s._setpair("centerx", "centery", v))
    midtop = property(lambda s: (s.centerx, s.top), lambda s, v: s._setpair("centerx", "top", v))
    midbottom = property(lambda s: (s.centerx, s.bottom), lambda s, v: s._setpair("centerx", "bottom", v))
    midleft = property(lambda s: (s.left, s.centery), lambda s, v: s._setpair("left", "centery", v))
    midright = property(lambda s: (s.right, s.centery), lambda s, v: s._setpair("right", "centery", v))

    def move(self, dx: float, dy: float = 0) -> "Rect":
        if isinstance(dx, (tuple, list)):
            dx, dy = dx
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def move_ip(self, dx: float, dy: float = 0) -> None:
        if isinstance(dx, (tuple, list)):
            dx, dy = dx
        self.x += int(dx)
        self.y += int(dy)

    def inflate(self, dw: float, dh: float) -> "Rect":
        return Rect(self.x - dw // 2, self.y - dh // 2, self.w + dw, self.h + dh)

    def inflate_ip(self, dw: float, dh: float) -> None:
        r = self.inflate(dw, dh)
        self.x, self.y, self.w, self.h = r.x, r.y, r.w, r.h

    def scale_by(self, sx: float, sy: float | None = None) -> "Rect":
        sy = sx if sy is None else sy
        nw, nh = int(self.w * sx), int(self.h * sy)
        return Rect(self.centerx - nw // 2, self.centery - nh // 2, nw, nh)

    def collidepoint(self, *p: Any) -> bool:
        x, y = p[0] if len(p) == 1 else p
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def colliderect(self, o: Any) -> bool:
        o = Rect(o)
        return self.x < o.x + o.w and o.x < self.x + self.w and self.y < o.y + o.h and o.y < self.y + self.h

    def union(self, o: Any) -> "Rect":
        o = Rect(o)
        x0, y0 = min(self.x, o.x), min(self.y, o.y)
        return Rect(x0, y0, max(self.right, o.right) - x0, max(self.bottom, o.bottom) - y0)

    def unionall(self, others: Any) -> "Rect":
        r = Rect(self)
        for o in others:
            r = r.union(o)
        return r

    def clip(self, o: Any) -> "Rect":
        o = Rect(o)
        x0, y0 = max(self.x, o.x), max(self.y, o.y)
        x1, y1 = min(self.right, o.right), min(self.bottom, o.bottom)
        return Rect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))

    def clamp(self, o: Any) -> "Rect":
        o = Rect(o)
        x = min(max(self.x, o.x), o.right - self.w) if self.w < o.w else o.centerx - self.w // 2
        y = min(max(self.y, o.y), o.bottom - self.h) if self.h < o.h else o.centery - self.h // 2
        return Rect(x, y, self.w, self.h)

    def clamp_ip(self, o: Any) -> None:
        r = self.clamp(o)
        self.x, self.y = r.x, r.y

    def collidelist(self, rects: Iterable[Any]) -> int:
        for i, r in enumerate(rects):
            if self.colliderect(r):
                return i
        return -1

    def contains(self, o: Any) -> bool:
        o = Rect(o)
        return self.x <= o.x and self.y <= o.y and o.right <= self.right and o.bottom <= self.bottom

    def normalize(self) -> None:
        if self.w < 0:
            self.x, self.w = self.x + self.w, -self.w
        if self.h < 0:
            self.y, self.h = self.y + self.h, -self.h


def _rgba(c: Any) -> tuple[int, int, int, int]:
    if isinstance(c, Surface):  # pragma: no cover
        raise TypeError("colour expected")
    c = tuple(int(max(0, min(255, v))) for v in c)
    return (c + (255,))[:4] if len(c) == 3 else c[:4]


# ------------------------------------------------------------------------------------------- Surface
class Surface:
    def __init__(self, size: Sequence[int] = (0, 0), flags: int = 0, depth: Any = 0, masks: Any = None) -> None:
        w, h = int(size[0]), int(size[1])
        if w < 0 or h < 0:
            raise error("Invalid resolution for Surface")
        self.a = np.zeros((h, w, 4), np.uint8)
        self.srcalpha = bool(flags & SRCALPHA)
        if not self.srcalpha:
            self.a[..., 3] = 255
        self.alpha = 255
        self.clip: Rect | None = None

    # construction helpers
    @classmethod
    def _from(cls, arr: np.ndarray, srcalpha: bool) -> "Surface":
        s = cls.__new__(cls)
        s.a, s.srcalpha, s.alpha, s.clip = arr, srcalpha, 255, None
        return s

    def get_width(self) -> int:
        return self.a.shape[1]

    def get_height(self) -> int:
        return self.a.shape[0]

    def get_size(self) -> tuple[int, int]:
        return (self.a.shape[1], self.a.shape[0])

    def get_rect(self, **kw: Any) -> Rect:
        r = Rect(0, 0, *self.get_size())
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def copy(self) -> "Surface":
        s = Surface._from(self.a.copy(), self.srcalpha)
        s.alpha = self.alpha
        return s

    def convert(self) -> "Surface":
        a = self.a.copy()
        a[..., 3] = 255
        return Surface._from(a, False)

    def convert_alpha(self) -> "Surface":
        return Surface._from(self.a.copy(), True)

    def set_alpha(self, v: int | None, flags: int = 0) -> None:
        self.alpha = 255 if v is None else int(max(0, min(255, v)))

    def get_alpha(self) -> int:
        return self.alpha

    def set_colorkey(self, *a: Any) -> None:
        pass

    def set_clip(self, r: Any = None) -> None:
        self.clip = None if r is None else Rect(r)

    def get_clip(self) -> Rect:
        return self.clip or self.get_rect()

    def get_at(self, p: Sequence[int]) -> tuple[int, int, int, int]:
        return tuple(int(v) for v in self.a[int(p[1]), int(p[0])])  # type: ignore[return-value]

    def set_at(self, p: Sequence[int], c: Any) -> None:
        x, y = int(p[0]), int(p[1])
        if 0 <= x < self.get_width() and 0 <= y < self.get_height():
            self.a[y, x] = _rgba(c) if self.srcalpha else _rgba(c)[:3] + (255,)

    def subsurface(self, r: Any) -> "Surface":
        r = Rect(r)
        s = Surface._from(self.a[r.y:r.bottom, r.x:r.right], self.srcalpha)
        return s

    def lock(self) -> None: ...
    def unlock(self) -> None: ...
    def get_bounding_rect(self) -> Rect:
        ys, xs = np.nonzero(self.a[..., 3])
        return Rect(0, 0, 0, 0) if len(xs) == 0 else Rect(xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)

    # drawing -------------------------------------------------------------------------------------
    def fill(self, color: Any, rect: Any = None, special_flags: int = 0) -> Rect:
        r = Rect(rect) if rect is not None else self.get_rect()
        r = r.clip(self.clip or self.get_rect()).clip(self.get_rect())
        if r.w <= 0 or r.h <= 0:
            return r
        c = np.array(_rgba(color), np.int32)
        reg = self.a[r.y:r.bottom, r.x:r.right]
        if special_flags in (BLEND_RGB_ADD, BLEND_RGBA_ADD):
            reg[..., :3] = np.clip(reg[..., :3].astype(np.int32) + c[:3], 0, 255)
        elif special_flags in (BLEND_RGB_SUB, BLEND_RGBA_SUB):
            reg[..., :3] = np.clip(reg[..., :3].astype(np.int32) - c[:3], 0, 255)
        elif special_flags in (BLEND_RGB_MULT, BLEND_RGBA_MULT):
            n = 4 if special_flags == BLEND_RGBA_MULT else 3
            reg[..., :n] = (reg[..., :n].astype(np.int32) * c[:n] // 255)
        else:
            reg[...] = c if self.srcalpha else np.append(c[:3], 255)
        return r

    def blit(self, src: "Surface", dest: Any = (0, 0), area: Any = None, special_flags: int = 0) -> Rect:
        if isinstance(dest, Rect):
            dx, dy = dest.x, dest.y
        else:
            dx, dy = int(dest[0]), int(dest[1])
        sa = src.a
        sx0, sy0 = 0, 0
        if area is not None:
            ar = Rect(area)
            sx0, sy0 = ar.x, ar.y
            sa = sa[ar.y:ar.bottom, ar.x:ar.right]
        h, w = sa.shape[:2]
        clip = (self.clip or self.get_rect()).clip(self.get_rect())
        x0, y0 = max(dx, clip.x), max(dy, clip.y)
        x1, y1 = min(dx + w, clip.right), min(dy + h, clip.bottom)
        if x1 <= x0 or y1 <= y0:
            return Rect(dx, dy, 0, 0)
        s = sa[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
        d = self.a[y0:y1, x0:x1]
        sf = special_flags
        if sf in (BLEND_RGB_ADD, BLEND_RGBA_ADD):
            d[..., :3] = np.clip(d[..., :3].astype(np.int32) + s[..., :3], 0, 255)
        elif sf in (BLEND_RGB_SUB, BLEND_RGBA_SUB):
            d[..., :3] = np.clip(d[..., :3].astype(np.int32) - s[..., :3], 0, 255)
        elif sf in (BLEND_RGB_MULT, BLEND_RGBA_MULT):
            n = 4 if sf == BLEND_RGBA_MULT else 3
            d[..., :n] = d[..., :n].astype(np.int32) * s[..., :n] // 255
        else:
            sal = s[..., 3].astype(np.float32) / 255.0 if src.srcalpha else np.ones(s.shape[:2], np.float32)
            sal = sal * (src.alpha / 255.0)
            if not self.srcalpha:
                for k in range(3):
                    d[..., k] = (s[..., k] * sal + d[..., k] * (1 - sal)).astype(np.uint8)
            else:
                da = d[..., 3].astype(np.float32) / 255.0
                oa = sal + da * (1 - sal)
                safe = np.where(oa > 0, oa, 1)
                for k in range(3):
                    d[..., k] = ((s[..., k] * sal + d[..., k] * da * (1 - sal)) / safe).astype(np.uint8)
                d[..., 3] = (oa * 255).astype(np.uint8)
        return Rect(x0, y0, x1 - x0, y1 - y0)

    # internal: write colour through a mask ('L' PIL image with offset)
    def _write(self, mask: Image.Image, ox: int, oy: int, color: Any) -> None:
        m = np.asarray(mask) > 127
        h, w = m.shape
        clip = (self.clip or self.get_rect()).clip(self.get_rect())
        x0, y0 = max(ox, clip.x), max(oy, clip.y)
        x1, y1 = min(ox + w, clip.right), min(oy + h, clip.bottom)
        if x1 <= x0 or y1 <= y0:
            return
        mm = m[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        c = _rgba(color)
        reg = self.a[y0:y1, x0:x1]
        if self.srcalpha:
            reg[mm] = c
        else:
            reg[mm] = c[:3] + (255,)


def _bbox(pts: Sequence[Sequence[float]], pad: int) -> tuple[int, int, int, int]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return int(math.floor(min(xs))) - pad, int(math.floor(min(ys))) - pad, int(math.ceil(max(xs))) + pad, int(math.ceil(max(ys))) + pad


def _canvas(surf: Surface, box: tuple[int, int, int, int]):
    x0, y0, x1, y1 = box
    # restrict to the surface to keep masks small for far off-screen shapes
    x0, y0 = max(x0, -2), max(y0, -2)
    x1, y1 = min(x1, surf.get_width() + 2), min(y1, surf.get_height() + 2)
    if x1 <= x0 or y1 <= y0:
        return None
    img = Image.new("L", (x1 - x0, y1 - y0), 0)
    return img, ImageDraw.Draw(img), x0, y0


class _Draw(types.ModuleType):
    def rect(self, surf: Surface, color: Any, rect: Any, width: int = 0, border_radius: int = 0, *a: Any, **kw: Any) -> Rect:
        r = Rect(rect)
        if r.w <= 0 or r.h <= 0:
            return Rect(r.x, r.y, 0, 0)
        cv = _canvas(surf, (r.x, r.y, r.right, r.bottom))
        if cv is None:
            return r
        img, d, ox, oy = cv
        box = [r.x - ox, r.y - oy, r.right - 1 - ox, r.bottom - 1 - oy]
        rad = min(border_radius, min(r.w, r.h) // 2)
        if rad > 0:
            d.rounded_rectangle(box, radius=rad, fill=255 if width <= 0 else None, outline=255 if width > 0 else None, width=max(1, width))
        else:
            d.rectangle(box, fill=255 if width <= 0 else None, outline=255 if width > 0 else None, width=max(1, width))
        surf._write(img, ox, oy, color)
        return r

    def circle(self, surf: Surface, color: Any, center: Sequence[float], radius: float, width: int = 0, *a: Any, **kw: Any) -> Rect:
        cx, cy = center
        rad = int(radius)
        if rad < 1:
            return Rect(cx, cy, 0, 0)
        cv = _canvas(surf, (cx - rad, cy - rad, cx + rad + 1, cy + rad + 1))
        if cv is not None:
            img, d, ox, oy = cv
            bb = [cx - rad - ox, cy - rad - oy, cx + rad - ox, cy + rad - oy]
            d.ellipse(bb, fill=255 if width <= 0 else None, outline=255 if width > 0 else None, width=max(1, width))
            surf._write(img, ox, oy, color)
        return Rect(cx - rad, cy - rad, rad * 2, rad * 2)

    def ellipse(self, surf: Surface, color: Any, rect: Any, width: int = 0, *a: Any, **kw: Any) -> Rect:
        r = Rect(rect)
        if r.w <= 0 or r.h <= 0:
            return r
        cv = _canvas(surf, (r.x, r.y, r.right, r.bottom))
        if cv is not None:
            img, d, ox, oy = cv
            d.ellipse([r.x - ox, r.y - oy, r.right - 1 - ox, r.bottom - 1 - oy], fill=255 if width <= 0 else None,
                      outline=255 if width > 0 else None, width=max(1, width))
            surf._write(img, ox, oy, color)
        return r

    def line(self, surf: Surface, color: Any, a: Sequence[float], b: Sequence[float], width: int = 1) -> Rect:
        pad = int(width) + 2
        cv = _canvas(surf, _bbox([a, b], pad))
        if cv is not None:
            img, d, ox, oy = cv
            d.line([(a[0] - ox, a[1] - oy), (b[0] - ox, b[1] - oy)], fill=255, width=max(1, int(width)))
            surf._write(img, ox, oy, color)
        return Rect(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1]))

    def lines(self, surf: Surface, color: Any, closed: bool, pts: Sequence[Sequence[float]], width: int = 1) -> Rect:
        pts = list(pts)
        if len(pts) < 2:
            return Rect(0, 0, 0, 0)
        pad = int(width) + 2
        cv = _canvas(surf, _bbox(pts, pad))
        if cv is not None:
            img, d, ox, oy = cv
            seq = [(p[0] - ox, p[1] - oy) for p in pts]
            if closed:
                seq.append(seq[0])
            d.line(seq, fill=255, width=max(1, int(width)), joint="curve")
            surf._write(img, ox, oy, color)
        return Rect(0, 0, 0, 0)

    aaline = line
    aalines = lines

    def polygon(self, surf: Surface, color: Any, pts: Sequence[Sequence[float]], width: int = 0) -> Rect:
        pts = list(pts)
        if len(pts) < 3:
            return Rect(0, 0, 0, 0)
        cv = _canvas(surf, _bbox(pts, int(width) + 2))
        if cv is not None:
            img, d, ox, oy = cv
            seq = [(p[0] - ox, p[1] - oy) for p in pts]
            if width <= 0:
                d.polygon(seq, fill=255)
            else:
                d.line(seq + [seq[0]], fill=255, width=int(width), joint="curve")
            surf._write(img, ox, oy, color)
        return Rect(0, 0, 0, 0)

    def arc(self, surf: Surface, color: Any, rect: Any, start: float, stop: float, width: int = 1) -> Rect:
        r = Rect(rect)
        if r.w <= 0 or r.h <= 0:
            return r
        cv = _canvas(surf, (r.x - width, r.y - width, r.right + width, r.bottom + width))
        if cv is not None:
            img, d, ox, oy = cv
            # pygame angles: counter-clockwise from +x; PIL: clockwise from +x
            d.arc([r.x - ox, r.y - oy, r.right - 1 - ox, r.bottom - 1 - oy], -math.degrees(stop), -math.degrees(start), fill=255, width=max(1, int(width)))
            surf._write(img, ox, oy, color)
        return r


draw = _Draw("pygame.draw")


# --------------------------------------------------------------------------------------------- fonts
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"]
_SERIF = {(False, False): "DejaVuSerif.ttf", (True, False): "DejaVuSerif-Bold.ttf",
          (False, True): "DejaVuSerif-Italic.ttf", (True, True): "DejaVuSerif-BoldItalic.ttf"}


def _find_font(name: str) -> str | None:
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


class Font:
    def __init__(self, path: Any, size: int, bold: bool = False, italic: bool = False) -> None:
        self.size_px = max(4, int(size * 0.92))  # pygame point sizes render a little smaller than PIL px
        self.bold, self.italic = bold, italic
        fp = path if isinstance(path, str) and os.path.exists(path) else _find_font(_SERIF[(bold, italic)])
        if fp is None:
            self.f = ImageFont.load_default()
        else:
            self.f = ImageFont.truetype(fp, self.size_px)

    def set_bold(self, v: bool) -> None: self.bold = bool(v)
    def set_italic(self, v: bool) -> None: self.italic = bool(v)
    def set_underline(self, v: bool) -> None: ...

    def size(self, text: str) -> tuple[int, int]:
        if not text:
            return (0, self.get_height())
        return (int(math.ceil(self.f.getlength(text))), self.get_height())

    def get_height(self) -> int:
        a, d = self.f.getmetrics()
        return a + d

    def get_linesize(self) -> int:
        return self.get_height() + 1

    def get_ascent(self) -> int:
        return self.f.getmetrics()[0]

    def get_descent(self) -> int:
        return -self.f.getmetrics()[1]

    def render(self, text: str, antialias: bool, color: Any, background: Any = None) -> Surface:
        w, h = self.size(text)
        w = max(1, w)
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).text((0, 0), text, font=self.f, fill=255)
        m = np.asarray(img).astype(np.float32) / 255.0
        c = _rgba(color)
        arr = np.zeros((h, w, 4), np.uint8)
        arr[..., 0], arr[..., 1], arr[..., 2] = c[0], c[1], c[2]
        arr[..., 3] = (m * c[3]).astype(np.uint8)
        s = Surface._from(arr, True)
        if background is not None:
            bg = Surface((w, h))
            bg.fill(background)
            bg.blit(s, (0, 0))
            return bg
        return s


class _FontMod(types.ModuleType):
    Font = Font
    _init = False

    def init(self) -> None: self._init = True
    def get_init(self) -> bool: return True
    def quit(self) -> None: self._init = False
    def SysFont(self, name: Any, size: int, bold: bool = False, italic: bool = False) -> Font:
        return Font(None, size, bold, italic)


font = _FontMod("pygame.font")


# ---------------------------------------------------------------------------------------- transform
class _Transform(types.ModuleType):
    @staticmethod
    def _resize(s: Surface, size: Sequence[int], resample: int) -> Surface:
        w, h = max(1, int(size[0])), max(1, int(size[1]))
        img = Image.fromarray(s.a, "RGBA").resize((w, h), resample)
        out = Surface._from(np.asarray(img).copy(), s.srcalpha)
        if not s.srcalpha:
            out.a[..., 3] = 255
        return out

    def smoothscale(self, s: Surface, size: Sequence[int], dest: Any = None) -> Surface:
        return self._resize(s, size, Image.BILINEAR if max(size) > 0 else Image.BILINEAR)

    def scale(self, s: Surface, size: Sequence[int], dest: Any = None) -> Surface:
        return self._resize(s, size, Image.NEAREST)

    def flip(self, s: Surface, fx: bool, fy: bool) -> Surface:
        a = s.a
        if fx:
            a = a[:, ::-1]
        if fy:
            a = a[::-1]
        return Surface._from(np.ascontiguousarray(a), s.srcalpha)

    def rotate(self, s: Surface, angle: float) -> Surface:
        img = Image.fromarray(s.a, "RGBA").rotate(angle, expand=True, resample=Image.BILINEAR)
        return Surface._from(np.asarray(img).copy(), True)

    rotozoom = lambda self, s, angle, scale: self.rotate(self.smoothscale(s, (s.get_width() * scale, s.get_height() * scale)), angle)  # noqa: E731


transform = _Transform("pygame.transform")


class _Image(types.ModuleType):
    def load(self, path: Any, namehint: str = "") -> Surface:
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            raise error(f"Couldn't open {path}: {exc}") from exc
        return Surface._from(np.asarray(img).copy(), True)

    def save(self, surf: Surface, path: str) -> None:
        Image.fromarray(surf.a if surf.srcalpha else surf.a[..., :3]).save(path)


image = _Image("pygame.image")


# ------------------------------------------------------------------------------ display/event/misc
class _Display(types.ModuleType):
    surface: Surface | None = None
    capture_path: str | None = None

    def set_mode(self, size: Sequence[int] = (0, 0), flags: int = 0, *a: Any, **kw: Any) -> Surface:
        if not size or size[0] == 0:
            size = (1280, 720)
        self.surface = Surface(size)
        return self.surface

    def get_surface(self) -> Surface | None: return self.surface
    def set_caption(self, *a: Any) -> None: ...
    def set_icon(self, *a: Any) -> None: ...
    def flip(self) -> None: ...
    update = flip
    def get_init(self) -> bool: return True
    def Info(self) -> Any: return types.SimpleNamespace(current_w=1280, current_h=720)


display = _Display("pygame.display")


class Event:
    def __init__(self, type: int = 0, dict: Any = None, **kw: Any) -> None:  # noqa: A002
        self.type = type
        self.__dict__.update(dict or {})
        self.__dict__.update(kw)

    def __repr__(self) -> str:
        return f"<Event({self.type}, {self.__dict__})>"


class _EventMod(types.ModuleType):
    Event = Event
    _q: list = []

    def get(self, *a: Any, **kw: Any) -> list:
        q, self._q = self._q, []
        return q

    def post(self, e: Event) -> None: self._q.append(e)
    def pump(self) -> None: ...
    def clear(self, *a: Any) -> None: self._q = []


event = _EventMod("pygame.event")


class _Key(types.ModuleType):
    def name(self, key: int) -> str:
        return _KEYNAMES.get(key, chr(key) if 32 <= key < 127 else str(key))

    def get_mods(self) -> int: return 0
    def get_pressed(self): return types.SimpleNamespace(__getitem__=lambda s, k: False)
    def set_repeat(self, *a: Any) -> None: ...


key = _Key("pygame.key")


class _Mouse(types.ModuleType):
    pos = (-1, -1)

    def get_pos(self) -> tuple[int, int]: return self.pos
    def set_cursor(self, *a: Any) -> None: ...
    def set_visible(self, v: bool) -> bool: return True
    def get_pressed(self, *a: Any): return (False, False, False)


mouse = _Mouse("pygame.mouse")


class _Clock:
    def tick(self, fps: float = 0) -> int: return 16
    def get_fps(self) -> float: return 60.0


class _TimeMod(types.ModuleType):
    Clock = _Clock

    def get_ticks(self) -> int: return int(_time.time() * 1000)
    def wait(self, ms: int) -> int: return ms
    def delay(self, ms: int) -> int: return ms


time = _TimeMod("pygame.time")


class _Sound:
    def __init__(self, *a: Any, buffer: bytes | None = None, **kw: Any) -> None:
        self.n = len(buffer) if buffer else 0
        self.vol = 1.0

    def play(self, *a: Any, **kw: Any) -> "_Channel": return _Channel()
    def stop(self) -> None: ...
    def set_volume(self, v: float) -> None: self.vol = v
    def get_volume(self) -> float: return self.vol
    def get_length(self) -> float: return self.n / (44100 * 4)
    def fadeout(self, ms: int) -> None: ...


class _Channel:
    def __init__(self, *a: Any) -> None: self.vol = 1.0
    def play(self, *a: Any, **kw: Any) -> None: ...
    def stop(self) -> None: ...
    def set_volume(self, *a: Any) -> None: ...
    def get_busy(self) -> bool: return False
    def fadeout(self, ms: int) -> None: ...
    def get_sound(self) -> None: return None


class _Mixer(types.ModuleType):
    Sound = _Sound
    Channel = _Channel
    _inited = False
    available = True  # tests may flip this to simulate "audio device missing"

    def pre_init(self, *a: Any, **kw: Any) -> None: ...
    def init(self, *a: Any, **kw: Any) -> None:
        if not self.available:
            raise error("mixer: no audio device (emulation)")
        self._inited = True

    def get_init(self): return (44100, -16, 2) if self._inited else None
    def quit(self) -> None: self._inited = False
    def set_num_channels(self, n: int) -> None: ...
    def set_reserved(self, n: int) -> None: ...
    def stop(self) -> None: ...
    def get_num_channels(self) -> int: return 24


mixer = _Mixer("pygame.mixer")


def init() -> tuple[int, int]:
    return (1, 0)


def quit() -> None:  # noqa: A001
    pass


def get_init() -> bool:
    return True


for _n, _m in (("draw", draw), ("font", font), ("transform", transform), ("image", image), ("display", display),
               ("event", event), ("key", key), ("mouse", mouse), ("time", time), ("mixer", mixer)):
    sys.modules[f"pygame.{_n}"] = _m
