"""Static content and cross-reference validation for the playable core.

Run from the project directory with: python tools/validate_content.py
If pygame-ce is not installed, an import-only stub enables gameplay/data validation;
this is not a graphical smoke test.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.headless_bootstrap import install_import_stub_if_missing  # noqa: E402
STUBBED_PYGAME = install_import_stub_if_missing()

from core.config import CLASS_BLURBS, CLASS_COLORS, FINAL_STAGE, PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from core import story  # noqa: E402
from entities.enemy import ARCHETYPES, BOSS_ROSTER, Enemy  # noqa: E402
from entities.player import PLAYER_CLASSES, _PAINTERS as ENTITY_PAINTERS, create_player  # noqa: E402
from entities.base_entity import Target  # noqa: E402
from main import CharacterKind, TITLE_PREVIEW_SPECS, _kind_for  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    check(set(PLAYER_CLASSES) == set(PlayerClass), "Every playable class must have exactly one player implementation")
    check(set(CLASS_COLORS) == set(PlayerClass), "Every playable class must have an accent color")
    check(set(CLASS_BLURBS) == set(PlayerClass), "Every playable class must have a class description")

    sprite_kinds = [_kind_for(create_player(f"Hero {i}", pclass), i) for i, pclass in enumerate(PlayerClass)]
    check(len(sprite_kinds) == len(set(sprite_kinds)), "Playable classes must map to unique battle silhouettes")
    check(all(isinstance(kind, CharacterKind) for kind in sprite_kinds), "Class sprite mapping returned an unknown type")
    check(set(ENTITY_PAINTERS) == set(PlayerClass), "Every playable class must have a dedicated entity portrait painter")
    preview_kinds = [kind for kind, _ in TITLE_PREVIEW_SPECS]
    check(len(preview_kinds) == len(set(preview_kinds)), "Title preview contains duplicate class silhouettes")
    check(set(preview_kinds) == set(CharacterKind), "Title preview must show every playable class model")

    ability_count = 0
    for pclass in PlayerClass:
        hero = create_player("Validation Hero", pclass)
        abilities = hero.abilities()
        keys = [a.key for a in abilities]
        check(abilities, f"{pclass.value} has no abilities")
        check(len(keys) == len(set(keys)), f"{pclass.value} has duplicate ability IDs")
        for ability in abilities:
            check(bool(ability.key.strip()), f"{pclass.value} has an empty ability ID")
            check(bool(ability.label.strip()), f"{pclass.value}/{ability.key} has an empty display label")
            check(isinstance(ability.target, Target), f"{pclass.value}/{ability.key} has an invalid target type")
            check(bool(ability.hint.strip()), f"{pclass.value}/{ability.key} has no player-facing effect description")
            check(bool(str(ability.cost).strip()), f"{pclass.value}/{ability.key} has no visible cost")
        ability_count += len(abilities)

    check(ARCHETYPES, "Enemy archetype registry is empty")
    check(len(ARCHETYPES) == len(set(ARCHETYPES)), "Duplicate enemy archetype keys")
    for key, archetype in ARCHETYPES.items():
        check(key == archetype.key, f"Enemy archetype registry mismatch for {key}")
        check(bool(archetype.names), f"Enemy archetype {key} has no names")
        check(archetype.hp > 0 and archetype.atk >= 0 and archetype.df >= 0, f"Enemy archetype {key} has invalid stats")
    check(BOSS_ROSTER, "Boss roster is empty")
    check(all(boss.sprite in ARCHETYPES for boss in BOSS_ROSTER), "A boss references an unknown sprite/archetype")
    check(set(story.STAGE_INTROS) == set(range(1, FINAL_STAGE + 1)), "Story intros must cover each authored hall")
    check(all(stage in story.STAGE_INTROS for stage in story.BOSS_INTROS), "A boss intro references a missing hall")

    # Deterministic plan check: all story encounters spawn and the three authored gates are bosses.
    state = GameState(seed=20261024)
    state.new_run([PlayerConfig("Validator", PlayerClass.WARRIOR)], "Normal", endless=False)
    stages = []
    for expected_stage in range(1, FINAL_STAGE + 1):
        state.stage = expected_stage - 1
        state.spawn_encounter()
        check(state.stage == expected_stage, f"Story stage increment mismatch at {expected_stage}")
        check(state.enemies and all(e.alive for e in state.enemies), f"Stage {expected_stage} spawned no living enemies")
        if state.is_boss_stage(expected_stage):
            check(any(e.boss for e in state.enemies), f"Boss milestone {expected_stage} did not spawn a boss")
        stages.append((expected_stage, len(state.enemies), ", ".join(e.name for e in state.enemies)))

    print(f"Content validation passed ({'import-only Pygame stub' if STUBBED_PYGAME else 'Pygame installed'}).")
    print(f"Playable classes: {len(PlayerClass)}; unique sprites: {len(set(sprite_kinds))}; abilities validated: {ability_count}.")
    print(f"Enemy archetypes: {len(ARCHETYPES)}; boss identities: {len(BOSS_ROSTER)}; authored halls: {len(story.STAGE_INTROS)}.")
    print("Story encounter table:")
    for stage, count, names in stages:
        print(f"  {stage:02d}: {count} enemy/enemies — {names}")
    if STUBBED_PYGAME:
        print("NOTE: Pygame was absent; validation checked content/gameplay imports only, not rendering.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
