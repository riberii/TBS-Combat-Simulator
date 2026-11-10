"""V3: a read-only snapshot of a hero's card hand for the UI (pure logic, no pygame).

The combat system builds one ``HandView`` per frame request; the renderer never reaches into ``CardBattle`` itself.
Keeping this a frozen snapshot means the drawing code cannot change a hand by accident and can be unit-tested with the
stub pygame.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from systems.card_system import CardBattle, can_pay, card_text, cost_label, parse_ref

PILES = ("draw", "discard", "exhaust")


@dataclass(frozen=True)
class HandCardView:
    ref: str
    name: str
    cost: str
    cost_kind: str
    ctype: str
    rarity: str
    text: str
    tags: tuple[str, ...]
    face: str
    playable: bool
    upgraded: bool
    element: str          # damage type of the first damaging op ("PHYSICAL" when none), used for the frame tint


@dataclass(frozen=True)
class HandView:
    hero_uid: int
    hero_name: str
    cards: tuple[HandCardView, ...]
    selected: int                     # cursor position (always valid when cards is non-empty, else -1)
    focused: bool                     # True while the player is steering the hand with the keyboard
    pending: int                      # hand index of the card waiting for a target, else -1
    counts: tuple[int, int, int]      # draw, discard, exhaust
    mulligans: int
    hand_size: int
    pile_view: Optional[str]          # "draw" / "discard" / "exhaust" while the pile viewer is open
    pile_cards: tuple[HandCardView, ...]
    event_serial: int
    events: tuple[tuple[int, str, str, int], ...]
    phase: str


def _element_of(card: Any) -> str:
    for op in card.ops:
        if op.get("op") in ("damage", "summon") and op.get("dtype"):
            return str(op["dtype"])
    return "PHYSICAL"


def card_view(hero: Any, ref: str, relics: Sequence[str] = ()) -> HandCardView:
    card, up = parse_ref(ref)
    return HandCardView(ref=ref, name=card.name + ("+" if up else ""), cost=cost_label(card, up, relics),
                        cost_kind=card.cost_kind, ctype=card.ctype, rarity=card.rarity, text=card_text(card, up),
                        tags=tuple(card.tags), face=card.face, playable=bool(can_pay(hero, card, up, relics)),
                        upgraded=up, element=_element_of(card))


def build_hand_view(hero: Any, cb: CardBattle, *, selected: int, focused: bool, pending: int, pile_view: Optional[str],
                    phase: str, since: int = 0) -> HandView:
    cards = tuple(card_view(hero, r, cb.relics) for r in cb.hand)
    sel = max(0, min(selected, len(cards) - 1)) if cards else -1
    pile_cards: tuple[HandCardView, ...] = ()
    if pile_view in PILES:
        pile_cards = tuple(card_view(hero, r, cb.relics) for r in cb.pile_contents(pile_view))
    counts = cb.pile_counts()
    return HandView(hero_uid=int(getattr(hero, "uid", 0)), hero_name=str(getattr(hero, "name", "")), cards=cards,
                    selected=sel, focused=focused, pending=pending,
                    counts=(counts["draw"], counts["discard"], counts["exhaust"]), mulligans=cb.mulligans,
                    hand_size=cb.hand_size, pile_view=pile_view, pile_cards=pile_cards,
                    event_serial=cb.event_serial, events=tuple(cb.events_since(since)), phase=phase)
