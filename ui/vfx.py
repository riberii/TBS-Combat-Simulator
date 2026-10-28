"""Visual juice: trauma-based screen shake, floating numbers, particles, flashes, alert banners and combat toasts."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any, Optional

import pygame

from core.config import SCREEN_H, SCREEN_W, Color, Pal
from systems.combat_system import CombatEvent, EventKind

MAX_SHAKE_PX = 18.0
MAX_FLOATERS = 24               # floating damage/heal numbers alive at once (oldest dropped first)
FLOATER_STACK_MAX = 4          # vertical stacking steps at one spot, so numbers cannot climb off-screen
LUNGE_TIME = 0.32
HIT_TIME = 0.22

# ---- toast tuning (purely presentational) ----------------------------------
TOAST_MAX = 4                  # tighter cap prevents wall-of-text; important events aren't buried
TOAST_FADE_IN = 0.12
TOAST_FADE_OUT = 0.40
TOAST_SLIDE_TIME = 0.20
TOAST_SLIDE_PX = 36.0
TOAST_GAP = 6
TOAST_MARGIN_X = 16
TOAST_TOP = 52                 # below the top bar and above enemy intent cards
TOAST_MAX_W = 340  # surface width budget; test asserts surface.get_width() <= 340
TOAST_MAX_CHARS = 120
TOAST_MAX_LINES = 2
TOAST_PAD_X = 12
TOAST_PAD_Y = 6
TOAST_ACCENT_W = 5
TOAST_BG = (14, 14, 22, 225)   # near-opaque dark plate keeps white text readable on any scene


@dataclass(frozen=True)
class _ToastStyle:
    color: Color
    priority: int
    life: float
    default_text: str


_AMBER: Color = (240, 160, 60)
_VIOLET: Color = (190, 120, 255)
_CYAN: Color = (90, 205, 255)
_STEEL: Color = (190, 195, 210)

_STYLES: dict[str, _ToastStyle] = {
    "restrained": _ToastStyle(_AMBER, 3, 3.2, "Restraint gained!"),
    "freed": _ToastStyle(Pal.GREEN, 3, 3.0, "Restraint broken!"),
    "struggle_failed": _ToastStyle(_STEEL, 1, 2.2, "Struggle failed"),
    "status": _ToastStyle(_VIOLET, 1, 2.6, "Status effect"),
    "lucidity": _ToastStyle(_VIOLET, 3, 3.2, "Lucidity lost"),
    "crit": _ToastStyle(Pal.GOLD, 1, 2.0, "Critical hit!"),
    "heal": _ToastStyle(Pal.GREEN, 1, 2.0, "Healed"),
    "phase": _ToastStyle(Pal.RED, 3, 4.5, "The boss enters a new phase!"),
    "loot": _ToastStyle(Pal.GOLD, 2, 3.0, "Loot found"),
    "reward": _ToastStyle(_CYAN, 2, 3.0, "Reward earned!"),
    "level_up": _ToastStyle(_CYAN, 3, 3.5, "Level up!"),
}

# Candidate EventKind member names per toast category. Only names that actually exist on
# EventKind are used; missing ones are ignored, so this never requires new enum members.
_KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "restrained": ("RESTRAINT_APPLIED", "RESTRAINED", "RESTRAIN", "BOUND", "BIND", "BOUND_APPLIED"),
    "freed": ("RESTRAINT_BROKEN", "RESTRAINT_BREAK", "BREAK_FREE", "BROKE_FREE", "FREED", "ESCAPE", "ESCAPED"),
    "struggle_failed": ("STRUGGLE_FAILED", "STRUGGLE_FAIL", "FAILED_STRUGGLE", "STRUGGLE_FAILURE"),
    "status": ("STATUS", "STATUS_APPLIED", "STATUS_EFFECT", "STATUS_EXPIRED", "BUFF", "DEBUFF"),
    "lucidity": ("LUCIDITY",),
    "crit": ("CRIT",),
    "heal": ("HEAL",),
    "phase": ("PHASE", "PHASE_CHANGE", "BOSS_PHASE", "PHASE_SHIFT"),
    "loot": ("LOOT", "LOOT_DROP", "DROP", "ITEM", "ITEM_GAINED"),
    "reward": ("GOLD", "XP"),
    "level_up": ("LEVEL_UP", "LEVELUP"),
}

ACTOR_EFFECT_TIME = 0.72
_ACTOR_EFFECT_COLORS: dict[str, Color] = {
    "cast": (190, 140, 255), "guard": (105, 190, 255),
    "dodge": (100, 235, 240), "heal": (120, 245, 165),
}


def _resolve_toast_kinds() -> dict[Any, str]:
    members = getattr(EventKind, "__members__", {})
    table: dict[Any, str] = {}
    for category, names in _KIND_ALIASES.items():
        for name in names:
            member = members.get(name)
            if member is not None:
                table.setdefault(member, category)
    return table


_TOAST_KINDS: dict[Any, str] = _resolve_toast_kinds()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_color(value: Any, default: Color) -> Color:
    """Return a clamped RGB tuple, or `default` if `value` is not colour-like."""
    try:
        r, g, b = (max(0, min(255, int(value[i]))) for i in range(3))
    except (TypeError, ValueError, IndexError, KeyError):
        return default
    return (r, g, b)


@dataclass
class Floater:
    text: str
    x: float
    y: float
    color: Color
    life: float
    max_life: float
    big: bool = False


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: Color
    size: float


@dataclass
class Alert:
    text: str
    color: Color
    life: float


@dataclass
class Toast:
    """A short-lived popup. Presentation state only; the text/kind come from combat events."""
    category: str
    text: str
    color: Color
    priority: int
    life: float
    max_life: float
    count: int = 1
    age: float = 0.0
    y: Optional[float] = None
    surface: Optional[pygame.Surface] = None


class VFX:
    """Owns all transient effects. Call `consume` with combat events, then update/draw each frame."""

    def __init__(self, fonts: dict[str, pygame.font.Font]) -> None:
        # main.py owns the shared UI font set (huge/big/mid/small/tiny), while
        # VFX historically used h1/h2. Normalize that interface here so the
        # first frame and combat overlays cannot crash with KeyError. Keep a
        # private copy: adding aliases must not mutate the caller's dictionary.
        self.fonts = dict(fonts)
        fallback = next(iter(self.fonts.values()), None)
        if fallback is None:
            # An empty font set is not useful, but failing at first draw is much
            # harder to diagnose; create safe defaults when pygame's font module
            # is available. GameApp initializes pygame before constructing VFX.
            if not pygame.font.get_init():
                pygame.font.init()
            fallback = pygame.font.Font(None, 18)
        self.fonts.setdefault("h1", self.fonts.get("big") or self.fonts.get("huge") or fallback)
        self.fonts.setdefault("h2", self.fonts.get("mid") or self.fonts.get("small") or fallback)
        self.fonts.setdefault("toast", self.fonts.get("tiny") or self.fonts.get("small") or fallback)
        self.rng = random.Random()
        self.trauma = 0.0
        self.screen_shake_enabled = True
        self.particles_enabled = True
        self.reduced_motion = False
        self.flash_enabled = True
        self.floaters: list[Floater] = []
        self.particles: list[Particle] = []
        self.alerts: list[Alert] = []
        self.toasts: list[Toast] = []
        self.flash_color: Color = Pal.RED
        self.flash = 0.0
        self.anchors: dict[int, tuple[float, float]] = {}  # entity uid -> sprite centre (set by renderer)
        self.lunges: dict[int, float] = {}
        self.hits: dict[int, float] = {}
        self.actor_effects: dict[int, tuple[str, float]] = {}
        self._overlay: Optional[pygame.Surface] = None

    # ---- event ingestion ---------------------------------------------------
    def consume(self, events: list[CombatEvent]) -> None:
        for ev in events:
            pos = self.anchors.get(ev.uid)
            if ev.kind in (EventKind.DAMAGE, EventKind.CRIT) and pos:
                crit = ev.kind is EventKind.CRIT
                same_pos = sum(1 for f in self.floaters if abs(f.x - pos[0]) < 60 and f.life > 0.4)
                y_offset = -min(same_pos, FLOATER_STACK_MAX) * 22
                self.floaters.append(Floater(f"{ev.amount}{'!' if crit else ''}", pos[0] + self.rng.uniform(-14, 14),
                                             pos[1] + y_offset, Pal.GOLD if crit else Pal.RED, 1.25, 1.25, big=crit or ev.amount > 30))
                self.burst(pos, Pal.RED if not crit else Pal.GOLD, 14 if crit else 8)
                if not self.reduced_motion:
                    self.hits[ev.uid] = HIT_TIME
            elif ev.kind is EventKind.HEAL and pos:
                same_pos = sum(1 for f in self.floaters if abs(f.x - pos[0]) < 60 and f.life > 0.4)
                y_offset = -min(same_pos, FLOATER_STACK_MAX) * 22
                self.floaters.append(Floater(f"+{ev.amount}", pos[0], pos[1] + y_offset, Pal.GREEN, 1.2, 1.2))
                self.burst(pos, Pal.GREEN, 8)
            elif ev.kind is EventKind.SHAKE:
                if self.screen_shake_enabled and not self.reduced_motion:
                    self.trauma = min(1.0, self.trauma + ev.power * 0.6)
            elif ev.kind is EventKind.LUNGE:
                if not self.reduced_motion:
                    self.lunges[ev.uid] = LUNGE_TIME
            elif ev.kind is EventKind.DEATH and pos:
                self.burst(pos, Pal.WHITE, 30)
                if self.screen_shake_enabled and not self.reduced_motion:
                    self.trauma = min(1.0, self.trauma + 0.4)
            elif ev.kind is EventKind.ACTION:
                data = getattr(ev, "data", {}) or {}
                data = data if isinstance(data, dict) else {}
                key = str(data.get("action_key", "")).lower()
                action_type = str(data.get("action_type", "ability")).lower()
                if action_type == "item" and any(word in key for word in ("heal", "tonic", "salve", "potion")):
                    effect = "heal"
                elif any(word in key for word in ("guard", "aegis", "barrier", "provoke", "scale_guard")):
                    effect = "guard"
                else:
                    effect = "cast"
                if ev.uid:
                    self.actor_effects[ev.uid] = (effect, ACTOR_EFFECT_TIME)
            elif ev.kind is EventKind.INTERCEPT and ev.uid:
                self.actor_effects[ev.uid] = ("guard", ACTOR_EFFECT_TIME)
            elif ev.kind is EventKind.DODGE and ev.uid:
                self.actor_effects[ev.uid] = ("dodge", ACTOR_EFFECT_TIME)
            elif ev.kind is EventKind.ALERT:
                self.alerts.append(Alert(ev.text, ev.color, 3.0))
                self.alerts = self.alerts[-3:]
                if self.flash_enabled and not self.reduced_motion:
                    self.flash_color, self.flash = ev.color, 0.35
            self._toast_from_event(ev)
        if len(self.floaters) > MAX_FLOATERS:
            self.floaters = self.floaters[-MAX_FLOATERS:]

    def burst(self, pos: tuple[float, float], color: Color, count: int) -> None:
        if not self.particles_enabled or self.reduced_motion:
            return
        # Effect counts are bounded to protect low-end systems and endless sessions.
        count = max(0, min(40, int(count)))
        if len(self.particles) + count > 400:
            count = max(0, 400 - len(self.particles))
        for _ in range(count):
            ang = self.rng.uniform(0, math.tau)
            spd = self.rng.uniform(60, 260)
            life = self.rng.uniform(0.3, 0.7)
            self.particles.append(Particle(pos[0], pos[1], math.cos(ang) * spd, math.sin(ang) * spd - 60,
                                           life, life, color, self.rng.uniform(2, 5)))

    # ---- toasts ----------------------------------------------------------------
    def push_toast(self, text: str, color: Optional[Color] = None, *, category: str = "status",
                   priority: Optional[int] = None, life: Optional[float] = None) -> bool:
        """Queue a toast. Returns False if `text` is empty. Raises ValueError for an unknown category.

        Identical live toasts are merged into one with a x<N> counter. When the queue exceeds
        TOAST_MAX the lowest-priority, oldest toast is dropped (never the one just added).
        """
        style = _STYLES.get(category)
        if style is None:
            raise ValueError(f"unknown toast category {category!r}; expected one of {sorted(_STYLES)}")
        clean = " ".join(str(text).split())
        if len(clean) > TOAST_MAX_CHARS:
            clean = clean[:TOAST_MAX_CHARS - 1].rstrip() + "…"
        if not clean:
            return False
        duration = style.life if life is None else max(0.35, min(8.0, float(life)))
        for t in self.toasts:
            if t.category == category and t.text == clean and t.life > 0:
                t.count += 1
                t.life = t.max_life = duration
                t.surface = None  # counter changed -> re-render
                return True
        toast = Toast(category, clean, _coerce_color(color, style.color) if color is not None else style.color,
                      style.priority if priority is None else _safe_int(priority), duration, duration)
        self.toasts.append(toast)
        while len(self.toasts) > TOAST_MAX:
            candidates = [t for t in self.toasts if t is not toast]
            if not candidates:
                break
            self.toasts.remove(min(candidates, key=lambda t: (t.priority, t.life)))
        return True

    def _toast_from_event(self, ev: CombatEvent) -> None:
        category = _TOAST_KINDS.get(ev.kind)
        if category is None:
            return
        style = _STYLES[category]
        amount = _safe_int(getattr(ev, "amount", 0))
        if category == "crit":
            text = f"Critical hit! {amount}" if amount > 0 else style.default_text
        elif category == "heal":
            text = f"Healed +{amount}" if amount > 0 else style.default_text
        elif category == "restrained":
            label = str(getattr(ev, "text", "") or "").strip()
            text = f"Restraint gained: {label}" if label else style.default_text
        elif category == "freed":
            label = str(getattr(ev, "text", "") or "").strip()
            text = f"Chain broken: {label}" if label else style.default_text
        elif category == "lucidity":
            label = str(getattr(ev, "text", "") or "").strip()
            text = label or (f"Lucidity -{amount}" if amount > 0 else style.default_text)
        elif category == "reward":
            label = str(getattr(ev, "kind", "")).lower()
            text = f"+{amount} gold" if label.endswith("gold") else f"+{amount} XP"
        else:
            raw = getattr(ev, "text", "")
            text = raw if isinstance(raw, str) and raw.strip() else style.default_text
        self.push_toast(text, category=category)

    @staticmethod
    def _fit_text(font: pygame.font.Font, text: str, max_w: int) -> str:
        if font.size(text)[0] <= max_w:
            return text
        while len(text) > 1 and font.size(text + "…")[0] > max_w:
            text = text[:-1]
        return text.rstrip() + "…"

    def _render_toast(self, toast: Toast) -> Optional[pygame.Surface]:
        font = self.fonts.get("toast")
        if font is None:
            return None
        label = toast.text if toast.count <= 1 else f"{toast.text} ×{toast.count}"
        max_line_w = TOAST_MAX_W - 2 * TOAST_PAD_X - TOAST_ACCENT_W
        lines: list[str] = []
        current = ""
        for word in label.split():
            candidate = f"{current} {word}".strip()
            if current and font.size(candidate)[0] > max_line_w:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > TOAST_MAX_LINES:
            lines = lines[:TOAST_MAX_LINES]
            lines[-1] = self._fit_text(font, lines[-1] + "…", max_line_w)
        imgs = [font.render(self._fit_text(font, line, max_line_w), True, Pal.WHITE) for line in lines]
        line_gap = 2
        # Cap width to TOAST_MAX_W so the panel never overflows its budget.
        w = min(TOAST_MAX_W, max((img.get_width() for img in imgs), default=0) + 2 * TOAST_PAD_X + TOAST_ACCENT_W)
        h = sum(img.get_height() for img in imgs) + max(0, len(imgs) - 1) * line_gap + 2 * TOAST_PAD_Y
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        rect = surf.get_rect()
        pygame.draw.rect(surf, TOAST_BG, rect, border_radius=6)
        pygame.draw.rect(surf, (*toast.color, 255), rect, 2, border_radius=6)
        pygame.draw.rect(surf, (*toast.color, 255), (0, 0, TOAST_ACCENT_W + 2, h),
                         border_top_left_radius=6, border_bottom_left_radius=6)
        y = (h - sum(img.get_height() for img in imgs) - max(0, len(imgs) - 1) * line_gap) // 2
        for img in imgs:
            surf.blit(img, (TOAST_ACCENT_W + TOAST_PAD_X, y))
            y += img.get_height() + line_gap
        return surf

    def _toast_alpha(self, t: Toast) -> int:
        fade_in = min(1.0, t.age / TOAST_FADE_IN) if TOAST_FADE_IN > 0 else 1.0
        fade_out = min(1.0, t.life / TOAST_FADE_OUT) if TOAST_FADE_OUT > 0 else 1.0
        return int(255 * max(0.0, min(fade_in, fade_out)))

    def _update_toasts(self, dt: float) -> None:
        for t in self.toasts:
            t.life -= dt
            t.age += dt
        self.toasts = [t for t in self.toasts if t.life > 0]
        y = float(TOAST_TOP)
        blend = min(1.0, 14.0 * dt)
        for t in self.toasts:
            if t.surface is None:
                t.surface = self._render_toast(t)
            height = t.surface.get_height() if t.surface is not None else 0
            t.y = y if t.y is None else t.y + (y - t.y) * blend
            y += height + TOAST_GAP

    def _draw_toasts(self, surf: pygame.Surface) -> None:
        for t in self.toasts:
            if t.surface is None or t.y is None:
                continue
            alpha = self._toast_alpha(t)
            if alpha <= 0:
                continue
            p = min(1.0, t.age / TOAST_SLIDE_TIME) if TOAST_SLIDE_TIME > 0 else 1.0
            slide = TOAST_SLIDE_PX * (1.0 - p) ** 3  # ease-out from the right edge
            t.surface.set_alpha(alpha)
            x = SCREEN_W - TOAST_MARGIN_X - t.surface.get_width() + slide
            surf.blit(t.surface, (int(x), int(t.y)))

    # ---- queries used by the renderer ---------------------------------------
    def offset(self) -> tuple[int, int]:
        if not self.screen_shake_enabled or self.reduced_motion:
            return (0, 0)
        mag = MAX_SHAKE_PX * self.trauma ** 2
        return int(self.rng.uniform(-1, 1) * mag), int(self.rng.uniform(-1, 1) * mag)

    def lunge_offset(self, uid: int, direction: int) -> int:
        if self.reduced_motion:
            return 0
        t = self.lunges.get(uid, 0.0)
        return int(direction * 46 * math.sin(math.pi * (1 - t / LUNGE_TIME))) if t > 0 else 0

    def hit_strength(self, uid: int) -> float:
        if self.reduced_motion:
            return 0.0
        return self.hits.get(uid, 0.0) / HIT_TIME

    def draw_actor_effect(self, surf: pygame.Surface, uid: int, center: tuple[float, float],
                          radius: float = 30.0) -> None:
        """Draw a short actor cue for committed abilities, guarding, and evasion."""
        if self.reduced_motion:
            return
        current = self.actor_effects.get(uid)
        if current is None:
            return
        kind, remaining = current
        color = _ACTOR_EFFECT_COLORS.get(kind)
        if color is None:
            return
        progress = max(0.0, min(1.0, 1.0 - remaining / ACTOR_EFFECT_TIME))
        cx, cy = map(int, center)
        rad = max(8, int(radius * (0.78 + progress * 0.30)))
        if kind == "guard":
            points = [(cx, cy-rad), (cx+rad, cy-rad//2), (cx+rad*3//4, cy+rad//2),
                      (cx, cy+rad), (cx-rad*3//4, cy+rad//2), (cx-rad, cy-rad//2)]
            pygame.draw.polygon(surf, color, points, max(2, int(radius * 0.08)))
        elif kind == "dodge":
            trail = int(radius * (1.0 + progress))
            for offset in (-8, 8):
                pygame.draw.line(surf, color, (cx-trail, cy+offset), (cx-trail//2, cy+offset-7), 2)
                pygame.draw.line(surf, color, (cx-trail//2, cy+offset-7), (cx, cy+offset), 2)
        else:
            pygame.draw.circle(surf, color, (cx, cy), rad, max(1, int(radius * 0.06)))
            for angle in (0.0, math.pi / 2, math.pi, math.pi * 1.5):
                x = cx + int(math.cos(angle + progress * 0.8) * rad)
                y = cy + int(math.sin(angle + progress * 0.8) * rad)
                pygame.draw.circle(surf, color, (x, y), max(2, int(radius * 0.07)))

    # ---- per-frame -------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.trauma = max(0.0, self.trauma - 1.6 * dt)
        self.flash = max(0.0, self.flash - 1.4 * dt)
        for table in (self.lunges, self.hits):
            for uid in list(table):
                table[uid] -= dt
                if table[uid] <= 0:
                    del table[uid]
        for uid, (effect, life) in list(self.actor_effects.items()):
            life -= dt
            if life <= 0:
                del self.actor_effects[uid]
            else:
                self.actor_effects[uid] = (effect, life)
        for f in self.floaters:
            f.life -= dt
            f.y -= 48 * dt
        self.floaters = [f for f in self.floaters if f.life > 0]
        for p in self.particles:
            p.life -= dt
            p.vy += 380 * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
        self.particles = [p for p in self.particles if p.life > 0]
        for a in self.alerts:
            a.life -= dt
        self.alerts = [a for a in self.alerts if a.life > 0]
        self._update_toasts(dt)

    def draw_world(self, surf: pygame.Surface) -> None:
        for p in self.particles:
            size = max(1, int(p.size * p.life / p.max_life))
            pygame.draw.rect(surf, p.color, (int(p.x), int(p.y), size, size))
        for f in self.floaters:
            font = self.fonts["h1"] if f.big else self.fonts["h2"]
            img = font.render(f.text, True, f.color)
            shadow = font.render(f.text, True, Pal.BLACK)
            img.set_alpha(int(255 * min(1.0, f.life / (f.max_life * 0.5))))
            surf.blit(shadow, shadow.get_rect(center=(f.x + 2, f.y + 2)))
            surf.blit(img, img.get_rect(center=(f.x, f.y)))

    def draw_overlay(self, surf: pygame.Surface) -> None:
        if self.flash > 0 and self.flash_enabled and not self.reduced_motion:
            if self._overlay is None:
                self._overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            self._overlay.fill((*self.flash_color, int(110 * self.flash)))
            surf.blit(self._overlay, (0, 0))
        for i, a in enumerate(self.alerts):
            img = self.fonts["h2"].render(a.text, True, Pal.WHITE)
            rect = img.get_rect(center=(SCREEN_W // 2 - 190, 92 + i * 38))
            box = rect.inflate(28, 10)
            fade = min(1.0, a.life / 0.5)
            pygame.draw.rect(surf, tuple(int(c * 0.35 * fade) for c in a.color), box, border_radius=6)
            pygame.draw.rect(surf, tuple(int(c * fade) for c in a.color), box, 2, border_radius=6)
            surf.blit(img, rect)
        self._draw_toasts(surf)
