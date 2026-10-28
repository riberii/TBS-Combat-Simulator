# R2 integration - status and test report

Branch: `r2-working-2026-10-26` (branched from the received working tree; `main` and `polish-pass-checkpoint-2026-10-26` untouched).

## READ THIS FIRST - what could not be verified
**pygame-ce could not be installed in the build environment (no network, no wheel available).** The game window was
never launched, so **no real Pygame screenshots or recordings exist**, and every drawing change below is
"wired but not run in Pygame". Everything labelled TESTED means unit/integration tests of game *logic* run against
the real source files, or asset logic run with a PIL stand-in (`tests/pil_pygame_shim.py`, not pygame-ce).
Please run on your machine: `pip install -r requirements.txt && python main.py`, then `python -m unittest discover -s tests`.

## 1. Gameplay (TESTED - real source, real CombatSystem)
| Feature | Files | Evidence |
|---|---|---|
| **Break Restraint no longer a flat mash.** Data-driven library of 9 restraint trials (paced pull, rune swap, sigil law with reversed rules, forbidden word, rune recall, hollow beat counter-rhythm, 3 multi-stage seals); anti-repetition, tier + tightness scaling, restraint affinity | `systems/restraint_trials.py` (new), `systems/combat_system.py` | `tests/test_r2_restraint_trials.py` (27 tests) |
| **Anti-spam:** presses <0.07 s are jams, <0.16 s half credit + fatigue, fatigue stalls sustained hammering, steady 3.5-5/s wins. | same | Tests: macro burst of 500 presses = 1 accepted; hammering at 8/12/20/40/100 Hz fails at tiers 1/4/8; steady 3.5/4/5 Hz wins; in the real combat loop 12+/14 seeded space-spam attempts fail, steady pacing clears `paced_pull` |
| **Heavier failure:** backlash 14 HP/20 LUC base (existing test values unchanged) now +3 HP/+5 LUC per earlier failure this fight (cap 3 steps); after 2 failures the "Choir of Correction" locks Break for 2 turns (menu shows CD); resets on success, battle end and rest. Always leaves 1 HP. | `entities/player.py` | 7 tests incl. lock expiry (path back), cap, no self-kill |
| Every trial is solvable (`is_solvable()`) at tiers 1-10 x 5 seeds | | tested |
| Generic QTE panel (`panel_lines`) so new trials render with no per-type UI code | `main.py` | executed under mocks (`tests/test_r2_draw_smoke.py`), never rendered |

### 1b. Skill trees 24 -> 48 nodes (TESTED - real CombatSystem)
Each class now has 6 nodes in 4 branches: core (t1-t3, legacy ids/costs/effects unchanged so old profiles load), specialisation (t4, needs t1), utility (t5, needs t1) and a capstone (t6, needs t3+t4+t5, 30 shards) that always carries a stated downside.
Effects are runtime perks (`Player.perks`) consumed in `systems/combat_system.py`: execute / opener / crit damage / lifesteal / regen / flat reduction / last stand / thorns / evade / damage dealt and taken / wounded damage, plus three Fallen Angel perks that change restraint play (Penitent Focus: +25% trial time; Lucid Ledger: softer Break backlash and a later Correction lock; Brief Release: one unbound strike after a clean Break, costing 8 Lucidity).
Refund is 50% per removed node (existing rule) and cascades through dependants. Perks are recomputed from the profile (never stacked) and survive save/load.
Evidence: `tests/test_r2_skill_tree.py` (30 tests): tree shape and prerequisites, purchase/refund, every perk's numeric effect through real strikes/enemy hits, save/load round trip, and all 8 classes with all 48 nodes fighting seeded random fights in bounds. The skill-tree screen was rewritten for 6 cards (mock-executed only).

### 1c. Bugs found and fixed
* **Sensory Deprivation did not black out enemy intent.** The enemy cards read the raw `intent` attribute and ignored `CombatSystem.intent_hidden`, so the Angel could see "> Crushing Blow (1.7)" while blinded. Cards now draw a black bar with "> ???". Tests: combat masks intent for a deprived Angel; the card draw leaks no intent text when hidden and shows it normally otherwise.
* **Vampire "Veil of Mist" gave +5 turns of ward instead of the described +5 HP absorb.** It now soaks that many HP (tested).

## 2. Art/audio integration (WIRED, executed under mocks, NEVER RENDERED in Pygame)
Direction from the user: all characters in a Nikke / Azur Lane adult-anime style. No image generator was available, so the art is cropped from the concept boards the user supplied (see `Assets/Generated/R2/CROP_PROVENANCE.md`), not newly drawn.

| Item | Where | Status |
|---|---|---|
| **Anime hero models for all 8 classes** (feathered 480 px busts, all women) replace the procedural hero bodies in combat, hub, setup and previews: glow halo, idle sway, red hit-flash, lunge offsets, party-size-aware sizing | `ui/renderer.py::_draw_model`, `ui/r2_assets.py` | sizing/hit-box math, flash-on-a-copy, fallback and error paths unit-tested; **look and scale unverified** |
| **Restraints stay readable on the anime art:** each live restraint gets a pulsing ring + icon on the model and the original hover/struggle hit boxes are re-mapped onto it (crown/halo, rune wings, chains, vines) | `ui/renderer.py::_draw_restraint_mark`, `model_hit_boxes` | math tested, drawing mock-run; **hover alignment unverified** |
| **Original procedural models are one setting away:** Settings -> "Anime character models: OFF" restores every original model, including the Fallen Angel's (the earlier chibi sprite pack was rejected, deleted from the release, and its code removed) | `systems/settings_system.py`, `main.py` | tested |
| **Main menu:** anime key art of all 8 heroes with slow parallax drift, drifting embers, the keyed game logo, menu/badge moved to the right column; falls back to the original title if the art is missing | `main.py::draw` | layout + fallback + reduced-motion branches mock-run; **screen unverified** |
| **Turn-start character cut-in:** the acting hero's bust slides in on a tinted band with her name (once per hero per round, ~0.9 s, no slide under reduced motion, never blocks input) | `main.py::_r2_cutin_tick`, `Painter.cutin` | timing curve and trigger rules tested; **draw unverified** |
| 8 class portraits as face thumbnails on party cards and a large portrait on the party-setup screen | `main.py` | layout/overlap **unverified** (card text may crowd the 42 px face) |
| 8 spell icons pop above the acting hero (fade, non-blocking) | `ui/r2_assets.py` | lifecycle + mapping tested; draw **unverified** |
| Audio: `chain_tighten`, `seal_success`, `qte_failure` WAVs via `AudioSystem.load_file_sfx` | `systems/audio_system.py` | format/clipping/click checks pass; **never listened to** |
| Settings toggles "Generated R2 art" and "Anime character models" (default ON; old settings files still load) | `systems/settings_system.py` | tested |
| Fallbacks: a missing/corrupt/wrong-size file or any draw error disables that asset and the old procedural art takes over | | tested |

Previews (PIL, **not in-game**): `QA/r2_previews/portraits_icons_titleart.png`, `elements.png`. Regenerate crops with `python tools/r2_build_models.py <boards folder>`.

## 3. Generated but NOT integrated
`resonance_pulse.wav` (no Resonance system exists in the code), element sheets `vfx/elements/*` (no element system), (restraint icons ARE used on the hero models), the procedural cathedral background (reviewed: cruder than the existing renderer's backdrop, deliberately not used), enemy art (enemies keep their procedural sprites; an attempt to cut the boss 'Vael' out of a board failed - the source is ~120 px tall and its dark dress merges with the backdrop).

## 4. R2 prompt items NOT implemented
Attack types and elemental magic (section 5), hybrid card system (section 6), animated sprites for the other 7 classes and enemies, real music, new boss/endless balancing. The earlier open items (save/load slots, endless beyond stage 12, full QA) were not re-worked this session.

## 5. Test results
| Run | Tests | Result |
|---|---|---|
| Baseline as received (stub, before changes) | 93 | 2 errors (`test_all_skins_palette_changes_render_model`, `test_tutorial_sparring_fight_launches_for_all_classes`: `pygame.mixer`/draw calls the import-only stub cannot do) |
| After R2 (this build) | 201 (+108 new: 27 trials/escalation, 30 assets, 30 skill tree/blackout, 21 mocked-draw/cut-in/title/renderer) | the **same 2 errors**, 2 skipped, 0 failures; no regressions |
| `tools/validate_content.py`, `tools/smoke_test.py` | | pass (headless stub; not a window run) |

Regression caught during work: new `GameApp`/`Painter` code assumed `__init__` had run; 12 existing tests (objects built without it) failed and were fixed with class-level defaults and `getattr` guards. A float-truncation bug in the new animation timer (8 x 0.1 s landed on frame 7) was found by a test and fixed.

## 6. Known risks to check first when you run it
1. Party-card face thumbnail (x+r.right-50) vs "HP nnn/nnn" text overlap.
2. Hero models: size/position in the party lane (busts are 300 px x scale, narrowed by neighbour spacing), glow, and restraint hover boxes on the art (`MODEL_HIT_FRACTIONS` in `ui/r2_assets.py`).
3. Skill-tree screen: six 58 px cards (text fit) and the 4-line passives list above the daily objective.
4. Title screen: the 10-item menu under the logo (y 228-582) and the badge below it (y 594).
5. Turn cut-in band/text overlap with the battlefield.
6. Enemy-card blackout bar and trial QTE panel text fit (`main.py`, `panel_lines` branch).
7. Disable art any time: Settings -> "Generated R2 art: OFF" (portraits, title, icons) and "Anime character models: OFF" (heroes).
