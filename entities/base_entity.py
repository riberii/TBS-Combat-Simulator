"""Abstract base class shared by heroes and enemies, plus common value types."""
from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.config import DEF_K, Color, Pal, QteKind


class Status(Enum):
    BURN = "Burn"
    EXPOSED = "Exposed"
    SUPPRESSED = "Suppressed"
    GUARD = "Guard"
    PROVOKE = "Provoke"
    EMPOWERED = "Empowered"
    WARDED = "Warded"


STATUS_COLORS: dict[Status, Color] = {
    Status.BURN: Pal.ORANGE, Status.EXPOSED: Pal.RED, Status.SUPPRESSED: Pal.PURPLE,
    Status.GUARD: Pal.BLUE, Status.PROVOKE: Pal.GOLD, Status.EMPOWERED: Pal.GREEN,
    Status.WARDED: Pal.CYAN,
}


class Target(Enum):
    ENEMY = "enemy"
    ALL_ENEMIES = "all"
    ALLY = "ally"
    SELF = "self"


@dataclass(frozen=True)
class Ability:
    """A selectable action. `enabled` is evaluated when the menu is built."""

    key: str
    label: str
    cost: str
    target: Target
    enabled: bool = True
    qte: Optional[QteKind] = None
    hint: str = ""


@dataclass(frozen=True)
class Bar:
    """A HUD resource bar description."""

    label: str
    value: float
    maximum: float
    color: Color


class BaseEntity(ABC):
    """Anything that can fight: owns HP, stats, statuses and damage maths."""

    _uids = itertools.count(1)

    def __init__(self, name: str, max_hp: int, attack: int, defense: int, speed: int) -> None:
        self.uid: int = next(BaseEntity._uids)
        self.name = name
        self.max_hp = max_hp
        self.hp = max_hp
        self.base_attack = attack
        self.base_defense = defense
        self.speed = speed
        self.statuses: dict[Status, int] = {}
        self.burn_power = 0

    # ---- identity -------------------------------------------------------
    @property
    @abstractmethod
    def accent(self) -> Color:
        """Primary colour used for sprites and highlights."""

    @property
    @abstractmethod
    def tagline(self) -> str:
        """Short descriptor shown under the name."""

    # ---- state ----------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0.0

    def has(self, status: Status) -> bool:
        return status in self.statuses

    def add_status(self, status: Status, turns: int) -> None:
        self.statuses[status] = max(self.statuses.get(status, 0), turns)

    def clear_statuses(self) -> None:
        self.statuses.clear()
        self.burn_power = 0

    # ---- derived stats --------------------------------------------------
    @property
    def attack_power(self) -> float:
        value = float(self.base_attack)
        if Status.EMPOWERED in self.statuses:
            value *= 1.25
        if Status.SUPPRESSED in self.statuses:
            value *= 0.65
        return value

    @property
    def defense_power(self) -> float:
        value = float(self.base_defense)
        if Status.WARDED in self.statuses:
            value *= 1.5
        if Status.GUARD in self.statuses:
            value *= 3.0
        return value

    # ---- damage ---------------------------------------------------------
    def mitigate(self, raw: float, *, true_damage: bool = False) -> int:
        """Convert raw damage to final damage after defense and Exposed."""
        dmg = raw if true_damage else raw * DEF_K / (DEF_K + self.defense_power)
        if Status.EXPOSED in self.statuses:
            dmg *= 2.0
        return max(1, int(dmg))

    def take_damage(self, amount: int) -> int:
        dealt = max(0, min(amount, self.hp))
        self.hp -= dealt
        return dealt

    def heal(self, amount: int) -> int:
        healed = max(0, min(amount, self.max_hp - self.hp))
        self.hp += healed
        return healed

    def end_round(self) -> int:
        """Apply damage-over-time, tick status durations. Returns burn damage dealt."""
        burn = 0
        if Status.BURN in self.statuses and self.alive:
            burn = self.take_damage(max(1, self.burn_power))
        for status in list(self.statuses):
            self.statuses[status] -= 1
            if self.statuses[status] <= 0:
                del self.statuses[status]
        if Status.BURN not in self.statuses:
            self.burn_power = 0
        return burn

    # ---- hooks (overridden where relevant) -------------------------------
    def on_hit_taken(self, dmg: int) -> None:
        """Called after this entity takes damage from another entity."""

    def on_deal_damage(self, dmg: int) -> None:
        """Called after this entity deals damage."""

    def badges(self) -> list[tuple[str, Color]]:
        return [(f"{s.value} {t}", STATUS_COLORS[s]) for s, t in self.statuses.items()]
