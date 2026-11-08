"""Seeded, headless integration smoke test: combat -> reward -> save/load -> local result.

Run: python tools/smoke_test.py
This uses the real simulation and persistence code, but deliberately does not claim to test pixels/audio.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.headless_bootstrap import install_import_stub_if_missing  # noqa: E402
STUBBED_PYGAME = install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402
from systems.leaderboard import LocalLeaderboard  # noqa: E402
from systems.save_system import SaveManager  # noqa: E402


def main() -> int:
    state = GameState(seed=20261024)
    state.new_run([PlayerConfig("Mara", PlayerClass.WARRIOR)], "Easy", endless=False)
    state.spawn_encounter()
    combat = CombatSystem(state)
    starting_enemy_hp = sum(e.hp for e in state.enemies)
    iterations = 0

    # Drive the same input/state machine the UI uses. Time advances in deterministic 1-second steps.
    while combat.phase not in (Phase.VICTORY, Phase.DEFEAT) and iterations < 300:
        iterations += 1
        if combat.phase is Phase.MENU:
            enabled = next((i for i, entry in enumerate(combat.menu) if entry.enabled), None)
            if enabled is None:
                raise AssertionError("Combat menu offered no enabled action")
            combat.menu_idx = enabled
            combat.handle_key("return")
        elif combat.phase is Phase.TARGET:
            combat.handle_key("return")
        elif combat.phase in (Phase.RESOLVE, Phase.ENEMY):
            combat.update(1.0)
        elif combat.phase is Phase.QTE:
            # Fail closed if the selected action unexpectedly introduces a QTE; no fake success is injected.
            combat.update(31.0)
        else:
            raise AssertionError(f"Unhandled combat phase: {combat.phase}")

    if combat.phase is not Phase.VICTORY:
        raise AssertionError(f"Seeded first encounter failed to reach victory (phase={combat.phase}, steps={iterations})")
    if sum(e.hp for e in state.enemies) >= starting_enemy_hp:
        raise AssertionError("Combat loop never damaged an enemy")
    reward_lines = state.claim_victory()
    if not reward_lines or state.gold <= 120:
        raise AssertionError("Victory did not award any rewards")

    with tempfile.TemporaryDirectory() as directory:
        saves = SaveManager(directory, slot_names=("slot1", "slot2", "slot3"))
        saves.save(1, state)
        loaded = saves.load(1)
        if loaded.run_id != state.run_id or loaded.stage != state.stage:
            raise AssertionError("Save/load failed to preserve run identity or stage")
        board = LocalLeaderboard(Path(directory) / "leaderboard.json")
        record, inserted = board.add_result(state, True, state.run_id)
        duplicate, inserted_twice = board.add_result(state, True, state.run_id)
        if not inserted or inserted_twice or record != duplicate or len(board.records()) != 1:
            raise AssertionError("Local leaderboard result was not idempotent")

    print(f"Deterministic smoke test passed: seed={state.seed}, stage={state.stage}, turns={iterations}, score={record['score']}.")
    print(f"Party HP after encounter: {state.players[0].hp}/{state.players[0].max_hp}; rewards: {' | '.join(reward_lines)}")
    print(f"Save/load and idempotent local record passed ({'headless Pygame stub' if STUBBED_PYGAME else 'Pygame installed'}).")
    if STUBBED_PYGAME:
        print("NOTE: this does not launch or visually verify the Pygame window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
