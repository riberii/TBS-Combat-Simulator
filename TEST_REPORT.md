# TEST_REPORT — Chains of the Abyssal Choir R2

**Read this first.** Real Pygame-ce could not be installed in the build environment (PyPI, GitHub and apt were blocked), so
**the game was never launched on real Pygame-ce, no real screenshot or recording exists, and no audio was ever listened to.**
Everything below is labelled by what it actually proves.

| Evidence level | Meaning |
|---|---|
| **STATIC** | compile / parse / data validation; no code of the game is run in a window |
| **UNIT (stub)** | `unittest` against real game logic with an import-only Pygame stub (`tools/headless_bootstrap.py`) |
| **EMULATED** | `GameApp` driven under the dev-only PIL emulation of Pygame (`tools/devpygame`), rendered to PNG. Catches Python errors in draw paths and gross layout faults. **Not** a Pygame-ce capture: fonts, blending, scaling and timing differ |
| **NUMERIC** | signal / simulation numbers computed by script |
| **NOT DONE** | real Pygame-ce window, real screenshots, real input timing, audio listening, gameplay feel |

## Environment

Linux container, Python 3, NumPy, Pillow, OpenCV (art extraction only). pygame-ce **absent**. pytest absent (suite is `unittest`).

## Results (final run of this build)

| Check | Level | Result |
|---|---|---|
| `python -m compileall -q .` | STATIC | PASS |
| `python tools/validate_content.py` | STATIC | PASS: 8 classes, 8 sprites, 37 abilities, 8 archetypes, 4 bosses, 12 halls, **24 cards, 19 restraint trials** |
| `python tools/smoke_test.py` | UNIT (stub) | PASS: seed 20261024, 14 turns, score 881, save/load, idempotent leaderboard |
| `python -m unittest discover -s tests` | UNIT (stub) + EMULATED | **216 tests: 212 pass, 2 skipped, 2 errors** (see below) |
| `tools/render_preview.py` (all screens) | EMULATED | renders without exceptions; PNGs named `*_emulated.png` |
| `tools/draft_flow_check.py` | EMULATED | draft screen pick / skip / forge / back flow passes |
| `tools/balance_sim.py` | NUMERIC | no crashes, no stuck fights (tables below) |
| R2 WAV effects (`tests/test_r2_audio.py`) | NUMERIC | no clipping, DC < 0.01, no edge clicks. **Not listened to** |

### The 2 test errors and 2 skips — investigated, not hidden
- `test_v2_features::test_all_skins_palette_changes_render_model` and `::test_tutorial_sparring_fight_launches_for_all_classes` need real `pygame.Surface` / `pygame.mixer`, which the import-only stub does not provide (`AttributeError: module 'pygame' has no attribute 'mixer'`). They are environment errors, not known game defects, and **have not passed in this environment**. Run them on a machine with pygame-ce.
- 2 skips: toast wrapping tests that need real pygame-ce font rendering.

### Test inventory added in R2 (all UNIT (stub) unless stated)
| File | What it proves |
|---|---|
| `test_restraint_trials.py` | every one of 19 trials is solvable by its reference solution at every allowed tier (12 seeds); blind mashing/holding at 8/25/60 Hz never clears any trial; `SpamGuard` fatigue; same seed → same trial; no immediate repeat; boss trials only for their boss; tier scaling monotonic |
| `test_restraint_integration.py` | trials inside real `CombatSystem`: themed selection, tier scaling, visible failure causes, recovery momentum, watchdog, boss trials, save/load |
| `test_intent_blackout.py` | Sensory Deprivation hides enemy intent in the combat preview and on enemy cards (bug reported by the user) |
| `test_skill_perks.py` | ≥6 skill nodes per class (48 total); each has a live runtime hook and changes behaviour; perks survive save/load |
| `test_elements.py` | affinities, statuses (Burn/Chill/Shock/Suppressed/Mark), enemy attack elements, determinism |
| `test_cards.py` | piles, seeded RNG, draw/discard/exhaust/reshuffle, drafts of three, upgrade/thin/transform, relics, tags, dead-hand prevention, Angel cards, save/load, card data validation |
| `test_draft_flow.py` | draft screen and shrine hub/screen flow via subprocess under EMULATION |
| `test_angel_cover.py` | no skin-coloured pixels left in the Fallen Angel's chest region; the cover script is idempotent; art sizes/alpha unchanged |
| `test_shrine.py` | shrine bargains: distinct seeded offers, costs shown and never lethal, refused bargains change nothing, gamble both outcomes, save/load of the once-per-hall flag |
| `test_assets_vfx.py` | every sheet/icon/ring/boss-art path exists and matches its declared grid; `Animation` timing, loop, one-shot, reduced-motion; art-effect lifecycle, cap, missing-art fallback; asset-root path jail |
| `test_r2_audio.py` | NUMERIC checks of the four R2 WAVs and loader errors |

## Balance (NUMERIC, `tools/balance_sim.py --runs 20 --skill 0.75`)

A scripted bot plays the real combat system for 12 stages; skill = probability each QTE/trial is cleared. It is a **regression tripwire, not a tuning authority**: the bot never manages restraints, never reads intents, and never builds a deck.

Reaching stage ≥5 (n=200 per class, ability-only bot), original game vs R2: Warrior 46% → 43%, Tank 90% → 96%, Vampire 59% → 58%, Dragonkin 70% → 90%. Warrior, Tank and Vampire are within noise; Dragonkin improved (cause not isolated).
Average stage reached, 20 runs/config, ability-only bot: Warrior 5.0, Tank 7.5, Rogue 3.9, Witch 4.0, Fallen Angel 1.0, Kitsune 4.0, Vampire 6.4, Dragonkin 7.3; Tank+Rogue+Kitsune clears 25%.

Findings, stated plainly:
- **Rogue / Witch / Kitsune stall at the stage-4 boss, and solo Fallen Angel dies in stage 1, with this bot — identically in the original game.** The Fallen Angel is a deliberately punishing challenge class and the bot ignores restraints, so this says nothing about a skilled human. Treat as unknown, not as balanced.
- A first sim run showed a large Vampire regression after the card system landed. Bisecting showed it was the bot choosing the new "Cards" menu entry at random, not a game change. With `--cards never` R2 matches the original. With `--cards mixed` cards were initially clearly weaker than abilities, so card damage multipliers were raised ~30% (e.g. Steady Strike 1.0 → 1.3x). Afterwards card-playing bots reach about the same depth for Warrior/Tank/Dragonkin; Vampire card play still trails (Crimson Tithe costs HP, which the bot spends carelessly).
- A real balance pass needs human play.

## Visual review (EMULATED only)
Screens inspected as emulated renders and fixed where faulty: title, setup (right-side class stage), combat, blackout combat, trials, draft (pick and deck mode), boss intro banner and boss art, restraint icons in sidebar/journal, hub, rewards, shop, victory/defeat, element and chain-ring FX. Fixed this pass: sidebar covering the draft and ending screens, hub hint colliding with party cards, ending title width. **Still unverified in real Pygame-ce:** font metrics, text fit, alpha blending, scaling quality, frame timing, all animation feel.

Known visual shortfalls: regular enemies are still the procedural low-poly silhouettes (the concept boards contain boss art and companion pets, not enemy sprites). Bosses use feathered concept-art portraits, not cut-outs. Hit/element FX are simple icon animations. Card hands are shown as menu entries, not as drawn cards in combat.

## Audio
Procedural cues (from V2) and four generated R2 WAVs are wired with a procedural fallback. Numeric checks only. **Nobody has listened to any of it.**

## Not done / needs a real machine
1. `pip install -r requirements.txt && python main.py` and play a full run.
2. Run the 2 erroring tests and the 2 skipped ones.
3. Capture real screenshots of the screens listed above; replace `*_emulated.png` claims with real ones.
4. Listen to every sound; check mix levels.
5. Human QTE/trial playtest at each tier, with attention to input-latency feel.
6. A human balance pass, in particular the Fallen Angel and the stage-4 boss.
