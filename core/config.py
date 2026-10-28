"""Global constants, colour palette, screen dimensions and asset paths."""
from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Final

Color = tuple[int, int, int]

SCREEN_W: Final[int] = 1280
SCREEN_H: Final[int] = 720
FPS: Final[int] = 60
TITLE: Final[str] = "Chains of the Abyssal Choir | V2.0"

ROOT_DIR: Final[Path] = Path(__file__).resolve().parent.parent
FONT_FILE: Final[Path] = ROOT_DIR / "assets" / "fonts" / "main.ttf"  # optional custom font
FONT_FALLBACKS: Final[str] = "georgia,palatinolinotype,bookantiqua,dejavuserif,timesnewroman,serif"


class Pal:
    """Dark-fantasy colour palette."""

    BG: Final[Color] = (11, 9, 17)
    PANEL: Final[Color] = (23, 19, 33)
    EDGE: Final[Color] = (72, 56, 98)
    TEXT: Final[Color] = (226, 219, 205)
    DIM: Final[Color] = (125, 117, 138)
    GOLD: Final[Color] = (232, 191, 92)
    RED: Final[Color] = (212, 62, 72)
    GREEN: Final[Color] = (96, 205, 124)
    BLUE: Final[Color] = (84, 144, 238)
    PURPLE: Final[Color] = (172, 104, 224)
    CYAN: Final[Color] = (92, 212, 222)
    ORANGE: Final[Color] = (238, 144, 62)
    BLACK: Final[Color] = (0, 0, 0)
    WHITE: Final[Color] = (255, 255, 255)


class PlayerClass(Enum):
    WARRIOR = "Warrior"
    TANK = "Tank"
    ROGUE = "Rogue"
    WITCH = "Witch"
    ANGEL = "Fallen Angel"
    KITSUNE = "Kitsune"
    VAMPIRE = "Vampire"
    DRAGONKIN = "Dragonkin"


CLASS_COLORS: Final[dict[PlayerClass, Color]] = {
    PlayerClass.WARRIOR: (222, 96, 78),
    PlayerClass.TANK: (96, 150, 230),
    PlayerClass.ROGUE: (116, 214, 140),
    PlayerClass.WITCH: (190, 112, 236),
    PlayerClass.ANGEL: (236, 220, 160),
    PlayerClass.KITSUNE: (255, 155, 91),
    PlayerClass.VAMPIRE: (194, 62, 100),
    PlayerClass.DRAGONKIN: (237, 111, 59),
}

CLASS_BLURBS: Final[dict[PlayerClass, str]] = {
    PlayerClass.WARRIOR: "Build Rage, sweep enemy groups, expose a target, then spend the full reserve on Executioner's Verdict.",
    PlayerClass.TANK: "Bastion stacks empower Shield Bash; Guard intercepts blows, Provoke fixes aggro, Aegis wards the party.",
    PlayerClass.ROGUE: "Build Combo, use Twin Fang's timing window, then cash out with a guaranteed-crit Assassinate.",
    PlayerClass.WITCH: "Mana powers area control and Soul Drain; Barrier and a reliable Hex Bolt keep the fragile caster in play.",
    PlayerClass.ANGEL: "NIGHTMARE. The Abyss chains you every turn. Keep Lucidity, break restraints, burn bright.",
    PlayerClass.KITSUNE: "Foxfire and misdirection. Build Spirit through attacks; spend it to evade, bait, and awaken.",
    PlayerClass.VAMPIRE: "Build Blood through precise strikes; spend it on bounded sustain, evasive mist, and team empowerment.",
    PlayerClass.DRAGONKIN: "Build Heat by fighting and guarding; convert it into breath, disruption, and a brief empowered aspect—overheat leaves you exposed.",
}


class QteKind(Enum):
    TYPING = "typing"
    MASH = "mash"
    TIMING = "timing"
    MEMORY = "memory"


# Difficulty name -> global stat multiplier (ordered easiest to hardest).
DIFFICULTIES: Final[dict[str, float]] = {"Easy": 0.75, "Normal": 1.0, "Hard": 1.35, "Insane": 1.8}

MAX_PARTY: Final[int] = 3
PARTY_HP_SCALE: Final[float] = 0.75   # +75% enemy HP per extra player
PARTY_ATK_SCALE: Final[float] = 0.15  # +15% enemy attack per extra player
PARTY_DEF_SCALE: Final[float] = 0.10  # +10% enemy defense per extra player
DEF_K: Final[int] = 30                # damage = raw * K / (K + defense)

# Legacy campaign constants (kept for existing importers; endless mode uses the helpers below).
BOSS_STAGES: Final[tuple[int, ...]] = (4, 8, 12)
FINAL_STAGE: Final[int] = 12

# ---------------------------------------------------------------------------
# Endless progression
# ---------------------------------------------------------------------------
FIRST_BOSS_STAGE: Final[int] = 4      # first boss; matches BOSS_STAGES[0]
BOSS_INTERVAL: Final[int] = 4         # a boss recurs every N stages after the first
ENDLESS_STAGE_CAP: Final[int] = 999   # stages above this reuse the cap's curve values (bounds all maths)

# HP grows polynomially (always finite thanks to ENDLESS_STAGE_CAP).
# ATK / DEF approach a ceiling asymptotically so damage can never run away.
HP_LINEAR_GROWTH: Final[float] = 0.15
HP_QUAD_GROWTH: Final[float] = 0.002
ATK_MULT_CAP: Final[float] = 3.0
ATK_GROWTH_RATE: Final[float] = 0.05
DEF_MULT_CAP: Final[float] = 2.5
DEF_GROWTH_RATE: Final[float] = 0.04

BOSS_HP_MULT: Final[float] = 2.5
BOSS_ATK_MULT: Final[float] = 1.15
BOSS_DEF_MULT: Final[float] = 1.10

# Largest share of a target's max HP that one hit should be allowed to take (see max_single_hit).
MAX_HIT_FRACTION: Final[float] = 0.65


@dataclass(frozen=True, slots=True)
class StageScaling:
    """Multipliers applied to stage-1 base enemy stats (before difficulty/party scaling)."""

    hp: float
    atk: float
    defense: float
    is_boss: bool


def _validate_stage(stage: int) -> int:
    """Return ``stage`` as a plain int, rejecting bools, non-integers and values below 1."""
    if isinstance(stage, bool):
        raise TypeError("stage must be an integer, not bool")
    try:
        value = operator.index(stage)
    except TypeError as exc:
        raise TypeError(f"stage must be an integer, got {type(stage).__name__}") from exc
    if value < 1:
        raise ValueError(f"stage must be >= 1, got {value}")
    return value


def is_boss_stage(stage: int) -> bool:
    """True for stage 4 and every 4th stage after it (4, 8, 12, 16, ...)."""
    value = _validate_stage(stage)
    return value >= FIRST_BOSS_STAGE and (value - FIRST_BOSS_STAGE) % BOSS_INTERVAL == 0


def next_boss_stage(stage: int) -> int:
    """Smallest boss stage that is >= ``stage``."""
    value = _validate_stage(stage)
    if value <= FIRST_BOSS_STAGE:
        return FIRST_BOSS_STAGE
    steps = -(-(value - FIRST_BOSS_STAGE) // BOSS_INTERVAL)  # ceiling division
    return FIRST_BOSS_STAGE + steps * BOSS_INTERVAL


def is_endless_stage(stage: int) -> bool:
    """True once the stage lies beyond the original campaign (FINAL_STAGE)."""
    return _validate_stage(stage) > FINAL_STAGE


@lru_cache(maxsize=512)
def _scaling_for(stage: int, boss: bool) -> StageScaling:
    n = stage - 1
    hp = 1.0 + HP_LINEAR_GROWTH * n + HP_QUAD_GROWTH * n * n
    atk = 1.0 + (ATK_MULT_CAP - 1.0) * (1.0 - math.exp(-ATK_GROWTH_RATE * n))
    dfn = 1.0 + (DEF_MULT_CAP - 1.0) * (1.0 - math.exp(-DEF_GROWTH_RATE * n))
    if boss:
        hp *= BOSS_HP_MULT
        atk *= BOSS_ATK_MULT
        dfn *= BOSS_DEF_MULT
    return StageScaling(hp=hp, atk=atk, defense=dfn, is_boss=boss)


def stage_scaling(stage: int) -> StageScaling:
    """Smooth, monotonic, bounded stat multipliers for ``stage`` (1.0 at stage 1).

    ATK and DEF multipliers never exceed ``ATK_MULT_CAP * BOSS_ATK_MULT`` and
    ``DEF_MULT_CAP * BOSS_DEF_MULT``; HP stays finite for any stage.
    """
    value = _validate_stage(stage)
    return _scaling_for(min(value, ENDLESS_STAGE_CAP), is_boss_stage(value))


def max_single_hit(max_hp: int) -> int:
    """Per-hit damage ceiling for a target with ``max_hp`` (at least 1).

    Opt-in helper: damage code may clamp enemy hits with it to rule out one-shots.
    """
    if isinstance(max_hp, bool) or not isinstance(max_hp, int):
        raise TypeError("max_hp must be an int")
    if max_hp < 1:
        raise ValueError(f"max_hp must be >= 1, got {max_hp}")
    return max(1, int(max_hp * MAX_HIT_FRACTION))