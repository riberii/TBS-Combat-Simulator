# Release Acceptance Checklist — Chains of the Abyssal Choir V2.0

Generated: 2026-10-25  
Tester environment: Python 3.14.2 · pygame-ce 2.5.6 · Windows 11  
Legend: `[x] VERIFIED` · `[~] IMPLEMENTED BUT NOT VISUALLY VERIFIED (headless only)` · `[ ] NOT DONE`

---

## A. Core Architecture

- [x] Single authoritative entry point (`main.py`)
- [x] Clean package structure: `core/`, `entities/`, `systems/`, `ui/`, `tests/`, `tools/`
- [x] No circular imports; explicit imports only; no broad silent exception handling
- [x] AST parse of `main.py` succeeds (`python -c "import ast; ast.parse(open('main.py').read())"`)
- [x] `python -B -m compileall -q .` exits 0 (all `.py` files compile cleanly)

---

## B. 8-Class Roster

- [x] **Warrior** — Rage resource, Slash/Heavy Blow/Battle Cry/Whirlwind, Bleed DoT
- [x] **Tank** — Stamina shield, Shield Slam/Iron Wall/Taunt, threat management
- [x] **Rogue** — Combo points, Quick Strike/Smoke Bomb/Eviscerate, crits on ailments
- [x] **Witch** — Mana/Overcast, Fireball/Ether Surge/Chain Lightning, burn stacks
- [x] **Fallen Angel** — Lucidity + Restraint chains, Writhe/Break Restraint/Martyrdom
- [x] **Kitsune** — Spirit gauge, Foxfire Thread/Paper Moon Double/Nine-Tail Ascendance, decoy
- [x] **Vampire** — Blood gauge, Sanguine Lunge/Veil of Night/Eclipse Feast, lifesteal
- [x] **Dragonkin** — Heat gauge/Overheat, Scale Guard/Ember Breath, cinder archetype

---

## C. Visual Scaling (P0 Fixes)

- [x] Solo hero formation scale 0.90 (≈378 px tall at base 420)
- [x] Duo hero formation scales 0.70 (≈294 px); wings clear sidebar at x≥237 and x≤688
- [x] Trio hero formation scales 0.52 (≈218 px); verified by chronicle/lane safety tests
- [x] Enemy solo scale 1.60; 2-enemy 1.50; 3-4 enemy 1.38; multi-row 1.05
- [x] Boss scale multiplier 1.45 (≈396 px for large bosses)
- [x] VFX particle anchors updated to new hero baseline (offset 210)

---

## D. Notification / Floater Polish (P0 Fixes)

- [x] Toast max-width 380 px; max visible toasts 4 (`TOAST_MAX`)
- [x] Vertical floater stagger: same-position floaters offset by -22 px each
- [x] Toast durations: phase 4.5 s · restrained 3.2 s · freed 3.0 s · crit/heal 2.0 s · loot 3.0 s · level_up 3.5 s
- [x] No duplicate combat popup stacking (deduplication via floater stagger + category keys)

---

## E. Combat Depth

- [x] Enemy intent previews with estimated damage: `Attack (~12 dmg)`, `Flurry (2× ~8 dmg)`, `Crushing Blow (~24 dmg)`, `DEVASTATION! (~35 dmg)`
- [x] Keypad 1–9 normalized to `"1"`–`"9"` in both `_key_name` and `CombatSystem.handle_key`
- [x] QTE timing/memory challenges implemented (phase `QTE`, drawn by `p.qte`)
- [x] Guard/dodge/cast/death animations via Character state machine in `ui/renderer.py`
- [x] Restraint system: FallenAngel chains rendered and animated; Lucidity drain and Bloodlust implemented
- [x] Status effects: Bleed, Burn, Stun, Silence, Expose tracked per entity
- [x] Round-start and round-end pet hooks active in CombatSystem (wisp, sprite, hound, beetle, raven)

---

## F. 6 Game Modes

- [x] **Story Campaign** — 12 authored halls, 3 boss milestones, narrative intros, campaign ending
- [x] **Endless Rift** — seeded encounter generation, bounded scaling curves
- [x] **Boss Rush** — consecutive cathedral boss gauntlet (start at stage 4; +3 stages per boss)
- [x] **Colosseum Arena** — high-stakes survival (`endless=True`), increased rewards
- [x] **Training Grounds** — 999 gold, non-competitive (not recorded in leaderboard)
- [x] **Daily Challenge** — `run_seed = int(datetime.now().strftime("%Y%m%d"))` (calendar-seeded)
- [x] All 6 modes selectable from title → Mode Select menu

---

## G. Economy & Regional Pricing

- [x] `calculate_item_price` in `systems/inventory_system.py` applies region parameter
- [x] Abyss region: ×1.60 base surcharge; Sanctum/Cathedral: ×1.25
- [x] Oath Road: ×0.95 (discount for early-area pilgrims)
- [x] Dragonkin anti-draconic surcharge ×2.0 in Cathedral and Sanctum regions
- [x] Class affinity discounts: Rogue tool 15% off, Witch arcane 10% off, Tank armor 10% off

---

## H. Leaderboard

- [x] LocalLeaderboard in `systems/leaderboard.py` supports all 6 mode filters
- [x] Filter cycling (LEFT/RIGHT on Leaderboard screen): `all / story / endless / boss_rush / arena / daily`
- [x] Training runs flagged `"training"` and excluded from competitive ranking
- [x] Score formula: `stage × 100 + bosses × 350 + levels × 50 + gold ÷ 5 + 750` (victory bonus)
- [x] Corrupt leaderboard file: error displayed without crash; file preserved

---

## I. Wardrobe & Companions (NEW)

- [x] `Screen.WARDROBE` enum member defined
- [x] Title menu entry: **"Wardrobe & Companions"** routes to `Screen.WARDROBE`
- [x] `_key_wardrobe`: TAB/LEFT/RIGHT switches pet ↔ skin column; UP/DOWN scrolls; ESC returns
- [x] `_draw_wardrobe`: dual-column gothic panel (companions left, attire right); accent swatches
- [x] 5 companions: Ashen Raven, Spectral Wisp, Grave Hound Pup, Obsidian Scarab, Silver Sprite
- [x] 4 attire themes: Classic Penitence, Choir Vestments, Gilded Dawn, Blood Moon Rite
- [x] Selection persists into run: `state.pet` and `state.skin` assigned in `_start_run`
- [x] Headless integration test passes (TAB, UP/DOWN, ESC, pet/skin wired to state)

---

## J. Class Academy / Tutorials (NEW)

- [x] `Screen.TUTORIALS` enum member defined
- [x] Title menu entry: **"Class Academy"** routes to `Screen.TUTORIALS`
- [x] `_key_tutorials`: UP/DOWN browses lessons; ESC returns
- [x] `_draw_tutorials`: sidebar lesson index (3 general + 8 class), main panel with summary + tips
- [x] 3 general tutorials: Combat Fundamentals, QTE Precision, Restraints & Lucidity
- [x] 8 class manuals: Warrior, Tank, Rogue, Witch, Fallen Angel, Kitsune, Vampire, Dragonkin
- [x] Headless integration test passes (navigation, lesson count, ESC)

---

## K. Save / Load / Settings

- [x] `SaveManager` with autosave slot 1 and manual slots 2–4 (displayed as 1–3)
- [x] `state.pet` and `state.skin` serialized in `to_dict()` / `from_dict()` in `core/game_state.py`
- [x] Settings round-trip: music volume, SFX volume, muted, screen shake, particles, reduced motion, fullscreen
- [x] Corrupt or missing save slot: popup error, no crash
- [x] Save-during-combat disabled; autosave triggers on victory

---

## L. Credits & Attribution

- [x] `CREDITS.md` contains **"Made by Riberii"** and `https://github.com/riberii/TBS-Combat-Simulator`
- [x] In-game `Screen.CREDITS` screen displays same attribution
- [x] MIT notice and **Copyright (c) 2026 Marquis Verino** preserved in `LICENSE.txt`
- [x] No personal user saves (`saves/autosave.json`, `saves/leaderboard.json`) in release archive
- [x] No telemetry, network calls, or API keys; game works fully offline

---

## M. Audio

- [x] `ProceduralAudioSystem` generates all SFX and BGM at runtime (no bundled audio files)
- [x] `_SilentAudio` fallback if audio init fails (prevents crash in headless / CI environments)
- [x] F2 mute toggle; volume controls in Settings

---

## N. Automated Tests

- [x] `pytest`: **83 passed, 73 subtests passed** in < 3 s
- [x] `tools/validate_content.py`: 8 classes · 8 sprites · 37 abilities · 8 archetypes · 4 bosses · 12 halls
- [x] `tools/smoke_test.py`: seed 20261024 · 14 turns · score 881 · save/load idempotent

---

## O. Documentation

- [x] `README.md` — covers 8 classes, 6 modes, pets, skins, wardrobe, tutorials, regional pricing, credits
- [x] `CHANGELOG_V2.md` — final pass entry dated 2026-10-25
- [x] `TEST_REPORT.md` — final pass results appended with new screen verification table
- [x] `CREDITS.md` — creator and reference attribution
- [x] `ASSET_CREDITS.md` — procedural asset inventory
- [x] `LICENSE.txt` — MIT, Copyright (c) 2026 Marquis Verino
- [x] `GAME_DESIGN.md`, `NARRATIVE_GUIDE.md`, `ART_AND_ANIMATION_GUIDE.md`, `SAVE_FORMAT.md`

---


---

## Q. Authored Kitsune Character Redesign (NEW)

- [x] Vector artwork updated in ui/renderer.py matching the authored anime character reference image
- [x] Long cascading amber/orange fox hair with straight-cut bangs and side wisps
- [x] Pointed fox ears with fluffy cream inner tufts and pink shading
- [x] Seductive anime facial expressions with amber eyes, lashes, and sly smirk rendered via _face
- [x] White slip/camisole top with thin shoulder straps and red-cord amulet pouch at collarbone
- [x] Dusty rose / mauve off-the-shoulder kimono with dramatic voluminous draped sleeves and fold lines
- [x] Deep crimson red obi sash with large decorative knot and dangling braided tassel cord
- [x] Bare thighs and glossy dark-espresso / black thigh-high lace-up boots with stiletto heels and front cross-lacing
- [x] Grand luxurious fluffy amber fox tail curling behind and above with warm orange gradients and ivory plume fluff
- [x] Ambient spirit embers and azure foxfire decoy aura

---

## R. Permanent Meta-Progression & Choir Shards (NEW)

- [x] Persistent meta-currency Choir Shards (◈) in core/meta_progression.py
- [x] Shards earned on run completion (victory/defeat past stage 2), boss kills, and daily objectives
- [x] Shards survive deaths, defeat, restarts, and mode changes (stored in profile.json)
- [x] 24-node Skill Tree across all 8 classes (3 tiers: 5, 10, 20 shards)
- [x] Full in-game Skill Tree screen (Screen.SKILL_TREE) with tabbed class navigation and prerequisite checks
- [x] Stat bonuses applied to party heroes at run start (pply_profile_bonuses)
- [x] Node refund mechanism ([R] refunds 50% shards and higher dependent tiers)
- [x] Automated unit tests: economy, prerequisites, cascade refund, and stat bonus verification

---

## S. Daily Choir Objective System (NEW)

- [x] Deterministic date-seeded daily objective generation (get_daily_task)
- [x] Displays objective, target mode, date, and +15 Shard reward
- [x] Displayed on Title screen Sanctum card and inside Skill Tree screen
- [x] Automatic completion verification and claiming at run end in _finish()
- [x] Strictly idempotent: cannot be claimed twice on the same calendar date

---

## T. Interactive Class Sparring Combat (NEW)

- [x] Launched directly from Class Academy (Screen.TUTORIALS) via [ENTER] or [T]
- [x] Spawns dedicated 1v1 practice combat against a Sparring Automaton
- [x] Real-time practice of class turn economy, resources, guard mitigation, and special skills
- [x] Safe training environment (does not pollute competitive leaderboard)

---

## U. Fallen Angel Rebalance (NEW)

- [x] Base break chance reduced from 0.55 to 0.40 with steeper restraint (-0.06) and tightness (-0.08) penalties
- [x] Increased failure backlash: 14 HP (from 8) and 20.0 Lucidity (from 10.0)
- [x] Angel Skill Tree Tier 3 passive ('Iron Will') provides +0.08 break chance bonus

## P. Release Package

- [x] Release ZIP generated: `Chains_of_the_Abyssal_Choir_V2.0_Release.zip` (excludes `.git`, `__pycache__`, `saves/*.json`, `.pytest_cache`)
- [x] SHA-256 checksum in `SHA256SUMS.txt`
- [x] ZIP extracted to temp dir; `pytest`, `validate_content.py`, `smoke_test.py` all pass on extracted copy

> **Run to generate:** `python tools/package_release.py` (see packaging section below)

---

## Release Packaging Commands

```powershell
# From the project root:
python tools/package_release.py
# Then verify the extracted package:
$env:SDL_VIDEODRIVER="dummy"; $env:SDL_AUDIODRIVER="dummy"
python -m pytest
python tools/validate_content.py
python tools/smoke_test.py
```
