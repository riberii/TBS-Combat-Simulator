"""Seeded combat robustness checks (no rendering, no real time).

Random inputs are driven through the real CombatSystem for every class. The same seeds always give the
same run, so a failure is reproducible. These catch crashes, impossible values, endless fights, and
input that changes state while an action is animating.
"""
from __future__ import annotations

import logging
import random
import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402

KEYS = ["up", "down", "left", "right", "return", "space", "escape", "a", "d", "w", "s",
        "1", "2", "3", "4", "5", "x", "tab"]
MAX_STEPS = 3000
_FINISHED = (Phase.VICTORY, Phase.DEFEAT)


def _snapshot(state: GameState, combat: CombatSystem):
    return (combat.phase,
            tuple((round(p.hp, 3), round(p.mana, 3), round(p.stamina, 3)) for p in state.players),
            tuple(round(e.hp, 3) for e in state.enemies),
            state.gold)


def _bounds_error(state: GameState):
    for p in state.players:
        for attr in ("hp", "mana", "stamina"):
            value, cap = getattr(p, attr, None), getattr(p, "max_" + attr, None)
            if value is not None and (value < 0 or (cap is not None and value > cap + 1e-6)):
                return f"{p.name} {attr}={value} (max {cap})"
    for e in state.enemies:
        if e.hp < 0 or e.hp > e.max_hp + 1e-6:
            return f"enemy {e.name} hp={e.hp}/{e.max_hp}"
    return None


def _new_fight(seed: int):
    rng = random.Random(seed)
    classes = list(PlayerClass)
    party = rng.sample(classes, rng.choice((1, 2, 3)))
    state = GameState(seed=seed)
    state.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(party)],
                  rng.choice(("Easy", "Normal", "Hard")), endless=False)
    state.stage = rng.choice((1, 4, 12))
    state.spawn_encounter()
    return rng, party, state, CombatSystem(state)


class CombatRobustnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)  # the QTE-stall failsafe logs on purpose

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def test_random_fights_finish_with_values_in_range(self) -> None:
        for seed in range(1, 25):
            rng, party, state, combat = _new_fight(seed)
            with self.subTest(seed=seed, party=[c.name for c in party]):
                steps = 0
                while combat.phase not in _FINISHED and steps < MAX_STEPS:
                    steps += 1
                    if combat.phase in (Phase.RESOLVE, Phase.ENEMY):
                        combat.update(rng.choice((0.05, 0.3, 1.0)))
                    elif combat.phase is Phase.QTE:
                        combat.update(31.0) if rng.random() < 0.5 else combat.handle_key(rng.choice(KEYS))
                    else:
                        combat.handle_key(rng.choice(KEYS))
                    self.assertIsNone(_bounds_error(state), f"step {steps}, phase {combat.phase.name}")
                self.assertIn(combat.phase, _FINISHED, "fight never ended")

    def test_input_spam_during_resolution_and_after_the_fight_changes_nothing(self) -> None:
        for seed in range(100, 116):
            rng, party, state, combat = _new_fight(seed)
            with self.subTest(seed=seed, party=[c.name for c in party]):
                steps = 0
                while combat.phase not in _FINISHED and steps < MAX_STEPS:
                    steps += 1
                    if combat.phase in (Phase.RESOLVE, Phase.ENEMY):
                        before = _snapshot(state, combat)
                        for key in KEYS:
                            combat.handle_key(key)
                        self.assertEqual(before, _snapshot(state, combat),
                                         f"keys altered state during {combat.phase.name}")
                        combat.update(rng.choice((0.1, 0.5, 1.0)))
                    elif combat.phase is Phase.QTE:
                        combat.update(31.0)
                    else:
                        combat.handle_key(rng.choice(KEYS))
                self.assertIn(combat.phase, _FINISHED)
                final = _snapshot(state, combat)
                for key in KEYS:
                    combat.handle_key(key)
                combat.update(1.0)
                self.assertEqual(final, _snapshot(state, combat), "state changed after the fight ended")


if __name__ == "__main__":
    unittest.main()
