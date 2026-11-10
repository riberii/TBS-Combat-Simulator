"""Companion / Pet system: passive party companions providing strategic utility."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Optional

from core.config import Pal

if TYPE_CHECKING:
    from systems.combat_system import CombatSystem


@dataclass(frozen=True)
class Pet:
    key: str
    name: str
    title: str
    desc: str
    passive_desc: str

PETS: Final[dict[str, Pet]] = {
    "raven": Pet(
        "raven",
        "Ashen Raven",
        "Scavenger of Emberfall",
        "Perches upon the vanguard's shoulder, eyeing glinting coin amid the soot.",
        "+20% gold awarded upon victory in every battle.",
    ),
    "wisp": Pet(
        "wisp",
        "Spectral Wisp",
        "Memory of the First Lantern",
        "A pale luminescent orb that soothes strained sinew and clears mind fog.",
        "Restores +5 MP and +5 STA to all living heroes at the start of each combat round.",
    ),
    "hound": Pet(
        "hound",
        "Grave Hound Pup",
        "Watch-beast of the Catacombs",
        "Growls at encroaching horrors, exposing vulnerabilities in their guard.",
        "+10% party attack power when striking enemies.",
    ),
    "beetle": Pet(
        "beetle",
        "Obsidian Scarab",
        "Carapace of the Deep Vein",
        "Its hardened shell emanates a faint protective field.",
        "+3 party defense against all incoming enemy strikes.",
    ),
    "sprite": Pet(
        "sprite",
        "Silver Sprite",
        "Weaver of Dawnlight",
        "Flits between wounded companions, mending minor wounds with thread of light.",
        "Restores 5 HP to the living hero with the lowest HP percentage at the end of each round.",
    ),
}

DEFAULT_PET = "raven"


def get_pet(key: Optional[str]) -> Optional[Pet]:
    if not key:
        return None
    return PETS.get(key)


def pet_gold_multiplier(key: Optional[str]) -> float:
    return 1.20 if key == "raven" else 1.0


def pet_atk_multiplier(key: Optional[str]) -> float:
    return 1.10 if key == "hound" else 1.0


def pet_def_bonus(key: Optional[str]) -> int:
    return 3 if key == "beetle" else 0


def on_round_start_pet(key: Optional[str], combat: CombatSystem) -> None:
    if key == "wisp":
        for hero in combat.players_alive():
            hero.mana = min(hero.max_mana, hero.mana + 5)
            hero.stamina = min(hero.max_stamina, hero.stamina + 5)
        combat.log("The Spectral Wisp pulses: +5 MP and +5 STA to the party.", Pal.CYAN)


def on_round_end_pet(key: Optional[str], combat: CombatSystem) -> None:
    if key == "sprite":
        alive = combat.players_alive()
        if alive:
            lowest = min(alive, key=lambda p: p.hp / max(1, p.max_hp))
            healed = combat.heal(lowest, 5)
            if healed > 0:
                combat.log(f"Silver Sprite mends {lowest.name} for {healed} HP.", Pal.GREEN)
