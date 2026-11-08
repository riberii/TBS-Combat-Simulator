# Save Format and Recovery

## Storage location

`SaveManager` writes outside the source tree under the user's application-data directory:

- Windows: `%LOCALAPPDATA%\AbyssalChoir\saves` (with documented fallbacks if unavailable)
- macOS: `~/Library/Application Support/AbyssalChoir/saves`
- Linux: `$XDG_DATA_HOME/AbyssalChoir/saves`, otherwise `~/.local/share/AbyssalChoir/saves`

The directory also stores settings and local leaderboard JSON. Tests inject a temporary directory so they never touch a real user profile.

## Two schema layers

- Save envelope: `format = "game-state-save"`, envelope `schema = 1`, slot metadata/checksums in the save system.
- Game state payload: `version = 1`; it stores the run id/seed, mode, difficulty, stage, economy, modifiers, RNG state, player class IDs and serializable player state, inventory and Chronicle log. Enemies are respawned when loading an in-progress encounter at the appropriate stage rather than storing a half-resolved combat object.
- Class identity is the stable enum name (for example `VAMPIRE`, not the display label); class display names can be edited without breaking saves.

The eight current player class implementations are built fresh, then saved attributes are validated/restored onto them. Newly introduced class fields have constructor defaults, so older saves continue to load; unknown fields are ignored for forward compatibility while malformed types/required fields fail with a specific error. Do not use pickle.

## Atomic writes and backups

Saves use a temporary file and atomic replacement; a prior valid save is rotated to `.bak`. The bad primary is preserved when a read fails. `Continue` selects the latest valid slot; explicit load can report corrupt/unsupported slots. Save version values should be incremented only with a real migration function and regression tests.

## Safe backup/reset

Close the game and copy the entire saves directory before investigating issues. To reset, rename the folder instead of deleting it; the game creates a fresh directory on next launch. Restore by renaming the backed-up folder to `saves`. Keep both the malformed primary and `.bak` if reporting a bug.
