# Chains of the Abyssal Choir — QA patch (shop crash, history and class regressions)

This patch preserves the existing project and public save/combat APIs. It focuses on confirmed integration faults and includes regression tests against the supplied game logic.

## Save/load integration

- `core/game_state.py`: adds an explicit enum type hint for Fallen Angel restraint state. A freshly created Angel has an empty restraint set, so the serializer previously had no live enum value from which to infer `Restraint`; the `SaveManager` write-then-load verification then rejected the save. Empty and populated restraint sets, optional restraint targets and lucidity now round-trip.
- `main.py`: reserves SaveManager slot 1 for autosave and slots 2–4 for the three visible manual slots, with real `SaveManager.save`, `load`, and `continue_latest` calls. Continue is enabled by any valid save and selects the newest loadable autosave/manual slot. Load/save menus show empty/corrupt slots correctly, and save errors are caught and reported instead of crashing.
- Corrupt latest saves are skipped for Continue, which falls back to the newest valid save. Loading a corrupt individual slot reports the error and stays in the slot menu.

## Combat / presentation / audio

- `main.py`: displays action descriptions and costs, target-phase action details, readable QTE instructions and live typing/timing/mash/memory progress. It routes combat/QTE/menu events to the existing procedural SFX system, avoids duplicate generic popups for structured combat events, and refreshes visual anchors using actual entity UIDs.
- `systems/combat_system.py`: exposes the pending target action read-only for the HUD, emits structured Fallen Angel lucidity events and caps damage from a single enemy hit using `core.config.max_single_hit`.
- `systems/qte_system.py`: typing QTEs expose progress/remaining/slip state, state their exact target word, reject multi-character and non-ASCII shortcuts, and support Backspace.
- `systems/audio_system.py`: adds generated sound definitions/aliases used for combat, restraint, QTE, UI, victory and defeat cues.
- `ui/vfx.py` and `ui/renderer.py`: route readable restraint, lucidity, reward and combat popups and maintain the visual restraint interaction.
- `requirements.txt`: declares NumPy for procedural sound generation.

## Shop crash and always-visible journal

- `main.py`: fixed the confirmed `TypeError: 'int' object is not iterable`. `Shop.rows` is an integer count; the painter now builds rows from the actual `Shop.stock` tuples and adds the Proceed row explicitly. Selected items show full descriptions, price and remaining stock. The pack count now sums `Inventory.counts` instead of calling `len()` on an object with no `__len__`.
- `main.py`: added a persistent run sidebar with recent actions and every current Fallen Angel restraint label/description. Press `H` to open the full journal; `TAB` switches between past actions/history and the restraint list, with `PAGE UP` / `PAGE DOWN` browsing the selected list. The journal freezes combat timers and QTE deadlines while open. Successful purchases, stage banners, rest, visit/exit merchant, victory rewards and load messages are recorded.
- `core/game_state.py`: saves up to 300 log entries and restores them with colour data. The field is optional, so existing v1 save files without `log` remain compatible. Invalid log data is rejected as corrupt rather than crashing unpredictably later.

## Endless progression

- `core/game_state.py` passes an endless boss ordinal into encounter creation so bosses continue rotating past the initial roster instead of repeating the same subset.
- `entities/enemy.py` accepts that optional ordinal while preserving the original `spawn_wave(stage, players, difficulty, rng)` call shape. Tests cover four distinct boss identities and varying endless waves/modifiers/reward multipliers.

## Class identity coverage

- Added regression checks for each class's distinct action keys and that each class's primary attack has a real combat effect.
- Tested Fallen Angel's escalating restraint cascade, lucidity decline under accumulating restraints, and the HP/lucidity/tightness penalty when a break attempt fails. This validates existing mechanics rather than adding compensating power to the challenge class.

## Files changed relative to the supplied ZIP

- `README.md`
- `PATCH_NOTES.md` (new)
- `core/game_state.py`
- `entities/enemy.py`
- `main.py`
- `requirements.txt`
- `systems/audio_system.py`
- `systems/combat_system.py`
- `systems/qte_system.py`
- `ui/renderer.py`
- `ui/vfx.py`
- `tests/test_save_and_progression.py` (new)
- `tests/test_ux_audio_fixes.py` (new)

`systems/save_system.py` and `systems/inventory_system.py` were inspected and exercised as supplied; they did not require code changes for the confirmed failures covered here.

## Verification performed

From the project directory:

- `python -m compileall -q .` — passed.
- `python -m unittest discover -s tests -v` — **30 tests passed, 0 failed**.

The test suite exercises the real `GameState`, `SaveManager`, `CombatSystem`, `Enemy`, `Shop`, player classes, QTE logic and VFX event routing. Four file-backed slots are saved and loaded; tests cover empty and populated restraint serialization, five classes and party sizes 1–3, per-member stats/resources, inventory, gold, difficulty, endless stage/modifiers, Continue selection, individual-slot menu save/load, corrupt-slot handling, shop row/painter contract, a real UI-routed purchase and autosave-on-Proceed, saved run history, journal navigation, each class's distinct ability kit and core attack, Fallen Angel's restraint/escape penalties, enemy-turn progression, per-hit damage cap, VFX anchors, popup stacking/expiry and QTE input.

## Runtime verification limit

Pygame-CE is not installed in this execution environment and network access is unavailable. Headless tests use a minimal import-only Pygame stub where needed to load UI/application modules; the game logic under test is the real supplied source, not a mocked SaveManager, GameState, Shop or combat system. The actual shop painter's control flow was exercised with the real Shop object and drawing primitives captured. The full graphical window, final visual layout, Windows input handling and physical audio playback were **not** run here. Therefore this patch does not claim the entire game is crash-free in every interactive path; run the included tests and perform the Windows smoke test below.
