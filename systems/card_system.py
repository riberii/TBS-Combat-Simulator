"""R2 hybrid tactical card system (vertical slice).

Cards are an *additional* way to spend a hero's turn, not a replacement: the baseline abilities and Items are always
in the menu, so an unlucky draw can never produce a dead turn. Cards spend resources heroes already own
(Stamina, Mana, Rage, Lucidity, a little HP) and ride the existing damage-type / status machinery.

Tactical tags (what the rules engine understands):
    SETUP     primes a target (applies MARK or an elemental status)
    STRIKE    +50% damage against a MARKED target and consumes the mark
    DETONATE  consumes MARK / BURN / CHILL / SHOCK / SUPPRESSED on the target for +60% damage each
    WARD      hardens the hero (Warded / Guard) against the telegraphed hit
    SHIFT     manipulates tempo and targeting: re-rolls the foe's telegraph, sheds aggro, draws a card
    SILENCE   interrupts a dangerous telegraph (charge / curse / devastate / rally)

Fallen Angel cards interact with her restraints (they scale with, or are paid for by, being bound) and never remove
them. All randomness comes from the ``random.Random`` handed in, so decks, hands and drafts are seed-reproducible.

Pure logic: no pygame. The combat system owns the per-battle ``CardBattle`` objects; the persistent deck is a list of
strings on the hero (``"strike"``, upgraded cards carry a trailing ``+``) so it round-trips through the generic save code.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Optional, Sequence

from core.elements import DamageType
from entities.base_entity import Status

if TYPE_CHECKING:  # pragma: no cover
    from systems.combat_system import CombatSystem

HAND_SIZE: Final[int] = 5
OPENING_HAND: Final[int] = 4
TAGS: Final[tuple[str, ...]] = ("SETUP", "STRIKE", "WARD", "SHIFT", "SILENCE", "DETONATE")
STRIKE_BONUS: Final[float] = 1.5
DETONATE_PER_STATUS: Final[float] = 0.6
DETONATE_SET: Final[tuple[Status, ...]] = (Status.MARK, Status.BURN, Status.CHILL, Status.SHOCK, Status.SUPPRESSED)
MAX_DECK: Final[int] = 30
MIN_DECK: Final[int] = 6
DRAFT_SKIP_GOLD: Final[int] = 12
RARITIES: Final[tuple[str, ...]] = ("common", "rare", "epic", "signature")
RARITY_WEIGHT: Final[dict[str, float]] = {"common": 6.0, "rare": 3.0, "epic": 1.2, "signature": 0.0}
CATCH_BREATH: Final[str] = "catch_breath"      # the free card injected if a hand would be dead


@dataclass(frozen=True)
class Card:
    key: str
    name: str
    ctype: str                    # attack / spell / defence / technique / reaction / summon / setup / payoff
    rarity: str
    cost_kind: str                # stamina / mana / rage / lucidity / hp / free
    cost: int
    target: str                   # enemy / all / self
    ops: tuple[dict[str, Any], ...]
    text: str
    tags: tuple[str, ...] = ()
    class_key: Optional[str] = None       # None = common (every class)
    exhaust: bool = False
    up_cost: Optional[int] = None         # cost when upgraded (default: ~20% cheaper)
    up_scale: float = 1.25                # damage / amount multiplier when upgraded
    face: str = "face_fate"               # Assets/Art/cards/<face>.png

    def __post_init__(self) -> None:
        for t in self.tags:
            if t not in TAGS:
                raise ValueError(f"card {self.key}: unknown tag {t}")
        if self.rarity not in RARITIES:
            raise ValueError(f"card {self.key}: unknown rarity {self.rarity}")


def _c(*a: Any, **k: Any) -> Card:
    return Card(*a, **k)


def dmg(mult: float, dtype: str = "PHYSICAL", **kw: Any) -> dict[str, Any]:
    return {"op": "damage", "mult": mult, "dtype": dtype, **kw}


CARDS: Final[dict[str, Card]] = {c.key: c for c in (
    # ---------------- common (every class) ----------------
    _c("strike", "Steady Strike", "attack", "common", "stamina", 15, "enemy", (dmg(1.3),),
       "Deal 1.3x damage. +50% and consumes the mark if the target is Marked.", ("STRIKE",), face="face_blood"),
    _c("brace", "Brace", "defence", "common", "stamina", 10, "self", ({"op": "ward", "turns": 1},),
       "Gain Warded (+50% defence) for a turn.", ("WARD",), face="face_resonance"),
    _c("catch_breath", "Catch Breath", "technique", "common", "free", 0, "self",
       ({"op": "gain", "res": "stamina", "n": 25},), "Recover 25 Stamina. Exhaust.", exhaust=True, face="face_fate"),
    _c("mark_prey", "Mark Prey", "setup", "common", "stamina", 10, "enemy",
       ({"op": "mark", "turns": 3}, {"op": "draw", "n": 1}), "Mark a foe for 3 turns and draw a card.", ("SETUP",), face="face_fate"),
    _c("break_mark", "Break the Mark", "payoff", "common", "stamina", 25, "enemy", ({"op": "detonate", "base": 0.8},),
       "Consume Mark/Burn/Chill/Shock/Suppression on the target: 0.8x +0.6x per status consumed.", ("DETONATE",), face="face_flame"),
    _c("disrupt", "Disrupt", "technique", "rare", "stamina", 20, "enemy", ({"op": "silence"},),
       "Cancel a charging, cursing or rallying foe's next action. Otherwise a weak hit that Suppresses.", ("SILENCE",), face="face_frost"),
    _c("feint", "Feint", "technique", "rare", "stamina", 15, "enemy", ({"op": "shift"},),
       "Re-roll the foe's telegraph, shed aggro and draw a card.", ("SHIFT",), face="face_fate"),
    _c("riposte", "Riposte Stance", "reaction", "rare", "stamina", 15, "self", ({"op": "guard", "turns": 1},),
       "Gain Guard (x3 defence) for a turn.", ("WARD",), face="face_resonance"),
    # ---------------- class cards ----------------
    _c("rending_cleave", "Rending Cleave", "attack", "common", "stamina", 20, "enemy",
       (dmg(1.8), {"op": "gain", "res": "rage", "n": 15}), "1.8x damage, +15 Rage.", ("STRIKE",), "WARRIOR", face="face_blood"),
    _c("rage_burst", "Rage Burst", "attack", "rare", "rage", 30, "all", (dmg(1.5),),
       "Spend 30 Rage: 1.5x damage to every foe.", (), "WARRIOR", face="face_flame"),
    _c("warcry", "Warcry", "technique", "rare", "stamina", 15, "self", ({"op": "status_self", "status": "EMPOWERED", "turns": 2},),
       "Gain Empowered (+25% attack) for 2 turns.", (), "WARRIOR", face="face_blood"),
    _c("radiant_bulwark", "Radiant Bulwark", "defence", "rare", "stamina", 20, "self",
       ({"op": "guard", "turns": 1}, {"op": "status_self", "status": "PROVOKE", "turns": 1}), "Guard and Provoke for a turn.",
       ("WARD", "SHIFT"), "TANK", face="face_resonance"),
    _c("hamstring", "Hamstring", "setup", "rare", "stamina", 15, "enemy", (dmg(0.9), {"op": "mark", "turns": 3}),
       "0.9x damage and Mark the target for 3 turns.", ("SETUP",), "ROGUE", face="face_blood"),
    _c("frost_lance", "Frost Lance", "spell", "common", "mana", 12, "enemy", (dmg(1.9, "FROST"),),
       "1.9x Frost damage (may Chill).", (), "WITCH", face="face_frost"),
    _c("ignite", "Ignite", "setup", "common", "mana", 10, "enemy", (dmg(1.2, "FIRE"), {"op": "status", "status": "BURN", "turns": 2, "burn": 4}),
       "1.2x Fire damage and set the foe Burning.", ("SETUP",), "WITCH", face="face_flame"),
    _c("storm_thread", "Storm Thread", "spell", "rare", "mana", 14, "enemy", (dmg(1.3, "STORM"), {"op": "status", "status": "SHOCK", "turns": 2}),
       "1.3x Storm damage and Shock: the next hit lands +25% harder.", ("SETUP",), "WITCH", face="face_resonance"),
    _c("arcane_reservoir", "Arcane Reservoir", "technique", "rare", "free", 0, "self", ({"op": "gain", "res": "mana", "n": 25},),
       "Recover 25 Mana. Exhaust.", (), "WITCH", exhaust=True, face="face_frost"),
    _c("penitent_strike", "Penitent Strike", "attack", "common", "stamina", 15, "enemy", (dmg(1.3, "SHADOW", scale_restraints=0.3),),
       "1.3x Shadow damage, +30% per active restraint (her chains lend weight; they still suppress her output).", ("STRIKE",), "ANGEL", face="face_blood"),
    _c("lucid_hymn", "Lucid Hymn", "technique", "rare", "hp", 8, "self", ({"op": "gain", "res": "lucidity", "n": 12},),
       "Pay 8 HP to regain 12 Lucidity. Exhaust.", (), "ANGEL", exhaust=True, face="face_fate"),
    _c("measured_defiance", "Measured Defiance", "technique", "rare", "lucidity", 10, "self", ({"op": "momentum", "n": 1}, {"op": "draw", "n": 1}),
       "Pay 10 Lucidity: +1 break momentum (the next break attempt is easier) and draw a card. Does not break a chain.", (), "ANGEL", face="face_resonance"),
    _c("chains_taut", "Chains Taut", "attack", "epic", "lucidity", 10, "all", (dmg(1.0, "HOLY", scale_restraints=0.2),),
       "Pay 10 Lucidity: 1.0x Holy damage to all, +20% per active restraint.", (), "ANGEL", face="face_flame"),
    _c("foxfire_familiar", "Foxfire Familiar", "summon", "rare", "mana", 14, "all", ({"op": "summon", "hits": 3, "mult": 0.6, "dtype": "FIRE"},),
       "Three foxfire wisps strike random foes for 0.6x Fire each.", (), "KITSUNE", face="face_flame"),
    _c("crimson_tithe", "Crimson Tithe", "attack", "rare", "hp", 10, "enemy", (dmg(2.1, "SHADOW"), {"op": "heal", "n": 8}),
       "Pay 10 HP: 2.1x Shadow damage and heal 8.", (), "VAMPIRE", face="face_blood"),
    _c("ember_roar", "Ember Roar", "attack", "rare", "stamina", 20, "all", (dmg(1.2, "FIRE"),),
       "1.2x Fire damage to every foe.", (), "DRAGONKIN", face="face_flame"),
)}

# starter deck recipes: common core + class cards
_CORE: Final[tuple[str, ...]] = ("strike", "strike", "strike", "brace", "brace", "mark_prey", "break_mark", CATCH_BREATH)
_CLASS_STARTERS: Final[dict[str, tuple[str, ...]]] = {
    "WARRIOR": ("rending_cleave", "rending_cleave", "rage_burst"),
    "TANK": ("radiant_bulwark", "riposte"),
    "ROGUE": ("hamstring", "feint"),
    "WITCH": ("frost_lance", "frost_lance", "ignite", "arcane_reservoir"),
    "ANGEL": ("penitent_strike", "penitent_strike", "lucid_hymn", "measured_defiance"),
    "KITSUNE": ("foxfire_familiar", "feint"),
    "VAMPIRE": ("crimson_tithe", "disrupt"),
    "DRAGONKIN": ("ember_roar", "riposte"),
}


def starter_deck(class_key: str) -> list[str]:
    return list(_CORE) + list(_CLASS_STARTERS.get(class_key.upper(), ()))


# ----------------------------------------------------------------------------- references / upgrades
def parse_ref(ref: str) -> tuple[Card, bool]:
    key, up = (ref[:-1], True) if ref.endswith("+") else (ref, False)
    return CARDS[key], up


def make_ref(key: str, upgraded: bool = False) -> str:
    return key + ("+" if upgraded else "")


def effective_cost(card: Card, upgraded: bool, relics: Sequence[str] = ()) -> int:
    base = card.cost
    if upgraded:
        base = card.up_cost if card.up_cost is not None else max(0, round(card.cost * 0.8))
    if "thin_blade" in relics and card.cost_kind == "stamina":
        base = max(0, base - 3)
    return base


def card_text(card: Card, upgraded: bool) -> str:
    return card.text + (" (Upgraded)" if upgraded else "")


def is_valid_ref(ref: str) -> bool:
    try:
        parse_ref(ref)
        return True
    except KeyError:
        return False


def sanitize_deck(refs: Any, class_key: str) -> list[str]:
    """Drop unknown / non-string entries (old saves, hand-edited files); fall back to the starter deck if too small."""
    out = [r for r in (refs if isinstance(refs, list) else []) if isinstance(r, str) and is_valid_ref(r)][:MAX_DECK]
    return out if len(out) >= MIN_DECK else starter_deck(class_key)


# ----------------------------------------------------------------------------- relics
@dataclass(frozen=True)
class Relic:
    key: str
    name: str
    text: str
    class_key: Optional[str] = None


RELICS: Final[dict[str, Relic]] = {r.key: r for r in (
    Relic("steady_hands", "Steady Hands", "Hand size +1."),
    Relic("opening_gambit", "Opening Gambit", "Draw 1 extra card at the start of every battle."),
    Relic("mulligan_charm", "Mulligan Charm", "One extra mulligan per battle."),
    Relic("ember_charm", "Ember Charm", "Fire cards deal +20% damage."),
    Relic("thin_blade", "Thin Blade", "Stamina cards cost 3 less."),
    Relic("hymnal_of_chains", "Hymnal of Chains", "Fallen Angel: every passed restraint trial draws a card.", "ANGEL"),
)}


# ----------------------------------------------------------------------------- per-battle state
@dataclass
class CardBattle:
    """Draw / hand / discard / exhaust piles for one hero for one battle."""
    rng: random.Random
    deck: list[str]
    relics: tuple[str, ...] = ()
    hand_size: int = HAND_SIZE
    draw_pile: list[str] = field(default_factory=list)
    hand: list[str] = field(default_factory=list)
    discard: list[str] = field(default_factory=list)
    exhausted: list[str] = field(default_factory=list)
    mulligans: int = 1
    reshuffles: int = 0

    @classmethod
    def start(cls, rng: random.Random, deck: Sequence[str], relics: Sequence[str] = ()) -> "CardBattle":
        cb = cls(rng=rng, deck=list(deck), relics=tuple(relics))
        if "steady_hands" in relics:
            cb.hand_size += 1
        if "mulligan_charm" in relics:
            cb.mulligans += 1
        cb.draw_pile = list(deck)
        rng.shuffle(cb.draw_pile)
        cb.draw(OPENING_HAND + (1 if "opening_gambit" in relics else 0))
        return cb

    # -- piles
    def _reshuffle(self) -> None:
        if self.discard:
            self.draw_pile = self.discard
            self.discard = []
            self.rng.shuffle(self.draw_pile)
            self.reshuffles += 1

    def draw(self, n: int = 1) -> list[str]:
        drawn: list[str] = []
        for _ in range(max(0, n)):
            if len(self.hand) >= self.hand_size:
                break
            if not self.draw_pile:
                self._reshuffle()
            if not self.draw_pile:
                break
            ref = self.draw_pile.pop()
            self.hand.append(ref)
            drawn.append(ref)
        return drawn

    def total_cards(self) -> int:
        return len(self.draw_pile) + len(self.hand) + len(self.discard) + len(self.exhausted)

    def play(self, index: int) -> str:
        """Move the card at ``index`` out of the hand into discard (or exhaust). Returns its ref."""
        ref = self.hand.pop(index)
        card, _ = parse_ref(ref)
        (self.exhausted if card.exhaust else self.discard).append(ref)
        return ref

    def mulligan(self) -> bool:
        if self.mulligans <= 0 or not self.hand:
            return False
        self.mulligans -= 1
        n = len(self.hand)
        self.discard.extend(self.hand)
        self.hand = []
        self.draw(n)
        return True

    # -- dead-hand prevention
    def ensure_playable(self, can_play: Any) -> Optional[str]:
        """Guarantee at least one playable card: dig for one, else swap the worst card for a free Catch Breath."""
        if any(can_play(ref) for ref in self.hand):
            return None
        for _ in range(3):
            if self.hand_size > len(self.hand):
                self.draw(1)
            elif self.hand:
                self.discard.append(self.hand.pop(0))
                self.draw(1)
            if any(can_play(ref) for ref in self.hand):
                return None
        if len(self.hand) >= self.hand_size and self.hand:
            self.discard.append(self.hand.pop())
        self.hand.append(CATCH_BREATH)
        return CATCH_BREATH


# ----------------------------------------------------------------------------- costs
def can_pay(hero: Any, card: Card, upgraded: bool, relics: Sequence[str] = ()) -> bool:
    cost = effective_cost(card, upgraded, relics)
    kind = card.cost_kind
    if kind == "free" or cost <= 0:
        return True
    if kind == "stamina":
        return hero.stamina >= cost
    if kind == "mana":
        return getattr(hero, "max_mana", 0) > 0 and hero.mana >= cost
    if kind == "rage":
        return hasattr(hero, "rage") and hero.rage >= cost
    if kind == "lucidity":
        return hasattr(hero, "lucidity") and hero.lucidity > cost
    if kind == "hp":
        return hero.hp > cost + 1
    return False


def pay(hero: Any, card: Card, upgraded: bool, combat: "CombatSystem", relics: Sequence[str] = ()) -> None:
    cost = effective_cost(card, upgraded, relics)
    if card.cost_kind == "free" or cost <= 0:
        return
    if card.cost_kind == "stamina":
        hero.spend_stamina(cost)
    elif card.cost_kind == "mana":
        hero.mana = max(0, hero.mana - cost)
    elif card.cost_kind == "rage":
        hero.rage = max(0, hero.rage - cost)
    elif card.cost_kind == "lucidity":
        hero.lucidity = max(0.0, hero.lucidity - cost)
    elif card.cost_kind == "hp":
        combat.hurt_self(hero, cost)


def cost_label(card: Card, upgraded: bool, relics: Sequence[str] = ()) -> str:
    c = effective_cost(card, upgraded, relics)
    unit = {"stamina": "STA", "mana": "MP", "rage": "RAGE", "lucidity": "LUC", "hp": "HP"}.get(card.cost_kind, "")
    return "free" if card.cost_kind == "free" or c <= 0 else f"{c} {unit}"


# ----------------------------------------------------------------------------- effects
_DANGEROUS = ("CHARGE", "CURSE", "DEVASTATE", "RALLY")


def _consume(foe: Any, statuses: Sequence[Status]) -> int:
    n = 0
    for st in statuses:
        if st in foe.statuses:
            del foe.statuses[st]
            if st is Status.BURN:
                foe.burn_power = 0
            n += 1
    return n


def resolve(card: Card, upgraded: bool, hero: Any, target: Any, combat: "CombatSystem",
            battle: Optional[CardBattle] = None, relics: Sequence[str] = ()) -> list[str]:
    """Run a card's effects. Costs must already be paid. Returns short human-readable notes (also logged)."""
    notes: list[str] = []
    scale = card.up_scale if upgraded else 1.0
    foes = [target] if card.target == "enemy" and target is not None else (combat.enemies_alive() if card.target == "all" else [])

    def strike(foe: Any, mult: float, dtype: str) -> int:
        dt = DamageType[dtype]
        if dt is DamageType.FIRE and "ember_charm" in relics:
            mult *= 1.2
        saved = combat._cur_dtype
        combat._cur_dtype = dt
        try:
            return combat.strike(hero, foe, mult)
        finally:
            combat._cur_dtype = saved

    for op in card.ops:
        kind = op["op"]
        if kind == "damage":
            for foe in list(foes):
                if not foe.alive:
                    continue
                mult = float(op["mult"]) * scale
                mult *= 1.0 + float(op.get("scale_restraints", 0.0)) * len(getattr(hero, "restraints", ()) or ())
                if "STRIKE" in card.tags and Status.MARK in foe.statuses:
                    mult *= STRIKE_BONUS
                    del foe.statuses[Status.MARK]
                    notes.append(f"{foe.name}'s mark is cashed in!")
                strike(foe, mult, op.get("dtype", "PHYSICAL"))
        elif kind == "mark":
            for foe in foes:
                foe.add_status(Status.MARK, int(op["turns"]))
                notes.append(f"{foe.name} is Marked.")
        elif kind == "status":
            st = Status[op["status"]]
            for foe in foes:
                if not foe.alive:
                    continue
                foe.add_status(st, int(op["turns"]))
                if st is Status.BURN:
                    foe.burn_power = max(foe.burn_power, int(op.get("burn", 3)))
                notes.append(f"{foe.name} is {st.value}.")
        elif kind == "status_self":
            hero.add_status(Status[op["status"]], int(op["turns"]))
        elif kind == "detonate":
            for foe in list(foes):
                n = _consume(foe, DETONATE_SET)
                mult = (float(op["base"]) + DETONATE_PER_STATUS * n) * scale
                notes.append(f"Detonation: {n} status(es) consumed." if n else "Nothing to detonate; only the base blow lands.")
                strike(foe, mult, "PHYSICAL")
        elif kind == "silence":
            for foe in foes:
                intent = getattr(foe, "intent", None)
                if intent is not None and intent.kind.name in _DANGEROUS:
                    combat.interrupt(foe)
                    notes.append(f"{foe.name}'s {intent.kind.name.lower()} is silenced!")
                else:
                    strike(foe, 0.4 * scale, "SHADOW")
                    foe.add_status(Status.SUPPRESSED, 1)
                    notes.append(f"{foe.name} has nothing to silence; it is Suppressed instead.")
        elif kind == "shift":
            for foe in foes:
                if foe.alive:
                    foe.intent = foe.choose_intent(combat.rng, combat.state.has_angel)
                    combat._refresh_intents(force=True)
                    notes.append(f"{foe.name}'s intent is thrown off.")
            hero.aggro = max(1.0, hero.aggro * 0.4)
            if battle is not None:
                battle.draw(1)
        elif kind == "ward":
            hero.add_status(Status.WARDED, int(op["turns"]))
        elif kind == "guard":
            hero.add_status(Status.GUARD, int(op["turns"]))
        elif kind == "heal":
            combat.heal(hero, int(float(op["n"]) * scale))
        elif kind == "gain":
            n = int(float(op["n"]) * scale)
            res = op["res"]
            if res == "stamina":
                hero.stamina = min(hero.max_stamina, hero.stamina + n)
            elif res == "mana":
                hero.mana = min(hero.max_mana, hero.mana + n)
            elif res == "rage" and hasattr(hero, "rage"):
                hero.rage = min(100, hero.rage + n)
            elif res == "lucidity" and hasattr(hero, "lucidity"):
                hero.lucidity = min(100.0, hero.lucidity + n)
        elif kind == "draw":
            if battle is not None:
                battle.draw(int(op["n"]))
        elif kind == "momentum":
            if hasattr(hero, "break_momentum"):
                hero.break_momentum = min(hero.MOMENTUM_MAX, hero.break_momentum + int(op["n"]))
                notes.append("The links wear thin: the next break attempt is easier.")
        elif kind == "summon":
            for _ in range(int(op["hits"])):
                alive = combat.enemies_alive()
                if not alive:
                    break
                strike(combat.rng.choice(alive), float(op["mult"]) * scale, op.get("dtype", "PHYSICAL"))
        else:  # pragma: no cover - guarded by validate_cards()
            raise ValueError(f"unknown card op {kind!r}")
    return notes


_VALID_OPS = {"damage", "mark", "status", "status_self", "detonate", "silence", "shift", "ward", "guard", "heal", "gain",
              "draw", "momentum", "summon"}


def validate_cards() -> list[str]:
    """Data-integrity problems in CARDS/starter decks (empty list = fine). Run by tools/validate_content.py and tests."""
    problems: list[str] = []
    for c in CARDS.values():
        for op in c.ops:
            if op.get("op") not in _VALID_OPS:
                problems.append(f"{c.key}: unknown op {op.get('op')}")
            if op.get("op") in ("status", "status_self") and op.get("status") not in Status.__members__:
                problems.append(f"{c.key}: unknown status {op.get('status')}")
            if op.get("dtype") and op["dtype"] not in DamageType.__members__:
                problems.append(f"{c.key}: unknown damage type {op['dtype']}")
        if c.target == "enemy" and not any(o["op"] in ("damage", "mark", "status", "detonate", "silence", "shift") for o in c.ops):
            problems.append(f"{c.key}: targets an enemy but has no enemy effect")
    for cls, extra in _CLASS_STARTERS.items():
        for key in list(_CORE) + list(extra):
            card = CARDS.get(key)
            if card is None:
                problems.append(f"starter {cls}: unknown card {key}")
            elif card.class_key not in (None, cls):
                problems.append(f"starter {cls}: {key} belongs to {card.class_key}")
    return problems


# ----------------------------------------------------------------------------- drafting / deck editing
@dataclass(frozen=True)
class DraftOption:
    kind: str          # card / relic / upgrade / purge / transform
    key: str = ""      # card key or relic key (blank for upgrade/purge)
    label: str = ""
    text: str = ""


def card_pool(class_key: str) -> list[Card]:
    return [c for c in CARDS.values() if c.class_key in (None, class_key.upper()) and c.rarity != "signature"]


def offer_draft(rng: random.Random, class_key: str, stage: int, deck: Sequence[str], relics: Sequence[str]) -> list[DraftOption]:
    """Three *different* options: weighted cards with a chance of a relic / forge / purge. Seed-reproducible."""
    pool = card_pool(class_key)
    for _ in range(5):                                       # bounded retries; the final attempt is always returned
        weights = []
        for c in pool:
            w = RARITY_WEIGHT[c.rarity] * (1.0 + 0.15 * min(stage, 12) * (c.rarity != "common"))
            w *= 1.5 if c.class_key else 1.0                  # class cards are the point of a class deck
            w *= 0.5 if sum(1 for r in deck if r.rstrip("+") == c.key) >= 3 else 1.0
            weights.append(w)
        opts: list[DraftOption] = []
        seen: set[tuple[str, str]] = set()
        owned_relics = set(relics)
        avail_relics = [r for r in RELICS.values() if r.key not in owned_relics and r.class_key in (None, class_key.upper())]
        attempts = 0
        while len(opts) < 3 and attempts < 60:
            attempts += 1
            roll = rng.random()
            if roll < 0.18 and avail_relics:
                r = rng.choice(avail_relics)
                o = DraftOption("relic", r.key, r.name, r.text)
            elif roll < 0.26 and any(not x.endswith("+") for x in deck):
                o = DraftOption("upgrade", "", "Forge", "Upgrade a card in your deck.")
            elif roll < 0.32 and len(deck) > MIN_DECK:
                o = DraftOption("purge", "", "Thin the Deck", "Remove a card from your deck.")
            elif roll < 0.38:
                o = DraftOption("transform", "", "Transmute", "Turn a card in your deck into a different one.")
            else:
                c = rng.choices(pool, weights=weights, k=1)[0]
                o = DraftOption("card", c.key, c.name, c.text)
            ident = (o.kind, o.key)
            if ident in seen:
                continue
            seen.add(ident)
            opts.append(o)
        if len(opts) == 3:
            return opts
    return opts


def apply_draft(option: DraftOption, deck: list[str], relics: list[str], rng: random.Random) -> str:
    """Apply an option that needs no further choice (card / relic). Returns a log line."""
    if option.kind == "card":
        if len(deck) >= MAX_DECK:
            return "The deck is full; the card crumbles."
        deck.append(option.key)
        return f"{CARDS[option.key].name} joins the deck."
    if option.kind == "relic":
        if option.key not in relics:
            relics.append(option.key)
        return f"{RELICS[option.key].name} acquired."
    return ""


def upgrade_card(deck: list[str], index: int) -> str:
    ref = deck[index]
    if ref.endswith("+"):
        return "Already upgraded."
    deck[index] = ref + "+"
    return f"{CARDS[ref].name} upgraded."


def thin_card(deck: list[str], index: int) -> str:
    if len(deck) <= MIN_DECK:
        return "The deck is already as thin as it can safely get."
    ref = deck.pop(index)
    return f"{parse_ref(ref)[0].name} removed from the deck."


def transform_card(deck: list[str], index: int, class_key: str, rng: random.Random) -> str:
    """Replace a card with a random different card of the same class pool (keeps upgrade state)."""
    old, up = parse_ref(deck[index])
    choices = [c for c in card_pool(class_key) if c.key != old.key]
    new = rng.choice(choices)
    deck[index] = make_ref(new.key, up)
    return f"{old.name} transforms into {new.name}."
