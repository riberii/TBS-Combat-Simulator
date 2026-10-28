"""Party data, gold, inventory, difficulty, encounters, turn queue and the setup model."""
from __future__ import annotations

import json
import math
import random
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from core import story
from core.config import BOSS_STAGES, DIFFICULTIES, FINAL_STAGE, MAX_PARTY, Color, Pal, PlayerClass
from entities.base_entity import BaseEntity
from entities.enemy import Enemy
from entities.player import FallenAngel, Player, Restraint, create_player
from systems.inventory_system import Inventory

# ---- endless-mode tuning -----------------------------------------------------
BOSS_INTERVAL = 4                # after FINAL_STAGE, every Nth stage is a boss stage
ENDLESS_THREAT_GROWTH = 0.05     # +5% enemy threat per stage beyond FINAL_STAGE
MAX_THREAT_SCALE = 6.0
MIN_THREAT_SCALE = 0.25
BASE_RECOVERY = 0.5              # fraction restored by rest_party (original behaviour)
BOSS_RECOVERY_BONUS = 0.25
ENDLESS_ATTRITION_PER_STAGE = 0.01
ENDLESS_ATTRITION_CAP = 0.15
MIN_RECOVERY = 0.25
MAX_RECOVERY = 1.0
BOSS_BOUNTY_PER_STAGE = 15       # extra gold per stage number for endless boss kills

SAVE_VERSION = 1
_SUPPORTED_SAVE_VERSIONS = frozenset({1})
_MAX_NAME_LEN = 64
_MISSING = object()

_ENDLESS_INTROS: tuple[str, ...] = (
    "The Abyss folds in on itself, and the path ahead is one you have not walked.",
    "Something older than the dark stirs beyond the next threshold.",
    "The stones remember your footsteps, yet the corridor is new.",
    "A cold wind carries whispers of those who descended before you.",
    "The depths refuse to end, and neither, it seems, do you.",
    "Light gutters. The dark leans closer, curious.",
)
_FALLBACK_BOSS_INTRO = "A towering presence bars the way, vast and patient."


class SaveDataError(ValueError):
    """Raised when serialized game data is malformed or inconsistent."""


class UnsupportedSaveVersionError(SaveDataError):
    """Raised when serialized game data comes from an unsupported save version."""


# ---- encounter modifiers -------------------------------------------------------
@dataclass(frozen=True)
class EncounterModifier:
    key: str
    label: str
    description: str
    group: str              # at most one modifier per group is active at a time
    threat: float = 1.0     # multiplies the difficulty passed to Enemy.spawn_wave
    gold: float = 1.0
    xp: float = 1.0
    recovery: float = 0.0   # added to the rest_party fraction


_MODIFIERS: tuple[EncounterModifier, ...] = (
    EncounterModifier("hardened", "Hardened Foes", "Enemies are tougher, but the spoils are richer.",
                      "threat", threat=1.2, gold=1.2, xp=1.2),
    EncounterModifier("feeble", "Feeble Foes", "Enemies are weakened, and the rewards are slimmer.",
                      "threat", threat=0.85, gold=0.9, xp=0.9),
    EncounterModifier("relentless", "Relentless Onslaught", "A savage assault that leaves little time to recover.",
                      "threat", threat=1.35, gold=1.4, xp=1.4, recovery=-0.05),
    EncounterModifier("plunder", "Hoarded Plunder", "The enemies guard a glittering hoard.",
                      "reward", gold=1.5),
    EncounterModifier("scholar", "Echoes of Knowledge", "Old battles echo here, teaching those who survive.",
                      "reward", xp=1.5),
    EncounterModifier("grim", "Grim Attrition", "The air saps strength, but danger pays well.",
                      "recovery", gold=1.25, xp=1.25, recovery=-0.15),
    EncounterModifier("sanctuary", "Hallowed Ground", "A faint sanctuary eases the aftermath.",
                      "recovery", gold=0.9, xp=0.9, recovery=0.2),
)
_MODIFIER_INDEX: dict[str, EncounterModifier] = {m.key: m for m in _MODIFIERS}
_MAX_ACTIVE_MODIFIERS = len({m.group for m in _MODIFIERS})


# ---- serialization helpers -----------------------------------------------------
class _Unencodable(Exception):
    """Internal: a value cannot be represented in the save format."""


def _encode_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"__enum__": value.name}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _Unencodable
        return value
    kind = type(value)
    if kind is list:
        return [_encode_value(v) for v in value]
    if kind is tuple:
        return {"__tuple__": [_encode_value(v) for v in value]}
    if kind in (set, frozenset):
        items = [_encode_value(v) for v in value]
        items.sort(key=lambda x: json.dumps(x, sort_keys=True))
        return {"__set__": items}
    if kind is dict:
        if not all(isinstance(k, str) for k in value):
            raise _Unencodable
        return {"__dict__": {k: _encode_value(v) for k, v in value.items()}}
    raise _Unencodable


def _enum_hint(ref: Any) -> Optional[type]:
    if isinstance(ref, Enum):
        return type(ref)
    if isinstance(ref, (list, tuple, set, frozenset)) and ref:
        first = next(iter(ref))
        return type(first) if isinstance(first, Enum) else None
    if isinstance(ref, dict) and ref:
        first = next(iter(ref.values()))
        return type(first) if isinstance(first, Enum) else None
    return None


def _decode_generic(raw: Any, hint: Optional[type], path: str) -> Any:
    if raw is None or isinstance(raw, (bool, int, str)):
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise SaveDataError(f"{path}: non-finite number")
        return raw
    if isinstance(raw, list):
        return [_decode_generic(v, hint, path) for v in raw]
    if isinstance(raw, dict) and len(raw) == 1:
        (tag, body), = raw.items()
        if tag == "__enum__":
            if hint is None or not isinstance(body, str) or body not in hint.__members__:
                raise SaveDataError(f"{path}: invalid enum value {body!r}")
            return hint[body]
        if tag == "__tuple__" and isinstance(body, list):
            return tuple(_decode_generic(v, hint, path) for v in body)
        if tag == "__set__" and isinstance(body, list):
            try:
                return frozenset(_decode_generic(v, hint, path) for v in body)
            except TypeError as exc:
                raise SaveDataError(f"{path}: unhashable set member") from exc
        if tag == "__dict__" and isinstance(body, dict):
            return {str(k): _decode_generic(v, hint, path) for k, v in body.items()}
    raise SaveDataError(f"{path}: unrecognised encoded value")


def _coerce_to_ref(value: Any, ref: Any, path: str) -> Any:
    """Check the decoded value against the live attribute's type; return the (possibly converted) value."""
    if value is None or ref is None:
        return value
    if isinstance(ref, Enum):
        ok = isinstance(value, type(ref))
    elif isinstance(ref, bool):
        ok = isinstance(value, bool)
    elif isinstance(ref, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(ref, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if ok:
            return float(value)
    elif isinstance(ref, str):
        ok = isinstance(value, str)
    elif isinstance(ref, list):
        ok = isinstance(value, list)
    elif isinstance(ref, tuple):
        ok = isinstance(value, tuple)
    elif isinstance(ref, (set, frozenset)):
        ok = isinstance(value, (set, frozenset))
        if ok:
            return type(ref)(value)
    elif isinstance(ref, dict):
        ok = isinstance(value, dict)
    else:
        ok = False
    if not ok:
        raise SaveDataError(f"{path}: type mismatch (expected {type(ref).__name__}, got {type(value).__name__})")
    return value


def _snapshot_attrs(obj: Any) -> tuple[dict[str, Any], list[str]]:
    """Encode every serialisable instance attribute; return (data, names that could not be encoded)."""
    live = getattr(obj, "__dict__", None)
    if live is None:
        return {}, ["<no __dict__>"]
    data: dict[str, Any] = {}
    skipped: list[str] = []
    for key in sorted(live):
        value = live[key]
        if callable(value):
            skipped.append(key)
            continue
        try:
            data[key] = _encode_value(value)
        except _Unencodable:
            skipped.append(key)
    return data, skipped


# Empty containers and optional fields have no live enum value from which to infer a type.
# Keep explicit hints for those attributes so their serialized enum names can round-trip.
_SAVE_ENUM_HINTS: dict[type, dict[str, type[Enum]]] = {
    FallenAngel: {"restraints": Restraint, "struggle_target": Restraint},
}


def _apply_attrs(obj: Any, data: dict[str, Any], label: str) -> None:
    live = getattr(obj, "__dict__", None)
    if live is None:
        raise SaveDataError(f"{label}: cannot restore attributes onto {type(obj).__name__}")
    for key, raw in data.items():
        if not isinstance(key, str):
            raise SaveDataError(f"{label}: attribute names must be strings")
        if key not in live:
            continue  # field no longer exists in this build; ignore for forward compatibility
        ref = live[key]
        path = f"{label}.{key}"
        hint = _enum_hint(ref) or _SAVE_ENUM_HINTS.get(type(obj), {}).get(key)
        value = _decode_generic(raw, hint, path)
        setattr(obj, key, _coerce_to_ref(value, ref, path))


def _require_json(data: Any, label: str) -> None:
    try:
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise SaveDataError(f"{label}: to_dict() output is not JSON-serialisable") from exc


def _has_hooks(obj: Any) -> bool:
    return callable(getattr(obj, "to_dict", None)) and callable(getattr(type(obj), "from_dict", None))


def _dump_component(obj: Any, label: str) -> dict[str, Any]:
    if _has_hooks(obj):
        data = obj.to_dict()
        if not isinstance(data, dict):
            raise SaveDataError(f"{label}: to_dict() must return a dict")
        _require_json(data, label)
        return {"mode": "hooks", "data": data}
    attrs, skipped = _snapshot_attrs(obj)
    return {"mode": "attrs", "data": attrs, "skipped": skipped}


def _load_component(fresh: Any, payload: Any, label: str, expected: type) -> Any:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise SaveDataError(f"{label}: malformed component payload")
    mode, data = payload.get("mode"), payload["data"]
    if mode == "hooks":
        factory = getattr(type(fresh), "from_dict", None)
        if not callable(factory):
            raise SaveDataError(f"{label}: saved with from_dict hooks that are unavailable in this build")
        try:
            obj = factory(data)
        except SaveDataError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise SaveDataError(f"{label}: from_dict failed: {exc}") from exc
        if not isinstance(obj, expected):
            raise SaveDataError(f"{label}: from_dict returned {type(obj).__name__}")
        return obj
    if mode == "attrs":
        _apply_attrs(fresh, data, label)
        return fresh
    raise SaveDataError(f"{label}: unknown payload mode {mode!r}")


def _get_int(data: dict[str, Any], key: str, *, minimum: int = 0, default: Any = _MISSING) -> int:
    if key not in data:
        if default is _MISSING:
            raise SaveDataError(f"missing field '{key}'")
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SaveDataError(f"field '{key}' must be an integer >= {minimum}")
    return value


def _get_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise SaveDataError(f"field '{key}' must be a boolean")
    return value


def _migrate_save(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the save version. Extend here (version -> upgraded dict) when SAVE_VERSION is bumped."""
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise SaveDataError("missing or invalid save 'version'")
    if version not in _SUPPORTED_SAVE_VERSIONS:
        raise UnsupportedSaveVersionError(
            f"unsupported save version {version}; supported: {sorted(_SUPPORTED_SAVE_VERSIONS)}"
        )
    return data


# ---- setup wizard --------------------------------------------------------------
@dataclass
class PlayerConfig:
    name: str
    pclass: PlayerClass


class SetupStep(Enum):
    COUNT = 0
    DIFFICULTY = 1
    CLASS = 2
    NAME = 3


class SetupModel:
    """State of the party-creation wizard (party size, difficulty, class + name per player)."""

    def __init__(self) -> None:
        self.step = SetupStep.COUNT
        self.count = 1
        self.diff_names = list(DIFFICULTIES)
        self.diff_idx = 1
        self.classes = list(PlayerClass)
        self.class_idx = 0
        self.name = ""
        self.configs: list[PlayerConfig] = []

    @property
    def slot(self) -> int:
        return len(self.configs)

    @property
    def difficulty(self) -> str:
        return self.diff_names[self.diff_idx]

    def move(self, delta: int) -> None:
        if self.step is SetupStep.COUNT:
            self.count = (self.count - 1 + delta) % MAX_PARTY + 1
        elif self.step is SetupStep.DIFFICULTY:
            self.diff_idx = (self.diff_idx + delta) % len(self.diff_names)
        elif self.step is SetupStep.CLASS:
            self.class_idx = (self.class_idx + delta) % len(self.classes)

    def type_char(self, ch: str) -> None:
        if self.step is SetupStep.NAME and ch.isprintable() and len(self.name) < 14:
            self.name += ch

    def backspace(self) -> None:
        self.name = self.name[:-1]

    def confirm(self) -> bool:
        """Advance the wizard. Returns True when the whole party is configured."""
        if self.step is SetupStep.COUNT:
            self.step = SetupStep.DIFFICULTY
        elif self.step is SetupStep.DIFFICULTY:
            self.step = SetupStep.CLASS
        elif self.step is SetupStep.CLASS:
            self.step = SetupStep.NAME
        else:
            name = self.name.strip() or f"Hero {self.slot + 1}"
            self.configs.append(PlayerConfig(name, self.classes[self.class_idx]))
            self.name = ""
            if len(self.configs) >= self.count:
                return True
            self.step = SetupStep.CLASS
        return False

    def back(self) -> None:
        if self.step is SetupStep.NAME:
            self.step = SetupStep.CLASS
        elif self.step is SetupStep.CLASS and not self.configs:
            self.step = SetupStep.DIFFICULTY
        elif self.step is SetupStep.DIFFICULTY:
            self.step = SetupStep.COUNT


class TurnQueue:
    """Ordered list of actors for the current round (heroes by speed, then enemies by speed)."""

    def __init__(self) -> None:
        self.entries: list[BaseEntity] = []
        self.index = 0

    def build(self, players: list[Player], enemies: list[Enemy]) -> None:
        heroes = sorted((p for p in players if p.alive), key=lambda e: -e.speed)
        foes = sorted((e for e in enemies if e.alive), key=lambda e: -e.speed)
        self.entries = [*heroes, *foes]
        self.index = 0

    @property
    def current(self) -> Optional[BaseEntity]:
        return self.entries[self.index] if self.index < len(self.entries) else None

    def advance(self) -> bool:
        """Move to the next actor. False when the round is over."""
        self.index += 1
        return self.index < len(self.entries)


@dataclass
class LogEntry:
    text: str
    color: Color


class GameState:
    """Everything that persists across encounters in a run."""

    def __init__(self, seed: Optional[int] = None) -> None:
        if seed is None:
            seed = random.SystemRandom().getrandbits(63)
        self.seed: int | str = seed if isinstance(seed, (int, str)) else str(seed)
        self.run_id = uuid.uuid4().hex
        self.rng = random.Random(seed)
        self.players: list[Player] = []
        self.enemies: list[Enemy] = []
        self.inventory = Inventory()
        self.queue = TurnQueue()
        self.gold = 0
        self.stage = 0
        self.difficulty_name = "Normal"
        self.log: deque[LogEntry] = deque(maxlen=300)
        # progression flags
        self.endless = True
        self.campaign_cleared = False
        self.bosses_defeated = 0
        self.best_stage = 0
        self.modifiers: list[str] = []  # keys of EncounterModifier active for the current stage
        self.pet: Optional[str] = None
        self.skin: str = "default"
        self.run_mode: str = "endless" if self.endless else "story"
        self.merchant_heals_used: int = 0
        self.elites_slain: int = 0
        self.party_deaths: int = 0
        self.lowest_hero_hp: int = 999

    # ---- properties -------------------------------------------------------
    @property
    def difficulty(self) -> float:
        return DIFFICULTIES[self.difficulty_name]

    @property
    def has_angel(self) -> bool:
        return any(isinstance(p, FallenAngel) for p in self.players)

    @property
    def party_alive(self) -> bool:
        return any(p.alive for p in self.players)

    @property
    def run_complete(self) -> bool:
        """Always False in endless mode; legacy (non-endless) runs still end at FINAL_STAGE."""
        if self.endless:
            return False
        return self.stage >= FINAL_STAGE and not any(e.alive for e in self.enemies)

    @property
    def endless_depth(self) -> int:
        """Stages beyond the original campaign (0 while inside it or in legacy mode)."""
        return max(0, self.stage - FINAL_STAGE) if self.endless else 0

    @property
    def active_modifiers(self) -> tuple[EncounterModifier, ...]:
        return tuple(_MODIFIER_INDEX[k] for k in self.modifiers if k in _MODIFIER_INDEX)

    def add_log(self, text: str, color: Color = Pal.TEXT) -> None:
        self.log.append(LogEntry(text, color))

    # ---- stage planning (pure functions of seed + stage) --------------------
    def is_boss_stage(self, stage: int) -> bool:
        if stage in BOSS_STAGES:
            return True
        return self.endless and stage > FINAL_STAGE and (stage - FINAL_STAGE) % BOSS_INTERVAL == 0

    def _plan_rng(self, kind: str, stage: int) -> random.Random:
        return random.Random(f"{self.seed}:{kind}:{stage}")

    def _plan_modifiers(self, stage: int) -> tuple[EncounterModifier, ...]:
        if not self.endless or stage <= FINAL_STAGE:
            return ()
        rng = self._plan_rng("mods", stage)
        wanted = 2 if stage % 5 == 0 else 1
        pool = list(_MODIFIERS)
        rng.shuffle(pool)
        picked: list[EncounterModifier] = []
        groups: set[str] = set()
        for mod in pool:
            if mod.group in groups:
                continue
            picked.append(mod)
            groups.add(mod.group)
            if len(picked) >= wanted:
                break
        return tuple(picked)

    def _wave_template_stage(self, stage: int) -> int:
        """Stage number handed to Enemy.spawn_wave; endless stages reuse valid late-campaign templates."""
        if not self.endless or stage <= FINAL_STAGE:
            return stage
        if self.is_boss_stage(stage):
            bosses = sorted(s for s in BOSS_STAGES if s <= FINAL_STAGE) or [FINAL_STAGE]
            idx = ((stage - FINAL_STAGE) // BOSS_INTERVAL - 1) % len(bosses)
            return bosses[idx]
        eligible = [s for s in range(max(1, FINAL_STAGE // 2), FINAL_STAGE) if s not in BOSS_STAGES]
        if not eligible:
            return max(1, FINAL_STAGE - 1)
        return self._plan_rng("wave", stage).choice(eligible)

    def _wave_difficulty(self) -> float:
        depth = self.endless_depth
        if depth <= 0:
            return self.difficulty
        scale = 1.0 + ENDLESS_THREAT_GROWTH * depth
        for mod in self.active_modifiers:
            scale *= mod.threat
        return self.difficulty * min(max(scale, MIN_THREAT_SCALE), MAX_THREAT_SCALE)

    def _reward_multipliers(self) -> tuple[float, float]:
        gold = xp = 1.0
        if self.endless_depth > 0:
            for mod in self.active_modifiers:
                gold *= mod.gold
                xp *= mod.xp
        return gold, xp

    def _recovery_fraction(self) -> float:
        depth = self.endless_depth
        if depth <= 0:
            return BASE_RECOVERY
        fraction = BASE_RECOVERY - min(ENDLESS_ATTRITION_CAP, ENDLESS_ATTRITION_PER_STAGE * depth)
        if self.is_boss_stage(self.stage):
            fraction += BOSS_RECOVERY_BONUS
        fraction += sum(m.recovery for m in self.active_modifiers)
        return min(max(fraction, MIN_RECOVERY), MAX_RECOVERY)

    def _stage_intro(self, stage: int) -> str:
        intro = story.STAGE_INTROS.get(stage)
        if intro is None:
            if self.endless and stage > FINAL_STAGE:
                intro = self._plan_rng("intro", stage).choice(_ENDLESS_INTROS)
            else:
                intro = "The dark deepens."
        return intro

    def _boss_intro(self, stage: int) -> str:
        intro = story.BOSS_INTROS.get(stage)
        if intro is not None:
            return intro
        keys = sorted(story.BOSS_INTROS)
        if not keys:
            return _FALLBACK_BOSS_INTRO
        n = max(0, (stage - FINAL_STAGE) // BOSS_INTERVAL - 1)
        return story.BOSS_INTROS[keys[n % len(keys)]]

    # ---- run lifecycle ----------------------------------------------------
    def new_run(self, configs: list[PlayerConfig], difficulty: str, *, endless: bool = True) -> None:
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty {difficulty!r}")
        if not 1 <= len(configs) <= MAX_PARTY:
            raise ValueError(f"Party size must be between 1 and {MAX_PARTY}")
        self.players = [create_player(c.name, c.pclass) for c in configs]
        self.run_id = uuid.uuid4().hex
        names = list(DIFFICULTIES)
        self.difficulty_name = difficulty
        if self.has_angel and names.index(difficulty) < len(names) - 1:
            self.difficulty_name = names[names.index(difficulty) + 1]
            self.add_log(f"The Abyss rejects '{difficulty}'. Difficulty raised to {self.difficulty_name}.", Pal.PURPLE)
        self.gold = 120
        self.stage = 0
        self.enemies = []
        self.queue = TurnQueue()
        self.endless = endless
        if getattr(self, "run_mode", "") in ("", "story", "endless"):
            self.run_mode = "endless" if endless else "story"
        self.campaign_cleared = False
        self.bosses_defeated = 0
        self.best_stage = 0
        self.modifiers = []
        self.merchant_heals_used = 0
        self.elites_slain = 0
        self.party_deaths = 0
        self.lowest_hero_hp = 999
        self.inventory = Inventory()
        self.inventory.add("health", 2)
        self.inventory.add("mana", 1)
        if self.has_angel:
            self.inventory.add("cutters")
            self.inventory.add("lucid")

    def spawn_encounter(self) -> str:
        """Advance to the next stage, build its enemies and return the intro text."""
        self.stage += 1
        self.best_stage = max(self.best_stage, self.stage)
        self.modifiers = [m.key for m in self._plan_modifiers(self.stage)]
        # Endless bosses reuse the tuned campaign stage templates, but their identity
        # must continue rotating through the complete roster after stage 12.
        boss_ordinal = None
        if self.is_boss_stage(self.stage):
            boss_ordinal = max(0, (self.stage - min(BOSS_STAGES)) // BOSS_INTERVAL)
        self.enemies = Enemy.spawn_wave(
            self._wave_template_stage(self.stage), len(self.players), self._wave_difficulty(), self.rng,
            boss_ordinal=boss_ordinal,
        )
        self.queue = TurnQueue()
        text = self._stage_intro(self.stage)
        if self.is_boss_stage(self.stage):
            text += "\n\n" + self._boss_intro(self.stage)
            if self.stage == FINAL_STAGE and self.has_angel:
                text += "\n" + story.ANGEL_BOSS_LINE
        for mod in self.active_modifiers:
            text += f"\n\nOmen - {mod.label}: {mod.description}"
        return text

    def claim_victory(self) -> list[str]:
        """Award gold/XP for the defeated wave. Returns summary lines.

        Idempotent per wave: claiming the same wave again awards nothing and returns ``[]``.
        The marker is transient (never serialised); a new or replaced wave can always be claimed.
        """
        if self.enemies and getattr(self, "_rewarded_wave", None) is self.enemies:
            return []
        self._rewarded_wave = self.enemies
        base_gold = sum((25 + 10 * self.stage) * (2 if e.boss else 1) for e in self.enemies)
        base_xp = sum((30 + 10 * self.stage) * (2 if e.boss else 1) for e in self.enemies)
        gold_mult, xp_mult = self._reward_multipliers()
        pet_mult = 1.20 if getattr(self, "pet", None) == "raven" else 1.0
        gold = int(round(base_gold * gold_mult * pet_mult))
        xp = int(round(base_xp * xp_mult))
        bounty = 0
        if self.endless_depth > 0 and self.is_boss_stage(self.stage):
            bounty = BOSS_BOUNTY_PER_STAGE * self.stage
            gold += bounty
        self.gold += gold
        lines = [f"Victory! +{gold} gold, +{xp} XP each."]
        mods = self.active_modifiers if self.endless_depth > 0 else ()
        if mods:
            lines.append("Omens: " + ", ".join(m.label for m in mods) + ".")
        if bounty:
            lines.append(f"Boss bounty: +{bounty} gold (included above).")
        if any(e.boss for e in self.enemies):
            self.bosses_defeated += 1
        if self.endless and not self.campaign_cleared and self.stage >= FINAL_STAGE:
            self.campaign_cleared = True
            lines.append("The campaign is won, yet the Abyss descends further still.")
        for p in self.players:
            if p.alive and p.gain_xp(xp):
                lines.append(f"{p.name} reaches level {p.level}!")
            p.after_battle()
        return lines

    def rest_party(self) -> None:
        """Between-battle recovery; the fallen rise at half health (endless stages adjust the fraction)."""
        fraction = self._recovery_fraction()
        for p in self.players:
            p.rest(fraction)

    # ---- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable snapshot of the run.

        Enemies are not stored: if an encounter is in progress, the save records the previous
        stage so that spawn_encounter() restarts the same stage on load.
        """
        in_encounter = any(e.alive for e in self.enemies)
        stage = max(0, self.stage - 1) if in_encounter else self.stage
        rng_version, rng_internal, rng_gauss = self.rng.getstate()
        players = [
            {
                "name": p.name,
                "class": self._class_of(p).name,
                "state": _dump_component(p, f"players[{i}]"),
            }
            for i, p in enumerate(self.players)
        ]
        return {
            "version": SAVE_VERSION,
            "seed": self.seed,
            "run_id": self.run_id,
            "pet": self.pet,
            "skin": getattr(self, "skin", "default"),
            "run_mode": getattr(self, "run_mode", "story"),
            "rng_state": [rng_version, list(rng_internal), rng_gauss],
            "difficulty": self.difficulty_name,
            "gold": self.gold,
            "stage": stage,
            "in_encounter": in_encounter,
            "endless": self.endless,
            "campaign_cleared": self.campaign_cleared,
            "bosses_defeated": self.bosses_defeated,
            "best_stage": self.best_stage,
            "merchant_heals_used": getattr(self, "merchant_heals_used", 0),
            "elites_slain": getattr(self, "elites_slain", 0),
            "party_deaths": getattr(self, "party_deaths", 0),
            "lowest_hero_hp": getattr(self, "lowest_hero_hp", 999),
            "modifiers": [] if in_encounter else list(self.modifiers),
            "players": players,
            "inventory": _dump_component(self.inventory, "inventory"),
            # Optional in older v1 saves; keeps the in-run action/chat history across Continue.
            "log": [
                {"text": entry.text, "color": list(entry.color)}
                for entry in list(self.log)[-300:]
            ],
        }

    @staticmethod
    def _class_of(player: Player) -> PlayerClass:
        pclass = getattr(player, "pclass", None)
        if not isinstance(pclass, PlayerClass):
            raise SaveDataError(f"player {getattr(player, 'name', '?')!r} has no PlayerClass 'pclass' attribute")
        return pclass

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        """Build a GameState from to_dict() output. Raises SaveDataError / UnsupportedSaveVersionError."""
        if not isinstance(data, dict):
            raise SaveDataError("save data must be a dict")
        data = _migrate_save(data)

        difficulty = data.get("difficulty")
        if not isinstance(difficulty, str) or difficulty not in DIFFICULTIES:
            raise SaveDataError(f"invalid difficulty {difficulty!r}")
        seed = data.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, (int, str)):
            raise SaveDataError("field 'seed' must be an int or string")

        state = cls(seed)
        run_id = data.get("run_id")
        if run_id is not None and (not isinstance(run_id, str) or not run_id or len(run_id) > 96):
            raise SaveDataError("field 'run_id' must be a non-empty string up to 96 characters")
        if isinstance(run_id, str):
            state.run_id = run_id
        state.pet = data.get("pet")
        state.skin = str(data.get("skin") or "default")
        state.run_mode = str(data.get("run_mode") or "story")
        state.difficulty_name = difficulty
        state.gold = _get_int(data, "gold")
        state.stage = _get_int(data, "stage")
        state.endless = _get_bool(data, "endless", True)
        state.campaign_cleared = _get_bool(data, "campaign_cleared", False)
        state.bosses_defeated = _get_int(data, "bosses_defeated", default=0)
        state.best_stage = max(_get_int(data, "best_stage", default=0), state.stage)
        state.merchant_heals_used = int(data.get("merchant_heals_used", 0))
        state.elites_slain = int(data.get("elites_slain", 0))
        state.party_deaths = int(data.get("party_deaths", 0))
        state.lowest_hero_hp = int(data.get("lowest_hero_hp", 999))
        if not state.endless and state.stage > FINAL_STAGE:
            raise SaveDataError("non-endless run cannot be beyond the final stage")

        # modifiers
        mods = data.get("modifiers", [])
        if not isinstance(mods, list) or not all(isinstance(k, str) for k in mods):
            raise SaveDataError("field 'modifiers' must be a list of strings")
        if len(set(mods)) != len(mods) or len(mods) > _MAX_ACTIVE_MODIFIERS:
            raise SaveDataError("field 'modifiers' has duplicates or too many entries")
        if any(k not in _MODIFIER_INDEX for k in mods):
            raise SaveDataError("field 'modifiers' contains unknown modifiers")
        if mods and state.endless_depth <= 0:
            raise SaveDataError("modifiers are only valid in endless stages")
        state.modifiers = list(mods)

        # players
        raw_players = data.get("players")
        if not isinstance(raw_players, list) or not 1 <= len(raw_players) <= MAX_PARTY:
            raise SaveDataError(f"'players' must be a list of 1..{MAX_PARTY} entries")
        for i, entry in enumerate(raw_players):
            label = f"players[{i}]"
            if not isinstance(entry, dict):
                raise SaveDataError(f"{label}: must be a dict")
            name, class_name = entry.get("name"), entry.get("class")
            if not isinstance(name, str) or not 0 < len(name) <= _MAX_NAME_LEN:
                raise SaveDataError(f"{label}: invalid name")
            if not isinstance(class_name, str) or class_name not in PlayerClass.__members__:
                raise SaveDataError(f"{label}: unknown class {class_name!r}")
            try:
                fresh = create_player(name, PlayerClass[class_name])
            except (KeyError, TypeError, ValueError) as exc:
                raise SaveDataError(f"{label}: cannot create player: {exc}") from exc
            state.players.append(_load_component(fresh, entry.get("state"), label, Player))

        # inventory
        state.inventory = _load_component(Inventory(), data.get("inventory"), "inventory", Inventory)

        # Action/chat history is optional for backward compatibility with earlier v1 saves.
        raw_log = data.get("log", [])
        if not isinstance(raw_log, list) or len(raw_log) > 300:
            raise SaveDataError("field 'log' must be a list containing at most 300 entries")
        for i, entry in enumerate(raw_log):
            if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
                raise SaveDataError(f"log[{i}] must contain string text")
            raw_color = entry.get("color", list(Pal.TEXT))
            if (not isinstance(raw_color, (list, tuple)) or len(raw_color) != 3 or
                    any(isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in raw_color)):
                raise SaveDataError(f"log[{i}].color must be an RGB triple")
            state.log.append(LogEntry(entry["text"], tuple(raw_color)))

        # RNG (optional: falls back to the seeded generator)
        raw_rng = data.get("rng_state")
        if raw_rng is not None:
            try:
                version, internal, gauss = raw_rng
                if (
                    isinstance(version, bool) or not isinstance(version, int)
                    or not isinstance(internal, list) or len(internal) != 625
                    or not all(isinstance(v, int) and not isinstance(v, bool) for v in internal)
                    or not (gauss is None or (isinstance(gauss, (int, float)) and not isinstance(gauss, bool)))
                ):
                    raise ValueError("malformed")
                state.rng.setstate((version, tuple(internal), gauss))
            except (TypeError, ValueError) as exc:
                raise SaveDataError("field 'rng_state' is invalid") from exc
        return state