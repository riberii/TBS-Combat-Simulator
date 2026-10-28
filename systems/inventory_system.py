"""Shared party inventory, item definitions, item effects and the merchant shop."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Optional

from core.config import Pal
from entities.base_entity import BaseEntity, Status, Target
from entities.enemy import INTENTS, IntentKind
from entities.player import FallenAngel, Player

if TYPE_CHECKING:
    from systems.combat_system import CombatSystem


MAX_STACK = 9          # hard ceiling for any single item in the party satchel
FURY_HP_COST = 12      # Bloodfury Brew: HP the drinker pays (never lethal)


@dataclass(frozen=True)
class ItemDef:
    key: str
    name: str
    price: int
    target: Target
    desc: str
    angel_only: bool = False
    stock_limit: int = 3          # merchant supply per visit (1-player baseline)
    max_carry: int = MAX_STACK    # party-wide carry cap for this item

    def __post_init__(self) -> None:
        if not self.key or not self.name:
            raise ValueError("ItemDef requires a non-empty key and name.")
        if self.price < 1:
            raise ValueError(f"{self.key}: price must be >= 1 (no free items).")
        if self.stock_limit < 1:
            raise ValueError(f"{self.key}: stock_limit must be >= 1.")
        if not 1 <= self.max_carry <= MAX_STACK:
            raise ValueError(f"{self.key}: max_carry must be within 1..{MAX_STACK}.")


def _build_catalog(defs: Iterable[ItemDef]) -> dict[str, ItemDef]:
    catalog: dict[str, ItemDef] = {}
    for d in defs:
        if d.key in catalog:
            raise ValueError(f"Duplicate item key: {d.key!r}")
        catalog[d.key] = d
    return catalog


ITEMS: dict[str, ItemDef] = _build_catalog((
    ItemDef("health", "Health Potion", 40, Target.ALLY, "Restore 40% max HP to an ally.", stock_limit=4),
    ItemDef("mana", "Mana Potion", 50, Target.ALLY, "+45 MP and +30 STA to an ally.", stock_limit=3),
    ItemDef("smoke", "Smoke Bomb", 110, Target.SELF, "Daze every enemy: they lose their next action.",
            stock_limit=2),
    ItemDef("tonic", "Rage Tonic", 90, Target.ALLY, "+25% attack for 4 rounds.", stock_limit=2),
    ItemDef("ward", "Ironbark Draught", 90, Target.ALLY, "+50% defense for 4 rounds.", stock_limit=2),
    # --- added variety ---
    ItemDef("elixir", "Vital Elixir", 85, Target.ALLY,
            "Restore 70% max HP to an ally. Scarce; carry 3 at most.", stock_limit=2, max_carry=3),
    ItemDef("vigor", "Vigor Draught", 35, Target.ALLY,
            "+60 STA to an ally. Cheap, but no healing and no mana.", stock_limit=4),
    ItemDef("fury", "Bloodfury Brew", 60, Target.ALLY,
            f"+25% attack for 5 rounds, but the drinker loses {FURY_HP_COST} HP (never lethal).",
            stock_limit=3),
    # --- Fallen Angel only ---
    ItemDef("cutters", "Bolt Cutters", 150, Target.ALLY, "Break one Restraint on a Fallen Angel.",
            angel_only=True, stock_limit=2),
    ItemDef("lucid", "Lucid Draught", 100, Target.ALLY, "+50 Lucidity to a Fallen Angel.",
            angel_only=True, stock_limit=2),
))

_HEAL_FRACTION: dict[str, float] = {"health": 0.4, "elixir": 0.7}


def _has_angel(players: Iterable[Player]) -> bool:
    return any(isinstance(p, FallenAngel) for p in players)


class Inventory:
    """Party-wide item counts. Counts are always within 0..item.max_carry."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {key: 0 for key in ITEMS}

    def add(self, key: str, n: int = 1) -> int:
        """Add up to `n` items, respecting the carry cap. Returns how many were actually added.

        Raises KeyError for unknown keys, TypeError for non-int `n`, ValueError for negative `n`.
        """
        if key not in ITEMS:
            raise KeyError(f"Unknown item key: {key!r}")
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError("n must be an int")
        if n < 0:
            raise ValueError("Cannot add a negative quantity.")
        added = min(n, self.room(key))
        if added:
            self.counts[key] = self.count(key) + added
        return added

    def count(self, key: str) -> int:
        """Current stock; unknown keys and corrupted negative values read as 0."""
        if key not in ITEMS:
            return 0
        return max(0, self.counts.get(key, 0))

    def room(self, key: str) -> int:
        """How many more of `key` the party can carry."""
        if key not in ITEMS:
            return 0
        return max(0, ITEMS[key].max_carry - self.count(key))

    def remove(self, key: str) -> bool:
        if self.count(key) <= 0:
            return False
        self.counts[key] = self.count(key) - 1
        return True

    def usable(self, players: list[Player]) -> list[ItemDef]:
        """Items with stock that make sense for the current party."""
        angel = _has_angel(players)
        return [i for i in ITEMS.values() if self.count(i.key) > 0 and (angel or not i.angel_only)]


def _alive(entity: BaseEntity) -> bool:
    hp = getattr(entity, "hp", None)
    return hp is None or hp > 0


def _resolve_target(item: ItemDef, user: Player, target: Optional[BaseEntity]) -> Player:
    if item.target is Target.ALLY and isinstance(target, Player):
        return target
    return user


def _unusable_reason(item: ItemDef, tgt: Player, combat: CombatSystem) -> Optional[str]:
    """Return why the item would be wasted or invalid right now, or None if it is fine."""
    if not _alive(tgt):
        return f"{tgt.name} has fallen - the {item.name} cannot help."
    hp = getattr(tgt, "hp", None)
    if item.key in _HEAL_FRACTION and hp is not None and hp >= tgt.max_hp:
        return f"{tgt.name} is already at full health."
    if item.key == "mana" and tgt.mana >= tgt.max_mana and tgt.stamina >= tgt.max_stamina:
        return f"{tgt.name} needs neither mana nor stamina."
    if item.key == "vigor" and tgt.stamina >= tgt.max_stamina:
        return f"{tgt.name} is already at full stamina."
    if item.key == "smoke" and not list(combat.enemies_alive()):
        return "There is nothing left to blind."
    if item.key == "fury" and hp is not None and hp <= 1:
        return f"{tgt.name} is too weak to survive the Brew."
    if item.angel_only and not isinstance(tgt, FallenAngel):
        return f"The {item.name} only works on a Fallen Angel."
    if item.key == "lucid" and isinstance(tgt, FallenAngel) and tgt.lucidity >= 100.0:
        return f"{tgt.name}'s mind is already clear."
    return None


def apply_item(inv: Inventory, item: ItemDef, user: Player, target: Optional[BaseEntity],
               ok: Optional[bool], combat: CombatSystem) -> bool:
    """Consume and apply an item. `ok` is the swallow-QTE result for gagged users.

    Returns True if the item was consumed (including a failed swallow), False if nothing
    happened and the item stays in the satchel.
    """
    if not isinstance(user, Player):
        raise TypeError("apply_item: `user` must be a Player")
    canonical = ITEMS.get(getattr(item, "key", None))
    if canonical is None:
        combat.log("That item is unknown to the satchel.", Pal.DIM)
        return False
    item = canonical
    if inv.count(item.key) <= 0:
        combat.log(f"No {item.name} left.", Pal.DIM)
        return False

    tgt = _resolve_target(item, user, target)
    reason = _unusable_reason(item, tgt, combat)
    if reason is not None:
        combat.log(reason, Pal.DIM)
        return False

    if not inv.remove(item.key):
        return False
    if ok is False:  # Iron Gag: failed to swallow
        combat.log(f"{user.name} chokes - the {item.name} is lost!", Pal.RED)
        combat.hurt_self(user, 10)
        return True

    if item.key in _HEAL_FRACTION:
        healed = combat.heal(tgt, max(1, int(tgt.max_hp * _HEAL_FRACTION[item.key])))
        combat.log(f"{tgt.name} recovers {healed} HP.", Pal.GREEN)
    elif item.key == "mana":
        tgt.mana = max(tgt.mana, min(tgt.max_mana, tgt.mana + 45))
        tgt.stamina = max(tgt.stamina, min(tgt.max_stamina, tgt.stamina + 30))
        combat.log(f"{tgt.name} drinks deep: mana and stamina surge.", Pal.BLUE)
    elif item.key == "vigor":
        tgt.stamina = max(tgt.stamina, min(tgt.max_stamina, tgt.stamina + 60))
        combat.log(f"{tgt.name}'s limbs feel light again.", Pal.BLUE)
    elif item.key == "smoke":
        for foe in combat.enemies_alive():
            foe.intent = INTENTS[IntentKind.SKIP]
        combat.alert("Smoke fills the chamber!", Pal.DIM)
    elif item.key == "tonic":
        tgt.add_status(Status.EMPOWERED, 4)
        combat.log(f"{tgt.name}'s blood boils with power.", Pal.GREEN)
    elif item.key == "fury":
        hp = getattr(tgt, "hp", None)
        cost = FURY_HP_COST if hp is None else max(0, min(FURY_HP_COST, int(hp) - 1))
        if cost:
            combat.hurt_self(tgt, cost)
        tgt.add_status(Status.EMPOWERED, 5)
        combat.log(f"{tgt.name} burns hot - fury over caution.", Pal.RED)
    elif item.key == "ward":
        tgt.add_status(Status.WARDED, 4)
        combat.log(f"Bark-hard skin spreads over {tgt.name}.", Pal.CYAN)
    elif item.key == "cutters" and isinstance(tgt, FallenAngel):
        broken = tgt.break_one()
        if broken is None:
            inv.add(item.key)  # nothing to cut: refund instead of wasting the tool
            combat.log("There is nothing left to cut.", Pal.DIM)
            return False
        combat.alert(f"{broken.label} CUT AWAY!", Pal.GREEN)
    elif item.key == "lucid" and isinstance(tgt, FallenAngel):
        tgt.lucidity = max(tgt.lucidity, min(100.0, tgt.lucidity + 50))
        combat.log(f"{tgt.name}'s mind clears.", Pal.CYAN)
    return True


def calculate_item_price(item: ItemDef, rng: random.Random, players: list[Player], stage: int = 1, region: str = "") -> int:
    """Calculate merchant item price considering base cost, regional inflation, and class affinities."""
    roll = rng.uniform(0.88, 1.18)
    reg = str(region or "").lower().strip()
    if reg in ("abyss", "choir_heart", "dungeon", "deep_dungeon"):
        region_mult = 1.60
    elif reg in ("sanctum", "cathedral"):
        region_mult = 1.25
    elif reg in ("oath_road", "surface", "ashen"):
        region_mult = 0.95
    elif stage <= 3:
        region_mult = 1.0
    elif stage <= 7:
        region_mult = 1.15
    elif stage <= 11:
        region_mult = 1.30
    else:
        region_mult = 1.45

    affinity = 1.0
    pclasses = {getattr(p, "pclass", None) for p in players}
    for pclass in pclasses:
        name = getattr(pclass, "name", str(pclass)).upper()
        if "ROGUE" in name and item.key in ("smoke", "tonic"):
            affinity *= 0.85
        elif "WITCH" in name and item.key in ("mana", "elixir"):
            affinity *= 0.85
        elif ("WARRIOR" in name or "TANK" in name) and item.key in ("vigor", "ward"):
            affinity *= 0.85
        elif "VAMPIRE" in name and item.key in ("fury", "elixir"):
            affinity *= 0.85
        elif "DRAGONKIN" in name:
            if item.key == "fury":
                affinity *= 0.85
            elif item.key == "ward":
                affinity *= 2.0 if reg in ("cathedral", "sanctum") else 1.25
        elif "KITSUNE" in name and item.key in ("smoke", "health"):
            affinity *= 0.90

    affinity = max(0.65, min(2.0, affinity))
    return max(1, int(round(item.price * roll * region_mult * affinity)))


class Shop:
    """Merchant stock with regional depth and class affinity pricing; last row proceeds.

    Prices are fixed at creation (always >= 1). Supply is limited per visit and grows by
    one per extra party member (up to three players), so larger parties are not starved.
    """

    def __init__(self, rng: random.Random, players: list[Player], stage: int = 1, region: str = "") -> None:
        if not isinstance(rng, random.Random):
            raise TypeError("Shop requires a random.Random instance for deterministic prices.")
        party = list(players)
        angel = _has_angel(party)
        extra = max(0, min(len(party), 3) - 1)
        self.stage = stage
        self.region = region
        self.stock: list[tuple[ItemDef, int]] = [
            (i, calculate_item_price(i, rng, party, stage, region))
            for i in ITEMS.values() if angel or not i.angel_only]
        self.supply: dict[str, int] = {i.key: i.stock_limit + extra for i, _ in self.stock}
        self.cursor = 0
        self.message = "The Hollow Peddler grins. \"Everything has a price, penitents.\""

    @property
    def rows(self) -> int:
        return len(self.stock) + 1  # + proceed

    @property
    def on_proceed(self) -> bool:
        return self.cursor == len(self.stock)

    def remaining(self, row: Optional[int] = None) -> int:
        """Units the merchant still has for a row (default: highlighted). Proceed row -> 0."""
        idx = self.cursor if row is None else row
        if not 0 <= idx < len(self.stock):
            return 0
        return max(0, self.supply.get(self.stock[idx][0].key, 0))

    def move(self, delta: int) -> None:
        self.cursor = (self.cursor + int(delta)) % self.rows

    def buy(self, gold: int, inv: Inventory) -> int:
        """Try to buy the highlighted row. Returns remaining gold (unchanged on any failure)."""
        if isinstance(gold, bool) or not isinstance(gold, int):
            raise TypeError("gold must be an int")
        self.cursor %= self.rows  # keep the cursor valid even if a caller poked it
        if self.on_proceed:
            self.message = "\"Moving on? Then keep your coin.\""
            return gold
        item, price = self.stock[self.cursor]
        if self.remaining() <= 0:
            self.message = f"\"The {item.name} is sold out.\""
            return gold
        if inv.room(item.key) <= 0:
            self.message = f"You can't carry more {item.name}."
            return gold
        if gold < price:
            self.message = "\"No coin, no mercy.\""
            return gold
        if inv.add(item.key) < 1:
            self.message = f"You can't carry more {item.name}."
            return gold
        self.supply[item.key] -= 1
        self.message = f"Bought {item.name} for {price}g."
        return gold - price