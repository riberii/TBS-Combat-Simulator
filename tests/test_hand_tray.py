"""V3 card hand tray: keyboard flow, snapshots, animation events. Pure logic (stub pygame), seed-reproducible."""
from __future__ import annotations

import logging
import random
import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.enemy import Intent, IntentKind  # noqa: E402
from systems.card_system import CATCH_BREATH, CardBattle, starter_deck  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402
from systems.hand_view import PILES  # noqa: E402


def _fight(classes=(PlayerClass.WARRIOR,), seed=9, stage=2):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(classes)], "Normal", endless=False)
    st.stage = stage - 1
    st.spawn_encounter()
    return st, CombatSystem(st)


def _ready(c, hero, limit=3000):
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


class EventLogTests(unittest.TestCase):
    def test_draw_play_exhaust_and_mulligan_emit_events(self):
        cb = CardBattle.start(random.Random(3), ["catch_breath", "strike", "strike", "brace", "brace", "mark_prey", "break_mark"])
        kinds = [e[1] for e in cb.events]
        self.assertEqual(kinds.count("draw"), len(cb.hand))
        serial = cb.event_serial
        cb.hand = ["catch_breath", "strike"]
        cb.play(0)
        cb.play(0)
        self.assertEqual([e[1] for e in cb.events_since(serial)], ["exhaust", "play"])
        cb.hand = ["strike", "brace"]
        serial = cb.event_serial
        self.assertTrue(cb.mulligan())
        self.assertEqual(cb.events_since(serial)[0][1], "mulligan")

    def test_event_log_is_bounded_and_serials_increase(self):
        cb = CardBattle.start(random.Random(1), starter_deck("WARRIOR"))
        for _ in range(200):
            cb.draw(5)
            while cb.hand:
                cb.play(0)
        self.assertLessEqual(len(cb.events), 48)
        serials = [e[0] for e in cb.events]
        self.assertEqual(serials, sorted(serials))
        self.assertEqual(cb.event_serial, serials[-1])

    def test_pile_viewer_never_reveals_draw_order(self):
        cb = CardBattle.start(random.Random(2), starter_deck("WITCH"))
        shown = cb.pile_contents("draw")
        self.assertEqual(sorted(shown), sorted(cb.draw_pile))
        self.assertEqual(cb.pile_counts()["draw"], len(cb.draw_pile))
        self.assertEqual(cb.pile_contents("nonsense"), [])


class TrayFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def _turn(self, classes=(PlayerClass.WARRIOR,), **kw):
        st, c = _fight(classes, **kw)
        hero = st.players[0]
        self.assertTrue(_ready(c, hero))
        return st, c, hero

    def test_view_exists_on_the_players_turn_and_matches_the_hand(self):
        _st, c, hero = self._turn()
        v = c.hand_view()
        cb = c.card_battles[hero.uid]
        self.assertIsNotNone(v)
        self.assertEqual([x.ref for x in v.cards], cb.hand)
        self.assertEqual(v.counts, (len(cb.draw_pile), len(cb.discard), len(cb.exhausted)))
        self.assertFalse(v.focused)
        self.assertEqual(v.selected, 0)
        self.assertEqual(v.hero_name, hero.name)

    def test_no_view_during_enemy_phase(self):
        _st, c, _hero = self._turn()
        c.phase = Phase.ENEMY
        self.assertIsNone(c.hand_view())

    def test_tab_focuses_hand_and_arrows_wrap(self):
        _st, c, hero = self._turn()
        n = len(c.card_battles[hero.uid].hand)
        c.handle_key("tab")
        self.assertTrue(c.hand_view().focused)
        for _ in range(n):
            c.handle_key("right")
        self.assertEqual(c.hand_idx, 0)
        c.handle_key("left")
        self.assertEqual(c.hand_idx, n - 1)
        c.handle_key("escape")
        self.assertFalse(c.hand_view().focused)
        self.assertIs(c.phase, Phase.MENU)

    def test_enter_plays_the_selected_card_from_the_tray(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        cb.hand = ["brace", "strike", "brace"]
        hero.stamina = 100
        foe = c.enemies_alive()[0]
        c.handle_key("tab")
        c.handle_key("right")                      # strike
        hp, sta = foe.hp, hero.stamina
        c.handle_key("return")
        if c.phase is Phase.TARGET:
            c.handle_key("return")
        self.assertLess(foe.hp, hp)
        self.assertEqual(hero.stamina, sta - 15)
        self.assertEqual(cb.discard, ["strike"])
        self.assertEqual(cb.hand, ["brace", "brace"])

    def test_number_keys_play_that_card_when_focused_but_pick_menu_rows_otherwise(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        cb.hand = ["brace", "brace"]
        hero.stamina = 100
        c.handle_key("tab")
        c.handle_key("2")
        self.assertEqual(len(cb.hand), 1)
        _st2, c2, hero2 = self._turn(seed=11)
        cb2 = c2.card_battles[hero2.uid]
        before = list(cb2.hand)
        c2.handle_key("1")                         # not focused: first ability row, never a card
        self.assertEqual(cb2.hand, before)

    def test_unaffordable_card_is_refused_and_keeps_the_turn(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        cb.hand = ["strike"]
        hero.stamina = 0
        c.handle_key("tab")
        c.handle_key("return")
        self.assertIs(c.phase, Phase.MENU)
        self.assertEqual(cb.hand, ["strike"])
        self.assertFalse(c.hand_view().cards[0].playable)

    def test_escape_from_target_returns_to_the_tray(self):
        import copy
        from entities.base_entity import BaseEntity
        st, c, hero = self._turn()
        twin = copy.deepcopy(st.enemies[0])
        twin.uid = next(BaseEntity._uids)
        st.enemies.append(twin)                    # two foes: a single-target card must ask for a target
        cb = c.card_battles[hero.uid]
        cb.hand = ["strike", "brace"]
        hero.stamina = 100
        c.handle_key("tab")
        c.handle_key("return")
        self.assertIs(c.phase, Phase.TARGET)
        self.assertEqual(c.hand_view().pending, 0)
        self.assertFalse(c.hand_view().focused, "the tray lowers while you pick a target")
        c.handle_key("escape")
        self.assertIs(c.phase, Phase.MENU)
        self.assertTrue(c.hand_view().focused, "Esc from targeting goes back to the tray")
        self.assertEqual(cb.hand, ["strike", "brace"])
        self.assertEqual(hero.stamina, 100, "nothing was paid")
        c.handle_key("return")                     # play again, this time confirm the target
        c.handle_key("right")
        c.handle_key("return")
        self.assertEqual(cb.hand, ["brace"])
        self.assertEqual(hero.stamina, 85)

    def test_mulligan_key_is_free_and_limited(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        n = len(cb.hand)
        c.handle_key("tab")
        c.handle_key("m")
        self.assertIs(c.phase, Phase.MENU)
        self.assertEqual(len(cb.hand), n)
        self.assertEqual(cb.mulligans, 0)
        total = cb.total_cards()
        c.handle_key("m")                          # no mulligans left: refused, nothing changes
        self.assertEqual(cb.total_cards(), total)

    def test_pile_viewer_cycles_and_closes(self):
        _st, c, _hero = self._turn()
        c.handle_key("v")
        seen = [c.hand_view().pile_view]
        c.handle_key("v")
        seen.append(c.hand_view().pile_view)
        c.handle_key("v")
        seen.append(c.hand_view().pile_view)
        c.handle_key("v")
        self.assertEqual(seen, list(PILES))
        self.assertIsNone(c.hand_view().pile_view)
        c.handle_key("v")
        c.handle_key("escape")
        self.assertIsNone(c.hand_view().pile_view)
        self.assertIs(c.phase, Phase.MENU)

    def test_viewer_swallows_other_keys(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        before = list(cb.hand)
        c.handle_key("v")
        c.handle_key("return")                     # closes the viewer, must not activate a menu row
        self.assertIs(c.phase, Phase.MENU)
        self.assertIsNone(c.hand_view().pile_view)
        self.assertEqual(cb.hand, before)

    def test_baseline_menu_flow_is_unchanged_without_tab(self):
        _st, c, hero = self._turn()
        c.handle_key("down")
        self.assertEqual(c.menu_idx, 1)
        self.assertFalse(c.hand_focus)
        c.handle_key("left")                       # arrows left/right do nothing in the plain menu
        self.assertIs(c.phase, Phase.MENU)

    def test_tab_with_empty_hand_is_refused(self):
        _st, c, hero = self._turn()
        cb = c.card_battles[hero.uid]
        cb.hand = []
        c.handle_key("tab")
        self.assertFalse(c.hand_focus)
        self.assertEqual(c.hand_view().cards, ())
        self.assertEqual(c.hand_view().selected, -1)

    def test_focus_resets_on_the_next_heros_turn(self):
        st, c, hero = self._turn((PlayerClass.WARRIOR, PlayerClass.WITCH))
        c.handle_key("tab")
        c.handle_key("right")
        self.assertTrue(c.hand_focus)
        c._open_menu()
        self.assertFalse(c.hand_focus)
        for _ in range(4000):
            if c.phase in (Phase.VICTORY, Phase.DEFEAT) or (c.phase is Phase.MENU and c.active is not hero):
                break
            if c.phase in (Phase.MENU, Phase.TARGET):
                c.handle_key("return")
            elif c.phase is Phase.QTE:
                c.update(60.0)
            else:
                c.update(0.5)
        if c.phase is Phase.MENU:
            self.assertEqual(c.hand_idx, 0)
            self.assertFalse(c.hand_focus)

    def test_random_tray_fights_always_finish(self):
        for seed in range(1, 10):
            rng = random.Random(seed)
            classes = tuple(rng.sample(list(PlayerClass), 2))
            st, c = _fight(classes, seed=seed, stage=rng.choice((1, 4)))
            for _ in range(6000):
                if c.phase in (Phase.VICTORY, Phase.DEFEAT):
                    break
                if c.phase is Phase.MENU:
                    c.handle_key(rng.choice(["tab", "right", "left", "return", "return", "1", "2", "3", "m", "v", "escape", "down"]))
                elif c.phase is Phase.TARGET:
                    c.handle_key(rng.choice(["right", "return", "escape"]))
                elif c.phase is Phase.QTE:
                    c.update(60.0)
                else:
                    c.update(0.5)
                v = c.hand_view()
                if v is not None and v.cards:
                    self.assertTrue(0 <= v.selected < len(v.cards))
            self.assertIn(c.phase, (Phase.VICTORY, Phase.DEFEAT), f"seed {seed}")


if __name__ == "__main__":
    unittest.main()
