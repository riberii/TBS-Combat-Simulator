"""R2 optional risk/reward Shrine (pure logic, no pygame).

Once per hall the party may kneel at a shrine and take one of three seeded bargains. Every bargain has a visible cost
and a visible reward; nothing here can kill a hero (HP costs always leave at least 1 HP) and declining is free.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from systems.card_system import MIN_DECK, RELICS, DraftOption

BLOOD_PACT_LOSS = 0.30
GAMBLE_LOSS = 0.25
GAMBLE_WIN_CHANCE = 0.5
MIN_HP_TO_BARGAIN = 4          # a hero below this cannot pay an HP cost (it would be a no-op or a trap)


def penance_cost(stage: int) -> int:
    return 40 + 12 * max(1, stage)


def offering_gold(stage: int) -> int:
    return 60 + 15 * max(1, stage)


def gamble_gold(stage: int) -> int:
    return 110 + 20 * max(1, stage)


def _text(key: str, stage: int) -> tuple[str, str]:
    if key == "blood_pact":
        return "Blood Pact", f"Every living hero loses {int(BLOOD_PACT_LOSS * 100)}% of current HP (never below 1). The hero at the shrine gains a relic."
    if key == "gilded_penance":
        return "Gilded Penance", f"Pay {penance_cost(stage)} gold. Upgrade a random card in the shrine hero's deck."
    if key == "burnt_offering":
        return "Burnt Offering", f"Burn a random card from the shrine hero's deck (never below {MIN_DECK}). Gain {offering_gold(stage)} gold."
    return "Choir's Gamble", f"Toss a coin: win {gamble_gold(stage)} gold, or every living hero loses {int(GAMBLE_LOSS * 100)}% of current HP."


SHRINE_KEYS = ("blood_pact", "gilded_penance", "burnt_offering", "choirs_gamble")


def roll_shrine(rng: random.Random, stage: int) -> list[DraftOption]:
    """Three different bargains, seed-reproducible."""
    keys = rng.sample(SHRINE_KEYS, 3)
    return [DraftOption("bargain", k, *_text(k, stage)) for k in keys]


def _living(players: Sequence[Any]) -> list[Any]:
    return [p for p in players if getattr(p, "hp", 0) > 0]


def _free_relics(hero: Any, relics: Sequence[str]) -> list[str]:
    cls = hero.pclass.name
    return sorted(r.key for r in RELICS.values() if r.key not in set(relics) and r.class_key in (None, cls))


def unavailable_reason(key: str, players: Sequence[Any], hero: Any, gold: int, relics: Sequence[str], stage: int) -> Optional[str]:
    """None if the bargain can be taken, else a short player-facing reason."""
    deck = list(getattr(hero, "deck_cards", []))
    if key == "blood_pact":
        if not _free_relics(hero, relics):
            return "No relic is left to claim."
        if not any(p.hp >= MIN_HP_TO_BARGAIN for p in _living(players)):
            return "The party is too weak to bleed."
    elif key == "gilded_penance":
        if gold < penance_cost(stage):
            return f"Needs {penance_cost(stage)} gold."
        if all(r.endswith("+") for r in deck):
            return "Every card is already upgraded."
    elif key == "burnt_offering":
        if len(deck) <= MIN_DECK:
            return "The deck is already as thin as it can safely get."
    elif key == "choirs_gamble":
        if not any(p.hp >= MIN_HP_TO_BARGAIN for p in _living(players)):
            return "The party is too weak to risk it."
    else:
        return "Unknown bargain."
    return None


def _bleed(players: Sequence[Any], pct: float) -> int:
    total = 0
    for p in _living(players):
        loss = min(p.hp - 1, int(p.hp * pct))
        if loss > 0:
            p.hp -= loss
            total += loss
    return total


@dataclass
class ShrineResult:
    ok: bool
    message: str
    gold_delta: int = 0


def apply_shrine(key: str, players: Sequence[Any], hero: Any, gold: int, relics: list[str], stage: int,
                 rng: random.Random) -> ShrineResult:
    """Apply one bargain. Mutates player HP / deck and the ``relics`` list; the caller applies ``gold_delta``."""
    why = unavailable_reason(key, players, hero, gold, relics, stage)
    if why:
        return ShrineResult(False, why)
    deck = hero.deck_cards
    if key == "blood_pact":
        lost = _bleed(players, BLOOD_PACT_LOSS)
        rk = rng.choice(_free_relics(hero, relics))
        relics.append(rk)
        return ShrineResult(True, f"The pact is sealed: {lost} HP spilled, {RELICS[rk].name} claimed.")
    if key == "gilded_penance":
        pool = [i for i, r in enumerate(deck) if not r.endswith("+")]
        i = rng.choice(pool)
        name = deck[i]
        deck[i] = name + "+"
        return ShrineResult(True, f"{penance_cost(stage)} gold burned; {name} is upgraded.", -penance_cost(stage))
    if key == "burnt_offering":
        i = rng.randrange(len(deck))
        gone = deck.pop(i)
        return ShrineResult(True, f"{gone.rstrip('+')} burns away; +{offering_gold(stage)} gold.", offering_gold(stage))
    if rng.random() < GAMBLE_WIN_CHANCE:
        return ShrineResult(True, f"The coin lands gold: +{gamble_gold(stage)} gold.", gamble_gold(stage))
    lost = _bleed(players, GAMBLE_LOSS)
    return ShrineResult(True, f"The coin lands dark: {lost} HP lost.", 0)
