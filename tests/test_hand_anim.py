"""V3 hand tray layout + animation state (pure python)."""
from __future__ import annotations

import random
import unittest
from dataclasses import replace

from systems.card_system import CardBattle, starter_deck
from systems.hand_view import build_hand_view
from ui.hand_anim import (CARD_W, GHOST_TTL, PILE_POS, REGION_L, REGION_R, Y_PEEK, Y_PENDING, Y_RAISED, Y_SELECTED,
                          HandAnimator, layout)


class _Hero:
    uid, name, stamina, mana, max_mana, hp = 7, "Hero", 100, 40, 40, 100


def _view(cb, **kw):
    args = dict(selected=0, focused=False, pending=-1, pile_view=None, phase="MENU")
    args.update(kw)
    return build_hand_view(_Hero(), cb, **args)


class LayoutTests(unittest.TestCase):
    def test_cards_stay_inside_the_tray_region_for_any_hand_size(self):
        for n in range(1, 10):
            pos = layout(n, 0, False, -1)
            self.assertEqual(len(pos), n)
            self.assertGreaterEqual(pos[0][0], REGION_L - 0.01)
            self.assertLessEqual(pos[-1][0] + CARD_W, REGION_R + 0.01)
            xs = [p[0] for p in pos]
            self.assertEqual(xs, sorted(xs))

    def test_heights_by_state(self):
        peek = layout(5, 2, False, -1)
        self.assertTrue(all(y == Y_PEEK for _x, y in peek))
        raised = layout(5, 2, True, -1)
        self.assertEqual([y for _x, y in raised], [Y_RAISED, Y_RAISED, Y_SELECTED, Y_RAISED, Y_RAISED])
        pend = layout(5, 0, False, 3)
        self.assertEqual(pend[3][1], Y_PENDING)
        self.assertEqual(pend[0][1], Y_PEEK)
        self.assertEqual(layout(0, 0, True, -1), [])


class AnimatorTests(unittest.TestCase):
    def test_opening_hand_is_dealt_from_the_pile(self):
        cb = CardBattle.start(random.Random(4), starter_deck("WARRIOR"))
        a = HandAnimator()
        v = _view(cb)
        a.update(v, 0.016)
        self.assertEqual([s.ref for s in a.slots], cb.hand)
        self.assertTrue(all(abs(s.x - PILE_POS[0]) < CARD_W * 3 for s in a.slots))
        self.assertLess(a.slots[0].alpha, 0.5, "new cards fade in")
        a.settle(v)
        want = layout(len(cb.hand), 0, False, -1)
        for s, (tx, ty) in zip(a.slots, want):
            self.assertAlmostEqual(s.x, tx, delta=1.0)
            self.assertAlmostEqual(s.y, ty, delta=1.0)
            self.assertEqual(s.alpha, 1.0)

    def test_playing_a_card_spawns_a_fading_ghost(self):
        cb = CardBattle.start(random.Random(4), starter_deck("WARRIOR"))
        a = HandAnimator()
        a.settle(_view(cb))
        ref = cb.hand[1]
        cb.play(1)
        a.update(_view(cb), 0.05)
        self.assertEqual([s.ref for s in a.slots], cb.hand)
        self.assertEqual(len(a.ghosts), 1)
        self.assertEqual(a.ghosts[0].ref, ref)
        self.assertGreater(a.ghosts[0].alpha, 0.5)
        for _ in range(20):
            a.update(_view(cb), 0.05)
        self.assertEqual(a.ghosts, [], f"ghosts vanish after {GHOST_TTL}s")

    def test_drawing_adds_a_slot_without_disturbing_others(self):
        cb = CardBattle.start(random.Random(4), starter_deck("WARRIOR"))
        cb.hand = cb.hand[:3]
        a = HandAnimator()
        a.settle(_view(cb))
        before = [(s.x, s.y) for s in a.slots]
        cb.draw(1)
        a.update(_view(cb), 0.016)
        self.assertEqual(len(a.slots), 4)
        self.assertEqual([s.ref for s in a.slots], cb.hand)
        self.assertEqual(a.slots[3].alpha < 0.5, True)
        self.assertEqual(len(before), 3)

    def test_mulligan_ghosts_the_old_hand_and_deals_the_new_one(self):
        cb = CardBattle.start(random.Random(5), starter_deck("WITCH"))
        a = HandAnimator()
        a.settle(_view(cb))
        old = list(cb.hand)
        cb.mulligan()
        a.update(_view(cb), 0.016)
        self.assertEqual(len(a.ghosts), len(old))
        self.assertEqual([s.ref for s in a.slots], cb.hand)

    def test_resyncs_if_the_hand_is_edited_behind_its_back(self):
        cb = CardBattle.start(random.Random(6), starter_deck("WARRIOR"))
        a = HandAnimator()
        a.settle(_view(cb))
        cb.hand = ["brace", "strike"]                     # no events emitted
        a.update(_view(cb), 0.016)
        self.assertEqual([s.ref for s in a.slots], ["brace", "strike"])
        cb.hand = []
        a.update(_view(cb), 0.016)
        self.assertEqual(a.slots, [])

    def test_each_hero_has_its_own_event_cursor(self):
        cb1 = CardBattle.start(random.Random(1), starter_deck("WARRIOR"))
        cb2 = CardBattle.start(random.Random(2), starter_deck("WITCH"))
        a = HandAnimator()
        v1 = _view(cb1)
        v2 = replace(_view(cb2), hero_uid=8)
        a.settle(v1)
        a.settle(v2)
        self.assertEqual([s.ref for s in a.slots], cb2.hand)
        a.update(v1, 0.016)                               # back to hero 1: rebuilt from its hand, no stale ghosts
        self.assertEqual([s.ref for s in a.slots], cb1.hand)
        self.assertEqual(a.ghosts, [])

    def test_no_view_only_ages_ghosts_and_never_raises(self):
        a = HandAnimator()
        a.update(None, 0.5)
        self.assertEqual((a.slots, a.ghosts), ([], []))
        cb = CardBattle.start(random.Random(4), starter_deck("WARRIOR"))
        a.settle(_view(cb))
        cb.play(0)
        a.update(_view(cb), 0.01)
        for _ in range(8):
            a.update(None, 0.1)
        self.assertEqual(a.ghosts, [])

    def test_huge_dt_is_clamped(self):
        cb = CardBattle.start(random.Random(4), starter_deck("WARRIOR"))
        a = HandAnimator()
        a.update(_view(cb), 999.0)
        self.assertTrue(all(0.0 <= s.alpha <= 1.0 for s in a.slots))


if __name__ == "__main__":
    unittest.main()
