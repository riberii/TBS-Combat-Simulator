"""Quick-time events and restraint struggles for Abyssal Choir.

Pure logic: the UI feeds key *names* (pygame.key.name), text and mouse positions,
then reads back plain data structures (tooltips, tension segments, wheel state)
to render. pygame is imported lazily and only inside ``RestraintManager.poll_mouse``
so the module stays testable headless.

Contents
    * Classic QTEs: TypingQTE, MashQTE, TimingQTE, MemoryQTE (+ ``create_qte``).
    * Restraints: Crown of Thorns, Sacred Rune Bindings, Shadow Thorn Vines,
      Gothic Chains (``Restraint`` / ``RestraintProfile`` / ``RESTRAINT_PROFILES``).
    * ``StruggleQTE``: [E] / [SPACE] mash + timing-wheel loop that wears a
      restraint's durability down.
    * ``RestraintManager``: hover detection (``get_hovered_restraint``), tooltip
      data, magic lock, HP drain accounting and struggle routing.
"""
from __future__ import annotations

import itertools
import math
import random
import textwrap
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Optional, Sequence

from core.config import QteKind

TAU = math.tau
Vec2 = tuple[float, float]
Colour3 = tuple[int, int, int]
Colour4 = tuple[int, int, int, int]

WORDS: tuple[str, ...] = (
    "chains", "penance", "abyss", "mercy", "ember", "wrath", "seraph", "hollow",
    "ashen", "vigil", "thorns", "requiem", "sorrow", "halo", "dirge", "cinder",
)
# Deliberately rare, long, ASCII-only words for the Fallen Angel's manacles trial.
# No common combat/lore words; a single wrong letter fails the check immediately.
ANGEL_WORDS: tuple[str, ...] = (
    "apokatastasis", "sesquipedalian", "phantasmagoria", "pulchritudinous",
    "sphygmomanometer", "intransigence", "circumlocution", "eschatological",
    "xylophonically", "disambiguation", "ratiocination", "chiaroscurist",
    "iatromancycraft", "obfuscationist", "transubstantiation", "cryptesthesia",
)
ARROWS: tuple[str, ...] = ("left", "up", "right", "down")

# Keys that trigger a struggle (pygame.key.name values).
STRUGGLE_KEYS: frozenset[str] = frozenset({"e", "space"})
# Player actions that a magic-locking restraint blocks.
MAGIC_ACTIONS: frozenset[str] = frozenset({"cast", "spell", "magic", "invoke", "hymn"})
STRUGGLE_PROMPT = "Press [E] to Struggle"


# ---------------------------------------------------------------------------
# Classic QTEs
# ---------------------------------------------------------------------------
class QTE(ABC):
    """Base timed input challenge."""

    kind: QteKind
    title: str = ""

    def __init__(self, limit: float) -> None:
        self.limit = limit
        self.elapsed = 0.0
        self.done = False
        self.success = False

    @property
    def time_ratio(self) -> float:
        return max(0.0, 1.0 - self.elapsed / self.limit)

    def finish(self, ok: bool) -> None:
        if not self.done:
            self.done, self.success = True, ok

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.elapsed += dt
        self._tick(dt)
        if self.elapsed >= self.limit:
            self.finish(False)

    def _tick(self, dt: float) -> None:
        """Optional per-frame behaviour for subclasses."""

    @abstractmethod
    def handle_key(self, key: str, text: str) -> None:
        """Process a key press."""

    @property
    @abstractmethod
    def hint(self) -> str:
        """One-line instruction for the player."""


class TypingQTE(QTE):
    """Type a word exactly. A wrong letter wipes your progress (Penitent Manacles)."""

    kind = QteKind.TYPING
    title = "MANACLES: TYPE TO STRIKE"

    def __init__(self, word: str, limit: float, fatal_mistake: bool = False) -> None:
        super().__init__(limit)
        self.word = word.lower()
        self.typed = ""
        self.slips = 0
        self.fatal_mistake = bool(fatal_mistake)

    @property
    def progress(self) -> float:
        return len(self.typed) / max(1, len(self.word))

    @property
    def remaining(self) -> str:
        return self.word[len(self.typed):]

    def handle_key(self, key: str, text: str) -> None:
        if self.done:
            return
        if key == "backspace":
            self.typed = self.typed[:-1]
        # Text input must be exactly one ASCII letter. Some platform/input methods
        # can provide multi-character or Unicode text, which must not advance a QTE.
        elif text:
            expected = self.word[len(self.typed)]
            correct = len(text) == 1 and text.isascii() and text.isalpha() and text.lower() == expected
            if correct:
                self.typed += text.lower()
                if self.typed == self.word:
                    self.finish(True)
            elif self.fatal_mistake:
                self.slips += 1
                self.finish(False)
            elif len(text) == 1 and text.isascii() and text.isalpha():
                self.slips += 1
                self.typed = ""

    @property
    def hint(self) -> str:
        if self.fatal_mistake:
            return f"ANGEL'S TRIAL: type {self.word.upper()} exactly. One wrong letter fails immediately."
        return f"Type {self.word.upper()} exactly. A wrong letter resets progress; Backspace removes one letter."


class MashQTE(QTE):
    """Hammer a key N times before the clock runs out (swallowing / breaking free)."""

    kind = QteKind.MASH

    def __init__(self, title: str, presses: int, limit: float, key: str = "space") -> None:
        super().__init__(limit)
        self.title = title
        self.presses = presses
        self.count = 0
        self.key = key

    def handle_key(self, key: str, text: str) -> None:
        if not self.done and key == self.key:
            self.count += 1
            if self.count >= self.presses:
                self.finish(True)

    @property
    def hint(self) -> str:
        return f"Mash [{self.key.upper()}]!  {self.count}/{self.presses}"


class TimingQTE(QTE):
    """Stop a sweeping cursor inside the target zone."""

    kind = QteKind.TIMING
    title = "STRIKE THE VITAL POINT"

    def __init__(self, rng: random.Random, speed: float, zone_width: float, limit: float = 5.0) -> None:
        super().__init__(limit)
        self.pos = 0.0
        self.direction = 1.0
        self.speed = speed
        centre = rng.uniform(0.25, 0.75)
        self.zone = (centre - zone_width / 2, centre + zone_width / 2)

    def _tick(self, dt: float) -> None:
        self.pos += self.direction * self.speed * dt
        if self.pos >= 1.0:
            self.pos, self.direction = 1.0, -1.0
        elif self.pos <= 0.0:
            self.pos, self.direction = 0.0, 1.0

    def handle_key(self, key: str, text: str) -> None:
        # Only Space is valid. Enter must never become a forgiving alternate timing input.
        if not self.done and key == "space":
            self.finish(self.zone[0] <= self.pos <= self.zone[1])

    @property
    def hint(self) -> str:
        return "Press [SPACE] when the cursor is inside the bright zone."


class MemoryQTE(QTE):
    """Memorise an arrow sequence, then repeat it."""

    kind = QteKind.MEMORY
    title = "WEAVE THE SIGIL"

    def __init__(self, sequence: list[str], show_time: float, limit: float) -> None:
        super().__init__(limit)
        self.sequence = sequence
        self.show_left = show_time
        self.index = 0

    @property
    def showing(self) -> bool:
        return self.show_left > 0.0

    def update(self, dt: float) -> None:
        if self.done:
            return
        if self.showing:  # memorisation time does not eat the input timer
            self.show_left -= dt
            return
        super().update(dt)

    def handle_key(self, key: str, text: str) -> None:
        if self.done or self.showing or key not in ARROWS:
            return
        if key == self.sequence[self.index]:
            self.index += 1
            if self.index == len(self.sequence):
                self.finish(True)
        else:
            self.finish(False)

    @property
    def hint(self) -> str:
        return "Memorise the sigil..." if self.showing else "Repeat it with the arrow keys."


def create_qte(kind: QteKind, rng: random.Random, tier: int = 1, title: Optional[str] = None) -> QTE:
    """Factory; `tier` (>=1) makes challenges harder as the run progresses."""
    tier = max(1, tier)
    if kind is QteKind.TYPING:
        word = rng.choice([w for w in WORDS if len(w) <= 4 + tier + 1] or list(WORDS))
        return TypingQTE(word, limit=2.5 + 0.45 * len(word))
    if kind is QteKind.MASH:
        return MashQTE(title or "BREAK IT!", presses=10 + 2 * tier, limit=3.5)
    if kind is QteKind.TIMING:
        # The target is rolled independently each challenge and becomes a narrow, exact timing window.
        return TimingQTE(rng, speed=1.05 + 0.16 * tier, zone_width=max(0.028, 0.105 - 0.009 * tier), limit=4.5)
    length = min(7, 3 + tier)
    return MemoryQTE([rng.choice(ARROWS) for _ in range(length)], show_time=0.5 * length + 0.6, limit=2.0 + 0.8 * length)


# ---------------------------------------------------------------------------
# Restraint definitions
# ---------------------------------------------------------------------------
class RestraintKind(Enum):
    CROWN_OF_THORNS = "crown_of_thorns"
    SACRED_RUNE_BINDINGS = "sacred_rune_bindings"
    SHADOW_THORN_VINES = "shadow_thorn_vines"
    GOTHIC_CHAINS = "gothic_chains"


@dataclass(frozen=True)
class RestraintProfile:
    """Static tuning + flavour text for one restraint type."""

    kind: RestraintKind
    name: str
    lore: str
    statuses: tuple[str, str, str]  # tight / loosening / cracking
    max_durability: float
    regen_per_sec: float
    mash_power: float            # base durability damage per press
    perfect_power: float         # extra damage for a timing-wheel hit
    hp_drain_struggle: float     # HP/s while the struggle phase is active
    hp_drain_idle: float         # HP/s while merely wearing it
    locks_magic: bool
    uses_wheel: bool             # False => pure rapid mashing (momentum driven)
    wheel_zone: float            # sweet-spot width in radians (wheel types)
    tension_lines: bool          # simulate spring-tension lines between points
    accent: Colour3
    hit_radius: float
    struggle_limit: float        # seconds the struggle phase lasts
    tighten_on_fail: float       # fraction of max durability regained on failure


RESTRAINT_PROFILES: dict[RestraintKind, RestraintProfile] = {
    RestraintKind.CROWN_OF_THORNS: RestraintProfile(
        kind=RestraintKind.CROWN_OF_THORNS,
        name="Crown of Thorns",
        lore=(
            "A circlet of black briars forged for those who sang out of tune. "
            "It cinches around the halo and drinks from the wearer with every defiant breath."
        ),
        statuses=(
            "The briars bite deep; every heartbeat tightens the circlet.",
            "The thorns slacken, yet still pierce your brow.",
            "The crown splinters; only a few barbs still hold.",
        ),
        max_durability=70.0,
        regen_per_sec=2.0,
        mash_power=2.2,
        perfect_power=16.0,
        hp_drain_struggle=3.0,
        hp_drain_idle=0.0,
        locks_magic=False,
        uses_wheel=True,
        wheel_zone=1.1,
        tension_lines=False,
        accent=(190, 40, 55),
        hit_radius=34.0,
        struggle_limit=11.0,
        tighten_on_fail=0.25,
    ),
    RestraintKind.SACRED_RUNE_BINDINGS: RestraintProfile(
        kind=RestraintKind.SACRED_RUNE_BINDINGS,
        name="Sacred Rune Bindings",
        lore=(
            "A seal of violet sigils burned into the air by the Silent Cantor. "
            "While it glows, no hymn or spell may leave your lips."
        ),
        statuses=(
            "The seal blazes violet; your magic is wholly smothered.",
            "The sigils flicker as your struggle frays their lines.",
            "The glyphs gutter like dying candles, ready to unravel.",
        ),
        max_durability=90.0,
        regen_per_sec=1.5,
        mash_power=1.0,
        perfect_power=18.0,
        hp_drain_struggle=0.0,
        hp_drain_idle=0.0,
        locks_magic=True,
        uses_wheel=True,
        wheel_zone=0.8,
        tension_lines=False,
        accent=(160, 70, 235),
        hit_radius=36.0,
        struggle_limit=12.0,
        tighten_on_fail=0.2,
    ),
    RestraintKind.SHADOW_THORN_VINES: RestraintProfile(
        kind=RestraintKind.SHADOW_THORN_VINES,
        name="Shadow Thorn Vines",
        lore=(
            "Living shadow grown in the abyss' bitter garden. "
            "The tendrils coil about wrist and ankle, drawing tighter against every pull."
        ),
        statuses=(
            "The vines are drum-tight, thorns pressing into every joint.",
            "The tendrils creak and begin to unspool.",
            "The vines fray into drifting smoke; one more pull.",
        ),
        max_durability=80.0,
        regen_per_sec=3.5,
        mash_power=2.5,
        perfect_power=11.0,
        hp_drain_struggle=0.0,
        hp_drain_idle=0.0,
        locks_magic=False,
        uses_wheel=True,
        wheel_zone=1.0,
        tension_lines=True,
        accent=(95, 135, 105),
        hit_radius=30.0,
        struggle_limit=11.0,
        tighten_on_fail=0.3,
    ),
    RestraintKind.GOTHIC_CHAINS: RestraintProfile(
        kind=RestraintKind.GOTHIC_CHAINS,
        name="Gothic Chains",
        lore=(
            "Iron links hammered in the Penitent Foundry, heavy with a thousand unanswered prayers. "
            "Only raw, relentless force will snap them."
        ),
        statuses=(
            "The links hold fast; each tug only rattles the iron.",
            "A link groans and warps under the strain.",
            "The chains are cracked through; hammer them apart!",
        ),
        max_durability=140.0,
        regen_per_sec=4.0,
        mash_power=3.5,
        perfect_power=0.0,
        hp_drain_struggle=0.0,
        hp_drain_idle=0.0,
        locks_magic=False,
        uses_wheel=False,
        wheel_zone=0.0,
        tension_lines=True,
        accent=(170, 175, 190),
        hit_radius=32.0,
        struggle_limit=10.0,
        tighten_on_fail=0.25,
    ),
}

_RESTRAINT_IDS = itertools.count(1)
REGEN_DELAY = 0.6  # seconds after the last struggle before durability regrows


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Shortest distance from point p to the segment a-b."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    length_sq = abx * abx + aby * aby
    if length_sq <= 1e-9:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (a[0] + abx * t), p[1] - (a[1] + aby * t))


def _lighten(colour: Colour3, amount: float) -> Colour3:
    r, g, b = colour
    return (
        int(r + (255 - r) * amount),
        int(g + (255 - g) * amount),
        int(b + (255 - b) * amount),
    )


# ---------------------------------------------------------------------------
# Restraint instances
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TensionSegment:
    """One simulated tension line, ready to draw as a (sagging) cord."""

    start: Vec2
    end: Vec2
    tension: float  # 0 slack .. 1+ taut
    sag: float      # pixels the midpoint should droop (0 when taut)


class _TensionLine:
    """Damped spring tracking how taut one cord between two points is."""

    __slots__ = ("a", "b", "tension", "velocity")

    SPRING = 90.0
    DAMPING = 9.0

    def __init__(self, a: int, b: int, tension: float) -> None:
        self.a = a
        self.b = b
        self.tension = tension
        self.velocity = 0.0

    def step(self, dt: float, target: float) -> None:
        accel = self.SPRING * (target - self.tension) - self.DAMPING * self.velocity
        self.velocity += accel * dt
        self.tension = max(0.0, min(1.25, self.tension + self.velocity * dt))


class Restraint:
    """A single active bondage effect pinned to a screen position."""

    def __init__(
        self,
        kind: RestraintKind,
        anchor: Vec2,
        tier: int = 1,
        rng: Optional[random.Random] = None,
    ) -> None:
        rng = rng or random.Random()
        self.uid = next(_RESTRAINT_IDS)
        self.kind = kind
        self.profile = RESTRAINT_PROFILES[kind]
        self.tier = max(1, tier)
        self.anchor: Vec2 = (float(anchor[0]), float(anchor[1]))
        self.max_durability = self.profile.max_durability * (1.0 + 0.12 * (self.tier - 1))
        self.durability = self.max_durability
        self.struggling = False
        self.escaped = False
        self.announced = False
        self.age = 0.0
        self.since_struggle = 99.0
        self.offsets: list[Vec2] = self._build_offsets(rng)
        self.lines: list[_TensionLine] = self._build_lines()
        # Hovering anywhere inside the bound area (not just on a cord) counts.
        self.hull_radius = max(math.hypot(ox, oy) for ox, oy in self.offsets)

    # -- construction -------------------------------------------------------
    def _build_offsets(self, rng: random.Random) -> list[Vec2]:
        if self.kind is RestraintKind.CROWN_OF_THORNS:
            return [(22.0 * math.cos(TAU * i / 6), 22.0 * math.sin(TAU * i / 6)) for i in range(6)]
        if self.kind is RestraintKind.SACRED_RUNE_BINDINGS:
            phase = rng.uniform(0.0, TAU)
            return [
                (42.0 * math.cos(phase + TAU * i / 4), 42.0 * math.sin(phase + TAU * i / 4))
                for i in range(4)
            ]
        if self.kind is RestraintKind.SHADOW_THORN_VINES:
            offsets: list[Vec2] = [(0.0, 0.0)]  # index 0 = root at the body core
            for i in range(5):
                ang = TAU * i / 5 + rng.uniform(-0.25, 0.25)
                rad = rng.uniform(46.0, 64.0)
                offsets.append((rad * math.cos(ang), rad * math.sin(ang)))
            return offsets
        return [(-38.0, 0.0), (38.0, 0.0), (0.0, 34.0)]  # wrists + hanging link

    def _build_lines(self) -> list[_TensionLine]:
        if not self.profile.tension_lines:
            return []
        if self.kind is RestraintKind.SHADOW_THORN_VINES:
            lines = [_TensionLine(0, i, 0.7) for i in range(1, 6)]
            lines += [_TensionLine(i, i % 5 + 1, 0.7) for i in range(1, 6)]
            return lines
        return [_TensionLine(0, 2, 0.7), _TensionLine(1, 2, 0.7)]

    # -- geometry -----------------------------------------------------------
    @property
    def points(self) -> list[Vec2]:
        ax, ay = self.anchor
        return [(ax + ox, ay + oy) for ox, oy in self.offsets]

    def set_anchor(self, anchor: Vec2) -> None:
        self.anchor = (float(anchor[0]), float(anchor[1]))

    def hit_test(self, pos: Vec2) -> bool:
        """True if `pos` is over any part of this restraint."""
        if self.escaped:
            return False
        radius = self.profile.hit_radius
        if math.hypot(pos[0] - self.anchor[0], pos[1] - self.anchor[1]) <= self.hull_radius:
            return True
        pts = self.points
        for x, y in pts:
            if math.hypot(pos[0] - x, pos[1] - y) <= radius:
                return True
        if self.lines:
            thin = radius * 0.55
            for line in self.lines:
                if _point_segment_distance(pos, pts[line.a], pts[line.b]) <= thin:
                    return True
        return False

    def tension_segments(self) -> list[TensionSegment]:
        pts = self.points
        segments: list[TensionSegment] = []
        for line in self.lines:
            a, b = pts[line.a], pts[line.b]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            sag = max(0.0, 1.0 - min(line.tension, 1.0)) * 0.12 * length
            segments.append(TensionSegment(a, b, line.tension, sag))
        return segments

    # -- state --------------------------------------------------------------
    @property
    def resistance_ratio(self) -> float:
        if self.escaped or self.max_durability <= 0.0:
            return 0.0
        return max(0.0, min(1.0, self.durability / self.max_durability))

    @property
    def glow(self) -> float:
        """0..1 pulse used for runes / crown highlights."""
        return 0.6 + 0.4 * math.sin(self.age * 3.0)

    @property
    def status_text(self) -> str:
        ratio = self.resistance_ratio
        idx = 0 if ratio > 0.66 else 1 if ratio > 0.33 else 2
        text = self.profile.statuses[idx]
        if self.profile.locks_magic:
            text += " Spellcasting is sealed."
        if self.struggling and self.profile.hp_drain_struggle > 0.0:
            text += " Your vitality bleeds away as you strain."
        return text

    # -- physics / damage ---------------------------------------------------
    def impulse(self, strength: float) -> None:
        """Kick every tension line (positive = jerk taut, negative = slacken)."""
        for i, line in enumerate(self.lines):
            line.velocity += strength * (1.0 if i % 2 == 0 else -0.6)

    def apply_damage(self, amount: float) -> None:
        if self.escaped or amount <= 0.0:
            return
        self.durability = max(0.0, self.durability - amount)
        self.since_struggle = 0.0
        self.impulse(3.0 + amount * 0.15)
        if self.durability <= 0.0:
            self.escaped = True
            self.struggling = False

    def tighten(self, amount: float) -> None:
        if self.escaped:
            return
        self.durability = min(self.max_durability, self.durability + amount)
        self.impulse(6.0)

    def update(self, dt: float) -> float:
        """Advance regen + spring physics. Returns HP drained this frame."""
        if dt <= 0.0:
            return 0.0
        self.age += dt
        self.since_struggle += dt
        step = min(dt, 0.05)
        if self.escaped:
            self._step_lines(step, 0.0)
            return 0.0
        if self.since_struggle > REGEN_DELAY and self.durability < self.max_durability:
            self.durability = min(self.max_durability, self.durability + self.profile.regen_per_sec * dt)
        self._step_lines(step, self.resistance_ratio)
        rate = self.profile.hp_drain_struggle if self.struggling else self.profile.hp_drain_idle
        return rate * dt

    def _step_lines(self, dt: float, ratio: float) -> None:
        if not self.lines:
            return
        flutter = 0.2 * abs(math.sin(self.age * 12.0)) if self.struggling else 0.0
        target = 0.0 if ratio <= 0.0 else 0.15 + 0.6 * ratio + flutter
        for line in self.lines:
            line.step(dt, target)

    def render_state(self) -> dict[str, Any]:
        """Plain data bundle for the UI layer."""
        return {
            "uid": self.uid,
            "kind": self.kind.value,
            "name": self.profile.name,
            "anchor": self.anchor,
            "points": self.points,
            "segments": self.tension_segments(),
            "ratio": self.resistance_ratio,
            "accent": self.profile.accent,
            "glow": self.glow,
            "struggling": self.struggling,
            "escaped": self.escaped,
            "locks_magic": self.profile.locks_magic,
        }


def create_restraint(
    kind: RestraintKind,
    anchor: Vec2,
    rng: Optional[random.Random] = None,
    tier: int = 1,
) -> Restraint:
    """Factory for restraints; `tier` scales durability."""
    return Restraint(kind, anchor, tier=tier, rng=rng)


# ---------------------------------------------------------------------------
# Struggle QTE
# ---------------------------------------------------------------------------
class StruggleQTE(QTE):
    """[E] / [SPACE] struggle against a restraint.

    Wheel restraints: a marker spins around a wheel; pressing while it is inside the
    glowing arc deals a heavy hit and builds a combo, a mistimed press only scrapes.
    Chain restraints: pure rapid mashing; momentum builds with fast presses and
    decays quickly, so a slow rhythm will not snap the links.
    Failing (time up) re-tightens the restraint.
    """

    MOMENTUM_CAP = 2.0
    MOMENTUM_STEP = 0.3
    MOMENTUM_DECAY = 1.6
    PERFECT_TIME_BONUS = 0.35

    def __init__(self, restraint: Restraint, rng: random.Random, tier: int = 1) -> None:
        profile = restraint.profile
        super().__init__(profile.struggle_limit)
        self.kind = QteKind.TIMING if profile.uses_wheel else QteKind.MASH
        self.title = f"STRUGGLE: {profile.name.upper()}"
        self.restraint = restraint
        self.rng = rng
        tier = max(1, tier)
        self.wheel_angle = rng.uniform(0.0, TAU)
        self.wheel_dir = 1.0
        self.wheel_speed = TAU * (0.6 + 0.07 * min(tier, 8))
        self.zone_width = max(0.45, profile.wheel_zone - 0.05 * (tier - 1))
        self.zone_centre = rng.uniform(0.0, TAU)
        self.combo = 0
        self.momentum = 0.0
        self.presses = 0
        self.perfects = 0
        self.misses = 0
        self.last_result = ""
        restraint.struggling = True

    # -- wheel --------------------------------------------------------------
    @property
    def in_zone(self) -> bool:
        diff = abs((self.wheel_angle - self.zone_centre + math.pi) % TAU - math.pi)
        return diff <= self.zone_width / 2.0

    def wheel_state(self) -> dict[str, float | bool | str | int]:
        """Data for drawing the timing wheel."""
        return {
            "enabled": self.restraint.profile.uses_wheel,
            "angle": self.wheel_angle,
            "zone_start": (self.zone_centre - self.zone_width / 2.0) % TAU,
            "zone_end": (self.zone_centre + self.zone_width / 2.0) % TAU,
            "in_zone": self.in_zone,
            "combo": self.combo,
            "momentum": self.momentum / self.MOMENTUM_CAP,
            "result": self.last_result,
        }

    @property
    def progress(self) -> float:
        """0 (fully bound) .. 1 (free)."""
        return 1.0 - self.restraint.resistance_ratio

    def _reroll_zone(self) -> None:
        self.zone_centre = (self.wheel_angle + math.pi + self.rng.uniform(-1.0, 1.0)) % TAU
        if self.rng.random() < 0.35:
            self.wheel_dir = -self.wheel_dir

    # -- QTE hooks ----------------------------------------------------------
    def _tick(self, dt: float) -> None:
        self.momentum = max(0.0, self.momentum - self.MOMENTUM_DECAY * dt)
        if self.restraint.profile.uses_wheel:
            self.wheel_angle = (self.wheel_angle + self.wheel_dir * self.wheel_speed * dt) % TAU
        if self.restraint.escaped:
            self.finish(True)

    def finish(self, ok: bool) -> None:
        if self.done:
            return
        super().finish(ok)
        restraint = self.restraint
        restraint.struggling = False
        if not ok and not restraint.escaped:
            restraint.tighten(restraint.max_durability * restraint.profile.tighten_on_fail)

    def abandon(self) -> None:
        """Stop struggling without penalty (player switched target)."""
        if not self.done:
            self.done, self.success = True, False
        self.restraint.struggling = False

    def handle_key(self, key: str, text: str) -> None:
        if self.done:
            return
        if key in STRUGGLE_KEYS or (text and text.lower() == "e"):
            self._struggle()

    def _struggle(self) -> None:
        profile = self.restraint.profile
        self.presses += 1
        self.momentum = min(self.MOMENTUM_CAP, self.momentum + self.MOMENTUM_STEP)
        base = profile.mash_power * (1.0 + self.momentum)
        if profile.uses_wheel:
            if self.in_zone:
                self.combo += 1
                self.perfects += 1
                damage = profile.perfect_power * (1.0 + 0.15 * min(self.combo, 5)) + base * 0.25
                self.limit += self.PERFECT_TIME_BONUS
                self.last_result = "PERFECT" if self.combo < 3 else f"PERFECT x{self.combo}"
                self._reroll_zone()
            else:
                self.combo = 0
                self.misses += 1
                damage = base * 0.35
                self.restraint.impulse(-2.0)
                self.last_result = "SLIP"
        else:
            damage = base
            self.last_result = "SNAP!" if self.momentum >= self.MOMENTUM_CAP * 0.6 else "RATTLE"
        self.restraint.apply_damage(damage)
        if self.restraint.escaped:
            self.last_result = "FREE!"
            self.finish(True)

    @property
    def hint(self) -> str:
        pct = int(round(self.progress * 100))
        if self.restraint.profile.uses_wheel:
            return f"Press [E] or [SPACE] as the marker crosses the glowing arc!  Loosened {pct}%"
        return f"Mash [E] or [SPACE] fast to snap the links!  Loosened {pct}%"


def create_struggle_qte(restraint: Restraint, rng: random.Random, tier: Optional[int] = None) -> StruggleQTE:
    """Factory for a struggle against `restraint` (defaults to the restraint's own tier)."""
    return StruggleQTE(restraint, rng, tier=tier if tier is not None else restraint.tier)


# ---------------------------------------------------------------------------
# Hover tooltip data
# ---------------------------------------------------------------------------
TOOLTIP_WIDTH = 300
TOOLTIP_PADDING = 14
TOOLTIP_WRAP_CHARS = 38
TOOLTIP_LINE_HEIGHT = 16
TOOLTIP_MARGIN = 8


@dataclass(frozen=True)
class TooltipData:
    """Everything the UI needs to draw the dark-gothic hover tooltip."""

    restraint_id: int
    kind: RestraintKind
    title: str
    resistance_value: float
    resistance_max: float
    resistance_ratio: float
    resistance_text: str
    lore_lines: tuple[str, ...]
    status_lines: tuple[str, ...]
    prompt: str
    accent: Colour3
    title_colour: Colour3
    text_colour: Colour3
    muted_colour: Colour3
    background: Colour4      # semi-transparent near-black
    border: Colour4
    box_pos: tuple[int, int]
    box_size: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


def _wrap(text: str) -> tuple[str, ...]:
    return tuple(textwrap.wrap(text, width=TOOLTIP_WRAP_CHARS)) or ("",)


def _layout_tooltip(
    mouse_pos: tuple[int, int],
    size: tuple[int, int],
    screen_size: tuple[int, int],
) -> tuple[int, int]:
    """Place the box beside the cursor, flipping/clamping to stay on screen."""
    mx, my = mouse_pos
    w, h = size
    sw, sh = screen_size
    x = mx + 18
    y = my + 22
    if x + w > sw - TOOLTIP_MARGIN:
        x = mx - 18 - w
    if y + h > sh - TOOLTIP_MARGIN:
        y = my - 22 - h
    x = max(TOOLTIP_MARGIN, min(x, max(TOOLTIP_MARGIN, sw - w - TOOLTIP_MARGIN)))
    y = max(TOOLTIP_MARGIN, min(y, max(TOOLTIP_MARGIN, sh - h - TOOLTIP_MARGIN)))
    return x, y


# ---------------------------------------------------------------------------
# Restraint manager
# ---------------------------------------------------------------------------
class RestraintManager:
    """Owns active restraints, hover detection, the struggle loop and magic lock."""

    def __init__(self, rng: Optional[random.Random] = None, screen_size: tuple[int, int] = (1280, 720)) -> None:
        self.rng = rng or random.Random()
        self.screen_size = screen_size
        self.restraints: list[Restraint] = []
        self.qte: Optional[StruggleQTE] = None
        self.last_qte: Optional[StruggleQTE] = None
        self.mouse_pos: tuple[int, int] = (-1, -1)
        self.hovered_id: Optional[int] = None
        self._events: list[str] = []
        self._hp_accum = 0.0

    # -- restraint bookkeeping ---------------------------------------------
    def add_restraint(self, kind: RestraintKind, anchor: Vec2, tier: int = 1) -> Restraint:
        restraint = create_restraint(kind, anchor, self.rng, tier)
        self.restraints.append(restraint)
        self._events.append(f"bound:{restraint.profile.name}")
        return restraint

    def remove_restraint(self, uid: int) -> None:
        if self.qte is not None and self.qte.restraint.uid == uid:
            self.cancel_struggle()
        self.restraints = [r for r in self.restraints if r.uid != uid]
        if self.hovered_id == uid:
            self.hovered_id = None

    def clear(self) -> None:
        self.cancel_struggle()
        self.restraints.clear()
        self.hovered_id = None

    @property
    def active_restraints(self) -> list[Restraint]:
        return [r for r in self.restraints if not r.escaped]

    @property
    def is_bound(self) -> bool:
        return bool(self.active_restraints)

    # -- magic lock ---------------------------------------------------------
    @property
    def magic_locked(self) -> bool:
        return any(r.profile.locks_magic for r in self.active_restraints)

    def is_action_blocked(self, action: str) -> bool:
        """True if a restraint currently forbids this player action."""
        return self.magic_locked and action.lower() in MAGIC_ACTIONS

    # -- mouse / hover ------------------------------------------------------
    def poll_mouse(self) -> tuple[int, int]:
        """Read pygame.mouse.get_pos() (lazy import; falls back to last known)."""
        try:
            import pygame
        except ImportError:
            return self.mouse_pos
        try:
            pos = pygame.mouse.get_pos()
            surface = pygame.display.get_surface()
        except pygame.error:
            return self.mouse_pos
        self.mouse_pos = (int(pos[0]), int(pos[1]))
        if surface is not None:
            self.screen_size = surface.get_size()
        return self.mouse_pos

    def _hit_restraint(self, pos: tuple[int, int]) -> Optional[Restraint]:
        for restraint in reversed(self.restraints):  # last drawn = topmost
            if restraint.hit_test(pos):
                return restraint
        return None

    @property
    def hovered_restraint(self) -> Optional[Restraint]:
        if self.hovered_id is None:
            return None
        for restraint in self.restraints:
            if restraint.uid == self.hovered_id and not restraint.escaped:
                return restraint
        return None

    def get_hovered_restraint(self, mouse_pos: Optional[tuple[int, int]] = None) -> Optional[TooltipData]:
        """Tooltip data for the restraint under the cursor, else None.

        Pass the mouse position explicitly, or omit it to read pygame.mouse.get_pos().
        """
        if mouse_pos is None:
            mouse_pos = self.poll_mouse()
        else:
            self.mouse_pos = (int(mouse_pos[0]), int(mouse_pos[1]))
            mouse_pos = self.mouse_pos
        restraint = self._hit_restraint(mouse_pos)
        self.hovered_id = restraint.uid if restraint is not None else None
        if restraint is None:
            return None
        return self._build_tooltip(restraint, mouse_pos)

    def _build_tooltip(self, restraint: Restraint, mouse_pos: tuple[int, int]) -> TooltipData:
        profile = restraint.profile
        lore_lines = _wrap(profile.lore)
        status_lines = _wrap(restraint.status_text)
        height = (
            TOOLTIP_PADDING
            + 24                                   # title
            + 36                                   # resistance label + bar
            + len(lore_lines) * TOOLTIP_LINE_HEIGHT + 8
            + len(status_lines) * TOOLTIP_LINE_HEIGHT + 8
            + 22                                   # action prompt
            + TOOLTIP_PADDING
        )
        size = (TOOLTIP_WIDTH, height)
        accent = profile.accent
        return TooltipData(
            restraint_id=restraint.uid,
            kind=restraint.kind,
            title=profile.name,
            resistance_value=restraint.durability,
            resistance_max=restraint.max_durability,
            resistance_ratio=restraint.resistance_ratio,
            resistance_text=f"Resistance: {int(round(restraint.durability))} / {int(round(restraint.max_durability))}",
            lore_lines=lore_lines,
            status_lines=status_lines,
            prompt=STRUGGLE_PROMPT,
            accent=accent,
            title_colour=_lighten(accent, 0.35),
            text_colour=(210, 200, 215),
            muted_colour=(150, 140, 160),
            background=(12, 9, 16, 205),
            border=(accent[0], accent[1], accent[2], 230),
            box_pos=_layout_tooltip(mouse_pos, size, self.screen_size),
            box_size=size,
        )

    # -- struggle loop ------------------------------------------------------
    def _pick_target(self) -> Optional[Restraint]:
        hovered = self._hit_restraint(self.mouse_pos)
        if hovered is not None:
            return hovered
        if self.qte is not None and not self.qte.done and not self.qte.restraint.escaped:
            return self.qte.restraint
        active = self.active_restraints
        if len(active) == 1:
            return active[0]
        return None

    def handle_key(self, key: str, text: str = "") -> bool:
        """Route a key press. Returns True if it was consumed by the struggle."""
        if key not in STRUGGLE_KEYS:
            return False
        target = self._pick_target()
        if target is None:
            return False
        if self.qte is not None and (self.qte.done or self.qte.restraint is not target):
            self.cancel_struggle()
        if self.qte is None:
            self.qte = create_struggle_qte(target, self.rng)
            self._events.append(f"struggle_started:{target.profile.name}")
        self.qte.handle_key(key, text)
        self._resolve_qte()
        return True

    def cancel_struggle(self) -> None:
        if self.qte is not None:
            self.qte.abandon()
            self.qte = None

    def _resolve_qte(self) -> None:
        qte = self.qte
        if qte is None or not qte.done:
            return
        name = qte.restraint.profile.name
        if qte.success:
            qte.restraint.announced = True
            self._events.append(f"escaped:{name}")
        else:
            self._events.append(f"failed:{name}")
        self.last_qte = qte
        self.qte = None

    # -- per-frame ----------------------------------------------------------
    def update(self, dt: float) -> float:
        """Advance everything. Returns HP drained this frame (fractional)."""
        dt = max(0.0, dt)
        drain = 0.0
        for restraint in self.restraints:
            drain += restraint.update(dt)
        if self.qte is not None:
            self.qte.update(dt)
            self._resolve_qte()
        for restraint in self.restraints:
            if restraint.escaped and not restraint.announced:
                restraint.announced = True
                self._events.append(f"released:{restraint.profile.name}")
        self.restraints = [r for r in self.restraints if not r.escaped]
        if self.hovered_id is not None and self.hovered_restraint is None:
            self.hovered_id = None
        self._hp_accum += drain
        return drain

    def take_hp_damage(self) -> int:
        """Whole HP points accumulated from draining restraints (keeps the remainder)."""
        whole = int(self._hp_accum)
        self._hp_accum -= whole
        return whole

    def pop_events(self) -> list[str]:
        events, self._events = self._events, []
        return events

    # -- render helpers -----------------------------------------------------
    def render_states(self) -> list[dict[str, Any]]:
        return [r.render_state() for r in self.restraints]

    def all_tension_segments(self) -> Sequence[TensionSegment]:
        segments: list[TensionSegment] = []
        for restraint in self.active_restraints:
            segments.extend(restraint.tension_segments())
        return segments


__all__ = [
    "ARROWS", "WORDS", "MAGIC_ACTIONS", "STRUGGLE_KEYS", "STRUGGLE_PROMPT",
    "QTE", "TypingQTE", "MashQTE", "TimingQTE", "MemoryQTE", "create_qte", "ANGEL_WORDS",
    "RestraintKind", "RestraintProfile", "RESTRAINT_PROFILES",
    "Restraint", "TensionSegment", "create_restraint",
    "StruggleQTE", "create_struggle_qte",
    "TooltipData", "RestraintManager",
]
