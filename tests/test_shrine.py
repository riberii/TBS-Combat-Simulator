"""Optional risk/reward shrine: costs are visible and never lethal, rewards land, outcomes are seed-reproducible."""
from __future__ import annotations

import random
import unittest
from types import SimpleNamespace as NS

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.game_state import GameState  # noqa: E402
from systems.card_system import MIN_DECK, RELICS, starter_deck  # noqa: E402
from systems.shrine import (SHRINE_KEYS, apply_shrine, gamble_gold, offering_gold, penance_cost, roll_shrine,  # noqa: E402
                            unavailable_reason)


def hero(hp=40, cls="WARRIOR", deck=None):
    return NS(hp=hp, max_hp=60, pclass=NS(name=cls), deck_cards=list(deck if deck is not None else starter_deck(cls)))


class ShrineTests(unittest.TestCase):
    def test_offers_are_three_distinct_and_reproducible(self):
        a = [o.key for o in roll_shrine(random.Random("x"), 4)]
        b = [o.key for o in roll_shrine(random.Random("x"), 4)]
        self.assertEqual(a, b)
        self.assertEqual(len(set(a)), 3)
        self.assertTrue(set(a) <= set(SHRINE_KEYS))
        for o in roll_shrine(random.Random(1), 6):
            self.assertEqual(o.kind, "bargain")
            self.assertTrue(o.label and o.text)

    def test_blood_pact_costs_hp_gives_relic_and_never_kills(self):
        ps = [hero(40), hero(2), hero(1)]
        relics: list[str] = []
        r = apply_shrine("blood_pact", ps, ps[0], 0, relics, 3, random.Random(1))
        self.assertTrue(r.ok)
        self.assertEqual(ps[0].hp, 28)
        self.assertEqual((ps[1].hp, ps[2].hp), (2, 1), "weak heroes are untouched, never killed")
        self.assertEqual(len(relics), 1)
        self.assertIn(relics[0], RELICS)

    def test_blood_pact_unavailable_without_relics_or_hp(self):
        h = hero(40)
        every = [k for k, r in RELICS.items() if r.class_key in (None, "WARRIOR")]
        self.assertIsNotNone(unavailable_reason("blood_pact", [h], h, 0, every, 2))
        self.assertIsNotNone(unavailable_reason("blood_pact", [hero(3)], hero(3), 0, [], 2))
        before = hero(40)
        res = apply_shrine("blood_pact", [before], before, 0, list(every), 2, random.Random(1))
        self.assertFalse(res.ok)
        self.assertEqual(before.hp, 40, "a refused bargain changes nothing")

    def test_penance_needs_gold_and_upgrades_exactly_one_card(self):
        h = hero()
        self.assertIsNotNone(unavailable_reason("gilded_penance", [h], h, penance_cost(2) - 1, [], 2))
        r = apply_shrine("gilded_penance", [h], h, 500, [], 2, random.Random(3))
        self.assertTrue(r.ok)
        self.assertEqual(r.gold_delta, -penance_cost(2))
        self.assertEqual(sum(c.endswith("+") for c in h.deck_cards), 1)

    def test_burnt_offering_respects_minimum_deck(self):
        h = hero()
        n = len(h.deck_cards)
        self.assertGreater(n, MIN_DECK - 1)
        small = hero(deck=h.deck_cards[:MIN_DECK])
        self.assertIsNotNone(unavailable_reason("burnt_offering", [small], small, 0, [], 2))
        res = apply_shrine("burnt_offering", [h], h, 0, [], 2, random.Random(4)) if n > MIN_DECK else None
        if res:
            self.assertEqual((len(h.deck_cards), res.gold_delta), (n - 1, offering_gold(2)))

    def test_gamble_has_both_outcomes_and_is_never_lethal(self):
        wins = losses = 0
        for s in range(60):
            ps = [hero(40), hero(1)]
            r = apply_shrine("choirs_gamble", ps, ps[0], 0, [], 3, random.Random(s))
            self.assertTrue(r.ok)
            self.assertGreaterEqual(ps[1].hp, 1)
            if r.gold_delta:
                wins += 1
                self.assertEqual((r.gold_delta, ps[0].hp), (gamble_gold(3), 40))
            else:
                losses += 1
                self.assertEqual(ps[0].hp, 30)
        self.assertTrue(wins > 10 and losses > 10)

    def test_same_seed_same_outcome(self):
        a, b = hero(), hero()
        ra = apply_shrine("choirs_gamble", [a], a, 0, [], 5, random.Random("k"))
        rb = apply_shrine("choirs_gamble", [b], b, 0, [], 5, random.Random("k"))
        self.assertEqual((ra.message, a.hp), (rb.message, b.hp))

    def test_shrine_stage_survives_save_load(self):
        from core.config import PlayerClass
        from core.game_state import PlayerConfig
        st = GameState(seed=5)
        st.new_run([PlayerConfig("A", PlayerClass.WARRIOR)], "Normal", endless=False)
        st.shrine_stage = 7
        self.assertEqual(GameState.from_dict(st.to_dict()).shrine_stage, 7)
        d = st.to_dict()
        d["shrine_stage"] = "bad"
        self.assertEqual(GameState.from_dict(d).shrine_stage, 0)


if __name__ == "__main__":
    unittest.main()
