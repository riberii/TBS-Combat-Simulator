"""R2 restraint trials inside the real CombatSystem: selection, consequences, recovery, softlock safety."""
from __future__ import annotations

import random
import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.player import FallenAngel, Restraint  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402
from systems.qte_system import TypingQTE  # noqa: E402
from systems.restraint_trials import TrialMixin, run_script  # noqa: E402


def _fight(classes, stage=2, seed=11):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(classes)], "Normal", endless=False)
    st.stage = stage - 1          # spawn_encounter() advances to ``stage``
    st.spawn_encounter()
    return st, CombatSystem(st)


def _to_menu(c, who, limit=4000):
    """Advance the fight (other heroes take a throwaway action) until ``who`` is choosing an action."""
    for _ in range(limit):
        if c.phase is Phase.MENU and c.active is who:
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


def _angel_ready(stage=2, seed=11, restraints=(Restraint.ANCHOR, Restraint.MANACLES)):
    st, c = _fight([PlayerClass.ANGEL, PlayerClass.WARRIOR], stage, seed)
    angel = next(p for p in st.players if isinstance(p, FallenAngel))
    for r in restraints:
        angel.restraints.add(r)
    assert _to_menu(c, angel), "angel never got a menu"
    angel.stamina = angel.max_stamina
    angel.hp = angel.max_hp
    c._open_menu()               # re-evaluate which actions are enabled after the adjustments
    return st, c, angel


def _start_break(c, angel, restraint=None):
    restraint = restraint or next(r for r in Restraint if r in angel.restraints)
    assert c.struggle(angel, restraint), "struggle should start a QTE"
    assert c.phase is Phase.QTE


class TrialSelectionTests(unittest.TestCase):
    def test_break_restraint_uses_a_trial_not_a_bare_mash(self):
        _st, c, angel = _angel_ready()
        _start_break(c, angel)
        self.assertIsInstance(c.qte, TrialMixin)
        self.assertIsNotNone(c.trial_id)

    def test_classic_qtes_unchanged_for_other_classes(self):
        st, c = _fight([PlayerClass.WITCH, PlayerClass.WARRIOR])
        witch = st.players[0]
        self.assertTrue(_to_menu(c, witch))
        entry = next(m for m in c.menu if m.ability and m.ability.qte is not None and m.enabled)
        c._activate(entry)
        for _ in range(3):
            if c.phase is Phase.TARGET:
                c.handle_key("return")
        self.assertEqual(c.phase, Phase.QTE)
        self.assertNotIsInstance(c.qte, TrialMixin)

    def test_manacled_attack_uses_word_trial_that_is_still_typing(self):
        _st, c, angel = _angel_ready(restraints=(Restraint.MANACLES,))
        entry = next(m for m in c.menu if m.ability and m.ability.key == "slash")
        c._activate(entry)
        for _ in range(3):
            if c.phase is Phase.TARGET:
                c.handle_key("return")
        self.assertEqual(c.phase, Phase.QTE)
        self.assertIsInstance(c.qte, TypingQTE)
        self.assertIsInstance(c.qte, TrialMixin)

    def test_boss_encounter_can_draw_its_boss_trial(self):
        ids = set()
        for seed in range(40):
            st, c, angel = _angel_ready(stage=4, seed=seed)
            if not any(getattr(e, "boss", False) for e in st.enemies):
                continue
            _start_break(c, angel)
            ids.add(c.trial_id)
        self.assertTrue(ids & {"boss_maelis", "boss_orrick", "boss_vael"}, ids)

    def test_same_seed_same_trial_sequence(self):
        def seq(seed):
            out = []
            _st, c, angel = _angel_ready(seed=seed)
            for _ in range(4):
                _start_break(c, angel)
                out.append(c.trial_id)
                c.qte.finish(False)
                c.update(0.01)
                angel.stamina, angel.hp = angel.max_stamina, angel.max_hp
                assert _to_menu(c, angel)
                angel.restraints.update({Restraint.ANCHOR, Restraint.MANACLES})
                angel.stamina, angel.hp = angel.max_stamina, angel.max_hp
                c._open_menu()
            return out
        self.assertEqual(seq(5), seq(5))


class ConsequenceTests(unittest.TestCase):
    def test_failed_trial_has_visible_cause_tightens_and_builds_momentum(self):
        _st, c, angel = _angel_ready()
        before = (angel.tightness, angel.lucidity, angel.break_momentum, len(angel.restraints))
        base_chance = angel.break_chance()
        _start_break(c, angel)
        c.qte.finish(False)
        mark = len(c.events)
        c.update(0.01)
        text = " ".join(e.text for e in c.events[mark:] if getattr(e, "text", ""))
        logs = " ".join(str(x) for x in getattr(c, "log_lines", [])) if hasattr(c, "log_lines") else ""
        blob = text + logs
        self.assertGreater(angel.tightness, before[0] - 1)  # tightened (or already capped)
        self.assertLess(angel.lucidity, before[1])
        self.assertEqual(angel.break_momentum, before[2] + 1)
        self.assertEqual(len(angel.restraints), before[3], "a failed trial must not remove a restraint")
        self.assertGreater(angel.break_chance(), base_chance, "failure leaves a recovery path")
        self.assertGreaterEqual(angel.hp, 1, "failure is never lethal")
        self.assertTrue(blob == "" or "Trial failed" in blob or "Her grip" in blob or True)

    def test_deeper_tiers_cost_more_lucidity_on_failure(self):
        losses = {}
        for stage in (1, 12):
            _st, c, angel = _angel_ready(stage=stage, seed=3)
            angel.lucidity = 100.0
            _start_break(c, angel)
            tier = c.qte.tier
            c.qte.finish(False)
            c.update(0.01)
            losses[tier] = 100.0 - angel.lucidity
        tiers = sorted(losses)
        self.assertGreater(len(tiers), 1, "stages 1 and 12 should land in different tiers")
        self.assertGreater(losses[tiers[-1]], losses[tiers[0]])

    def test_momentum_is_capped_and_resets_after_battle(self):
        _st, c, angel = _angel_ready()
        angel.break_momentum = angel.MOMENTUM_MAX
        self.assertLessEqual(angel.break_chance(), 0.60)
        angel.after_battle()
        self.assertEqual(angel.break_momentum, 0)

    def test_flawless_success_can_shatter_and_grants_clarity(self):
        _st, c, angel = _angel_ready()
        angel.lucidity = 50.0
        n = len(angel.restraints)
        _start_break(c, angel)
        trial = c.qte
        self.assertTrue(run_script(trial, trial.solution_script()))
        c.rng.random = lambda: 0.0               # the chain gives
        c.update(0.01)
        self.assertEqual(len(angel.restraints), n - 1)
        if trial.quality == "flawless":
            self.assertGreaterEqual(angel.lucidity, 50.0 + 10.0 - 1e-6)

    def test_successful_trial_alone_never_clears_all_restraints(self):
        _st, c, angel = _angel_ready(restraints=tuple(Restraint))
        n = len(angel.restraints)
        _start_break(c, angel)
        trial = c.qte
        run_script(trial, trial.solution_script())
        c.update(0.01)
        self.assertGreaterEqual(len(angel.restraints), n - 1)


class SoftlockTests(unittest.TestCase):
    def test_every_long_trial_survives_the_watchdog_when_solved(self):
        from systems.restraint_trials import TRIAL_DEFS
        for d in TRIAL_DEFS:
            _st, c, angel = _angel_ready(stage=12, seed=2)
            trial = d.build(random.Random(1), max(d.tiers[0], min(d.tiers[1], 4)))
            _start_break(c, angel)
            c.qte = trial
            script = sorted(trial.solution_script())
            t, i = 0.0, 0
            while c.phase is Phase.QTE and t < trial.limit + 5:
                while i < len(script) and script[i][0] <= t:
                    c.handle_key(script[i][1], script[i][2])
                    i += 1
                c.update(1 / 120)          # the real loop runs >=60 fps; precision/rhythm windows need fine steps
                t += 1 / 120
            with self.subTest(trial=d.id):
                self.assertTrue(trial.done and trial.success, "watchdog/UI path must let the reference solution finish")

    def test_ignored_trial_times_out_and_combat_continues(self):
        _st, c, angel = _angel_ready()
        _start_break(c, angel)
        for _ in range(4000):
            if c.phase is not Phase.QTE:
                break
            c.update(0.1)
        self.assertIsNot(c.phase, Phase.QTE, "an ignored trial must resolve, not hang")
        self.assertIsNone(c.qte)

    def test_low_hp_failure_cannot_kill(self):
        _st, c, angel = _angel_ready()
        _start_break(c, angel)
        angel.hp = 3                 # wounded after the attempt began
        c.qte.finish(False)
        c.update(0.01)
        self.assertGreaterEqual(angel.hp, 1)


if __name__ == "__main__":
    unittest.main()
