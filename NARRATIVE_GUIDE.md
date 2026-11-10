# Narrative Guide

## Tone and current arc

The Dawn Bell of Emberfall has gone silent; a choir now sings from the Sunken Cathedral of Vael. The party descends through twelve halls to recover the Bell's stolen heart. The arc escalates through three jailer encounters and ends at Vael's throne; the ending differs if the Fallen Angel is in the party. Story text is deliberately concise and event-led, with stage and boss introductions placed in the run Chronicle.

## Source of truth

- `core/story.py` owns the prologue, twelve stage intros, boss intros, Angel-specific boss line, Angel lore and victory/defeat epilogues.
- `GameState.spawn_encounter()` selects the relevant stage and boss lines and returns the intro for the caller to log/show.
- `GameApp._start_run()` records the Story prologue context in the saved run log; the Chronicle preserves those lines with past actions.
- The result panel chooses the Angel-specific epilogue when the party includes a Fallen Angel; otherwise it uses the general victory ending. Defeat uses its own ending.
- Class skills produce concise combat lines at the moment their effect occurs. The UI does not report success when an action's result failed.

## Voices and extension convention

Warrior/Rogue lines should focus on openings, pressure and tempo; Tank on protecting the line; Witch on patterns and occult control; Fallen Angel on responsibility and restraint rather than suffering alone; Kitsune on misdirection and the cost of bargains; Vampire on measured thirst and leverage; Dragonkin on heat, restraint and the moment pressure becomes danger. Keep new lines short, keyed to actual combat outcomes, and avoid repeating a unique line every turn. Future branching dialogue should persist a stable story flag and change a result/reward/encounter—not merely show two choices with the same result.

## Limits

The current campaign is linear and its narrative variation is primarily stage/boss intros, combat logs, and the Angel-specific boss/ending lines. A full relationship system, choice branches, animated dialogue cutscenes, narrator priority scheduler, voice acting and codex discovery UI are not shipped in this version.
