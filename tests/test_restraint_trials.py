"""R2 restraint-trial library: solvability, anti-spam behaviour, determinism, picker rules.

Pure logic; run with ``python -m unittest tests.test_restraint_trials``.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import headless_bootstrap  # noqa: F401,E402  (stubs pygame so imports work headless)

from systems.restraint_trials import (  # noqa: E402
    MAX_TIER, TRIAL_BY_ID, TRIAL_DEFS, SpamGuard, ThrashTrial, TrialLibrary, run_script, trial_tier, validate_trial,
)


def _tiers(d):
    return range(d.tiers[0], d.tiers[1] + 1)


class SolvabilityTests(unittest.TestCase):
    def test_every_definition_is_solvable_at_every_allowed_tier(self):
        for d in TRIAL_DEFS:
            for tier in _tiers(d):
                for seed in range(12):
                    with self.subTest(trial=d.id, tier=tier, seed=seed):
                        t = d.build(random.Random(seed), tier)
                        validate_trial(t)
                        self.assertTrue(run_script(t, t.solution_script()), "reference solution must succeed")

    def test_library_ids_unique_and_tiers_valid(self):
        ids = [d.id for d in TRIAL_DEFS]
        self.assertEqual(len(ids), len(set(ids)))
        for d in TRIAL_DEFS:
            self.assertTrue(1 <= d.tiers[0] <= d.tiers[1] <= MAX_TIER, d.id)

    def test_library_is_big_enough_to_resist_repetition(self):
        self.assertGreaterEqual(len(TRIAL_DEFS), 12)
        self.assertGreaterEqual(len({d.family for d in TRIAL_DEFS}), 5)


class AntiSpamTests(unittest.TestCase):
    def _spam(self, trial, key, rate_hz, seconds):
        script, t = [], 0.0
        while t < seconds:
            script.append((t, key, ""))
            t += 1.0 / rate_hz
        return run_script(trial, script, tail=0.2)

    def test_mashing_or_holding_never_clears_any_trial(self):
        non_boss = [d for d in TRIAL_DEFS if not d.boss]
        for d in non_boss:
            for tier in _tiers(d):
                for key in ("space", "e", "left"):
                    for hz in (8, 25, 60):
                        with self.subTest(trial=d.id, tier=tier, key=key, hz=hz):
                            t = d.build(random.Random(3), tier)
                            self.assertFalse(self._spam(t, key, hz, t.limit + 1), "blind spam must not solve a trial")

    def test_boss_trials_also_resist_spam(self):
        for d in (x for x in TRIAL_DEFS if x.boss):
            for key in ("space", "e", "up"):
                with self.subTest(trial=d.id, key=key):
                    t = d.build(random.Random(5), 2)
                    self.assertFalse(self._spam(t, key, 30, t.limit + 1))

    def test_spam_guard_rejects_too_fast_presses_and_accrues_fatigue(self):
        g = SpamGuard()
        self.assertGreater(g.press(0.0), 0.0)
        self.assertEqual(g.press(0.01), 0.0, "press inside the minimum interval is worth nothing")
        # Sustained fast pressing is worth less than paced pressing over the same time.
        fast, paced = SpamGuard(), SpamGuard()
        fast_total = sum(fast.press(i * 0.115) for i in range(80))
        paced_total = sum(paced.press(i * 0.34) for i in range(27))
        self.assertLess(fast_total / 80, paced_total / 27, "per-press value must fall under sustained fast input")

    def test_thrash_trial_still_completes_with_human_pacing(self):
        t = ThrashTrial(6.0, 1)
        self.assertTrue(run_script(t, t.solution_script()))


class DeterminismAndPickerTests(unittest.TestCase):
    def test_same_seed_same_trial(self):
        a = TrialLibrary().pick("GOTHIC_CHAINS", 2, random.Random(11))
        b = TrialLibrary().pick("GOTHIC_CHAINS", 2, random.Random(11))
        self.assertEqual(a[0].id, b[0].id)
        self.assertEqual(a[1].solution_script(), b[1].solution_script())

    def test_no_immediate_repeat_and_variety(self):
        lib, rng, seen = TrialLibrary(), random.Random(2), []
        for _ in range(40):
            d, _t = lib.pick("GOTHIC_CHAINS", 2, rng)
            seen.append(d.id)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])), "same trial twice in a row")
        self.assertGreaterEqual(len(set(seen)), 5, "picker should rotate through many trials")

    def test_boss_trials_only_for_matching_boss(self):
        lib, rng = TrialLibrary(), random.Random(1)
        for _ in range(60):
            d, _ = lib.pick(None, 2, rng)
            self.assertIsNone(d.boss, "boss trial leaked into a non-boss fight")
        got = {lib.pick(None, 2, random.Random(s), boss="Warden Maelis")[0].id for s in range(30)}
        self.assertIn("boss_maelis", got)

    def test_tier_scaling_is_monotonic_and_clamped(self):
        prev = 0
        for stage in range(1, 20):
            t = trial_tier(stage)
            self.assertGreaterEqual(t, prev)
            self.assertTrue(1 <= t <= MAX_TIER)
            prev = t
        self.assertEqual(trial_tier(1, 0, 0), 1)
        self.assertEqual(trial_tier(40, 9, 9), MAX_TIER)

    def test_required_trial_ids_present(self):
        for tid in ("boss_maelis", "boss_orrick", "boss_vael", "seal_judgment", "thrash_anchor"):
            self.assertIn(tid, TRIAL_BY_ID)


class RenderDataTests(unittest.TestCase):
    def test_render_data_is_plain_and_has_cause_fields(self):
        for d in TRIAL_DEFS:
            t = d.build(random.Random(4), d.tiers[0])
            data = t.render_data()
            self.assertIsInstance(data, dict)
            for k in ("title", "rule"):
                self.assertIn(k, data, f"{d.id} render_data lacks {k}")


if __name__ == "__main__":
    unittest.main()
