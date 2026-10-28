"""Presentation-only Pygame renderer for the menus, shop, HUD, pause and results screens.

``MenuRenderer`` draws; it never mutates game state and owns no navigation.  ``main.py``
decides which screen is active, which row is selected and what the data is.

Design notes
------------
* Everything is laid out in a 1280x720 *design space* (``core.config.SCREEN_W/H``) and mapped
  onto the target surface with a uniform scale, centred (letter/pillar-boxed).  Any surface
  size therefore renders correctly; backgrounds still fill the whole surface.
* No external assets: system fonts only (``core.config.FONT_FALLBACKS``), all art is drawn
  procedurally.  Background specks use a fixed-seed RNG, so output is deterministic apart
  from the selection pulse, which reads an injectable millisecond clock.
* Game objects (shop, party members, enemies, combat) are read by duck typing through
  ``getattr`` / mapping lookups with safe fallbacks, so this module imports nothing from
  gameplay code and cannot create circular imports.  The attribute names it looks for are
  listed in each method's docstring.
"""
from __future__ import annotations

import math
import operator
import random
from dataclasses import dataclass
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

import pygame

from core.config import (
    CLASS_BLURBS,
    CLASS_COLORS,
    DIFFICULTIES,
    FONT_FALLBACKS,
    MAX_PARTY,
    SCREEN_H,
    SCREEN_W,
    TITLE,
    Color,
    Pal,
    PlayerClass,
    is_boss_stage,
    is_endless_stage,
)

__all__ = ["MenuRenderer"]

DEFAULT_MAIN_MENU_ITEMS: Final[tuple[str, ...]] = ("Continue", "New Game", "Quit")
DEFAULT_PAUSE_ACTIONS: Final[tuple[str, ...]] = ("Resume", "Quit to Menu")

_DIFFICULTY_TAGLINES: Final[dict[str, str]] = {
    "Easy": "A gentler descent. Enemies are weakened.",
    "Normal": "The intended trial.",
    "Hard": "Foes strike harder and endure longer.",
    "Insane": "The Abyss shows no mercy.",
}
_DEFEAT_WORDS: Final[tuple[str, ...]] = ("defeat", "fallen", "game over", "slain", "died", "death")
_CLASS_ATTRS: Final[tuple[str, ...]] = (
    "player_class", "pclass", "cls", "klass", "class_", "class", "char_class", "hero_class",
)
_MISSING: Final = object()


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def _clamp01(value: float) -> float:
    if value != value:  # NaN
        return 0.0
    return max(0.0, min(1.0, value))


def _mix(a: Color, b: Color, t: float) -> Color:
    t = _clamp01(t)
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _shade(color: Color, factor: float) -> Color:
    return (
        max(0, min(255, int(color[0] * factor))),
        max(0, min(255, int(color[1] * factor))),
        max(0, min(255, int(color[2] * factor))),
    )


def _get(obj: Any, names: Sequence[str], default: Any = None) -> Any:
    """First non-callable value found under any of ``names`` (attribute or mapping key)."""
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, Mapping):
            if name in obj:
                return obj[name]
            continue
        value = getattr(obj, name, _MISSING)
        if value is not _MISSING and not callable(value):
            return value
    return default


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value) if math.isfinite(value) else default


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value)


def _seq(value: Any) -> list[Any]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _str_list(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping) or not isinstance(value, Iterable):
        raise TypeError(f"{name} must be a sequence of strings")
    return [str(item) for item in value]


def _coerce_class(value: Any) -> PlayerClass | None:
    if isinstance(value, PlayerClass):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        for member in PlayerClass:
            if key in (member.value.lower(), member.name.lower()):
                return member
    return None


def _class_of(obj: Any) -> PlayerClass | None:
    if obj is None:
        return None
    return _coerce_class(obj) or _coerce_class(_get(obj, _CLASS_ATTRS))


def _hp_color(frac: float) -> Color:
    if frac > 0.5:
        return Pal.GREEN
    if frac > 0.25:
        return Pal.ORANGE
    return Pal.RED


def _ellipsize(text: str, font: pygame.font.Font, max_w: int) -> str:
    """Trim ``text`` with '...' so it fits ``max_w`` pixels (ASCII dots: font-safe)."""
    if max_w <= 0:
        return ""
    if font.size(text)[0] <= max_w:
        return text
    ell = "..."
    if font.size(ell)[0] > max_w:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid].rstrip() + ell)[0] <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ell


def _split_long(word: str, font: pygame.font.Font, max_w: int) -> list[str]:
    if font.size(word)[0] <= max_w:
        return [word]
    pieces: list[str] = []
    cur = ""
    for ch in word:
        if cur and font.size(cur + ch)[0] > max_w:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        pieces.append(cur)
    return pieces


def _wrap(text: str, font: pygame.font.Font, max_w: int) -> list[str]:
    """Greedy word wrap honouring ``\\n``; over-long words are broken by character."""
    max_w = max(1, max_w)
    out: list[str] = []
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            out.append("")
            continue
        line = ""
        for word in words:
            for piece in _split_long(word, font, max_w):
                trial = piece if not line else f"{line} {piece}"
                if font.size(trial)[0] <= max_w:
                    line = trial
                else:
                    if line:
                        out.append(line)
                    line = piece
        out.append(line)
    return out


def _visible_span(heights: Sequence[int], selected: int, avail: int) -> tuple[int, int]:
    """Half-open ``[start, end)`` row window that fits ``avail`` px and keeps ``selected`` in view."""
    n = len(heights)
    if n == 0:
        return 0, 0
    selected = max(0, min(selected, n - 1))
    start = 0
    while True:
        end, used = start, 0
        while end < n and used + heights[end] <= avail:
            used += heights[end]
            end += 1
        if end == start:
            end = min(n, start + 1)
        if selected >= end and start < selected:
            start += 1
            continue
        return start, end


# ---------------------------------------------------------------------------
# Normalised views of duck-typed game objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _ShopRow:
    name: str
    cost: int | None
    desc: str
    stock: int | None
    sold_out: bool


@dataclass(frozen=True, slots=True)
class _Actor:
    raw: Any
    name: str
    hp: float
    max_hp: float
    mp: float | None
    max_mp: float | None
    cls: PlayerClass | None
    statuses: tuple[str, ...]
    alive: bool
    is_boss: bool


def _shop_row(raw: Any, index: int) -> _ShopRow:
    fallback = f"Item {index + 1}"
    if isinstance(raw, str):
        return _ShopRow(raw, None, "", None, False)
    if isinstance(raw, (tuple, list)):
        name = str(raw[0]) if len(raw) > 0 else fallback
        cost = _opt_int(raw[1]) if len(raw) > 1 else None
        desc = str(raw[2]) if len(raw) > 2 and raw[2] is not None else ""
        return _ShopRow(name, cost, desc, None, False)
    name = _get(raw, ("name", "title", "label"))
    desc = _get(raw, ("description", "desc", "text", "blurb"))
    stock = _opt_int(_get(raw, ("stock", "quantity", "count", "remaining")))
    sold = bool(_get(raw, ("sold_out", "sold"), False)) or (stock is not None and stock <= 0)
    return _ShopRow(
        str(name) if name is not None else fallback,
        _opt_int(_get(raw, ("cost", "price", "gold"))),
        str(desc) if desc is not None else "",
        stock,
        sold,
    )


def _status_names(raw: Any) -> tuple[str, ...]:
    items = list(raw) if isinstance(raw, Mapping) else _seq(raw)
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            names.append(item)
        else:
            label = _get(item, ("name", "label", "kind"))
            if label is not None:
                names.append(str(getattr(label, "value", label)))
    return tuple(names)


def _actor(raw: Any, index: int, default_name: str) -> _Actor:
    hp = _num(_get(raw, ("hp", "health", "current_hp")), 0.0)
    max_hp = _num(_get(raw, ("max_hp", "maxhp", "hp_max", "max_health")), max(hp, 1.0))
    mp_raw = _get(raw, ("mp", "mana", "current_mp"))
    max_mp_raw = _get(raw, ("max_mp", "maxmp", "mp_max", "max_mana"))
    mp = _num(mp_raw) if mp_raw is not None else None
    max_mp = _num(max_mp_raw) if max_mp_raw is not None else None
    if mp is not None and (max_mp is None or max_mp <= 0):
        max_mp = max(mp, 1.0)
    if mp is None:
        max_mp = None
    alive_raw = _get(raw, ("alive", "is_alive"))
    name = _get(raw, ("name", "label"))
    return _Actor(
        raw=raw,
        name=str(name) if name is not None else f"{default_name} {index + 1}",
        hp=max(0.0, hp),
        max_hp=max(1.0, max_hp),
        mp=mp,
        max_mp=max_mp,
        cls=_class_of(raw),
        statuses=_status_names(_get(raw, ("statuses", "status_effects", "effects", "buffs"))),
        alive=bool(alive_raw) if alive_raw is not None else hp > 0,
        is_boss=bool(_get(raw, ("is_boss", "boss"), False)),
    )


def _is_marked(actor: _Actor, marker: Any) -> bool:
    if marker is None:
        return False
    if marker is actor.raw:
        return True
    return isinstance(marker, str) and marker == actor.name


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
class MenuRenderer:
    """Stateless-with-respect-to-gameplay UI painter (caches fonts and one background only).

    ``main_menu_items``: labels for the main menu; ``selected_index`` indexes this list 1:1.
    The first entry is treated as the "Continue" row and is dimmed when ``has_continue`` is False.

    ``pause_actions``: labels drawn first on the pause menu; the entries of ``slot_names``
    follow under a "Save Slots" header.  ``selected_index`` spans actions then slots.

    ``ticks``: millisecond clock used only for the selection pulse (inject for tests).
    """

    def __init__(
        self,
        main_menu_items: Sequence[str] | None = None,
        pause_actions: Sequence[str] | None = None,
        ticks: Callable[[], int] | None = None,
    ) -> None:
        self._main_items = self._validated_labels(main_menu_items, DEFAULT_MAIN_MENU_ITEMS, "main_menu_items", True)
        self._pause_actions = self._validated_labels(pause_actions, DEFAULT_PAUSE_ACTIONS, "pause_actions", False)
        self._ticks: Callable[[], int] = ticks if ticks is not None else pygame.time.get_ticks
        self._fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self._bg: tuple[tuple[int, int], pygame.Surface] | None = None
        # Per-call draw context (layout only, set by _begin).
        self._scale = 1.0
        self._ox = 0.0
        self._oy = 0.0

    # -- construction helpers ------------------------------------------------
    @staticmethod
    def _validated_labels(
        value: Sequence[str] | None, default: tuple[str, ...], name: str, require_non_empty: bool
    ) -> tuple[str, ...]:
        if value is None:
            return default
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise TypeError(f"{name} must be a sequence of strings")
        labels = tuple(value)
        if not all(isinstance(label, str) for label in labels):
            raise TypeError(f"{name} must contain only strings")
        if require_non_empty and not labels:
            raise ValueError(f"{name} must not be empty")
        return labels

    @staticmethod
    def _clamp_index(value: Any, count: int, name: str) -> int:
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an int, not bool")
        try:
            index = operator.index(value)
        except TypeError as exc:
            raise TypeError(f"{name} must be an int, got {type(value).__name__}") from exc
        return max(0, min(index, count - 1)) if count > 0 else 0

    # -- layout context --------------------------------------------------------
    def _begin(self, surface: pygame.Surface) -> None:
        if not isinstance(surface, pygame.Surface):
            raise TypeError("surface must be a pygame.Surface")
        width, height = surface.get_size()
        if width < 2 or height < 2:
            raise ValueError(f"surface too small to draw on: {width}x{height}")
        self._scale = min(width / SCREEN_W, height / SCREEN_H)
        self._ox = (width - SCREEN_W * self._scale) / 2.0
        self._oy = (height - SCREEN_H * self._scale) / 2.0

    def _u(self, value: float) -> int:
        return int(round(value * self._scale))

    def _pt(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(self._ox + x * self._scale)), int(round(self._oy + y * self._scale)))

    def _rect(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        left, top = self._pt(x, y)
        right, bottom = self._pt(x + w, y + h)
        return pygame.Rect(left, top, max(1, right - left), max(1, bottom - top))

    def _pulse(self) -> float:
        return math.sin(self._ticks() / 420.0) * 0.5 + 0.5

    def _font(self, size: float, bold: bool = False) -> pygame.font.Font:
        px = max(9, int(round(size * self._scale)))
        key = (px, bold)
        font = self._fonts.get(key)
        if font is None:
            if not pygame.font.get_init():
                pygame.font.init()
            font = pygame.font.SysFont(FONT_FALLBACKS, px, bold=bold)
            self._fonts[key] = font
        return font

    # -- text ------------------------------------------------------------------
    def _text(
        self,
        surface: pygame.Surface,
        text: Any,
        size: float,
        color: Color,
        pos: tuple[int, int],
        *,
        bold: bool = False,
        anchor: str = "topleft",
        max_w: int | None = None,
        shadow: bool = True,
        glow: Color | None = None,
    ) -> pygame.Rect:
        font = self._font(size, bold)
        content = str(text)
        if max_w is not None:
            content = _ellipsize(content, font, max_w)
        if not content:
            return pygame.Rect(pos, (0, 0))
        image = font.render(content, True, color)
        rect = image.get_rect(**{anchor: pos})
        if glow is not None:
            halo = font.render(content, True, glow)
            halo.set_alpha(70)
            d = max(1, self._u(3))
            for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d), (-d, -d), (d, d), (-d, d), (d, -d)):
                surface.blit(halo, rect.move(dx, dy))
        if shadow:
            dark = font.render(content, True, Pal.BLACK)
            dark.set_alpha(160)
            surface.blit(dark, rect.move(max(1, self._u(2)), max(1, self._u(2))))
        surface.blit(image, rect)
        return rect

    def _paragraph(
        self,
        surface: pygame.Surface,
        text: str,
        size: float,
        color: Color,
        rect: pygame.Rect,
        *,
        bold: bool = False,
        gap: int | None = None,
        centered: bool = False,
    ) -> int:
        """Wrap ``text`` into ``rect`` (ellipsised if it overflows); returns the bottom y used."""
        font = self._font(size, bold)
        line_h = font.get_linesize()
        gap = self._u(3) if gap is None else gap
        lines = _wrap(text, font, rect.w)
        cap = max(1, (rect.h + gap) // (line_h + gap))
        if len(lines) > cap:
            lines = lines[:cap]
            lines[-1] = _ellipsize(lines[-1].rstrip() + " ...", font, rect.w)
        y = rect.y
        for line in lines:
            if line:
                if centered:
                    self._text(surface, line, size, color, (rect.centerx, y), bold=bold, anchor="midtop")
                else:
                    self._text(surface, line, size, color, (rect.x, y), bold=bold)
            y += line_h + gap
        return y - gap

    # -- primitives --------------------------------------------------------------
    def _diamond(self, surface: pygame.Surface, center: tuple[int, int], r: int, color: Color) -> None:
        cx, cy = center
        pygame.draw.polygon(surface, color, [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)])

    def _arrow(self, surface: pygame.Surface, center: tuple[int, int], r: int, direction: int, color: Color) -> None:
        cx, cy = center
        d = 1 if direction >= 0 else -1
        pygame.draw.polygon(surface, color, [(cx + d * r, cy), (cx - d * r, cy - r), (cx - d * r, cy + r)])

    def _coin(self, surface: pygame.Surface, center: tuple[int, int], r: int) -> None:
        pygame.draw.circle(surface, Pal.GOLD, center, r)
        pygame.draw.circle(surface, _shade(Pal.GOLD, 0.6), center, r, max(1, r // 4))
        pygame.draw.circle(surface, _mix(Pal.GOLD, Pal.WHITE, 0.4), (center[0] - r // 4, center[1] - r // 4), max(1, r // 4))

    def _corners(self, surface: pygame.Surface, rect: pygame.Rect, color: Color) -> None:
        n = self._u(14)
        o = self._u(4)
        w = max(1, self._u(2))
        l, t, r, b = rect.left + o, rect.top + o, rect.right - o - 1, rect.bottom - o - 1
        for (x, y, dx, dy) in ((l, t, 1, 1), (r, t, -1, 1), (l, b, 1, -1), (r, b, -1, -1)):
            pygame.draw.line(surface, color, (x, y), (x + dx * n, y), w)
            pygame.draw.line(surface, color, (x, y), (x, y + dy * n), w)
            self._diamond(surface, (x + dx * self._u(3), y + dy * self._u(3)), max(2, self._u(3)), color)

    def _glow(self, surface: pygame.Surface, rect: pygame.Rect, color: Color, spread: float = 10.0) -> None:
        g = max(2, self._u(spread))
        steps = 4
        layer = pygame.Surface((rect.w + 2 * g, rect.h + 2 * g), pygame.SRCALPHA)
        pulse = self._pulse()
        for i in range(steps):
            alpha = int((26 + 34 * pulse) * (1 - i / steps))
            grow = g - (i * g) // steps
            box = pygame.Rect(g - grow, g - grow, rect.w + 2 * grow, rect.h + 2 * grow)
            pygame.draw.rect(layer, (*color, alpha), box, width=max(1, g // steps + 1), border_radius=self._u(10) + grow)
        surface.blit(layer, (rect.x - g, rect.y - g))

    def _panel(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        border: Color = Pal.EDGE,
        fill: Color = Pal.PANEL,
        alpha: int = 236,
        ornaments: Color | None = None,
    ) -> None:
        radius = self._u(8)
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, (*fill, alpha), layer.get_rect(), border_radius=radius)
        surface.blit(layer, rect.topleft)
        pygame.draw.rect(surface, border, rect, width=max(1, self._u(2)), border_radius=radius)
        inner = rect.inflate(-self._u(10), -self._u(10))
        if inner.w > 4 and inner.h > 4:
            pygame.draw.rect(surface, _shade(border, 0.55), inner, width=1, border_radius=max(1, radius - 2))
        if ornaments is not None:
            self._corners(surface, rect, ornaments)

    def _bar(self, surface: pygame.Surface, rect: pygame.Rect, frac: float, color: Color) -> None:
        frac = _clamp01(frac)
        radius = max(1, rect.h // 3)
        pygame.draw.rect(surface, (28, 23, 40), rect, border_radius=radius)
        if frac > 0:
            fill = pygame.Rect(rect.x, rect.y, max(2, int(rect.w * frac)), rect.h)
            pygame.draw.rect(surface, color, fill, border_radius=radius)
            shine = pygame.Rect(fill.x, fill.y, fill.w, max(1, fill.h // 3))
            pygame.draw.rect(surface, _mix(color, Pal.WHITE, 0.28), shine, border_radius=radius)
        pygame.draw.rect(surface, Pal.EDGE, rect, width=1, border_radius=radius)

    def _chip(self, surface: pygame.Surface, text: str, topleft: tuple[int, int], color: Color, size: float = 13) -> pygame.Rect:
        font = self._font(size)
        pad = self._u(6)
        w = font.size(text)[0] + 2 * pad
        rect = pygame.Rect(topleft, (w, font.get_linesize() + self._u(2)))
        pygame.draw.rect(surface, _shade(color, 0.28), rect, border_radius=self._u(5))
        pygame.draw.rect(surface, color, rect, width=1, border_radius=self._u(5))
        self._text(surface, text, size, _mix(color, Pal.WHITE, 0.35), rect.center, anchor="center", shadow=False)
        return rect

    def _divider(self, surface: pygame.Surface, cx: int, y: int, half_w: int, color: Color = Pal.EDGE) -> None:
        gap = self._u(14)
        w = max(1, self._u(2))
        pygame.draw.line(surface, color, (cx - half_w, y), (cx - gap, y), w)
        pygame.draw.line(surface, color, (cx + gap, y), (cx + half_w, y), w)
        self._diamond(surface, (cx, y), max(3, self._u(6)), Pal.GOLD)

    def _button(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        *,
        selected: bool,
        enabled: bool = True,
        sub: str | None = None,
        accent: Color = Pal.GOLD,
        size: float = 24,
    ) -> None:
        if selected and enabled:
            self._glow(surface, rect, accent)
            fill, border, color = _mix(Pal.PANEL, accent, 0.2), accent, _mix(accent, Pal.WHITE, 0.45)
        elif selected:
            fill, border, color = Pal.PANEL, Pal.DIM, Pal.DIM
        else:
            fill = Pal.PANEL
            border = Pal.EDGE if enabled else _shade(Pal.EDGE, 0.6)
            color = Pal.TEXT if enabled else _shade(Pal.DIM, 0.8)
        self._panel(surface, rect, border=border, fill=fill, alpha=240)
        pad = self._u(44)
        if selected:
            r = max(3, self._u(6))
            self._diamond(surface, (rect.left + self._u(22), rect.centery), r, border)
            self._diamond(surface, (rect.right - self._u(22), rect.centery), r, border)
        if sub:
            self._text(surface, label, size, color, (rect.left + pad, rect.centery), anchor="midleft", bold=selected, max_w=rect.w // 2)
            self._text(surface, sub, size * 0.62, Pal.DIM, (rect.right - pad, rect.centery), anchor="midright", max_w=rect.w // 2 - pad, shadow=False)
        else:
            self._text(surface, label, size, color, rect.center, anchor="center", bold=selected, max_w=rect.w - 2 * pad)

    def _background(self, surface: pygame.Surface) -> None:
        size = surface.get_size()
        if self._bg is None or self._bg[0] != size:
            self._bg = (size, self._build_background(size))
        surface.blit(self._bg[1], (0, 0))

    def _build_background(self, size: tuple[int, int]) -> pygame.Surface:
        w, h = size
        bg = pygame.Surface(size)
        top, bottom = Pal.BG, _mix(Pal.BG, Pal.PURPLE, 0.12)
        for y in range(h):
            pygame.draw.line(bg, _mix(top, bottom, y / (h - 1)), (0, y), (w, y))
        layer = pygame.Surface(size, pygame.SRCALPHA)
        cx, cy = self._pt(SCREEN_W / 2, SCREEN_H * 0.47)
        for i, radius in enumerate((150, 230, 310, 400)):
            pygame.draw.circle(layer, (*Pal.EDGE, 34 - i * 5), (cx, cy), self._u(radius), max(1, self._u(2)))
        for k in range(12):  # sigil spokes
            ang = k * math.tau / 12
            p1 = (cx + int(math.cos(ang) * self._u(150)), cy + int(math.sin(ang) * self._u(150)))
            p2 = (cx + int(math.cos(ang) * self._u(400)), cy + int(math.sin(ang) * self._u(400)))
            pygame.draw.line(layer, (*Pal.EDGE, 18), p1, p2, 1)
        link_h, link_w = max(6, self._u(28)), max(4, self._u(15))
        stroke = max(1, self._u(2))
        for x in (self._pt(86, 0)[0], self._pt(SCREEN_W - 86, 0)[0]):
            y, i = -link_h, 0
            while y < h:
                lw = link_w if i % 2 == 0 else max(2, link_w // 3)
                pygame.draw.ellipse(layer, (*Pal.EDGE, 64), pygame.Rect(x - lw // 2, y, lw, link_h), stroke)
                y += int(link_h * 0.78)
                i += 1
        rng = random.Random(0x5EED_AB55)
        for _ in range(max(10, (w * h) // 7000)):
            px, py = rng.randrange(w), rng.randrange(h)
            alpha = rng.randrange(20, 90)
            pygame.draw.circle(layer, (*Pal.DIM, alpha), (px, py), 1 if rng.random() < 0.85 else 2)
        steps = 24
        band = max(2, min(w, h) // 60)
        for i in range(steps):
            if w - 2 * i * band < 1 or h - 2 * i * band < 1:
                break
            alpha = int(125 * (1 - i / steps) ** 2)
            pygame.draw.rect(layer, (0, 0, 0, alpha), pygame.Rect(i * band, i * band, w - 2 * i * band, h - 2 * i * band), width=band)
        bg.blit(layer, (0, 0))
        return bg

    def _emblem(self, surface: pygame.Surface, kind: PlayerClass, center: tuple[int, int], r: int, color: Color) -> None:
        cx, cy = center

        def p(dx: float, dy: float) -> tuple[int, int]:
            return (cx + int(dx * r), cy + int(dy * r))

        pygame.draw.circle(surface, _shade(color, 0.22), center, r)
        pygame.draw.circle(surface, color, center, r, max(2, self._u(3)))
        pygame.draw.circle(surface, _shade(color, 0.55), center, int(r * 0.86), 1)
        poly = pygame.draw.polygon
        if kind is PlayerClass.WARRIOR:
            poly(surface, color, [p(-.08, .35), p(-.08, -.45), p(0, -.64), p(.08, -.45), p(.08, .35)])
            poly(surface, color, [p(-.3, .35), p(.3, .35), p(.3, .45), p(-.3, .45)])
            poly(surface, color, [p(-.05, .45), p(.05, .45), p(.05, .66), p(-.05, .66)])
        elif kind is PlayerClass.TANK:
            poly(surface, color, [p(-.46, -.46), p(.46, -.46), p(.46, .05), p(0, .7), p(-.46, .05)])
            poly(surface, _shade(color, 0.3), [p(-.3, -.32), p(.3, -.32), p(.3, .0), p(0, .46), p(-.3, .0)])
            poly(surface, color, [p(-.05, -.3), p(.05, -.3), p(.05, .3), p(-.05, .3)])
        elif kind is PlayerClass.ROGUE:
            poly(surface, color, [p(0, -.72), p(.2, 0), p(0, .3), p(-.2, 0)])
            pygame.draw.line(surface, color, p(-.26, .3), p(.26, .3), max(2, self._u(3)))
            pygame.draw.line(surface, color, p(0, .3), p(0, .66), max(2, self._u(3)))
        elif kind is PlayerClass.WITCH:
            poly(surface, color, [p(0, -.76), p(.3, .2), p(-.3, .2)])
            poly(surface, color, [p(-.64, .26), p(.64, .26), p(.5, .42), p(-.5, .42)])
            poly(surface, _shade(color, 0.3), [p(-.28, .08), p(.28, .08), p(.3, .2), p(-.3, .2)])
        else:  # Fallen Angel
            for s in (-1, 1):
                poly(surface, color, [p(s * .06, 0), p(s * .7, -.38), p(s * .56, .04), p(s * .66, .3), p(s * .06, .36)])
            pygame.draw.ellipse(surface, color, pygame.Rect(p(-.26, -.78), (int(.52 * r), max(2, int(.2 * r)))), max(1, self._u(2)))
            pygame.draw.circle(surface, color, p(0, .02), max(2, int(.14 * r)))

    # =========================================================================
    # Screens
    # =========================================================================
    def draw_main_menu(self, surface: pygame.Surface, selected_index: int, has_continue: bool) -> None:
        """Title screen.  ``selected_index`` indexes ``main_menu_items``; row 0 is "Continue"."""
        self._begin(surface)
        index = self._clamp_index(selected_index, len(self._main_items), "selected_index")
        self._background(surface)

        title_font = self._font(68, True)
        y = self._pt(0, 92)[1]
        for line in _wrap(TITLE, title_font, self._u(1120)):
            rect = self._text(surface, line, 68, Pal.GOLD, (self._pt(SCREEN_W / 2, 0)[0], y), bold=True, anchor="midtop", glow=Pal.PURPLE)
            y = rect.bottom + self._u(4)
        y += self._u(6)
        self._text(surface, "Descend. Endure. Break the chains.", 22, Pal.DIM, (self._pt(SCREEN_W / 2, 0)[0], y), anchor="midtop")
        y += self._font(22).get_linesize() + self._u(18)
        self._divider(surface, self._pt(SCREEN_W / 2, 0)[0], y, self._u(260), Pal.EDGE)

        n = len(self._main_items)
        top = max(self._pt(0, 340)[1], y + self._u(44))
        gap = self._u(14)
        avail = surface.get_height() - top - self._u(70)
        btn_h = max(self._u(24), min(self._u(58), (avail - gap * (n - 1)) // n))
        btn_w = self._u(400)
        left = self._pt(SCREEN_W / 2, 0)[0] - btn_w // 2
        for i, label in enumerate(self._main_items):
            rect = pygame.Rect(left, top + i * (btn_h + gap), btn_w, btn_h)
            enabled = has_continue or i != 0
            self._button(surface, rect, label, selected=i == index, enabled=enabled, sub=None if enabled else "No save found")
        self._text(
            surface, "The Abyss never ends.", 16, _shade(Pal.DIM, 0.8),
            (self._pt(SCREEN_W / 2, 0)[0], self._pt(0, SCREEN_H - 26)[1]), anchor="midtop", shadow=False,
        )

    def draw_party_select(
        self,
        surface: pygame.Surface,
        configs: Sequence[Any],
        selected_slot: int,
        available_classes: Sequence[PlayerClass],
    ) -> None:
        """Party builder.  ``configs`` holds up to ``MAX_PARTY`` entries, each a ``PlayerClass``,
        ``None`` (empty slot) or an object/mapping with a class under ``player_class``/``cls``/...
        and an optional ``name``.  Missing trailing entries are drawn as empty slots."""
        self._begin(surface)
        if isinstance(configs, (str, bytes, Mapping)) or not isinstance(configs, Iterable):
            raise TypeError("configs must be a sequence")
        slots = list(configs)[:MAX_PARTY]
        if isinstance(available_classes, (str, bytes, Mapping)) or not isinstance(available_classes, Iterable):
            raise TypeError("available_classes must be a sequence of PlayerClass")
        classes = [c for c in available_classes if isinstance(c, PlayerClass)]
        slot = self._clamp_index(selected_slot, MAX_PARTY, "selected_slot")
        self._background(surface)

        cx = self._pt(SCREEN_W / 2, 0)[0]
        filled = sum(1 for cfg in slots if _class_of(cfg) is not None)
        self._text(surface, "Assemble Your Party", 44, Pal.GOLD, (cx, self._pt(0, 34)[1]), bold=True, anchor="midtop", glow=Pal.PURPLE)
        self._text(surface, f"Party {filled}/{MAX_PARTY}", 20, Pal.DIM, (cx, self._pt(0, 92)[1]), anchor="midtop")

        margin, gap = 60.0, 28.0
        card_w = (SCREEN_W - 2 * margin - gap * (MAX_PARTY - 1)) / MAX_PARTY
        for i in range(MAX_PARTY):
            cfg = slots[i] if i < len(slots) else None
            rect = self._rect(margin + i * (card_w + gap), 130, card_w, 400)
            self._party_card(surface, rect, i, cfg, i == slot, len(classes) > 1)

        strip = self._rect(margin, 556, SCREEN_W - 2 * margin, 124)
        self._panel(surface, strip, ornaments=Pal.GOLD)
        self._text(surface, "Available Classes", 18, Pal.DIM, (strip.left + self._u(24), strip.top + self._u(14)))
        current = _class_of(slots[slot]) if slot < len(slots) else None
        if not classes:
            self._text(surface, "No classes available.", 20, Pal.DIM, strip.center, anchor="center")
            return
        inner_w = strip.w - self._u(48)
        chip_gap = self._u(12)
        chip_w = min(self._u(220), (inner_w - chip_gap * (len(classes) - 1)) // len(classes))
        chip_h = self._u(46)
        x0 = strip.centerx - (chip_w * len(classes) + chip_gap * (len(classes) - 1)) // 2
        for k, cls in enumerate(classes):
            color = CLASS_COLORS[cls]
            rect = pygame.Rect(x0 + k * (chip_w + chip_gap), strip.top + self._u(52), chip_w, chip_h)
            on = cls is current
            pygame.draw.rect(surface, _shade(color, 0.35 if on else 0.18), rect, border_radius=self._u(8))
            pygame.draw.rect(surface, color if on else _shade(color, 0.55), rect, width=max(1, self._u(3 if on else 1)), border_radius=self._u(8))
            self._text(surface, cls.value, 19, Pal.WHITE if on else Pal.TEXT, rect.center, anchor="center", bold=on, max_w=rect.w - self._u(12), shadow=False)

    def _party_card(self, surface: pygame.Surface, rect: pygame.Rect, index: int, cfg: Any, selected: bool, can_cycle: bool) -> None:
        cls = _class_of(cfg)
        color = CLASS_COLORS[cls] if cls is not None else Pal.EDGE
        accent = color if cls is not None else Pal.GOLD
        if selected:
            self._glow(surface, rect, accent, 12)
        self._panel(
            surface, rect, border=accent if selected else _shade(color, 0.7),
            fill=_mix(Pal.PANEL, color, 0.12 if selected else 0.05), ornaments=Pal.GOLD if selected else None,
        )
        name = _get(cfg, ("name", "label", "hero_name")) if cls is not None else None
        title = str(name) if name else f"Slot {index + 1}"
        self._text(surface, title, 18, Pal.DIM, (rect.left + self._u(24), rect.top + self._u(20)), max_w=rect.w - self._u(48))
        emblem_c = (rect.centerx, rect.top + self._u(120))
        r = self._u(58)
        if cls is None:
            for k in range(0, 24, 2):
                a0, a1 = k * math.tau / 24, (k + 1) * math.tau / 24
                pygame.draw.line(
                    surface, Pal.EDGE,
                    (emblem_c[0] + int(math.cos(a0) * r), emblem_c[1] + int(math.sin(a0) * r)),
                    (emblem_c[0] + int(math.cos(a1) * r), emblem_c[1] + int(math.sin(a1) * r)), max(1, self._u(2)),
                )
            self._text(surface, "+", 56, Pal.EDGE, emblem_c, anchor="center", bold=True, shadow=False)
            self._text(surface, "Empty Slot", 28, Pal.DIM, (rect.centerx, rect.top + self._u(206)), anchor="midtop", bold=True)
            self._text(surface, "No hero chosen", 17, _shade(Pal.DIM, 0.8), (rect.centerx, rect.top + self._u(248)), anchor="midtop", shadow=False)
        else:
            self._emblem(surface, cls, emblem_c, r, color)
            self._text(surface, cls.value, 30, color, (rect.centerx, rect.top + self._u(196)), anchor="midtop", bold=True, max_w=rect.w - self._u(40))
            body = pygame.Rect(rect.left + self._u(26), rect.top + self._u(246), rect.w - self._u(52), rect.h - self._u(268))
            self._paragraph(surface, CLASS_BLURBS.get(cls, ""), 17, Pal.TEXT, body, centered=True)
        if selected and can_cycle:
            ay = emblem_c[1]
            self._arrow(surface, (rect.left + self._u(30), ay), self._u(10), -1, accent)
            self._arrow(surface, (rect.right - self._u(30), ay), self._u(10), 1, accent)

    def draw_difficulty(self, surface: pygame.Surface, selected_name: str) -> None:
        """Difficulty picker listing ``core.config.DIFFICULTIES``; ``selected_name`` must be a key."""
        self._begin(surface)
        if selected_name not in DIFFICULTIES:
            raise ValueError(f"unknown difficulty {selected_name!r}; expected one of {list(DIFFICULTIES)}")
        self._background(surface)
        cx = self._pt(SCREEN_W / 2, 0)[0]
        self._text(surface, "Select Difficulty", 46, Pal.GOLD, (cx, self._pt(0, 54)[1]), bold=True, anchor="midtop", glow=Pal.PURPLE)
        self._divider(surface, cx, self._pt(0, 124)[1], self._u(240))

        names = list(DIFFICULTIES)
        n = len(names)
        gap = 14.0
        avail = 720 - 160 - 70
        row_h = max(30.0, min(98.0, (avail - gap * (n - 1)) / n))
        top_mult = max(DIFFICULTIES.values())
        for i, name in enumerate(names):
            mult = DIFFICULTIES[name]
            t = i / (n - 1) if n > 1 else 0.0
            color = _mix(Pal.GREEN, Pal.GOLD, t * 2) if t < 0.5 else _mix(Pal.GOLD, Pal.RED, (t - 0.5) * 2)
            rect = self._rect(230, 160 + i * (row_h + gap), 820, row_h)
            sel = name == selected_name
            if sel:
                self._glow(surface, rect, color)
            self._panel(surface, rect, border=color if sel else Pal.EDGE, fill=_mix(Pal.PANEL, color, 0.16 if sel else 0.0), ornaments=Pal.GOLD if sel else None)
            if sel:
                self._diamond(surface, (rect.left + self._u(26), rect.centery), max(3, self._u(7)), color)
            tag = _DIFFICULTY_TAGLINES.get(name, f"Enemy stats x{mult:.2f}")
            tx = rect.left + self._u(52)
            name_rect = self._text(surface, name, 30, _mix(color, Pal.WHITE, 0.4) if sel else Pal.TEXT, (tx, rect.top + self._u(row_h * 0.14)), bold=True, max_w=rect.w // 2)
            self._text(surface, tag, 17, Pal.DIM, (tx, name_rect.bottom + self._u(4)), max_w=rect.w // 2 + self._u(40), shadow=False)
            bar = pygame.Rect(rect.right - self._u(230), rect.centery + self._u(4), self._u(180), max(4, self._u(12)))
            self._text(surface, f"Enemy stats x{mult:.2f}", 16, Pal.TEXT if sel else Pal.DIM, (bar.right, bar.top - self._u(6)), anchor="bottomright", shadow=False)
            self._bar(surface, bar, mult / top_mult if top_mult > 0 else 0.0, color)

    def draw_shop(self, surface: pygame.Surface, shop: Any, gold: int) -> None:
        """Shop screen.  ``shop`` is a sequence of items or an object/mapping exposing
        ``items`` (also ``stock``/``inventory``/``wares``), optional ``title`` and the highlighted
        row under ``selected``/``selected_index``/``cursor``/``index``.  An item is a string,
        a ``(name, cost[, description])`` tuple, or an object/mapping with ``name``,
        ``cost``/``price``, ``description``, ``stock`` and ``sold_out``."""
        self._begin(surface)
        if isinstance(gold, bool) or not isinstance(gold, (int, float)) or not math.isfinite(gold):
            raise TypeError("gold must be a finite number")
        wallet = max(0, int(gold))
        if isinstance(shop, (list, tuple)):
            raw_items, raw_sel, title = list(shop), 0, "Merchant"
        else:
            raw_items = _seq(_get(shop, ("items", "stock", "inventory", "wares")))
            raw_sel = _opt_int(_get(shop, ("selected", "selected_index", "cursor", "index"))) or 0
            title = str(_get(shop, ("title", "name"), "Merchant"))
        rows = [_shop_row(raw, i) for i, raw in enumerate(raw_items)]
        sel = max(0, min(raw_sel, len(rows) - 1)) if rows else 0
        self._background(surface)

        self._text(surface, title, 40, Pal.GOLD, self._pt(60, 34), bold=True, glow=Pal.PURPLE, max_w=self._u(700))
        gold_text = f"{wallet:,}"
        right = self._pt(SCREEN_W - 60, 0)[0]
        text_rect = self._text(surface, gold_text, 30, Pal.GOLD, (right, self._pt(0, 42)[1]), bold=True, anchor="topright")
        self._coin(surface, (text_rect.left - self._u(22), text_rect.centery), self._u(13))

        list_rect = self._rect(60, 112, 700, 560)
        self._panel(surface, list_rect, ornaments=Pal.GOLD)
        detail = self._rect(790, 112, 430, 560)
        self._panel(surface, detail, ornaments=Pal.GOLD)

        if not rows:
            self._text(surface, "The shelves are bare.", 24, Pal.DIM, list_rect.center, anchor="center")
            return

        pad, row_h, row_gap = self._u(18), self._u(62), self._u(8)
        pitch = row_h + row_gap
        avail = list_rect.h - 2 * pad + row_gap
        start, end = _visible_span([pitch] * len(rows), sel, avail)
        for slot, i in enumerate(range(start, end)):
            row = rows[i]
            rect = pygame.Rect(list_rect.left + pad, list_rect.top + pad + slot * pitch, list_rect.w - 2 * pad - self._u(14), row_h)
            on = i == sel
            afford = row.cost is not None and wallet >= row.cost and not row.sold_out
            if on:
                self._glow(surface, rect, Pal.GOLD, 6)
            self._panel(surface, rect, border=Pal.GOLD if on else Pal.EDGE, fill=_mix(Pal.PANEL, Pal.GOLD, 0.14 if on else 0.0), alpha=240)
            name_c = (_mix(Pal.GOLD, Pal.WHITE, 0.4) if on else Pal.TEXT) if not row.sold_out else Pal.DIM
            right_edge = rect.right - self._u(18)
            cost_w = self._u(120)
            if row.sold_out:
                self._text(surface, "SOLD OUT", 18, Pal.DIM, (right_edge, rect.centery), anchor="midright", bold=True, shadow=False)
            elif row.cost is not None:
                cr = self._text(surface, f"{row.cost:,}", 22, Pal.GOLD if afford else Pal.RED, (right_edge, rect.centery), anchor="midright", bold=True, shadow=False)
                self._coin(surface, (cr.left - self._u(14), cr.centery), self._u(8))
                cost_w = cr.w + self._u(50)
            label_w = rect.w - cost_w - self._u(36)
            if row.stock is not None and not row.sold_out:
                self._text(surface, row.name, 22, name_c, (rect.left + self._u(18), rect.top + self._u(10)), bold=on, max_w=label_w)
                self._text(surface, f"In stock: {row.stock}", 15, Pal.DIM, (rect.left + self._u(18), rect.top + self._u(36)), shadow=False, max_w=label_w)
            else:
                self._text(surface, row.name, 22, name_c, (rect.left + self._u(18), rect.centery), anchor="midleft", bold=on, max_w=label_w)
        track = pygame.Rect(list_rect.right - pad, list_rect.top + pad, self._u(6), list_rect.h - 2 * pad)
        if end - start < len(rows):
            pygame.draw.rect(surface, (28, 23, 40), track, border_radius=self._u(3))
            th = max(self._u(24), track.h * (end - start) // len(rows))
            ty = track.top + (track.h - th) * start // max(1, len(rows) - (end - start))
            pygame.draw.rect(surface, Pal.EDGE, pygame.Rect(track.left, ty, track.w, th), border_radius=self._u(3))

        chosen = rows[sel]
        x, w = detail.left + self._u(26), detail.w - self._u(52)
        y = self._paragraph(surface, chosen.name, 30, Pal.GOLD, pygame.Rect(x, detail.top + self._u(26), w, self._u(90)), bold=True) + self._u(14)
        self._divider(surface, detail.centerx, y, w // 2)
        y += self._u(22)
        body = pygame.Rect(x, y, w, detail.bottom - y - self._u(130))
        self._paragraph(surface, chosen.desc or "No description.", 19, Pal.TEXT if chosen.desc else Pal.DIM, body)
        foot = detail.bottom - self._u(112)
        self._divider(surface, detail.centerx, foot - self._u(10), w // 2)
        if chosen.sold_out:
            status, status_c = "Sold out", Pal.DIM
        elif chosen.cost is None:
            status, status_c = "Not for sale", Pal.DIM
        elif wallet >= chosen.cost:
            status, status_c = "Affordable", Pal.GREEN
        else:
            status, status_c = f"Need {chosen.cost - wallet:,} more gold", Pal.RED
        if chosen.cost is not None:
            self._text(surface, "Price", 17, Pal.DIM, (x, foot + self._u(4)))
            pr = self._text(surface, f"{chosen.cost:,}", 26, Pal.GOLD, (x + w, foot), anchor="topright", bold=True)
            self._coin(surface, (pr.left - self._u(18), pr.centery), self._u(10))
        self._text(surface, status, 20, status_c, (x, foot + self._u(48)), bold=True, max_w=w)

    def draw_hud(self, surface: pygame.Surface, state: Any, combat: Any | None) -> None:
        """In-run overlay; does not clear the surface.  Everything is optional / duck-typed:

        ``state``: ``stage`` (int), ``gold``, ``party`` (or ``players``/``heroes``), ``difficulty``,
        ``round``.  ``combat`` (may be ``None``): ``enemies``, ``log`` (strings, oldest first),
        ``active`` and ``target`` (actor object or name), ``round``, ``message``.
        Actors expose ``name``, ``hp``, ``max_hp``, ``mp``, ``max_mp``, ``alive``, ``is_boss``,
        ``statuses`` and a class under ``player_class``/``cls``.
        """
        self._begin(surface)
        party = [_actor(raw, i, "Hero") for i, raw in enumerate(_seq(_get(state, ("party", "players", "heroes"))))]
        enemy_raw = _seq(_get(combat, ("enemies", "foes", "monsters")))
        if not enemy_raw and combat is not None:
            enemy_raw = _seq(_get(state, ("enemies", "foes", "monsters")))
        enemies = [_actor(raw, i, "Enemy") for i, raw in enumerate(enemy_raw)]
        active = _get(combat, ("active", "active_actor", "current_actor", "actor"))
        target = _get(combat, ("target", "selected_target"))

        self._hud_top(surface, state, combat, active, party, enemies)
        message = _get(combat, ("message", "prompt", "banner"))
        if message:
            self._text(surface, message, 24, Pal.GOLD, (self._pt(SCREEN_W / 2, 0)[0], self._pt(0, 84)[1]), anchor="midtop", bold=True, max_w=self._u(1000))
        self._hud_enemies(surface, enemies, active, target)
        self._hud_party(surface, party, active)
        self._hud_log(surface, [str(line) for line in _seq(_get(combat, ("log", "messages", "history")))])

    def _hud_top(self, surface: pygame.Surface, state: Any, combat: Any | None, active: Any, party: list[_Actor], enemies: list[_Actor]) -> None:
        bar = self._rect(16, 12, SCREEN_W - 32, 54)
        self._panel(surface, bar, alpha=225)
        stage = _opt_int(_get(state, ("stage", "stage_number", "current_stage")))
        label = f"Stage {stage}" if stage is not None else "Stage -"
        left = self._text(surface, label, 26, Pal.GOLD, (bar.left + self._u(22), bar.centery), anchor="midleft", bold=True)
        x = left.right + self._u(14)
        if stage is not None and stage >= 1:
            if is_boss_stage(stage):
                x = self._chip(surface, "BOSS", (x, bar.centery - self._u(11)), Pal.RED).right + self._u(8)
            if is_endless_stage(stage):
                x = self._chip(surface, "ENDLESS", (x, bar.centery - self._u(11)), Pal.PURPLE).right + self._u(8)
        diff = _get(state, ("difficulty", "difficulty_name"))
        if diff:
            self._text(surface, str(getattr(diff, "value", diff)), 17, Pal.DIM, (x + self._u(4), bar.centery), anchor="midleft", shadow=False, max_w=self._u(160))
        rnd = _opt_int(_get(combat, ("round", "turn", "turn_number", "round_number")))
        if rnd is None:
            rnd = _opt_int(_get(state, ("round", "turn", "turn_number", "round_number")))
        who = next((a.name for a in party + enemies if _is_marked(a, active)), None)
        if who is None and isinstance(active, str):
            who = active
        center_bits = []
        if rnd is not None:
            center_bits.append(f"Round {rnd}")
        if who:
            center_bits.append(f"{who}'s turn")
        if center_bits:
            self._text(surface, "  -  ".join(center_bits), 21, Pal.TEXT, bar.center, anchor="center", max_w=self._u(420))
        gold = _opt_int(_get(state, ("gold", "money", "coins")))
        if gold is not None:
            t = self._text(surface, f"{max(0, gold):,}", 24, Pal.GOLD, (bar.right - self._u(24), bar.centery), anchor="midright", bold=True)
            self._coin(surface, (t.left - self._u(18), t.centery), self._u(10))

    def _hud_enemies(self, surface: pygame.Surface, enemies: list[_Actor], active: Any, target: Any) -> None:
        if not enemies:
            return
        shown, extra = enemies[:6], max(0, len(enemies) - 6)
        gap = 16.0
        avail = SCREEN_W - 64
        card_w = min(250.0, (avail - gap * (len(shown) - 1)) / len(shown))
        boss_w = min(card_w * 1.25, 320.0)
        widths = [boss_w if e.is_boss else card_w for e in shown]
        total = sum(widths) + gap * (len(shown) - 1)
        x = (SCREEN_W - total) / 2
        top = 118.0
        for e, w in zip(shown, widths):
            h = 104.0 if e.is_boss else 92.0
            rect = self._rect(x, top, w, h)
            x += w + gap
            marked = _is_marked(e, target)
            acting = _is_marked(e, active)
            base = Pal.GOLD if e.is_boss else Pal.RED
            if marked or acting:
                self._glow(surface, rect, Pal.GOLD, 8)
            self._panel(surface, rect, border=Pal.GOLD if (marked or acting) else _shade(base, 0.7), fill=_mix(Pal.PANEL, Pal.RED, 0.1), alpha=225)
            pad = self._u(14)
            name_c = Pal.DIM if not e.alive else (Pal.GOLD if e.is_boss else Pal.TEXT)
            self._text(surface, e.name, 20 if e.is_boss else 18, name_c, (rect.left + pad, rect.top + self._u(10)), bold=True, max_w=rect.w - 2 * pad)
            frac = e.hp / e.max_hp
            bar = pygame.Rect(rect.left + pad, rect.top + self._u(40), rect.w - 2 * pad, self._u(14))
            self._bar(surface, bar, frac, Pal.RED if e.alive else Pal.DIM)
            self._text(surface, f"{int(math.ceil(e.hp)):,}/{int(e.max_hp):,}" if e.alive else "DEFEATED", 14, Pal.DIM, (rect.left + pad, bar.bottom + self._u(4)), shadow=False, max_w=rect.w - 2 * pad)
            self._status_chips(surface, e.statuses, (rect.left + pad, rect.bottom - self._u(26)), rect.w - 2 * pad, Pal.PURPLE)
        if extra:
            self._text(surface, f"+{extra} more", 16, Pal.DIM, self._pt(SCREEN_W - 40, 240), anchor="topright", shadow=False)

    def _status_chips(self, surface: pygame.Surface, names: Sequence[str], pos: tuple[int, int], max_w: int, color: Color) -> None:
        x, y = pos
        right = pos[0] + max_w
        for i, name in enumerate(names):
            remaining = len(names) - i
            font = self._font(13)
            width = font.size(name)[0] + self._u(12)
            more = f"+{remaining}"
            reserve = font.size(more)[0] + self._u(16) if remaining > 1 else 0
            if x + width + reserve > right and i > 0:
                self._chip(surface, more, (x, y), Pal.DIM)
                return
            if x + width > right:
                name = _ellipsize(name, font, max(1, right - x - self._u(12)))
                if not name:
                    return
                width = font.size(name)[0] + self._u(12)
            x = self._chip(surface, name, (x, y), color).right + self._u(5)

    def _hud_party(self, surface: pygame.Surface, party: list[_Actor], active: Any) -> None:
        panel = self._rect(16, 534, 842, 174)
        self._panel(surface, panel, alpha=225)
        if not party:
            return
        shown = party[:6]
        gap = 10.0
        inner_w = 842 - 24
        card_w = min(274.0, (inner_w - gap * (len(shown) - 1)) / len(shown))
        total = card_w * len(shown) + gap * (len(shown) - 1)
        x = 16 + (842 - total) / 2
        for actor in shown:
            rect = self._rect(x, 544, card_w, 154)
            x += card_w + gap
            color = CLASS_COLORS[actor.cls] if actor.cls is not None else Pal.EDGE
            acting = _is_marked(actor, active)
            if acting:
                self._glow(surface, rect, Pal.GOLD, 8)
            self._panel(surface, rect, border=Pal.GOLD if acting else _shade(color, 0.75), fill=_mix(Pal.PANEL, color, 0.1), alpha=240)
            pygame.draw.rect(surface, color, pygame.Rect(rect.left + self._u(10), rect.top + self._u(6), rect.w - self._u(20), max(2, self._u(3))), border_radius=self._u(2))
            pad = self._u(14)
            inner = rect.w - 2 * pad
            top = rect.top + self._u(14)
            tag_w = 0
            if not actor.alive:
                tag_w = self._text(surface, "FALLEN", 13, Pal.RED, (rect.right - pad, top + self._u(3)), anchor="topright", bold=True, shadow=False).w + self._u(6)
            self._text(surface, actor.name, 19, Pal.TEXT if actor.alive else Pal.DIM, (rect.left + pad, top), bold=True, max_w=inner - tag_w)
            if actor.cls is not None:
                self._text(surface, actor.cls.value, 14, color, (rect.left + pad, top + self._u(24)), shadow=False, max_w=inner)
            hp_bar = pygame.Rect(rect.left + pad, rect.top + self._u(64), inner, self._u(15))
            frac = actor.hp / actor.max_hp
            self._bar(surface, hp_bar, frac, _hp_color(frac) if actor.alive else Pal.DIM)
            self._text(surface, f"HP {int(math.ceil(actor.hp)):,}/{int(actor.max_hp):,}", 14, Pal.TEXT, (hp_bar.left, hp_bar.bottom + self._u(2)), shadow=False, max_w=inner)
            if actor.mp is not None and actor.max_mp is not None:
                mp_bar = pygame.Rect(rect.left + pad, rect.top + self._u(104), inner, self._u(11))
                self._bar(surface, mp_bar, actor.mp / actor.max_mp, Pal.BLUE)
                self._text(surface, f"MP {int(actor.mp):,}/{int(actor.max_mp):,}", 13, Pal.DIM, (mp_bar.left, mp_bar.bottom + self._u(1)), shadow=False, max_w=inner)
            self._status_chips(surface, actor.statuses, (rect.left + pad, rect.bottom - self._u(26)), inner, Pal.CYAN)

    def _hud_log(self, surface: pygame.Surface, log: list[str]) -> None:
        panel = self._rect(872, 534, SCREEN_W - 872 - 16, 174)
        self._panel(surface, panel, alpha=225)
        pad = self._u(16)
        self._text(surface, "Chronicle", 15, Pal.DIM, (panel.left + pad, panel.top + self._u(10)), shadow=False)
        if not log:
            return
        font = self._font(16)
        line_h = font.get_linesize()
        area = pygame.Rect(panel.left + pad, panel.top + self._u(34), panel.w - 2 * pad, panel.h - self._u(46))
        cap = max(1, area.h // line_h)
        visual: list[tuple[str, int]] = []
        recent = log[-12:]
        for age, entry in enumerate(reversed(recent)):
            wrapped = _wrap(entry, font, area.w)
            for line in reversed(wrapped):
                visual.append((line, age))
            if len(visual) >= cap:
                break
        visual = visual[:cap]
        y = area.bottom - line_h
        for line, age in visual:
            color = _mix(Pal.TEXT, Pal.DIM, min(1.0, age * 0.28))
            if line:
                self._text(surface, line, 16, color, (area.left, y), shadow=False)
            y -= line_h

    def draw_pause(self, surface: pygame.Surface, selected_index: int, slot_names: Sequence[str | None]) -> None:
        """Pause overlay (dims whatever is already on ``surface``).  ``selected_index`` spans the
        pause actions first, then ``slot_names`` (``None``/blank renders as "Empty Slot")."""
        self._begin(surface)
        if isinstance(slot_names, (str, bytes, Mapping)) or not isinstance(slot_names, Iterable):
            raise TypeError("slot_names must be a sequence of strings")
        slots = [("" if s is None else str(s)).strip() or "Empty Slot" for s in slot_names]
        actions = list(self._pause_actions)
        total = len(actions) + len(slots)
        sel = self._clamp_index(selected_index, total, "selected_index")

        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        surface.blit(shade, (0, 0))

        # entries: (kind, label, logical index)
        entries: list[tuple[str, str, int]] = [("row", label, i) for i, label in enumerate(actions)]
        if slots:
            entries.append(("header", "Save Slots", -1))
            entries += [("slot", label, len(actions) + i) for i, label in enumerate(slots)]
        row_h, head_h, gap = self._u(52), self._u(30), self._u(10)
        heights = [(head_h if kind == "header" else row_h) + gap for kind, _, _ in entries]
        panel_w = self._u(560)
        title_h = self._u(92)
        pad = self._u(26)
        max_h = surface.get_height() - self._u(60)
        content_max = max(row_h, max_h - title_h - pad)
        selected_visual = next((k for k, e in enumerate(entries) if e[2] == sel), 0)
        start, end = _visible_span(heights, selected_visual, content_max + gap)
        used = sum(heights[start:end]) - gap
        panel_h = title_h + used + pad
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = (surface.get_width() // 2, surface.get_height() // 2)
        self._glow(surface, panel, Pal.PURPLE, 14)
        self._panel(surface, panel, ornaments=Pal.GOLD, alpha=245)
        self._text(surface, "Paused", 40, Pal.GOLD, (panel.centerx, panel.top + self._u(22)), bold=True, anchor="midtop", glow=Pal.PURPLE)
        self._divider(surface, panel.centerx, panel.top + self._u(78), panel_w // 2 - self._u(40))
        y = panel.top + title_h
        inner_w = panel_w - 2 * pad
        for k in range(start, end):
            kind, label, logical = entries[k]
            if kind == "header":
                self._text(surface, label.upper(), 15, Pal.DIM, (panel.left + pad + self._u(4), y + self._u(8)), shadow=False)
                pygame.draw.line(surface, Pal.EDGE, (panel.left + pad + self._u(110), y + head_h // 2 + self._u(4)), (panel.right - pad, y + head_h // 2 + self._u(4)), 1)
            else:
                rect = pygame.Rect(panel.left + pad, y, inner_w, row_h)
                if kind == "slot":
                    self._button(surface, rect, label, selected=logical == sel, enabled=True, sub=f"Slot {logical - len(actions) + 1}", size=21)
                else:
                    self._button(surface, rect, label, selected=logical == sel, size=24)
            y += heights[k]
        if start > 0:
            self._arrow_vertical(surface, (panel.centerx, panel.top + title_h - self._u(10)), -1)
        if end < len(entries):
            self._arrow_vertical(surface, (panel.centerx, panel.bottom - self._u(10)), 1)

    def _arrow_vertical(self, surface: pygame.Surface, center: tuple[int, int], direction: int) -> None:
        r = max(3, self._u(7))
        cx, cy = center
        d = 1 if direction >= 0 else -1
        pygame.draw.polygon(surface, Pal.DIM, [(cx, cy + d * r), (cx - r, cy - d * r), (cx + r, cy - d * r)])

    def draw_results(
        self,
        surface: pygame.Surface,
        title: str,
        lines: Sequence[str],
        options: Sequence[str],
        selected_index: int,
    ) -> None:
        """Run summary / game-over screen: ``title``, wrapped ``lines`` (blank string = spacer)
        and a vertical stack of ``options``.  Titles containing "defeat", "fallen", "game over"
        etc. are tinted red, anything else gold."""
        self._begin(surface)
        body_lines = _str_list(lines, "lines")
        labels = _str_list(options, "options")
        index = self._clamp_index(selected_index, len(labels), "selected_index")
        title = str(title)
        self._background(surface)

        lowered = title.lower()
        tint = Pal.RED if any(word in lowered for word in _DEFEAT_WORDS) else Pal.GOLD
        cx = self._pt(SCREEN_W / 2, 0)[0]
        title_font = self._font(56, True)
        y = self._pt(0, 42)[1]
        for line in _wrap(title, title_font, self._u(1100))[:2]:
            rect = self._text(surface, line, 56, tint, (cx, y), bold=True, anchor="midtop", glow=_shade(tint, 0.6))
            y = rect.bottom + self._u(2)
        y += self._u(10)
        self._divider(surface, cx, y, self._u(300), _shade(tint, 0.6))

        n = len(labels)
        gap = self._u(10)
        btn_h = max(self._u(24), min(self._u(52), (self._u(200) - gap * max(0, n - 1)) // n)) if n else 0
        opts_h = n * btn_h + max(0, n - 1) * gap
        bottom = surface.get_height() - self._u(44)
        panel_top = y + self._u(26)
        panel = pygame.Rect(0, 0, self._u(820), 0)
        panel.left = cx - panel.w // 2
        panel.top = panel_top
        panel.h = max(self._u(60), bottom - opts_h - (self._u(26) if n else 0) - panel_top)
        self._panel(surface, panel, ornaments=Pal.GOLD)
        text_rect = panel.inflate(-self._u(70), -self._u(50))
        font = self._font(21)
        wrapped: list[str] = []
        for entry in body_lines:
            wrapped.extend(_wrap(entry, font, text_rect.w) if entry.strip() else [""])
        line_h = font.get_linesize() + self._u(5)
        cap = max(1, (text_rect.h + self._u(5)) // line_h)
        if len(wrapped) > cap:
            wrapped = wrapped[:cap]
            wrapped[-1] = _ellipsize(wrapped[-1].rstrip() + " ...", font, text_rect.w)
        ly = text_rect.top
        for line in wrapped:
            if line:
                self._text(surface, line, 21, Pal.TEXT, (text_rect.left, ly), shadow=False)
            ly += line_h

        btn_w = self._u(400)
        by = bottom - opts_h
        for i, label in enumerate(labels):
            rect = pygame.Rect(cx - btn_w // 2, by + i * (btn_h + gap), btn_w, btn_h)
            self._button(surface, rect, label, selected=i == index, accent=tint, size=22)
