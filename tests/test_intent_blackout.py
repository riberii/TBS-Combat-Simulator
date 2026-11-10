"""Sensory Deprivation (Fallen Angel) must black out enemy intent everywhere the player can see it.

Regression for: the enemy card read ``enemy.intent`` directly and ignored ``combat.intent_hidden``,
so the real telegraph stayed visible while the Angel was deprived.
"""
from __future__ import annotations

import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.player import FallenAngel, Restraint  # noqa: E402
from systems.combat_system import CombatSystem, EventKind  # noqa: E402


def _fight(classes, stage=2, seed=7):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(classes)], "Normal", endless=False)
    st.stage = stage
    st.spawn_encounter()
    return st, CombatSystem(st)


def _add(angel, restraint):
    r = angel.restraints
    r.add(restraint) if hasattr(r, "add") else r.append(restraint)


class IntentBlackoutTests(unittest.TestCase):
    def test_deprived_angel_hides_every_foe_intent(self):
        st, c = _fight([PlayerClass.ANGEL, PlayerClass.WARRIOR])
        angel = next(p for p in st.players if isinstance(p, FallenAngel))
        _add(angel, Restraint.DEPRIVATION)
        c.active = angel
        self.assertTrue(c.intent_hidden)
        shown = [c.intent_preview(f) for f in c.enemies_alive()]
        self.assertTrue(shown)
        for pv in shown:
            self.assertIsNotNone(pv)
            self.assertTrue(pv.hidden)
            self.assertIsNone(pv.kind, "hidden preview must not carry the real intent kind")
            self.assertEqual(pv.damage, 0)
            self.assertEqual(pv.label, "???")

    def test_other_heroes_still_see_intent(self):
        st, c = _fight([PlayerClass.ANGEL, PlayerClass.WARRIOR])
        angel = next(p for p in st.players if isinstance(p, FallenAngel))
        _add(angel, Restraint.DEPRIVATION)
        c.active = next(p for p in st.players if p is not angel)
        self.assertFalse(c.intent_hidden)
        for f in c.enemies_alive():
            pv = c.intent_preview(f)
            self.assertTrue(pv is None or not pv.hidden)

    def test_no_restraint_no_blackout(self):
        st, c = _fight([PlayerClass.ANGEL])
        angel = st.players[0]
        c.active = angel
        if Restraint.DEPRIVATION not in angel.restraints:
            self.assertFalse(angel.blackout)
            self.assertFalse(c.intent_hidden)

    def test_intent_events_do_not_leak_text_while_deprived(self):
        st, c = _fight([PlayerClass.ANGEL])
        angel = st.players[0]
        _add(angel, Restraint.DEPRIVATION)
        c.active = angel
        events = []
        c._emit = lambda kind, *a, **k: events.append((kind, a, k))  # capture
        c._refresh_intents(force=True)
        intents = [e for e in events if e[0] is EventKind.INTENT]
        self.assertTrue(intents)
        for _k, args, kw in intents:
            text = args[2] if len(args) > 2 else kw.get("text", "")
            self.assertIn("???", text)
            self.assertTrue(kw["data"]["hidden"])
            self.assertEqual(kw["data"]["kind"], "HIDDEN")

    def test_painter_follows_combat_preview(self):
        import main as game
        p = game.Painter.__new__(game.Painter)         # no fonts / surfaces needed for the decision logic
        st, c = _fight([PlayerClass.ANGEL])
        angel = st.players[0]
        foe = c.enemies_alive()[0]
        p.intent_probe = c.intent_preview
        c.active = angel
        self.assertFalse(p._intent_is_hidden(foe))
        _add(angel, Restraint.DEPRIVATION)
        self.assertTrue(p._intent_is_hidden(foe), "enemy card must black out when combat reports hidden")
        p.intent_probe = None
        self.assertFalse(p._intent_is_hidden(foe), "no probe -> fall back to normal display")
        p.intent_probe = lambda e: 1 / 0
        self.assertFalse(p._intent_is_hidden(foe), "broken probe must not crash the renderer")


if __name__ == "__main__":
    unittest.main()
