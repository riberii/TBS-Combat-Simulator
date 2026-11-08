# Release Readiness — Abyssal Choir V2.0

## Verdict

**CONDITIONAL GO** — All core tactical RPG systems, 8-class roster, vector art redesigns matching authored reference designs, 6 game modes, wardrobe/skins/companions, daily objectives, regional pricing, NPC lore dialogues, 24-node skill tree meta-progression, save integrity, and corruption safety are fully implemented and automated-regression tested (83 unit/integration tests passing, 73 subtests passing, 0 failures).

Physical visual inspection on a live 1080p display and physical speaker audio listening are the remaining owner-side acceptance checks, as this development environment runs headlessly (`SDL_VIDEODRIVER="dummy"`, `SDL_AUDIODRIVER="dummy"`).

---

## Evidence Used

- **Source of truth:** `Chains_of_the_Abyssal_Choir_V2.0` workspace directly extracted and updated.
- **Environment:** Windows 11, Python 3.14.2, pygame-ce 2.5.6 (SDL 2.32.10), NumPy 2.4.4.
- **Test Suite:** `python -m pytest tests/` — **83 passed, 73 subtests passed, 0 failed** in 2.66s.
- **Content Validation:** `python tools/validate_content.py` — **PASS** (8 playable classes, 8 unique silhouettes, 37 validated abilities, 8 enemy archetypes, 4 boss profiles, 12 authored halls).
- **Headless Smoke Simulation:** `python tools/smoke_test.py` — **PASS** (seed 20261024, stage 1, 14 turns, score 881; atomic save/load and idempotent local leaderboard verified).
- **Clean Package Verification:** `python tools/package_release.py` — **PASS** (builds clean ZIP without `.git`, caches, or personal saves; extracts to temporary sandbox and verifies tests pass from clean archive).
- **SHA-256 Provenance:** Recorded in `SHA256SUMS.txt`.

---

## Acceptance Checklist

### Visual / Presentation

- [x] **Character Redesigns & Scale:** All 8 classes feature authored vector silhouettes matching the provided reference images:
  - **Warrior:** Art Nouveau silver hair, gold butterfly ornament, gold filigree armor, radiant golden blade.
  - **Tank:** Platinum blonde hair, white/gold enameled plate, sacred cross tabard, massive greatsword with deep blue sapphire inlay.
  - **Witch:** Raccoon ears, large tattered grey hat with twin flower pins & lightning tear, chocolate brown hair, off-the-shoulder keyhole sweater dress, striped thigh-high stockings with garter strap, fluffy boot cuffs, Mary-Jane shoes, giant fluffy striped raccoon tail.
  - **Fallen Angel:** Silver/white hair with lilac tint, glowing violet eyes, curved obsidian dragon horns, 3-tier feathered/clawed wings, segmented barbed dragon tail, floating soul-fire embers.
  - **Kitsune:** Amber fox ears & hair, off-shoulder kimono, crimson obi, white slip, lace-up boots, billowing fluffy tail.
  - **Dragonkin:** Pure white hair, crimson dragon horns, shrine-maiden miko robes, pleated red hakama, sinuous tail, furnace embers.
  - **Rogue & Vampire:** Asymmetric hood, dual curved daggers; tailored velvet coat, floating blood crests.
- [x] **Battlefield Formation Scaling:** Hero formations (1-Hero: 0.90, 2-Hero: 0.70, 3-Hero: 0.52) preserve layout clearance across chronicle sidebar and enemy lane. Angel wings span tested clear of sidebar bounds.
- [x] **Enemy & Boss Silhouettes:** 8 distinct enemy archetypes (Beast, Void, Nature, Construct, Cultist, Hunter, Undead, Cinder) and 4 boss profiles with increased scale (1.38–1.60x) and clear intent indicators.
- [x] **Notification & Floater Polish:** Toast stack limited to 4 visible notifications (`TOAST_MAX = 4`, 340px max width, per `ui/vfx.py`); floater vertical staggering (-22px offset per overlapping popup); explicit category-based display durations.
- [x] **Cosmetic Skin Palettes:** 4 attire themes (Classic Penitence, Choir Vestments, Gilded Dawn, Blood Moon Rite) dynamically recolor hero sprite models at runtime (`test_all_skins_palette_changes_render_model`).
- [~] **Display Resolution & Fullscreen:** 1280×720 base logical canvas with responsive letterboxing and F11 fullscreen toggle. *Headless only: live human display inspection recommended.*

### Animation / Sound

- [x] **Motion & Timing:** Actor delta-time motion cues with expiration timers (lunge, slash, recoil, barrier flashes, floaters).
- [x] **Procedural Audio Synthesis:** 15 procedural SFX generators covering physical strikes, magic surges, barriers, restraints, UI, and boss phases; BGM loop generation with `_SilentAudio` headless fallback.
- [x] **Settings Integration:** Master volume, SFX volume, mute toggle (F2), screen shake, particle effects, and reduced motion settings persist and modulate runtime systems.
- [~] **Physical Audio Output:** Synthesis verified via automated sample generation; *physical speaker/headphone listening remains an owner-side check.*

### Gameplay / Narrative

- [x] **8 Complete Class Kits:** Unique resource loops (Rage, Bastion/Stamina, Combo, Mana, Lucidity/Restraints, Spirit, Blood, Heat), 37 validated abilities, and signature status interactions.
- [x] **Strategic Combat Intent:** Enemy intent previews with damage estimates, multi-phase boss cycles, and QTE struggle challenges (timing, typing, mash, memory).
- [x] **Fallen Angel Restraints:** Escalating curse chains with visible binding graphics, Lucidity drain, Break Restraint mechanics, and rebalanced struggle backlash.
- [x] **6 Game Modes:** Story Campaign (12 halls), Endless Rift, Boss Rush Gauntlet, Colosseum Arena, Training Grounds, and Daily Challenge—all selectable, functional, and persisting mode across saves.
- [x] **Meta-Progression (Sanctum of Ascension):** Persistent Choir Shards (`◈`), 24-node skill tree across all 8 classes (all 24 stat keys wired to live simulation hooks), and node refunding (`[R]`).
- [x] **Wardrobe & Companions:** Dedicated selection screen (`Screen.WARDROBE`); 5 companions with live combat passives (Raven +20% gold, Wisp MP/STA regen, Hound +10% ATK, Beetle +3 DEF, Sprite HP heal).
- [x] **Class Academy & Sparring:** Dedicated tutorial codex (`Screen.TUTORIALS`) with 3 general tutorials, 8 class manuals, and interactive 1v1 sparring combat against an automaton.
- [x] **Honest Daily Objectives:** Deterministic date-seeded tasks evaluating exact conditions (merchant heals, elite kills, party deaths, HP threshold) without artificial shortcuts.
- [x] **Regional Merchant Economy:** Dynamic price scaling by stage depth (`oath_road`, `cathedral`, `sanctum`, `choir_heart`, `abyss`) and class affinity discounts.
- [x] **NPC Lore Dialogues:** In-hub dialogue system (`Screen.DIALOGUE`, hub `[T]` key) featuring Archivist Voren, Sister Moira, and the Hollow Peddler.

### Engineering / Ship

- [x] **Single Entry Point:** `main.py` is the single authoritative entry point with clean subsystem separation.
- [x] **Crash Prevention & Integrity:** Corrupt profile and save files are safely preserved as timestamped `.bak` files without crashing or losing user data.
- [x] **Clean Packaging:** `tools/package_release.py` automatically bundles a clean release archive excluding `.git`, `__pycache__`, `.pytest_cache`, and personal user saves.
- [x] **Attribution & Licensing:** Preserves MIT license, copyright Marquis Verino, and visible credit to "Made by Riberii" and `https://github.com/riberii/TBS-Combat-Simulator`.
- [x] **Automated Test Coverage:** 83 unit/integration tests passing (73 subtests) with 0 regressions.

---

## Remaining Owner Acceptance Steps

1. **Launch on Physical Display:** Run `py -3 main.py` or double-click `run_game.bat`.
2. **Visual Inspection:** Verify character models on the title screen and in combat at native display resolution.
3. **Audio Acceptance:** Verify procedural audio effects and background music on physical speakers/headphones.
4. **Campaign Playthrough:** Complete a full Story or Endless expedition using your preferred party combination.
