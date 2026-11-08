"""R2 damage types, affinities and elemental statuses (pure data + tiny helpers, no pygame).

Every damaging action carries a ``DamageType``. Targets have *affinities*: a multiplier per type
(>1 weak, <1 resistant). Elemental hits can also apply a status:

    FIRE   -> BURN        (damage over time; strength scales with the hit)
    FROST  -> CHILL       (target hits 20% weaker)
    STORM  -> SHOCK       (the next hit on the target lands +25% harder, then the shock is spent)
    SHADOW -> SUPPRESSED  (attack power -35% for a turn)
    HOLY   -> (none)      (bonus damage versus the unholy instead)
    PHYSICAL has no status.

A weakness hit always applies its status; a neutral hit does with ``BASE_STATUS_CHANCE``; a resisted hit never does.
All randomness goes through the combat RNG, so fights stay seed-reproducible.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Final, Optional

from core.config import Color


class DamageType(Enum):
    PHYSICAL = "Physical"
    FIRE = "Fire"
    FROST = "Frost"
    STORM = "Storm"
    HOLY = "Holy"
    SHADOW = "Shadow"

    @property
    def color(self) -> Color:
        return DAMAGE_COLORS[self]

    @property
    def short(self) -> str:
        return {"Physical": "PHYS", "Fire": "FIRE", "Frost": "FROST", "Storm": "STORM",
                "Holy": "HOLY", "Shadow": "SHDW"}[self.value]


DAMAGE_COLORS: Final[dict[DamageType, Color]] = {
    DamageType.PHYSICAL: (225, 215, 205),
    DamageType.FIRE: (255, 140, 60),
    DamageType.FROST: (130, 205, 255),
    DamageType.STORM: (255, 232, 110),
    DamageType.HOLY: (255, 245, 190),
    DamageType.SHADOW: (190, 120, 255),
}

WEAK_AT: Final[float] = 1.15        # multiplier at or above which a hit counts as a weakness
RESIST_AT: Final[float] = 0.85      # at or below which it counts as resisted
BASE_STATUS_CHANCE: Final[float] = 0.30
BOSS_AFFINITY_SOFTEN: Final[float] = 0.5   # bosses keep half of their archetype's swing so no one element trivialises them
AFFINITY_FLOOR: Final[float] = 0.2
AFFINITY_CEIL: Final[float] = 1.6

P, F, I, S, H, D = (DamageType.PHYSICAL, DamageType.FIRE, DamageType.FROST,
                    DamageType.STORM, DamageType.HOLY, DamageType.SHADOW)

# Enemy archetype key -> {damage type: multiplier taken}. Unlisted types are neutral (1.0).
ARCHETYPE_AFFINITY: Final[dict[str, dict[DamageType, float]]] = {
    "beast": {F: 1.30, D: 0.80},
    "void": {H: 1.35, D: 0.60, P: 0.90},
    "nature": {F: 1.40, I: 0.80},
    "construct": {S: 1.40, P: 0.85, F: 0.90},
    "cultist": {D: 1.25, I: 1.25, H: 0.75},
    "hunter": {I: 1.30, S: 0.85},
    "undead": {H: 1.50, F: 1.25, D: 0.50, I: 0.70, P: 0.85},
    "cinder": {I: 1.50, F: 0.25},
}
# Element an enemy archetype's attacks carry.
ARCHETYPE_ATTACK: Final[dict[str, DamageType]] = {
    "beast": P, "void": D, "nature": P, "construct": P, "cultist": H, "hunter": P, "undead": D, "cinder": F,
}
# Player class name -> affinities (heroes are mostly neutral; a few have a signature weakness/resistance).
CLASS_AFFINITY: Final[dict[str, dict[DamageType, float]]] = {
    "WARRIOR": {},
    "TANK": {P: 0.90, D: 1.10},
    "ROGUE": {},
    "WITCH": {P: 1.10, D: 0.85},
    "ANGEL": {H: 1.25, D: 0.80},
    "KITSUNE": {S: 1.15},
    "VAMPIRE": {H: 1.30, F: 1.15, D: 0.85},
    "DRAGONKIN": {F: 0.60, I: 1.20},
}
# Ability key -> element of its damage. Anything not listed is PHYSICAL.
ABILITY_ELEMENT: Final[dict[str, DamageType]] = {
    "bash": H,                                               # Tank: radiant shield bash
    "bolt": I, "curse": D, "drain": D,                       # Witch
    "slash": D, "halo": H,                                   # Fallen Angel
    "foxfire": F, "masquerade": D,                           # Kitsune
    "crimson_mark": D, "sanguine_lunge": D, "eclipse_feast": D,   # Vampire
    "ember_breath": F, "wingbeat": S,                        # Dragonkin
}
# Element -> (status name from entities.base_entity.Status, turns).
STATUS_FOR: Final[dict[DamageType, tuple[str, int]]] = {
    F: ("BURN", 2), I: ("CHILL", 2), S: ("SHOCK", 2), D: ("SUPPRESSED", 1),
}
CHILL_ATTACK_FACTOR: Final[float] = 0.80
SHOCK_BONUS: Final[float] = 1.25


def element_of_ability(key: str) -> DamageType:
    return ABILITY_ELEMENT.get(key, DamageType.PHYSICAL)


def _clamp(v: float) -> float:
    return max(AFFINITY_FLOOR, min(AFFINITY_CEIL, v))


def affinity(entity: Any, dtype: DamageType) -> float:
    """Damage multiplier ``entity`` takes from ``dtype``. Neutral (1.0) for anything unknown."""
    table: Optional[dict[DamageType, float]] = None
    arch = getattr(entity, "arch", None)
    if arch is not None:
        table = ARCHETYPE_AFFINITY.get(str(getattr(arch, "key", "")))
        if table is not None and getattr(entity, "boss", False):
            return _clamp(1.0 + (table.get(dtype, 1.0) - 1.0) * BOSS_AFFINITY_SOFTEN)
    else:
        pclass = getattr(entity, "pclass", None)
        table = CLASS_AFFINITY.get(str(getattr(pclass, "name", "")))
    if not table:
        return 1.0
    return _clamp(table.get(dtype, 1.0))


def affinity_tag(mult: float) -> str:
    """'weak' / 'resist' / '' for a multiplier."""
    if mult >= WEAK_AT:
        return "weak"
    if mult <= RESIST_AT:
        return "resist"
    return ""


def attack_element(entity: Any) -> DamageType:
    """Element carried by an enemy's attacks (physical for anything unknown)."""
    arch = getattr(entity, "arch", None)
    return ARCHETYPE_ATTACK.get(str(getattr(arch, "key", "")), DamageType.PHYSICAL)


def affinity_summary(entity: Any) -> tuple[list[DamageType], list[DamageType]]:
    """(weaknesses, resistances) of an entity, strongest first - used by the enemy card."""
    rows = [(t, affinity(entity, t)) for t in DamageType]
    weak = [t for t, m in sorted(rows, key=lambda r: -r[1]) if m >= WEAK_AT]
    res = [t for t, m in sorted(rows, key=lambda r: r[1]) if m <= RESIST_AT]
    return weak, res
