# Chains of the Abyssal Choir — V2.0

A self-contained, offline dark-fantasy turn-based tactical RPG for **one player commanding a party of 1–3 heroes**. It uses Python and pygame-ce, with original procedural character art, an atmospheric cathedral renderer, time-based character motion, procedural sound effects, 12 authored Story halls, and a replayable Endless Rift.

## Runtime and setup

- **Python:** 3.10+ (Python 3.11 or 3.12 recommended)
- **Renderer/input:** pygame-ce 2.5.6+
- **Audio synthesis:** NumPy 1.24+
- **Network:** not required at runtime
- **Platform target:** Windows first; Linux/macOS supported where pygame-ce and SDL are supported

Windows PowerShell (from this folder):

```powershell
py -3 -m pip install -r requirements.txt
py -3 main.py
```

Or double-click `run_game.bat`. It prints startup errors rather than hiding them. On Linux/macOS:

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

The game renders on a 1280×720 logical canvas; resize the window or press **F11** to toggle fullscreen. The title screen keeps all eight class models visible above the menu, and combat party cards show a class-resource gauge alongside HP/Mana/Stamina. Party scale follows the 1–3 hero formation to stay within the chronicle and enemy lanes. Settings persist across launches.

## R2 additions

See `R2_STATUS_AND_TEST_REPORT.md` (what is tested vs only wired), `Assets/Generated/R2/CROP_PROVENANCE.md`, and `requirements-dev.txt` (Pillow, tests only). Break Restraint now uses a varied restraint-trial library: hammering Space is penalised, so pace your pulls (about 4 per second) or follow each trial's on-screen rule. Repeated failures hit harder and can lock Break for two turns. Settings has \"Generated R2 art\" and \"Anime character models\" toggles (heroes are drawn as anime models; turn the second one off for the original procedural models). The Skill Tree now has 6 nodes per class (core path, specialisation, utility, capstone with a tradeoff).

## Controls

- **Menus:** Up/Down or W/S; Enter/Space confirms; Esc goes back; F11 toggles fullscreen; F2 mutes audio. **Credits / About** is available from the title menu.
- **Party setup:** Up/Down selects a row; Left/Right changes party size/class; type a name; Enter advances; Esc goes back.
- **Combat:** number keys 1–9 select visible actions; arrows navigate targets; Enter confirms; Esc cancels a target/QTE when allowed; P pauses; H opens the Chronicle; Tab switches journal panes; Page Up/Page Down scroll.
- **Fallen Angel restraints:** hover a glowing restraint and press E to attempt the targeted struggle on her turn. Restraints persist until broken and impose real combat costs.
- **QTEs:** typing QTEs require exact letters and fail on the first wrong printable key; timing QTEs require Space inside the randomized live zone; the Gag/Break QTE uses the shown mash key; memory QTEs repeat the shown sequence.
- **Merchant:** Up/Down selects stock, Enter buys or proceeds, Esc leaves.

## Play loop and content

1. Main menu → **New Game** → choose **Story Campaign** or **Endless Rift**.
2. Select 1–3 heroes, choose a difficulty, and start the first encounter.
3. Read enemy intent, choose a class action, select targets when requested, and resolve the action through the shared combat system.
4. Victory awards gold and XP; non-final encounters recover the party automatically and autosave. Visit the merchant or descend to the next encounter.
5. Defeat or final Story victory shows a result recap and epilogue; completed results are recorded to the local leaderboard when storage is available.

### The eight playable classes

- **Warrior — Rage:** a frontline damage dealer who builds Rage through aggression, then spends it on execution or cleave pressure.
- **Tank — Bastion:** the party anchor; guard, taunt, and party wards build Bastion, which amplifies Shield Bash.
- **Rogue — Combo:** a fast precision attacker who builds Combo, uses Vanish to prepare a stronger opening, and cashes out with Assassinate/Twin Fang.
- **Witch — Mana:** ranged arcane control, area curses, Barrier, and Soul Drain; Mana and cooldowns limit burst.
- **Fallen Angel — Lucidity and restraints:** high-risk damage with a persistent curse loop; every turn may add restraints, and ignoring them reduces damage and lucidity while tightening the bindings.
- **Kitsune — Spirit:** foxfire and illusions; attacks generate Spirit, which powers decoys, evasion, group misdirection, and a short Ascendance.
- **Vampire — Blood:** a night duelist who generates Blood by dealing/taking damage and spends it on bounded healing, a protective mist, party empowerment, or an execute-style finisher.
- **Dragonkin — Heat:** a durable offensive bruiser who gains Heat through combat; Ember Breath and Wingbeat control groups, while overheating vents the gauge and leaves the Dragonkin exposed.

Each class has a unique class resource, a basic attack through the shared combat menu, and a distinct set of class actions with descriptions/costs. Class selection and the title preview both include all eight models.

## Modes included in this build

- **Story Campaign:** 12 authored halls, three boss milestones, rich narrative stage/boss intros, 6 authored story chapters, and a campaign ending.
- **Endless Rift:** seeded encounter generation, bounded stat curves, modifiers beyond the initial campaign, and a recurring boss roster with escalating bounties.
- **Boss Rush:** a gauntlet pitting the party consecutively against cathedral bosses (Warden Maelis, Choirmaster Orrick, and Vael).
- **Colosseum Arena:** high-stakes survival wave encounters with increased combat rewards.
- **Training Grounds:** practice drills against training sentinels with full resources and generous purse for testing combinations.
- **Daily Challenge:** fixed calendar-date-seeded run with preset party and daily modifiers.

### Additional Features

- **8 Enemy Archetypes:** Beast, Void, Nature, Construct, Cultist, Hunter, Undead, and Cinder—each with custom silhouettes, combat behaviors, and intent profiles.
- **Dynamic Merchant Pricing Matrix:** Regional depth tolls and class affinities (Rogue tools discount, Witch arcane discount, Dragonkin ward surcharges).
- **Companion / Pet System:** 5 companions (Ashen Raven, Spectral Wisp, Grave Hound Pup, Obsidian Scarab, Silver Sprite) offering passive strategic advantages.
- **Cosmetics & Skins:** 4 palette themes (Classic Penitence, Choir Vestments, Gilded Dawn, Blood Moon Rite) for all 8 hero classes.
- **Wardrobe & Companions Screen:** Browse and select your active companion pet and hero attire palette from the title menu before starting a run. Your chosen companion and attire theme persist into combat.
- **Class Tutorials & Codex:** Detailed combat guides and class-specific manuals for all 8 hero classes, accessible from the **Class Academy** title option. Press **[ENTER]** or **[T]** on any lesson to launch an **Interactive Sparring Combat** drill against an automaton.
- **Sanctum of Ascension (Meta-Progression):** Earn **Choir Shards** (`◈`) from completed expeditions, boss kills, and daily tasks. Spend them in the **Skill Tree** title menu to permanently unlock 24 class passives (3 tiers per class) that apply to all future runs. Reallocate points anytime with a 50% refund (**[R]**).
- **Daily Choir Objectives:** Deterministic date-seeded objectives each calendar day granting 15 Choir Shards on completion. Tracked in the title screen Sanctum badge and inside the Skill Tree.
- **Kitsune Character Redesign:** Hand-authored anime fox spirit vector illustration matching the official design reference—featuring cascading amber hair, fox ears, dusty rose off-the-shoulder kimono, crimson obi, white slip, bare thighs, glossy lace-up thigh-high boots, and a grand fluffy tail.

## Credits and provenance

The title menu's **Credits / About** page and [`CREDITS.md`](CREDITS.md) show “Made by Riberii” and the requested project link. The repository is credited as a reference; broader source-code provenance is not asserted. The existing MIT notice and copyright are retained in [`LICENSE.txt`](LICENSE.txt). The game works offline and stores saves, settings and records locally. See [`ASSET_CREDITS.md`](ASSET_CREDITS.md) for the procedural art/audio inventory.

## Progression and rules

- Encounter rewards grant gold and XP. XP requirement per level is `80 × current level`; each level adds 12 max HP, 2 attack, 1 defense, and 5 max Mana when the hero uses Mana.
- Character level is capped at 30. XP beyond the cap is recorded as bounded `mastery_xp`; it does not inflate stats and does not yet unlock mastery rewards.
- Damage is resolved by the combat simulation, not by drawing code. Ordinary strike damage uses `raw = max(0, attack_power × multiplier)`, then defense mitigation `raw × 30 / (30 + defense)`; a critical hit multiplies raw damage by 1.8 before mitigation. Exposed targets take 2× damage. Damage-over-time, shields/barriers, and class hooks are resolved by the combat system.
- Enemy intent is telegraphed. Enemy types use role-specific silhouettes/intent weights; bosses rotate through distinct profiles and escalate under an enrage threshold. Endless enemy stat curves cap at stage 999 and their threat multiplier at 6×; the displayed stage counter can continue without unbounded combat-stat inflation.
- The shop has bounded stock and described effects; the combat inventory and rewards use the same game state.

## Save, settings, and leaderboard storage

All player data is outside the source folder:

- **Windows:** `%LOCALAPPDATA%\AbyssalChoir\saves` (falls back to `%APPDATA%` or the user profile if unavailable)
- **macOS:** `~/Library/Application Support/AbyssalChoir/saves`
- **Linux:** `$XDG_DATA_HOME/AbyssalChoir/saves` or `~/.local/share/AbyssalChoir/saves`

The directory contains autosave/manual slots, rotating `.bak` backups, `settings.json`, and `leaderboard.json`. Save files are JSON, validated, written atomically, and never deserialized with pickle. `Continue` loads the newest valid save. Corrupt saves are preserved and reported.

**Safe backup/reset:** close the game, copy the whole `AbyssalChoir/saves` folder somewhere safe, then rename the original folder to `saves-backup` to start fresh; restore by renaming it back. Do not delete the only copy of a save when diagnosing corruption.

## Test and validation commands

```powershell
py -3 -m compileall -q .
py -3 -m unittest discover -s tests -v
py -3 tools/validate_content.py
py -3 tools/smoke_test.py
```

`validate_content.py` checks class factories, unique sprite kinds, ability IDs/targets, enemy/boss data, and all authored story stages. `smoke_test.py` drives a deterministic real simulation through combat victory, rewards, save/load, and idempotent local leaderboard insertion. These tools can use an import-only Pygame stub when pygame-ce is missing; in that mode they verify logic/content, **not pixels or sound output**.

## Project structure

```text
main.py                         # one authoritative entry point and application state machine
core/config.py                  # class roster, palette, difficulty, bounded stage scaling
core/game_state.py              # run state, encounter generation, rewards, save serialization
core/story.py                   # authored prologue, stage/boss intros, lore, epilogues
entities/base_entity.py         # shared entity/status/ability value types
entities/player.py              # all eight playable class kits and entity portrait painters
entities/enemy.py               # role archetypes, intent rules, boss roster and scaling
systems/combat_system.py        # turn flow, validation, simulation, combat events
systems/qte_system.py           # timing, typing, mash and memory QTE logic
systems/inventory_system.py     # inventory and merchant economy
systems/save_system.py          # JSON saves, atomic writes, backups, validation
systems/settings_system.py      # versioned local settings and atomic writes
systems/leaderboard.py          # local, mode-aware, idempotent result records
systems/audio_system.py         # original procedural SFX and music/no-device fallback
ui/renderer.py                  # procedural scene, eight character silhouettes, enemy sprites
docs/archive/                    # historical RC notes and the unused legacy menu renderer
ui/vfx.py                       # combat feedback, damage/heal events and reduced-motion settings
tools/validate_content.py       # static/content integration validation
tools/smoke_test.py             # deterministic headless combat/persistence smoke test
tests/                          # save, combat, class, QTE, settings and release regressions
```

## Troubleshooting

- If `import pygame` fails, install the dependency using the commands above; the package is **pygame-ce**, imported as `pygame`.
- If no sound device is available, the game should continue silently; check the Master/SFX settings and OS output device.
- If a save cannot load, use Load Game to inspect other slots and preserve the bad JSON plus `.bak` for diagnosis.
- If the window opens off-screen, press Alt+F4, set `fullscreen` to `false` in `settings.json`, or temporarily rename the settings file (keep a backup).
- The repository does not bundle third-party art, fonts, or music; character/enemy/environment visuals and procedural sounds are generated by local code. The system serif font is used unless an optional local TTF is installed at `assets/fonts/main.ttf`.

## Further documentation

- `ENGINE_DECISION.md` — evidence-based engine/runtime decision
- `GAME_DESIGN.md` — implemented mechanics, class loops and formulas
- `ART_AND_ANIMATION_GUIDE.md` — procedural art and presentation contract
- `NARRATIVE_GUIDE.md` — current story structure and extension notes
- `SAVE_FORMAT.md` — schemas, migration and paths
- `CHANGELOG_V2.md` — changes in this release
- `TEST_REPORT.md` — actual commands/results and unverified areas
- `CREDITS.md` — in-game attribution, reference scope and privacy note
- `ASSET_CREDITS.md` — asset provenance
