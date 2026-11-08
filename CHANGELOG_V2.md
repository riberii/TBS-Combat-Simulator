# Changelog — V2.0

## Polish Pass Checkpoints — 2026-10-26 (no pygame available; see QA/POLISH_PASS_STATUS.md)

- **Audio:** added distinct `enemy_swing`, `ward`, `death`, `victory`, `defeat` sounds (previously aliases of unrelated cues); numeric checks only, not listened to.
- **Saves:** a damaged slot file is quarantined as `slotN.json.corrupt-<ms>` before a new save replaces it.
- **Rewards:** `GameState.claim_victory()` is now idempotent per enemy wave.
- **Notifications:** policy documented and tested as `TOAST_MAX = 4`, 340px (docs previously said five / 380px).
- **Version label:** standardised on V2.0 (matches `TITLE` in code and the release packager); stray V3.0 labels removed.
- **Title screen:** subtitle legibility plate; class labels aligned under each preview hero (not rendered or verified on screen).
- **Combat robustness:** seeded fuzz (260 fights, 8 classes) and input-spam checks found no defects; a small version is kept as `tests/test_combat_robustness.py`. The shared headless pygame stub now maps key names like the test stub.
- **Effects:** floating damage numbers capped at 24 with bounded stacking (`ui/vfx.py`); reduced-motion behaviour covered by a test.
- **Tests:** +10 regression tests (93 collected).

## V2.0 Continuation Pass — 2026-10-25: Documentation & Release Package Finalized

- **RELEASE_ACCEPTANCE_CHECKLIST.md**: Updated all section P (Release Package) items to [x] VERIFIED; corrected pytest count from 69 to 81.
- **QA/RELEASE_READINESS.md**: Rewritten to reflect CONDITIONAL GO verdict with all B1–B8 fixes verified, comprehensive checklist of all implemented features, and honest UNVERIFIED items (physical display/audio inspection).
- **TEST_REPORT.md**: Updated test count to 81 passed, 73 subtests (81 was the count at that point; later B-series fixes brought it to 83, see TEST_REPORT.md); appended B-series fix verification table and hero redesign summary.
- **All documentation now consistent**: README, TEST_REPORT, RELEASE_ACCEPTANCE_CHECKLIST, and QA/RELEASE_READINESS all referenced 81 tests passing at that point (now 83; the single authoritative figure lives in TEST_REPORT.md).

## Implemented in this release pass

### V2.0 Final Pass — 2026-10-25: Kitsune Visual Redesign, Meta-Progression, and Rebalance

- **Authored Kitsune Character Redesign** (ui/renderer.py):
  - Procedural anime vector artwork re-engineered from the newly supplied official character reference.
  - Long cascading amber/orange fox hair with straight-cut bangs, framing wisps, and delicate fox ears with fluffy cream inner tufts.
  - Seductive anime facial expressions with amber eyes, delicate lashes, and sly smirk rendered via _face.
  - White slip/camisole top with thin shoulder straps and red-cord amulet pouch hanging at the collarbone.
  - Dusty rose / mauve off-the-shoulder kimono with dramatic voluminous draped sleeves and geometric fold lines.
  - Deep crimson red obi sash with large decorative knot and dangling braided tassel cord.
  - Bare thighs leading into glossy dark-espresso / black thigh-high lace-up boots with stiletto heels and front cross-lacing.
  - Grand luxurious fluffy amber fox tail curling behind and above with warm orange gradients and ivory fluff plume.
  - Ambient spirit embers and azure foxfire decoy aura.
- **Permanent Meta-Progression & Currency (Sanctum of Ascension)** (core/meta_progression.py, Screen.SKILL_TREE):
  - Persistent meta-currency Choir Shards earned by completing runs (victory or defeat past stage 2), slaying cathedral bosses, and completing daily tasks. Shards persist across deaths, victories, and restarts.
  - 24-Node Skill Tree across all 8 classes (3 tiers per class costing 5, 10, and 20 shards) offering permanent stat bonuses.
  - Full in-game Skill Tree screen accessible from title menu with tabbed class navigation, prerequisite checks, purchase flow, and 50% refund capability ([R]).
  - Stat bonuses automatically applied to party heroes at run start (apply_profile_bonuses).
- **Deterministic Daily Choir Objective System**:
  - Deterministic date-seeded daily tasks rewarding 15 Choir Shards upon completion.
  - Prominently displayed in a Sanctum status card on the title screen and within the Skill Tree screen.
  - Automatic completion detection and claim reward flow in _finish(); strictly idempotent per calendar day.
- **Interactive Class Sparring Combat**:
  - Players can launch interactive 1v1 practice combat directly from the Class Academy (Screen.TUTORIALS) by pressing [ENTER] or [T].
  - Spawns a dedicated sparring construct allowing real-time mastery of turn actions, resources, guard, and class-specific mechanics.
- **Fallen Angel Rebalance & Backlash**:
  - Base break chance reduced to 0.40 (from 0.55), with steeper penalties per active restraint (-0.06) and tightness (-0.08).
  - Failed struggles inflict increased backlash: 14 HP (from 8) and 20.0 Lucidity (from 10.0).
  - Angel Skill Tree Tier 3 passive ('Iron Will') provides +0.08 break chance bonus to counter restraint penalties.
- **Menu Simplification**:
  - Victory and defeat ending menu streamlined to a single clean 'Return to Main Menu' action.
  - Title menu 'Load Game' cleaned up to 'Manage Saves'; Continue Run displays active slot.
- **Test Suite Expanded to 75 Tests**:
  - 6 new comprehensive unit tests covering profile shard economy, skill tree prerequisites, refunds, stat application, daily task idempotency, angel break chance rebalance, and run shard calculation.
  - 75 tests (73 subtests) passing with 0 failures.

### V2.0 Final Pass — 2026-10-25: Wardrobe, Tutorials, and Release Hardening

- **Wardrobe & Companions Screen** (Screen.WARDROBE): Browse and select your active companion
  pet (Ashen Raven, Spectral Wisp, Grave Hound Pup, Obsidian Scarab, Silver Sprite) and attire
  palette (Classic Penitence, Choir Vestments, Gilded Dawn, Blood Moon Rite) from the title menu.
  TAB/LEFT/RIGHT switches column; UP/DOWN browses entries; ESC returns to title.
- **Class Academy Screen** (Screen.TUTORIALS): Full tactical codex with 3 general tutorials
  (Combat Fundamentals, QTE Precision, Restraints) and 8 class-specific manuals accessible from
  the title menu. Sidebar shows lesson index; main panel shows summary and tactical tips.
- **Pet & Skin Wired to Run Start**: _start_run now writes state.pet and state.skin from
  the Wardrobe selection, so companion passives (hound +10% ATK, wisp MP/STA regen, sprite HP
  regen, beetle +3 DEF, raven +20% gold) are active throughout the run.
- **Title Menu Expanded**: “Wardrobe & Companions” and “Class Academy” added to title menu.
- **Color Constants Added**: GREEN and CYAN added to global palette constants in main.py.
- **All 69 Tests Passing**: pytest, alidate_content.py, and smoke_test.py all pass after
  all changes.


- **Major Battlefield Sprite Scale Overhaul**:
  - Hero battle formations increased: 1-Hero scale 0.90 (+36%), 2-Hero scale 0.70 (+46%), 3-Hero scale 0.52 (+30%), centered with conservative wing clearance.
  - Enemy battlefield scales increased: Solo enemy 1.60 (+45%), 2-enemy 1.50 (+44%), 3-4 enemies 1.38 (+38%), multi-row 1.05 (+46%). Boss multiplier preserved at 1.08x.
  - Repositioned foot baselines and VFX anchor calculations to maintain crisp particle targeting.
- **Eight Distinct Enemy Archetypes**:
  - Full suite of 8 archetypes: Beast (Hound/Wolf), Void (Wisp/Shade), Nature (Thornwraith), Construct (Sentinel/Bulwark), Cultist (Acolyte/Cantor), Hunter (Stalker/Prowler), Undead (Ghoul/Carcass), and Cinder (Pyromancer/Elemental).
  - Procedural vector rendering silhouettes, distinct anatomy, and palettes for all 8 archetypes.
- **Dynamic Merchant Pricing Matrix**:
  - Regional depth surcharge: higher halls (Drowned Nave, Deep Choir, Sunken Throne) increase item prices to reflect deep dungeon scarcity.
  - Class affinities: Rogues receive discounts on tools/smoke bombs, Witches on mana/elixirs, Warriors/Tanks on martial provisions, Vampires on vital brews, Dragonkin on brews (with surcharges on anti-draconic wards), and Kitsune on trick items.
- **Companion / Pet System**:
  - 5 strategic companions: Ashen Raven (+20% victory gold), Spectral Wisp (+5 MP/STA turn start), Grave Hound Pup (+10% party attack), Obsidian Scarab (+3 party defense), and Silver Sprite (turn-end heal for lowest-HP hero).
- **Cosmetics & Skins**:
  - Attire variants for all 8 classes: Classic Penitence (Default), Choir Vestments (Abyssal), Gilded Dawn (Dawnlight), and Blood Moon Rite (Crimson).
- **Six Functional Game Modes**:
  - Story Campaign (12 authored halls, boss milestones, and narrative epilogue).
  - Endless Rift (escalating waves with boss rotation and increasing bounties).
  - Boss Rush Gauntlet (consecutive battles against cathedral guardians).
  - Colosseum Arena (high-stakes survival skirmishes).
  - Training Grounds (dummy drills and ability experimentation).
  - Daily Challenge (calendar-date seeded runs).
- **Expanded Narrative & Atmospheric Flavor**:
  - 6 authored chapters detailing the lore of Emberfall and the Sunken Cathedral.
  - Rich multi-sentence stage intros for all 12 stages, describing environmental decay and altar echoes.
  - Class-specific combat barks for all 8 classes across combat start, low HP (< 30%), boss encounters, and victory.
  - Branching NPC dialogue for Archivist Voren, Sister Moira, and the Hollow Peddler.
- **Class Tutorials & Tactical Manuals**:
  - Comprehensive guide covering turn flow, timing/memory QTEs, and Angel chain mechanics.
  - Dedicated tactical manuals for all 8 hero classes detailing optimal resource loops and counters.
- **Creator Credit & Licensing**:
  - Visible in-game credit: "Made by Riberii" with link to `https://github.com/riberii/TBS-Combat-Simulator`.
  - Upstream MIT license and copyright notice for Marquis Verino preserved intact in `LICENSE.txt` and `CREDITS.md`.

## Existing systems preserved

Story (12 halls/three boss milestones), Endless Rift, enemy telegraphs and boss profiles, QTEs, combat event/VFX feedback, procedural audio, settings, automatic between-encounter recovery, merchant, JSON saves with backup handling, and the local mode-aware leaderboard remain in the same shared architecture.
