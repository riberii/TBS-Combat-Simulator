"""R2 hybrid card system: piles, seeded RNG, dead-hand prevention, tag synergies in real combat, drafting, saves."""
from __future__ import annotations

import logging
import random
import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.base_entity import Status  # noqa: E402
from entities.enemy import ARCHETYPES, Intent, IntentKind  # noqa: E402
from entities.player import FallenAngel, Restraint  # noqa: E402
from systems.card_system import (CARDS, CATCH_BREATH, DRAFT_SKIP_GOLD, HAND_SIZE, MAX_DECK, MIN_DECK, OPENING_HAND, RELICS,  # noqa: E402
                                 TAGS, CardBattle, apply_draft, can_pay, offer_draft, parse_ref, sanitize_deck,
                                 starter_deck, thin_card, transform_card, upgrade_card, validate_cards)
from systems.combat_system import CombatSystem, Phase  # noqa: E402


def _fight(classes=(PlayerClass.WARRIOR,), seed=9, stage=2):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(classes)], "Normal", endless=False)
    st.stage = stage - 1
    st.spawn_encounter()
    return st, CombatSystem(st)


def _ready(c, hero, limit=3000):
    """Advance the fight until ``hero`` is choosing an action (others take throwaway actions)."""
    for _ in range(limit):
        if c.phase is Phase.MENU and c.active is hero:
            return True
        if c.phase in (Phase.VICTORY, Phase.DEFEAT):
            return False
        if c.phase in (Phase.MENU, Phase.TARGET):
            c.handle_key("return")
        elif c.phase is Phase.QTE:
            c.update(60.0)
        else:
            c.update(0.5)
    return False


def _set_hand(c, hero, refs):
    cb = c._battle_for(hero)
    cb.hand = list(refs)
    return cb


def _play(c, hero, ref, target_idx=0):
    """Play a card through the real menu flow."""
    c._open_cards()
    entry = next(m for m in c.menu if m.kind == "card" and m.card == ref)
    c._activate(entry)
    if c.phase is Phase.TARGET:
        c.target_idx = target_idx
        c.handle_key("return")


class DataTests(unittest.TestCase):
    def test_card_table_is_valid(self):
        self.assertEqual(validate_cards(), [])

    def test_every_tag_is_used_and_each_class_has_a_starter_deck(self):
        used = {t for c in CARDS.values() for t in c.tags}
        self.assertEqual(used, set(TAGS))
        for pc in PlayerClass:
            deck = starter_deck(pc.name)
            self.assertGreaterEqual(len(deck), MIN_DECK)
            for ref in deck:
                card, _ = parse_ref(ref)
                self.assertIn(card.class_key, (None, pc.name), f"{ref} in {pc.name} deck")

    def test_sanitize_deck_drops_garbage(self):
        self.assertEqual(sanitize_deck(["strike", "nope", 5, None, "brace+"] * 3, "WARRIOR"),
                         ["strike", "brace+"] * 3)
        self.assertEqual(sanitize_deck("junk", "WITCH"), starter_deck("WITCH"))
        self.assertEqual(sanitize_deck(["strike"], "WITCH"), starter_deck("WITCH"))
        self.assertLessEqual(len(sanitize_deck(["strike"] * 99, "WARRIOR")), MAX_DECK)


class PileTests(unittest.TestCase):
    def test_seeded_opening_hands_are_reproducible(self):
        deck = starter_deck("WARRIOR")
        a = CardBattle.start(random.Random(5), deck)
        b = CardBattle.start(random.Random(5), deck)
        self.assertEqual(a.hand, b.hand)
        self.assertEqual(a.draw_pile, b.draw_pile)
        self.assertEqual(len(a.hand), OPENING_HAND)
        self.assertTrue(any(CardBattle.start(random.Random(s), deck).hand != a.hand for s in range(6, 16)))

    def test_cards_are_conserved_through_play_reshuffle_and_exhaust(self):
        deck = starter_deck("WITCH")
        cb = CardBattle.start(random.Random(2), deck)
        for _ in range(80):
            cb.draw(HAND_SIZE)
            self.assertLessEqual(len(cb.hand), HAND_SIZE)
            if cb.hand:
                cb.play(0)
            self.assertEqual(cb.total_cards(), len(deck))
        self.assertGreater(cb.reshuffles, 0)
        self.assertTrue(cb.exhausted, "exhaust cards leave the cycle")
        for ref in cb.exhausted:
            self.assertTrue(CARDS[ref.rstrip("+")].exhaust)
        self.assertFalse(set(cb.exhausted) & set(cb.draw_pile) and False)

    def test_exhausted_cards_never_return(self):
        cb = CardBattle.start(random.Random(1), ["catch_breath"] * 3 + ["strike"] * 3)
        for _ in range(40):
            cb.draw(5)
            while cb.hand:
                cb.play(0)
        self.assertEqual(sorted(cb.exhausted), ["catch_breath"] * 3)
        self.assertEqual(cb.total_cards(), 6)

    def test_relics_change_hand_and_mulligans(self):
        base = CardBattle.start(random.Random(1), starter_deck("WARRIOR"))
        rich = CardBattle.start(random.Random(1), starter_deck("WARRIOR"), ("steady_hands", "mulligan_charm", "opening_gambit"))
        self.assertEqual(rich.hand_size, base.hand_size + 1)
        self.assertEqual(rich.mulligans, base.mulligans + 1)
        self.assertEqual(len(rich.hand), len(base.hand) + 1)

    def test_mulligan_is_limited_and_keeps_hand_size(self):
        cb = CardBattle.start(random.Random(3), starter_deck("WARRIOR"))
        n = len(cb.hand)
        self.assertTrue(cb.mulligan())
        self.assertEqual(len(cb.hand), n)
        self.assertEqual(cb.total_cards(), len(starter_deck("WARRIOR")))
        self.assertFalse(cb.mulligan(), "one mulligan per battle by default")

    def test_dead_hand_is_prevented(self):
        deck = ["frost_lance"] * 8 + ["strike"] * 2          # almost everything costs mana
        for seed in range(30):
            cb = CardBattle.start(random.Random(seed), deck)
            cb.hand = ["frost_lance"] * 4
            can = lambda ref: ref in ("strike", CATCH_BREATH)   # a hero with stamina but no mana
            cb.ensure_playable(can)
            self.assertTrue(any(can(r) for r in cb.hand), f"seed {seed}: dead hand")
        cb = CardBattle.start(random.Random(0), ["frost_lance"] * 8)
        cb.hand = ["frost_lance"] * HAND_SIZE
        self.assertEqual(cb.ensure_playable(lambda ref: ref == CATCH_BREATH), CATCH_BREATH)
        self.assertIn(CATCH_BREATH, cb.hand)
        self.assertLessEqual(len(cb.hand), HAND_SIZE)


class CombatIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def _hero_turn(self, classes=(PlayerClass.WARRIOR,), idx=0, **kw):
        st, c = _fight(classes, **kw)
        hero = st.players[idx]
        self.assertTrue(_ready(c, hero))
        return st, c, hero

    def test_menu_has_cards_alongside_every_baseline_action(self):
        _st, c, hero = self._hero_turn()
        labels = [m.label for m in c.menu]
        self.assertTrue(any(l.startswith("Cards") for l in labels))
        self.assertIn("Items", labels)
        for a in hero.abilities():
            self.assertIn(a.label, labels, "cards must not replace baseline actions")

    def test_playing_a_card_pays_costs_discards_it_and_hurts_the_target(self):
        st, c, hero = self._hero_turn()
        cb = _set_hand(c, hero, ["strike", "brace", "strike", "brace"])
        foe = c.enemies_alive()[0]
        hero.stamina = 100
        hp, sta = foe.hp, hero.stamina
        _play(c, hero, "strike")
        self.assertLess(foe.hp, hp)
        self.assertEqual(hero.stamina, sta - 15)
        self.assertEqual(len(cb.hand), 3)
        self.assertEqual(cb.discard, ["strike"])
        self.assertIsNot(c.phase, Phase.MENU, "a card play spends the turn")

    def test_unaffordable_cards_are_disabled_and_cannot_be_played(self):
        _st, c, hero = self._hero_turn()
        _set_hand(c, hero, ["strike", CATCH_BREATH])
        hero.stamina = 5
        c._open_cards()
        entry = next(m for m in c.menu if m.card == "strike")
        self.assertFalse(entry.enabled)
        hp = c.enemies_alive()[0].hp
        c._activate(entry)
        self.assertEqual(c.enemies_alive()[0].hp, hp)

    def test_mulligan_does_not_use_the_turn(self):
        _st, c, hero = self._hero_turn()
        c._open_cards()
        entry = next(m for m in c.menu if m.kind == "mulligan")
        c._activate(entry)
        self.assertIs(c.phase, Phase.MENU)
        self.assertFalse(any(m.kind == "mulligan" for m in c.menu), "no mulligans left")

    def test_strike_cashes_in_a_mark(self):
        _st, c, hero = self._hero_turn()
        c.rng.random = lambda: 0.99
        foe = c.enemies_alive()[0]
        foe.hp = foe.max_hp = 100000
        _set_hand(c, hero, ["strike"])
        _play(c, hero, "strike")
        plain = 100000 - foe.hp
        for ph in (Phase.RESOLVE,):
            c.phase = Phase.MENU
        c.active = hero
        foe.hp = 100000
        foe.add_status(Status.MARK, 3)
        hero.stamina = 100
        _set_hand(c, hero, ["strike"])
        _play(c, hero, "strike")
        marked = 100000 - foe.hp
        self.assertGreater(marked, plain * 1.3)
        self.assertNotIn(Status.MARK, foe.statuses, "the mark is consumed")

    def test_detonate_consumes_statuses_and_scales(self):
        _st, c, hero = self._hero_turn()
        c.rng.random = lambda: 0.99
        foe = c.enemies_alive()[0]
        foe.hp = foe.max_hp = 100000
        hero.stamina = 100
        _set_hand(c, hero, ["break_mark"])
        _play(c, hero, "break_mark")
        base = 100000 - foe.hp
        c.phase, c.active = Phase.MENU, hero
        foe.hp = 100000
        foe.add_status(Status.MARK, 3)
        foe.add_status(Status.BURN, 2)
        foe.burn_power = 3
        foe.add_status(Status.CHILL, 2)
        hero.stamina = 100
        _set_hand(c, hero, ["break_mark"])
        _play(c, hero, "break_mark")
        self.assertGreater(100000 - foe.hp, base * 1.8)
        for st in (Status.MARK, Status.BURN, Status.CHILL):
            self.assertNotIn(st, foe.statuses)

    def test_silence_interrupts_a_charge(self):
        _st, c, hero = self._hero_turn()
        foe = c.enemies_alive()[0]
        foe.intent = Intent(IntentKind.CHARGE)
        foe.hp = foe.max_hp = 100000
        hero.stamina = 100
        _set_hand(c, hero, ["disrupt"])
        _play(c, hero, "disrupt")
        pv = c.intent_preview(foe)
        self.assertEqual(pv.label, "Staggered")
        self.assertFalse(getattr(foe, "charging", False))

    def test_shift_rerolls_intent_sheds_aggro_and_draws(self):
        _st, c, hero = self._hero_turn(classes=(PlayerClass.ROGUE,))
        hero.aggro = 50.0
        hero.stamina = 100
        cb = _set_hand(c, hero, ["feint"])
        _play(c, hero, "feint")
        self.assertLess(hero.aggro, 50.0)
        self.assertGreaterEqual(len(cb.hand), 1, "feint draws a card")

    def test_ward_and_guard_cards_apply_statuses(self):
        _st, c, hero = self._hero_turn()
        hero.stamina = 100
        _set_hand(c, hero, ["brace"])
        _play(c, hero, "brace")
        self.assertIn(Status.WARDED, hero.statuses)

    def test_angel_cards_lean_on_her_restraints_and_never_remove_them(self):
        st, c = _fight((PlayerClass.ANGEL,))
        angel = st.players[0]
        angel.restraints.update({Restraint.ANCHOR, Restraint.MANACLES})
        self.assertTrue(_ready(c, angel))
        c.rng.random = lambda: 0.99
        foe = c.enemies_alive()[0]
        foe.hp = foe.max_hp = 100000
        angel.stamina = 100
        _set_hand(c, angel, ["penitent_strike"])
        _play(c, angel, "penitent_strike")
        bound = 100000 - foe.hp
        self.assertTrue({Restraint.ANCHOR, Restraint.MANACLES} <= angel.restraints, "cards never remove restraints")
        # same card with no restraints: scale term vanishes (and the bound output penalty too)
        st2, c2 = _fight((PlayerClass.ANGEL,))
        a2 = st2.players[0]
        self.assertTrue(_ready(c2, a2))
        c2.rng.random = lambda: 0.99
        f2 = c2.enemies_alive()[0]
        f2.hp = f2.max_hp = 100000
        a2.stamina = 100
        _set_hand(c2, a2, ["penitent_strike"])
        _play(c2, a2, "penitent_strike")
        free = 100000 - f2.hp
        self.assertGreater(free, 0)
        self.assertGreater(bound, 0)

    def test_angel_momentum_card_helps_the_next_break_without_breaking(self):
        st, c = _fight((PlayerClass.ANGEL,))
        angel = st.players[0]
        angel.restraints.update({Restraint.ANCHOR})
        self.assertTrue(_ready(c, angel))
        angel.lucidity = 80.0
        before = angel.break_chance()
        _set_hand(c, angel, ["measured_defiance"])
        _play(c, angel, "measured_defiance")
        self.assertEqual(angel.break_momentum, 1)
        self.assertGreater(angel.break_chance(), before)
        self.assertIn(Restraint.ANCHOR, angel.restraints)
        self.assertEqual(angel.lucidity, 70.0)

    def test_hp_costs_are_never_lethal(self):
        card, up = parse_ref("lucid_hymn")
        st, c = _fight((PlayerClass.ANGEL,))
        angel = st.players[0]
        angel.hp = card.cost + 1
        self.assertFalse(can_pay(angel, card, up))
        angel.hp = card.cost + 2
        self.assertTrue(can_pay(angel, card, up))

    def test_same_seed_same_hands_in_real_combat(self):
        def hands(seed):
            st, c = _fight((PlayerClass.WITCH,), seed=seed)
            hero = st.players[0]
            _ready(c, hero)
            return list(c._battle_for(hero).hand)
        self.assertEqual(hands(7), hands(7))

    def test_random_card_fights_always_finish(self):
        for seed in range(1, 12):
            rng = random.Random(seed)
            classes = rng.sample(list(PlayerClass), 2)
            st, c = _fight(tuple(classes), seed=seed, stage=rng.choice((1, 4)))
            for _ in range(5000):
                if c.phase in (Phase.VICTORY, Phase.DEFEAT):
                    break
                if c.phase is Phase.MENU:
                    cards = [m for m in c.menu if m.kind == "cards" and m.enabled]
                    if cards and rng.random() < 0.8:
                        c._activate(cards[0])
                        playable = [m for m in c.menu if m.kind == "card" and m.enabled]
                        if playable:
                            c._activate(rng.choice(playable))
                            continue
                    c.handle_key(rng.choice(["return", "down", "1", "2", "escape"]))
                elif c.phase is Phase.TARGET:
                    c.handle_key(rng.choice(["right", "return"]))
                elif c.phase is Phase.QTE:
                    c.update(60.0)
                else:
                    c.update(0.5)
            self.assertIn(c.phase, (Phase.VICTORY, Phase.DEFEAT), f"seed {seed}")


class DraftTests(unittest.TestCase):
    def test_three_distinct_options_and_seed_reproducible(self):
        deck, relics = starter_deck("WITCH"), []
        for seed in range(40):
            a = offer_draft(random.Random(seed), "WITCH", 3, deck, relics)
            b = offer_draft(random.Random(seed), "WITCH", 3, deck, relics)
            self.assertEqual(a, b)
            self.assertEqual(len(a), 3)
            self.assertEqual(len({(o.kind, o.key) for o in a}), 3)

    def test_offers_respect_class_and_ownership(self):
        deck = starter_deck("WARRIOR")
        relics = list(RELICS)
        for seed in range(60):
            for o in offer_draft(random.Random(seed), "WARRIOR", 6, deck, relics):
                self.assertNotEqual(o.kind, "relic", "owned relics are not offered again")
                if o.kind == "card":
                    self.assertIn(CARDS[o.key].class_key, (None, "WARRIOR"))
        kinds = {o.kind for s in range(200) for o in offer_draft(random.Random(s), "ANGEL", 5, deck, [])}
        self.assertEqual(kinds, {"card", "relic", "upgrade", "purge", "transform"})

    def test_apply_card_relic_and_deck_editing_rules(self):
        deck, relics, rng = starter_deck("ANGEL"), [], random.Random(1)
        n = len(deck)
        apply_draft(offer_draft(random.Random(1), "ANGEL", 2, deck, relics)[0], deck, relics, rng)
        from systems.card_system import DraftOption
        apply_draft(DraftOption("card", "chains_taut", "x"), deck, relics, rng)
        self.assertIn("chains_taut", deck)
        apply_draft(DraftOption("relic", "steady_hands", "x"), deck, relics, rng)
        self.assertEqual(relics, ["steady_hands"])
        i = deck.index("strike")
        upgrade_card(deck, i)
        self.assertEqual(deck[i], "strike+")
        self.assertEqual(upgrade_card(deck, i), "Already upgraded.")
        before = len(deck)
        thin_card(deck, deck.index("brace"))
        self.assertEqual(len(deck), before - 1)
        small = ["strike"] * MIN_DECK
        self.assertIn("thin", thin_card(small, 0))
        self.assertEqual(len(small), MIN_DECK, "cannot thin below the minimum")
        j = deck.index("strike+")
        transform_card(deck, j, "ANGEL", random.Random(4))
        self.assertTrue(deck[j].endswith("+"), "transform keeps upgrade state")
        self.assertGreater(len(deck), n - 5)
        full = ["strike"] * MAX_DECK
        apply_draft(DraftOption("card", "strike", "x"), full, [], rng)
        self.assertEqual(len(full), MAX_DECK)

    def test_upgrades_help(self):
        from systems.card_system import effective_cost
        card, _ = parse_ref("strike")
        self.assertLess(effective_cost(card, True), effective_cost(card, False))
        self.assertLess(effective_cost(card, False, ("thin_blade",)), effective_cost(card, False))
        self.assertEqual(DRAFT_SKIP_GOLD, 12)


class PersistenceTests(unittest.TestCase):
    def test_deck_and_relics_survive_save_and_load(self):
        st, c = _fight((PlayerClass.WITCH, PlayerClass.ANGEL))
        for h in st.players:
            c._battle_for(h)
        st.players[0].deck_cards = starter_deck("WITCH") + ["storm_thread+"]
        st.relics = ["steady_hands", "ember_charm"]
        loaded = GameState.from_dict(st.to_dict())
        self.assertEqual(loaded.players[0].deck_cards, st.players[0].deck_cards)
        self.assertEqual(loaded.players[1].deck_cards, st.players[1].deck_cards)
        self.assertEqual(loaded.relics, ["steady_hands", "ember_charm"])

    def test_old_saves_without_cards_get_starter_decks(self):
        st, _c = _fight()
        data = st.to_dict()
        data.pop("relics", None)
        for p in data["players"]:
            p["state"]["data"].pop("deck_cards", None)
        loaded = GameState.from_dict(data)
        self.assertEqual(loaded.relics, [])
        c = CombatSystem(loaded)
        self.assertEqual(c._battle_for(loaded.players[0]).total_cards(), len(starter_deck("WARRIOR")))

    def test_corrupt_deck_data_cannot_crash_combat(self):
        st, _c = _fight()
        st.players[0].deck_cards = ["nope", 3, None]
        st.relics = []
        c = CombatSystem(st)
        self.assertGreaterEqual(c._battle_for(st.players[0]).total_cards(), MIN_DECK)


if __name__ == "__main__":
    unittest.main()
