"""Playable classes: Warrior, Tank, Rogue, Witch, Fallen Angel, Kitsune, Vampire and Dragonkin.

Two of the heroes carry fully procedural anime-style vector portraits:

* Fallen Angel - hovering, bandaged, violet-winged, halo-crowned girl with a
  crown of thorns, a bandaged eye, one visible red eye and a cross-hilted dark blade.
* Witch        - silver-haired gothic cleric in a black lace hood with red eyes,
  a clergy gown with torn lace cuffs, spiral-patterned stockings and a thorned staff.

Rendering contract (everything is drawn with pygame.draw polygons on a 2x
supersampled canvas, no image assets are needed):

    rect = hero.render(screen, (ground_x, ground_y), scale=1.0, flip=False)

``pos`` is the point on the ground under the hero's feet.  Idle breathing /
floating loops run off ``time.perf_counter()`` (math.sin), so nothing has to be
ticked every frame; pass ``t=`` to drive the loop from your own clock.  Skill
animations are started automatically from ``use()`` (``play_anim``) and fade out
by themselves.  ``hud_state()`` returns HP/MP/STA, active restraints and skill
cooldowns for the HUD.
"""
from __future__ import annotations

import math
import time
from abc import abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Optional, Sequence

import pygame

from core.config import CLASS_COLORS, Color, Pal, PlayerClass, QteKind
from entities.base_entity import Ability, Bar, BaseEntity, Status, Target

if TYPE_CHECKING:
    from systems.combat_system import CombatSystem

Pt = tuple[float, float]
RGB = tuple[int, int, int]

# ==========================================================================
#  Vector drawing toolkit
# ==========================================================================
CANVAS_W, CANVAS_H = 460, 560          # logical units of a hero sprite
CANVAS_OX, CANVAS_OY = 230, 372        # canvas position of the hero's pelvis (local origin)
GROUND = 135                           # ground line, relative to the pelvis


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _ease(k: float) -> float:
    k = _clamp(k)
    return k * k * (3.0 - 2.0 * k)


def _pulse(k: float) -> float:
    return math.sin(math.pi * _clamp(k))


def _mix(a: Sequence[int], b: Sequence[int], k: float) -> RGB:
    k = _clamp(k)
    return (int(a[0] + (b[0] - a[0]) * k), int(a[1] + (b[1] - a[1]) * k), int(a[2] + (b[2] - a[2]) * k))


def _rgba(c: Sequence[int], a: float) -> tuple[int, int, int, int]:
    return (int(c[0]), int(c[1]), int(c[2]), int(_clamp(a, 0, 255)))


def _norm(v: Pt) -> Pt:
    length = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / length, v[1] / length)


def _rot(p: Pt, ang: float, c: Pt = (0.0, 0.0)) -> Pt:
    ca, sa = math.cos(ang), math.sin(ang)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)


def _bezier(p0: Pt, p1: Pt, p2: Pt, p3: Pt, n: int = 14) -> list[Pt]:
    pts = []
    for i in range(n + 1):
        s = i / n
        m = 1.0 - s
        pts.append((m ** 3 * p0[0] + 3 * m * m * s * p1[0] + 3 * m * s * s * p2[0] + s ** 3 * p3[0],
                    m ** 3 * p0[1] + 3 * m * m * s * p1[1] + 3 * m * s * s * p2[1] + s ** 3 * p3[1]))
    return pts


def _catmull(pts: Sequence[Pt], n: int = 6) -> list[Pt]:
    """Smooth open path through `pts`."""
    if len(pts) < 3:
        return list(pts)
    ext = [pts[0]] + list(pts) + [pts[-1]]
    out: list[Pt] = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for j in range(n):
            s = j / n
            s2, s3 = s * s, s * s * s
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * s + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * s2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * s3) for k in (0, 1)))  # type: ignore[arg-type]
    out.append(pts[-1])
    return out


def _smooth_closed(pts: Sequence[Pt], n: int = 5) -> list[Pt]:
    """Smooth closed outline through `pts`."""
    count = len(pts)
    out: list[Pt] = []
    for i in range(count):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % count], pts[(i + 2) % count]
        for j in range(n):
            s = j / n
            s2, s3 = s * s, s * s * s
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * s + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * s2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * s3) for k in (0, 1)))  # type: ignore[arg-type]
    return out


def _ellipse_pts(c: Pt, rx: float, ry: float, ang: float = 0.0, n: int = 32,
                 a0: float = 0.0, a1: float = 2 * math.pi) -> list[Pt]:
    full = (a1 - a0) >= 2 * math.pi - 1e-6
    count = n if full else n + 1
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for i in range(count):
        th = a0 + (a1 - a0) * i / n
        x, y = rx * math.cos(th), ry * math.sin(th)
        pts.append((c[0] + x * ca - y * sa, c[1] + x * sa + y * ca))
    return pts


def _widths(n: int, ctrl: Sequence[float]) -> list[float]:
    """Interpolate a short list of control widths over `n` path samples."""
    m = len(ctrl) - 1
    out = []
    for i in range(n):
        s = (i / (n - 1) * m) if n > 1 else 0.0
        j = min(int(s), m - 1) if m > 0 else 0
        out.append(_lerp(ctrl[j], ctrl[min(j + 1, m)], s - j))
    return out


def _ribbon_poly(path: Sequence[Pt], widths: Sequence[float]) -> list[Pt]:
    left, right = [], []
    n = len(path)
    for i, (x, y) in enumerate(path):
        a, b = path[max(0, i - 1)], path[min(n - 1, i + 1)]
        tx, ty = _norm((b[0] - a[0], b[1] - a[1]))
        nx, ny = -ty, tx
        h = widths[i] * 0.5
        left.append((x + nx * h, y + ny * h))
        right.append((x - nx * h, y - ny * h))
    return left + right[::-1]


def _ik2(s: Pt, t: Pt, l1: float, l2: float, bend: float = 1.0) -> tuple[Pt, Pt]:
    """Two-bone IK. Returns (elbow, hand). bend=+1 bows the elbow clockwise."""
    dx, dy = t[0] - s[0], t[1] - s[1]
    raw = math.hypot(dx, dy) or 1e-6
    ux, uy = dx / raw, dy / raw
    d = _clamp(raw, abs(l1 - l2) + 0.5, l1 + l2 - 0.5)
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))
    elbow = (s[0] + ux * a - uy * h * bend, s[1] + uy * a + ux * h * bend)
    hand = (s[0] + ux * d, s[1] + uy * d)
    return elbow, hand


class VectorCanvas:
    """Supersampled polygon canvas with a local origin at the hero's pelvis."""

    def __init__(self, ss: int = 2) -> None:
        self.ss = max(1, int(ss))
        self.surf = pygame.Surface((CANVAS_W * self.ss, CANVAS_H * self.ss), pygame.SRCALPHA)
        self.off: Pt = (0.0, 0.0)

    def _px(self, p: Pt) -> Pt:
        return ((p[0] + self.off[0] + CANVAS_OX) * self.ss, (p[1] + self.off[1] + CANVAS_OY) * self.ss)

    def _fill(self, polys: list[list[Pt]], color: Sequence[int]) -> None:
        """Fill pixel-space polygons with ONE colour, composited once (no alpha stacking)."""
        if not polys:
            return
        alpha = color[3] if len(color) == 4 else 255
        if alpha <= 0:
            return
        if alpha >= 255:
            for pl in polys:
                if len(pl) >= 3:
                    pygame.draw.polygon(self.surf, (color[0], color[1], color[2]), pl)
            return
        xs = [x for pl in polys for x, _ in pl]
        ys = [y for pl in polys for _, y in pl]
        x0, y0 = max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1)
        x1, y1 = min(self.surf.get_width(), int(max(xs)) + 2), min(self.surf.get_height(), int(max(ys)) + 2)
        if x1 <= x0 or y1 <= y0:
            return
        tmp = pygame.Surface((x1 - x0, y1 - y0), pygame.SRCALPHA)
        col = (color[0], color[1], color[2], int(alpha))
        for pl in polys:
            if len(pl) >= 3:
                pygame.draw.polygon(tmp, col, [(x - x0, y - y0) for x, y in pl])
        self.surf.blit(tmp, (x0, y0))

    # ---- primitives ------------------------------------------------------
    def poly(self, pts: Sequence[Pt], color: Sequence[int]) -> None:
        if len(pts) >= 3:
            self._fill([[self._px(p) for p in pts]], color)

    def ellipse(self, c: Pt, rx: float, ry: float, color: Sequence[int], ang: float = 0.0, n: int = 28) -> None:
        self.poly(_ellipse_pts(c, rx, ry, ang, n), color)

    def stroke(self, pts: Sequence[Pt], width: float, color: Sequence[int],
               closed: bool = False, joints: bool = True) -> None:
        if len(pts) < 2:
            return
        hw = width * 0.5
        seq = list(pts) + ([pts[0]] if closed else [])
        polys: list[list[Pt]] = []
        for a, b in zip(seq, seq[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            nx, ny = -dy / length * hw, dx / length * hw
            polys.append([self._px((a[0] + nx, a[1] + ny)), self._px((b[0] + nx, b[1] + ny)),
                          self._px((b[0] - nx, b[1] - ny)), self._px((a[0] - nx, a[1] - ny))])
        if joints and width > 1.8:
            for p in seq:
                polys.append([self._px(q) for q in _ellipse_pts(p, hw, hw, 0.0, 8)])
        self._fill(polys, color)

    def ribbon(self, path: Sequence[Pt], ctrl_widths: Sequence[float], color: Sequence[int]) -> list[Pt]:
        poly = _ribbon_poly(path, _widths(len(path), ctrl_widths))
        self.poly(poly, color)
        return poly

    def grad_ribbon(self, path: Sequence[Pt], ctrl_widths: Sequence[float], c0: RGB, c1: RGB) -> list[Pt]:
        """Ribbon whose colour fades from c0 (start) to c1 (end). Returns its outline."""
        n = len(path)
        poly = _ribbon_poly(path, _widths(n, ctrl_widths))
        self.poly(poly, _mix(c0, c1, 0.5))
        for i in range(n - 1):
            self.poly([poly[i], poly[i + 1], poly[2 * n - 2 - i], poly[2 * n - 1 - i]], _mix(c0, c1, (i + 0.5) / (n - 1)))
        return poly

    def glow(self, c: Pt, r: float, color: Sequence[int], strength: float = 1.0, steps: int = 9) -> None:
        for i in range(steps):
            rr = r * (1.0 - i / steps)
            self.ellipse(c, rr, rr, _rgba(color, 255 * strength * 1.5 / steps), n=22)


def _strand(cv: VectorCanvas, start: Pt, end: Pt, bend: float, width: float, col: RGB, edge: Optional[RGB],
            t: float, phase: float, amp: float) -> None:
    """One swaying tapered hair lock."""
    sw = math.sin(t * 1.25 + phase) * amp
    sx, sy = start
    ex, ey = end
    c1 = (sx + bend * 0.45, sy + (ey - sy) * 0.30)
    c2 = (ex - (ex - sx) * 0.30 + sw * 0.5 + bend, sy + (ey - sy) * 0.72)
    tip = (ex + sw, ey + math.cos(t * 0.95 + phase) * amp * 0.25)
    path = _bezier(start, c1, c2, tip, 14)
    poly = cv.ribbon(path, [width * 0.55, width, width * 0.8, width * 0.45, 0.6], col)
    if edge:
        cv.stroke(path[2:-1], 0.9, _rgba(edge, 170), joints=False)


def _feather(cv: VectorCanvas, base: Pt, ang: float, length: float, width: float, c0: RGB, c1: RGB,
             droop: float = 0.12) -> list[Pt]:
    d = (math.cos(ang), math.sin(ang))
    tip = (base[0] + d[0] * length, base[1] + d[1] * length + length * droop)
    p1 = (base[0] + d[0] * length * 0.33, base[1] + d[1] * length * 0.33)
    p2 = (base[0] + d[0] * length * 0.68, base[1] + d[1] * length * 0.68 + length * droop * 0.5)
    path = _bezier(base, p1, p2, tip, 10)
    poly = cv.grad_ribbon(path, [width * 0.2, width * 0.85, width, width * 0.7, width * 0.3, 0.8], c0, c1)
    cv.stroke(poly, 1.0, _rgba((14, 6, 24), 230), closed=True, joints=False)
    return path


def _wraps(cv: VectorCanvas, a: Pt, b: Pt, w0: float, w1: float, count: int, col: RGB) -> None:
    """Bandage wraps across the limb segment a->b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    for j in range(count):
        s = (j + 0.5) / count
        cx, cy = a[0] + dx * s, a[1] + dy * s
        w = _lerp(w0, w1, s) * 0.5
        cv.stroke([(cx + nx * w - ux * 2.2, cy + ny * w - uy * 2.2), (cx - nx * w + ux * 2.2, cy - ny * w + uy * 2.2)],
                  1.7, _rgba(col, 235), joints=False)


def _face(cv: VectorCanvas, hc: Pt, skin: RGB, shade: RGB, iris: RGB, iris_hi: RGB, blink: float,
          smile: float = 0.0, left: bool = True, right: bool = True, brow: RGB = (150, 130, 160)) -> None:
    """Shared anime face (head centre `hc`, ~46 wide, ~60 tall)."""
    def H(pts: Sequence[Pt]) -> list[Pt]:
        return [(hc[0] + x, hc[1] + y) for x, y in pts]

    outline = [(-21, -22), (-23, -8), (-20, 8), (-13, 21), (0, 29), (13, 21), (20, 8), (23, -8), (21, -22), (10, -29),
               (0, -31), (-10, -29)]
    smooth = _smooth_closed(outline, 4)
    cv.poly(H(smooth), skin)
    cv.poly(H([(23, -8), (20, 8), (13, 21), (0, 29), (6, 22), (15, 10), (19, -6)]), _rgba(shade, 150))
    for sx in (-1, 1):
        cv.ellipse((hc[0] + sx * 13.5, hc[1] + 12.5), 6.2, 3.0, (255, 140, 156, 70))
    bs = max(0.1, 1.0 - 0.9 * blink)
    for sx, visible in ((-1, left), (1, right)):
        if not visible:
            continue
        ex, ey = hc[0] + sx * 10.5, hc[1] + 2.0
        cv.ellipse((ex, ey), 7.4, 7.8 * bs, (252, 246, 250))
        cv.ellipse((ex, ey + 0.8 * bs), 5.4, 6.6 * bs, iris)
        cv.ellipse((ex, ey + 2.5 * bs), 4.2, 3.1 * bs, iris_hi)
        cv.ellipse((ex, ey + 0.5 * bs), 2.2, 3.4 * bs, (30, 6, 14))
        cv.ellipse((ex - 1.8, ey - 2.5 * bs), 1.9, 1.9 * bs + 0.15, (255, 255, 255))
        cv.ellipse((ex + 2.3, ey + 2.9 * bs), 0.9, 0.9 * bs + 0.1, (255, 255, 255, 210))
        cv.stroke(_ellipse_pts((ex, ey), 8.2, 8.4 * bs, 0.0, 12, math.pi * 1.04, math.pi * 1.96), 2.3, (34, 18, 38),
                  joints=True)
        cv.stroke([(ex + sx * 7.8, ey - 1.0), (ex + sx * 11.4, ey - 3.4)], 1.7, (34, 18, 38))
        cv.stroke(_ellipse_pts((ex, ey), 7.6, 7.8 * bs, 0.0, 8, math.pi * 0.12, math.pi * 0.88), 0.8, _rgba(shade, 150),
                  joints=False)
        cv.stroke([(ex - 6.5, hc[1] - 10.5), (ex, hc[1] - 12.8 + sx * 0.4), (ex + 6.5, hc[1] - 10.5)], 1.5,
                  _rgba(brow, 220))
    cv.stroke([(hc[0] + 0.4, hc[1] + 9.0), (hc[0] + 1.6, hc[1] + 11.2)], 1.0, _rgba(shade, 230))
    cv.stroke(_catmull([(hc[0] - 4.2, hc[1] + 17.6), (hc[0], hc[1] + 17.8 + smile * 2.2), (hc[0] + 4.6, hc[1] + 17.2 - smile * 0.4)], 4),
              1.4, (162, 84, 106))


# ==========================================================================
#  Shared palettes + skill animation lengths
# ==========================================================================
_INK = (16, 10, 24)
_SKIN = (247, 236, 241)
_SKIN_SH = (222, 203, 219)
_BANDAGE = (240, 236, 242)
_BANDAGE_SH = (192, 186, 200)
_GOTH = (26, 24, 34)
_GOTH_HI = (88, 84, 108)
_VIOLET = (178, 100, 245)
_STEEL = (150, 150, 168)
_GOLD = (214, 176, 100)
_ANGEL_HAIR = ((238, 226, 236), (196, 178, 206), (136, 118, 158))
_WITCH_HAIR = ((249, 246, 252), (216, 210, 228), (156, 148, 178))

ANIM_LENGTH = {"slash": 0.60, "dash": 0.70, "halo": 1.25, "bolt": 0.80, "barrier": 0.85, "curse": 1.40,
               "blood": 0.72, "mist": 0.88, "breath": 1.05, "wingbeat": 0.82, "ascend": 1.25,
               "foxfire": 0.58, "illusion": 0.72, "ninefold": 0.62, "masquerade": 1.05,
               "hurt": 0.35}


def _chain(cv: VectorCanvas, a: Pt, b: Pt, links: int, sag: float, col: RGB = (118, 118, 136)) -> None:
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + sag)
    path = [((1 - s) ** 2 * a[0] + 2 * (1 - s) * s * mid[0] + s * s * b[0],
             (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * mid[1] + s * s * b[1]) for s in (i / links for i in range(links + 1))]
    for i in range(links):
        c = ((path[i][0] + path[i + 1][0]) / 2, (path[i][1] + path[i + 1][1]) / 2)
        ang = math.atan2(path[i + 1][1] - path[i][1], path[i + 1][0] - path[i][0]) + (i % 2) * math.pi / 2
        cv.ellipse(c, 4.0, 2.3, (40, 38, 50), ang, 10)
        cv.ellipse(c, 2.9, 1.2, _mix(col, (220, 220, 235), 0.2 + 0.1 * (i % 2)), ang, 10)


def _barbs(cv: VectorCanvas, path: Sequence[Pt]) -> None:
    cv.stroke(path, 1.5, (136, 136, 152), joints=False)
    for i in range(2, len(path) - 1, 2):
        x, y = path[i]
        tx, ty = _norm((path[i + 1][0] - path[i - 1][0], path[i + 1][1] - path[i - 1][1]))
        nx, ny = -ty, tx
        cv.stroke([(x - nx * 3.6 - tx * 1.6, y - ny * 3.6 - ty * 1.6), (x + nx * 3.6 + tx * 1.6, y + ny * 3.6 + ty * 1.6)],
                  1.1, (190, 190, 205), joints=False)
        cv.stroke([(x - nx * 3.6 + tx * 1.6, y - ny * 3.6 + ty * 1.6), (x + nx * 3.6 - tx * 1.6, y + ny * 3.6 - ty * 1.6)],
                  1.1, (190, 190, 205), joints=False)


def _wing(cv: VectorCanvas, side: int, flap: float, back: float, barbed: bool) -> None:
    """Dark purple feathered wing: long primaries, then shorter coverts (the far wing is smaller)."""
    sc = 1.0 if side > 0 else 0.8
    ox, oy = side * 12.0, -142.0
    leading: Optional[list[Pt]] = None
    for layer in (0, 1):
        n = 10 if layer == 0 else 8
        for i in range(n - 1, -1, -1):
            u = i / (n - 1)
            if layer == 0:
                deg = _lerp(64, 2, u)
                length = _lerp(268, 150, u ** 0.7) * sc * (1 + 0.035 * math.sin(i * 1.7))
                wmax = _lerp(36, 25, u) * sc
                c0, c1 = (24, 10, 42), _mix((90, 40, 156), (186, 120, 246), 1 - u)
            else:
                deg = _lerp(72, -2, u)
                length = _lerp(142, 70, u) * sc
                wmax = _lerp(28, 21, u) * sc
                c0, c1 = (16, 8, 28), _mix((48, 22, 88), (112, 58, 180), 1 - u)
            deg += flap * (7 * (1 - u) + 3) - back * 34 * (1 - 0.45 * u)
            a = math.radians(deg)
            d = (side * math.cos(a), -math.sin(a))
            p0 = (ox + side * u * 5, oy + u * 24)
            p3 = (p0[0] + d[0] * length, p0[1] + d[1] * length + length * 0.17)
            p1 = (p0[0] + d[0] * length * 0.33, p0[1] + d[1] * length * 0.33)
            p2 = (p0[0] + d[0] * length * 0.68, p0[1] + d[1] * length * 0.68 + length * 0.08)
            path = _bezier(p0, p1, p2, p3, 12)
            poly = cv.grad_ribbon(path, [wmax * 0.2, wmax * 0.9, wmax, wmax * 0.95, wmax * 0.68, wmax * 0.12], c0, c1)
            cv.stroke(poly, 1.1, _rgba(_INK, 235), closed=True, joints=False)
            cv.stroke(path[1:-2], 1.0, (205, 150, 255, 120), joints=False)
            if layer == 0 and i == 0:
                leading = path
    if barbed and leading:
        _barbs(cv, leading)


def _crown_of_thorns(cv: VectorCanvas, c: Pt, rx: float, ry: float, ang: float, t: float) -> None:
    n = 44
    pts = []
    for i in range(n):
        th = 2 * math.pi * i / n
        r = 1 + 0.08 * math.sin(th * 7) + 0.05 * math.sin(th * 11 + 1.0)
        pts.append(_rot((c[0] + rx * math.cos(th) * r, c[1] + ry * math.sin(th) * r), ang, c))
    cv.stroke(pts, 7.0, _rgba(_VIOLET, 38), closed=True, joints=False)
    cv.stroke(pts, 3.2, (58, 44, 40), closed=True)
    cv.stroke(pts[n // 2:] + pts[:1], 1.1, (140, 116, 92, 210), joints=False)
    for i in range(0, n, 3):
        x, y = pts[i]
        dx, dy = _norm((x - c[0], y - c[1]))
        ln = 5.0 + (i % 2) * 2.5
        cv.stroke([(x, y), (x + dx * ln + dy * 1.4, y + dy * ln - dx * 1.4)], 1.4, (30, 22, 22), joints=False)
    # twinkle
    k = 0.5 + 0.5 * math.sin(t * 3.0)
    cv.ellipse(_rot((c[0] + rx * 0.9, c[1] - ry * 0.2), ang, c), 1.6 + k, 1.6 + k, (255, 235, 230, 200))


def _cross_blade(cv: VectorCanvas, grip: Pt, ang: float, length: float, glow: float, t: float) -> None:
    """Cross-hilted blade of dark glass with a violet edge."""
    d = (math.cos(ang), math.sin(ang))
    n = (-d[1], d[0])
    g = (grip[0] + d[0] * 10, grip[1] + d[1] * 10)
    tip = (g[0] + d[0] * length, g[1] + d[1] * length)
    mid = (g[0] + d[0] * length * 0.7, g[1] + d[1] * length * 0.7)
    cv.stroke([g, tip], 14, _rgba(_VIOLET, 34 * glow), joints=False)
    cv.stroke([g, tip], 7, _rgba(_VIOLET, 46 * glow), joints=False)
    body = [(g[0] + n[0] * 5.6, g[1] + n[1] * 5.6), (mid[0] + n[0] * 4.4, mid[1] + n[1] * 4.4), tip,
            (mid[0] - n[0] * 4.4, mid[1] - n[1] * 4.4), (g[0] - n[0] * 5.6, g[1] - n[1] * 5.6)]
    cv.poly(body, (30, 20, 48))
    cv.stroke([body[0], body[1], body[2]], 1.5, _rgba((205, 140, 255), 150 + 90 * glow), joints=False)
    cv.stroke([body[2], body[3], body[4]], 1.0, (96, 56, 150), joints=False)
    cv.stroke([(g[0] + d[0] * 6, g[1] + d[1] * 6), (g[0] + d[0] * length * 0.85, g[1] + d[1] * length * 0.85)],
              1.3, (100, 58, 160, 200), joints=False)
    cv.stroke([grip, g], 5, (46, 34, 58))
    _wraps(cv, grip, g, 5, 5, 3, _BANDAGE_SH)
    cv.ellipse((grip[0] - d[0] * 4, grip[1] - d[1] * 4), 3.6, 3.6, _STEEL)
    for sgn in (-1, 1):
        end = (g[0] + n[0] * 17 * sgn, g[1] + n[1] * 17 * sgn)
        cv.stroke([(g[0] + n[0] * 3 * sgn, g[1] + n[1] * 3 * sgn), end], 3.4, (212, 206, 226))
        cv.poly([(end[0] + n[0] * 2.4 * sgn, end[1] + n[1] * 2.4 * sgn),
                 (end[0] - d[0] * 3.6 + n[0] * sgn, end[1] - d[1] * 3.6 + n[1] * sgn),
                 (end[0] + d[0] * 3.6 + n[0] * sgn, end[1] + d[1] * 3.6 + n[1] * sgn)], (232, 228, 240))
    cv.ellipse(g, 3.2, 3.2, _rgba(_VIOLET, 255))
    k = 0.5 + 0.5 * math.sin(t * 3.4)
    r = 4.0 + 4.0 * k
    cv.poly([(g[0], g[1] - r * 1.6), (g[0] + r * 0.35, g[1] - r * 0.35), (g[0] + r * 1.6, g[1]),
             (g[0] + r * 0.35, g[1] + r * 0.35), (g[0], g[1] + r * 1.6), (g[0] - r * 0.35, g[1] + r * 0.35),
             (g[0] - r * 1.6, g[1]), (g[0] - r * 0.35, g[1] - r * 0.35)], (255, 245, 255, 200))


def _halo_ring(cv: VectorCanvas, c: Pt, rx: float, ry: float, tilt: float, t: float, power: float) -> None:
    ring = _ellipse_pts(c, rx, ry, tilt, 56)
    for width, alpha in ((16, 34), (10, 62), (6, 110)):
        cv.stroke(ring, width, _rgba((196, 84, 255), alpha * power), closed=True, joints=False)
    cv.stroke(ring, 2.4, _rgba((255, 222, 255), 235), closed=True, joints=False)
    inner = _ellipse_pts(c, rx * 0.84, ry * 0.84, tilt, 40)
    cv.stroke(inner, 1.0, _rgba((236, 160, 255), 150 * power), closed=True, joints=False)
    for j in range(16):
        th = t * 0.55 + j * 2 * math.pi / 16
        a = _rot((c[0] + math.cos(th) * rx * 0.97, c[1] + math.sin(th) * ry * 0.97), tilt, c)
        b = _rot((c[0] + math.cos(th) * rx * 0.76, c[1] + math.sin(th) * ry * 0.76), tilt, c)
        cv.stroke([a, b], 1.3, _rgba((245, 180, 255), 200 * power), joints=False)


def _paint_angel(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    restr = getattr(p, "restraints", None) or set()

    def has(name: str) -> bool:
        return any(r.name == name for r in restr)

    hair_l, hair_m, hair_d = _ANGEL_HAIR
    bob = -16.0 + math.sin(t * 1.55) * 7.0                  # hover
    breath = math.sin(t * 2.1)
    cb = breath * 1.8                                       # chest rise
    boost = _pulse(k) if anim in ("halo", "dash", "slash") else 0.0
    flap = math.sin(t * 1.7) * (1.0 + 0.9 * boost)
    back = _pulse(k) if anim == "dash" else 0.0
    ph = t % 4.6
    blink = math.sin(math.pi * ph / 0.14) if ph < 0.14 else 0.0
    lsw = math.sin(t * 1.55 + 0.8) * 4.0

    # ---- ground shadow + dash streaks -------------------------------------
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 58 + bob * 0.9, 9, (0, 0, 0, 70))
    if anim == "dash":
        a = _pulse(k)
        for j in range(9):
            y = -190 + j * 30
            x0 = -40 - 36 * (j % 3)
            ln = (90 + (j * 37) % 70) * a
            cv.ribbon([(x0, y + bob), (x0 - ln * 0.5, y + bob), (x0 - ln, y + bob)], [0.6, 3.2, 0.3],
                      _rgba((196, 140, 255), 150 * a))
    cv.off = (0.0, bob)

    # ---- wings + back cloak -------------------------------------------------
    _wing(cv, -1, flap, back, has("BARBED_WINGS"))
    _wing(cv, 1, flap, back, has("BARBED_WINGS"))
    cv.glow((0, -70), 130, (130, 50, 200), 0.30)
    for i in range(5):
        sway = math.sin(t * 1.3 + i) * 7
        path = _bezier((-14 + i * 7, -128 + i * 8), (-50 - i * 6, -80 + i * 10), (-90 - i * 14 + sway, 0 + i * 12),
                       (-118 - i * 16 + sway * 1.4, 56 + i * 20), 12)
        cv.ribbon(path, [14, 34, 24, 3], (140, 134, 158, 120))

    # ---- back hair ----------------------------------------------------------
    sway = math.sin(t * 1.1)
    mass = [(-34, -218), (-56, -180), (-76, -110), (-86, -30 + sway * 4), (-66, 40 + sway * 6), (-34, 52), (0, 40),
            (34, 52), (66, 40 - sway * 6), (86, -30 - sway * 4), (76, -110), (56, -180), (34, -218)]
    cv.poly(_smooth_closed(mass, 4), hair_m)
    for i in range(13):
        f = i / 12
        sx, sy = _lerp(-30, 30, f), -226 + abs(f - 0.5) * 26
        ex = _lerp(-96, 84, f) + ((i * 7) % 5 - 2) * 6
        ey = _lerp(-10, 70, ((i * 5) % 7) / 6) + 14
        col = hair_l if i % 3 else _mix(hair_l, hair_m, 0.5)
        _strand(cv, (sx, sy), (ex, ey), (ex - sx) * 0.3, 15, col, hair_d, t, i * 0.8, 5 + (i % 4) * 2)
    antenna = _bezier((-4, -230), (-10, -268), (10 + math.sin(t * 1.4) * 8, -290), (26 + math.sin(t * 1.4) * 14, -306), 12)
    cv.ribbon(antenna, [3.5, 3.0, 1.6, 0.4], hair_l)

    # ---- legs ---------------------------------------------------------------
    legs = [[(11, -8), (30, 44), (20, 92), (24, 124)], [(-11, -8), (-16, 50), (-30 + lsw, 96), (-34 + lsw, 126)]]
    for pts in legs:
        path = _catmull(pts, 6)
        cv.ribbon(path, [19, 16, 11, 7.5, 5.5], _SKIN)
        cv.ribbon([(x + 2.2, y) for x, y in path], [8, 6, 4, 2.5, 2], _rgba(_SKIN_SH, 170))
        a_, b_ = path[int(len(path) * 0.55)], path[int(len(path) * 0.92)]
        cv.ribbon([(a_[0], a_[1]), (b_[0], b_[1])], [9.4, 6.8], _rgba(_BANDAGE, 215))
        _wraps(cv, a_, b_, 9, 6.5, 6, _BANDAGE_SH)
        ft = path[-1]
        cv.poly([(ft[0] - 4.5, ft[1] - 2), (ft[0] + 4.5, ft[1] - 2), (ft[0] + 3, ft[1] + 8), (ft[0] - 1, ft[1] + 12),
                 (ft[0] - 4, ft[1] + 6)], _SKIN)
        if has("SABATONS"):
            cv.ribbon(path[-7:], [12.5, 9], (52, 50, 64))
            for sx in (-4, 0, 4):
                cv.poly([(ft[0] + sx - 2, ft[1] + 8), (ft[0] + sx + 2, ft[1] + 8), (ft[0] + sx, ft[1] + 17)], (190, 190, 205))
        if has("ANCHOR") and pts[0][0] < 0:
            end = (-50, 156)
            _chain(cv, (ft[0], ft[1] + 6), end, 9, 16)
            cv.stroke([(end[0], end[1] - 10), (end[0], end[1] + 12)], 3, (96, 96, 112))
            cv.stroke([(end[0] - 7, end[1] - 5), (end[0] + 7, end[1] - 5)], 3, (96, 96, 112))
            cv.stroke(_ellipse_pts((end[0], end[1] + 4), 10, 8, 0.0, 10, 0.1 * math.pi, 0.9 * math.pi), 3, (96, 96, 112))

    # ---- skirt --------------------------------------------------------------
    hem = [(66 - 16.5 * i, 80 + (i % 2) * 22 + math.sin(t * 1.6 + i * 0.9) * 5) for i in range(9)]
    skirt = [(27, -14), (36, 20), (56, 56)] + hem + [(-56, 56), (-36, 20), (-27, -14)]
    cv.poly(skirt, _GOTH)
    for x, y in hem[1:-1]:
        cv.stroke([(x * 0.3, -6), (x, y)], 1.2, (62, 56, 80, 150), joints=False)
    cv.stroke(hem, 1.7, _rgba(_VIOLET, 170))
    cv.stroke([(27, -14), (36, 20), (56, 56), hem[0]], 1.2, _rgba(_GOTH_HI, 200), joints=False)
    cv.stroke([(-27, -14), (-36, 20), (-56, 56), hem[-1]], 1.2, _rgba(_GOTH_HI, 200), joints=False)

    # ---- torso --------------------------------------------------------------
    ch = 1.0 + 0.012 * breath
    torso = [(-25 * ch, -148 + cb), (-21 * ch, -122 + cb), (-17, -96), (-15, -78), (-20, -40), (-25, -10), (25, -10),
             (20, -40), (15, -78), (17, -96), (21 * ch, -122 + cb), (25 * ch, -148 + cb)]
    cv.poly(_smooth_closed(torso, 3), _GOTH)
    cv.stroke([(-22 * ch, -140 + cb), (-14, -96)], 1.4, _rgba(_VIOLET, 120), joints=False)
    cv.stroke([(22 * ch, -140 + cb), (14, -96)], 1.4, _rgba(_VIOLET, 120), joints=False)
    cv.stroke([(0, -136 + cb), (0, -12)], 1.0, (62, 56, 80))
    for j in range(5):
        y = -92 + j * 9
        cv.stroke([(-5, y), (5, y + 4.5)], 1.0, _rgba(_STEEL, 190), joints=False)
        cv.stroke([(5, y), (-5, y + 4.5)], 1.0, _rgba(_STEEL, 190), joints=False)
    cv.stroke([(-25, -148 + cb), (-8, -142 + cb), (0, -135 + cb), (8, -142 + cb), (25, -148 + cb)], 2.0, _GOTH_HI)
    for sgn in (-1, 1):
        cape = [(sgn * 8, -158 + cb), (sgn * 40, -148 + cb), (sgn * 52, -124 + cb), (sgn * 41, -129 + cb),
                (sgn * 35, -116 + cb), (sgn * 27, -128 + cb), (sgn * 12, -134 + cb)]
        cv.poly(cape, _GOTH)
        cv.stroke(cape[1:6], 1.4, _rgba(_VIOLET, 190), joints=False)

    # ---- arms, crown, blade ------------------------------------------------------
    sl, sr = (-26.0, -142.0 + cb), (26.0, -142.0 + cb)
    if anim == "dash":
        tgt_l = (sl[0] + 66 * math.cos(2.95), sl[1] + 66 * math.sin(2.95))
        ha, blade_ang = 0.05, 0.0
    elif anim == "slash":
        tgt_l = (-44.0, -50.0 + cb * 0.4)
        ha = _lerp(-1.9, 1.2, _ease(k))
        blade_ang = ha + 0.3
    elif anim == "halo":
        e = _ease(min(1.0, k * 2.5))
        tgt_l = (sl[0] + 70 * math.cos(_lerp(1.6, -2.4, e)), sl[1] + 70 * math.sin(_lerp(1.6, -2.4, e)))
        ha = _lerp(0.85, -0.75, e)
        blade_ang = _lerp(ha + 0.45, -1.5, e)
    else:
        tgt_l = (-44.0 + math.sin(t * 1.55) * 2, -50.0 + cb * 0.4)
        ha = 0.85
        blade_ang = ha + 0.45
    el, hl = _ik2(sl, tgt_l, 44, 40, +1)
    tgt_r = (sr[0] + 78 * math.cos(ha), sr[1] + 78 * math.sin(ha))
    er, hr = _ik2(sr, tgt_r, 44, 40, -1)

    _crown_of_thorns(cv, (hl[0] + 2, hl[1] + 17 + math.sin(t * 1.7) * 1.5), 19, 9, 0.25, t)
    for s_, e_, h_ in ((sl, el, hl), (sr, er, hr)):
        cv.ribbon([s_, e_], [19, 15], _GOTH)
        cv.stroke([(s_[0] + 4, s_[1] + 2), (e_[0] + 3, e_[1] + 2)], 1.1, _rgba(_GOTH_HI, 190), joints=False)
        cv.ribbon([e_, h_], [11, 8.5], _BANDAGE)
        _wraps(cv, e_, h_, 11, 8.5, 6, _BANDAGE_SH)
        cv.ellipse(e_, 7.5, 7.5, _GOTH)
    _cross_blade(cv, hr, blade_ang, 112, 0.7 + 0.3 * math.sin(t * 3.0) + boost * 0.6, t)
    for h_ in (hl, hr):
        cv.ellipse(h_, 6.2, 5.6, _BANDAGE)
        cv.stroke([(h_[0] - 4, h_[1] - 1), (h_[0] + 4, h_[1] + 1)], 1.2, _BANDAGE_SH, joints=False)
        cv.stroke([(h_[0] - 3, h_[1] + 2), (h_[0] + 3, h_[1] + 4)], 1.2, _BANDAGE_SH, joints=False)
    if has("MANACLES"):
        for e_, h_ in ((el, hl), (er, hr)):
            dx, dy = _norm((h_[0] - e_[0], h_[1] - e_[1]))
            c = (h_[0] - dx * 8, h_[1] - dy * 8)
            ang = math.atan2(dy, dx) + math.pi / 2
            cv.ellipse(c, 8.6, 5.6, (74, 72, 90), ang)
            cv.ellipse(c, 6.2, 3.6, (34, 32, 44), ang)
            cv.stroke(_ellipse_pts(c, 8.2, 5.2, ang, 8, math.pi * 1.1, math.pi * 1.9), 1.1, (200, 200, 216), joints=False)
            _chain(cv, (c[0], c[1] + 5), (c[0] - 2, c[1] + 28), 4, 3)

    # ---- neck + bandages ----------------------------------------------------------
    cv.poly([(-7, -176 + cb), (7, -176 + cb), (8.5, -148 + cb), (-8.5, -148 + cb)], _SKIN)
    cv.poly([(2, -176 + cb), (7, -176 + cb), (8.5, -148 + cb), (4, -148 + cb)], _rgba(_SKIN_SH, 150))
    for j in range(4):
        y = -170 + j * 6 + cb * 0.6
        arc = _ellipse_pts((0, y), 9.6, 3.4, 0.0, 10, 0.02 * math.pi, 0.98 * math.pi)
        cv.stroke(arc, 4.6, _BANDAGE_SH, joints=False)
        cv.stroke(arc, 3.2, _BANDAGE, joints=False)

    # ---- head ---------------------------------------------------------------------
    hc = (-2.0, -198.0 + cb * 0.5)

    def H(pts: Sequence[Pt]) -> list[Pt]:
        return [(hc[0] + x, hc[1] + y) for x, y in pts]

    sway = math.sin(t * 1.4)
    for i, (ang, ln) in enumerate(((math.pi + 0.30, 56), (math.pi + 0.72, 50), (math.pi + 1.12, 40))):
        _feather(cv, (hc[0] - 19, hc[1] - 22), ang + sway * 0.05 * (i + 1), ln, 14, (28, 12, 48), (156, 88, 226))
    _face(cv, hc, _SKIN, _SKIN_SH, (206, 28, 56), (255, 96, 110), blink, smile=-0.2, left=True, right=False,
          brow=hair_d)
    # side locks, then the pointed ear pokes through them
    for sgn, ex_ in ((-1, -36), (1, 33)):
        lock = _bezier(H([(sgn * 23, -22)])[0], H([(sgn * 30, -2)])[0], H([(sgn * 28 + sway * 3, 24)])[0],
                       H([(ex_, 58 + sway * 3)])[0], 12)
        cv.ribbon(lock, [10, 13, 9, 0.8], hair_l)
        cv.stroke(lock[2:-1], 0.9, _rgba(hair_d, 150), joints=False)
    cv.poly(H([(-21, -3), (-41, -14), (-36, -6), (-34, 1), (-21, 9)]), _SKIN)
    cv.poly(H([(-23, -1), (-35, -9), (-31, -2), (-23, 5)]), _rgba(_SKIN_SH, 200))
    cv.stroke(_ellipse_pts(H([(-30, 0)])[0], 2.8, 3.4, 0.0, 10), 1.0, _STEEL)
    # bandaged right eye
    patch = H([(10.5, 2)])[0]
    cv.ellipse(patch, 11, 10.5, _BANDAGE)
    cv.stroke(_ellipse_pts(patch, 11, 10.5, 0.0, 16), 1.0, _BANDAGE_SH, closed=True, joints=False)
    for j in range(4):
        y = -6 + j * 5
        cv.stroke([(patch[0] - 9, patch[1] + y * 0.8 - 2), (patch[0] + 9, patch[1] + y * 0.8 + 3)], 1.0, _BANDAGE_SH,
                  joints=False)
    cv.ribbon(H([(-22, -15), (0, -17), (22, -10)]), [5, 5], _rgba(_BANDAGE, 235))
    cv.stroke(H([(-22, -12.5), (0, -14.5), (22, -7.5)]), 0.9, _BANDAGE_SH, joints=False)
    if has("DEPRIVATION"):
        cv.ribbon(H([(-25, 0), (0, 3), (25, 0)]), [15, 15], (16, 14, 22))
        cv.stroke(H([(-24, -5), (0, -2), (24, -5)]), 1.0, _rgba(_GOTH_HI, 200), joints=False)
    if has("IRON_GAG"):
        cv.ribbon(H([(-23, 16), (0, 18.5), (23, 16)]), [6.5, 6.5], (24, 20, 28))
        cv.poly(H([(-17, 14), (-11, 14), (-11, 21), (-17, 21)]), _STEEL)
        cv.ellipse(H([(-14, 17.5)])[0], 1.6, 1.6, (40, 38, 50))
    # fringe
    cap = _ellipse_pts((hc[0], hc[1] - 4), 26, 30, 0.0, 14, math.pi, 2 * math.pi)
    cap += H([(26, -12), (21, -5), (15, -17), (9, -3), (2, -19), (-5, -4), (-12, -18), (-18, -5), (-26, -12)])
    cv.poly(cap, hair_l)
    cv.stroke(_ellipse_pts((hc[0], hc[1] - 4), 22, 26, 0.0, 12, math.pi * 1.15, math.pi * 1.8), 1.2, _rgba(hair_m, 190),
              joints=False)
    cv.poly(H([(6, -20), (25, -16), (28, -3), (23, 3), (19, -6), (14, -12), (8, -14)]), _rgba(hair_l, 240))
    # halo
    pw = 0.78 + 0.22 * math.sin(t * 3.1)
    hx, hy = hc[0] + 3, hc[1] - 54 + math.sin(t * 2.1) * 2
    rx = 46.0
    if anim == "halo":
        ch_ = _ease(min(1.0, k / 0.38))
        rx *= 1 + 0.28 * ch_ * (1 - _ease((k - 0.38) / 0.3))
        pw = min(1.4, pw + 0.9 * ch_)
        cv.glow((hx, hy), 70 * ch_ + 20, (210, 100, 255), 0.45 * ch_)
    _halo_ring(cv, (hx, hy), rx, 14.0, -0.16, t, pw)

    # ---- skill FX ------------------------------------------------------------------
    if anim == "slash" and 0.08 < k < 0.98:
        a1 = _lerp(-1.9, 1.2, _ease(k))
        path = [(sr[0] + 190 * math.cos(a1 - 1.15 * (1 - s)), sr[1] + 190 * math.sin(a1 - 1.15 * (1 - s)))
                for s in (i / 14 for i in range(15))]
        fade = 1.0 - _ease((k - 0.55) / 0.43)
        cv.ribbon(path, [0.5, 26, 13], _rgba((150, 70, 235), 150 * fade))
        cv.ribbon(path, [0.3, 11, 5], _rgba((245, 226, 255), 215 * fade))
    if anim == "halo" and k > 0.34:
        kk = (k - 0.34) / 0.66
        cx, cy = 0.0, -90.0
        cv.glow((cx, cy), 150 * (1 - kk) + 20, (255, 210, 255), 0.7 * (1 - kk))
        for lag, wd in ((0.0, 12), (0.18, 7)):
            q = _clamp((kk - lag) / (1 - lag))
            if q <= 0:
                continue
            r = 30 + q * 215
            ring = _ellipse_pts((cx, cy), r, r * 0.62, 0.0, 56)
            cv.stroke(ring, wd * (1 - q) + 2, _rgba((200, 100, 255), 210 * (1 - q)), closed=True, joints=False)
            cv.stroke(ring, 2.0, _rgba((255, 236, 255), 235 * (1 - q)), closed=True, joints=False)
        for j in range(18):
            th = j * 2 * math.pi / 18 + 0.2
            r0, r1 = 30 + kk * 130, 30 + kk * 215
            cv.stroke([(cx + math.cos(th) * r0, cy + math.sin(th) * r0 * 0.62),
                       (cx + math.cos(th) * r1, cy + math.sin(th) * r1 * 0.62)], 2.0,
                      _rgba((230, 150, 255), 200 * (1 - kk)), joints=False)
    cv.off = (0.0, 0.0)


# ==========================================================================
#  Witch painter
# ==========================================================================
_LACE = (214, 210, 226)
_ROBE = (27, 25, 35)


def _lace_row(cv: VectorCanvas, pts: Sequence[Pt], r: float) -> None:
    """Scalloped lace trim: little pale beads with a dark pin-prick."""
    for x, y in pts:
        cv.ellipse((x, y), r, r * 0.85, _LACE, n=10)
        cv.ellipse((x, y + r * 0.1), r * 0.38, r * 0.3, (70, 64, 86), n=6)


def _lace_cuff(cv: VectorCanvas, wrist: Pt, d: Pt, w: float, t: float) -> None:
    """Torn bell-sleeve cuff whose ragged lace points along `d`."""
    n = (-d[1], d[0])
    cnt = 9
    bases = [(wrist[0] + n[0] * (j / (cnt - 1) - 0.5) * w, wrist[1] + n[1] * (j / (cnt - 1) - 0.5) * w) for j in range(cnt)]
    tips = []
    for j, b in enumerate(bases):
        ln = 9 + ((j * 5) % 3) * 4 + math.sin(t * 2.0 + j) * 1.2
        tips.append((b[0] + d[0] * ln + n[0] * 1.5, b[1] + d[1] * ln + n[1] * 1.5))
    poly: list[Pt] = [bases[0]]
    for j in range(cnt):
        poly.append(tips[j])
        if j < cnt - 1:
            poly.append(((bases[j][0] + bases[j + 1][0]) / 2, (bases[j][1] + bases[j + 1][1]) / 2))
    poly.append(bases[-1])
    cv.poly(poly, (238, 234, 246))
    cv.stroke(poly, 0.8, (70, 64, 86), closed=True, joints=False)
    cv.stroke(bases, 2.6, _LACE, joints=False)


def _curse_ground(cv: VectorCanvas, k: float, t: float) -> None:
    grow = _ease(min(1.0, k * 1.5))
    a = 1.0 if k < 0.7 else 1.0 - (k - 0.7) / 0.3
    r = _lerp(30, 215, grow)
    ry = r * 0.22
    c = (0.0, GROUND - 4.0)
    ring = _ellipse_pts(c, r, ry, 0.0, 56)
    cv.poly(ring, (90, 10, 40, int(70 * a)))
    cv.stroke(ring, 5, _rgba((255, 70, 110), 110 * a), closed=True, joints=False)
    cv.stroke(ring, 2, _rgba((255, 200, 210), 230 * a), closed=True, joints=False)
    cv.stroke(_ellipse_pts(c, r * 0.78, ry * 0.78, 0.0, 48), 1.4, _rgba((255, 120, 150), 200 * a), closed=True,
              joints=False)
    for j in range(20):
        th = t * 0.8 + j * 2 * math.pi / 20
        cv.stroke([(c[0] + math.cos(th) * r * 0.98, c[1] + math.sin(th) * ry * 0.98),
                   (c[0] + math.cos(th) * r * 0.80, c[1] + math.sin(th) * ry * 0.80)], 1.4,
                  _rgba((255, 150, 175), 200 * a), joints=False)
    star = [(c[0] + math.cos(-math.pi / 2 + t * 0.6 + i * 2 * math.pi / 5) * r * 0.78,
             c[1] + math.sin(-math.pi / 2 + t * 0.6 + i * 2 * math.pi / 5) * ry * 0.78) for i in range(5)]
    cv.stroke([star[i] for i in (0, 2, 4, 1, 3, 0)], 1.6, _rgba((255, 150, 180), 210 * a), joints=False)
    if k > 0.2:
        rise = _ease((k - 0.2) / 0.5)
        for j in range(10):
            th = j * 2 * math.pi / 10 + 0.3
            bx, by = c[0] + math.cos(th) * r * 0.8, c[1] + math.sin(th) * ry * 0.8
            h = (60 + 30 * math.sin(j * 2.3 + t * 3)) * rise
            wob = math.sin(t * 5 + j) * 8
            path = _bezier((bx, by), (bx + wob * 0.5, by - h * 0.35), (bx - wob, by - h * 0.7), (bx + wob * 0.6, by - h), 10)
            cv.ribbon(path, [4, 3, 1.5, 0.3], _rgba((210, 24, 60), 200 * a))
    cv.glow(c, r * 0.6, (255, 60, 100), 0.25 * a)


def _barrier_dome(cv: VectorCanvas, frac: float, k: float, casting: bool, t: float) -> None:
    grow = _ease(min(1.0, k * 1.8)) if casting else 1.0
    a = 1.0 if casting else 0.35 + 0.65 * frac
    cx, cy = 0.0, -66.0
    rx, ry = 112.0 * grow, 172.0 * grow
    if rx < 4:
        return
    pulse = 0.8 + 0.2 * math.sin(t * 3.0)
    ring = _ellipse_pts((cx, cy), rx, ry, 0.0, 64)
    cv.poly(ring, (90, 40, 150, int(34 * a)))
    cv.stroke(ring, 6, _rgba((150, 70, 230), 70 * a * pulse), closed=True, joints=False)
    cv.stroke(ring, 2.2, _rgba((214, 160, 255), 210 * a * pulse), closed=True, joints=False)
    for m in (0.38, 0.72):
        cv.stroke(_ellipse_pts((cx, cy), rx * m, ry, 0.0, 40), 1.0, _rgba((190, 120, 255), 70 * a), closed=True, joints=False)
    for m in (-0.5, 0.0, 0.5):
        cv.stroke(_ellipse_pts((cx, cy + ry * m), rx * math.sqrt(1 - m * m), ry * 0.12, 0.0, 36), 1.0,
                  _rgba((190, 120, 255), 60 * a), closed=True, joints=False)
    th = t * 1.2
    cv.stroke(_ellipse_pts((cx, cy), rx * 0.96, ry * 0.96, 0.0, 14, th, th + 1.0), 3.2, _rgba((255, 236, 255), 160 * a),
              joints=False)
    for j in range(6):
        ang = t * 0.7 + j * 1.05
        cv.ellipse((cx + math.cos(ang) * rx * 0.8, cy + math.sin(ang * 1.3) * ry * 0.8), 1.8, 1.8, (255, 240, 255, 200))


def _paint_witch(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    hair_l, hair_m, hair_d = _WITCH_HAIR
    bob = math.sin(t * 1.8) * 1.6
    breath = math.sin(t * 2.0)
    cb = breath * 1.6
    ph = (t + 1.3) % 5.1
    blink = math.sin(math.pi * ph / 0.14) if ph < 0.14 else 0.0
    wind = math.sin(t * 0.9)

    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 60, 9, (0, 0, 0, 80))
    if anim == "curse":
        _curse_ground(cv, k, t)
    cv.off = (0.0, bob)

    # ---- back hair -------------------------------------------------------------
    mass = [(-30, -200), (-48, -170), (-66, -110), (-82, -30 + wind * 4), (-94, 40 + wind * 6), (-70, 72), (-40, 50),
            (-10, 30), (12, 30), (34, 62), (54, 12 + wind * 3), (60, -80), (46, -170), (30, -200)]
    cv.poly(_smooth_closed(mass, 4), hair_m)
    for i in range(14):
        f = i / 13
        sx, sy = _lerp(-36, 36, f), -176 + abs(f - 0.5) * 10
        ex = _lerp(-122, 62, f) + ((i * 7) % 5 - 2) * 7
        ey = 24 + (i * 13) % 90
        col = hair_l if i % 3 else _mix(hair_l, hair_m, 0.5)
        _strand(cv, (sx, sy), (ex, ey), (ex - sx) * 0.35, 15, col, hair_d, t, i * 0.7, 6 + (i % 4) * 2.5)

    # ---- hood (back dome) --------------------------------------------------------
    seg1 = _bezier((-40, -146), (-58, -178), (-52, -250), (-6, -268), 14)
    seg2 = _bezier((-6, -268), (36, -282), (62, -215), (46, -150), 14)
    dome = seg1 + seg2[1:] + [(0, -138)]
    cv.poly(dome, (24, 22, 32))
    cv.stroke(seg1 + seg2[1:], 1.6, _rgba(_GOTH_HI, 170), joints=False)

    # ---- left leg (right one is drawn in the skirt slit) ---------------------------
    def hem_y(x: float) -> float:
        return 96 + 5 * math.sin(x * 0.09 + t * 1.4)

    cv.ribbon(_catmull([(-12, -6), (-16, 52), (-18, 100), (-20, 122)], 6), [17, 15, 10, 7.5], (22, 20, 30))
    cv.poly([(-31, 114), (-12, 114), (-9, 127), (-27, 135), (-39, 133)], (18, 16, 24))
    cv.ellipse((-35, 132.5), 2.2, 1.8, _rgba((200, 200, 216), 220))

    # ---- robe ----------------------------------------------------------------------
    xs = [-72 + 12 * i for i in range(13)]
    robe = [(-30, -146), (-34, -110), (-28, -74), (-30, -30), (-52, 40)] + [(x, hem_y(x)) for x in xs] + \
           [(52, 40), (30, -30), (28, -74), (34, -110), (30, -146)]
    cv.poly(robe, _ROBE)
    for x in (-44, -28, -12, 40, 52):
        cv.stroke([(x * 0.45, -20), (x * 1.18, hem_y(x))], 1.0, (64, 58, 80, 140), joints=False)
    cv.stroke([(-34, -110), (-28, -74), (-30, -30), (-52, 40), (-72, hem_y(-72))], 1.2, _rgba(_GOTH_HI, 170), joints=False)
    cv.stroke([(34, -110), (28, -74), (30, -30), (52, 40), (72, hem_y(72))], 1.2, _rgba(_GOTH_HI, 170), joints=False)
    _lace_row(cv, [(x, hem_y(x) + 2) for x in xs], 4.8)
    # white cross emblem
    cv.stroke([(-38, 8), (-38, 30)], 3.2, (236, 232, 242), joints=False)
    cv.stroke([(-46, 15), (-30, 15)], 3.2, (236, 232, 242), joints=False)
    # skirt slit with the stocking leg
    cv.poly([(8, -8), (30, -8), (47, 98), (2, 98)], (14, 12, 20))
    leg = _catmull([(13, -6), (20, 52), (19, 100), (20, 122)], 6)
    cv.ribbon(leg, [17, 15, 10, 7.5], (22, 20, 30))
    for off, amp, a_ in ((0.0, 5.0, 210), (2.5, 3.5, 150)):
        wave = []
        for i, (x, y) in enumerate(leg[2:-4]):
            wave.append((x + math.sin(i * 0.55 + off) * amp, y))
        cv.stroke(wave, 1.2, _rgba((196, 196, 214), a_), joints=False)
    cv.poly([(8, 114), (28, 114), (31, 126), (14, 135), (2, 133)], (18, 16, 24))
    cv.ellipse((6, 132.5), 2.2, 1.8, _rgba((200, 200, 216), 220))
    cv.stroke([(8, -8), (2, 98)], 1.4, _rgba(_LACE, 220), joints=False)
    cv.stroke([(30, -8), (47, 98)], 1.4, _rgba(_LACE, 220), joints=False)

    # ---- bodice, straps, belt ----------------------------------------------------------
    ch = 1.0 + 0.012 * breath
    cv.poly([(-14 * ch, -148 + cb), (14 * ch, -148 + cb), (19 * ch, -100 + cb * 0.6), (17, -72), (-17, -72),
             (-19 * ch, -100 + cb * 0.6)], (236, 232, 242))
    cv.stroke([(0, -146 + cb), (0, -74)], 0.9, (184, 178, 198), joints=False)
    cv.stroke([(-26, -142 + cb), (10, -84)], 3.2, (28, 26, 36), joints=False)
    cv.stroke([(26, -142 + cb), (-10, -84)], 3.2, (28, 26, 36), joints=False)
    cv.ribbon([(-20, -72), (0, -70), (20, -72)], [6, 6], (30, 28, 40))
    cv.ellipse((0, -71), 3.4, 3.0, (200, 200, 216))
    # shoulder capelet with scalloped lace
    cape = [(-34, -152 + cb), (-42, -134 + cb), (-40, -114 + cb), (-24, -122 + cb), (0, -112 + cb), (24, -122 + cb),
            (40, -114 + cb), (42, -134 + cb), (34, -152 + cb), (0, -160 + cb)]
    cv.poly(cape, (32, 30, 42))
    _lace_row(cv, [(-40, -113 + cb), (-32, -116 + cb), (-24, -120 + cb), (-16, -118 + cb), (-8, -114 + cb), (0, -111 + cb),
                   (8, -114 + cb), (16, -118 + cb), (24, -120 + cb), (32, -116 + cb), (40, -113 + cb)], 3.6)

    # ---- staff + arms ------------------------------------------------------------------------
    s1 = _pulse(min(1.0, k * 2.0)) if anim == "bolt" else 0.0
    s2 = _pulse(min(1.0, k * 2.2)) if anim == "curse" else 0.0
    grip = (-54.0 + 10 * s1, -66.0 - 8 * s1 - 16 * s2 + cb * 0.3)
    tilt = -0.11 + 0.60 * s1 - 0.05 * s2
    u = (math.sin(tilt), -math.cos(tilt))
    nrm = (-u[1], u[0])
    bottom = (grip[0] - u[0] * 130, grip[1] - u[1] * 130)
    top = (grip[0] + u[0] * 132, grip[1] + u[1] * 132)
    cv.stroke([bottom, top], 5.2, (36, 24, 46))
    cv.stroke([(bottom[0] + 1.2, bottom[1]), (top[0] + 1.2, top[1])], 1.0, _rgba(_GOLD, 150), joints=False)
    for q in (-96, 36, 70, 104):
        c_ = (grip[0] + u[0] * q, grip[1] + u[1] * q)
        cv.stroke([(c_[0] - nrm[0] * 3.4, c_[1] - nrm[1] * 3.4), (c_[0] + nrm[0] * 3.4, c_[1] + nrm[1] * 3.4)], 2.4, _GOLD,
                  joints=False)
    gp = (grip[0] + u[0] * 16, grip[1] + u[1] * 16)
    for sgn in (-1, 1):
        cv.stroke(_bezier(gp, (gp[0] + nrm[0] * 9 * sgn, gp[1] + nrm[1] * 9 * sgn),
                          (gp[0] + nrm[0] * 17 * sgn + u[0] * 2, gp[1] + nrm[1] * 17 * sgn + u[1] * 2),
                          (gp[0] + nrm[0] * 20 * sgn + u[0] * 12, gp[1] + nrm[1] * 20 * sgn + u[1] * 12), 8), 2.8, _GOLD)
    for sgn in (-1, 1):
        a_ = (top[0] - u[0] * 6, top[1] - u[1] * 6)
        path = _bezier(a_, (a_[0] + nrm[0] * 14 * sgn + u[0] * 4, a_[1] + nrm[1] * 14 * sgn + u[1] * 4),
                       (a_[0] + nrm[0] * 30 * sgn + u[0] * 26, a_[1] + nrm[1] * 30 * sgn + u[1] * 26),
                       (a_[0] + nrm[0] * 10 * sgn + u[0] * 52, a_[1] + nrm[1] * 10 * sgn + u[1] * 52), 12)
        cv.stroke(path, 6, (30, 20, 38))
        cv.stroke(path, 3.0, _GOLD)
        for i in (3, 6, 9):
            x, y = path[i]
            cv.poly([(x - 2, y), (x + 2, y), (x + nrm[0] * 6 * sgn, y + nrm[1] * 6 * sgn)], (150, 110, 60))
    orb = (top[0] + u[0] * 14, top[1] + u[1] * 14)
    og = 0.55 + 0.25 * math.sin(t * 3.2) + (0.6 * _pulse(min(1.0, k * 2.5)) if anim == "bolt" else 0.0)
    cv.glow(orb, 30 * (1 + 0.3 * og), (255, 40, 70), 0.55 * og)
    cv.ellipse(orb, 7.5, 7.5, (220, 24, 44))
    cv.ellipse((orb[0] - 1.8, orb[1] - 2.2), 2.6, 2.2, (255, 140, 150))
    if anim == "bolt" and k < 0.45:
        q = k / 0.45
        cv.stroke(_ellipse_pts(orb, 22 * q + 6, 22 * q + 6, 0.0, 28), 1.6, _rgba((255, 120, 150), 220 * (1 - q * 0.5)),
                  closed=True, joints=False)
        for j in range(6):
            th = t * 5 + j * 1.05
            cv.ellipse((orb[0] + math.cos(th) * 20 * (1 - q) + 4, orb[1] + math.sin(th) * 20 * (1 - q)), 1.6, 1.6,
                       (255, 190, 200, 220))

    sl, sr = (-31.0, -140.0 + cb), (31.0, -140.0 + cb)
    el, hl = _ik2(sl, grip, 46, 44, +1)
    tgt_r = (13.0, -128.0 + cb) if anim != "curse" else (46.0 + 20 * s2, -150.0 - 20 * s2)
    er, hr = _ik2(sr, tgt_r, 46, 44, -1)
    for s_, e_, h_ in ((sl, el, hl), (sr, er, hr)):
        dv = _norm((h_[0] - e_[0], h_[1] - e_[1]))
        wrist = (h_[0] - dv[0] * 12, h_[1] - dv[1] * 12)
        path = _catmull([s_, e_, wrist], 7)
        cv.ribbon(path, [20, 24, 36], _ROBE)
        cv.stroke(path, 1.1, _rgba(_GOTH_HI, 170), joints=False)
        _lace_cuff(cv, wrist, dv, 30, t)
        cv.ellipse(h_, 7.2, 6.6, (38, 36, 48))
        for off in (-3.5, 0.0, 3.5):
            cv.stroke([(h_[0] + off, h_[1] - 2), (h_[0] + off * 1.2, h_[1] + 5)], 1.1, (70, 66, 84), joints=False)

    # ---- neck, face ---------------------------------------------------------------------------------
    cv.poly([(-7, -176 + cb), (7, -176 + cb), (8.5, -148 + cb), (-8.5, -148 + cb)], (250, 240, 245))
    cv.ribbon([(-9, -153 + cb), (0, -150 + cb), (9, -153 + cb)], [4.4, 4.4], (28, 26, 36))
    cv.stroke([(0, -150 + cb), (0, -143 + cb)], 1.0, _STEEL, joints=False)
    cv.stroke([(-2, -146 + cb), (2, -146 + cb)], 1.0, _STEEL, joints=False)
    hc = (0.0, -196.0 + cb * 0.4)

    def H(pts: Sequence[Pt]) -> list[Pt]:
        return [(hc[0] + x, hc[1] + y) for x, y in pts]

    cv.ellipse((hc[0], hc[1] - 2), 31, 37, (14, 12, 20))
    _face(cv, hc, (251, 241, 246), (224, 206, 222), (200, 22, 52), (255, 84, 96), blink, smile=0.9, brow=hair_d)
    # fringe, parted left of centre
    cv.poly(H([(-2, -33), (-20, -26), (-26, -8), (-23, 11), (-17, -2), (-10, -14), (0, -21)]), hair_l)
    cv.poly(H([(-2, -33), (22, -26), (27, -8), (24, 9), (18, -4), (11, -14), (2, -21)]), hair_l)
    cv.stroke(H([(-2, -31), (-14, -20), (-20, -6)]), 1.0, _rgba(hair_d, 170), joints=False)
    cv.stroke(H([(0, -31), (14, -20), (19, -6)]), 1.0, _rgba(hair_d, 170), joints=False)
    # hood front: rim, lace and drapes
    rim = _ellipse_pts((hc[0], hc[1] - 2), 31, 37, 0.0, 28, 0.85 * math.pi, 2.15 * math.pi)
    cv.stroke(rim, 8.0, (26, 24, 34))
    _lace_row(cv, _ellipse_pts((hc[0], hc[1] - 2), 36, 42, 0.0, 22, 0.88 * math.pi, 2.12 * math.pi), 3.0)
    for sgn in (-1, 1):
        drape = [(sgn * 34, -188 + cb), (sgn * 47, -160 + cb), (sgn * 54, -134 + cb), (sgn * 38, -142 + cb),
                 (sgn * 30, -128 + cb), (sgn * 26, -160 + cb)]
        cv.poly(drape, (26, 24, 34))
        cv.stroke(drape[:4], 1.4, _rgba(_LACE, 200), joints=False)
    # long locks falling over the capelet
    for sx, ex_, ph_ in ((-30, -40, 0.3), (-24, -26, 1.4), (30, 44, 2.1), (24, 28, 3.0)):
        _strand(cv, (sx, -162 + cb), (ex_, -62), (ex_ - sx) * 0.4, 12, hair_l, hair_d, t, ph_, 3.5)

    # ---- skill FX -----------------------------------------------------------------------------------------
    if anim == "bolt" and k >= 0.4:
        q = (k - 0.4) / 0.6
        px, py = orb[0] + q * 320, orb[1] - q * 28
        fade = 1.0 - _ease((q - 0.8) / 0.2)
        trail = [(px - 110 * s, py + 9 * s + math.sin(t * 20 + s * 6) * 2.0) for s in (i / 12 for i in range(13))][::-1]
        cv.ribbon(trail, [0.4, 8, 15], _rgba((255, 60, 120), 150 * fade))
        cv.ribbon(trail, [0.3, 3, 6], _rgba((255, 220, 235), 220 * fade))
        cv.glow((px, py), 30, (255, 70, 130), 0.8 * fade)
        cv.ellipse((px, py), 6, 6, _rgba((255, 245, 250), 255 * fade))
    if anim == "curse" and k < 0.5:
        cv.glow(orb, 50 * _pulse(k * 2) + 10, (255, 50, 90), 0.5 * _pulse(k * 2))
    pw = p if hasattr(p, "barrier") else None
    bar = getattr(pw, "barrier", 0) if pw else 0
    bar_max = max(1, getattr(pw, "barrier_max", 1)) if pw else 1
    if bar > 0 or anim == "barrier":
        _barrier_dome(cv, bar / bar_max if bar_max else 1.0, k, anim == "barrier", t)
    cv.off = (0.0, 0.0)


def _paint_warrior(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Warrior: grounded red war-cloak, exposed greaves and a diagonal greatsword."""
    bob = math.sin(t * 2.0) * 1.4
    rage = int(getattr(p, "rage", 0))
    red = (151, 39, 49) if rage < 70 else (224, 58, 55)
    dark, steel, gold = (35, 27, 39), (121, 126, 145), (226, 176, 104)
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 49, 8, (0,0,0,90))
    cv.off = (0.0, bob)
    cv.poly([(-24,-153),(-42,-117),(-51,-35),(-34,-48),(-20,-7),(0,-26),(18,-7),(37,-47),(52,-28),(43,-118),(24,-153)], red)
    cv.poly([(-21,-149),(-17,-104),(-23,-46),(-12,-9),(-4,-8),(-4,-56),(-7,-104)], dark)
    cv.poly([(8,-104),(6,-55),(13,-8),(29,-8),(21,-47),(20,-105)], dark)
    cv.poly([(-29,-155),(-23,-172),(0,-179),(24,-172),(30,-155),(18,-124),(0,-114),(-18,-124)], steel)
    cv.poly([(-24,-151),(0,-165),(24,-151),(15,-129),(0,-119),(-15,-129)], red)
    cv.ellipse((0,-194),19,23,(219,176,151))
    cv.poly([(-22,-202),(-17,-220),(5,-228),(23,-210),(17,-195),(8,-206),(-9,-211),(-18,-198)], dark)
    cv.stroke([(-12,-188),(0,-184),(12,-188)], 1.5, (88,31,36), joints=False)
    # Full-length blade, guard and hot fuller create a strong asymmetric outline.
    cv.stroke([(25,-95),(43,-73),(75,-20)], 7.0, steel, joints=False)
    cv.stroke([(25,-95),(43,-73),(75,-20)], 1.2, gold, joints=False)
    cv.stroke([(18,-91),(36,-80)], 4.0, gold, joints=False)
    for yy in (-130,-122,-114):
        cv.stroke([(-9,yy),(9,yy+3)], 1.0, gold, joints=False)
    if anim == "slash" and k < 0.8:
        cv.stroke(_bezier((22,-105),(55,-91),(69,-45),(81,-27),14), 7*(1-k), _rgba((255,128,104),190*(1-k)), joints=False)
    if rage >= 70:
        cv.glow((0,-125),18,(255,67,55),0.35)
    cv.off = (0.0, 0.0)


def _paint_tank(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Tank: broad blue steel silhouette, grounded stance and an unmistakable kite shield."""
    bob = math.sin(t * 1.45) * 0.7
    bastion = int(getattr(p, "bastion", 0))
    blue = (59,92,137)
    steel, gold, dark = (92,108,133), (224,199,145), (26,30,43)
    cv.off = (0.0,0.0)
    cv.ellipse((0,GROUND),54,8,(0,0,0,95))
    cv.off = (0.0,bob)
    cv.poly([(-24,-151),(-41,-122),(-42,-42),(-27,-7),(-9,-7),(-7,-76),(8,-76),(12,-7),(31,-7),(44,-42),(38,-122),(23,-151)], dark)
    cv.poly([(-32,-153),(-24,-173),(24,-173),(32,-153),(29,-111),(17,-83),(-17,-83),(-29,-111)], steel)
    cv.poly([(-22,-151),(0,-166),(22,-151),(15,-125),(0,-111),(-15,-125)], blue)
    cv.poly([(-25,-165),(-20,-184),(0,-190),(20,-184),(25,-165),(12,-171),(-12,-171)], steel)
    cv.ellipse((0,-193),18,21,(204,166,145))
    cv.poly([(-22,-202),(-19,-218),(0,-228),(19,-218),(22,-202),(8,-207),(-8,-207)], dark)
    cv.stroke([(-9,-190),(9,-190)], 2.2, (133,202,255), joints=False)
    # Shield is larger than the arm, with nested plates and a bright boss.
    cv.poly([(-43,-140),(-76,-125),(-74,-81),(-57,-52),(-38,-82),(-33,-124)], blue)
    cv.poly([(-47,-129),(-65,-116),(-64,-86),(-57,-69),(-46,-89)], (92,143,189))
    cv.poly([(-59,-119),(-54,-106),(-59,-92),(-64,-106)], gold)
    cv.glow((-57,-104),9,(141,208,255),0.38)
    cv.stroke([(24,-103),(38,-79),(32,-50)], 6.0, steel, joints=False)
    if anim in ("barrier", "halo") or bastion >= 3:
        cv.glow((0,-105),45,(90,165,255),0.38)
        cv.ellipse((0,-103),48,65,(75,145,238,24),(132,194,255),1.2)
    cv.off=(0.0,0.0)


def _paint_rogue(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Rogue: light asymmetric hood, short split coat, twin daggers and quick afterimages."""
    bob = math.sin(t * 2.8) * 1.8
    combo = int(getattr(p, "combo", 0))
    green = (83,217,147)
    dark, cloth, skin = (20,25,37), (33,42,49), (213,169,148)
    cv.off=(0.0,0.0)
    cv.ellipse((0,GROUND),41,7,(0,0,0,90))
    cv.off=(0.0,bob)
    cv.poly([(-20,-151),(-37,-117),(-30,-65),(-50,-12),(-22,-23),(0,-52),(23,-22),(47,-7),(35,-68),(41,-118),(21,-151)], dark)
    cv.poly([(-18,-147),(0,-158),(20,-146),(15,-106),(-16,-106)], cloth)
    cv.poly([(-25,-168),(-19,-210),(3,-229),(24,-210),(25,-180),(12,-202),(-9,-204)], dark)
    cv.ellipse((1,-193),17,21,skin)
    cv.poly([(-18,-202),(0,-217),(19,-202),(11,-197),(-10,-198)], dark)
    cv.stroke([(-10,-189),(-3,-190)],2.0,green,joints=False)
    cv.stroke([(5,-190),(11,-189)],2.0,green,joints=False)
    cv.stroke([(-18,-104),(18,-105)],3.0,(194,172,111),joints=False)
    cv.stroke([(24,-87),(42,-63),(63,-31)],3.5,green,joints=False)
    cv.stroke([(-24,-87),(-42,-62),(-62,-34)],3.5,green,joints=False)
    cv.stroke([(63,-31),(55,-36),(58,-27)],1.0,(225,242,231),joints=False)
    cv.stroke([(-62,-34),(-55,-38),(-57,-29)],1.0,(225,242,231),joints=False)
    for x,y in ((-22,-132),(18,-130),(0,-118)):
        cv.glow((x,y),3,(95,226,156),0.35)
    if combo >= 3 or getattr(p,"shadowed",False):
        cv.glow((0,-119),26,green,0.22)
    if anim in ("dash","slash") and k < 0.8:
        for offset in (-13,13):
            cv.stroke(_bezier((offset,-83),(offset+30,-70),(offset+34,-46),(offset+51,-25),10),3*(1-k),_rgba(green,130*(1-k)),joints=False)
    cv.off=(0.0,0.0)


def _paint_generic(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Simple breathing silhouette for the classes that have no bespoke portrait."""
    bob = math.sin(t * 1.8) * 1.5
    breath = math.sin(t * 2.0) * 1.5
    acc = tuple(int(v) for v in p.accent[:3])
    dark = _mix(acc, (10, 10, 16), 0.65)
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 52, 8, (0, 0, 0, 80))
    cv.off = (0.0, bob)
    cv.poly([(-26, -150 + breath), (26, -150 + breath), (30, -20), (46, 118), (-46, 118), (-30, -20)], dark)
    cv.stroke([(-26, -150 + breath), (-30, -20), (-46, 118)], 2.0, acc, joints=False)
    cv.stroke([(26, -150 + breath), (30, -20), (46, 118)], 2.0, acc, joints=False)
    cv.ellipse((0, -186 + breath * 0.5), 22, 26, _SKIN)
    cv.poly(_ellipse_pts((0, -192 + breath * 0.5), 25, 27, 0.0, 14, math.pi, 2 * math.pi), dark)
    cv.stroke([(40, -60), (70, 60 + (_pulse(k) * -90 if anim else 0))], 4.0, (190, 190, 205))
    cv.off = (0.0, 0.0)


def _paint_kitsune(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Fox-spirit silhouette: swept tails, ear silhouette, talisman sash and foxfire."""
    bob = math.sin(t * 2.4) * 2.2
    sway = math.sin(t * 1.7) * 5.0
    awakened = getattr(p, "awakened_turns", 0) > 0
    fire = (255, 180, 96) if not awakened else (255, 231, 151)
    orange, dark, cream = (190, 75, 43), (38, 19, 31), (244, 218, 185)
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 52, 8, (0, 0, 0, 90))
    # Three broad tails sit behind the body; their moving tips convey a spirit rather than a rogue reskin.
    for side, phase in ((-1, 0.0), (1, 1.3), (0, 2.4)):
        tip = math.sin(t * 1.65 + phase) * 7.0
        path = _bezier((side * 5, -48), (side * 40, -56), (side * 57 + tip, -116),
                       (side * 31 + tip, -151 - 5 * math.sin(t + phase)), 18)
        cv.poly(_ribbon_poly(path, _widths(len(path) - 1, (3, 12, 16, 8, 0.5))), (111, 38, 42))
        inner = _bezier((side * 8, -55), (side * 36, -66), (side * 47 + tip, -116),
                        (side * 30 + tip, -145), 16)
        cv.stroke(inner, 2.3, cream, joints=False)
        cv.glow((side * 32 + tip, -130), 9 if awakened else 5, fire, 0.48)
    cv.off = (0.0, bob)
    # Split dancer's coat, armored waist and flowing sleeves.
    cv.poly([(-25,-150),( -38,-105),(-33,-47),(-49,-9),(-21,-20),(0,-58),(18,-17),(46,-8),(34,-63),(40,-112),(23,-151)], dark)
    cv.poly([(-23,-150),(0,-164),(23,-150),(15,-108),(0,-91),(-15,-108)], orange)
    cv.poly([(-20,-120),(0,-133),(20,-120),(13,-94),(0,-84),(-13,-94)], (61,34,39))
    cv.stroke([(-21,-117),(0,-130),(21,-117)], (247,193,119), 1.8, joints=False)
    # Fox ears and tousled hair frame the mask-like face.
    cv.poly([(-17,-201),(-30,-238),(-3,-220),(-2,-199)], orange)
    cv.poly([(8,-200),(29,-239),(27,-208),(15,-196)], orange)
    cv.poly([(-16,-207),(-23,-229),(-7,-215)], cream)
    cv.poly([(12,-207),(24,-230),(20,-211)], cream)
    cv.ellipse((0,-194), 20, 24, cream, orange, 1.2)
    cv.poly([(-21,-200),(-18,-218),(0,-230),(19,-216),(22,-198),(10,-208),(-10,-208)], dark)
    cv.poly([(-12,-194),(0,-198),(12,-194),(7,-185),(0,-182),(-7,-185)], (60,33,43))
    cv.stroke([(-11,-192),(-4,-190)], fire, 2.1, joints=False)
    cv.stroke([(4,-190),(11,-192)], fire, 2.1, joints=False)
    cv.stroke([(-4,-179),(0,-177),(4,-179)], dark, 1.2, joints=False)
    # Bell, paper talisman and paired spirit blades.
    cv.stroke([(-18,-91),(0,-86),(18,-91)], (234,195,122), 3.0, joints=False)
    cv.poly([(-6,-83),(6,-83),(5,-67),(-5,-67)], (234,216,174), (150,55,49), 1)
    cv.stroke([(26,-89),(42,-64),(57,-36)], fire, 4, joints=False)
    cv.stroke([(57,-36),(51,-40),(54,-29)], cream, 1.5, joints=False)
    cv.stroke([(-25,-89),(-42,-67),(-53,-43)], fire, 3.5, joints=False)
    cv.glow((42,-75), 16 if awakened else 9, fire, 0.55)
    if getattr(p, "decoy_turns", 0):
        cv.glow((0,-120), 38, (114,205,255), 0.28)
    if anim in ("foxfire", "masquerade", "ascend") and k < 0.8:
        fade = _ease(min(1.0, k * 1.7)) if anim != "ascend" else 1.0 - k * 0.55
        cv.glow((32, -117), 32, fire, 0.65 * fade)
        cv.stroke(_bezier((28,-116),(58,-134),(61,-93),(44,-82),12), fire, 3.0 * fade, joints=False)
    if awakened:
        for i in range(3):
            a = t * 0.7 + i * math.tau / 3
            cv.glow((math.cos(a)*37, -166 + math.sin(a)*15), 7, (255,226,143), 0.56)
    cv.off = (0.0, 0.0)


def _paint_vampire(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Vampire: high-collared wine-red coat, pale duelist face and orbiting blood sigils."""
    bob = math.sin(t * 1.7) * 1.5
    blood = int(getattr(p, "blood", 0))
    black, wine, red, silver = (22, 17, 29), (74, 18, 43), (210, 48, 81), (204, 197, 216)
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 50, 8, (0, 0, 0, 95))
    cv.off = (0.0, bob)
    cv.poly([(-20,-151),(-39,-120),(-43,-48),(-58,3),(-22,-14),(-4,-63),(0,-86),(9,-54),(32,-9),(55,2),(39,-56),(35,-121),(20,-151)], wine)
    cv.poly([(-18,-145),(0,-158),(19,-145),(23,-104),(8,-74),(0,-96),(-11,-75),(-23,-103)], black)
    cv.poly([(-24,-154),(-32,-177),(-18,-171),(0,-180),(18,-171),(32,-177),(24,-151),(0,-164)], black)
    cv.ellipse((0,-193),19,24,(222,181,164))
    cv.poly([(-22,-201),(-17,-218),(0,-230),(20,-216),(23,-197),(10,-208),(-8,-207),(-16,-197)], black)
    cv.stroke([(-11,-190),(-4,-191)], 2.0, (255,86,116), joints=False)
    cv.stroke([(5,-191),(12,-190)], 2.0, (255,86,116), joints=False)
    cv.poly([(-12,-121),(0,-130),(12,-121),(8,-105),(0,-99),(-8,-105)], wine)
    cv.stroke([(0,-120),(0,-104)], 1.2, (255,172,185), joints=False)
    cv.stroke([(27,-99),(39,-67),(62,-19)], 3.8, silver, joints=False)
    cv.stroke([(27,-99),(39,-67),(62,-19)], 1.4, red, joints=False)
    for i in range(3):
        a = t * 0.9 + i * math.tau / 3
        px, py = math.cos(a) * (35 + i * 2), -118 + math.sin(a) * 28
        cv.glow((px,py), 5 + blood / 35, red, 0.35 + blood / 200)
    if blood >= 65 or anim in ("blood", "ascend"):
        cv.glow((0,-121), 22 + blood * 0.08, red, 0.3 + blood / 300)
    if anim in ("blood", "dash", "mist", "ascend") and k < 0.92:
        fade = 1.0-k
        for side in (-1,1):
            path = _bezier((side*18,-73),(side*56,-88),(side*42,-39),(side*70,-25),12)
            cv.stroke(path, 2.5 * fade, _rgba(red, 200 * fade), joints=False)
            cv.glow(path[7], 12 * fade, red, 0.4 * fade)
    cv.off = (0.0, 0.0)


def _paint_dragonkin(cv: VectorCanvas, p: "Player", t: float, anim: Optional[str], k: float) -> None:
    """Dragonkin: plated scale silhouette, horned head, articulated tail and furnace core."""
    bob = math.sin(t * 1.65) * 1.1
    heat = int(getattr(p, "heat", 0))
    glow = min(1.0, 0.25 + heat / 130.0)
    scale_color = (116, 42, 35) if heat < 65 else (185, 60, 35)
    ember = (255, 121, 48) if heat < 65 else (255, 211, 94)
    dark, plate, gold = (29, 25, 35), (73, 70, 82), (224, 153, 89)
    cv.off = (0.0, 0.0)
    cv.ellipse((0, GROUND), 54, 8, (0,0,0,100))
    tail = _bezier((18,-49),(48,-38),(72,-63),(74,-100 + math.sin(t*1.8)*5),18)
    cv.stroke(tail, 12, dark, joints=False)
    cv.stroke(tail, 6, scale_color, joints=False)
    cv.off = (0.0, bob)
    cv.poly([(-23,-153),(-38,-125),(-34,-62),(-44,-12),(-21,-6),(-7,-50),(1,-78),(13,-45),(35,-8),(49,-15),(37,-71),(33,-125),(22,-153)], dark)
    cv.poly([(-25,-151),(-32,-172),(-18,-179),(0,-169),(18,-179),(32,-172),(25,-150),(0,-140)], plate)
    cv.poly([(-25,-154),(-14,-166),(0,-159),(13,-166),(25,-154),(19,-119),(0,-104),(-19,-119)], scale_color)
    for yy, width in ((-145,15),(-134,18),(-123,15)):
        for xx in (-width, 0, width):
            cv.poly([(xx-4,yy),(xx,yy-5),(xx+4,yy),(xx,yy+4)], (133,57,46))
    cv.glow((0,-128), 10 + heat * 0.05, ember, glow * 0.7)
    cv.poly([(-19,-201),(-30,-226),(-17,-220),(-11,-205),(11,-205),(17,-220),(30,-226),(19,-201)], dark)
    cv.ellipse((0,-192),19,22,(173,126,105))
    cv.poly([(-21,-199),(-16,-216),(0,-224),(17,-216),(22,-198),(10,-204),(-9,-204)], dark)
    cv.stroke([(-12,-188),(-4,-191)], 1.4, ember, joints=False)
    cv.stroke([(4,-191),(12,-188)], 1.4, ember, joints=False)
    cv.poly([(-24,-151),(-44,-163),(-54,-144),(-35,-126),(-22,-131)], plate)
    cv.poly([(24,-151),(44,-163),(54,-144),(35,-126),(22,-131)], plate)
    cv.stroke([(25,-94),(42,-74),(64,-26)], 6.5, plate, joints=False)
    cv.stroke([(25,-94),(42,-74),(64,-26)], 1.1, gold, joints=False)
    if heat > 55 or anim in ("breath", "wingbeat", "ascend"):
        for side in (-1,1):
            cv.glow((side*29,-119), 12 + heat*0.04, ember, glow*0.55)
    if anim in ("breath", "wingbeat", "ascend", "slash") and k < 0.95:
        fade = 1.0-k
        path = _bezier((12,-178),(42,-171),(58,-147),(88,-139),14)
        cv.ribbon(path, [1, 5, 11], _rgba(ember, 180 * fade))
        cv.glow(path[-1], 24 * fade, ember, 0.55 * fade)
    cv.off = (0.0, 0.0)


_PAINTERS = {PlayerClass.WARRIOR: _paint_warrior, PlayerClass.TANK: _paint_tank, PlayerClass.ROGUE: _paint_rogue,
             PlayerClass.ANGEL: _paint_angel, PlayerClass.WITCH: _paint_witch, PlayerClass.KITSUNE: _paint_kitsune,
             PlayerClass.VAMPIRE: _paint_vampire, PlayerClass.DRAGONKIN: _paint_dragonkin}


# ==========================================================================
#  Heroes
# ==========================================================================
class Player(BaseEntity):
    """Common hero logic: stamina/mana regeneration, aggro, levelling, cooldowns, portrait."""

    MAX_LEVEL = 30
    MAX_MASTERY_XP = 10_000_000

    def __init__(self, name: str, pclass: PlayerClass, hp: int, atk: int, df: int, speed: int,
                 mana: int = 0) -> None:
        super().__init__(name, hp, atk, df, speed)
        self.pclass = pclass
        self.max_stamina = 100
        self.stamina = 100
        self.max_mana = mana
        self.mana = mana
        self.aggro = 10.0
        self.level = 1
        self.xp = 0
        self.mastery_xp = 0  # overflow at level cap is recorded, never converted into runaway stats
        self.cooldowns: dict[str, int] = {}          # skill key -> turns left
        self.perks: dict[str, float] = {}            # R2 skill-tree runtime perks (see core.meta_progression.PERK_HELP)
        self._anim: Optional[str] = None             # active skill animation
        self._anim_t0 = 0.0
        self._sprite_cache: Optional[tuple[tuple, float, "pygame.Surface"]] = None

    def perk(self, key: str) -> float:
        """Value of a skill-tree runtime perk (0.0 when not unlocked)."""
        return float(getattr(self, "perks", {}).get(key, 0.0))

    @property
    def accent(self) -> Color:
        return CLASS_COLORS[self.pclass]

    @property
    def tagline(self) -> str:
        return f"{self.pclass.value}  Lv.{self.level}"

    @property
    def blackout(self) -> bool:
        """True when the HUD should be obscured for this hero (Sensory Deprivation)."""
        return False

    # ---- to be provided by each class -----------------------------------
    @abstractmethod
    def abilities(self) -> list[Ability]:
        """Actions available this turn (flags computed from current resources)."""

    @abstractmethod
    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        """Execute ability `key`. `ok` is the QTE result (None if no QTE was required)."""

    def class_bars(self) -> list[Bar]:
        return []

    def item_qte(self) -> Optional[QteKind]:
        return None

    def active_restraints(self) -> list[str]:
        """Labels of the restraints currently locked on this hero (none by default)."""
        return []

    # ---- skill cooldowns ----------------------------------------------------
    def cooldown_left(self, key: str) -> int:
        return self.cooldowns.get(key, 0)

    def ready(self, key: str) -> bool:
        return self.cooldown_left(key) <= 0

    def start_cooldown(self, key: str, turns: int) -> None:
        self.cooldowns[key] = max(0, turns)

    def tick_cooldowns(self) -> None:
        for key in list(self.cooldowns):
            self.cooldowns[key] -= 1
            if self.cooldowns[key] <= 0:
                del self.cooldowns[key]

    def cd_label(self, key: str, base: str, turns: int) -> str:
        left = self.cooldown_left(key)
        return f"{base}  CD {left}" if left else f"{base}  (CD {turns})"

    # ---- shared behaviour -------------------------------------------------
    def bars(self) -> list[Bar]:
        out = [Bar("STA", self.stamina, self.max_stamina, Pal.GOLD)]
        if self.max_mana:
            out.append(Bar("MP", self.mana, self.max_mana, Pal.BLUE))
        return out + self.class_bars()

    def hud_state(self) -> dict:
        """Snapshot for the HUD: HP/MP/STA, active restraints and skill cooldowns."""
        return {
            "name": self.name, "class": self.pclass.value, "level": self.level,
            "hp": (self.hp, self.max_hp), "mp": (self.mana, self.max_mana),
            "stamina": (self.stamina, self.max_stamina),
            "restraints": self.active_restraints(),
            "cooldowns": dict(self.cooldowns),
            "badges": [label for label, _ in self.badges()],
        }

    def spend_stamina(self, amount: int) -> None:
        self.stamina = max(0, self.stamina - amount)

    def on_turn_start(self, combat: CombatSystem) -> None:
        self.tick_cooldowns()
        sta_regen = 20 + getattr(self, "sta_regen_bonus", 0)
        self.stamina = min(self.max_stamina, self.stamina + sta_regen)
        if self.max_mana:
            mp_regen = 8 + getattr(self, "mp_regen_bonus", 0)
            self.mana = min(self.max_mana, self.mana + mp_regen)

    def on_deal_damage(self, dmg: int) -> None:
        self.aggro += dmg

    def gain_xp(self, amount: int) -> bool:
        """Grant XP on a bounded level curve; preserve overflow as non-stat mastery XP at cap."""
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("XP amount must be an integer")
        if amount < 0:
            raise ValueError("XP amount cannot be negative")
        self.xp = max(0, int(self.xp)) + amount
        leveled = False
        while self.level < self.MAX_LEVEL and self.xp >= 80 * self.level:
            self.xp -= 80 * self.level
            self.level += 1
            self.max_hp += 12
            self.base_attack += 2
            self.base_defense += 1
            if self.max_mana:
                self.max_mana += 5
            leveled = True
        if self.level >= self.MAX_LEVEL and self.xp:
            self.mastery_xp = min(self.MAX_MASTERY_XP, max(0, int(self.mastery_xp)) + self.xp)
            self.xp = 0
        return leveled

    def rest(self, hp_ratio: float = 1.0) -> None:
        """Full recovery between battles (hp_ratio = fraction restored if revived)."""
        self.hp = self.max_hp if self.alive else max(1, int(self.max_hp * hp_ratio))
        self.stamina, self.mana = self.max_stamina, self.max_mana
        self.cooldowns.clear()
        self.clear_statuses()

    def after_battle(self) -> None:
        self.clear_statuses()
        self.cooldowns.clear()
        self.aggro = 10.0

    # ---- portrait / animation ---------------------------------------------------
    def play_anim(self, name: str) -> None:
        """Start a skill animation ('slash', 'dash', 'halo', 'bolt', 'barrier', 'curse', 'hurt')."""
        if name == "hurt" and self._anim_state(time.perf_counter())[0] not in (None, "hurt"):
            return  # a hit never cuts a skill animation short
        self._anim, self._anim_t0 = name, time.perf_counter()

    def _anim_state(self, now: float) -> tuple[Optional[str], float]:
        if self._anim is None:
            return None, 0.0
        k = (now - self._anim_t0) / ANIM_LENGTH.get(self._anim, 0.6)
        if k >= 1.0 or k < 0.0:
            self._anim = None
            return None, 0.0
        return self._anim, k

    @staticmethod
    def fx_offset(name: Optional[str], k: float) -> tuple[float, float]:
        """Pixel offset (at scale 1, facing right) the sprite travels during a skill."""
        if name == "dash":
            return (_pulse(k) * 110.0, -_pulse(k) * 38.0)
        if name == "slash":
            return (_pulse(k) * 26.0, 0.0)
        if name in ("bolt", "curse"):
            return (-6.0 * _pulse(k), 0.0)
        if name == "hurt":
            return (math.sin(k * 38.0) * 6.0 * (1.0 - k), 0.0)
        return (0.0, 0.0)

    def render(self, surface: "pygame.Surface", pos: tuple[float, float], scale: float = 1.0, flip: bool = False,
               t: Optional[float] = None, ss: int = 2, idle_fps: float = 24.0,
               anim: Optional[tuple[Optional[str], float]] = None) -> "pygame.Rect":
        """Draw the hero with its feet on `pos` and return the blitted rect.

        While idle (real-time clock, no skill playing) the sprite is re-drawn `idle_fps` times a
        second and reused in between; skill animations redraw every call.  `anim=(name, progress)`
        forces a pose, e.g. for previews or screenshots.
        """
        real_time = t is None
        now = time.perf_counter() if real_time else t
        name, k = anim if anim is not None else self._anim_state(now)
        bar = getattr(self, "barrier", 0)
        bar_max = max(1, getattr(self, "barrier_max", 1))
        visual_state = tuple((attr, getattr(self, attr, None)) for attr in (
            "rage", "bastion", "combo", "spirit", "awakened_turns", "shadowed",
            "blood", "heat", "overheated_turns", "barrier", "lucidity", "tightness",
        ))
        key = (scale, ss, self.alive, int(8 * bar / bar_max) + (1 if bar else 0),
               tuple(self.active_restraints()), visual_state)
        sprite: Optional["pygame.Surface"] = None
        if real_time and name is None and self._sprite_cache is not None:
            c_key, c_time, c_sprite = self._sprite_cache
            if c_key == key and 0.0 <= now - c_time < 1.0 / max(1.0, idle_fps):
                sprite = c_sprite
        if sprite is None:
            cv = VectorCanvas(ss)
            _PAINTERS.get(self.pclass, _paint_generic)(cv, self, now, name, k)
            sprite = cv.surf
            size = (max(1, int(CANVAS_W * scale)), max(1, int(CANVAS_H * scale)))
            if sprite.get_size() != size:
                sprite = pygame.transform.smoothscale(sprite, size)
            if name == "hurt":
                sprite.fill((int(70 * (1.0 - k)), 0, 0, 0), special_flags=pygame.BLEND_RGB_ADD)
            if not self.alive:
                sprite.fill((70, 70, 82, 255), special_flags=pygame.BLEND_RGBA_MULT)
            self._sprite_cache = (key, now, sprite) if (real_time and name is None) else None
        if flip:
            sprite = pygame.transform.flip(sprite, True, False)
        dx, dy = self.fx_offset(name, k)
        dx *= scale * (-1.0 if flip else 1.0)
        dy *= scale
        return surface.blit(sprite, (int(pos[0] - CANVAS_OX * scale + dx),
                                     int(pos[1] - (CANVAS_OY + GROUND) * scale + dy)))


# --------------------------------------------------------------------------
class Warrior(Player):
    """Momentum bruiser: Rage is earned by fighting (and by bleeding) and fades when you stall."""

    RAGE_DECAY = 6

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.WARRIOR, 120, 16, 9, 8)
        self.rage = 0

    def on_turn_start(self, combat: CombatSystem) -> None:
        super().on_turn_start(combat)
        self.rage = max(0, self.rage - self.RAGE_DECAY)

    def abilities(self) -> list[Ability]:
        return [
            Ability("cleave", "Cleave Strike", "+18 Rage", Target.ENEMY,
                    hint=f"Damage grows with Rage. Rage fades {self.RAGE_DECAY} per turn."),
            Ability("rend", "Rending Blow", "20 STA  +25 Rage", Target.ENEMY, self.stamina >= 20,
                    hint="1.6x damage, leaves the foe Exposed."),
            Ability("execute", "Executioner's Verdict", "100% RAGE", Target.ENEMY, self.rage >= 100,
                    hint="3.5x damage; 1.5x more on wounded foes."),
            Ability("sweep", "Breaker Sweep", "35+ RAGE", Target.ALL_ENEMIES, self.rage >= 35,
                    hint="Spend all Rage to cut through every living foe; stronger with a full reserve."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        rage_extra = getattr(self, "rage_bonus", 0)
        if key == "cleave":
            if target is None:
                return
            combat.strike(self, target, 1.0 + self.rage * 0.004)
            self.rage = min(100, self.rage + 18 + rage_extra)
        elif key == "rend":
            if target is None:
                return
            self.spend_stamina(20)
            combat.strike(self, target, 1.6)
            target.add_status(Status.EXPOSED, 1)
            self.rage = min(100, self.rage + 25 + rage_extra)
        elif key == "execute":
            assert target is not None
            mult = 3.5 * (1.5 if target.hp_ratio < 0.35 else 1.0)
            combat.alert(f"{self.name}: EXECUTION!", Pal.RED)
            combat.shake(0.9)
            self.play_anim("slash")
            combat.strike(self, target, mult)
            self.rage = 0
        elif key == "sweep":
            if self.rage < 35:
                combat.alert("Breaker Sweep needs at least 35 Rage.", Pal.ORANGE)
                return
            spent, self.rage = self.rage, 0
            mult = 0.72 + spent * 0.0063
            self.play_anim("slash")
            combat.alert(f"BREAKER SWEEP — {spent} Rage committed.", Pal.RED)
            for foe in combat.enemies_alive():
                combat.strike(self, foe, mult)

    def on_hit_taken(self, dmg: int) -> None:
        self.rage = min(100, self.rage + 12)

    def class_bars(self) -> list[Bar]:
        return [Bar("RAGE", self.rage, 100, Pal.RED)]

    def after_battle(self) -> None:
        super().after_battle()
        self.rage = 0


class Tank(Player):
    """Retaliation wall: every blow absorbed charges Bastion, and Shield Bash spends it."""

    BASTION_MAX = 5
    PROVOKE_CD = 3

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.TANK, 170, 13, 16, 5)
        self.bastion = 0

    def abilities(self) -> list[Ability]:
        return [
            Ability("bash", "Shield Bash", "free  spends BASTION", Target.ENEMY,
                    hint=f"+25% damage per Bastion stack (all spent), extra aggro. "
                         f"{self.BASTION_MAX} stacks also Suppress the foe."),
            Ability("guard", "Bulwark Guard", "20 STA  +2 Bastion", Target.SELF, self.stamina >= 20,
                    hint="DEF x3, intercept single-target hits on allies, -40% boss heavy damage."),
            Ability("provoke", "Taunting Roar", self.cd_label("provoke", "15 STA", self.PROVOKE_CD), Target.SELF,
                    self.ready("provoke") and self.stamina >= 15,
                    hint="Enemies must target you for 2 rounds."),
            Ability("aegis", "Aegis Wall", self.cd_label("aegis", "30 STA", 4), Target.SELF,
                    self.ready("aegis") and self.stamina >= 30,
                    hint="Ward the whole living party for 2 turns; gain 1 Bastion. Long cooldown."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        if key == "bash":
            assert target is not None
            stacks, self.bastion = self.bastion, 0
            combat.strike(self, target, 1.0 + 0.25 * stacks)
            self.aggro += 30
            if stacks >= self.BASTION_MAX and target.alive:
                target.add_status(Status.SUPPRESSED, 1)
                combat.alert(f"{self.name}: BASTION BREAKS LOOSE!", Pal.BLUE)
        elif key == "guard":
            self.spend_stamina(20)
            self.add_status(Status.GUARD, 1)
            self.bastion = min(self.BASTION_MAX, self.bastion + 2)
            combat.log(f"{self.name} raises the Bulwark. Allies are shielded.", Pal.BLUE)
        elif key == "provoke":
            self.spend_stamina(15)
            self.start_cooldown("provoke", self.PROVOKE_CD)
            self.add_status(Status.PROVOKE, 2)
            self.aggro += 150
            combat.alert(f"{self.name} ROARS - all eyes turn!", Pal.GOLD)
        elif key == "aegis":
            if not self.ready("aegis") or self.stamina < 30:
                combat.alert("Aegis Wall needs 30 Stamina and must be ready.", Pal.ORANGE)
                return
            self.spend_stamina(30)
            self.start_cooldown("aegis", 4)
            for ally in combat.players_alive():
                ally.add_status(Status.WARDED, 2)
            self.bastion = min(self.BASTION_MAX, self.bastion + 1)
            self.play_anim("barrier")
            combat.alert("AEGIS WALL — the party's guard hardens.", Pal.BLUE)
            combat.log(f"{self.name} braces the party behind a warding wall.", Pal.BLUE)

    def on_deal_damage(self, dmg: int) -> None:
        self.aggro += dmg * 2

    def on_hit_taken(self, dmg: int) -> None:
        if dmg > 0:
            self.bastion = min(self.BASTION_MAX, self.bastion + 1)

    def class_bars(self) -> list[Bar]:
        return [Bar("BASTION", self.bastion, self.BASTION_MAX, Pal.BLUE)]

    def after_battle(self) -> None:
        super().after_battle()
        self.bastion = 0


class Rogue(Player):
    """Glass-cannon opportunist: builds Combo, strikes from the Shadow, and loses Combo when hit."""

    SHADOW_BONUS = 1.3

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.ROGUE, 90, 20, 6, 12)
        self.combo = 0
        self.shadowed = False

    def _opening(self) -> float:
        """Consume the Shadow bonus (set by Vanish) and return its damage multiplier."""
        if self.shadowed:
            self.shadowed = False
            return self.SHADOW_BONUS
        return 1.0

    def abilities(self) -> list[Ability]:
        return [
            Ability("quick", "Flicker Stab", "10 STA  +1 Combo", Target.ENEMY, self.stamina >= 10,
                    hint="Fast strike; crit chance rises with Combo. +30% from the Shadow."),
            Ability("assassinate", "Assassinate", "3+ COMBO", Target.ENEMY, self.combo >= 3, QteKind.TIMING,
                    "Guaranteed crit, stronger with Combo. Nail the timing for bonus damage."),
            Ability("vanish", "Vanish", "20 STA  +1 Combo", Target.SELF, self.stamina >= 20,
                    hint="Drop off every enemy's radar; your next attack gains +30%. Any hit on you ends it."),
            Ability("twin_fang", "Twin Fang", "18 STA  +Combo", Target.ENEMY, self.stamina >= 18,
                    QteKind.TIMING, "Two fast strikes. Clean timing raises the combo by 2; the second cut is weaker on a miss."),
        ]

    @property
    def max_combo(self) -> int:
        return getattr(self, "combo_max", 5)

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        c_bonus = getattr(self, "crit_bonus", 0.0)
        c_max = self.max_combo
        if key == "quick":
            assert target is not None
            self.spend_stamina(10)
            combat.strike(self, target, 0.8 * self._opening(), crit_chance=0.15 + 0.08 * self.combo + c_bonus)
            self.combo = min(c_max, self.combo + 1)
        elif key == "assassinate":
            assert target is not None
            mult = (0.9 + 0.3 * self.combo) * (1.25 if ok else 1.0) * self._opening()
            combat.alert("ASSASSINATE!" if ok else "Assassinate (clumsy)", Pal.GREEN if ok else Pal.DIM)
            combat.strike(self, target, mult, force_crit=True)
            self.combo = 0
        elif key == "vanish":
            self.spend_stamina(20)
            self.aggro = 1.0
            self.combo = min(c_max, self.combo + 1)
            self.shadowed = True
            combat.log(f"{self.name} melts into the dark.", Pal.GREEN)
        elif key == "twin_fang":
            assert target is not None
            if self.stamina < 18:
                combat.alert("Twin Fang needs 18 Stamina.", Pal.ORANGE)
                return
            self.spend_stamina(18)
            self.play_anim("dash")
            combo_before = self.combo
            crit = min(0.75, 0.08 + 0.06 * combo_before + c_bonus)
            first = combat.strike(self, target, 0.62, crit_chance=crit)
            if target.alive:
                combat.strike(self, target, 0.82 if ok is True else 0.42, crit_chance=crit)
            self.combo = min(c_max, self.combo + (2 if ok is True and first > 0 else 1 if first > 0 else 0))
            combat.log(f"{self.name} crosses both blades through the opening.", Pal.GREEN if ok is True else Pal.DIM)

    def on_hit_taken(self, dmg: int) -> None:
        if dmg > 0:
            self.shadowed = False
            self.combo = max(0, self.combo - 1)

    def class_bars(self) -> list[Bar]:
        return [Bar("COMBO", self.combo, self.max_combo, Pal.GREEN)]

    def badges(self) -> list[tuple[str, Color]]:
        out = [("SHADOWED", Pal.GREEN)] if self.shadowed else []
        return out + super().badges()

    def after_battle(self) -> None:
        super().after_battle()
        self.combo = 0
        self.shadowed = False


# --------------------------------------------------------------------------
class Witch(Player):
    """Silver-haired gothic cleric: ranged Hex Bolts, a Dark Barrier and the Area Curse."""

    BARRIER_COST = 25
    CURSE_COST = 45
    BARRIER_TURNS = 2
    BARRIER_CD = 4
    BOLT_MANA = 6

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.WITCH, 75, 9, 4, 9, mana=100)
        self.barrier = 0          # damage the Dark Barrier can still soak
        self.barrier_max = 0
        self.barrier_turns = 0

    def on_turn_start(self, combat: CombatSystem) -> None:
        super().on_turn_start(combat)
        mp_bonus = getattr(self, "mp_regen_bonus", 0)
        self.mana = min(self.max_mana, self.mana + 4 + mp_bonus)
        if self.barrier_turns > 0:
            self.barrier_turns -= 1
            if self.barrier_turns == 0 and self.barrier > 0:
                self.barrier = 0
                combat.log(f"{self.name}'s Dark Barrier crumbles to ash.", Pal.PURPLE)

    def on_hit_taken(self, dmg: int) -> None:
        # The barrier refunds whatever it soaks (damage is applied before this hook runs).
        soaked = min(self.barrier, dmg) if self.barrier > 0 else 0
        if soaked:
            self.barrier -= soaked
            self.hp = min(self.max_hp, self.hp + soaked)
            if self.barrier <= 0:
                self.barrier_turns = 0
        if soaked < dmg:
            self.play_anim("hurt")

    def _castable(self, cost: int) -> bool:
        return self.mana >= cost or self.hp > cost - self.mana + 1

    def _cost_label(self, cost: int) -> str:
        return f"{cost} MP" if self.mana >= cost else f"{cost} MP OVERCAST: -{cost - self.mana} HP"

    def abilities(self) -> list[Ability]:
        return [
            Ability("bolt", "Hex Bolt", f"free  +{self.BOLT_MANA} MP", Target.ENEMY,
                    hint="Ranged magic bolt. Cheap, reliable, restores mana."),
            Ability("barrier", "Dark Barrier", self.cd_label("barrier", self._cost_label(self.BARRIER_COST), self.BARRIER_CD),
                    Target.SELF, self.ready("barrier") and self._castable(self.BARRIER_COST),
                    hint=f"Wraps you in a dome that soaks damage for {self.BARRIER_TURNS} turns. Overcast = x1.5."),
            Ability("curse", "Area Curse", self.cd_label("curse", self._cost_label(self.CURSE_COST), 4),
                    Target.ALL_ENEMIES, self.ready("curse") and self._castable(self.CURSE_COST), QteKind.MEMORY,
                    "Hits all foes, Exposes and Suppresses them. Weave the sigil for full power."),
            Ability("drain", "Soul Drain", self.cd_label("drain", "22 MP", 2), Target.ENEMY,
                    self.ready("drain") and self.mana >= 22,
                    hint="Spend mana to strike a single foe and recover one-third of damage dealt as HP."),
        ]

    def _cast(self, cost: int, combat: CombatSystem) -> float:
        """Pay for a spell; falls back to HP (Overcast) for +50% power."""
        if self.mana >= cost:
            self.mana -= cost
            return 1.0
        deficit = cost - self.mana
        self.mana = 0
        combat.hurt_self(self, deficit)
        combat.alert(f"{self.name} OVERCASTS - blood fuels the spell!", Pal.RED)
        return 1.5

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        s_mult = 1.0 + getattr(self, "spell_mult", 0.0)
        if key == "bolt":
            assert target is not None
            self.play_anim("bolt")
            combat.strike(self, target, 1.7 * s_mult)
            self.mana = min(self.max_mana, self.mana + self.BOLT_MANA)
        elif key == "barrier":
            power = self._cast(self.BARRIER_COST, combat)
            self.barrier_max = self.barrier = int((self.max_hp * 0.35 * power + self.base_defense * 2) * s_mult)
            self.barrier_turns = self.BARRIER_TURNS
            self.start_cooldown("barrier", self.BARRIER_CD)
            self.play_anim("barrier")
            combat.alert("DARK BARRIER", Pal.PURPLE)
            combat.log(f"{self.name} weaves a dome of shadow ({self.barrier} absorb).", Pal.PURPLE)
        elif key == "curse":
            power = self._cast(self.CURSE_COST, combat) * (1.0 if ok else 0.6) * s_mult
            self.start_cooldown("curse", 4)
            self.play_anim("curse")
            combat.alert("AREA CURSE!" if ok else "The sigil frays...", Pal.PURPLE)
            combat.shake(0.8)
            for foe in combat.enemies_alive():
                combat.strike(self, foe, 1.4 * power)
                if foe.alive:
                    foe.add_status(Status.SUPPRESSED, 2 if ok else 1)
                    if ok:
                        foe.add_status(Status.EXPOSED, 2)
        elif key == "drain":
            if target is None:
                return
            if not self.ready("drain") or self.mana < 22:
                combat.alert("Soul Drain needs 22 Mana and must be ready.", Pal.ORANGE)
                return
            self.mana -= 22
            self.start_cooldown("drain", 2)
            self.play_anim("bolt")
            mult = (1.35 if target.has(Status.EXPOSED) else 1.05) * s_mult
            dealt = combat.strike(self, target, mult)
            recovered = max(1, dealt // 3) if dealt > 0 else 0
            healed = combat.heal(self, recovered)
            combat.log(f"{self.name} draws {healed} vitality from the severed thread.", Pal.PURPLE)

    def class_bars(self) -> list[Bar]:
        return [Bar("BARRIER", self.barrier, max(1, self.barrier_max), Pal.PURPLE)] if self.barrier > 0 else []

    def badges(self) -> list[tuple[str, Color]]:
        out = [(f"BARRIER {self.barrier}", Pal.PURPLE)] if self.barrier > 0 else []
        return out + super().badges()

    def after_battle(self) -> None:
        super().after_battle()
        self.barrier = self.barrier_max = self.barrier_turns = 0

    def rest(self, hp_ratio: float = 1.0) -> None:
        super().rest(hp_ratio)
        self.barrier = self.barrier_max = self.barrier_turns = 0


class Kitsune(Player):
    """Fox-spirit tactician: build Spirit with clean hits, then spend it to misdirect and evade."""

    SPIRIT_MAX = 100

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.KITSUNE, 98, 17, 6, 13)
        self.spirit = 0
        self.decoy_turns = 0
        self.evasion_charges = 0
        self.awakened_turns = 0

    @property
    def max_spirit(self) -> int:
        return self.SPIRIT_MAX + getattr(self, "spirit_bonus", 0)

    def gain_spirit(self, amount: int) -> int:
        # Normalize first so a malformed/out-of-range save cannot produce a negative
        # return value or leave the resource outside its invariant.
        cap = self.max_spirit
        before = min(cap, max(0, int(self.spirit)))
        self.spirit = min(cap, max(0, before + int(amount)))
        return self.spirit - before

    def consume_evasion(self) -> bool:
        """Consume one prepared sidestep. CombatSystem calls this before applying a single-target hit."""
        if self.evasion_charges <= 0:
            return False
        self.evasion_charges -= 1
        self.decoy_turns = max(0, self.decoy_turns - 1)
        self.gain_spirit(12 if self.awakened_turns else 8)
        return True

    def on_turn_start(self, combat: CombatSystem) -> None:
        super().on_turn_start(combat)
        if self.awakened_turns > 0:
            self.awakened_turns -= 1
            if self.awakened_turns == 0:
                combat.log(f"{self.name}'s borrowed ninefold flame gutters out.", Pal.ORANGE)
        # Decoys must never become a permanent defensive buff if the enemy uses only area attacks.
        if self.decoy_turns > 0:
            self.decoy_turns = 0
            self.evasion_charges = 0

    def on_deal_damage(self, dmg: int) -> None:
        super().on_deal_damage(dmg)
        if dmg > 0:
            self.gain_spirit(6)

    def abilities(self) -> list[Ability]:
        return [
            Ability("foxfire", "Foxfire Thread", "free  +Spirit", Target.ENEMY, True, QteKind.TIMING,
                    "Precise foxfire strike. A clean timing hit burns and exposes the target; damage builds Spirit."),
            Ability("paper_moon", "Paper Moon Double", "25 Spirit", Target.SELF, self.spirit >= 25,
                    hint="Plant a decoy that baits the next single-target enemy strike and turns it into a dodge."),
            Ability("ninefold", "Ninefold Step", "20 Spirit", Target.SELF, self.spirit >= 20, QteKind.TIMING,
                    "Prepare one guaranteed evade; perfect timing prepares a second charge and refunds 8 Spirit."),
            Ability("masquerade", "Kitsune's Masquerade", "40 Spirit", Target.ALL_ENEMIES,
                    self.spirit >= 40, QteKind.MEMORY,
                    "A spirit-seal feint suppresses every enemy; a clean sequence also exposes them briefly."),
            Ability("ascend", "Nine-Tail Ascendance", "65 Spirit", Target.SELF,
                    self.spirit >= 65 and self.awakened_turns <= 0,
                    hint="Spend the reserve to awaken for 3 turns: stronger Foxfire and enhanced Spirit on evasion."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        if key == "foxfire":
            if target is None:
                return
            self.play_anim("foxfire")
            clean = ok is True
            fox_extra = 1.0 + getattr(self, "fox_mult", 0.0)
            power = (1.20 if clean else 0.78) * (1.30 if self.awakened_turns else 1.0) * fox_extra
            dealt = combat.strike(self, target, power)
            self.gain_spirit(12 if dealt > 0 else 0)
            if target.alive:
                target.add_status(Status.BURN, 2 if clean else 1)
                target.burn_power = max(target.burn_power, 4 if clean else 2)
                if clean:
                    target.add_status(Status.EXPOSED, 1)
            combat.log(f"{self.name} threads foxfire through the opening{'—the seal lands cleanly' if clean else ', the flame frays'}.",
                       Pal.ORANGE if clean else Pal.DIM)
        elif key == "paper_moon":
            if self.spirit < 25:
                combat.alert("Paper Moon needs 25 Spirit.", Pal.ORANGE)
                return
            self.spirit -= 25
            self.decoy_turns = 1 + int(getattr(self, "decoy_extra", 0))
            self.evasion_charges = max(self.evasion_charges, 1)
            self.aggro = max(1.0, self.aggro * 0.45)
            self.play_anim("illusion")
            combat.alert("PAPER MOON — the next single-target strike chases a false silhouette.", Pal.CYAN)
            combat.log(f"{self.name} leaves a paper-thin echo where danger expects her to stand.", Pal.CYAN)
        elif key == "ninefold":
            if self.spirit < 20:
                combat.alert("Ninefold Step needs 20 Spirit.", Pal.ORANGE)
                return
            self.spirit -= 20
            self.evasion_charges = max(self.evasion_charges, 2 if ok is True else 1)
            self.play_anim("ninefold")
            if ok is True:
                self.gain_spirit(8)
                combat.alert("NINEFOLD STEP — perfect timing leaves two afterimages.", Pal.CYAN)
            else:
                combat.log(f"{self.name} slips into a hurried sidestep; one evade is ready.", Pal.CYAN)
        elif key == "masquerade":
            if self.spirit < 40:
                combat.alert("Masquerade needs 40 Spirit.", Pal.ORANGE)
                return
            self.spirit -= 40
            self.play_anim("masquerade")
            clean = ok is True
            combat.alert("KITSUNE'S MASQUERADE" if clean else "THE MASQUERADE FRAYS", Pal.PURPLE if clean else Pal.DIM)
            for foe in combat.enemies_alive():
                foe.add_status(Status.SUPPRESSED, 2 if clean else 1)
                if clean:
                    foe.add_status(Status.EXPOSED, 1)
            combat.log("Paper seals bloom across the field; enemies strike at the wrong story.", Pal.PURPLE)
        elif key == "ascend":
            if self.spirit < 65 or self.awakened_turns > 0:
                combat.alert("Nine-Tail Ascendance is not ready.", Pal.ORANGE)
                return
            self.spirit -= 65
            self.awakened_turns = 3
            self.play_anim("ascend")
            combat.alert("NINE-TAIL ASCENDANCE — borrowed fire, three turns.", Pal.ORANGE)
            combat.log(f"{self.name}'s tails fan into a ring of foxfire; the borrowed power will fade.", Pal.ORANGE)

    def class_bars(self) -> list[Bar]:
        return [Bar("SPIRIT", self.spirit, self.max_spirit, Pal.ORANGE)]

    def badges(self) -> list[tuple[str, Color]]:
        out: list[tuple[str, Color]] = []
        if self.decoy_turns:
            out.append(("PAPER MOON", Pal.CYAN))
        if self.awakened_turns:
            out.append((f"AWAKENED {self.awakened_turns}", Pal.ORANGE))
        if self.evasion_charges:
            out.append((f"EVADE x{self.evasion_charges}", Pal.CYAN))
        return out + super().badges()

    def after_battle(self) -> None:
        super().after_battle()
        self.decoy_turns = 0
        self.evasion_charges = 0
        self.awakened_turns = 0
        self.spirit = min(self.spirit, 25)



class Vampire(Player):
    """Night duelist: Blood fuels a bounded mix of burst, evasion and team tempo."""

    BLOOD_MAX = 100

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.VAMPIRE, 105, 19, 7, 11)
        self.blood = 20

    def gain_blood(self, amount: int) -> int:
        mult = 1.0 + getattr(self, "blood_mult", 0.0)
        eff_amount = int(amount * mult)
        before = min(self.BLOOD_MAX, max(0, int(self.blood)))
        self.blood = min(self.BLOOD_MAX, max(0, before + eff_amount))
        return self.blood - before

    def on_deal_damage(self, dmg: int) -> None:
        super().on_deal_damage(dmg)
        if dmg > 0:
            self.gain_blood(10)

    def on_hit_taken(self, dmg: int) -> None:
        if dmg > 0:
            self.gain_blood(7)
            pool = int(getattr(self, "veil_pool", 0))
            if pool > 0:                      # Veil of Mist: the mist soaks the next damage (profile bonus, in HP)
                soak = min(pool, int(dmg))
                self.veil_pool = pool - soak
                self.hp = min(self.max_hp, self.hp + soak)

    def abilities(self) -> list[Ability]:
        return [
            Ability("crimson_mark", "Crimson Mark", "free  +Blood", Target.ENEMY,
                    hint="A measured cut exposes the target for 2 turns and builds Blood."),
            Ability("sanguine_lunge", "Sanguine Lunge", "35 Blood", Target.ENEMY,
                    self.blood >= 35, hint="Strike hard, then recover up to 24 HP from damage dealt."),
            Ability("veil_night", "Veil of Night", "20 Blood", Target.SELF,
                    self.blood >= 20 and self.ready("veil_night"),
                    hint="Reduce threat and gain a one-turn ward against the next blow."),
            Ability("blood_pact", "Blood Pact", self.cd_label("blood_pact", "45 Blood", 4), Target.SELF,
                    self.blood >= 45 and self.ready("blood_pact"),
                    hint="Empower the living party for 2 turns; costs Blood and has a 4-turn cooldown."),
            Ability("eclipse_feast", "Eclipse Feast", self.cd_label("eclipse_feast", "65 Blood", 3), Target.ENEMY,
                    self.blood >= 65 and self.ready("eclipse_feast"),
                    hint="Finisher deals more to targets below 35% HP; healing is capped at 24 HP."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        if key == "crimson_mark":
            if target is None:
                return
            self.play_anim("blood")
            dealt = combat.strike(self, target, 0.72)
            if target.alive:
                target.add_status(Status.EXPOSED, 2)
            if dealt > 0:
                self.gain_blood(6)
            combat.log(f"{self.name} marks a fault in the target's guard with a crimson cut.", Pal.RED)
        elif key == "sanguine_lunge":
            if target is None or self.blood < 35:
                combat.alert("Sanguine Lunge needs 35 Blood and a living target.", Pal.ORANGE)
                return
            self.blood -= 35
            self.play_anim("dash")
            dealt = combat.strike(self, target, 1.42)
            healed = combat.heal(self, min(24, max(0, dealt // 4)))
            combat.log(f"The night duelist draws {healed} vitality from the lunge.", Pal.RED)
        elif key == "veil_night":
            if self.blood < 20 or not self.ready("veil_night"):
                combat.alert("Veil of Night needs 20 Blood and must be ready.", Pal.ORANGE)
                return
            self.blood -= 20
            self.start_cooldown("veil_night", 2)
            self.aggro = max(1.0, self.aggro * 0.45)
            self.veil_pool = int(getattr(self, "veil_bonus", 0))   # "+5 HP absorb" as described, not +5 turns of ward
            self.add_status(Status.WARDED, 1)
            self.play_anim("mist")
            combat.alert("VEIL OF NIGHT — the next blow meets mist.", Pal.PURPLE)
        elif key == "blood_pact":
            if self.blood < 45 or not self.ready("blood_pact"):
                combat.alert("Blood Pact needs 45 Blood and must be ready.", Pal.ORANGE)
                return
            self.blood -= 45
            self.start_cooldown("blood_pact", 4)
            for ally in combat.players_alive():
                ally.add_status(Status.EMPOWERED, 2)
            self.play_anim("halo")
            combat.alert("BLOOD PACT — the party's next two turns sharpen.", Pal.RED)
            combat.log(f"{self.name} binds a measured drop of their strength to the party.", Pal.RED)
        elif key == "eclipse_feast":
            if target is None or self.blood < 65 or not self.ready("eclipse_feast"):
                combat.alert("Eclipse Feast needs 65 Blood, a living target, and a ready cooldown.", Pal.ORANGE)
                return
            self.blood -= 65
            self.start_cooldown("eclipse_feast", 3)
            mult = 2.05 if target.hp_ratio <= 0.35 else 1.35
            self.play_anim("blood")
            dealt = combat.strike(self, target, mult)
            healed = combat.heal(self, min(24, max(0, dealt // 4)))
            combat.alert("ECLIPSE FEAST" if target.hp_ratio <= 0.35 else "Eclipse Feast", Pal.RED)
            combat.log(f"The finisher returns {healed} HP; the thirst remains bounded.", Pal.RED)

    def class_bars(self) -> list[Bar]:
        return [Bar("BLOOD", self.blood, self.BLOOD_MAX, Pal.RED)]

    def badges(self) -> list[tuple[str, Color]]:
        return ([ (f"BLOOD {self.blood}", Pal.RED) ] if self.blood >= 65 else []) + super().badges()

    def after_battle(self) -> None:
        super().after_battle()
        self.blood = min(25, self.blood)

    def rest(self, hp_ratio: float = 1.0) -> None:
        super().rest(hp_ratio)
        self.blood = max(15, min(35, self.blood))


class Dragonkin(Player):
    """Heat bruiser: defense and offense raise Heat; overheat costs a vulnerable turn."""

    HEAT_MAX = 100

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.DRAGONKIN, 138, 17, 10, 7)
        self.heat = 24  # enough Heat for the signature opener; the player has a first-turn choice
        self.overheated_turns = 0

    @property
    def heat_max(self) -> int:
        return self.HEAT_MAX + getattr(self, "heat_cap_bonus", 0)

    def gain_heat(self, amount: int) -> int:
        cap = self.heat_max
        before = min(cap, max(0, int(self.heat)))
        proposed = before + max(0, int(amount))
        if proposed >= cap:
            # Crossing the cap vents stored heat, but exposes the Dragonkin for a beat.
            self.heat = 55
            self.overheated_turns = max(1, self.overheated_turns)
            self.add_status(Status.EXPOSED, 2)
            return 0
        self.heat = proposed
        return self.heat - before

    def on_deal_damage(self, dmg: int) -> None:
        super().on_deal_damage(dmg)
        if dmg > 0:
            self.gain_heat(8)

    def on_hit_taken(self, dmg: int) -> None:
        if dmg > 0:
            self.gain_heat(10)

    def on_turn_start(self, combat: CombatSystem) -> None:
        super().on_turn_start(combat)
        if self.overheated_turns > 0:
            combat.log(f"{self.name}'s scales vent furnace heat; the opening leaves them exposed.", Pal.ORANGE)
            self.overheated_turns -= 1

    def abilities(self) -> list[Ability]:
        return [
            Ability("scale_guard", "Scale Guard", "20 STA  +12 Heat", Target.SELF, self.stamina >= 20,
                    hint="Brace for one turn, triple defense, and build Heat."),
            Ability("ember_breath", "Ember Breath", "30 Heat", Target.ALL_ENEMIES,
                    self.heat >= 30 and self.ready("ember_breath"), QteKind.TIMING,
                    "Area breath: clean timing deals more damage and applies a stronger Burn."),
            Ability("dragon_challenge", "Dragon's Challenge", "18 Heat", Target.ENEMY,
                    self.heat >= 18, hint="A measured strike exposes the target and draws its attention."),
            Ability("wingbeat", "Wingbeat", self.cd_label("wingbeat", "28 Heat", 2), Target.ALL_ENEMIES,
                    self.heat >= 28 and self.ready("wingbeat"),
                    hint="Disrupt the whole enemy line; suppresses survivors for one turn."),
            Ability("ancient_aspect", "Ancient Aspect", self.cd_label("ancient_aspect", "65 Heat", 4), Target.SELF,
                    self.heat >= 65 and self.ready("ancient_aspect"),
                    hint="Empower and ward yourself for 2 turns; overheat can still leave you exposed."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        if key == "scale_guard":
            if self.stamina < 20:
                combat.alert("Scale Guard needs 20 Stamina.", Pal.ORANGE)
                return
            self.spend_stamina(20)
            self.add_status(Status.GUARD, 1)
            self.gain_heat(12)
            self.play_anim("barrier")
            combat.log(f"{self.name} locks plated scales and channels force into the stance.", Pal.ORANGE)
        elif key == "ember_breath":
            if self.heat < 30 or not self.ready("ember_breath"):
                combat.alert("Ember Breath needs 30 Heat and must be ready.", Pal.ORANGE)
                return
            self.heat -= 30
            self.start_cooldown("ember_breath", 2)
            clean = ok is True
            self.play_anim("breath")
            combat.alert("EMBER BREATH" if clean else "SCATTERED EMBERS", Pal.ORANGE if clean else Pal.DIM)
            for foe in combat.enemies_alive():
                dealt = combat.strike(self, foe, 0.92 if clean else 0.62)
                if foe.alive:
                    foe.add_status(Status.BURN, 2 if clean else 1)
                    foe.burn_power = max(foe.burn_power, 5 if clean else 3)
            combat.log("A fan of furnace breath sweeps across the enemy line.", Pal.ORANGE)
        elif key == "dragon_challenge":
            if target is None or self.heat < 18:
                combat.alert("Dragon's Challenge needs 18 Heat and a living target.", Pal.ORANGE)
                return
            self.heat -= 18
            self.play_anim("slash")
            combat.strike(self, target, 0.9)
            if target.alive:
                target.add_status(Status.EXPOSED, 2)
            self.add_status(Status.PROVOKE, 2)
            self.aggro += 80
            combat.alert("DRAGON'S CHALLENGE — meet the fire head-on.", Pal.ORANGE)
        elif key == "wingbeat":
            if self.heat < 28 or not self.ready("wingbeat"):
                combat.alert("Wingbeat needs 28 Heat and must be ready.", Pal.ORANGE)
                return
            self.heat -= 28
            self.start_cooldown("wingbeat", 2)
            self.play_anim("wingbeat")
            combat.alert("WINGBEAT — the line breaks.", Pal.ORANGE)
            for foe in combat.enemies_alive():
                combat.strike(self, foe, 0.62)
                if foe.alive:
                    foe.add_status(Status.SUPPRESSED, 1)
        elif key == "ancient_aspect":
            if self.heat < 65 or not self.ready("ancient_aspect"):
                combat.alert("Ancient Aspect needs 65 Heat and must be ready.", Pal.ORANGE)
                return
            self.heat -= 65
            self.start_cooldown("ancient_aspect", 4)
            self.add_status(Status.EMPOWERED, 2)
            self.add_status(Status.WARDED, 2)
            self.play_anim("ascend")
            combat.alert("ANCIENT ASPECT — scales ignite, the borrowed aspect will fade.", Pal.ORANGE)

    def class_bars(self) -> list[Bar]:
        return [Bar("HEAT", self.heat, self.heat_max, Pal.ORANGE)]

    def badges(self) -> list[tuple[str, Color]]:
        out = [("OVERHEATED / EXPOSED", Pal.RED)] if self.overheated_turns > 0 else []
        return out + super().badges()

    def after_battle(self) -> None:
        super().after_battle()
        self.heat = min(30, self.heat)
        self.overheated_turns = 0

    def rest(self, hp_ratio: float = 1.0) -> None:
        super().rest(hp_ratio)
        self.heat = min(20, self.heat)
        self.overheated_turns = 0


# --------------------------------------------------------------------------
class Restraint(Enum):
    """Permanent curses, ordered by the priority in which Break Restraint removes them."""

    MANACLES = ("Penitent Manacles", "Attacks need a typing QTE; a botched word wastes the blow")
    IRON_GAG = ("Iron Gag", "Items need a swallowing QTE")
    DEPRIVATION = ("Sensory Deprivation", "UI and enemy intent blacked out")
    SABATONS = ("Spiked Sabatons", "25% of the damage you deal returns as recoil")
    BARBED_WINGS = ("Barbed Wings", "Bleeds 4+ HP and -3 STA recovery each turn; Dash -25%")
    ANCHOR = ("Abyssal Anchor", "-4 STA recovery each turn; Aerial Dash locked")

    def __init__(self, label: str, desc: str) -> None:
        self.label = label
        self.desc = desc


class FallenAngel(Player):
    """Challenge-only nightmare class with no compensating strengths.

    Restraints cascade every turn and tighten the longer she stays bound; stamina, mana and
    lucidity recover poorly; escapes are costly and uncertain; a shattered mind forces bloodlust
    turns that hurt her.  Her stats sit at or below the other heroes' and she has no exclusive
    damage, defence, economy or utility bonus.

    Kit: Dark Blade Slash, Aerial Dash, Halo Detonation, plus the self-harm/restraint-management
    tools Writhe, Pierce Palm and Break Restraint.
    """

    SLASH_STA = 15
    OVEREXERT_HP = 10          # Slash paid in blood when stamina runs dry (keeps her playable)
    DASH_STA = 25
    DASH_CD = 3
    HALO_MP = 30
    HALO_BACKLASH_HP = 6
    BREAK_STA = 40
    BREAK_BACKLASH_HP = 14
    BREAK_BACKLASH_LUC = 20.0
    MAX_TIGHTNESS = 3
    TIGHTEN_EVERY = 3          # turns spent bound per extra notch of Tightening
    FUMBLE_BELOW_LUC = 25.0    # below this the mind frays and attacks may misfire
    FRENZY_AFTERMATH_LUC = 15.0

    def __init__(self, name: str) -> None:
        super().__init__(name, PlayerClass.ANGEL, 100, 14, 4, 6, mana=40)
        self.restraints: set[Restraint] = set()
        self.struggle_target: Optional[Restraint] = None  # set by the [E] hover-struggle; None = highest priority
        self.lucidity = 100.0
        self.bloodlust_turns = 0
        self.tightness = 0                 # 0..MAX_TIGHTNESS; worsens every restraint effect
        self._bound_turns = 0
        self._in_frenzy = False
        self.failed_breaks = 0             # R2: failed Break Restraint attempts this encounter (escalates backlash)
        self.release_window = 0            # R2 capstone: strikes left that ignore restraint penalties
        self.recent_trials: list[str] = []  # R2: last restraint trials used (anti-repetition, transient)

    CORRECTION_AFTER = 2       # R2: consecutive failed breaks before the Choir of Correction locks Break
    CORRECTION_LOCK_TURNS = 2
    ESCALATION_CAP = 3

    def note_trial(self, trial_id: str) -> None:
        self.recent_trials.append(trial_id)
        del self.recent_trials[:-6]

    def break_backlash(self) -> tuple[int, float]:
        """(HP, lucidity) lost on a failed Break; +3 HP / +5 LUC per earlier failure this fight (max 3 steps)."""
        n = min(self.failed_breaks, self.ESCALATION_CAP)
        soft = int(self.perk("break_soft"))          # Lucid Ledger
        return max(1, self.BREAK_BACKLASH_HP + 3 * n - 3 * soft), max(0.0, self.BREAK_BACKLASH_LUC + 5.0 * n - 5.0 * soft)

    @property
    def correction_after(self) -> int:
        return self.CORRECTION_AFTER + int(self.perk("break_soft"))

    @property
    def blackout(self) -> bool:
        return Restraint.DEPRIVATION in self.restraints

    @property
    def martyr(self) -> bool:
        """Below 30% HP: pain floods the mind and lucidity drains faster (no damage bonus)."""
        return self.hp_ratio < 0.30

    def item_qte(self) -> Optional[QteKind]:
        return QteKind.MASH if Restraint.IRON_GAG in self.restraints else None

    def active_restraints(self) -> list[str]:
        return [r.label for r in Restraint if r in self.restraints]

    # ---- derived odds (also shown on the HUD) -----------------------------------
    def fumble_chance(self) -> float:
        """Chance an attack misfires from a fraying mind (0 while lucidity >= FUMBLE_BELOW_LUC)."""
        if self.lucidity >= self.FUMBLE_BELOW_LUC:
            return 0.0
        return 0.5 * _clamp((self.FUMBLE_BELOW_LUC - self.lucidity) / self.FUMBLE_BELOW_LUC)

    def break_chance(self) -> float:
        """Chance a successful mash actually shatters a chain; falls as the chains tighten.

        Lowered base (0.40 → was 0.55) and steeper per-restraint / tightness penalties,
        making escape a meaningful resource decision rather than a near-guarantee.
        The Angel's class skill-tree node ``Iron Will`` can partially offset the penalty
        via ``_profile_break_bonus``.
        """
        profile_bonus = getattr(self, "_profile_break_bonus", 0.0)
        return _clamp(
            0.40 - 0.06 * len(self.restraints) - 0.08 * self.tightness + profile_bonus,
            0.12, 0.45,
        )

    def _misfires(self, combat: CombatSystem) -> bool:
        chance = self.fumble_chance()
        return chance > 0.0 and combat.rng.random() < chance

    def _overexert_cost(self) -> int:
        """HP paid for a Slash with no stamina left; never lethal, so she always has a legal action."""
        return min(self.OVEREXERT_HP, max(0, self.hp - 1))

    def _recoil(self, combat: CombatSystem, dealt: int) -> None:
        if Restraint.SABATONS in self.restraints and dealt > 0:
            combat.hurt_self(self, max(1, dealt // 4))
            combat.log("Spiked Sabatons bite into your feet.", Pal.RED)

    def abilities(self) -> list[Ability]:
        atk_qte = QteKind.TYPING if Restraint.MANACLES in self.restraints else None
        anchored = Restraint.ANCHOR in self.restraints
        slash_cost = (f"{self.SLASH_STA} STA" if self.stamina >= self.SLASH_STA
                      else f"OVEREXERT -{self._overexert_cost()} HP")
        fumble = self.fumble_chance()
        frayed = f" Mind fraying: {int(fumble * 100)}% to misfire." if fumble else ""
        return [
            Ability("slash", "Dark Blade Slash", slash_cost, Target.ENEMY,
                    True, atk_qte,
                    "1.0x strike with a small crit chance. Needs free hands; with no stamina it is "
                    "paid in blood (never lethal)." + frayed),
            Ability("dash", "Aerial Dash", self.cd_label("dash", f"{self.DASH_STA} STA", self.DASH_CD), Target.ENEMY,
                    self.ready("dash") and self.stamina >= self.DASH_STA and not anchored,
                    hint="1.35x strike, no refund and no escape from notice; leaves you Exposed. "
                         "Barbed Wings dull it; the Abyssal Anchor grounds you." + frayed),
            Ability("halo", "Halo Detonation",
                    self.cd_label("halo", f"{self.HALO_MP} MP  -10 LUC  -{self.HALO_BACKLASH_HP} HP", 3),
                    Target.ALL_ENEMIES,
                    self.ready("halo") and self.mana >= self.HALO_MP and self.hp > self.HALO_BACKLASH_HP + 2, atk_qte,
                    "1.1x to every foe. The blast scorches you and clouds your mind." + frayed),
            Ability("writhe", "Writhe in Chains", "-15 HP  +15 STA +10 MP", Target.SELF, self.hp > 16,
                    hint="Tear your own skin to feed the fire. Costs more than it gives back."),
            Ability("pierce", "Pierce Palm", "-12 HP  +25 LUC", Target.SELF,
                    self.lucidity < 100 and self.hp > 14, hint="Pain anchors the mind, but only partly."),
            Ability("break", "Break Restraint",
                    self.cd_label("break", f"{self.BREAK_STA} STA  {int(self.break_chance() * 100)}%", self.CORRECTION_LOCK_TURNS)
                    if not self.ready("break") else f"{self.BREAK_STA} STA  {int(self.break_chance() * 100)}%",
                    Target.SELF,
                    bool(self.restraints) and self.stamina >= self.BREAK_STA and self.ready("break")
                    and self.hp > self.break_backlash()[0] + 1,
                    QteKind.MASH,
                    f"Pass a restraint trial (mashing is penalised), then the chain still has to give "
                    f"({int(self.break_chance() * 100)}%). Failure costs {self.break_backlash()[0]} HP and "
                    f"{int(self.break_backlash()[1])} LUC, tightens the chains, and each failure this fight hurts more; "
                    f"after {self.correction_after} the Choir of Correction locks Break for {self.CORRECTION_LOCK_TURNS} turns."),
        ]

    def use(self, key: str, target: Optional[BaseEntity], ok: Optional[bool], combat: CombatSystem) -> None:
        if self.restraints and key not in ("break", "pierce"):
            bound_tax = min(18.0, 3.0 * len(self.restraints) + 2.0 * self.tightness)
            self.lucidity = max(0.0, self.lucidity - bound_tax)
            combat.log(f"The restraints smother the action: -{bound_tax:g} lucidity.", Pal.PURPLE)
            # Acting while bound makes the next escape attempt less forgiving.
            if self.tightness < self.MAX_TIGHTNESS and len(self.restraints) >= 2:
                self.tightness += 1
                combat.alert(f"THE CHAINS TIGHTEN x{self.tightness}", Pal.RED)
        if self.bloodlust_turns > 0:
            # Forced turns are dangerous: the frenzy tears at her whatever she does.
            combat.hurt_self(self, max(2, self.max_hp // 12))
            combat.log(f"{self.name}'s bloodlust claws at her own flesh.", Pal.RED)
            if not self.alive:
                return
        if key == "slash":
            assert target is not None
            self.play_anim("slash")
            if self.stamina >= self.SLASH_STA:
                self.spend_stamina(self.SLASH_STA)
            else:
                self.stamina = 0
                cost = self._overexert_cost()
                if cost:
                    combat.hurt_self(self, cost)
                combat.log(f"{self.name} swings on empty - it costs her blood.", Pal.RED)
                if not self.alive:
                    return
            if ok is False or self._misfires(combat):
                combat.log(f"{self.name} fumbles the chains - the blow goes wide!", Pal.RED)
                return
            self._recoil(combat, combat.strike(self, target, 1.0, crit_chance=0.1))
        elif key == "dash":
            assert target is not None
            self.spend_stamina(self.DASH_STA)
            self.start_cooldown("dash", self.DASH_CD)
            self.play_anim("dash")
            dealt = 0
            if self._misfires(combat):
                combat.log(f"{self.name} lunges blindly and crashes past the foe!", Pal.RED)
            else:
                mult = 1.35 * (0.75 if Restraint.BARBED_WINGS in self.restraints else 1.0)
                dealt = combat.strike(self, target, mult, crit_chance=0.15)
            self.add_status(Status.EXPOSED, 1)
            combat.log(f"{self.name} overreaches and is left Exposed.", Pal.PURPLE)
            self._recoil(combat, dealt)
        elif key == "halo":
            self.mana = max(0, self.mana - self.HALO_MP)
            self.lucidity = max(0.0, self.lucidity - 10)
            self.start_cooldown("halo", 3)
            self.play_anim("halo")
            combat.hurt_self(self, self.HALO_BACKLASH_HP)
            if not self.alive:
                return
            if ok is False or self._misfires(combat):
                combat.log(f"{self.name}'s halo gutters out - the blast never comes!", Pal.RED)
                return
            combat.alert("HALO DETONATION!", Pal.PURPLE)
            combat.shake(0.9)
            total = 0
            for foe in combat.enemies_alive():
                total += combat.strike(self, foe, 1.1)
            self._recoil(combat, total)
        elif key == "writhe":
            combat.hurt_self(self, 15)
            self.stamina = min(self.max_stamina, self.stamina + 15)
            self.mana = min(self.max_mana, self.mana + 10)
            combat.log(f"{self.name} writhes against the iron.", Pal.PURPLE)
        elif key == "pierce":
            combat.hurt_self(self, 12)
            self.lucidity = min(100.0, self.lucidity + 25)
            combat.log(f"{self.name} pierces a palm. The pain is clarity.", Pal.CYAN)
        elif key == "break":
            if not self.restraints:
                combat.log("There is nothing left to break.", Pal.DIM)
                return
            self.spend_stamina(self.BREAK_STA)
            aimed, self.struggle_target = self.struggle_target, None
            chance = self.break_chance()
            if ok and combat.rng.random() < chance:
                broken = aimed if aimed in self.restraints else next(r for r in Restraint if r in self.restraints)
                self.restraints.discard(broken)
                self.tightness = max(0, self.tightness - 1)
                self.failed_breaks = 0
                if self.perk("release") > 0:           # Brief Release capstone
                    self.release_window = int(self.perk("release"))
                    self.lucidity = max(0.0, self.lucidity - self.perk("release_cost"))
                    combat.log("The chains fall away for a heartbeat: your next strike is unbound.", Pal.CYAN)
                combat.alert(f"{broken.label} SHATTERED!", Pal.GREEN)
            else:
                combat.log("Her grip slips." if not ok else "The chain holds. The Abyss laughs.", Pal.RED)
                hp_cost, luc_cost = self.break_backlash()
                cost = min(hp_cost, max(0, self.hp - 1))
                if cost:
                    combat.hurt_self(self, cost)
                self.lucidity = max(0.0, self.lucidity - luc_cost)
                if self.failed_breaks:
                    combat.log(f"Repeated failure: the backlash bites harder ({hp_cost} HP, {int(luc_cost)} LUC).", Pal.PURPLE)
                self.failed_breaks += 1
                if self.failed_breaks >= self.correction_after:
                    self.start_cooldown("break", self.CORRECTION_LOCK_TURNS)
                    combat.log(f"The Choir of Correction seals your hands: Break Restraint is locked "
                               f"for {self.CORRECTION_LOCK_TURNS} turns.", Pal.PURPLE)
                if self.tightness < self.MAX_TIGHTNESS:
                    self.tightness += 1
                    combat.log("Thrashing only draws the chains tighter.", Pal.PURPLE)

    def break_one(self) -> Optional[Restraint]:
        """Remove the highest-priority restraint (Bolt Cutters)."""
        for restraint in Restraint:
            if restraint in self.restraints:
                self.restraints.discard(restraint)
                return restraint
        return None

    def on_turn_start(self, combat: CombatSystem) -> None:
        self.tick_cooldowns()
        self._bound_turns += 1
        if self._in_frenzy and self.bloodlust_turns <= 0:
            # A forced episode has ended: a thin gasp of clarity, so she is never locked out forever.
            self._in_frenzy = False
            self.lucidity = max(self.lucidity, self.FRENZY_AFTERMATH_LUC)
            combat.log(f"{self.name} surfaces from the frenzy, shaking.", Pal.CYAN)
        # Curse Cascade: the Abyss chains you a little more every turn.
        missing = [r for r in Restraint if r not in self.restraints]
        if missing:
            curse = combat.rng.choice(missing)
            self.restraints.add(curse)
            combat.alert(f"CURSE: {curse.label}", Pal.PURPLE)
            combat.log(f"{curse.label} locks on: {curse.desc}.", Pal.PURPLE)
        # Tightening: the longer she stays bound, the harder every chain bites.
        if self.restraints and self._bound_turns % self.TIGHTEN_EVERY == 0 and self.tightness < self.MAX_TIGHTNESS:
            self.tightness += 1
            combat.alert(f"THE CHAINS TIGHTEN x{self.tightness}", Pal.RED)
        count = len(self.restraints)
        regen = 12 - count - self.tightness            # poor recovery that worsens with every chain
        if Restraint.ANCHOR in self.restraints:
            regen -= 4
        if Restraint.BARBED_WINGS in self.restraints:
            regen -= 3
            bleed = min(4 + self.tightness, max(0, self.hp - 1))   # it bleeds her but never finishes her
            if bleed:
                combat.hurt_self(self, bleed)
        self.stamina = max(0, min(self.max_stamina, self.stamina + regen))
        self.mana = min(self.max_mana, self.mana + 2)
        drift = 4 - 2 * count - self.tightness - (3 if self.martyr else 0)
        if self.martyr:
            combat.log(f"{self.name}'s agony floods her mind.", Pal.ORANGE)
        self.lucidity = max(0.0, min(100.0, self.lucidity + drift))
        if self.lucidity <= 0 and self.bloodlust_turns == 0:
            self.bloodlust_turns = 2
            self._in_frenzy = True
            combat.alert("LUCIDITY SHATTERED - BLOODLUST!", Pal.RED)

    def on_deal_damage(self, dmg: int) -> None:
        super().on_deal_damage(dmg)
        self.aggro += dmg * 0.5          # the bound prey draws every eye

    def on_hit_taken(self, dmg: int) -> None:
        self.lucidity = max(0.0, self.lucidity - dmg * 0.5)
        self.play_anim("hurt")

    def class_bars(self) -> list[Bar]:
        out = [Bar("LUC", self.lucidity, 100, Pal.PURPLE)]
        if self.tightness:
            out.append(Bar("BIND", self.tightness, self.MAX_TIGHTNESS, Pal.RED))
        return out

    def badges(self) -> list[tuple[str, Color]]:
        out = [(r.label, Pal.RED) for r in Restraint if r in self.restraints]
        if self.tightness:
            out.append((f"TIGHTENING x{self.tightness}", Pal.RED))
        if self.bloodlust_turns:
            out.append(("BLOODLUST", Pal.RED))
        elif self.fumble_chance() > 0:
            out.append((f"FRAYING {int(self.fumble_chance() * 100)}%", Pal.ORANGE))
        if self.martyr:
            out.append(("MARTYR -LUC", Pal.ORANGE))
        return out + super().badges()

    def hud_state(self) -> dict:
        state = super().hud_state()
        state.update({
            "lucidity": (self.lucidity, 100.0), "tightness": self.tightness,
            "bloodlust_turns": self.bloodlust_turns, "misfire_chance": self.fumble_chance(),
            "break_chance": self.break_chance(),
        })
        return state

    def after_battle(self) -> None:
        super().after_battle()  # restraints persist until broken
        self.bloodlust_turns = 0
        self._in_frenzy = False
        self._bound_turns = 0
        self.failed_breaks = 0
        self.release_window = 0
        self.lucidity = min(100.0, self.lucidity + 15)

    def rest(self, hp_ratio: float = 1.0) -> None:
        keep, kept_tightness = set(self.restraints), self.tightness
        super().rest(hp_ratio)
        self.restraints, self.tightness = keep, kept_tightness
        self.bloodlust_turns = 0
        self._in_frenzy = False
        self._bound_turns = 0
        self.failed_breaks = 0
        self.release_window = 0
        self.lucidity = max(self.lucidity, 45.0)
        # Poor recovery: even a full rest leaves her short of her limits.
        self.hp = min(self.hp, max(1, int(self.max_hp * 0.8)))
        self.stamina = int(self.max_stamina * 0.8)
        self.mana = int(self.max_mana * 0.5)


PLAYER_CLASSES: dict[PlayerClass, type[Player]] = {
    PlayerClass.WARRIOR: Warrior, PlayerClass.TANK: Tank, PlayerClass.ROGUE: Rogue,
    PlayerClass.WITCH: Witch, PlayerClass.ANGEL: FallenAngel, PlayerClass.KITSUNE: Kitsune,
    PlayerClass.VAMPIRE: Vampire, PlayerClass.DRAGONKIN: Dragonkin,
}


def create_player(name: str, pclass: PlayerClass) -> Player:
    """Factory used when the party is assembled."""
    return PLAYER_CLASSES[pclass](name)  # type: ignore[call-arg]
