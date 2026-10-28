"""abyssal_choir/ui/renderer.py

AAA-style procedural renderer for ABYSSAL CHOIR (pygame 2.x, no external assets).

* Fallen Angel : dark purple wings, glowing purple halo, arm / torso bandages, crown of thorns.
* Witch        : flowing white hair, dark lace hood, clergy dress, ornate staff.
  Both are painted 2x supersampled from vector primitives and animated with math.sin()
  (breathing, floating, hair / cloth sway, wing flutter, blinking).
* Restraints   : Crown of Thorns, Sacred Rune Bindings, Shadow Thorn Vines, Gothic Chains.
  Each restraint registers hit boxes; hovering one (pygame.mouse.get_pos()) shows a
  semi-transparent dark-gothic tooltip: name, resistance status, lore and "Press [E] to Struggle".
* Atmosphere   : parallax gothic cathedral, drifting fog layers, live embers, light shafts,
  soft lighting bloom and a vignette.

Public API
----------
    renderer = Renderer((1280, 720), on_struggle=callback)
    renderer.update(dt)                         # once per frame (seconds)
    renderer.draw(screen, characters)           # draws everything, tooltip last
    renderer.handle_event(event)                # returns HoverTarget when [E] is pressed over a restraint
    renderer.hovered                            # HoverTarget | None  (character + restraint under the cursor)

Run this file directly for an interactive demo:  python renderer.py
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

import pygame

from core.cosmetics import get_skin
from ui.r2_assets import RESTRAINT_KIND_ICON, fit_model_height, model_hit_boxes

Color = tuple[int, int, int]
Vec = tuple[float, float]

# ===================================================================================================
#  palette
# ===================================================================================================
WHITE: Color = (255, 255, 255)
INK: Color = (14, 9, 22)

# fallen angel
A_SKIN: Color = (240, 226, 238)
A_SKIN_SH: Color = (204, 182, 214)
A_SKIN_DK: Color = (166, 140, 184)
A_HAIR: Color = (46, 28, 80)
A_HAIR_MID: Color = (74, 46, 122)
A_HAIR_HI: Color = (152, 106, 226)
WING_DK: Color = (38, 16, 72)
WING_MID: Color = (68, 30, 114)
WING_LT: Color = (102, 54, 164)
WING_RIM: Color = (170, 114, 234)
CLOTH_DK: Color = (18, 12, 32)
CLOTH: Color = (32, 22, 54)
CLOTH_LT: Color = (58, 42, 92)
CLOTH_EDGE: Color = (96, 68, 144)
BANDAGE: Color = (232, 224, 214)
BANDAGE_SH: Color = (194, 184, 178)
BANDAGE_EDGE: Color = (140, 128, 140)
HALO: Color = (212, 148, 255)
HALO_CORE: Color = (246, 226, 255)

# witch
W_SKIN: Color = (251, 239, 238)
W_SKIN_SH: Color = (224, 200, 208)
W_HAIR: Color = (238, 240, 252)
W_HAIR_SH: Color = (190, 194, 224)
W_HAIR_DK: Color = (146, 150, 188)
W_HAIR_HI: Color = (255, 255, 255)
DRESS: Color = (26, 22, 38)
DRESS_LT: Color = (46, 40, 66)
DRESS_DK: Color = (12, 10, 20)
DRESS_EDGE: Color = (74, 64, 104)
LACE: Color = (208, 200, 234)
LACE_DK: Color = (122, 110, 162)
GOLD: Color = (238, 208, 130)
GOLD_DK: Color = (152, 118, 66)
WOOD: Color = (62, 40, 50)
WOOD_HI: Color = (116, 80, 88)

# restraints
IRON: Color = (98, 94, 124)
IRON_DK: Color = (30, 26, 44)
IRON_HI: Color = (192, 188, 216)
RUNE: Color = (188, 120, 255)
RUNE_HI: Color = (238, 210, 255)
RUNE_RED: Color = (255, 84, 124)
THORN: Color = (22, 12, 30)
THORN_EDGE: Color = (112, 46, 146)
THORN_TIP: Color = (214, 84, 152)
BRIAR: Color = (76, 50, 42)
BRIAR_DK: Color = (38, 24, 26)
BRIAR_HI: Color = (132, 92, 72)

# ===================================================================================================
#  small helpers
# ===================================================================================================


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def mix(a: Color, b: Color, f: float) -> Color:
    f = clamp(f, 0.0, 1.0)
    return (int(lerp(a[0], b[0], f)), int(lerp(a[1], b[1], f)), int(lerp(a[2], b[2], f)))


def shade(c: Color, f: float) -> Color:
    return (int(clamp(c[0] * f, 0, 255)), int(clamp(c[1] * f, 0, 255)), int(clamp(c[2] * f, 0, 255)))


def with_alpha(c: Color, a: float) -> tuple[int, int, int, int]:
    return (c[0], c[1], c[2], int(clamp(a, 0, 255)))


def bezier(p0: Vec, p1: Vec, p2: Vec, p3: Vec, n: int = 14) -> list[Vec]:
    out: list[Vec] = []
    for i in range(n + 1):
        u = i / n
        v = 1.0 - u
        out.append((v ** 3 * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u ** 3 * p3[0],
                    v ** 3 * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u ** 3 * p3[1]))
    return out


def quad_path(a: Vec, c: Vec, b: Vec, n: int = 12) -> list[Vec]:
    """Quadratic curve a -> b bent towards control point c (used for limbs)."""
    c1 = (a[0] + (c[0] - a[0]) * 2 / 3, a[1] + (c[1] - a[1]) * 2 / 3)
    c2 = (b[0] + (c[0] - b[0]) * 2 / 3, b[1] + (c[1] - b[1]) * 2 / 3)
    return bezier(a, c1, c2, b, n)


def ribbon(path: list[Vec], widths: list[float]) -> list[Vec]:
    """Closed polygon hugging a centre line with a per-point half width."""
    left: list[Vec] = []
    right: list[Vec] = []
    n = len(path)
    for i, (x, y) in enumerate(path):
        a, c = path[max(0, i - 1)], path[min(n - 1, i + 1)]
        dx, dy = c[0] - a[0], c[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d
        w = widths[i]
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


def taper(n: int, w0: float, w1: float, bulge: float = 0.0) -> list[float]:
    return [lerp(w0, w1, i / n) + bulge * math.sin(math.pi * i / n) for i in range(n + 1)]


def sample_path(pts: Sequence[Vec], spacing: float) -> list[tuple[float, float, float]]:
    """Equidistant samples (x, y, tangent angle) along a polyline."""
    if len(pts) < 2 or spacing <= 0:
        return []
    lens = [0.0]
    for i in range(1, len(pts)):
        lens.append(lens[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = lens[-1]
    out: list[tuple[float, float, float]] = []
    i = 1
    s = spacing * 0.5
    while s < total:
        while i < len(pts) - 1 and lens[i] < s:
            i += 1
        seg = (lens[i] - lens[i - 1]) or 1.0
        f = (s - lens[i - 1]) / seg
        x = lerp(pts[i - 1][0], pts[i][0], f)
        y = lerp(pts[i - 1][1], pts[i][1], f)
        out.append((x, y, math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0])))
        s += spacing
    return out


def ellipse_pts(cx: float, cy: float, rx: float, ry: float, n: int = 28, rot: float = 0.0,
                a0: float = 0.0, a1: float = math.tau) -> list[Vec]:
    cr, sr = math.cos(rot), math.sin(rot)
    out: list[Vec] = []
    for i in range(n + 1):
        a = lerp(a0, a1, i / n)
        ex, ey = math.cos(a) * rx, math.sin(a) * ry
        out.append((cx + ex * cr - ey * sr, cy + ex * sr + ey * cr))
    return out


def catmull(pts: Sequence[Vec], per: int = 8) -> list[Vec]:
    """Catmull-Rom spline through the given points."""
    if len(pts) < 3:
        return list(pts)
    ext = [pts[0]] + list(pts) + [pts[-1]]
    out: list[Vec] = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(per):
            u = k / per
            u2, u3 = u * u, u * u * u
            out.append((0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * u + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * u2
                               + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * u3),
                        0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * u + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * u2
                               + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * u3)))
    out.append(tuple(pts[-1]))  # type: ignore[arg-type]
    return out


def wrap_path(spine: Sequence[Vec], amp: float, turns: float, phase: float) -> list[Vec]:
    """Displace a spine sideways with a sine so it reads as a vine winding around a limb."""
    n = len(spine)
    out: list[Vec] = []
    for i, (x, y) in enumerate(spine):
        a, c = spine[max(0, i - 1)], spine[min(n - 1, i + 1)]
        dx, dy = c[0] - a[0], c[1] - a[1]
        d = math.hypot(dx, dy) or 1.0
        o = math.sin(i / max(1, n - 1) * turns * math.tau + phase) * amp
        out.append((x - dy / d * o, y + dx / d * o))
    return out


def ep(c: Vec, rx: float, ry: float, rot: float, a: float, k: float = 1.0) -> Vec:
    """Point on a rotated ellipse (angle a, radius multiplier k)."""
    ex, ey = math.cos(a) * rx * k, math.sin(a) * ry * k
    cr, sr = math.cos(rot), math.sin(rot)
    return (c[0] + ex * cr - ey * sr, c[1] + ex * sr + ey * cr)


def pointed_arch(x0: float, x1: float, spring: float, bottom: float, steps: int = 12) -> list[Vec]:
    """Gothic (equilateral) arch opening: straight jambs plus two circular arcs."""
    r = x1 - x0
    pts: list[Vec] = [(x0, bottom)]
    for i in range(steps + 1):
        a = math.radians(180 - 60 * i / steps)
        pts.append((x1 + r * math.cos(a), spring - r * math.sin(a)))
    for i in range(1, steps + 1):
        a = math.radians(60 - 60 * i / steps)
        pts.append((x0 + r * math.cos(a), spring - r * math.sin(a)))
    pts.append((x1, bottom))
    return pts


def load_font(size: int, bold: bool = False, italic: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("georgia,palatinolinotype,garamond,timesnewroman,dejavuserif,serif", size,
                               bold=bold, italic=italic)


# ---------------------------------------------------------------------------------------------------
#  radial glow sprite caches
# ---------------------------------------------------------------------------------------------------
_GLOW_ADD: dict[tuple[int, Color, int], pygame.Surface] = {}
_GLOW_ALPHA: dict[tuple[int, Color, int], pygame.Surface] = {}


def glow_add(radius: int, color: Color, level: int = 6) -> pygame.Surface:
    """Black-background radial gradient meant for additive blitting (BLEND_RGB_ADD)."""
    radius = max(2, int(radius))
    level = int(clamp(level, 0, 8))
    key = (radius, color, level)
    surf = _GLOW_ADD.get(key)
    if surf is None:
        if len(_GLOW_ADD) > 600:
            _GLOW_ADD.clear()
        surf = pygame.Surface((radius * 2, radius * 2))
        k = level / 6.0
        step = max(1, radius // 40)
        for r in range(radius, 0, -step):
            f = (1.0 - r / radius) ** 2 * k
            pygame.draw.circle(surf, (min(255, int(color[0] * f)), min(255, int(color[1] * f)),
                                      min(255, int(color[2] * f))), (radius, radius), r)
        _GLOW_ADD[key] = surf
    return surf


def glow_alpha(radius: int, color: Color, alpha: int = 160) -> pygame.Surface:
    """Per-pixel-alpha radial gradient for normal blitting (fog, sprite-layer glows)."""
    radius = max(2, int(radius))
    alpha = int(clamp(alpha, 0, 255)) // 16 * 16
    key = (radius, color, alpha)
    surf = _GLOW_ALPHA.get(key)
    if surf is None:
        if len(_GLOW_ALPHA) > 600:
            _GLOW_ALPHA.clear()
        surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        step = max(1, radius // 40)
        for r in range(radius, 0, -step):
            f = (1.0 - r / radius) ** 2
            pygame.draw.circle(surf, (color[0], color[1], color[2], int(alpha * f)), (radius, radius), r)
        _GLOW_ALPHA[key] = surf
    return surf


# ===================================================================================================
#  data model
# ===================================================================================================
class RestraintKind(Enum):
    CROWN_OF_THORNS = "crown_of_thorns"
    SACRED_RUNE_BINDINGS = "sacred_rune_bindings"
    SHADOW_THORN_VINES = "shadow_thorn_vines"
    GOTHIC_CHAINS = "gothic_chains"


@dataclass(frozen=True)
class RestraintLore:
    name: str
    lore: str
    accent: Color


RESTRAINT_LORE: dict[RestraintKind, RestraintLore] = {
    RestraintKind.CROWN_OF_THORNS: RestraintLore(
        "Crown of Thorns",
        "Braided from the briars of the Weeping Garden. Every thorn drinks a verse from the wearer's mind, "
        "leaving a silence the Choir is eager to fill.",
        (226, 120, 120)),
    RestraintKind.SACRED_RUNE_BINDINGS: RestraintLore(
        "Sacred Rune Bindings",
        "Seals of a forsaken liturgy, inscribed in light that was once holy. They gnaw at the will of whoever "
        "bears them and answer only to the voice that sang them.",
        (190, 126, 255)),
    RestraintKind.SHADOW_THORN_VINES: RestraintLore(
        "Shadow Thorn Vines",
        "Barbed vines grown from the shadows of the drowned nave. They tighten with every breath, feeding on "
        "fear and the slow warmth of the living.",
        (176, 84, 214)),
    RestraintKind.GOTHIC_CHAINS: RestraintLore(
        "Gothic Chains",
        "Black-iron links forged in the bell foundry beneath the cathedral. Each link rings with the Choir's "
        "ninth note, heavy enough to anchor a falling star.",
        (170, 172, 214)),
}

# (minimum ratio, label, colour) - first match wins
STATUS_STEPS: tuple[tuple[float, str, Color], ...] = (
    (0.85, "Unyielding", (214, 214, 236)),
    (0.60, "Resolute", (190, 170, 240)),
    (0.35, "Straining", (240, 200, 120)),
    (0.12, "Fraying", (246, 150, 100)),
    (0.00, "Failing", (255, 96, 110)),
)
STRUGGLE_PROMPT = "Press [E] to Struggle"


@dataclass(eq=False)
class Restraint:
    """One visual restraint. Optional display text can mirror a game's real status effect."""
    kind: RestraintKind
    resistance: float = 100.0
    max_resistance: float = 100.0
    shake: float = 0.0          # 0..1, set to 1.0 on a struggle attempt; decays on its own
    display_name: Optional[str] = None
    display_lore: Optional[str] = None

    @property
    def ratio(self) -> float:
        return clamp(self.resistance / self.max_resistance, 0.0, 1.0) if self.max_resistance > 0 else 0.0

    @property
    def broken(self) -> bool:
        return self.resistance <= 0.0

    @property
    def status(self) -> tuple[str, Color]:
        if self.broken:
            return "Shattered", (120, 120, 140)
        for floor, label, color in STATUS_STEPS:
            if self.ratio >= floor:
                return label, color
        return STATUS_STEPS[-1][1], STATUS_STEPS[-1][2]

    @property
    def info(self) -> RestraintLore:
        base = RESTRAINT_LORE[self.kind]
        if self.display_name is None and self.display_lore is None:
            return base
        # GameApp can attach the actual gameplay effect's label/lore while keeping
        # the silhouette and accent colour from this renderer's visual restraint.
        return RestraintLore(self.display_name or base.name, self.display_lore or base.lore, base.accent)


class CharacterKind(Enum):
    FALLEN_ANGEL = "fallen_angel"
    WITCH = "witch"
    WARRIOR = "warrior"
    TANK = "tank"
    ROGUE = "rogue"
    KITSUNE = "kitsune"
    VAMPIRE = "vampire"
    DRAGONKIN = "dragonkin"


_UID = itertools.count(1)


@dataclass(eq=False)
class Character:
    """Anything the renderer can draw. (x, y) is the point on the floor between the feet."""
    kind: CharacterKind
    name: str
    x: float
    y: float
    scale: float = 1.0
    restraints: list[Restraint] = field(default_factory=list)
    phase: float = field(default_factory=lambda: random.uniform(0.0, math.tau))
    uid: int = field(default_factory=lambda: next(_UID))
    entity_uid: int = 0  # UID of the gameplay entity; bridges combat animation events to this model.
    awakened: bool = False       # non-authoritative presentation flags mirrored from the player entity
    decoy_turns: int = 0
    blood: int = 0                # Vampire resource accent; mirrored for presentation only
    heat: int = 0                 # Dragonkin resource accent; mirrored for presentation only
    overheated: bool = False
    skin_key: str = "default"

    def restraint(self, kind: RestraintKind) -> Optional[Restraint]:
        for r in self.restraints:
            if r.kind is kind:
                return r
        return None

    def bind(self, kind: RestraintKind, resistance: float = 100.0) -> Restraint:
        existing = self.restraint(kind)
        if existing is not None:
            existing.resistance = existing.max_resistance = resistance
            return existing
        r = Restraint(kind, resistance, resistance)
        self.restraints.append(r)
        return r

    def release(self, kind: RestraintKind) -> None:
        self.restraints = [r for r in self.restraints if r.kind is not kind]


@dataclass(eq=False)
class HoverTarget:
    character: Character
    restraint: Restraint


# ===================================================================================================
#  atmosphere: backdrop, fog, embers, light shafts, vignette
# ===================================================================================================
class Ember:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color", "phase", "freq", "amp", "near", "gravity")

    def __init__(self) -> None:
        self.x = self.y = self.vx = self.vy = 0.0
        self.life = self.max_life = 1.0
        self.size = 2.0
        self.color: Color = (255, 150, 64)
        self.phase = self.freq = self.amp = self.gravity = 0.0
        self.near = False


class Atmosphere:
    EMBER_COLORS: tuple[Color, ...] = ((255, 150, 64), (255, 198, 104), (255, 112, 56), (206, 140, 255), (150, 110, 255))

    def __init__(self, w: int, h: int, floor_y: int, seed: int = 7, ember_count: int = 96) -> None:
        self.w, self.h, self.floor_y = w, h, floor_y
        self.rng = random.Random(seed)
        self.background = self._make_background()
        self.shafts = self._make_shafts()
        self.vignette = self._make_vignette()
        fh = max(60, int(h * 0.2))
        # (tile, y, speed px/s, vertical bob, phase)
        self.fog_back: list[tuple[pygame.Surface, int, float, float, float]] = [
            (self._make_fog(fh, 16, fh // 3, fh // 2 - 2, (150, 130, 214), 48, seed + 1), floor_y - int(fh * 0.8), 6.0, 5.0, 0.0),
            (self._make_fog(fh, 18, fh // 3, fh // 2 - 2, (118, 98, 176), 48, seed + 2), floor_y - int(fh * 0.1), -10.0, 7.0, 1.7),
        ]
        self.fog_front: list[tuple[pygame.Surface, int, float, float, float]] = [
            (self._make_fog(fh, 14, fh // 3, fh // 2 - 2, (98, 82, 148), 64, seed + 3), h - int(fh * 0.95), 16.0, 6.0, 3.1),
        ]
        self.embers: list[Ember] = [self._spawn_ember(True) for _ in range(ember_count)]
        self.bursts: list[Ember] = []

    # ---- construction ---------------------------------------------------------------------------
    def _make_background(self) -> pygame.Surface:
        w, h, fy = self.w, self.h, self.floor_y
        s = pygame.Surface((w, h))
        for y in range(h):
            f = y / max(1, h - 1)
            pygame.draw.line(s, (int(9 + 20 * f), int(6 + 11 * f), int(20 + 34 * f)), (0, y), (w, y))
        # A blood eclipse nested inside the ruined cathedral's rose window.
        cx, cy, r = int(w * 0.57), int(fy * 0.31), int(fy * 0.235)
        halo = int(r * 2.8)
        s.blit(glow_alpha(halo, (166, 34, 73), 124), (cx - halo, cy - halo))
        pygame.draw.circle(s, (36, 9, 26), (cx, cy), r + 7)
        pygame.draw.circle(s, (151, 30, 61), (cx, cy), r + 2, max(2, int(r * 0.025)))
        pygame.draw.circle(s, (24, 17, 38), (cx, cy), r)
        pygame.draw.circle(s, (93, 23, 53), (cx + int(r*0.14), cy - int(r*0.06)), int(r*0.86))
        pygame.draw.circle(s, (18, 18, 37), (cx + int(r*0.21), cy - int(r*0.07)), int(r*0.77))
        # Broken orbital rings and thorn-like eclipse rays.
        for rad, col, width in ((r*1.13, (91, 37, 77), 2), (r*1.23, (48, 29, 61), 1)):
            pygame.draw.circle(s, col, (cx, cy), int(rad), width)
        for i in range(18):
            a = i * math.tau / 18 + 0.10
            x0, y0 = cx + math.cos(a) * r * 1.06, cy + math.sin(a) * r * 1.06
            x1, y1 = cx + math.cos(a) * r * (1.12 + (i % 3) * 0.06), cy + math.sin(a) * r * (1.12 + (i % 3) * 0.06)
            pygame.draw.line(s, (166, 47, 83), (int(x0), int(y0)), (int(x1), int(y1)), 2)
        glass = ((118, 38, 105), (58, 64, 126), (155, 43, 72), (76, 50, 120))
        pr = max(3, int(r * 0.2))
        for i in range(12):
            a = i * math.tau / 12 + 0.26
            px, py = cx + math.cos(a) * r * 0.62, cy + math.sin(a) * r * 0.62
            pygame.draw.circle(s, glass[i % 4], (int(px), int(py)), pr)
            pygame.draw.circle(s, (92, 70, 150), (int(px), int(py)), pr, 2)
        for i in range(12):
            a = i * math.tau / 12
            pygame.draw.line(s, (84, 64, 138), (cx + math.cos(a) * r * 0.16, cy + math.sin(a) * r * 0.16),
                             (cx + math.cos(a) * r, cy + math.sin(a) * r), 2)
        pygame.draw.circle(s, (160, 126, 230), (cx, cy), max(3, int(r * 0.13)))
        pygame.draw.circle(s, (96, 72, 158), (cx, cy), r, 4)
        pygame.draw.circle(s, (64, 48, 110), (cx, cy), int(r * 0.4), 2)
        # far arcade
        top, n = int(fy * 0.5), 7
        span = w / n
        pygame.draw.rect(s, (13, 9, 24), (0, top, w, fy - top))
        for i in range(n):
            x0, x1 = i * span + span * 0.14, (i + 1) * span - span * 0.14
            opening = pointed_arch(x0, x1, top + (fy - top) * 0.42, fy)
            pygame.draw.polygon(s, (22, 16, 42), opening)
            pygame.draw.lines(s, (48, 36, 84), False, opening[1:-1], 2)
            gx, gy = int((x0 + x1) / 2), int(fy - (fy - top) * 0.3)
            s.blit(glow_alpha(int(span * 0.5), (80, 60, 150), 64), (gx - int(span * 0.5), gy - int(span * 0.5)))
        # Broken spires silhouette the skyline; the skyline is intentionally asymmetric.
        spires = ((0.08,0.30,0.08),(0.22,0.17,0.055),(0.34,0.35,0.045),(0.72,0.26,0.06),(0.84,0.16,0.07),(0.94,0.32,0.055))
        for fx, height, width in spires:
            sx = int(w * fx); sw = max(10, int(w * width)); sy = int(fy * height)
            tower = [(sx-sw//2, fy), (sx-sw//2, sy+24), (sx-sw//4, sy+10), (sx, sy),
                     (sx+sw//4, sy+10), (sx+sw//2, sy+24), (sx+sw//2, fy)]
            pygame.draw.polygon(s, (10, 8, 20), tower)
            pygame.draw.lines(s, (32, 24, 48), False, tower[1:-1], 2)
            pygame.draw.line(s, (51, 33, 62), (sx, sy+2), (sx, sy+int((fy-sy)*0.42)), 1)
            for j in range(3):
                yy = sy + int((fy-sy) * (0.25 + j*0.19))
                pygame.draw.line(s, (23, 17, 37), (sx-sw//2, yy), (sx+sw//2, yy-2), 2)
        # Suspended masonry and rune shards give the void foreground depth.
        shard_rng = random.Random(811)
        for _ in range(38):
            sx = shard_rng.randint(int(w*0.20), int(w*0.82))
            sy = shard_rng.randint(int(fy*0.16), int(fy*0.78))
            size = shard_rng.randint(4, 13)
            pygame.draw.polygon(s, (19, 14, 31), [(sx,sy-size),(sx+size//2,sy-1),(sx+size//3,sy+size),(sx-size//2,sy+size//3)])
            if shard_rng.random() < 0.23:
                pygame.draw.line(s, (104,35,86), (sx, sy-size//2), (sx+size//3, sy+size//2), 1)
        # big foreground pillars with ribs and capitals
        for fx in (0.035, 0.165, 0.835, 0.965):
            pw = int(w * 0.05)
            px = int(w * fx - pw / 2)
            pygame.draw.rect(s, (15, 11, 27), (px, 0, pw, fy + 4))
            pygame.draw.rect(s, (36, 28, 62), (px, 0, pw, fy + 4), 2)
            for k in range(1, 4):
                pygame.draw.line(s, (26, 20, 46), (px + k * pw // 4, 0), (px + k * pw // 4, fy), 1)
            pygame.draw.rect(s, (24, 18, 42), (px - 6, int(fy * 0.12), pw + 12, 12))
            pygame.draw.rect(s, (24, 18, 42), (px - 6, fy - 12, pw + 12, 14))
        # hanging chains
        for hx, hl in ((0.30, 0.20), (0.42, 0.34), (0.58, 0.30), (0.70, 0.22)):
            x = int(w * hx)
            for y in range(0, int(fy * hl), 7):
                pygame.draw.ellipse(s, (58, 52, 82), (x - 2, y, 4, 8), 1)
        # floor
        for y in range(fy, h):
            f = (y - fy) / max(1, h - fy)
            pygame.draw.line(s, (int(24 - 14 * f), int(18 - 10 * f), int(38 - 22 * f)), (0, y), (w, y))
        for i in range(1, 10):
            y = fy + int((h - fy) * (i / 9) ** 1.8)
            pygame.draw.line(s, (40, 31, 66), (0, y), (w, y), 1)
        for k in range(-9, 10):
            pygame.draw.line(s, (36, 28, 60), (int(w / 2 + k * span * 0.22), fy), (int(w / 2 + k * span * 1.15), h), 1)
        # Ancient, fragmented summoning circle set into the polished floor.
        scx, scy = w // 2, fy + int((h-fy)*0.48)
        rx, ry = int(w*0.16), int((h-fy)*0.14)
        pygame.draw.ellipse(s, (43, 27, 61), (scx-rx, scy-ry, rx*2, ry*2), 2)
        pygame.draw.ellipse(s, (66, 35, 82), (scx-int(rx*.76), scy-int(ry*.70), int(rx*1.52), int(ry*1.4)), 1)
        for i in range(12):
            a = i * math.tau / 12
            x0, y0 = scx + math.cos(a)*rx*.76, scy + math.sin(a)*ry*.70
            x1, y1 = scx + math.cos(a)*rx, scy + math.sin(a)*ry
            if i not in (2, 5, 8, 10):
                pygame.draw.line(s, (70, 38, 86), (int(x0), int(y0)), (int(x1), int(y1)), 1)
            if i % 3 == 0:
                px, py = scx + math.cos(a)*rx*.88, scy + math.sin(a)*ry*.82
                pygame.draw.polygon(s, (87, 39, 84), [(int(px),int(py-5)),(int(px+4),int(py)),(int(px),int(py+5)),(int(px-4),int(py))], 1)
        refl = int(w * 0.28)
        s.blit(glow_alpha(refl, (124, 50, 110), 68), (w // 2 - refl, fy - refl // 3))
        pygame.draw.line(s, (60, 46, 104), (0, fy), (w, fy), 2)
        return s

    def _make_shafts(self) -> pygame.Surface:
        w, h, fy = self.w, self.h, self.floor_y
        s = pygame.Surface((w, h))
        s.fill((0, 0, 0))
        spec = ((0.30, 0.18), (0.42, 0.34), (0.58, 0.66), (0.70, 0.82))
        for tx, bx in spec:
            for wd, col in ((1.0, (7, 5, 14)), (0.72, (9, 7, 18)), (0.44, (11, 9, 22))):
                pts = [(w * tx - 22 * wd, 0), (w * tx + 22 * wd, 0), (w * bx + 90 * wd, fy + (h - fy) * 0.5),
                       (w * bx - 90 * wd, fy + (h - fy) * 0.5)]
                pygame.draw.polygon(s, col, pts)
        return s

    def _make_vignette(self) -> pygame.Surface:
        w, h = self.w, self.h
        v = pygame.Surface((w, h), pygame.SRCALPHA)
        depth = int(min(w, h) * 0.34)
        for i in range(0, depth, 3):
            a = int(170 * (1.0 - i / depth) ** 2)
            pygame.draw.rect(v, (0, 0, 0, a), (i, i, w - 2 * i, h - 2 * i), 3)
        return v

    def _make_fog(self, height: int, count: int, rmin: int, rmax: int, color: Color, alpha: int, seed: int) -> pygame.Surface:
        rng = random.Random(seed)
        s = pygame.Surface((self.w, height), pygame.SRCALPHA)
        for _ in range(count):
            r = rng.randint(max(8, rmin), max(9, rmax))
            x = rng.randint(0, self.w)
            y = rng.randint(r, max(r, height - r))
            g = glow_alpha(r, color, alpha)
            for off in (-self.w, 0, self.w):
                s.blit(g, (x - r + off, y - r))
        return s

    # ---- embers ---------------------------------------------------------------------------------
    def _spawn_ember(self, initial: bool = False) -> Ember:
        r = self.rng
        e = Ember()
        e.near = r.random() < 0.28
        e.x = r.uniform(0, self.w)
        e.y = r.uniform(0, self.h) if initial else self.h + r.uniform(4, 40)
        e.vx = r.uniform(-6, 6)
        e.vy = -r.uniform(14, 42) * (1.4 if e.near else 1.0)
        e.max_life = r.uniform(6.0, 13.0)
        e.life = r.uniform(1.0, e.max_life) if initial else e.max_life
        e.size = r.uniform(1.3, 2.5) * (1.8 if e.near else 1.0)
        e.color = r.choice(self.EMBER_COLORS)
        e.phase = r.uniform(0, math.tau)
        e.freq = r.uniform(0.8, 2.4)
        e.amp = r.uniform(8, 26)
        e.gravity = 0.0
        return e

    def burst(self, x: float, y: float, color: Color, count: int = 28) -> None:
        r = self.rng
        for _ in range(count):
            if len(self.bursts) > 420:
                break
            e = Ember()
            a, sp = r.uniform(0, math.tau), r.uniform(40, 200)
            e.x, e.y = x, y
            e.vx, e.vy = math.cos(a) * sp, math.sin(a) * sp - 50
            e.max_life = e.life = r.uniform(0.7, 1.7)
            e.size = r.uniform(1.4, 3.0)
            e.color = color if r.random() < 0.7 else r.choice(self.EMBER_COLORS)
            e.phase, e.freq, e.amp = r.uniform(0, math.tau), r.uniform(2, 5), 0.0
            e.gravity = 150.0
            e.near = r.random() < 0.4
            self.bursts.append(e)

    def update(self, dt: float, t: float) -> None:
        for i, e in enumerate(self.embers):
            e.life -= dt
            e.y += e.vy * dt
            e.x += (e.vx + math.sin(t * e.freq + e.phase) * e.amp) * dt
            if e.life <= 0 or e.y < -30 or e.x < -40 or e.x > self.w + 40:
                self.embers[i] = self._spawn_ember()
        alive: list[Ember] = []
        for e in self.bursts:
            e.life -= dt
            if e.life <= 0:
                continue
            e.vy += e.gravity * dt
            e.vx *= max(0.0, 1.0 - 1.8 * dt)
            e.x += e.vx * dt
            e.y += e.vy * dt
            alive.append(e)
        self.bursts = alive

    # ---- drawing --------------------------------------------------------------------------------
    def draw_backdrop(self, surf: pygame.Surface, t: float) -> None:
        surf.blit(self.background, (0, 0))
        # slowly breathing rose-window light
        cx, cy = self.w // 2, int(self.floor_y * 0.36)
        rad = int(self.floor_y * 0.44)
        lvl = 2 + int(1.2 * (0.5 + 0.5 * math.sin(t * 0.7)))
        surf.blit(glow_add(rad, (150, 100, 235), lvl), (cx - rad, cy - rad), special_flags=pygame.BLEND_RGB_ADD)
        surf.blit(self.shafts, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _blit_fog(self, surf: pygame.Surface, layers: list, t: float) -> None:
        for tile, y, speed, bob, phase in layers:
            x = int((t * speed) % self.w)
            yy = y + int(math.sin(t * 0.35 + phase) * bob)
            surf.blit(tile, (x - self.w, yy))
            surf.blit(tile, (x, yy))

    def draw_fog_back(self, surf: pygame.Surface, t: float) -> None:
        self._blit_fog(surf, self.fog_back, t)

    def draw_fog_front(self, surf: pygame.Surface, t: float) -> None:
        self._blit_fog(surf, self.fog_front, t)

    def draw_embers(self, surf: pygame.Surface, t: float, near: bool) -> None:
        for e in itertools.chain(self.embers, self.bursts):
            if e.near != near:
                continue
            fade = min(1.0, e.life / 1.4, (e.max_life - e.life) / 0.8 + 0.001)
            flick = 0.65 + 0.35 * math.sin(t * (7.0 + e.freq * 3.0) + e.phase * 3.0)
            b = fade * flick
            if b < 0.05:
                continue
            rad = int(clamp(round(e.size * (3.4 if near else 2.8) / 2) * 2, 4, 16))
            level = 6 if b > 0.66 else (4 if b > 0.33 else 2)
            surf.blit(glow_add(rad, e.color, level), (int(e.x) - rad, int(e.y) - rad), special_flags=pygame.BLEND_RGB_ADD)
            core = mix((0, 0, 0), mix(e.color, WHITE, 0.55), 0.35 + 0.65 * b)
            pygame.draw.circle(surf, core, (int(e.x), int(e.y)), max(1, int(e.size * 0.55)))

    def draw_vignette(self, surf: pygame.Surface) -> None:
        surf.blit(self.vignette, (0, 0))


# ===================================================================================================
#  supersampled sprite brush
# ===================================================================================================
LW, LH = 480, 420           # sprite layer size in 1x units
OX, OY = 240, 390           # position of the feet-centre inside the layer
SS = 2                      # supersampling factor
SPRITE_INTERVAL = 1.0 / 30.0
LASH: Color = (34, 20, 48)
FLOOR_ANCHOR_X = 150.0      # where wrist chains are bolted to the floor
ANKLE_ANCHOR_X = 46.0


class Brush:
    """Draws in sprite-local units (feet at 0,0; up is negative y) onto a supersampled layer.

    Colours with alpha < 255 are painted through a temporary SRCALPHA surface so they blend properly.
    """

    def __init__(self, layer: pygame.Surface, k: float) -> None:
        self.layer, self.k = layer, k
        self.ox, self.oy = OX * k, OY * k

    def P(self, x: float, y: float) -> Vec:
        return (self.ox + x * self.k, self.oy + y * self.k)

    def px(self, w: float) -> int:
        return max(1, int(round(w * self.k)))

    def _paint(self, pts: list[Vec], color: tuple, painter: Callable, pad: int = 3) -> None:
        if len(color) == 4 and color[3] < 255:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            x0, y0 = int(math.floor(min(xs))) - pad, int(math.floor(min(ys))) - pad
            w, h = int(math.ceil(max(xs))) - x0 + pad * 2, int(math.ceil(max(ys))) - y0 + pad * 2
            if w < 2 or h < 2 or w > 2600 or h > 2600:
                return
            tmp = pygame.Surface((w, h), pygame.SRCALPHA)
            painter(tmp, [(x - x0, y - y0) for x, y in pts], color)
            self.layer.blit(tmp, (x0, y0))
        else:
            painter(self.layer, pts, color[:3])

    def poly(self, pts: Sequence[Vec], color: tuple, edge: Optional[tuple] = None, ew: float = 1.0) -> None:
        if len(pts) < 3:
            return
        px = [self.P(x, y) for x, y in pts]
        self._paint(px, color, lambda s, p, c: pygame.draw.polygon(s, c, p))
        if edge is not None:
            wd = self.px(ew)
            self._paint(px, edge, lambda s, p, c: pygame.draw.lines(s, c, True, p, wd), pad=wd + 2)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, color: tuple, edge: Optional[tuple] = None,
                ew: float = 1.0) -> None:
        x0, y0 = self.P(cx - rx, cy - ry)
        x1, y1 = self.P(cx + rx, cy + ry)
        corners = [(x0, y0), (x1, y1)]

        def rect_of(p: list[Vec]) -> pygame.Rect:
            return pygame.Rect(int(p[0][0]), int(p[0][1]), max(1, int(p[1][0] - p[0][0])), max(1, int(p[1][1] - p[0][1])))

        self._paint(corners, color, lambda s, p, c: pygame.draw.ellipse(s, c, rect_of(p)))
        if edge is not None:
            wd = self.px(ew)
            self._paint(corners, edge, lambda s, p, c: pygame.draw.ellipse(s, c, rect_of(p), wd), pad=wd + 2)

    def circle(self, cx: float, cy: float, r: float, color: tuple, edge: Optional[tuple] = None, ew: float = 1.0) -> None:
        self.ellipse(cx, cy, r, r, color, edge, ew)

    def line(self, a: Vec, c: Vec, color: tuple, w: float = 1.0) -> None:
        wd = self.px(w)
        pts = [self.P(*a), self.P(*c)]
        self._paint(pts, color, lambda s, p, col: pygame.draw.line(s, col, p[0], p[1], wd), pad=wd + 2)

    def path(self, pts: Sequence[Vec], color: tuple, w: float = 1.0, caps: bool = True) -> None:
        if len(pts) < 2:
            return
        wd = self.px(w)
        px = [self.P(x, y) for x, y in pts]

        def paint(s: pygame.Surface, p: list[Vec], col: tuple) -> None:
            pygame.draw.lines(s, col, False, p, wd)
            if caps and wd > 2:
                for q in (p if wd > 3 else (p[0], p[-1])):
                    pygame.draw.circle(s, col, (int(q[0]), int(q[1])), wd // 2)

        self._paint(px, color, paint, pad=wd + 2)

    def glow(self, cx: float, cy: float, r: float, color: Color, alpha: int = 150) -> None:
        rad = max(2, int(r * self.k))
        x, y = self.P(cx, cy)
        self.layer.blit(glow_alpha(rad, color, alpha), (int(x) - rad, int(y) - rad))


# ===================================================================================================
#  character painter (one instance per repaint)
# ===================================================================================================
Hit = tuple[RestraintKind, tuple[float, float, float, float]]
Light = tuple[float, float, float, Color, int]


class SpritePainter:
    def __init__(self, brush: Brush, t: float, ch: Character) -> None:
        self.b, self.t, self.ch, self.ph = brush, t, ch, ch.phase
        self.res: dict[RestraintKind, Restraint] = {r.kind: r for r in ch.restraints if not r.broken}
        self.hits: list[Hit] = []
        self.lights: list[Light] = []
        self.skin_def = get_skin(getattr(ch, "skin_key", "default"))
        self.accent_col = self.skin_def.accent_color
        self.trim_col = self.skin_def.trim_color

    # ---- bookkeeping ----------------------------------------------------------------------------
    def hit(self, kind: RestraintKind, x: float, y: float, w: float, h: float) -> None:
        self.hits.append((kind, (x, y, w, h)))

    def hit_pts(self, kind: RestraintKind, pts: Sequence[Vec], pad: float = 4.0) -> None:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.hit(kind, min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)

    def light(self, x: float, y: float, r: float, color: Color, level: int) -> None:
        self.lights.append((x, y, r, color, level))

    @staticmethod
    def inten(r: Restraint) -> float:
        return 0.45 + 0.55 * r.ratio

    def paint(self) -> None:
        painter = {
            CharacterKind.FALLEN_ANGEL: self._paint_angel,
            CharacterKind.WITCH: self._paint_witch,
            CharacterKind.WARRIOR: self._paint_warrior,
            CharacterKind.TANK: self._paint_tank,
            CharacterKind.ROGUE: self._paint_rogue,
            CharacterKind.KITSUNE: self._paint_kitsune,
            CharacterKind.VAMPIRE: self._paint_vampire,
            CharacterKind.DRAGONKIN: self._paint_dragonkin,
        }.get(self.ch.kind, self._paint_witch)
        painter()

    # ---- class-specific silhouettes ------------------------------------------------------------
    # Separate equipment silhouettes keep the three martial classes readable at gameplay scale.
    def _paint_warrior(self) -> None:
        """Silver-haired Gothic Knight with radiant holy/radiant golden sword.
        Matches Image 1 reference: silver hair, deep sapphire eyes, ornate silver plate,
        gold filigree accents, white/black tabard, and luminous golden blade.
        """
        b, t = self.b, self.t
        bob = math.sin(t * 2.0 + self.ph) * 1.5
        sway = math.sin(t * 1.4 + self.ph) * 2.5

        # Ground shadow
        b.ellipse(0, -1, 50, 8, (0, 0, 0, 95))

        # Color palette
        steel_plate = (210, 215, 228)
        steel_sh = (155, 160, 178)
        steel_dk = (95, 100, 118)
        gold_trim = mix((245, 210, 100), self.accent_col, 0.45)
        gold_dk = mix((175, 130, 45), self.trim_col, 0.45)

        cape_back = mix((24, 22, 34), self.trim_col, 0.3)
        tunic_wh = (245, 246, 252)
        tunic_sh = (205, 208, 220)
        leather_dk = (38, 32, 36)

        skin = (252, 235, 224)
        skin_sh = (224, 192, 175)
        eye_col = (55, 120, 215)
        eye_hi = (165, 215, 255)

        hair_col = (246, 248, 255)
        hair_sh = (188, 194, 212)
        hair_hi = (255, 255, 255)

        # 1. Flowing Back Cape
        cape_pts = [
            (-26, -150 + bob),
            (-44 + sway * 0.5, -110),
            (-52 + sway, -35),
            (-32 + sway * 0.7, -42),
            (-18 + sway * 0.4, -12),
            (0, -22),
            (18 + sway * 0.4, -12),
            (36 + sway * 0.7, -40),
            (50 + sway, -32),
            (42 + sway * 0.5, -110),
            (26, -150 + bob),
        ]
        b.poly(cape_pts, cape_back, gold_dk, 1.2)
        b.path([(-52 + sway, -35), (-18 + sway * 0.4, -12), (0, -22), (18 + sway * 0.4, -12), (50 + sway, -32)], gold_trim, 1.5)

        # 2. Armored Legs & Boots (Gothic Sabatons & Greaves)
        for s in (-1, 1):
            lx = s * 14
            # Thigh under-armor
            b.poly([(lx - 7, -98 + bob * 0.5), (lx + 7, -98 + bob * 0.5), (lx + 6, -56), (lx - 6, -56)], leather_dk, steel_dk, 0.8)
            # Knee poleyn (plate cop with gold star/fluting)
            b.poly([(lx - 8, -58), (lx, -64), (lx + 8, -58), (lx + 6, -46), (lx, -44), (lx - 6, -46)], steel_plate, gold_trim, 1.2)
            b.circle(lx, -53, 2.4, gold_trim, gold_dk, 0.6)
            # Greaves (shin plate)
            b.poly([(lx - 7, -46), (lx + 7, -46), (lx + 8, -12), (lx - 8, -12)], steel_plate, steel_sh, 1.0)
            b.line((lx, -44), (lx, -12), steel_sh, 1.0)
            # Pointed Sabatons (feet)
            b.poly([(lx - 8, -12), (lx + 8, -12), (lx + s * 12, 1), (lx - s * 2, 1)], steel_dk, steel_plate, 1.0)
            b.path([(lx - 7, -8), (lx + 4, -8), (lx + s * 8, 0)], gold_trim, 1.0)

        # 3. Layered White & Navy Tabard / Fauld
        b.poly([(-18, -110 + bob), (18, -110 + bob), (22, -68), (0, -78), (-22, -68)], tunic_wh, tunic_sh, 1.0)
        b.poly([(-12, -108 + bob), (12, -108 + bob), (15, -70), (0, -76), (-15, -70)], cape_back, gold_trim, 0.9)
        # Leather belt and gold buckle
        b.poly([(-19, -108 + bob), (19, -108 + bob), (19, -100 + bob), (-19, -100 + bob)], leather_dk, gold_dk, 1.0)
        b.poly([(-5, -107 + bob), (5, -107 + bob), (5, -101 + bob), (-5, -101 + bob)], gold_trim, gold_dk, 1.2)

        # 4. Ornate Steel Cuirass (Breastplate with golden filigree)
        b.poly([(-24, -156 + bob), (24, -156 + bob), (20, -108 + bob), (-20, -108 + bob)], steel_plate, steel_sh, 1.4)
        b.poly([(-16, -152 + bob), (0, -158 + bob), (16, -152 + bob), (12, -114 + bob), (0, -110 + bob), (-12, -114 + bob)], tunic_wh, gold_trim, 1.2)
        # Gold filigree lines on chest
        b.path([(-14, -145 + bob), (0, -132 + bob), (14, -145 + bob)], gold_trim, 1.5)
        b.path([(-10, -135 + bob), (0, -124 + bob), (10, -135 + bob)], gold_trim, 1.2)
        b.circle(0, -132 + bob, 3.2, gold_trim, gold_dk, 0.8)
        # Gorget (neck guard)
        b.poly([(-14, -164 + bob), (14, -164 + bob), (16, -152 + bob), (-16, -152 + bob)], steel_plate, gold_trim, 1.1)

        # 5. Tiered Gothic Pauldrons (Shoulder plate armor)
        for s in (-1, 1):
            px = s * 26
            py = -158 + bob
            # Main curved bell pauldron
            b.poly([(px - s * 6, py - 6), (px + s * 14, py - 4), (px + s * 18, py + 14), (px - s * 4, py + 18)], steel_plate, gold_trim, 1.3)
            # Lower articulated lames
            b.poly([(px + s * 2, py + 16), (px + s * 16, py + 12), (px + s * 14, py + 24), (px, py + 26)], steel_dk, gold_trim, 1.0)
            b.circle(px + s * 8, py + 6, 2.5, gold_trim, gold_dk, 0.6)

        # 6. Radiant Golden Greatsword (held angled forward)
        blade_base = (24, -92 + bob)
        blade_mid = (48, -62 + bob * 0.5)
        blade_tip = (78, -18)
        # Crossguard with wings
        b.poly([(14, -98 + bob), (32, -84 + bob), (36, -88 + bob), (18, -102 + bob)], gold_trim, gold_dk, 1.5)
        b.circle(25, -93 + bob, 3.5, (90, 180, 255), gold_trim, 0.8)
        # Two-handed hilt & pommel
        b.line((22, -96 + bob), (10, -110 + bob), leather_dk, 3.5)
        b.circle(9, -111 + bob, 3.2, gold_trim, gold_dk, 1.0)
        # Golden gleaming blade
        b.line(blade_base, blade_tip, (255, 235, 140), 6.5)
        b.line(blade_base, blade_tip, (255, 255, 220), 2.5)
        b.path([(blade_base[0] - 2, blade_base[1] - 2), (blade_tip[0] - 1, blade_tip[1] - 1)], gold_trim, 1.0)
        b.glow(blade_mid[0], blade_mid[1], 26, (255, 220, 110), 110)

        # Armored arms & gauntlets
        b.poly([(-22, -150 + bob), (-34, -126 + bob), (-30, -112 + bob), (-18, -136 + bob)], steel_plate, steel_sh, 1.0)
        self._hand((-32, -110 + bob), 0.8, steel_plate, gold_trim, 1.0)
        b.poly([(18, -148 + bob), (28, -122 + bob), (22, -98 + bob), (14, -124 + bob)], steel_plate, steel_sh, 1.0)
        self._hand((24, -94 + bob), -0.6, steel_plate, gold_trim, 1.0)

        # 7. Silver Hair Back Locks
        for side in (-1, 1):
            h_back = [
                (side * 8, -196 + bob),
                (side * 22, -184 + bob),
                (side * 28 + sway * 0.6, -145 + bob),
                (side * 20 + sway, -110),
                (side * 12 + sway * 0.8, -125),
            ]
            b.poly(h_back, hair_col, hair_sh, 1.0)

        # 8. Face & Beautiful Anime Features
        hc = (0, -194 + bob)
        b.ellipse(hc[0], hc[1], 17.5, 21.0, skin, skin_sh, 0.8)
        self._face(hc, skin, skin_sh, eye_col, eye_hi)

        # 9. Silver Hair Front bangs and Side Strands
        for side in (-1, 1):
            sbang = [
                (side * 10, -210 + bob),
                (side * 18, -196 + bob),
                (side * 16 + sway * 0.3, -168 + bob),
                (side * 11 + sway * 0.2, -174 + bob),
                (side * 13, -198 + bob),
            ]
            b.poly(sbang, hair_col, hair_sh, 0.9)
        b.poly([(-14, -212 + bob), (0, -218 + bob), (14, -212 + bob), (9, -198 + bob), (0, -204 + bob), (-9, -198 + bob)], hair_col, hair_sh, 0.8)
        b.path([(-6, -214 + bob), (-3, -199 + bob)], hair_hi, 1.0)
        b.path([(6, -214 + bob), (3, -199 + bob)], hair_hi, 1.0)

    def _paint_tank(self) -> None:
        """Holy Paladin Crusader in immaculate white/gold plate and radiant blue holy greatsword.
        Matches Image 2 reference: blonde hair, radiant blue eyes, pure white/gold enameled plate,
        massive paladin pauldrons, golden cross tabard, and imposing holy greatsword.
        """
        b, t = self.b, self.t
        bob = math.sin(t * 1.5 + self.ph) * 1.0

        # Ground shadow
        b.ellipse(0, -1, 56, 9, (0, 0, 0, 100))

        # Color palette
        white_plate = (248, 248, 254)
        plate_sh = (205, 210, 225)
        plate_dk = (145, 150, 170)
        gold_trim = mix((248, 214, 98), self.accent_col, 0.45)
        gold_dk = mix((176, 132, 44), self.trim_col, 0.45)
        holy_blue = (65, 145, 235)
        holy_blue_hi = (180, 225, 255)

        skin = (252, 236, 226)
        skin_sh = (226, 194, 178)
        eye_col = (50, 135, 230)
        eye_hi = (165, 220, 255)

        blonde = (248, 222, 126)
        blonde_sh = (196, 154, 72)
        blonde_hi = (255, 246, 185)

        # 1. Armored Legs & Plated Greaves (Heavy Holy Crusader)
        for s in (-1, 1):
            lx = s * 16
            # Heavy thigh plate
            b.poly([(lx - 8, -96 + bob * 0.4), (lx + 8, -96 + bob * 0.4), (lx + 8, -58), (lx - 8, -58)], white_plate, plate_sh, 1.0)
            # Massive golden cross knee poleyn
            b.poly([(lx - 9, -58), (lx, -66), (lx + 9, -58), (lx + 7, -44), (lx - 7, -44)], gold_trim, gold_dk, 1.2)
            b.circle(lx, -55, 2.8, white_plate, gold_dk, 0.8)
            # Enamelled white shin greaves
            b.poly([(lx - 8, -44), (lx + 8, -44), (lx + 9, -10), (lx - 9, -10)], white_plate, gold_trim, 1.2)
            b.line((lx, -42), (lx, -10), gold_trim, 1.2)
            # Heavy sabatons
            b.poly([(lx - 9, -10), (lx + 9, -10), (lx + s * 14, 1), (lx - s * 3, 1)], plate_dk, gold_trim, 1.1)

        # 2. Sacred Cross Tabard (white cloth with gold trim and sacred heraldry)
        b.poly([(-20, -112 + bob), (20, -112 + bob), (24, -62), (-24, -62)], white_plate, gold_trim, 1.4)
        # Golden Cross on tabard
        b.line((0, -108 + bob), (0, -66), gold_trim, 4.5)
        b.line((-14, -92 + bob), (14, -92 + bob), gold_trim, 4.5)
        b.circle(0, -92 + bob, 3.5, holy_blue, gold_dk, 1.0)
        # Heavy gold cingulum (belt)
        b.poly([(-22, -114 + bob), (22, -114 + bob), (22, -104 + bob), (-22, -104 + bob)], gold_trim, gold_dk, 1.2)
        b.poly([(-7, -115 + bob), (7, -115 + bob), (7, -103 + bob), (-7, -103 + bob)], white_plate, gold_dk, 1.2)

        # 3. Solid White & Gold Breastplate
        b.poly([(-26, -160 + bob), (26, -160 + bob), (22, -112 + bob), (-22, -112 + bob)], white_plate, plate_sh, 1.5)
        # Sculpted gorget with glowing holy sapphire
        b.poly([(-16, -168 + bob), (16, -168 + bob), (18, -156 + bob), (-18, -156 + bob)], gold_trim, gold_dk, 1.2)
        b.circle(0, -160 + bob, 4.2, holy_blue, gold_trim, 1.0)
        b.circle(0, -160 + bob, 1.6, holy_blue_hi)

        # 4. Massive Tiered Paladin Pauldrons
        for s in (-1, 1):
            px = s * 29
            py = -162 + bob
            # Main holy winged pauldron
            b.poly([(px - s * 6, py - 8), (px + s * 16, py - 4), (px + s * 20, py + 18), (px - s * 4, py + 22)], white_plate, gold_trim, 1.5)
            # Gold filigree cross on pauldron
            b.line((px + s * 8, py + 2), (px + s * 8, py + 14), gold_trim, 2.5)
            b.line((px + s * 3, py + 8), (px + s * 13, py + 8), gold_trim, 2.5)
            b.circle(px + s * 8, py + 8, 2.0, holy_blue, gold_dk, 0.6)

        # 5. Towering Holy Greatsword (planted resolutely in the ground at center-front)
        blade_x = 0
        blade_top_y = -106 + bob
        blade_bot_y = 0
        # Divine crossguard
        b.poly([(-24, blade_top_y + 4), (24, blade_top_y + 4), (22, blade_top_y + 12), (-22, blade_top_y + 12)], gold_trim, gold_dk, 1.5)
        b.circle(blade_x, blade_top_y + 8, 4.0, holy_blue, gold_trim, 1.0)
        b.circle(blade_x, blade_top_y + 8, 1.8, (255, 255, 255))
        # Hilt & golden pommel
        b.line((blade_x, blade_top_y + 4), (blade_x, blade_top_y - 20), gold_dk, 4.0)
        b.circle(blade_x, blade_top_y - 22, 4.0, gold_trim, gold_dk, 1.2)
        # Armored gauntlets resting on the pommel/crossguard
        self._hand((-7, blade_top_y - 12), -0.2, white_plate, gold_trim, 1.1)
        self._hand((7, blade_top_y - 12), 0.2, white_plate, gold_trim, 1.1)
        # Broad holy blade plunging downward
        b.poly([(blade_x - 7, blade_top_y + 12), (blade_x + 7, blade_top_y + 12), (blade_x + 5, blade_bot_y), (blade_x - 5, blade_bot_y)], white_plate, plate_sh, 1.2)
        b.line((blade_x, blade_top_y + 14), (blade_x, blade_bot_y - 2), holy_blue, 2.0)
        b.glow(blade_x, -45, 30, holy_blue, 90)

        # Armored arms & pauldrons
        for s in (-1, 1):
            b.poly([(s * 20, -154 + bob), (s * 18, -128 + bob), (s * 8, -114 + bob), (s * 12, -148 + bob)], white_plate, gold_trim, 1.1)

        # 6. Blonde Hair Back Layers
        for side in (-1, 1):
            h_back = [
                (side * 8, -198 + bob),
                (side * 20, -188 + bob),
                (side * 24, -156 + bob),
                (side * 14, -138 + bob),
                (side * 8, -150 + bob),
            ]
            b.poly(h_back, blonde, blonde_sh, 1.0)

        # 7. Resolute Noble Face
        hc = (0, -196 + bob)
        b.ellipse(hc[0], hc[1], 18.0, 21.5, skin, skin_sh, 0.8)
        self._face(hc, skin, skin_sh, eye_col, eye_hi)

        # 8. Blonde Front Bangs & Crown
        b.poly([(-16, -214 + bob), (0, -220 + bob), (16, -214 + bob), (10, -198 + bob), (0, -204 + bob), (-10, -198 + bob)], blonde, blonde_sh, 0.9)
        b.path([(-8, -216 + bob), (-4, -200 + bob)], blonde_hi, 1.2)
        b.path([(8, -216 + bob), (4, -200 + bob)], blonde_hi, 1.2)
        # Holy golden circlet / headband
        b.path([(-15, -207 + bob), (0, -211 + bob), (15, -207 + bob)], gold_trim, 2.2)
        b.circle(0, -211 + bob, 2.5, holy_blue, gold_dk, 0.8)

    def _paint_rogue(self) -> None:
        b, t = self.b, self.t
        bob = math.sin(t * 2.7 + self.ph) * 2.0
        sway = math.sin(t * 1.9 + self.ph) * 4.0
        # Skin palette: accent tints the coat, trim tints blade edges
        coat_dk = mix((26, 31, 43), self.accent_col, 0.18)
        coat_edge = mix((83, 187, 144), self.trim_col, 0.32)
        blade_col = mix((168, 255, 193), self.trim_col, 0.28)
        eye_col = mix((126, 255, 178), self.accent_col, 0.22)
        b.ellipse(0,-1,40,7,(0,0,0,90))
        # Asymmetrical hood and split coat, slim silhouette with paired knives.
        b.poly([(-21,-153+bob),(-39,-116),( -32,-64),(-51,-15),(-23,-25),(0,-52),(22,-23),(49,-8),(36,-70),(42,-119),(22,-153+bob)], coat_dk, coat_edge, 1.2)
        b.poly([(-19,-146+bob),(0,-157+bob),(22,-145+bob),(17,-108),(-17,-107)], mix(coat_dk,(30,48,46),0.5), mix(coat_edge,(97,211,160),0.5), 1.0)
        b.poly([(-25,-167+bob),( -19,-214+bob),(2,-230+bob),(23,-212+bob),(24,-181+bob),(12,-202+bob),(-10,-205+bob)], (20,25,37), mix((71,152,125),self.accent_col,0.22), 1.4)
        b.ellipse(1,-194+bob,17,21,(210,165,145),(39,35,44),0.8)
        b.poly([(-18,-204+bob),(0,-218+bob),(19,-204+bob),(12,-198+bob),(-10,-198+bob)], (20,24,35))
        # neon eye slits, belt and daggers.
        b.path([(-9,-190+bob),(-3,-190+bob)], eye_col, 2.2)
        b.path([(5,-190+bob),(11,-190+bob)], eye_col, 2.2)
        b.path([(-16,-103),(16,-105)], mix((204,183,104),self.trim_col,0.25), 3.0)
        b.path([(25,-86),(42,-61),(62,-29)], blade_col, 4)
        b.path([(62,-29),(58,-37),(52,-34)], (214,240,230), 1.0)
        b.path([(-24+sway,-88),(-40+sway,-59),(-60+sway,-36)], blade_col, 4)
        b.path([(-60+sway,-36),(-53+sway,-41),(-53+sway,-34)], (214,240,230), 1.0)
        for x,y in ((-22,-132),(18,-130),(0,-118)):
            b.circle(x,y,2.8,mix((95,226,156),self.accent_col,0.20))
        self._face((1,-194+bob),(224,177,153),(161,113,100),(79,190,126),(180,255,195))

    def _paint_kitsune(self) -> None:
        """Kitsune spirit dancer — anime fox maiden with flowing amber hair, grand fluffy tail,

        dusty-rose off-shoulder kimono, crimson obi, white slip, and glossy lace-up boots.
        Matches the authored character reference design.
        """
        b, t = self.b, self.t
        bob = math.sin(t * 2.2 + self.ph) * 1.6
        sway = math.sin(t * 1.5 + self.ph) * 4.0
        awakened = bool(getattr(self.ch, "awakened", False))

        # Color palette
        amber_dk = (168, 76, 32)
        amber_mid = (224, 122, 52)
        amber_lt = (252, 168, 92)
        tail_cream = (252, 238, 214)

        skin = (252, 234, 222)
        skin_sh = (226, 190, 172)
        eye_col = (214, 76, 36)
        eye_hi = (255, 185, 110)

        mauve = mix((174, 120, 146), self.accent_col, 0.28)
        mauve_dk = mix((132, 84, 108), self.accent_col, 0.28)
        mauve_lt = mix((196, 142, 168), self.accent_col, 0.28)

        slip_wh = (248, 246, 252)
        slip_sh = (218, 214, 226)

        red_obi = mix((164, 34, 46), self.trim_col, 0.32)
        red_dk = mix((118, 20, 30), self.trim_col, 0.32)
        red_lt = mix((212, 54, 68), self.trim_col, 0.32)

        boot_col = (28, 20, 24)
        boot_hi = (68, 48, 58)
        boot_sole = (20, 14, 18)

        # Ground shadow
        b.ellipse(0, -1, 46, 8, (0, 0, 0, 95))

        # ------------------------------------------------------------------
        # 1. Grand Fluffy Fox Tail (billowing behind and curling upward on left)
        # ------------------------------------------------------------------
        t_tip = math.sin(t * 1.4 + self.ph) * 6.5
        tail_outer = [
            (-12, -80),
            (-32, -86),
            (-56, -104),
            (-74, -134),
            (-82 + t_tip * 0.4, -168),
            (-76 + t_tip * 0.7, -204),
            (-52 + t_tip, -232),
            (-26 + t_tip, -222),
            (-18 + t_tip * 0.6, -196),
            (-28, -168),
            (-44, -142),
            (-36, -116),
            (-18, -94),
            (-8, -82),
        ]
        b.poly(tail_outer, amber_dk, amber_mid, 1.2)
        # Inner warm amber body of the tail
        tail_mid_pts = [
            (-24, -94),
            (-46, -114),
            (-62, -140),
            (-68 + t_tip * 0.5, -174),
            (-62 + t_tip * 0.8, -206),
            (-44 + t_tip, -224),
            (-28 + t_tip, -212),
            (-24 + t_tip * 0.6, -192),
            (-34, -164),
            (-46, -138),
            (-30, -110),
        ]
        b.poly(tail_mid_pts, amber_mid, amber_lt, 1.0)
        # Cream / ivory fluffy plume at tail apex
        tail_cream_pts = [
            (-60 + t_tip * 0.6, -188),
            (-52 + t_tip, -226),
            (-32 + t_tip, -218),
            (-22 + t_tip * 0.8, -196),
            (-30 + t_tip * 0.5, -182),
            (-42 + t_tip * 0.4, -198),
        ]
        b.poly(tail_cream_pts, tail_cream, (255, 250, 240), 1.0)
        # Fluff texture feather strokes
        b.path([(-56, -132), (-48, -156), (-54 + t_tip * 0.5, -186)], amber_lt, 2.0)
        b.path([(-68 + t_tip * 0.4, -165), (-56 + t_tip * 0.7, -202)], tail_cream, 1.8)

        # ------------------------------------------------------------------
        # 2. Back Hair (flowing warm amber hair behind shoulders)
        # ------------------------------------------------------------------
        # Left locks flowing down behind kimono
        b.poly([
            (-16, -190 + bob), (-24, -165 + bob), (-30, -130),
            (-36, -95 + sway * 0.4), (-26, -95), (-18, -135), (-12, -175 + bob)
        ], amber_dk, amber_mid, 0.8)
        # Right locks trailing behind
        b.poly([
            (14, -190 + bob), (22, -165 + bob), (32, -125),
            (42, -85 - sway * 0.4), (32, -85), (20, -130), (12, -175 + bob)
        ], amber_dk, amber_mid, 0.8)

        # ------------------------------------------------------------------
        # 3. Bare Thighs & Slender Legs
        # ------------------------------------------------------------------
        # Left upper leg (bare porcelain thigh above boot)
        b.poly([(-14, -86), (-5, -86), (-5, -50), (-14, -50)], skin, skin_sh, 0.7)
        # Right upper leg (bare porcelain thigh above boot)
        b.poly([(5, -86), (14, -86), (14, -50), (5, -50)], skin, skin_sh, 0.7)

        # ------------------------------------------------------------------
        # 4. Glossy Thigh-High Lace-Up Leather Boots
        # ------------------------------------------------------------------
        # Left boot (shaft, calf, ankle, heeled foot)
        left_boot = [
            (-15, -52), (-4, -50), (-5, -30), (-7, -14),
            (-12, -2), (-4, -2), (-4, -8), (-9, -15), (-7, -30), (-14, -48)
        ]
        b.poly(left_boot, boot_col, boot_hi, 1.0)
        # Left stiletto heel
        b.poly([(-13, -8), (-11, -8), (-11, 0), (-13, 0)], boot_sole)
        # Left boot gloss shine
        b.path([(-9, -46), (-8, -32), (-9, -18)], boot_hi, 1.4)
        # Left front criss-cross laces
        for ly in (-44, -36, -28, -20):
            b.path([(-11, ly), (-7, ly + 4)], (55, 40, 48), 1.0)
            b.path([(-7, ly), (-11, ly + 4)], (55, 40, 48), 1.0)
            b.circle(-11, ly, 0.8, (120, 95, 105))
            b.circle(-7, ly, 0.8, (120, 95, 105))

        # Right boot
        right_boot = [
            (4, -50), (15, -52), (14, -48), (11, -30), (10, -14),
            (14, -2), (6, -2), (7, -8), (6, -15), (5, -30)
        ]
        b.poly(right_boot, boot_col, boot_hi, 1.0)
        # Right stiletto heel
        b.poly([(6, -8), (8, -8), (8, 0), (6, 0)], boot_sole)
        # Right boot gloss shine
        b.path([(9, -46), (10, -32), (9, -18)], boot_hi, 1.4)
        # Right front criss-cross laces
        for ry in (-44, -36, -28, -20):
            b.path([(7, ry), (11, ry + 4)], (55, 40, 48), 1.0)
            b.path([(11, ry), (7, ry + 4)], (55, 40, 48), 1.0)
            b.circle(7, ry, 0.8, (120, 95, 105))
            b.circle(11, ry, 0.8, (120, 95, 105))

        # ------------------------------------------------------------------
        # 5. White Slip / Camisole Top (underneath open kimono)
        # ------------------------------------------------------------------
        # Torso camisole bodice
        b.poly([
            (-12, -152 + bob), (-4, -147 + bob), (0, -149 + bob),
            (4, -147 + bob), (12, -152 + bob), (10, -112), (-10, -112)
        ], slip_wh, slip_sh, 0.8)
        # Camisole thin shoulder straps
        b.path([(-9, -164 + bob), (-7, -151 + bob)], slip_wh, 1.2)
        b.path([(9, -164 + bob), (7, -151 + bob)], slip_wh, 1.2)
        # Exposed porcelain collarbone & neck
        b.poly([(-8, -172 + bob), (0, -176 + bob), (8, -172 + bob), (7, -153 + bob), (-7, -153 + bob)], skin, skin_sh, 0.6)
        # Delicate neck pouch / amulet on red cord
        b.path([(-6, -162 + bob), (0, -145 + bob), (6, -162 + bob)], red_obi, 1.2)
        b.poly([(-3, -145 + bob), (3, -145 + bob), (2.5, -137 + bob), (-2.5, -137 + bob)], red_dk, red_lt, 0.8)
        b.circle(0, -145 + bob, 1.5, amber_lt)

        # ------------------------------------------------------------------
        # 6. Dusty Rose / Mauve Kimono (Off-shoulder draped robe & voluminous sleeves)
        # ------------------------------------------------------------------
        # Off-shoulder draping neckline slipping down upper arms
        b.poly([
            (-22, -146 + bob), (-14, -140 + bob), (-10, -148 + bob), (-18, -155 + bob)
        ], mauve, mauve_dk, 0.9)
        b.poly([
            (22, -146 + bob), (14, -140 + bob), (10, -148 + bob), (18, -155 + bob)
        ], mauve, mauve_dk, 0.9)

        # Left voluminous draping sleeve
        left_sleeve = [
            (-18, -148 + bob), (-28, -135), (-44, -115),
            (-48, -82), (-34, -74), (-26, -96), (-18, -116)
        ]
        b.poly(left_sleeve, mauve, mauve_dk, 1.1)
        # Left sleeve inner fold & pattern line
        b.path([(-26, -132), (-40, -112), (-42, -86)], mauve_dk, 1.4)
        b.path([(-22, -140), (-34, -100)], mauve_lt, 1.0)

        # Right voluminous draping sleeve
        right_sleeve = [
            (18, -148 + bob), (28, -135), (42, -115),
            (46, -80), (32, -72), (24, -94), (18, -116)
        ]
        b.poly(right_sleeve, mauve, mauve_dk, 1.1)
        b.path([(26, -132), (38, -112), (40, -84)], mauve_dk, 1.4)
        b.path([(22, -140), (32, -98)], mauve_lt, 1.0)

        # Lower kimono skirt loosely parted around hips
        left_skirt = [(-11, -110), (-24, -92), (-28, -66), (-16, -60), (-10, -82)]
        b.poly(left_skirt, mauve, mauve_dk, 1.0)
        right_skirt = [(11, -110), (22, -92), (26, -64), (16, -58), (10, -82)]
        b.poly(right_skirt, mauve, mauve_dk, 1.0)
        # Delicate hands emerging from sleeves
        self._hand((-26, -92), 1.2, skin, skin_sh, 0.85)
        self._hand((24, -90), -1.2, skin, skin_sh, 0.85)

        # ------------------------------------------------------------------
        # 7. Scarlet Obi Sash with Knot & Hanging Braided Tassel
        # ------------------------------------------------------------------
        # Wide red obi waistband
        b.poly([(-12, -112), (12, -112), (12, -98), (-12, -98)], red_obi, red_dk, 1.0)
        # Decorative obi knot bow
        b.poly([(4, -108), (14, -112), (18, -102), (10, -96)], red_lt, red_dk, 0.8)
        b.poly([(4, -104), (12, -102), (8, -94)], red_obi)
        # Long dangling braided tassel cord
        b.path([(10, -96), (14, -80), (12, -64)], red_obi, 2.4)
        b.path([(10, -96), (14, -80), (12, -64)], red_lt, 1.0)
        # Tassel end fluff
        b.poly([(9, -64), (15, -64), (14, -56), (10, -56)], red_dk, red_lt, 0.7)

        # ------------------------------------------------------------------
        # 8. Head & Expressive Anime Face
        # ------------------------------------------------------------------
        hc = (0, -194 + bob)
        self._face(hc, skin, skin_sh, eye_col, eye_hi)

        # ------------------------------------------------------------------
        # 9. Amber Fox Ears (with fluffy ivory inner fur tufts)
        # ------------------------------------------------------------------
        # Left fox ear
        b.poly([
            (-14, -204 + bob), (-28, -242 + bob), (-6, -222 + bob), (-2, -200 + bob)
        ], amber_dk, amber_mid, 1.1)
        # Left ear cream inner fluff
        b.poly([
            (-14, -208 + bob), (-22, -232 + bob), (-8, -218 + bob)
        ], tail_cream, (245, 210, 195), 0.7)
        # Soft inner pink shading
        b.poly([(-12, -210 + bob), (-17, -225 + bob), (-9, -216 + bob)], (235, 175, 170))

        # Right fox ear
        b.poly([
            (6, -200 + bob), (10, -222 + bob), (28, -242 + bob), (16, -204 + bob)
        ], amber_dk, amber_mid, 1.1)
        # Right ear cream inner fluff
        b.poly([
            (10, -218 + bob), (22, -232 + bob), (14, -208 + bob)
        ], tail_cream, (245, 210, 195), 0.7)
        b.poly([(11, -216 + bob), (17, -225 + bob), (13, -210 + bob)], (235, 175, 170))

        # ------------------------------------------------------------------
        # 10. Front Amber Hair, Bangs & Wisps
        # ------------------------------------------------------------------
        # Crown and hair volume
        b.poly([
            (-19, -203 + bob), (-15, -218 + bob), (0, -228 + bob),
            (15, -218 + bob), (19, -203 + bob), (10, -210 + bob), (-10, -210 + bob)
        ], amber_dk, amber_mid, 0.9)
        # Straight-cut anime bangs framing forehead
        b.poly([
            (-14, -205 + bob), (-10, -191 + bob), (-5, -201 + bob),
            (0, -190 + bob), (5, -201 + bob), (10, -191 + bob), (14, -205 + bob)
        ], amber_mid, amber_dk, 0.6)
        # Long side strands framing face
        b.path([(-16, -202 + bob), (-18, -178 + bob), (-14, -162 + bob)], amber_mid, 2.2)
        b.path([(-16, -202 + bob), (-18, -178 + bob), (-14, -162 + bob)], amber_lt, 1.0)
        b.path([(16, -202 + bob), (18, -178 + bob), (14, -162 + bob)], amber_mid, 2.2)
        b.path([(16, -202 + bob), (18, -178 + bob), (14, -162 + bob)], amber_lt, 1.0)

        # ------------------------------------------------------------------
        # 11. Foxfire Aura & Embers (Active effects)
        # ------------------------------------------------------------------
        if getattr(self.ch, "decoy_turns", 0):
            b.glow(0, -116, 36, (116, 204, 255), 0.35)
        if awakened:
            for i in range(3):
                a = t * 1.1 + i * math.tau / 3
                b.glow(math.cos(a) * 34, -160 + math.sin(a) * 16, 8.0, amber_lt, 0.55)
        else:
            # Ambient gentle spirit ember
            ember_a = t * 0.9 + self.ph
            b.glow(math.sin(ember_a) * 22, -140 + math.cos(ember_a) * 12, 4.0, amber_lt, 0.28)

    # ---- shared body parts ----------------------------------------------------------------------
    def _paint_vampire(self) -> None:
        """A precise night duelist with a high collar, wine-red coat and floating blood sigils."""
        b, t = self.b, self.t
        bob = math.sin(t * 1.7 + self.ph) * 1.4
        black = (19, 16, 29)
        wine = mix((67, 18, 40), self.accent_col, 0.24)
        crimson = mix((205, 43, 80), self.trim_col, 0.30)
        silver = mix((208, 202, 220), self.trim_col, 0.15)
        b.ellipse(0, -1, 43, 7, (0, 0, 0, 95))
        # Coat splits into sharp tails rather than a generic robe silhouette.
        b.poly([(-19,-149+bob),(-36,-118),(-42,-47),(-57,2),(-22,-12),(-4,-62),(0,-85),(9,-53),(31,-8),(54,2),(38,-57),(34,-119),(20,-149+bob)], wine, crimson, 1.4)
        b.poly([(-20,-149+bob),(-30,-169+bob),(-15,-163+bob),(0,-177+bob),(16,-163+bob),(30,-169+bob),(20,-149+bob)], black, (157,70,96), 1.2)
        b.poly([(-17,-147),(0,-161),(18,-147),(23,-108),(8,-76),(0,-94),(-9,-75),(-22,-107)], black, (130,51,83), 1.1)
        b.ellipse(0,-192+bob,19,23,(221,180,166),(63,31,44),1.0)
        b.poly([(-22,-200+bob),(-18,-216+bob),(0,-228+bob),(19,-215+bob),(23,-196+bob),(9,-207+bob),(-9,-206+bob),(-16,-197+bob)], black, crimson, 1.3)
        b.path([(-10,-190+bob),(-4,-191+bob)], (255,87,123), 2.1)
        b.path([(5,-191+bob),(11,-190+bob)], (255,87,123), 2.1)
        # Blood brooch, rapier, and orbiting seal fragments.
        b.poly([(-10,-122),(0,-131),(10,-122),(7,-106),(0,-100),(-7,-106)], wine, (249,166,183), 1.0)
        b.path([(0,-122),(0,-105)], (255,172,185), 1.1)
        b.path([(25,-93),(42,-67),(64,-22)], silver, 4.2)
        b.path([(25,-93),(42,-67),(64,-22)], crimson, 1.1)
        for j in range(3):
            a = t * 0.8 + j * math.tau / 3
            px, py = math.cos(a) * 38, -117 + math.sin(a) * 25
            b.poly([(px,py-5),(px+3,py),(px,py+5),(px-3,py)], (130,28,58), crimson, 0.7)
            self.light(px, py, 10, crimson, 2)
        if self.ch.blood >= 65 or self.ch.awakened:
            self.light(0,-118,34,crimson,3)
        if getattr(self.ch, "decoy_turns", 0):
            b.ellipse(0,-110,47,63,(111,64,135,36),(180,100,224),1.0)

    def _paint_dragonkin(self) -> None:
        """White-haired Horned Shrine Maiden / Dragon Warrior.
        Matches Image 3 reference: pure white hair, crimson/gold curved dragon horns,
        flowing shrine-maiden robes, pleated red hakama, golden draconic slit eyes,
        sinuous scaled tail, and floating furnace embers.
        """
        b, t = self.b, self.t
        bob = math.sin(t * 1.6 + self.ph) * 1.2
        sway = math.sin(t * 1.3 + self.ph) * 3.5
        heat = max(0, min(100, int(getattr(self.ch, "heat", 25))))

        # Ground shadow
        b.ellipse(0, -1, 52, 8, (0, 0, 0, 95))

        # Color palette
        miko_red = mix((178, 28, 38), self.accent_col, 0.35)
        miko_red_dk = mix((118, 16, 24), self.trim_col, 0.35)
        miko_red_lt = (218, 52, 64)

        white_robe = (248, 248, 254)
        white_sh = (212, 214, 226)

        gold_cord = (245, 205, 85)
        gold_dk = (175, 130, 40)

        skin = (252, 235, 226)
        skin_sh = (226, 192, 178)
        eye_col = (245, 175, 35)
        eye_hi = (255, 240, 140)

        hair_col = (248, 248, 255)
        hair_sh = (195, 200, 218)
        hair_hi = (255, 255, 255)

        horn_dk = (32, 24, 28)
        horn_red = (195, 35, 45)

        # 1. Sinuous Dragon Tail (curling behind on left)
        t_sw = math.sin(t * 1.2 + self.ph) * 7.0
        tail_segs = [
            (14, -50),
            (36 + t_sw * 0.3, -42),
            (58 + t_sw * 0.6, -58),
            (74 + t_sw * 0.9, -84),
            (76 + t_sw * 1.2, -114),
            (62 + t_sw * 1.4, -138),
        ]
        for j in range(len(tail_segs) - 1):
            w = 15 - j * 2.2
            b.path([tail_segs[j], tail_segs[j+1]], horn_dk, w)
            b.path([tail_segs[j], tail_segs[j+1]], miko_red, max(1.5, w * 0.5))
            b.circle(tail_segs[j+1][0] - 2, tail_segs[j+1][1], 2.2, gold_cord)

        # 2. Flowing Pleated Red Hakama Pants / Skirt
        hakama_pts = [
            (-18, -108 + bob),
            (18, -108 + bob),
            (32 + sway * 0.5, -12),
            (14 + sway * 0.3, -6),
            (0, -18),
            (-14 + sway * 0.3, -6),
            (-32 + sway * 0.5, -12),
        ]
        b.poly(hakama_pts, miko_red, miko_red_dk, 1.4)
        for fx in (-14, -7, 0, 7, 14):
            b.line((fx, -105 + bob), (fx * 1.7 + sway * 0.4, -12), miko_red_dk, 1.5)
            b.line((fx + 1, -105 + bob), (fx * 1.7 + 1 + sway * 0.4, -12), miko_red_lt, 0.8)
        for s in (-1, 1):
            zx = s * 12
            b.poly([(zx - 5, -12), (zx + 5, -12), (zx + s * 4, 1), (zx - s * 2, 1)], white_robe, (180, 150, 110), 1.0)
            b.line((zx - 4, 0), (zx + 4, 0), (195, 45, 45), 1.5)

        # 3. Ceremonial Shimenawa Obi (Black and Gold rope belt)
        b.poly([(-19, -112 + bob), (19, -112 + bob), (19, -103 + bob), (-19, -103 + bob)], horn_dk, gold_dk, 1.0)
        b.path([(-18, -107 + bob), (0, -105 + bob), (18, -107 + bob)], gold_cord, 2.0)
        b.poly([(-4, -105 + bob), (4, -105 + bob), (6, -72), (-6, -72)], white_robe, miko_red, 1.0)
        b.circle(0, -103 + bob, 3.5, gold_cord, gold_dk, 0.8)

        # 4. White Miko Kimono Wrap & Flowing Wide Sleeves
        b.poly([(-21, -156 + bob), (21, -156 + bob), (19, -112 + bob), (-19, -112 + bob)], white_robe, white_sh, 1.2)
        b.line((-16, -156 + bob), (6, -122 + bob), miko_red, 2.5)
        b.line((16, -156 + bob), (-6, -122 + bob), miko_red, 2.5)
        for s in (-1, 1):
            sx = s * 22
            sy = -152 + bob
            sleeve = [
                (sx, sy),
                (sx + s * 22 + sway * 0.6, sy + 18),
                (sx + s * 28 + sway * 0.8, sy + 62),
                (sx + s * 10 + sway * 0.4, sy + 74),
                (sx - s * 2, sy + 38),
            ]
            b.poly(sleeve, white_robe, miko_red, 1.4)
            b.poly([(sx + s * 12 + sway * 0.4, sy + 58), (sx + s * 26 + sway * 0.8, sy + 52), (sx + s * 24 + sway * 0.7, sy + 68), (sx + s * 10 + sway * 0.4, sy + 72)], miko_red, gold_cord, 1.0)
            self._hand((sx + s * 6 + sway * 0.2, sy + 34), s * 0.5, skin, skin_sh, 0.9)

        # 5. Silky White Long Hair Back Layers
        for side in (-1, 1):
            h_back = [
                (side * 8, -196 + bob),
                (side * 24, -180 + bob),
                (side * 30 + sway * 0.5, -135 + bob),
                (side * 22 + sway * 0.8, -90),
                (side * 12 + sway * 0.6, -115),
            ]
            b.poly(h_back, hair_col, hair_sh, 1.0)

        # 6. Beautiful Draconic Face
        hc = (0, -194 + bob)
        b.ellipse(hc[0], hc[1], 17.0, 20.5, skin, skin_sh, 0.8)
        self._face(hc, skin, skin_sh, eye_col, eye_hi)

        # 7. Swept-Back Crimson Dragon Horns
        for s in (-1, 1):
            horn = [
                (s * 12, -206 + bob),
                (s * 22, -218 + bob),
                (s * 34, -238 + bob),
                (s * 42, -256 + bob),
                (s * 36, -252 + bob),
                (s * 26, -230 + bob),
                (s * 16, -210 + bob),
            ]
            b.poly(horn, horn_dk, horn_red, 1.3)
            b.path([(s * 22, -220 + bob), (s * 26, -228 + bob)], gold_cord, 2.0)
            b.path([(s * 30, -236 + bob), (s * 35, -244 + bob)], gold_cord, 1.8)

        # 8. White Front Bangs and Hair Ribbons
        b.poly([(-15, -212 + bob), (0, -218 + bob), (15, -212 + bob), (9, -198 + bob), (0, -204 + bob), (-9, -198 + bob)], hair_col, hair_sh, 0.8)
        b.path([(-7, -214 + bob), (-3, -199 + bob)], hair_hi, 1.1)
        b.path([(7, -214 + bob), (3, -199 + bob)], hair_hi, 1.1)
        for s in (-1, 1):
            b.poly([(s * 14, -198 + bob), (s * 19, -194 + bob), (s * 18, -178 + bob), (s * 13, -182 + bob)], miko_red, gold_cord, 0.8)

        # 9. Furnace Heat Embers
        num_embers = 3 if heat < 50 else (6 if heat < 80 else 10)
        for k in range(num_embers):
            ea = t * 1.5 + k * (math.tau / num_embers)
            er = 28 + (k % 3) * 14
            ex = math.cos(ea) * er
            ey = -120 + math.sin(ea * 1.3) * 35
            b.circle(ex, ey, 2.2, (255, 180, 50), (255, 230, 110), 0.6)
            b.glow(ex, ey, 10, (255, 120, 30), 80)

    def _face(self, hc: Vec, skin: Color, skin_sh: Color, eye: Color, eye_hi: Color, strain: float = 0.0) -> None:
        b, t = self.b, self.t
        x, y = hc
        blink = ((t + self.ph * 1.7) % 4.3) < 0.14
        face = [(-15, -6), (-16, 2), (-13, 11), (-6, 17), (0, 19.5), (6, 17), (13, 11), (16, 2), (15, -6), (11, -14), (0, -17), (-11, -14)]
        b.poly([(x + px, y + py) for px, py in face], skin, skin_sh, 0.7)
        b.poly([(x - 13, y + 11), (x - 6, y + 17), (x, y + 19.5), (x + 6, y + 17), (x + 13, y + 11), (x + 6, y + 13),
                (x, y + 14.5), (x - 6, y + 13)], with_alpha(skin_sh, 150))
        for s in (-1, 1):
            ex, ey = x + s * 7.4, y + 3.2
            if not blink:
                b.ellipse(ex, ey, 4.9, 5.6, (250, 246, 252), (120, 100, 140), 0.5)
                b.ellipse(ex + s * 0.2, ey + 0.5, 3.7, 5.0, eye)
                b.ellipse(ex + s * 0.2, ey - 1.6, 3.7, 2.9, shade(eye, 0.55))
                b.ellipse(ex + s * 0.2, ey + 0.8, 1.5, 2.4, (22, 10, 34))
                b.circle(ex - 1.2, ey - 1.9, 1.25, WHITE)
                b.circle(ex + 1.2, ey + 2.0, 0.7, eye_hi)
                b.path(ellipse_pts(ex, ey, 5.3, 6.0, n=8, a0=math.pi * 1.02, a1=math.pi * 1.98), LASH, 1.6)
                b.path([(ex + s * 5.0, ey - 1.8), (ex + s * 7.6, ey - 3.8)], LASH, 1.3)
            else:
                b.path([(ex - 4.8, ey + 0.4), (ex, ey + 1.8), (ex + 4.8, ey + 0.4)], LASH, 1.5)
            b.path([(ex - s * 4.2, ey - 8.6 + strain * 0.8), (ex, ey - 9.8), (ex + s * 4.2, ey - 8.8)], mix(LASH, skin, 0.35), 1.0)
            b.ellipse(ex + s * 0.6, ey + 7.0, 3.8, 1.9, (255, 140, 168, 80))
        b.path([(x + 0.4, y + 8.6), (x - 0.1, y + 10.2)], mix(skin_sh, LASH, 0.35), 0.9)
        my = y + 13.6
        b.path([(x - 2.8, my + strain * 0.9), (x, my + 0.6 - strain * 0.6), (x + 2.8, my + strain * 0.9)], (176, 92, 116), 1.0)

    def _hand(self, p: Vec, ang: float, skin: Color, skin_sh: Color, s: float = 1.0) -> None:
        b = self.b
        b.ellipse(p[0], p[1], 3.3 * s, 4.2 * s, skin, skin_sh, 0.5)
        ca, sa = math.cos(ang), math.sin(ang)
        for i in (-1, 0, 1):
            ox, oy = -sa * i * 1.7 * s, ca * i * 1.7 * s
            ln = (6.0 - abs(i) * 0.8) * s
            b.path([(p[0] + ox + ca * 2.5 * s, p[1] + oy + sa * 2.5 * s), (p[0] + ox + ca * ln, p[1] + oy + sa * ln)], skin, 1.5 * s)

    def _limb(self, a: Vec, el: Vec, wr: Vec, w0: float, w1: float, skin: Color, skin_sh: Color) -> list[Vec]:
        path = quad_path(a, el, wr, 12)
        self.b.poly(ribbon(path, taper(12, w0, w1, 0.5)), skin, skin_sh, 0.6)
        return path

    def _bandage(self, path: Sequence[Vec], width: float, spacing: float, tail: bool = True, stain: bool = True) -> None:
        b = self.b
        samples = sample_path(path, spacing)
        for i, (x, y, ang) in enumerate(samples):
            ca, sa = math.cos(ang), math.sin(ang)
            nx, ny = -sa, ca
            sp = spacing * 0.62
            pts = [(x + nx * width - ca * sp * 0.9, y + ny * width - sa * sp * 0.9),
                   (x + nx * width + ca * sp * 0.6, y + ny * width + sa * sp * 0.6),
                   (x - nx * width + ca * sp * 0.9, y - ny * width + sa * sp * 0.9),
                   (x - nx * width - ca * sp * 0.6, y - ny * width - sa * sp * 0.6)]
            b.poly(pts, BANDAGE if i % 2 == 0 else BANDAGE_SH, BANDAGE_EDGE, 0.45)
        if stain and samples:
            x, y, _ = samples[len(samples) // 2]
            b.ellipse(x + 0.8, y, width * 0.5, width * 0.4, (150, 36, 86, 120))
        if tail and samples:
            x, y, _ = samples[-1]
            sway = math.sin(self.t * 2.2 + self.ph + x * 0.1)
            tp = bezier((x, y), (x + 3 + sway * 2, y + 5), (x + 1 + sway * 4, y + 10), (x + 4 + sway * 5, y + 16), 8)
            b.poly(ribbon(tp, taper(8, width * 0.42, width * 0.2)), BANDAGE, BANDAGE_EDGE, 0.4)

    def _locks(self, hc: Vec, specs: Sequence[tuple], col: Color, mid: Color, hi: Color, amp: float = 6.0) -> None:
        """Swaying hair locks. spec = (x0, y0, x1, y1, bulge, half_width, phase) relative to the head centre."""
        b, t = self.b, self.t
        for x0, y0, x1, y1, bw, wd, pk in specs:
            sway = math.sin(t * 1.25 + self.ph + pk)
            sway2 = math.sin(t * 0.8 + self.ph * 1.7 + pk * 1.3)
            p0 = (hc[0] + x0, hc[1] + y0)
            p3 = (hc[0] + x1 + sway * amp, hc[1] + y1)
            p1 = (p0[0] + bw * 0.8 + sway * amp * 0.3, p0[1] + (p3[1] - p0[1]) * 0.33)
            p2 = (p3[0] - bw * 0.6 - sway2 * amp * 0.8, p0[1] + (p3[1] - p0[1]) * 0.72)
            path = bezier(p0, p1, p2, p3, 12)
            b.poly(ribbon(path, taper(12, wd, 0.6, wd * 0.35)), col, shade(col, 0.72), 0.6)
            inner = [(px + wd * 0.22, py) for px, py in path]
            b.poly(ribbon(inner, taper(12, wd * 0.5, 0.3, wd * 0.15)), mid)
            b.path(path[1:9], hi, max(0.5, wd * 0.14))

    # ---- restraint: Gothic Chains ---------------------------------------------------------------
    def _link(self, x: float, y: float, ang: float, length: float, wd: float, face: bool, inten: float) -> None:
        b = self.b
        col = mix(IRON_DK, IRON, 0.45 + 0.55 * inten)
        if face:
            pts = ellipse_pts(x, y, length * 0.56, wd * 0.95, n=14, rot=ang)
            b.path(pts, IRON_DK, wd * 0.80, caps=False)
            b.path(pts, col, wd * 0.46, caps=False)
            b.path(pts[1:6], IRON_HI, wd * 0.16, caps=False)
        else:
            ca, sa = math.cos(ang), math.sin(ang)
            d = length * 0.40
            b.line((x - ca * d, y - sa * d), (x + ca * d, y + sa * d), IRON_DK, wd * 1.05)
            b.line((x - ca * d, y - sa * d), (x + ca * d, y + sa * d), col, wd * 0.62)
            b.line((x - ca * d * 0.6, y - sa * d * 0.6 - wd * 0.2), (x + ca * d * 0.5, y + sa * d * 0.5 - wd * 0.2),
                   mix(col, IRON_HI, 0.7), wd * 0.2)

    def _chain_path(self, path: Sequence[Vec], link: float, wd: float, inten: float, shake: float) -> None:
        for i, (x, y, ang) in enumerate(sample_path(path, link)):
            jx = math.sin(self.t * 47 + i * 1.7) * shake * 1.3
            jy = math.cos(self.t * 53 + i * 1.3) * shake * 1.3
            self._link(x + jx, y + jy, ang, link * 1.18, wd, i % 2 == 0, inten)

    def _cuff(self, p: Vec, ang: float, r: float, inten: float, toward: Optional[Vec] = None) -> None:
        b = self.b
        ca, sa = math.cos(ang), math.sin(ang)
        nx, ny = -sa, ca
        hl = 2.8
        pts = [(p[0] + nx * r - ca * hl, p[1] + ny * r - sa * hl), (p[0] + nx * r + ca * hl, p[1] + ny * r + sa * hl),
               (p[0] - nx * r + ca * hl, p[1] - ny * r + sa * hl), (p[0] - nx * r - ca * hl, p[1] - ny * r - sa * hl)]
        b.poly(pts, IRON_DK, mix(IRON, IRON_HI, inten), 0.9)
        b.line((p[0] + nx * r * 0.8 - ca * 0.6, p[1] + ny * r * 0.8 - sa * 0.6),
               (p[0] - nx * r * 0.8 - ca * 0.6, p[1] - ny * r * 0.8 - sa * 0.6), mix(IRON, IRON_HI, 0.6), 0.6)
        if toward is not None:
            dx, dy = toward[0] - p[0], toward[1] - p[1]
            d = math.hypot(dx, dy) or 1.0
            rp = (p[0] + dx / d * (r + 1.4), p[1] + dy / d * (r + 1.4))
            b.path(ellipse_pts(rp[0], rp[1], 2.5, 2.5, n=14), mix(IRON, IRON_HI, 0.8), 1.0)

    def _floor_bolt(self, p: Vec) -> None:
        b = self.b
        b.ellipse(p[0], p[1], 11, 3.8, IRON_DK, IRON, 0.8)
        b.ellipse(p[0], p[1] - 0.4, 5, 1.8, (16, 12, 26))
        b.path(ellipse_pts(p[0], p[1] - 4.2, 3.6, 3.6, n=14), IRON_HI, 1.0)

    def _padlock(self, c: Vec, inten: float) -> None:
        b = self.b
        b.path(ellipse_pts(c[0], c[1] - 3.2, 3.2, 3.8, n=12, a0=math.pi, a1=math.tau), IRON_HI, 1.4)
        b.poly([(c[0] - 4.6, c[1] - 3), (c[0] + 4.6, c[1] - 3), (c[0] + 5.0, c[1] + 4.6), (c[0] - 5.0, c[1] + 4.6)],
               IRON_DK, mix(IRON, IRON_HI, inten), 0.9)
        b.circle(c[0], c[1] - 0.2, 1.1, (6, 4, 12))
        b.line((c[0], c[1]), (c[0], c[1] + 2.6), (6, 4, 12), 0.9)

    def _chains(self, rig: dict, r: Restraint) -> None:
        inten, shake = self.inten(r), r.shake
        sag = 3.0 + 7.0 * (1.0 - inten)
        # chest bandolier X with padlock
        shl, shr, hip = rig["shL"], rig["shR"], rig["hip"]
        a1, b1 = (shl[0] + 2, shl[1] + 7), (14.0, hip[1] - 6)
        a2, b2 = (shr[0] - 2, shr[1] + 7), (-14.0, hip[1] - 6)
        p1 = bezier(a1, (a1[0] + 8, a1[1] + 14 + sag), (b1[0] - 10, b1[1] - 14 + sag), b1, 12)
        p2 = bezier(a2, (a2[0] - 8, a2[1] + 14 + sag), (b2[0] + 10, b2[1] - 14 + sag), b2, 12)
        self._chain_path(p1, 6.4, 2.2, inten, shake)
        self._chain_path(p2, 6.4, 2.2, inten, shake)
        self._padlock((0.0, (a1[1] + b1[1]) / 2 + sag * 0.3), inten)
        self.hit_pts(RestraintKind.GOTHIC_CHAINS, p1 + p2, 5)
        for s, k in ((-1, "L"), (1, "R")):
            wr, el, an = rig["wr" + k], rig["el" + k], rig["an" + k]
            # wrist chain to a floor bolt
            fa = (s * FLOOR_ANCHOR_X, 7.0)
            end = (fa[0], fa[1] - 4.2)
            c1 = (lerp(wr[0], end[0], 0.33) + s * 2, lerp(wr[1], end[1], 0.33) + sag)
            c2 = (lerp(wr[0], end[0], 0.66) - s * 2, lerp(wr[1], end[1], 0.66) + sag)
            wp = bezier(wr, c1, c2, end, 18)
            self._chain_path(wp, 7.4, 2.5, inten, shake)
            self._floor_bolt(fa)
            self._cuff(wr, math.atan2(wr[1] - el[1], wr[0] - el[0]), 5.0, inten, toward=c1)
            self.hit_pts(RestraintKind.GOTHIC_CHAINS, wp + [(wr[0] - 6, wr[1] - 6), (wr[0] + 6, wr[1] + 6)], 5)
            # ankle chain to a floor bolt
            ab = (s * ANKLE_ANCHOR_X, 7.0)
            aend = (ab[0], ab[1] - 4.2)
            ap = bezier(an, (an[0] + s * 6, an[1] + 12 + sag * 0.5), (aend[0] - s * 8, aend[1] - 8), aend, 12)
            self._chain_path(ap, 6.6, 2.3, inten, shake)
            self._floor_bolt(ab)
            self._cuff(an, math.pi / 2, 4.4, inten, toward=ap[2])
            self.hit_pts(RestraintKind.GOTHIC_CHAINS, ap + [(an[0] - 5, an[1] - 4)], 5)
        if shake > 0.05:
            self.light(0, hip[1] - 20, 70, (200, 200, 255), int(2 + shake * 3))

    # ---- restraint: Shadow Thorn Vines ----------------------------------------------------------
    def _vine(self, path: Sequence[Vec], w0: float, w1: float, phase: float, inten: float, shake: float) -> list[Vec]:
        b, t = self.b, self.t
        n = len(path)
        if n < 4:
            return list(path)
        jit = shake * 1.4
        pts: list[Vec] = []
        for i, (x, y) in enumerate(path):
            pts.append((x + math.sin(t * 1.6 + i * 0.45 + phase) * (0.5 + jit * 0.8),
                        y + math.cos(t * 1.3 + i * 0.5 + phase) * (0.4 + jit * 0.6)))
        widths = [lerp(w0, w1, i / (n - 1)) * (0.86 + 0.14 * math.sin(i * 0.9 + phase)) for i in range(n)]
        b.poly(ribbon(pts, widths), THORN, mix(THORN, THORN_EDGE, 0.5 + 0.5 * inten), 0.8)
        b.path(pts, mix(THORN, (150, 80, 210), 0.45 + 0.35 * inten), 0.55, caps=False)
        wavg = (w0 + w1) / 2
        for k, (x, y, ang) in enumerate(sample_path(pts, 8.2)):
            side = 1 if k % 2 == 0 else -1
            ca, sa = math.cos(ang), math.sin(ang)
            nx, ny = -sa * side, ca * side
            ln = (3.6 + 3.8 * inten) * (0.8 + 0.2 * math.sin(k * 1.7 + phase))
            base1 = (x - ca * 1.7 + nx * wavg * 0.8, y - sa * 1.7 + ny * wavg * 0.8)
            base2 = (x + ca * 1.7 + nx * wavg * 0.8, y + sa * 1.7 + ny * wavg * 0.8)
            tip = (x + nx * (wavg + ln) + ca * 2.6, y + ny * (wavg + ln) + sa * 2.6)
            b.poly([base1, tip, base2], (30, 14, 40), mix(THORN_EDGE, THORN_TIP, 0.35), 0.5)
            if k % 5 == 2:
                pulse = 0.6 + 0.4 * math.sin(t * 3.0 + k)
                b.circle(tip[0], tip[1], 1.3, mix(THORN_EDGE, THORN_TIP, pulse))
                if k % 10 == 2:
                    self.light(tip[0], tip[1], 12, THORN_TIP, 3)
        return pts

    def _vines(self, rig: dict, r: Restraint) -> None:
        inten, shake = self.inten(r), r.shake
        b = self.b
        hipy = rig["hip"][1]
        spines: list[tuple[list[Vec], float, float, float]] = []
        for s, k in ((-1, "L"), (1, "R")):
            root = (s * 22.0, 7.0)
            b.glow(root[0], root[1] - 4, 20, (4, 0, 10), 170)
            leg = catmull([root, (s * 14.0, -3.0), rig["an" + k], rig["kn" + k], (s * 10.0, hipy)], 6)
            spines.append((wrap_path(leg, 5.6, 3.4, self.ph + s), 3.5, 1.5, 0.3 * s))
            arm = catmull([rig["sh" + k], rig["el" + k], rig["wr" + k]], 8)
            spines.append((wrap_path(arm, 4.4, 2.6, s * 1.3 + 1.0), 2.4, 1.1, 1.1 * s))
        torso = catmull([(-12.0, hipy), (10.0, rig["waist"][1] - 6), (-10.0, rig["chest"][1] + 6), (12.0, rig["chest"][1] - 12)], 8)
        spines.append((wrap_path(torso, 2.6, 2.2, 0.4), 2.6, 1.2, 2.2))
        for spine, w0, w1, ph in spines:
            drawn = self._vine(spine, w0, w1, ph + self.ph, inten, shake)
            self.hit_pts(RestraintKind.SHADOW_THORN_VINES, drawn, 5)

    # ---- restraint: Sacred Rune Bindings --------------------------------------------------------
    def _glyph(self, c: Vec, rx: float, ry: float, rot: float, a: float, kind: int, col: Color) -> None:
        b = self.b
        if kind == 0:
            b.line(ep(c, rx, ry, rot, a, 0.82), ep(c, rx, ry, rot, a, 1.0), col, 0.9)
            b.line(ep(c, rx, ry, rot, a, 0.92), ep(c, rx, ry, rot, a + 0.13, 1.02), col, 0.8)
        elif kind == 1:
            b.line(ep(c, rx, ry, rot, a, 0.82), ep(c, rx, ry, rot, a, 1.0), col, 0.9)
            b.line(ep(c, rx, ry, rot, a - 0.08, 0.91), ep(c, rx, ry, rot, a + 0.08, 0.91), col, 0.8)
        else:
            b.path([ep(c, rx, ry, rot, a - 0.09, 1.0), ep(c, rx, ry, rot, a, 0.83), ep(c, rx, ry, rot, a + 0.09, 1.0)], col, 0.8)

    def _seal(self, c: Vec, r: float, squash: float, rot: float, spin: float, n: int, inten: float, hexa: bool = False) -> None:
        b = self.b
        col = mix((74, 40, 128), RUNE, 0.35 + 0.65 * inten)
        hi = mix((120, 80, 190), RUNE_HI, 0.35 + 0.65 * inten)
        ry = r * squash
        b.glow(c[0], c[1], r * 2.0, RUNE, int(60 + 90 * inten))
        b.path(ellipse_pts(c[0], c[1], r, ry, n=36, rot=rot), col, 1.5)
        b.path(ellipse_pts(c[0], c[1], r * 0.8, ry * 0.8, n=36, rot=rot), mix(col, (30, 14, 60), 0.4), 0.8)
        for k in range(n):
            self._glyph(c, r, ry, rot, spin + k * math.tau / n, k % 3, hi)
        if hexa:
            for off in (0.0, math.pi / 3):
                tri = [ep(c, r, ry, rot, spin * 0.7 + off + j * math.tau / 3, 0.76) for j in range(3)]
                b.path(tri + [tri[0]], col, 0.9)
        b.circle(c[0], c[1], max(0.8, r * 0.07), hi)

    def _floor_seal(self) -> None:
        r = self.res[RestraintKind.SACRED_RUNE_BINDINGS]
        inten = self.inten(r)
        rx, ry, c = 96.0, 24.0, (0.0, 5.0)
        spin = self.t * 0.45
        self.b.glow(0, 5, 118, RUNE, int(50 + 70 * inten))
        self.b.path(ellipse_pts(c[0], c[1], rx * 1.04, ry * 1.04, n=48), mix((60, 30, 110), RUNE, 0.35 + 0.65 * inten), 1.8)
        self.b.path(ellipse_pts(c[0], c[1], rx * 0.5, ry * 0.5, n=36), mix((60, 30, 110), RUNE, 0.3 + 0.5 * inten), 1.0)
        self._seal(c, rx, ry / rx, 0.0, spin, 18, inten, hexa=True)
        self.hit(RestraintKind.SACRED_RUNE_BINDINGS, -rx - 4, c[1] - ry - 4, 2 * rx + 8, 2 * ry + 8)

    def _body_seals(self, rig: dict, r: Restraint) -> None:
        inten = self.inten(r)
        spin = self.t * 0.9 * (1.0 + r.shake * 3.0)
        seals: list[tuple[Vec, float, float, float, int]] = []
        for k in ("L", "R"):
            wr, el, an = rig["wr" + k], rig["el" + k], rig["an" + k]
            seals.append((wr, 8.6, 0.36, math.atan2(wr[1] - el[1], wr[0] - el[0]) + math.pi / 2, 7))
            seals.append((an, 8.2, 0.34, 0.0, 7))
        seals.append((rig["chest"], 19.0, 0.26, 0.0, 12))
        seals.append((rig["waist"], 16.0, 0.24, 0.0, 10))
        # energy threads between the wrist seals through the chest seal
        thread = catmull([rig["wrL"], rig["shL"], rig["chest"], rig["shR"], rig["wrR"]], 8)
        for i, (x, y, _) in enumerate(sample_path(thread, 7.0)):
            pulse = 0.5 + 0.5 * math.sin(self.t * 4.0 - i * 0.7)
            self.b.circle(x, y, 0.7 + 0.8 * pulse, mix((80, 44, 140), RUNE_HI, pulse * inten))
        for c, rad, squash, rot, n in seals:
            self._seal(c, rad, squash, rot, spin, n, inten)
            self.hit(RestraintKind.SACRED_RUNE_BINDINGS, c[0] - rad - 2, c[1] - rad - 2, rad * 2 + 4, rad * 2 + 4)
            self.light(c[0], c[1], rad * 3.0, RUNE, 3)

    # ---- restraint: Crown of Thorns -------------------------------------------------------------
    def _crown(self, cx: float, cy: float, rx: float, ry: float, r: Restraint) -> None:
        b, t = self.b, self.t
        inten, shake = self.inten(r), r.shake
        b.glow(cx, cy, rx * 1.3, (150, 50, 200), int(40 + 70 * inten))
        arc = ellipse_pts(cx, cy, rx, ry, n=34, a0=math.pi * 0.04, a1=math.pi * 0.96)
        band_a = [(x, y + math.sin(i * 1.1) * 0.9) for i, (x, y) in enumerate(arc)]
        band_b = [(x, y - math.sin(i * 1.1) * 0.9) for i, (x, y) in enumerate(arc)]
        b.path(band_a, BRIAR_DK, 2.8)
        b.path(band_b, BRIAR, 2.3)
        b.path(band_a[::2], mix(BRIAR, BRIAR_HI, inten), 0.8, caps=False)
        for i in range(1, len(arc) - 1, 2):
            x, y = arc[i]
            a = lerp(math.pi * 0.04, math.pi * 0.96, i / (len(arc) - 1))
            if (i // 2) % 2 == 0:
                d = (math.cos(a) * 0.75, -0.85)
                ln = (4.2 + 4.0 * inten) * (0.85 + 0.15 * math.sin(i))
            else:
                d = (-math.cos(a) * 0.25, 0.95)
                ln = 2.8 + 2.2 * inten
            dn = math.hypot(d[0], d[1]) or 1.0
            ux, uy = d[0] / dn, d[1] / dn
            tip = (x + ux * ln, y + uy * ln)
            b.poly([(x - uy * 1.2, y + ux * 1.2), tip, (x + uy * 1.2, y - ux * 1.2)], BRIAR_DK, mix(BRIAR, BRIAR_HI, 0.5), 0.5)
            b.circle(tip[0], tip[1], 0.6, (190, 130, 100))
            if (i // 2) % 4 == 1:
                pulse = 0.55 + 0.45 * math.sin(t * 3.2 + i)
                b.circle(tip[0], tip[1], 1.1, mix((120, 30, 70), RUNE_RED, pulse))
                drip = 2.5 + 2.2 * (0.5 + 0.5 * math.sin(t * 1.5 + i * 0.9)) + shake * 2.0
                b.line((tip[0], tip[1] + 1.0), (tip[0], tip[1] + 1.0 + drip), (200, 40, 90), 0.8)
                b.circle(tip[0], tip[1] + 1.4 + drip, 0.9, (230, 60, 110))
                self.light(tip[0], tip[1], 11, RUNE_RED, 3)
        self.hit(RestraintKind.CROWN_OF_THORNS, cx - rx - 6, cy - 14, 2 * rx + 12, ry + 28)

    # ---- Fallen Angel ---------------------------------------------------------------------------
    def _angel_rig(self, pulled: bool) -> dict:
        t, ph = self.t, self.ph
        br = math.sin(t * 1.7 + ph)                     # breathing
        sw = math.sin(t * 0.9 + ph * 1.3)               # slow sway
        fl = -15.0 + math.sin(t * 1.25 + ph * 0.7) * 5.0  # floating height (negative = up)
        rig: dict = {"br": br, "sw": sw, "fl": fl}
        rig["hip"] = (0.0, -112.0 + fl)
        rig["waist"] = (0.0, -124.0 + fl)
        rig["chest"] = (0.0, -151.0 + fl - br * 0.8)
        rig["neck"] = (0.0, -174.0 + fl - br * 0.9)
        rig["head"] = (sw * 0.7, -199.0 + fl - br * 1.1)
        for s, k in ((-1, "L"), (1, "R")):
            rig["sh" + k] = (s * 18.0, -168.0 + fl - br * 0.9)
            rig["an" + k] = (s * 8.0, -9.0 + fl)
            rig["kn" + k] = (s * 9.5, -60.0 + fl)
            if pulled:
                tr = math.sin(t * 6.5 + self.ph + s) * 0.7
                rig["el" + k] = (s * 40.0, -150.0 + fl)
                rig["wr" + k] = (s * 66.0 + s * tr, -124.0 + fl + tr)
            else:
                rig["el" + k] = (s * 30.0, -141.0 + fl + br * 0.6)
                rig["wr" + k] = (s * 34.0 + s * sw * 1.2, -107.0 + fl + sw * 0.8)
        return rig

    def _paint_angel(self) -> None:
        res = self.res
        rig = self._angel_rig(RestraintKind.GOTHIC_CHAINS in res)
        hc = rig["head"]
        if RestraintKind.SACRED_RUNE_BINDINGS in res:
            self._floor_seal()
        # Image 5: Dragon/demon tail coiling behind
        self._angel_dragon_tail(rig)
        for s in (-1, 1):
            self._wing(s, rig)
        # Silver-white hair with lilac tint
        a_hair = mix(A_HAIR, (226, 220, 240), 0.75)
        a_mid = mix(A_HAIR_MID, (200, 190, 225), 0.70)
        a_hi = (248, 244, 255)
        self._locks(hc, ANGEL_BACK_LOCKS, a_hair, a_mid, a_hi, amp=6.0)
        self._angel_legs(rig)
        self._angel_skirt(rig)
        self._angel_torso(rig)
        self._angel_arms(rig)
        self._angel_head(rig)
        # Curved dragon horns (Image 5)
        self._angel_horns(hc)
        # Floating soul embers around wings (Image 5)
        for j in range(4):
            ea = self.t * 1.2 + j * math.tau / 4 + self.ph
            ex = math.cos(ea) * 80
            ey = rig["chest"][1] - 38 + math.sin(ea) * 32
            self.b.glow(ex, ey, 5.0, (190, 95, 255), 45)
        vines = res.get(RestraintKind.SHADOW_THORN_VINES)
        if vines is not None:
            self._vines(rig, vines)
        chains = res.get(RestraintKind.GOTHIC_CHAINS)
        if chains is not None:
            self._chains(rig, chains)
        runes = res.get(RestraintKind.SACRED_RUNE_BINDINGS)
        if runes is not None:
            self._body_seals(rig, runes)
        crown = res.get(RestraintKind.CROWN_OF_THORNS)
        if crown is not None:
            self._crown(hc[0], hc[1] - 15.5, 19.5, 4.6, crown)
        self._halo(hc)

    def _angel_horns(self, hc: Vec) -> None:
        """Curved obsidian dragon horns framing the head (Image 5)."""
        b = self.b
        x, y = hc
        for s in (-1, 1):
            base = (x + s * 14.0, y - 6.0)
            mid = (x + s * 26.0, y - 26.0)
            tip = (x + s * 20.0, y - 46.0)
            horn_pts = [base, (base[0] - s * 5, base[1] - 3), mid, tip, (mid[0] + s * 4, mid[1] + 3)]
            b.poly(horn_pts, (22, 16, 32), (90, 48, 125), 0.8)
            b.line((mid[0], mid[1]), (tip[0], tip[1]), (185, 95, 245), 1.0)

    def _angel_dragon_tail(self, rig: dict) -> None:
        """Segmented spiky demon/dragon tail with barbed tip (Image 5)."""
        b, t = self.b, self.t
        hip = (0.0, rig["hip"][1] + 4)
        sway = math.sin(t * 1.6 + self.ph) * 7.0
        pts = quad_path(hip, (-38.0 + sway * 0.4, -48.0), (18.0 + sway, -6.0), 12)
        b.poly(ribbon(pts, taper(12, 5.8, 1.8)), (22, 16, 32), (105, 52, 140), 0.8)
        tip = pts[-1]
        b.poly([(tip[0], tip[1] - 7), (tip[0] + 11, tip[1] + 2), (tip[0] - 2, tip[1] + 7), (tip[0] - 5, tip[1])],
               (28, 18, 42), (185, 88, 230), 0.8)

    def _wing(self, s: int, rig: dict) -> None:
        b, t = self.b, self.t
        flap = math.sin(t * 1.15 + self.ph + (0.45 if s > 0 else 0.0))
        rx0, ry0 = s * 12.0, rig["chest"][1] - 14.0
        b.glow(s * 84, ry0 - 34, 96, (110, 56, 206), 70)
        w_rim = mix(WING_RIM, self.trim_col, 0.28)
        w_mid = mix(WING_MID, self.accent_col, 0.22)
        rows = ((9, 1.0, WING_DK, 0.0), (8, 0.74, w_mid, 0.5), (7, 0.46, WING_LT, 0.25))
        for ri, (count, lenk, col, off) in enumerate(rows):
            if ri == 2:
                self._wing_bone(s, rx0, ry0, flap)
            for i in range(count):
                u = (i + off) / count
                ang = math.radians(lerp(84, -50, u) + flap * 4.0 * (1 - u * 0.4))
                length = 158.0 * lenk * (0.45 + 0.55 * math.sin(math.pi * (u * 0.9 + 0.05)))
                dx, dy = s * math.cos(ang), -math.sin(ang)
                p0 = (rx0, ry0)
                path = bezier(p0, (p0[0] + dx * length * 0.3, p0[1] + dy * length * 0.3 + length * 0.03),
                              (p0[0] + dx * length * 0.7, p0[1] + dy * length * 0.7 + length * 0.12),
                              (p0[0] + dx * length, p0[1] + dy * length + length * 0.15), 10)
                hw = 6.4 * (0.65 + lenk * 0.55)
                widths = [hw * math.sin(math.pi * (0.08 + 0.9 * (j / 10) ** 0.85)) for j in range(11)]
                b.poly(ribbon(path, widths), col, mix(col, w_rim, 0.62), 0.8)
                b.path(path[2:9], mix(col, w_rim, 0.4), 0.6, caps=False)

    def _wing_bone(self, s: int, rx0: float, ry0: float, flap: float) -> None:
        b = self.b
        wr = (s * (108.0 + flap * 3.0), ry0 - 92.0 + flap * 2.0)
        path = quad_path((rx0, ry0), (s * 52.0, ry0 - 70.0), wr, 12)
        b.poly(ribbon(path, taper(12, 5.2, 3.0)), (22, 10, 44), mix(WING_RIM, WING_DK, 0.4), 0.8)
        claw = [(wr[0] - s * 3, wr[1] + 3), (wr[0] + s * 3, wr[1] - 2), (wr[0] + s * 9, wr[1] - 13), (wr[0] + s * 1, wr[1] - 4)]
        b.poly(claw, (210, 190, 240), (120, 90, 170), 0.6)

    def _angel_legs(self, rig: dict) -> None:
        b = self.b
        for s, k in ((-1, "L"), (1, "R")):
            hip = (s * 8.0, rig["hip"][1])
            kn, an = rig["kn" + k], rig["an" + k]
            path = quad_path(hip, (kn[0] + s * 1.5, kn[1]), an, 12)
            b.poly(ribbon(path, taper(12, 5.6, 2.6, 0.8)), CLOTH_DK, CLOTH_EDGE, 0.6)
            b.path(path[2:10], CLOTH_LT, 0.9, caps=False)
            self._bandage(quad_path((kn[0], kn[1] + 4), (kn[0], (kn[1] + an[1]) / 2), (an[0], an[1] - 3), 8), 3.1, 4.2, tail=(s > 0))
            foot = [(an[0] - 2.8, an[1] - 1), (an[0] + 2.8, an[1] - 1), (an[0] + 2.2, an[1] + 10), (an[0] + 0.3, an[1] + 14), (an[0] - 2.0, an[1] + 9)]
            b.poly(foot, A_SKIN, A_SKIN_SH, 0.5)

    def _angel_skirt(self, rig: dict) -> None:
        b, t = self.b, self.t
        fl, wy = rig["fl"], rig["waist"][1]
        hem: list[Vec] = []
        for i in range(13):
            f = i / 12
            hem.append((lerp(34, -34, f), fl - 50 + 9 * abs(math.sin(f * math.pi * 4.5)) + math.sin(t * 2.0 + f * 6 + self.ph) * 1.5))
        poly = [(-12, wy), (12, wy), (21, wy + 24), (29, wy + 50)] + hem + [(-29, wy + 50), (-21, wy + 24)]
        b.poly(poly, CLOTH, CLOTH_EDGE, 0.9)
        for i in range(-4, 5):
            f = i / 4
            b.line((f * 8, wy + 5), (f * 30, fl - 52), CLOTH_DK if i % 2 else CLOTH_LT, 0.9)
        for x0, ln, pk in ((-9.0, 70.0, 0.0), (0.0, 84.0, 1.1), (9.0, 66.0, 2.3)):
            sw = math.sin(t * 1.7 + self.ph + pk)
            p3 = (x0 * 2.2 + sw * 5, wy + 4 + ln)
            path = bezier((x0, wy + 4), (x0 + sw * 2, wy + ln * 0.3), (p3[0] - sw * 3, wy + ln * 0.65), p3, 10)
            b.poly(ribbon(path, taper(10, 3.4, 1.2)), CLOTH_LT, CLOTH_EDGE, 0.6)

    def _angel_torso(self, rig: dict) -> None:
        b = self.b
        ys, cy, wy, hy = rig["shL"][1], rig["chest"][1], rig["waist"][1], rig["hip"][1]
        wch = 17.5 + rig["br"] * 0.5
        pts = [(-6, ys - 2), (-17, ys + 1), (-wch, cy), (-13, wy - 6), (-10.5, wy), (-13.5, hy), (13.5, hy), (10.5, wy),
               (13, wy - 6), (wch, cy), (17, ys + 1), (6, ys - 2), (0, ys + 3)]
        b.poly(pts, CLOTH, CLOTH_EDGE, 0.9)
        b.path([(-4, ys + 4), (-3, cy), (-1, wy)], CLOTH_LT, 1.0, caps=False)
        self._bandage([(-16, ys + 7), (-4, cy + 4), (8, wy - 2), (14, hy - 4)], 4.4, 5.0, tail=False)
        self._bandage([(16, ys + 7), (4, cy + 4), (-8, wy - 2), (-14, hy - 4)], 4.4, 5.0, tail=True)
        self._bandage([(-15.5, cy - 4), (0, cy - 1), (15.5, cy - 4)], 3.6, 4.4, tail=False, stain=False)

    def _angel_arms(self, rig: dict) -> None:
        b = self.b
        for s, k in ((-1, "L"), (1, "R")):
            sh, el, wr = rig["sh" + k], rig["el" + k], rig["wr" + k]
            b.ellipse(sh[0], sh[1] + 1, 5.4, 5.6, A_SKIN, A_SKIN_SH, 0.5)
            path = self._limb(sh, el, wr, 4.6, 2.9, A_SKIN, A_SKIN_SH)
            self._bandage(path[1:6], 4.0, 4.4, tail=False)
            self._bandage(path[6:13], 3.1, 4.0, tail=(s > 0))
            ang = math.atan2(wr[1] - el[1], wr[0] - el[0])
            self._hand((wr[0] + math.cos(ang) * 3.4, wr[1] + math.sin(ang) * 3.4), ang, A_SKIN, A_SKIN_SH)

    def _angel_head(self, rig: dict) -> None:
        b = self.b
        hc = rig["head"]
        x, y = hc
        strain = clamp(len(self.res) / 4.0, 0.0, 1.0)
        b.poly(ribbon([(0.0, rig["neck"][1] + 4), (hc[0] * 0.5, rig["neck"][1] - 6), (hc[0] * 0.8, y + 14)], [3.6, 3.2, 3.0]),
               A_SKIN_SH, A_SKIN_DK, 0.5)
        # Silver-white hair with glowing luminous violet eyes (Image 5)
        a_hair = mix(A_HAIR, (226, 220, 240), 0.75)
        a_mid = mix(A_HAIR_MID, (200, 190, 225), 0.70)
        a_hi = (248, 244, 255)
        b.ellipse(x, y - 4, 18.5, 20.5, a_hair)
        self._face(hc, A_SKIN, A_SKIN_SH, (210, 110, 255), (245, 190, 255), strain)
        b.ellipse(x, y - 12.5, 17.6, 11.2, a_hair, shade(a_hair, 0.7), 0.6)
        self._locks(hc, ANGEL_BANGS, a_hair, a_mid, a_hi, amp=2.0)
        self._locks(hc, ANGEL_SIDE_LOCKS, a_hair, a_mid, a_hi, amp=3.0)
        self._locks(hc, ANGEL_AHOGE, a_hair, a_mid, a_hi, amp=2.0)

    def _halo(self, hc: Vec) -> None:
        b, t = self.b, self.t
        cx, cy = hc[0], hc[1] - 35.0
        pulse = 0.5 + 0.5 * math.sin(t * 2.1 + self.ph)
        rot = 0.08 * math.sin(t * 0.6 + self.ph)
        b.glow(cx, cy, 40, HALO, int(110 + 50 * pulse))
        ring = ellipse_pts(cx, cy, 21.0, 5.8, n=44, rot=rot)
        b.path(ring, mix((90, 40, 150), HALO, 0.7 + 0.3 * pulse), 3.8)
        b.path(ring, HALO, 2.4)
        b.path(ring, mix(HALO, HALO_CORE, 0.8), 1.1)
        for k in range(4):
            px, py = ep((cx, cy), 21.0, 5.8, rot, t * 0.9 + k * math.pi / 2)
            b.circle(px, py, 0.9 + 0.5 * math.sin(t * 3 + k), HALO_CORE)
        self.light(cx, cy, 64, HALO, 5)

    # ---- Witch ----------------------------------------------------------------------------------
    def _witch_rig(self, pulled: bool) -> dict:
        t, ph = self.t, self.ph
        br = math.sin(t * 1.6 + ph)
        sw = math.sin(t * 0.8 + ph * 1.3)
        rig: dict = {"br": br, "sw": sw, "fl": 0.0}
        rig["hip"] = (0.0, -92.0)
        rig["waist"] = (0.0, -101.0)
        rig["chest"] = (0.0, -130.0 - br * 0.7)
        rig["neck"] = (0.0, -158.0 - br * 0.8)
        rig["head"] = (sw * 0.5, -182.0 - br * 0.9)
        for s, k in ((-1, "L"), (1, "R")):
            rig["sh" + k] = (s * 19.0, -150.0 - br * 0.8)
            rig["an" + k] = (s * 9.0, -6.0)
            rig["kn" + k] = (s * 10.0, -50.0)
            if pulled:
                tr = math.sin(t * 6.0 + ph + s) * 0.7
                rig["el" + k] = (s * 40.0, -134.0)
                rig["wr" + k] = (s * 64.0 + s * tr, -110.0 + tr)
            else:
                rig["el" + k] = (s * 33.0, -124.0 + br * 0.5)
                rig["wr" + k] = (-36.0 if s < 0 else 48.0, -97.0 + sw * 0.8)
        return rig

    def _paint_witch(self) -> None:
        """Anime Raccoon-Ear Witch with grand striped fluffy tail and ragged witch hat.
        Matches Image 2 reference: chocolate brown hair, raccoon ears, wide tattered witch hat
        with flower pin, off-the-shoulder grey keyhole sweater dress, striped thigh-high stockings,
        fluffy boot cuffs, and mary-jane shoes with heart buckles.
        """
        res = self.res
        rig = self._witch_rig(RestraintKind.GOTHIC_CHAINS in res)
        hc = rig["head"]
        if RestraintKind.SACRED_RUNE_BINDINGS in res:
            self._floor_seal()
        # 1. Giant fluffy striped raccoon tail billowing behind (Image 2)
        self._witch_raccoon_tail(rig)
        w_hair_br = (66, 46, 40)
        w_hair_sh = (44, 30, 26)
        w_hair_hi = (112, 82, 72)
        self._locks(hc, WITCH_BACK_LOCKS, w_hair_br, w_hair_sh, w_hair_hi, amp=7.0)
        self._witch_dress(rig)
        self._witch_staff(rig)
        self._witch_arms(rig)
        self._witch_head(rig)
        vines = res.get(RestraintKind.SHADOW_THORN_VINES)
        if vines is not None:
            self._vines(rig, vines)
        chains = res.get(RestraintKind.GOTHIC_CHAINS)
        if chains is not None:
            self._chains(rig, chains)
        runes = res.get(RestraintKind.SACRED_RUNE_BINDINGS)
        if runes is not None:
            self._body_seals(rig, runes)
        crown = res.get(RestraintKind.CROWN_OF_THORNS)
        if crown is not None:
            self._crown(hc[0], hc[1] - 26.0, 25.0, 6.0, crown)

    def _witch_raccoon_tail(self, rig: dict) -> None:
        """Grand fluffy striped raccoon tail (Image 2)."""
        b, t = self.b, self.t
        sway = math.sin(t * 1.5 + self.ph) * 8.5
        p0 = (10.0, rig["hip"][1] + 16.0)
        p1 = (44.0, -28.0)
        p2 = (96.0 + sway * 0.6, -82.0)
        p3 = (106.0 + sway, -145.0)
        p4 = (74.0 + sway * 1.2, -202.0)
        p5 = (42.0 + sway * 1.4, -222.0)
        seg1 = bezier(p0, (p0[0] + 15, p0[1] - 10), (p1[0] + 20, p1[1] - 25), p2, 12)
        seg2 = bezier(p2, (p2[0] + 10, p2[1] - 30), (p3[0] - 10, p3[1] - 30), p5, 13)
        spine = seg1 + seg2[1:]
        n_pts = len(spine)
        widths = [10.0 + 36.0 * math.sin(math.pi * (i / (n_pts - 1)) ** 0.8) for i in range(n_pts)]
        # Tail base body (dark grey fur)
        tail_poly = ribbon(spine, widths)
        b.poly(tail_poly, (52, 48, 56), (36, 32, 40), 1.0)
        # Alternating light warm-grey fur bands (Image 2 raccoon stripes)
        band_col = (176, 172, 182)
        for b_idx in (1, 3, 5):
            idx_start = b_idx * 4
            idx_end = min(n_pts - 1, idx_start + 4)
            sub_poly = ribbon(spine[idx_start:idx_end+1], widths[idx_start:idx_end+1])
            b.poly(sub_poly, band_col, (140, 136, 148), 0.8)
        tip = spine[-1]
        b.poly([(tip[0], tip[1] - 8), (tip[0] - 14, tip[1] - 3), (tip[0] - 6, tip[1] + 7), (tip[0] + 9, tip[1] + 2)],
               (44, 40, 48), (32, 28, 36), 0.6)

    def _witch_dress(self, rig: dict) -> None:
        """Off-the-shoulder grey keyhole sweater dress & striped thigh-highs (Image 2)."""
        b, t = self.b, self.t
        wy, sy, cy = rig["waist"][1], rig["shL"][1], rig["chest"][1]
        sw_col = mix((118, 115, 126), self.accent_col, 0.22)
        sw_dk = mix((78, 75, 86), self.accent_col, 0.20)
        sw_lt = mix((152, 148, 160), self.accent_col, 0.24)
        ribbon_col = mix((42, 38, 48), self.trim_col, 0.35)

        # 1. Legs with striped thigh-high stockings (Image 2)
        for s in (-1, 1):
            lx = s * 8.5
            leg_pts = [(lx - 3.5, wy + 20), (lx + 3.5, wy + 20), (lx + 4.0, -10), (lx - 4.0, -10)]
            b.poly(leg_pts, (248, 238, 236))  # bare thigh
            # Striped stockings from wy + 32 down to -8
            stocking_pts = [(lx - 4.0, wy + 32), (lx + 4.0, wy + 32), (lx + 3.5, -4), (lx - 3.5, -4)]
            b.poly(stocking_pts, (42, 38, 46))
            # Alternating light grey stripes on stocking
            for st_y in range(int(wy + 40), -4, 14):
                b.poly([(lx - 4.1, st_y), (lx + 4.1, st_y), (lx + 4.1, st_y + 7), (lx - 4.1, st_y + 7)],
                       (175, 172, 182), (145, 142, 152), 0.5)
            # Fluffy white fur cuffs at ankle (Image 2)
            b.ellipse(lx, -6.0, 7.5, 4.5, (244, 242, 248), (200, 196, 206), 0.6)
            # Mary-Jane shoes with heart buckle
            b.poly([(lx - 3.8, -4), (lx + 3.8, -4), (lx + 4.2, 2), (lx + 0.5, 5), (lx - 3.8, 2)],
                   (28, 24, 32), (18, 14, 22), 0.8)
            b.circle(lx, -1.0, 1.3, (220, 180, 192))  # heart buckle

        # Garter strap on left leg (Image 2)
        b.path([(-12.5, wy + 26), (-5.0, wy + 26)], ribbon_col, 2.0)
        b.circle(-8.5, wy + 26, 1.4, (220, 180, 192))

        # 2. Flared ruffled mini skirt
        skirt_hem_y = wy + 24.0
        skirt_poly = [(-13, wy), (13, wy), (24, skirt_hem_y), (-24, skirt_hem_y)]
        b.poly(skirt_poly, sw_col, sw_dk, 0.9)
        # Ruffle pleats on skirt
        for rx in range(-20, 21, 5):
            b.line((rx * 0.5, wy + 2), (rx, skirt_hem_y), sw_lt, 0.8)
        # Small ribbon bows on skirt corners
        for s in (-1, 1):
            b.circle(s * 20, skirt_hem_y - 2, 2.0, ribbon_col)

        # 3. Off-the-shoulder sweater bodice with keyhole cutout (Image 2)
        bod = [(-7, sy - 2), (-18, sy + 3), (-16, cy), (-12, wy), (12, wy), (16, cy), (18, sy + 3), (7, sy - 2), (0, sy + 4)]
        b.poly(bod, sw_col, sw_dk, 0.9)
        # Keyhole / chest cutout revealing skin
        b.ellipse(0, cy - 2, 5.5, 7.5, (252, 240, 238), (224, 202, 208), 0.7)
        # Sweater ribbing texture
        for rib_x in (-8, -4, 4, 8):
            b.line((rib_x, cy + 8), (rib_x * 0.9, wy), sw_dk, 0.6)

    def _witch_staff(self, rig: dict) -> None:
        b, t = self.b, self.t
        pulled = RestraintKind.GOTHIC_CHAINS in self.res
        base = (76.0 if pulled else 48.0, 4.0)
        hand = rig["wrR"]
        dx, dy = hand[0] - base[0], hand[1] - base[1]
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        sway = 0.0 if pulled else math.sin(t * 0.8 + self.ph) * 1.2
        top = (base[0] + ux * 250 + sway, base[1] + uy * 250)
        b.line(base, top, WOOD, 3.4)
        b.line((base[0] - 0.9, base[1]), (top[0] - 0.9, top[1]), WOOD_HI, 1.0)
        for f in (0.22, 0.5, 0.82):
            px, py = lerp(base[0], top[0], f), lerp(base[1], top[1], f)
            b.line((px - 2.4, py), (px + 2.4, py), GOLD_DK, 1.8)
        cx, cy = top[0], top[1] - 14.0
        pulse = 0.5 + 0.5 * math.sin(t * 2.4 + self.ph)
        ring = ellipse_pts(cx, cy, 11, 11, n=28)
        b.path(ring, GOLD_DK, 3.2)
        b.path(ring, GOLD, 1.6)
        for k in range(8):
            a = t * 0.3 + k * math.pi / 4
            b.line((cx + math.cos(a) * 11, cy + math.sin(a) * 11), (cx + math.cos(a) * 15.5, cy + math.sin(a) * 15.5), GOLD, 1.2)
        b.glow(cx, cy, 20, (176, 120, 255), int(120 + 60 * pulse))
        b.circle(cx, cy, 6.2, mix((120, 70, 200), (190, 140, 255), pulse), (240, 220, 255), 0.8)
        b.circle(cx - 1.6, cy - 1.8, 1.6, WHITE)
        b.line((cx, cy - 25), (cx, cy - 37), GOLD, 1.8)
        b.line((cx - 4, cy - 31), (cx + 4, cy - 31), GOLD, 1.8)
        self.light(cx, cy, 70, (170, 110, 255), 5)

    def _witch_arms(self, rig: dict) -> None:
        """Loose knit sweater sleeves with ribbon ties (Image 2)."""
        b = self.b
        sw_col = mix((118, 115, 126), self.accent_col, 0.22)
        sw_edge = mix((78, 75, 86), self.accent_col, 0.20)
        ribbon_col = mix((42, 38, 48), self.trim_col, 0.35)
        for s, k in ((-1, "L"), (1, "R")):
            sh, el, wr = rig["sh" + k], rig["el" + k], rig["wr" + k]
            path = quad_path(sh, el, wr, 12)
            widths = [lerp(7.0, 13.0, (i / 12) ** 1.5) + 0.8 * math.sin(math.pi * i / 12) for i in range(13)]
            b.poly(ribbon(path, widths), sw_col, sw_edge, 0.8)
            # Ribbon cross-laces on sleeves (Image 2)
            mid = path[6]
            b.line((mid[0] - 4, mid[1] - 4), (mid[0] + 4, mid[1] + 4), ribbon_col, 1.5)
            b.line((mid[0] + 4, mid[1] - 4), (mid[0] - 4, mid[1] + 4), ribbon_col, 1.5)
            end, prev = path[-1], path[-3]
            ang = math.atan2(end[1] - prev[1], end[0] - prev[0])
            ca, sa = math.cos(ang), math.sin(ang)
            self._hand((end[0] + ca * 5.5, end[1] + sa * 5.5), ang, (252, 240, 238), (224, 202, 208), 0.95)

    def _witch_head(self, rig: dict) -> None:
        """Raccoon ears & wide tattered witch hat with flower pin (Image 2)."""
        b = self.b
        hc = rig["head"]
        x, y = hc
        strain = clamp(len(self.res) / 4.0, 0.0, 1.0)
        w_hair_br = (66, 46, 40)
        w_hair_sh = (44, 30, 26)
        w_hair_hi = (112, 82, 72)
        hat_col = (56, 52, 60)
        hat_edge = (36, 32, 40)

        # 1. Face & Chocolate Brown Hair
        b.ellipse(x, y - 1, 21.5, 24.5, (8, 6, 14), hat_edge, 0.8)
        b.ellipse(x, y - 3, 19.0, 22.0, w_hair_sh)
        self._face(hc, (252, 240, 238), (224, 202, 208), (145, 82, 95), (255, 210, 220), strain)
        b.ellipse(x, y - 12.5, 17.6, 11.2, w_hair_br, w_hair_sh, 0.6)
        self._locks(hc, WITCH_BANGS, w_hair_br, w_hair_sh, w_hair_hi, amp=2.0)
        self._locks(hc, WITCH_FRONT_LOCKS, w_hair_br, w_hair_sh, w_hair_hi, amp=5.0)

        # 2. Cute furry Raccoon Ears peeking out (Image 2)
        for s in (-1, 1):
            ear_base = (x + s * 14.0, y - 14.0)
            ear_tip = (x + s * 24.0, y - 34.0)
            ear_in = (x + s * 6.0, y - 24.0)
            b.poly([ear_base, ear_tip, ear_in], (54, 48, 54), hat_edge, 0.8)
            b.poly([(ear_base[0] + s * 2, ear_base[1] - 2), (ear_tip[0] - s * 2, ear_tip[1] + 3), (ear_in[0] + s * 1, ear_in[1] - 1)],
                   (238, 206, 216), (252, 238, 244), 0.5)

        # 3. Wide Tattered Witch Hat with Flower Pin (Image 2)
        # Wide elliptical tilted brim with ragged edge
        brim_pts = []
        for a_step in range(28):
            ang = a_step * math.tau / 28
            # Jagged frayed rips on brim edges
            rip = 3.0 * math.sin(ang * 5.0) if a_step in (4, 5, 12, 13, 20, 21) else 0.0
            bx = x + 4.0 + math.cos(ang) * (56.0 + rip)
            by = y - 20.0 + math.sin(ang) * (15.0 + rip * 0.3) - math.cos(ang) * 4.0
            brim_pts.append((bx, by))
        b.poly(brim_pts, hat_col, hat_edge, 1.0)

        # Hatband
        band_col = mix((88, 82, 96), self.accent_col, 0.30)
        b.poly([(x - 22, y - 25), (x + 24, y - 28), (x + 22, y - 34), (x - 20, y - 31)], band_col, hat_edge, 0.6)

        # Flower Pin on hatband (twin pale blossoms - Image 2)
        fl_x, fl_y = x + 18.0, y - 31.0
        for fa in range(5):
            fang = fa * math.tau / 5
            b.circle(fl_x + math.cos(fang) * 3.5, fl_y + math.sin(fang) * 3.5, 2.2, (244, 240, 246), (190, 185, 198), 0.4)
        b.circle(fl_x, fl_y, 1.5, (255, 225, 140))  # gold stamen

        # Conical hat top curving and bending with a zig-zag lightning tear (Image 2)
        cone_pts = [(x - 18, y - 30), (x - 26, y - 55), (x - 14, y - 82), (x + 12, y - 68), (x + 20, y - 33)]
        b.poly(cone_pts, hat_col, hat_edge, 1.0)
        # Lightning zig-zag tear on hat side (Image 2)
        b.path([(x - 2, y - 48), (x + 6, y - 56), (x + 1, y - 62), (x + 10, y - 72)], (22, 18, 26), 2.0)
        # lace-edged hood rim in front of the hair
        arc = ellipse_pts(x, y - 1, 22.5, 25.5, n=34, a0=math.pi * 0.85, a1=math.pi * 2.15)
        b.path(arc, DRESS_DK, 4.6)
        b.path(arc, DRESS_EDGE, 1.0, caps=False)
        for px, py in arc[1:-1:2]:
            dx, dy = px - x, py - (y - 1)
            dd = math.hypot(dx, dy) or 1.0
            ox, oy = px + dx / dd * 3.2, py + dy / dd * 3.2
            b.circle(ox, oy, 2.3, LACE, LACE_DK, 0.5)
            b.circle(ox, oy, 0.9, DRESS_DK)


# hair lock tables: (x0, y0, x1, y1, bulge, half_width, phase) relative to the head centre
ANGEL_BACK_LOCKS = [(-10, -8, -24, 128, -8, 9, 0.0), (-4, -12, -14, 138, -3, 10, 0.9), (4, -12, 10, 142, 3, 10, 1.7),
                    (10, -8, 22, 130, 8, 9, 2.5), (-14, -2, -34, 100, -10, 7, 3.3), (14, -2, 32, 104, 10, 7, 4.1)]
ANGEL_BANGS = [(-12, -20, -14, 3, -4, 5.2, 0.2), (-6, -22, -8, -1.5, -2, 5.0, 0.9), (1, -22, 2, -2.5, 1, 5.2, 1.6),
               (8, -21, 9, -1, 3, 5.0, 2.3), (13, -18, 15, 5, 3, 4.6, 3.1)]
ANGEL_SIDE_LOCKS = [(-15, -8, -19, 52, -5, 6.0, 0.4), (15, -8, 19, 56, 5, 6.0, 1.3)]
ANGEL_AHOGE = [(0, -23, 4, -35, 2, 1.8, 2.0)]
WITCH_BACK_LOCKS = [(-17, -6, -44, 150, -14, 12, 0.0), (-10, -10, -30, 160, -8, 12, 0.7), (10, -10, 34, 158, 8, 12, 1.5),
                    (17, -6, 46, 148, 14, 12, 2.2), (-20, 2, -52, 120, -18, 9, 2.9), (20, 2, 54, 124, 18, 9, 3.6),
                    (0, -12, 0, 168, 0, 13, 4.3)]
WITCH_BANGS = [(-12, -20, -13, 2, -3, 5.4, 0.3), (-5, -22, -6, -2, -2, 5.2, 1.0), (2, -22, 3, -3, 1, 5.4, 1.7),
               (9, -21, 10, -1, 3, 5.2, 2.4), (14, -17, 16, 6, 3, 4.8, 3.2)]
WITCH_FRONT_LOCKS = [(-16, -4, -26, 66, -6, 6.5, 0.5), (16, -4, 27, 70, 6, 6.5, 1.4),
                     (-13, 2, -19, 50, -3, 4.5, 2.2), (13, 2, 20, 52, 3, 4.5, 3.0)]


# ===================================================================================================
#  the renderer
# ===================================================================================================
@dataclass
class _Sprite:
    surf: pygame.Surface
    hits: list[Hit]
    lights: list[Light]
    stamp: float
    sig: tuple


class Renderer:
    """Draws the whole scene. Call update(dt) then draw(surface, characters) every frame."""

    def __init__(self, size: tuple[int, int] = (1280, 720), floor_y: Optional[int] = None,
                 on_struggle: Optional[Callable[[HoverTarget], None]] = None, bloom: bool = True, seed: int = 7) -> None:
        self.w, self.h = size
        self.floor_y = floor_y if floor_y is not None else int(self.h * 0.62)
        self.atmo = Atmosphere(self.w, self.h, self.floor_y, seed)
        self.on_struggle = on_struggle
        self.bloom_enabled = bloom
        self.time = 0.0
        self.mouse_override: Optional[tuple[int, int]] = None   # set to bypass pygame.mouse.get_pos() (tests, scaled windows)
        self.hovered: Optional[HoverTarget] = None
        self._dt = 1.0 / 60.0
        self.motion_scale = 1.0
        self._sprites: dict[int, _Sprite] = {}
        self._shadows: dict[tuple[int, int], pygame.Surface] = {}
        self._fonts: dict[str, pygame.font.Font] = {}
        self._centers: dict[tuple[int, RestraintKind], tuple[int, int]] = {}
        self._hover_rects: list[pygame.Rect] = []
        self.assets: Optional[Any] = None   # R2: ui.r2_assets.AssetLibrary; None => procedural art only
        self._tip_target: Optional[HoverTarget] = None
        self._tip_alpha = 0.0
        self._hand_cursor = False

    # ---- public API -----------------------------------------------------------------------------
    @property
    def hovered_restraint(self) -> Optional[Restraint]:
        return self.hovered.restraint if self.hovered else None

    @property
    def hovered_character(self) -> Optional[Character]:
        return self.hovered.character if self.hovered else None

    def update(self, dt: float) -> None:
        self._dt = clamp(dt, 0.0, 0.1) * clamp(getattr(self, "motion_scale", 1.0), 0.0, 1.0)
        self.time += self._dt
        self.atmo.update(self._dt, self.time)

    def burst(self, x: float, y: float, color: Color = (255, 150, 64), count: int = 28) -> None:
        self.atmo.burst(x, y, color, count)

    def shatter(self, ch: Character, kind: RestraintKind) -> None:
        """Burst of sparks where the restraint was, then remove it from the character."""
        r = ch.restraint(kind)
        if r is None:
            return
        cx, cy = self._centers.get((ch.uid, kind), (int(ch.x), int(ch.y - 100 * ch.scale)))
        self.atmo.burst(cx, cy, r.info.accent, 46)
        r.resistance = 0.0
        ch.release(kind)
        self._sprites.pop(ch.uid, None)

    def handle_event(self, event: pygame.event.Event) -> Optional[HoverTarget]:
        """[E] while hovering a restraint = a struggle attempt. Returns the target (or None)."""
        if event.type == pygame.KEYDOWN and event.key == pygame.K_e and self.hovered is not None:
            target = self.hovered
            target.restraint.shake = 1.0
            cx, cy = self._centers.get((target.character.uid, target.restraint.kind), (0, 0))
            self.atmo.burst(cx, cy, target.restraint.info.accent, 12)
            if self.on_struggle is not None:
                self.on_struggle(target)
            return target
        return None

    def draw(self, surface: pygame.Surface, characters: Sequence[Character],
             mouse_pos: Optional[tuple[int, int]] = None) -> None:
        t = self.time
        atmo = self.atmo
        atmo.draw_backdrop(surface, t)
        atmo.draw_fog_back(surface, t)
        atmo.draw_embers(surface, t, False)
        candidates: list[tuple[int, pygame.Rect, Character, Restraint]] = []
        lights: list[tuple[float, float, float, Color, int]] = []
        seen: set[int] = set()
        self._centers.clear()
        xs = sorted(c.x for c in characters)
        gap = min((b - a for a, b in zip(xs, xs[1:]) if b - a > 1.0), default=0.0)
        for ch in sorted(characters, key=lambda c: c.y):
            for r in ch.restraints:
                r.shake = max(0.0, r.shake - self._dt * 2.2)
            seen.add(ch.uid)
            self._draw_shadow(surface, ch)
            assets = self.assets
            aspect = assets.model_aspect(ch.kind.value) if assets is not None and assets.enabled else None
            spr = None if aspect else self._sprite(ch)      # R2 anime model replaces the procedural body
            motion = getattr(self, "combat_vfx", None)
            entity_uid = int(getattr(ch, "entity_uid", 0) or 0)
            remaining = motion.lunges.get(entity_uid, 0.0) if motion is not None and entity_uid else 0.0
            lunge = motion.lunge_offset(entity_uid, 1) if motion is not None and entity_uid else 0
            hurt = motion.hit_strength(entity_uid) if motion is not None and entity_uid else 0.0
            tremor = int(math.sin(self.time * 78.0 + ch.phase) * 4 * hurt) if hurt > 0 else 0
            dy = -int(math.sin(math.pi * (1.0 - remaining / 0.28)) * 8) if remaining > 0 else 0
            dx = lunge + tremor
            model_rect = self._draw_model(surface, ch, aspect, dx, dy, hurt, gap) if aspect else None
            if model_rect is not None:
                hit_list = [(RestraintKind[n], b) for n, b in model_hit_boxes(
                    model_rect.x, model_rect.y, model_rect.width, model_rect.height, ch.x, ch.y, ch.scale)]
                light_list = []
            else:
                if spr is None:                    # model failed at draw time: fall back to the procedural body
                    spr = self._sprite(ch)
                sx, sy = int(ch.x - OX * ch.scale + dx), int(ch.y - OY * ch.scale + dy)
                surface.blit(spr.surf, (sx, sy))
                hit_list, light_list = spr.hits, spr.lights
            if assets is not None and assets.enabled and entity_uid:
                assets.draw_pops(surface, entity_uid, ch.x + dx, ch.y - 214 * ch.scale + dy, ch.scale)
            if remaining > 0:
                progress = 1.0 - remaining / 0.28
                slash_col = ((235, 215, 255) if ch.kind in (CharacterKind.WITCH, CharacterKind.FALLEN_ANGEL)
                             else (150, 255, 190) if ch.kind is CharacterKind.ROGUE
                             else (255, 186, 105) if ch.kind is CharacterKind.KITSUNE
                             else (255, 91, 126) if ch.kind is CharacterKind.VAMPIRE
                             else (255, 151, 65) if ch.kind is CharacterKind.DRAGONKIN
                             else (255, 160, 108) if ch.kind is CharacterKind.WARRIOR
                             else (160, 210, 255))
                arc = pygame.Rect(int(ch.x + 8 * ch.scale + dx), int(ch.y - 186 * ch.scale + dy),
                                 max(24, int(92 * ch.scale)), max(18, int(56 * ch.scale)))
                pygame.draw.arc(surface, slash_col, arc, 0.18 + progress * 0.75, 2.45 + progress * 0.75,
                                max(2, int(3 * ch.scale)))
            if motion is not None and entity_uid:
                motion.draw_actor_effect(surface, entity_uid, (ch.x + dx, ch.y - 190 * ch.scale + dy),
                                         24 + 18 * ch.scale)
            boxes: dict[RestraintKind, list[pygame.Rect]] = {}
            for kind, (hx, hy, hw, hh) in hit_list:
                rect = pygame.Rect(int(ch.x + hx * ch.scale), int(ch.y + hy * ch.scale),
                                   max(1, int(hw * ch.scale)), max(1, int(hh * ch.scale)))
                r = ch.restraint(kind)
                if r is not None and not r.broken:
                    candidates.append((rect.width * rect.height, rect, ch, r))
                    boxes.setdefault(kind, []).append(rect)
            for kind, rects in boxes.items():
                u = rects[0].unionall(rects[1:]) if len(rects) > 1 else rects[0]
                self._centers[(ch.uid, kind)] = u.center
                if model_rect is not None:
                    self._draw_restraint_mark(surface, kind, u, ch)
            for lx, ly, lr, lc, lv in light_list:
                lights.append((ch.x + lx * ch.scale, ch.y + ly * ch.scale, lr * ch.scale, lc, lv))
        for uid in [u for u in self._sprites if u not in seen]:
            del self._sprites[uid]
        atmo.draw_fog_front(surface, t)
        atmo.draw_embers(surface, t, True)
        self._draw_lights(surface, lights)
        if self.bloom_enabled:
            self._bloom(surface)
        atmo.draw_vignette(surface)
        # --- hover + tooltip (drawn last, never bloomed) ---
        mouse = mouse_pos if mouse_pos is not None else (self.mouse_override or pygame.mouse.get_pos())
        self._resolve_hover(candidates, mouse)
        self._set_cursor(self.hovered is not None)
        if self.hovered is not None:
            self._tip_target = self.hovered
            self._tip_alpha = min(1.0, self._tip_alpha + self._dt * 8.0)
            self._draw_highlights(surface)
        else:
            self._tip_alpha = max(0.0, self._tip_alpha - self._dt * 9.0)
        if self._tip_target is not None and self._tip_alpha > 0.01 and not self._tip_target.restraint.broken:
            self._draw_tooltip(surface, self._tip_target, mouse, self._tip_alpha)

    # ---- R2 anime models -----------------------------------------------------------------------
    def _draw_model(self, surface: pygame.Surface, ch: Character, aspect: float, dx: int, dy: int, hurt: float,
                    gap: float) -> Optional[pygame.Rect]:
        """Draw the hero's anime bust (glow, idle sway, hit flash). Returns its rect, or None to fall back."""
        assets = self.assets
        try:
            height = fit_model_height(ch.scale, aspect, gap)
            img = assets.model(ch.kind.value, int(height))
            if img is None:
                return None
            w, h = img.get_size()
            sway = math.sin(self.time * 1.6 + ch.phase) * 3.0 * max(0.5, ch.scale)
            rect = pygame.Rect(int(ch.x - w / 2 + dx), int(ch.y - h + dy + sway), w, h)
            halo = assets.glow(ch.kind.value, (int(w * 1.25), int(h * 1.05)))
            if halo is not None:
                surface.blit(halo, (rect.centerx - halo.get_width() // 2, rect.centery - halo.get_height() // 2))
            if hurt > 0.0:
                img = img.copy()
                img.fill((int(150 * hurt), int(15 * hurt), int(30 * hurt), 0), special_flags=getattr(pygame, "BLEND_RGB_ADD", 0))
            surface.blit(img, rect.topleft)
            return rect
        except (pygame.error, AttributeError, ValueError, TypeError) as exc:
            assets.disable(f"anime model draw failed: {exc}")
            return None

    def _draw_restraint_mark(self, surface: pygame.Surface, kind: RestraintKind, rect: pygame.Rect, ch: Character) -> None:
        """Visible marker for each live restraint, because the anime art has no procedural chains painted on it."""
        assets = self.assets
        try:
            pulse = 0.5 + 0.5 * math.sin(self.time * 4.0 + ch.phase)
            col = (255, int(70 + 60 * pulse), int(90 + 60 * pulse))
            pygame.draw.ellipse(surface, col, rect.inflate(-rect.width // 6, -rect.height // 6), 1)
            icon = assets.icon(RESTRAINT_KIND_ICON.get(kind.name, "chains"), 30) if assets is not None else None
            if icon is not None:
                surface.blit(icon, (rect.centerx - icon.get_width() // 2, rect.centery - icon.get_height() // 2))
        except (pygame.error, AttributeError, ValueError, TypeError):
            pass

    # ---- sprites --------------------------------------------------------------------------------
    def _sprite(self, ch: Character) -> _Sprite:
        live = [r for r in ch.restraints if not r.broken]
        sig = (ch.kind, round(ch.scale, 3), tuple((r.kind, int(r.ratio * 12)) for r in live))
        shaking = any(r.shake > 0.02 for r in live)
        spr = self._sprites.get(ch.uid)
        if spr is None or spr.sig != sig or shaking or self.time - spr.stamp >= SPRITE_INTERVAL:
            spr = self._paint(ch, sig)
            self._sprites[ch.uid] = spr
        return spr

    def _paint(self, ch: Character, sig: tuple) -> _Sprite:
        k = SS * ch.scale
        layer = pygame.Surface((max(8, int(LW * k)), max(8, int(LH * k))), pygame.SRCALPHA)
        layer.fill((34, 24, 52, 0))      # transparent, but a dark tint so smoothscale fringes stay dark
        painter = SpritePainter(Brush(layer, k), self.time, ch)
        painter.paint()
        surf = pygame.transform.smoothscale(layer, (max(4, int(LW * ch.scale)), max(4, int(LH * ch.scale))))
        return _Sprite(surf, painter.hits, painter.lights, self.time, sig)

    def _draw_shadow(self, surface: pygame.Surface, ch: Character) -> None:
        lift = 0.0
        base = 84.0
        if ch.kind is CharacterKind.FALLEN_ANGEL:
            lift = 15.0 + math.sin(self.time * 1.25 + ch.phase * 0.7) * 5.0
            base = 70.0
        w = int(base * ch.scale * clamp(1.0 - lift / 90.0, 0.4, 1.0))
        h = max(4, int(w * 0.22))
        key = (w // 2 * 2, h // 2 * 2)
        sh = self._shadows.get(key)
        if sh is None:
            if len(self._shadows) > 64:
                self._shadows.clear()
            sh = pygame.Surface(key, pygame.SRCALPHA)
            for i in range(4):
                pygame.draw.ellipse(sh, (0, 0, 0, 36), (i * key[0] // 14, i * key[1] // 14,
                                                        max(2, key[0] - 2 * i * key[0] // 14), max(2, key[1] - 2 * i * key[1] // 14)))
            self._shadows[key] = sh
        surface.blit(sh, (int(ch.x - key[0] / 2), int(ch.y - key[1] / 2 + 3)))

    # ---- lighting -------------------------------------------------------------------------------
    @staticmethod
    def _draw_lights(surface: pygame.Surface, lights: Sequence[tuple[float, float, float, Color, int]]) -> None:
        for x, y, r, color, level in lights:
            rad = int(clamp(r, 8, 170)) // 4 * 4
            surface.blit(glow_add(rad, color, level), (int(x) - rad, int(y) - rad), special_flags=pygame.BLEND_RGB_ADD)

    def _bloom(self, surface: pygame.Surface) -> None:
        """Cheap soft bloom: downsample, keep only the bright parts, blur by upscaling, add back."""
        sw, sh = surface.get_size()
        small = pygame.transform.smoothscale(surface, (max(8, sw // 6), max(8, sh // 6)))
        small.fill((84, 84, 84), special_flags=pygame.BLEND_RGB_SUB)
        small.blit(small.copy(), (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        big = pygame.transform.smoothscale(small, (sw, sh))
        big.fill((190, 190, 190), special_flags=pygame.BLEND_RGB_MULT)
        surface.blit(big, (0, 0), special_flags=pygame.BLEND_RGB_ADD)

    # ---- hover ----------------------------------------------------------------------------------
    def _resolve_hover(self, cands: list[tuple[int, pygame.Rect, Character, Restraint]], mouse: tuple[int, int]) -> None:
        best: Optional[tuple[int, pygame.Rect, Character, Restraint]] = None
        for item in cands:
            if item[1].collidepoint(mouse) and (best is None or item[0] < best[0]):
                best = item
        if best is None:
            self.hovered = None
            self._hover_rects = []
            return
        _, _, ch, r = best
        if self.hovered is None or self.hovered.character is not ch or self.hovered.restraint is not r:
            self.hovered = HoverTarget(ch, r)
        self._hover_rects = [rect for _, rect, c, rr in cands if c is ch and rr is r][:14]

    def _set_cursor(self, hand: bool) -> None:
        if hand == self._hand_cursor:
            return
        self._hand_cursor = hand
        try:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if hand else pygame.SYSTEM_CURSOR_ARROW)
        except (pygame.error, TypeError, AttributeError):
            pass

    def _draw_highlights(self, surface: pygame.Surface) -> None:
        if self.hovered is None:
            return
        accent = self.hovered.restraint.info.accent
        pulse = 0.5 + 0.5 * math.sin(self.time * 6.0)
        col = with_alpha(mix(accent, WHITE, 0.25 + 0.3 * pulse), 150 + 80 * pulse)
        for rect in self._hover_rects:
            box = rect.inflate(4, 4)
            tmp = pygame.Surface(box.size, pygame.SRCALPHA)
            if box.width > box.height * 3:
                pygame.draw.ellipse(tmp, col, tmp.get_rect(), 2)
            else:
                pygame.draw.rect(tmp, col, tmp.get_rect(), 2, border_radius=7)
            surface.blit(tmp, box.topleft)

    # ---- tooltip --------------------------------------------------------------------------------
    def _font(self, name: str) -> pygame.font.Font:
        f = self._fonts.get(name)
        if f is None:
            if not pygame.font.get_init():
                pygame.font.init()
            spec = {"title": (22, True, False), "body": (15, False, True), "small": (13, False, False),
                    "key": (14, True, False)}[name]
            f = self._fonts[name] = load_font(spec[0], spec[1], spec[2])
        return f

    @staticmethod
    def _wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
        lines: list[str] = []
        cur = ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if cur and font.size(trial)[0] > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def _draw_tooltip(self, surface: pygame.Surface, target: HoverTarget, mouse: tuple[int, int], alpha: float) -> None:
        r = target.restraint
        info = r.info
        f_title, f_body, f_small, f_key = self._font("title"), self._font("body"), self._font("small"), self._font("key")
        width, pad = 326, 14
        inner = width - 2 * pad
        label, scol = r.status
        accent = info.accent
        pulse = 0.5 + 0.5 * math.sin(self.time * 5.0)

        title = f_title.render(info.name, True, mix(accent, WHITE, 0.4))
        lore_lines = self._wrap(f_body, info.lore, inner)
        lore_h = len(lore_lines) * f_body.get_linesize()
        row_h = f_small.get_height()
        bar_h = 12
        foot_h = f_key.get_height() + 8
        height = (pad + title.get_height() + 6 + 8 + row_h + 5 + bar_h + 10 + lore_h + 8 + 8 + foot_h + pad - 4)

        box = pygame.Surface((width, height), pygame.SRCALPHA)
        rect = box.get_rect()
        pygame.draw.rect(box, (12, 8, 22, 216), rect, border_radius=9)
        band = pygame.Surface((width - 4, pad + title.get_height() + 10), pygame.SRCALPHA)
        band.fill((*mix((40, 20, 70), accent, 0.25), 70))
        box.blit(band, (2, 2))
        pygame.draw.rect(box, (*mix((90, 56, 150), accent, 0.35), 235), rect, 1, border_radius=9)
        pygame.draw.rect(box, (70, 40, 112, 190), rect.inflate(-6, -6), 1, border_radius=6)
        for cx, cy in ((5, 5), (width - 6, 5), (5, height - 6), (width - 6, height - 6)):
            pygame.draw.polygon(box, (*accent, 235), [(cx, cy - 3), (cx + 3, cy), (cx, cy + 3), (cx - 3, cy)])

        y = pad - 2
        box.blit(title, ((width - title.get_width()) // 2, y))
        y += title.get_height() + 6
        pygame.draw.line(box, (*accent, 150), (pad + 6, y), (width // 2 - 7, y))
        pygame.draw.line(box, (*accent, 150), (width // 2 + 7, y), (width - pad - 6, y))
        pygame.draw.polygon(box, (*accent, 230), [(width // 2, y - 3), (width // 2 + 4, y), (width // 2, y + 3), (width // 2 - 4, y)])
        y += 8
        left = f_small.render("Resistance Status", True, (160, 150, 186))
        right = f_small.render(label.upper(), True, scol)
        box.blit(left, (pad, y))
        box.blit(right, (width - pad - right.get_width(), y))
        y += row_h + 5
        bar = pygame.Rect(pad, y, inner, bar_h)
        pygame.draw.rect(box, (26, 16, 42, 235), bar, border_radius=4)
        fill = pygame.Rect(bar.x, bar.y, int(bar.width * r.ratio), bar.height)
        if fill.width > 0:
            pygame.draw.rect(box, (*scol, 235), fill, border_radius=4)
            pygame.draw.rect(box, (*mix(scol, WHITE, 0.45), 140), pygame.Rect(fill.x, fill.y, fill.width, bar_h // 3), border_radius=4)
        for i in range(1, 10):
            bx = bar.x + bar.width * i // 10
            pygame.draw.line(box, (10, 6, 18, 150), (bx, bar.y + 1), (bx, bar.bottom - 2))
        pygame.draw.rect(box, (120, 96, 170, 220), bar, 1, border_radius=4)
        val = f_small.render(f"{int(round(r.resistance))} / {int(round(r.max_resistance))}", True, WHITE)
        box.blit(val, (bar.centerx - val.get_width() // 2, bar.centery - val.get_height() // 2))
        y += bar_h + 10
        for ln in lore_lines:
            box.blit(f_body.render(ln, True, (206, 196, 226)), (pad, y))
            y += f_body.get_linesize()
        y += 8
        pygame.draw.line(box, (*accent, 110), (pad, y), (width - pad, y))
        y += 8
        p1 = f_key.render("Press ", True, (176, 166, 204))
        p2 = f_key.render("[E]", True, WHITE)
        p3 = f_key.render(" to Struggle", True, (236, 132, 146))
        x = (width - (p1.get_width() + p2.get_width() + p3.get_width())) // 2
        cap = pygame.Rect(x + p1.get_width() - 3, y - 1, p2.get_width() + 6, p2.get_height() + 2)
        pygame.draw.rect(box, (*mix((60, 30, 100), accent, 0.3 + 0.4 * pulse), int(120 + 90 * pulse)), cap, border_radius=5)
        pygame.draw.rect(box, (*mix(accent, WHITE, 0.3), 235), cap, 1, border_radius=5)
        box.blit(p1, (x, y))
        box.blit(p2, (x + p1.get_width(), y))
        box.blit(p3, (x + p1.get_width() + p2.get_width(), y))

        bx, by = mouse[0] + 18, mouse[1] + 22
        sw, sh = surface.get_size()
        if bx + width > sw - 6:
            bx = mouse[0] - width - 14
        if by + height > sh - 6:
            by = mouse[1] - height - 14
        bx, by = int(clamp(bx, 6, max(6, sw - width - 6))), int(clamp(by, 6, max(6, sh - height - 6)))
        shadow = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), shadow.get_rect(), border_radius=9)
        shadow.set_alpha(int(255 * alpha))
        surface.blit(shadow, (bx + 3, by + 4))
        box.set_alpha(int(255 * alpha))
        surface.blit(box, (bx, by))


AAARenderer = Renderer      # alias kept for older imports

__all__ = ["Renderer", "AAARenderer", "Character", "CharacterKind", "Restraint", "RestraintKind", "RestraintLore",
           "RESTRAINT_LORE", "HoverTarget", "STRUGGLE_PROMPT"]


# ===================================================================================================
#  interactive demo:  python renderer.py
# ===================================================================================================
def _demo() -> None:
    pygame.init()
    size = (1280, 720)
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("Abyssal Choir - renderer demo")
    clock = pygame.time.Clock()
    rng = random.Random(3)

    def on_struggle(target: HoverTarget) -> None:
        r = target.restraint
        r.resistance = max(0.0, r.resistance - rng.uniform(8.0, 15.0))
        if r.resistance <= 0.0:
            renderer.shatter(target.character, r.kind)

    renderer = Renderer(size, on_struggle=on_struggle)

    def make_cast() -> list[Character]:
        angel = Character(CharacterKind.FALLEN_ANGEL, "Seraphine", 410, 650, 1.2)
        for kind in RestraintKind:
            angel.bind(kind)
        witch = Character(CharacterKind.WITCH, "Morrigan", 870, 650, 1.2)
        witch.bind(RestraintKind.GOTHIC_CHAINS, 100)
        witch.bind(RestraintKind.SACRED_RUNE_BINDINGS, 70)
        witch.bind(RestraintKind.CROWN_OF_THORNS, 45)
        return [angel, witch]

    cast = make_cast()
    help_font = renderer._font("small")
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                cast = make_cast()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_b:
                renderer.bloom_enabled = not renderer.bloom_enabled
            else:
                renderer.handle_event(event)
        renderer.update(dt)
        renderer.draw(screen, cast)
        hint = help_font.render("Hover a restraint   [E] struggle   [R] reset   [B] bloom   [ESC] quit", True, (170, 160, 200))
        screen.blit(hint, (16, size[1] - 26))
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    _demo()
