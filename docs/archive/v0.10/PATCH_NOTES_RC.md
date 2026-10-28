# Chains of the Abyssal Choir — v0.9 Release Candidate audit

## Changes in this RC pass

- Moved party sprites to x positions 270, 415, and 560 so the persistent left-side action/restraint chronicle no longer sits on top of the first player.
- Reduced the between-fight hub menu to two decisions: Visit the Merchant and Descend to the next fight. Save/load and Main Menu remain in the pause menu; Escape opens that menu from camp.
- Made between-fight recovery automatic after a non-final victory, and autosave happens after recovery. This removes the redundant Rest option from the post-fight decision menu.
- Added three regression tests for sidebar/player overlap, hub-menu contents, and Escape-to-pause navigation.

## Tests executed

Command: `python -m compileall -q .`

Result: passed.

Command: `python -m unittest discover -s tests -v`

Result: 33 tests passed, 0 failed. The tests exercise actual project GameState, SaveManager, Player, Enemy, Shop, CombatSystem, QTE, VFX, and app transition logic; a minimal import-only Pygame stub is used where Pygame-CE is unavailable.

## Not verified / release blockers

- Pygame-CE is unavailable in this test environment. A real Windows graphical launch, sprite overlap at runtime, visual resolution scaling, keyboard interaction in the live event loop, and physical audio playback have not been tested here.
- The automated suite does not replace a full human playthrough from new game through late-game boss progression.
- Do not describe this as a guaranteed crash-free final release until the above platform checks are completed.
