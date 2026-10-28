"""R2 tests: restraint trial library, anti-spam mash, escalating Break backlash.

These exercise the real source modules (no mocks of game logic).  They need no display; if pygame-ce is
missing, tools.headless_bootstrap installs the import-only stub exactly like the other tests do.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.headless_bootstrap import install_import_stub_if_missing  # noqa: E402

install_import_stub_if_missing()

from entities.player import FallenAngel, Restraint  # noqa: E402
from systems.restraint_trials import (  # noqa: E402
    TRIAL_LIBRARY, AlternatingQTE, ConditionalSigilQTE, CounterRhythmQTE, PacedMashQTE, SealStagesQTE,
    build_trial, make_trial, trial_ids,
)


def drive_presses(q: PacedMashQTE, rate: float, seconds: float, step: float = 0.005) -> None:
    """Press [space] `rate` times a second on the QTE's own clock."""
    next_press, t = 0.0, 0.0
    while t < seconds and not q.done:
        if t >= next_press:
            q.handle_key("space", " ")
            next_press += 1.0 / rate
        q.update(step)
        t += step


class PacedMashTests(unittest.TestCase):
    def fresh(self, tier: int = 1) -> PacedMashQTE:
        need = 10 + 2 * tier
        return PacedMashQTE(need, need / 4.0 + 2.5)

    def test_steady_rhythm_succeeds(self) -> None:
        for rate in (3.5, 4.0, 5.0):
            q = self.fresh()
            drive_presses(q, rate, q.limit)
            self.assertTrue(q.done and q.success, f"steady {rate}/s should win (credit {q.credit:.1f})")

    def test_hammering_fails(self) -> None:
        for rate in (8.0, 12.0, 20.0, 40.0, 100.0):
            for tier in (1, 4, 8):
                q = self.fresh(tier)
                drive_presses(q, rate, q.limit + 1.0)
                self.assertTrue(q.done and not q.success, f"mash {rate}/s tier {tier} must fail (credit {q.credit:.1f}/{q.need})")

    def test_macro_burst_is_jammed(self) -> None:
        q = self.fresh()
        for _ in range(500):          # 500 presses in the same instant
            q.handle_key("space", " ")
        self.assertEqual(q.accepted, 1)
        self.assertGreaterEqual(q.jams, 499)
        self.assertFalse(q.done)

    def test_fatigue_recovers_with_rest(self) -> None:
        q = self.fresh()
        drive_presses(q, 12.0, 1.0)
        tired = q.fatigue
        self.assertGreater(tired, 0.5)
        for _ in range(200):
            q.update(0.01)
            if q.done:
                break
        self.assertLess(q.fatigue, tired)

    def test_ignores_other_keys_and_post_finish_input(self) -> None:
        q = self.fresh()
        q.handle_key("x", "x")
        self.assertEqual(q.accepted, 0)
        q.finish(False)
        q.handle_key("space", " ")
        self.assertEqual(q.accepted, 0)

    def test_times_out(self) -> None:
        q = self.fresh()
        for _ in range(int(q.limit / 0.1) + 5):
            q.update(0.1)
        self.assertTrue(q.done and not q.success)


class OtherTrialTests(unittest.TestCase):
    def test_alternating_requires_alternation(self) -> None:
        q = AlternatingQTE(6, 10.0)
        for i in range(6):
            q.handle_key("left" if i % 2 == 0 else "right", "")
        self.assertTrue(q.done and q.success)
        q = AlternatingQTE(6, 10.0)
        for _ in range(6):
            q.handle_key("left", "")
        self.assertTrue(q.done and not q.success, "pressing one side repeatedly must fail")

    def test_alternating_stumble_resets_streak(self) -> None:
        q = AlternatingQTE(6, 10.0)
        q.handle_key("left", ""); q.handle_key("right", ""); q.handle_key("right", "")
        self.assertEqual(q.streak, 0)
        self.assertEqual(q.stumbles, 1)

    def test_conditional_sigils_follow_rule_and_fail_on_wrong_arrow(self) -> None:
        rng = random.Random(3)
        q = ConditionalSigilQTE(rng, 5, 12.0, inverted=True)
        while not q.done:
            q.handle_key(q.expected(), "")
        self.assertTrue(q.success)
        q = ConditionalSigilQTE(random.Random(3), 5, 12.0, inverted=True)
        wrong = next(a for a in ("left", "right", "up", "down") if a != q.expected())
        q.handle_key(wrong, "")
        self.assertTrue(q.done and not q.success)

    def test_counter_rhythm_wants_the_offbeat(self) -> None:
        q = CounterRhythmQTE(3, 0.5, 8.0)
        t = 0.0
        while t < q.lead + 0.5 * q.period - 1e-9:   # advance to the first off-beat centre
            q.update(0.01); t += 0.01
        for _ in range(3):
            target = q.lead + (int((q.elapsed - q.lead) // q.period) + 0.5) * q.period
            while q.elapsed < target - 0.005:
                q.update(0.005)
            q.handle_key("space", " ")
            for _ in range(int(q.period / 0.005)):   # wait for the next off-beat
                q.update(0.005)
                if q.done: break
        self.assertTrue(q.done and q.success, (q.hits, q.misses))

    def test_counter_rhythm_on_beat_spam_fails(self) -> None:
        q = CounterRhythmQTE(4, 0.5, 8.0)
        for _ in range(10):
            q.handle_key("space", " ")      # during lead-in = all misses
        self.assertTrue(q.done and not q.success)

    def test_stages_require_all_stages(self) -> None:
        a, b = AlternatingQTE(2, 5.0), AlternatingQTE(2, 5.0)
        seal = SealStagesQTE([a, b], "Test Seal")
        for k in ("left", "right"):
            seal.handle_key(k, "")
        self.assertFalse(seal.done)
        self.assertEqual(seal.stage_index, 1)
        for k in ("left", "right"):
            seal.handle_key(k, "")
        self.assertTrue(seal.done and seal.success)
        a, b = AlternatingQTE(2, 5.0), AlternatingQTE(2, 5.0)
        seal = SealStagesQTE([a, b], "Test Seal")
        for _ in range(4):
            seal.handle_key("left", "")
        self.assertTrue(seal.done and not seal.success)


class LibraryTests(unittest.TestCase):
    def test_every_definition_builds_and_is_solvable_at_every_tier(self) -> None:
        for tid in trial_ids():
            for tier in range(1, 11):
                for seed in range(5):
                    q = make_trial(tid, random.Random(seed), tier)
                    self.assertTrue(q.is_solvable(), f"{tid} tier {tier} seed {seed} unsolvable")
                    self.assertTrue(q.panel_lines, f"{tid} has no panel lines")
                    self.assertGreater(q.limit, 0)

    def test_library_has_variety(self) -> None:
        self.assertGreaterEqual(len(TRIAL_LIBRARY), 9)
        self.assertGreaterEqual(len({d.families for d in TRIAL_LIBRARY}), 9)

    def test_anti_repetition_and_seed_determinism(self) -> None:
        rng = random.Random(11)
        recent: list[str] = []
        for _ in range(200):
            _, tid = build_trial(rng, 6, (), recent, 0)
            self.assertNotIn(tid, recent[-2:])
            recent.append(tid)
        a = [build_trial(random.Random(5), 4, ("IRON_GAG",), (), 1)[1] for _ in range(3)]
        self.assertEqual(len(set(a)), 1)

    def test_tightness_raises_effective_tier(self) -> None:
        tiers_loose = {build_trial(random.Random(s), 1, (), (), 0)[1] for s in range(80)}
        tiers_tight = {build_trial(random.Random(s), 1, (), (), 5)[1] for s in range(80)}
        self.assertNotIn("judgment_seal", tiers_loose)
        self.assertIn("judgment_seal", tiers_tight)

    def test_affinity_favours_matching_restraint(self) -> None:
        picks = [build_trial(random.Random(s), 1, ("MANACLES",), (), 0)[1] for s in range(300)]
        self.assertGreater(picks.count("forbidden_word"), picks.count("rune_swap"))


class BreakEscalationTests(unittest.TestCase):
    class _Combat:
        def __init__(self) -> None:
            self.rng = random.Random(1)
            self.logs: list[str] = []

        def log(self, text, *a, **k): self.logs.append(text)
        def alert(self, text, *a, **k): self.logs.append(text)
        def hurt_self(self, hero, amount): hero.hp -= amount

    def angel(self) -> FallenAngel:
        a = FallenAngel("Seraph")
        a.restraints = {Restraint.MANACLES, Restraint.IRON_GAG}
        a.hp = a.max_hp
        a.stamina = a.max_stamina
        return a

    def test_base_values_preserved(self) -> None:
        self.assertEqual(FallenAngel.BREAK_BACKLASH_HP, 14)
        self.assertEqual(FallenAngel.BREAK_BACKLASH_LUC, 20.0)
        self.assertEqual(self.angel().break_backlash(), (14, 20.0))

    def test_failures_escalate_and_trigger_correction_lock(self) -> None:
        a, c = self.angel(), self._Combat()
        seen = []
        for _ in range(3):
            hp0, luc0 = a.hp, a.lucidity
            expected = a.break_backlash()
            a.use("break", None, False, c)
            seen.append(expected)
            self.assertEqual(hp0 - a.hp, expected[0])
            self.assertAlmostEqual(luc0 - a.lucidity, expected[1])
            a.stamina = a.max_stamina
            a.lucidity = 100.0
            a.hp = a.max_hp
        self.assertEqual(seen, [(14, 20.0), (17, 25.0), (20, 30.0)])
        self.assertFalse(a.ready("break"), "Choir of Correction should lock Break after repeated failures")
        self.assertTrue(any("Correction" in line for line in c.logs))

    def test_escalation_is_capped(self) -> None:
        a = self.angel()
        a.failed_breaks = 99
        self.assertEqual(a.break_backlash(), (14 + 9, 20.0 + 15.0))

    def test_lock_expires_and_menu_reflects_it(self) -> None:
        a, c = self.angel(), self._Combat()
        a.use("break", None, False, c); a.stamina = a.max_stamina; a.hp = a.max_hp
        a.use("break", None, False, c); a.stamina = a.max_stamina; a.hp = a.max_hp
        entry = next(x for x in a.abilities() if x.key == "break")
        self.assertFalse(entry.enabled if hasattr(entry, "enabled") else entry.usable)
        a.tick_cooldowns(); a.tick_cooldowns()
        self.assertTrue(a.ready("break"), "path back: lock must expire")

    def test_cannot_kill_self_on_failure(self) -> None:
        a, c = self.angel(), self._Combat()
        a.hp = 5
        a.use("break", None, False, c)
        self.assertGreaterEqual(a.hp, 1)

    def test_success_resets_counter_but_restraints_remain_meaningful(self) -> None:
        a, c = self.angel(), self._Combat()
        a.use("break", None, False, c)
        self.assertEqual(a.failed_breaks, 1)
        a.stamina = a.max_stamina
        a._profile_break_bonus = 1.0     # force the dice; ok=True path
        before = len(a.restraints)
        a.use("break", None, True, c)
        self.assertEqual(len(a.restraints), before - 1, "one success removes exactly one restraint")
        self.assertEqual(a.failed_breaks, 0)

    def test_state_resets_after_battle_and_rest(self) -> None:
        a = self.angel()
        a.failed_breaks = 3
        a.after_battle()
        self.assertEqual(a.failed_breaks, 0)
        a.failed_breaks = 2
        a.rest()
        self.assertEqual(a.failed_breaks, 0)


class CombatIntegrationTests(unittest.TestCase):
    """Drive the real CombatSystem: menu -> Break Restraint -> trial -> resolution."""

    def _open_break_trial(self, seed: int):
        from core.config import PlayerClass
        from core.game_state import GameState, PlayerConfig
        from systems.combat_system import CombatSystem, Phase
        state = GameState(seed=seed)
        state.new_run([PlayerConfig("Seraph", PlayerClass.ANGEL)], "Normal", endless=False)
        state.stage = 4
        state.spawn_encounter()
        combat = CombatSystem(state)
        angel = state.players[0]
        angel.restraints = {Restraint.IRON_GAG}
        for _ in range(400):
            if combat.phase is Phase.MENU:
                break
            combat.update(0.05)
        self.assertIs(combat.phase, Phase.MENU)
        combat.menu_idx = next(i for i, e in enumerate(combat.menu) if e.ability and e.ability.key == "break")
        combat.handle_key("return")
        self.assertIs(combat.phase, Phase.QTE, "Break Restraint must open a QTE")
        return combat, angel, Phase

    def test_break_uses_trial_library_not_plain_mash(self) -> None:
        from systems.qte_system import MashQTE
        for seed in range(1, 15):
            combat, angel, _ = self._open_break_trial(seed)
            self.assertNotIsInstance(combat.qte, MashQTE)
            self.assertTrue(hasattr(combat.qte, "trial_id"))
            self.assertEqual(angel.recent_trials[-1], combat.qte.trial_id)

    def test_spamming_space_fails_the_break_trial_and_costs_the_angel(self) -> None:
        failures = 0
        for seed in range(1, 15):
            combat, angel, Phase = self._open_break_trial(seed)
            hp0 = angel.hp
            for _ in range(2000):
                if combat.phase is not Phase.QTE:
                    break
                combat.handle_key("space", " ")
                combat.update(0.005)
            self.assertIsNot(combat.phase, Phase.QTE, "QTE must always resolve (no softlock)")
            if angel.hp < hp0:
                failures += 1
        self.assertGreaterEqual(failures, 12, "button hammering should almost never clear a restraint trial")

    def test_paced_input_can_clear_a_paced_trial_in_combat(self) -> None:
        cleared = 0
        for seed in range(1, 40):
            combat, angel, Phase = self._open_break_trial(seed)
            if getattr(combat.qte, "trial_id", "") != "paced_pull":
                continue
            qte = combat.qte
            t, nxt = 0.0, 0.0
            while combat.phase is Phase.QTE and t < 30:
                if t >= nxt:
                    combat.handle_key("space", " ")
                    nxt += 0.24
                combat.update(0.005)
                t += 0.005
            self.assertTrue(qte.done and qte.success, f"steady pacing should clear paced_pull (seed {seed})")
            cleared += 1
        self.assertGreater(cleared, 0, "need at least one paced_pull sample")


if __name__ == "__main__":
    unittest.main()
