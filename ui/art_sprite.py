"""Illustrated character "standees" for the combat/title renderer (R2 art pass).

The eight classes are drawn from cut-out anime key art (``Assets/Art/models/<class>.png``, produced by
``tools/extract_art.py``). This module turns one of those images plus the live Restraint list into a ready-to-blit
surface, and reports the click/hover rectangles for each restraint so the existing "hover a restraint and press E to
struggle" interaction keeps working exactly as it did with the procedural sprites.

If a model image is missing, ``paint_art_sprite`` returns ``None`` and the caller falls back to the procedural painter.
No pygame state is touched at import time.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import pygame

Color = tuple[int, int, int]

# display height (px at ch.scale == 0.52, the three-hero formation) and float height per class
ART_PROFILE: dict[str, tuple[float, float]] = {
    "warrior": (300.0, 0.0), "tank": (300.0, 0.0), "rogue": (300.0, 0.0), "witch": (306.0, 0.0),
    "vampire": (300.0, 0.0), "dragonkin": (300.0, 0.0),
    "fallen_angel": (330.0, 10.0),   # floats slightly: chained, but not grounded
    "kitsune": (246.0, 44.0),        # bust-up art: hovers on foxfire instead of standing
}
AURA: dict[str, Color] = {
    "warrior": (255, 150, 104), "tank": (124, 172, 255), "rogue": (118, 230, 168), "witch": (184, 124, 255),
    "fallen_angel": (214, 96, 255), "kitsune": (255, 172, 92), "vampire": (255, 72, 118), "dragonkin": (255, 124, 56),
}
THORN: Color = (22, 12, 30)
THORN_EDGE: Color = (130, 56, 170)
THORN_TIP: Color = (230, 92, 168)
RUNE: Color = (196, 128, 255)
RUNE_HI: Color = (240, 214, 255)
IRON_HI: Color = (206, 204, 228)

# (x0, y0, x1, y1) fractions of the standee box, per restraint kind (several rects allowed)
HIT_FRACTIONS: dict[str, list[tuple[float, float, float, float]]] = {
    "gothic_chains": [(0.12, 0.40, 0.88, 0.70)],
    "crown_of_thorns": [(0.22, 0.00, 0.78, 0.17)],
    "sacred_rune_bindings": [(0.00, 0.55, 0.30, 0.74), (0.70, 0.55, 1.00, 0.74), (0.05, 0.93, 0.95, 1.00)],
    "shadow_thorn_vines": [(0.18, 0.70, 0.82, 0.97)],
}


@dataclass
class ArtSprite:
    surf: Any
    hits: list[tuple[str, tuple[float, float, float, float]]]
    ox: float                 # feet-centre x inside ``surf``
    oy: float                 # feet y inside ``surf``
    lights: list[tuple[float, float, float, Color, int]] = field(default_factory=list)


def class_key(kind: Any) -> str:
    return str(getattr(kind, "value", kind)).lower()


def display_height(key: str, scale: float) -> float:
    base, _lift = ART_PROFILE.get(key, (300.0, 0.0))
    return max(60.0, base * (0.52 + (scale - 0.52) * 0.66) / 0.52)


def _scaled(assets: Any, rel_fx: str, size: tuple[int, int]) -> Optional[Any]:
    return assets.fx(rel_fx, (max(2, size[0]), max(2, size[1])))


_FADED: dict[tuple[int, tuple[int, int]], Any] = {}


def _faded_bottom(fig: Any, frac: float = 0.10) -> Any:
    """Copy of ``fig`` whose lowest ``frac`` dissolves to transparent, so a cut-out never ends in a hard line."""
    key = (id(fig), fig.get_size())
    hit = _FADED.get(key)
    if hit is not None:
        return hit
    w, h = fig.get_size()
    out = fig.copy()
    mask = pygame.Surface((w, h), pygame.SRCALPHA)
    mask.fill((255, 255, 255, 255))
    start = int(h * (1.0 - frac))
    for y in range(start, h):
        a = int(255 * (1.0 - (y - start) / max(1, h - start)) ** 1.3)
        pygame.draw.line(mask, (255, 255, 255, a), (0, y), (w, y))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    if len(_FADED) > 40:
        _FADED.clear()
    _FADED[key] = out
    return out


def _aura(layer: Any, cx: float, cy: float, rx: float, ry: float, col: Color, alpha: int) -> None:
    """Soft layered ellipse glow (alpha-blended so it also works on a transparent layer)."""
    for i in range(7):
        f = 1.0 - i / 7.0
        a = int(alpha * (0.10 + 0.55 * (1 - f)) / 3.2)
        r = pygame.Rect(0, 0, int(rx * 2 * (0.55 + 0.45 * f)), int(ry * 2 * (0.55 + 0.45 * f)))
        r.center = (int(cx), int(cy))
        tmp = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.ellipse(tmp, (*col, max(0, min(255, a))), tmp.get_rect())
        layer.blit(tmp, r.topleft)


def _thorn_crown(layer: Any, box_w: float, ox: float, top: float, ratio: float, shake: float, t: float) -> None:
    cx, cy = ox + math.sin(t * 40) * shake * 2.0, top + box_w * 0.05
    rx, ry = box_w * 0.27, box_w * 0.07
    pts = []
    for i in range(40):
        a = i / 40 * math.tau
        pts.append((cx + math.cos(a) * rx, cy + math.sin(a) * ry))
    pygame.draw.lines(layer, THORN, True, pts, 5)
    pygame.draw.lines(layer, THORN_EDGE, True, pts, 2)
    spikes = 14 if ratio > 0.35 else 8
    for i in range(spikes):
        a = i / spikes * math.tau + 0.2
        px, py = cx + math.cos(a) * rx, cy + math.sin(a) * ry
        ln = (7 + 4 * math.sin(i * 2.3)) * (0.6 + 0.4 * ratio)
        tip = (px + math.cos(a) * ln, py + math.sin(a) * ln * 1.15 - 4)
        pygame.draw.polygon(layer, THORN_TIP, [(px - 2, py), (px + 2, py), tip])
    # a few crimson beads where the briars bite
    for i in range(3):
        a = 2.4 + i * 1.7
        pygame.draw.circle(layer, (255, 96, 120), (int(cx + math.cos(a) * rx), int(cy + math.sin(a) * ry)), 2)


def _rune_cuff(layer: Any, x: float, y: float, r: float, ratio: float, t: float, phase: float) -> None:
    glow = pygame.Surface((int(r * 5), int(r * 5)), pygame.SRCALPHA)
    for i in range(5):
        pygame.draw.circle(glow, (*RUNE, 16 + i * 6), glow.get_rect().center, int(r * (2.4 - i * 0.35)))
    layer.blit(glow, (int(x - glow.get_width() / 2), int(y - glow.get_height() / 2)))
    pygame.draw.circle(layer, (40, 20, 70), (int(x), int(y)), int(r))
    pygame.draw.circle(layer, RUNE, (int(x), int(y)), int(r), 2)
    pygame.draw.circle(layer, RUNE_HI, (int(x), int(y)), int(r * 0.62), 1)
    n = 6 if ratio > 0.4 else 4
    for i in range(n):
        a = phase + t * 0.9 + i / n * math.tau
        pygame.draw.line(layer, RUNE_HI, (x + math.cos(a) * r * 0.7, y + math.sin(a) * r * 0.7),
                         (x + math.cos(a) * r * 1.25, y + math.sin(a) * r * 1.25), 1)


def _floor_seal(layer: Any, cx: float, cy: float, rx: float, ratio: float, t: float) -> None:
    ry = rx * 0.17
    for k, w in ((1.0, 2), (0.78, 1)):
        r = pygame.Rect(0, 0, int(rx * 2 * k), int(ry * 2 * k))
        r.center = (int(cx), int(cy))
        pygame.draw.ellipse(layer, (*RUNE, 190), r, w)
    n = 8
    for i in range(n):
        a = t * 0.5 + i / n * math.tau
        x, y = cx + math.cos(a) * rx * 0.89, cy + math.sin(a) * ry * 0.89
        pygame.draw.circle(layer, RUNE_HI, (int(x), int(y)), 2 if ratio > 0.4 else 1)


def _vines(layer: Any, W: float, H: float, top: float, ox: float, ratio: float, shake: float, t: float) -> None:
    rng = random.Random(7)
    for v in range(2):
        side = -1 if v == 0 else 1
        phase = rng.random() * 6.0 + v
        pts = []
        steps = 26
        for i in range(steps + 1):
            f = i / steps
            y = top + H * (0.97 - 0.27 * f)
            x = ox + side * W * (0.16 - 0.05 * f) + math.sin(f * 11.0 + phase + t * 1.4) * W * 0.07 + math.sin(t * 45) * shake * 2.0
            pts.append((x, y))
        pygame.draw.lines(layer, THORN, False, pts, 7)
        pygame.draw.lines(layer, THORN_EDGE, False, pts, 2)
        for i in range(1, len(pts), 2):
            x, y = pts[i]
            d = -1 if i % 4 == 1 else 1
            pygame.draw.polygon(layer, THORN_TIP, [(x, y), (x + d * 9, y - 5), (x + d * 3, y + 2)])


def _chains(assets: Any, layer: Any, W: float, H: float, top: float, ox: float, ratio: float, shake: float, t: float) -> None:
    j = math.sin(t * 38) * shake * 3.0
    specs = [("chain_ring_red_b", 1.05, 0.40, 0.58), ("chain_silver_diagonal", 0.78, 0.42, 0.56), ("chain_silver_tangle", 0.62, 0.20, 0.80)]
    n = 3 if ratio > 0.6 else 2 if ratio > 0.3 else 1
    for name, wf, hf, yc in specs[:n]:
        size = (int(W * wf), int(H * hf))
        im = _scaled(assets, name, size)
        if im is None:
            # procedural fallback: a taut iron band
            r = pygame.Rect(0, 0, int(W * wf), int(H * 0.1))
            r.center = (int(ox), int(top + H * yc))
            pygame.draw.ellipse(layer, IRON_HI, r, 3)
            continue
        layer.blit(im, (int(ox - im.get_width() / 2 + j), int(top + H * yc - im.get_height() / 2)))


def paint_art_sprite(assets: Any, kind: Any, scale: float, restraints: Sequence[Any], t: float,
                     phase: float = 0.0, blood: int = 0, heat: int = 0) -> Optional[ArtSprite]:
    """Compose the standee. ``restraints`` are renderer ``Restraint`` objects (kind.value, ratio, shake, broken)."""
    key = class_key(kind)
    model = assets.model(key) if assets is not None else None
    if model is None:
        return None
    base_h, lift = ART_PROFILE.get(key, (300.0, 0.0))
    H = display_height(key, scale)
    mw, mh = model.get_size()
    W = H * mw / mh
    fig = assets.image(f"Art/models/{key}.png", (max(8, int(W)), max(8, int(H))))
    if fig is None:
        return None
    pad_x, pad_top, pad_bot = int(W * 0.30), 26, 16
    LWp, LHp = int(W + pad_x * 2), int(H + pad_top + pad_bot)
    layer = pygame.Surface((LWp, LHp), pygame.SRCALPHA)
    ox = LWp / 2.0
    feet_y = pad_top + H          # figure box bottom
    lift_px = lift * (H / base_h)
    aura = AURA.get(key, (200, 160, 255))
    live = [r for r in restraints if not getattr(r, "broken", False)]
    # glow behind the figure (stronger when the heroine is strained)
    strain = 0.0 if not live else 1.0 - min(r.ratio for r in live)
    acol = (255, 70, 110) if strain > 0.55 else aura
    _aura(layer, ox, feet_y - H * 0.50, W * 0.62, H * 0.52, acol, 120 + int(70 * strain))
    _aura(layer, ox, feet_y - 4, W * 0.55, W * 0.10, aura, 150)       # floor pool
    layer.blit(_faded_bottom(fig, 0.16 if key == 'kitsune' else 0.07), (int(ox - W / 2), int(feet_y - H)))
    # --- restraints ---------------------------------------------------------------------------------------
    for r in live:
        kv = getattr(r.kind, "value", str(r.kind))
        ratio = float(getattr(r, "ratio", 1.0))
        shake = float(getattr(r, "shake", 0.0))
        if kv == "gothic_chains":
            _chains(assets, layer, W, H, feet_y - H, ox, ratio, shake, t)
        elif kv == "crown_of_thorns":
            _thorn_crown(layer, W, ox, feet_y - H, ratio, shake, t)
        elif kv == "sacred_rune_bindings":
            _rune_cuff(layer, ox - W * 0.42, feet_y - H * 0.64, W * 0.075, ratio, t, 0.0)
            _rune_cuff(layer, ox + W * 0.42, feet_y - H * 0.64, W * 0.075, ratio, t, 1.7)
            _floor_seal(layer, ox, feet_y - 3, W * 0.5, ratio, t)
        elif kv == "shadow_thorn_vines":
            _vines(layer, W, H, feet_y - H, ox, ratio, shake, t)
    # hits: offsets from the feet point, in px (caller divides by ch.scale)
    hits: list[tuple[str, tuple[float, float, float, float]]] = []
    for kv, rects in HIT_FRACTIONS.items():
        for (x0, y0, x1, y1) in rects:
            hits.append((kv, ((x0 - 0.5) * W, y0 * H - H - lift_px, (x1 - x0) * W, (y1 - y0) * H)))
    lights = [(0.0, -H * 0.55 - lift_px, H * 0.55, aura, 2)]
    sp = ArtSprite(layer, hits, ox, feet_y, lights)
    sp.lift = lift_px  # type: ignore[attr-defined]
    return sp
