"""Enemies: archetypes, party/difficulty scaling, telegraphed intents and boss behaviour."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from core.config import (BOSS_STAGES, PARTY_ATK_SCALE, PARTY_DEF_SCALE, PARTY_HP_SCALE, Color, Pal)
from entities.base_entity import BaseEntity


class IntentKind(Enum):
    ATTACK = "Attack"
    HEAVY = "Crushing Blow"
    MULTI = "Flurry"
    CHARGE = "Gathering Power"
    DEVASTATE = "DEVASTATION"
    CURSE = "Abyssal Curse"
    SKIP = "Dazed"
    GUARD = "Brace"      # self-buff: raises the enemy's defence until its next intent
    RALLY = "Rally"      # support: empowers living allies' next damaging intent


@dataclass(frozen=True)
class Intent:
    kind: IntentKind
    power: float = 1.0
    hits: int = 1

    @property
    def label(self) -> str:
        return self.kind.value

    @property
    def dangerous(self) -> bool:
        return self.kind in (IntentKind.DEVASTATE, IntentKind.CHARGE, IntentKind.CURSE)


INTENTS: dict[IntentKind, Intent] = {
    IntentKind.ATTACK: Intent(IntentKind.ATTACK, 1.0),
    IntentKind.HEAVY: Intent(IntentKind.HEAVY, 1.7),
    IntentKind.MULTI: Intent(IntentKind.MULTI, 0.7, hits=2),
    IntentKind.CHARGE: Intent(IntentKind.CHARGE, 0.0),
    IntentKind.CURSE: Intent(IntentKind.CURSE, 0.0),
    IntentKind.SKIP: Intent(IntentKind.SKIP, 0.0),
    IntentKind.GUARD: Intent(IntentKind.GUARD, 0.0),
    IntentKind.RALLY: Intent(IntentKind.RALLY, 0.0),
}

# Intents whose power is scaled by phase/rally bonuses (DEVASTATE has fixed, pre-balanced power).
_SCALED_DAMAGE = (IntentKind.ATTACK, IntentKind.HEAVY, IntentKind.MULTI)
# Intents that become more likely as the party grows (pressure instead of raw HP).
_PRESSURE_KINDS = (IntentKind.HEAVY, IntentKind.MULTI, IntentKind.CHARGE, IntentKind.CURSE)

ENRAGE_THRESHOLD = 0.40
PHASE2_POWER = 1.15
RALLY_POWER = 1.30
GUARD_DEF_FACTOR = 0.8   # defence bonus = max(2, base_df * factor)
SOFT_STAGE = 16          # beyond this stage HP/DEF growth slows; ATK keeps growing
_WAVE_SHARE = {1: 1.0, 2: 0.65, 3: 0.55}


def _grow(stage: int, rate: float, soft_factor: float = 1.0) -> float:
    """Linear per-stage growth that slows by ``soft_factor`` after SOFT_STAGE (endless-friendly)."""
    n = stage - 1
    knee = SOFT_STAGE - 1
    if n <= knee:
        return rate * n
    return rate * (knee + (n - knee) * soft_factor)


@dataclass(frozen=True)
class Scaling:
    """Multipliers applied to enemy stats for party size and difficulty.

    ``threat`` and ``extra_hits`` convert part of the party-size challenge into
    more dangerous behaviour instead of piling everything onto enemy HP.
    """

    hp: float
    atk: float
    df: float
    threat: float = 1.0
    extra_hits: int = 0

    @classmethod
    def for_party(cls, players: int, difficulty: float) -> "Scaling":
        if not math.isfinite(difficulty) or difficulty <= 0:
            raise ValueError(f"difficulty must be a positive finite number, got {difficulty!r}")
        extra = max(0, int(players) - 1)
        return cls(
            hp=(1 + PARTY_HP_SCALE * extra) * difficulty,
            atk=(1 + PARTY_ATK_SCALE * extra) * difficulty,
            df=(1 + PARTY_DEF_SCALE * extra) * (0.5 + 0.5 * difficulty),
            threat=1.0 + 0.12 * extra * (0.5 + 0.5 * difficulty),
            extra_hits=1 if extra >= 2 else 0,
        )


@dataclass(frozen=True)
class Archetype:
    key: str
    names: tuple[str, ...]
    hp: int
    atk: int
    df: int
    speed: int
    color: Color
    weights: dict[IntentKind, int]
    min_stage: int = 1   # first stage at which regular waves may include this archetype
    sprite: str = ""     # sprite key to use when it differs from ``key``

    @property
    def sprite_key(self) -> str:
        return self.sprite or self.key


ARCHETYPES: dict[str, Archetype] = {
    "beast": Archetype("beast", ("Ashfang Hound", "Cinder Stalker", "Gutter Wolf"), 55, 9, 3, 11,
                       (214, 120, 70), {IntentKind.ATTACK: 5, IntentKind.MULTI: 3, IntentKind.HEAVY: 2}),
    "void": Archetype("void", ("Hollow Wisp", "Voidmaw", "Chorus Shade"), 48, 8, 2, 8,
                      (140, 96, 214), {IntentKind.ATTACK: 4, IntentKind.MULTI: 2, IntentKind.CHARGE: 3}),
    "nature": Archetype("nature", ("Thornwraith", "Rootbound Penitent", "Gravebloom"), 66, 8, 5, 5,
                        (96, 176, 104), {IntentKind.ATTACK: 4, IntentKind.HEAVY: 3, IntentKind.CURSE: 1}),
    # Tank: braces to blunt the party's burst, then punishes with heavy blows.
    "construct": Archetype("construct", ("Gilded Sentinel", "Rusted Warden", "Hollow Bulwark"), 62, 7, 6, 4,
                           (176, 176, 196),
                           {IntentKind.ATTACK: 4, IntentKind.GUARD: 3, IntentKind.HEAVY: 3},
                           min_stage=2),
    # Support: empowers allies and curses; fragile, so killing it first is the counterplay.
    "cultist": Archetype("cultist", ("Ashen Acolyte", "Choir Zealot", "Veiled Cantor"), 44, 7, 2, 9,
                         (214, 176, 90),
                         {IntentKind.ATTACK: 3, IntentKind.RALLY: 3, IntentKind.CURSE: 2, IntentKind.MULTI: 1},
                         min_stage=3),
    # Hunter: swift flanker that executes rapid multi-strikes and heavy punishing blows.
    "hunter": Archetype("hunter", ("Abyssal Stalker", "Shadowblade Zealot", "Dusk Prowler"), 45, 10, 2, 12,
                        (60, 180, 200),
                        {IntentKind.MULTI: 4, IntentKind.HEAVY: 3, IntentKind.ATTACK: 3},
                        min_stage=2),
    # Undead: durable tomb lurker that drains endurance and curses the living.
    "undead": Archetype("undead", ("Charnel Ghoul", "Tomb Carcass", "Wailer of the Crypt"), 72, 7, 4, 4,
                        (120, 150, 130),
                        {IntentKind.ATTACK: 4, IntentKind.CURSE: 3, IntentKind.HEAVY: 2, IntentKind.GUARD: 2},
                        min_stage=3),
    # Cinder: volatile pyre remnant that builds power toward explosive devastation.
    "cinder": Archetype("cinder", ("Pyre Acolyte", "Scorched Imp", "Ashborn Elemental"), 50, 9, 2, 10,
                        (255, 90, 40),
                        {IntentKind.ATTACK: 3, IntentKind.CHARGE: 3, IntentKind.MULTI: 2, IntentKind.CURSE: 1},
                        min_stage=4),
}


@dataclass(frozen=True)
class BossProfile:
    name: str
    sprite: str                              # archetype key used for stats base / sprite
    cycle: tuple[IntentKind, ...]
    enraged_cycle: tuple[IntentKind, ...]


# DEVASTATE is never listed: it always follows CHARGE automatically (see Enemy.choose_intent).
BOSS_CYCLE = (IntentKind.ATTACK, IntentKind.MULTI, IntentKind.CHARGE, IntentKind.HEAVY, IntentKind.CURSE)
BOSS_ENRAGED_CYCLE = (IntentKind.HEAVY, IntentKind.CHARGE, IntentKind.MULTI)

# Bosses rotate through this roster in the order BOSS_STAGES occurs, then loop with a tier suffix.
BOSS_ROSTER: tuple[BossProfile, ...] = (
    # Relentless melee: flurries and heavy blows, one charge per cycle.
    BossProfile("Warden Maelis, the Gilded Jailer", "beast",
                (IntentKind.ATTACK, IntentKind.MULTI, IntentKind.HEAVY, IntentKind.CHARGE, IntentKind.MULTI),
                (IntentKind.MULTI, IntentKind.HEAVY, IntentKind.CHARGE)),
    # Controller: curses in both phases, charge is the punish window.
    BossProfile("Choirmaster Orrick", "void",
                (IntentKind.ATTACK, IntentKind.CURSE, IntentKind.MULTI, IntentKind.CHARGE, IntentKind.HEAVY),
                (IntentKind.CURSE, IntentKind.MULTI, IntentKind.CHARGE, IntentKind.HEAVY)),
    # Classic scripted cycle.
    BossProfile("Vael, the Silent Seraph", "void", BOSS_CYCLE, BOSS_ENRAGED_CYCLE),
    # Bulwark: braces between heavy hits; burst it down while it is exposed.
    BossProfile("Sister Elowen, the Briar Saint", "nature",
                (IntentKind.GUARD, IntentKind.HEAVY, IntentKind.ATTACK, IntentKind.CURSE, IntentKind.CHARGE),
                (IntentKind.HEAVY, IntentKind.CURSE, IntentKind.CHARGE, IntentKind.MULTI)),
)

# Legacy stage -> (name, archetype key) view of the first rotation; spawn_wave uses BOSS_ROSTER.
BOSSES: dict[int, tuple[str, str]] = {
    stage: (p.name, p.sprite) for stage, p in zip((4, 8, 12), BOSS_ROSTER)
}


def _validate_tables() -> None:
    for arch in ARCHETYPES.values():
        if not arch.weights or any(k not in INTENTS or w <= 0 for k, w in arch.weights.items()):
            raise ValueError(f"Archetype {arch.key!r} has invalid intent weights")
    for boss in BOSS_ROSTER:
        if boss.sprite not in ARCHETYPES:
            raise ValueError(f"Boss {boss.name!r} references unknown archetype {boss.sprite!r}")
        for cycle in (boss.cycle, boss.enraged_cycle):
            if not cycle or IntentKind.DEVASTATE in cycle:
                raise ValueError(f"Boss {boss.name!r} has an invalid intent cycle")


_validate_tables()


def _boss_ordinal(stage: int) -> int:
    """Index of ``stage`` within the configured boss cadence (stable rotation key)."""
    try:
        ordered = sorted({int(s) for s in BOSS_STAGES})
    except (TypeError, ValueError):
        ordered = []
    return ordered.index(stage) if stage in ordered else stage


_DEFENSE_ATTRS = ("df", "defense", "defence")


class Enemy(BaseEntity):
    """Scaled foe that announces an Intent each round."""

    def __init__(self, arch: Archetype | str, name: str = "", stage: int = 1,
                 scale: Optional[Scaling] = None, hp_share: float = 1.0,
                 boss: bool = False, profile: Optional[BossProfile] = None, **kwargs) -> None:
        if isinstance(arch, str) and (isinstance(name, (int, float)) or "archetype" in kwargs):
            # Support direct entity instantiation: Enemy(name, hp, atk, df, speed, archetype=...)
            actual_name = arch
            hp = int(name) if isinstance(name, (int, float)) else kwargs.get("hp", kwargs.get("max_hp", 60))
            atk = int(stage) if isinstance(stage, (int, float)) else kwargs.get("attack", kwargs.get("atk", 8))
            df = int(scale) if isinstance(scale, (int, float)) else kwargs.get("defense", kwargs.get("df", 3))
            spd = int(hp_share) if isinstance(hp_share, (int, float)) else kwargs.get("speed", kwargs.get("spd", 5))
            arch_key = kwargs.get("archetype", "construct")
            if arch_key == "normal" or arch_key not in ARCHETYPES:
                arch_key = "construct"
            actual_arch = ARCHETYPES[arch_key]
            super().__init__(actual_name, max(1, hp), max(1, atk), max(0, df), spd)
            self.arch = actual_arch
            self.boss = boss
            self.stage = 1
            self.scale = Scaling(1.0, 1.0, 1.0)
            self.profile = profile
            self.squad = [self]
            self.charging = False
            self.intent = None
            self._cycle = 0
            self._phase_two = False
            self._last_kind = None
            self._rallied_by = None
            self._guard_bonus = 0
            self._guarding = False
            self._df_attr = next((a for a in _DEFENSE_ATTRS
                                  if isinstance(getattr(self, a, None), (int, float))
                                  and not isinstance(getattr(self, a, None), bool)), None)
            return

        if isinstance(arch, str):
            arch = ARCHETYPES.get(arch, ARCHETYPES["construct"])
        if scale is None:
            scale = Scaling(1.0, 1.0, 1.0)
        if stage < 1:
            raise ValueError(f"stage must be >= 1, got {stage}")
        if hp_share <= 0:
            raise ValueError(f"hp_share must be > 0, got {hp_share}")
        hp = (arch.hp + _grow(stage, 17, 0.6)) * scale.hp * hp_share * (2.3 if boss else 1.0)
        atk = (arch.atk + _grow(stage, 1.3)) * scale.atk * (1.15 if boss else 1.0)
        df = (arch.df + _grow(stage, 0.7, 0.5)) * scale.df * (1.1 if boss else 1.0)
        super().__init__(name, max(1, int(hp)), max(1, int(atk)), max(0, int(df)), arch.speed + (2 if boss else 0))
        self.arch = arch
        self.boss = boss
        self.stage = stage
        self.scale = scale
        self.profile = profile
        self.squad = [self]     # wave-mates (including self); set by spawn_wave
        self.charging = False
        self.intent = None
        self._cycle = 0
        self._phase_two = False
        self._last_kind = None
        self._rallied_by = None
        self._guard_bonus = 0
        self._guarding = False
        self._df_attr = next((a for a in _DEFENSE_ATTRS
                              if isinstance(getattr(self, a, None), (int, float))
                              and not isinstance(getattr(self, a, None), bool)), None)

    @property
    def accent(self) -> Color:
        return Pal.RED if self.boss else self.arch.color

    @property
    def tagline(self) -> str:
        return "BOSS" if self.boss else self.arch.key.title()

    @property
    def enraged(self) -> bool:
        return self.boss and self.hp_ratio < ENRAGE_THRESHOLD

    @property
    def phase(self) -> int:
        return 2 if (self._phase_two or self.enraged) else 1

    @property
    def guarding(self) -> bool:
        return self._guarding

    @property
    def _can_guard(self) -> bool:
        return self._df_attr is not None

    # -- intent selection -------------------------------------------------------------------

    def choose_intent(self, rng: random.Random, curse_available: bool) -> Intent:
        """Pick (and telegraph) next action. Bosses follow a scripted cycle."""
        self._release_guard()
        if self.charging:
            self.charging = False
            self._last_kind = IntentKind.DEVASTATE
            return Intent(IntentKind.DEVASTATE, 2.2 if self.boss else 1.6)
        if self.boss:
            if self.enraged and not self._phase_two:
                # Fair phase change: one telegraphed, defensive turn before the enraged cycle starts.
                self._phase_two = True
                self._cycle = 0
                if self._can_guard:
                    return self._telegraph(IntentKind.GUARD)
            kind = self._boss_kind(curse_available)
        else:
            kind = self._pick_kind(rng, curse_available)
        return self._telegraph(kind)

    def _boss_kind(self, curse_available: bool) -> IntentKind:
        if self.profile is not None:
            cycle = self.profile.enraged_cycle if self.enraged else self.profile.cycle
        else:
            cycle = BOSS_ENRAGED_CYCLE if self.enraged else BOSS_CYCLE
        kind = cycle[self._cycle % len(cycle)]
        self._cycle += 1
        if (kind is IntentKind.CURSE and not curse_available) or (kind is IntentKind.GUARD and not self._can_guard):
            kind = IntentKind.ATTACK
        return kind

    def _pick_kind(self, rng: random.Random, curse_available: bool) -> IntentKind:
        allies = self._living_allies()
        pool: dict[IntentKind, float] = {}
        for kind, weight in self.arch.weights.items():
            if kind is IntentKind.CURSE and not curse_available:
                continue
            if kind is IntentKind.GUARD and (not self._can_guard or self._last_kind is IntentKind.GUARD):
                continue
            if kind is IntentKind.RALLY and not any(a._rallied_by is not self for a in allies):
                continue
            w = float(weight)
            if kind in _PRESSURE_KINDS:
                w *= self.scale.threat
            if kind is self._last_kind and kind in (IntentKind.HEAVY, IntentKind.MULTI):
                w *= 0.4   # avoid back-to-back spikes
            if w > 0:
                pool[kind] = w
        if not pool:
            return IntentKind.ATTACK
        return rng.choices(list(pool), weights=list(pool.values()))[0]

    def _telegraph(self, kind: IntentKind) -> Intent:
        """Build the Intent for ``kind`` and apply any effect that takes hold at telegraph time."""
        base = INTENTS[kind]
        power, hits = base.power, base.hits
        if kind is IntentKind.MULTI and self.scale.extra_hits > 0:
            hits += self.scale.extra_hits
            power = round(base.power * base.hits / hits * 1.1, 2)   # more, lighter hits
        if kind in _SCALED_DAMAGE:
            mult = PHASE2_POWER if self.phase == 2 and self.boss else 1.0
            src = self._rallied_by
            if src is not None and src.hp_ratio > 0:
                mult *= RALLY_POWER
            self._rallied_by = None   # consumed (or void if the supporter died)
            power = round(power * mult, 2)
        elif kind is IntentKind.GUARD:
            self._raise_guard()
        elif kind is IntentKind.RALLY:
            for ally in self._living_allies():
                ally._rallied_by = self
        self._last_kind = kind
        if power == base.power and hits == base.hits:
            return base
        return replace(base, power=power, hits=hits)

    # -- guard / rally helpers --------------------------------------------------------------

    def _living_allies(self) -> list["Enemy"]:
        return [e for e in self.squad if e is not self and e.hp_ratio > 0]

    def _raise_guard(self) -> None:
        attr = self._df_attr
        if attr is None or self._guarding:
            return
        current = getattr(self, attr)
        self._guard_bonus = max(2, int(current * GUARD_DEF_FACTOR))
        setattr(self, attr, current + self._guard_bonus)
        self._guarding = True

    def _release_guard(self) -> None:
        attr = self._df_attr
        if self._guarding and attr is not None:
            setattr(self, attr, max(0, getattr(self, attr) - self._guard_bonus))
        self._guard_bonus = 0
        self._guarding = False

    # -- encounter generation ---------------------------------------------------------------

    @classmethod
    def spawn_wave(cls, stage: int, players: int, difficulty: float, rng: random.Random, *,
                   boss_ordinal: Optional[int] = None) -> list["Enemy"]:
        """Create an encounter scaled to party size and difficulty."""
        if not isinstance(rng, random.Random):
            raise TypeError("rng must be a random.Random instance")
        stage = max(1, int(stage))
        players = max(1, int(players))
        scale = Scaling.for_party(players, difficulty)

        if stage in BOSS_STAGES:
            ordinal = _boss_ordinal(stage) if boss_ordinal is None else boss_ordinal
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
                raise ValueError("boss_ordinal must be a non-negative integer")
            tier, idx = divmod(ordinal, len(BOSS_ROSTER))
            profile = BOSS_ROSTER[idx]
            name = profile.name if tier == 0 else f"{profile.name} +{tier}"
            return [cls(ARCHETYPES[profile.sprite], name, stage, scale, 1.0, boss=True, profile=profile)]

        top = max(1, min(players + (1 if stage > 6 else 0), 3))
        low = 2 if (stage >= 10 and top >= 2) else 1
        count = rng.randint(low, top)
        share = _WAVE_SHARE.get(count, 0.55)
        eligible = [a for a in ARCHETYPES.values() if a.min_stage <= stage]
        available = list(eligible)
        used_names: set[str] = set()
        wave: list[Enemy] = []
        for _ in range(count):
            if not available:
                available = list(eligible)
            arch = rng.choice(available)
            available.remove(arch)
            names = [n for n in arch.names if n not in used_names] or list(arch.names)
            name = rng.choice(names)
            used_names.add(name)
            wave.append(cls(arch, name, stage, scale, share))
        for enemy in wave:
            enemy.squad = wave
        return wave
