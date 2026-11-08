# Polish Pass Status — 2026-10-26 (checkpoint 7, environment-limited)

**Environment:** Python 3.12.3 + NumPy 2.4.4. `pygame-ce` and `pytest` were NOT installable (no network), so nothing could be rendered, played, or heard in this session.

## Safety
- Recovery branch: `polish-pass-checkpoint-2026-10-26` (created from the working tree HEAD; `main` untouched in history).
- Pre-existing uncommitted changes in `CHANGELOG_V2.md`, `README.md`, `RELEASE_ACCEPTANCE_CHECKLIST.md`, `TEST_REPORT.md` are line-ending only (CRLF); `git diff --ignore-space-at-eol` is empty. Preserved as-is.

## Baseline (actual results)
| Check | Result |
|---|---|
| `python -m compileall -q .` | PASS |
| `python tools/validate_content.py` | PASS (content/gameplay imports only; rendering not checked) |
| `python tools/smoke_test.py` | PASS with import-only pygame stub (seed 20261024, 14 turns, score 881) |
| `python -m unittest discover -s tests` | Baseline 83 tests collected (93 after checkpoint 2–7 additions); 2 errors + 2 skipped. Both errors are the pygame stub (`Surface()`, `pygame.mixer`), not code defects. Full result needs real pygame-ce — **Unverified here**. |

## Implemented this checkpoint
- **Notification policy unified** (code was already authoritative: `TOAST_MAX = 4`, `TOAST_MAX_W = 340` in `ui/vfx.py`).
  - `ART_AND_ANIMATION_GUIDE.md`: "five" → four toasts, 340px.
  - `QA/RELEASE_READINESS.md`: "380px" → 340px.
  - Tests tightened: cap test now asserts `== TOAST_MAX` (was `<= 5`), width test uses `TOAST_MAX_W`, max-stack test uses `TOAST_MAX + 1`. Status: **Implemented; cap test Tested** (runs under stub); width/stack tests **Unverified** (need pygame fonts).

## Checkpoint 2 — audio (`systems/audio_system.py`)
Audit (NumPy only, sample properties): all 15 original SFX were already unclipped, DC-free and click-free. The gap was that `victory`, `defeat`, `death`, `ward` and `enemy_swing` were only *aliases* of unrelated cues (`qte_success`, `qte_fail`, `ui_confirm`, `impact`), so key moments had no sound of their own.
- **Implemented:** five new synths — `enemy_swing` (dark falling whoosh + thump, panned right→left), `ward` (swelling glassy shimmer for barriers), `death` (heavy falling tone + dust), `victory` (short open-fifth bell fanfare), `defeat` (slow descending minor sigh). Their placeholder aliases were removed; `SFX_NAMES` follows `_SFX_SYNTHS` automatically. The call sites in `main.py` are unchanged.
- **Measured (Tested):** peaks 0.78–0.86, no clipping, DC < 0.002, no edge clicks, all ≤ 1.65 s.
- **Music loops (Tested, numeric only):** all three levels wrap with a seam step smaller than an ordinary sample step at 22.05 kHz and 44.1 kHz; peaks 0.69–0.79. No change made to the music.
- **New tests (+3):** own-generator check for the five cues; peak/DC/click/length check on every SFX over 3 seeds; loop-seam check for all BGM levels.
- **Audio verified: NO.** These numbers show the sounds are technically clean, not that they sound good or are well balanced against the music. Needs listening on real speakers; run `python systems/audio_system.py` to audition every cue, and tune gains/pitches by ear.

## Checkpoint 3 — reliability (no pygame needed; verified by experiment)
- **Saves (`systems/save_system.py`) — Implemented, Tested.** Experiment showed a corrupt slot file was silently overwritten by the next save (the good `.bak` was already protected). Now a non-empty damaged slot is copied to `slotN.json.corrupt-<ms>` first (newest 3 kept, best effort, never blocks saving). Load of a corrupt slot already left the file untouched. Note: `delete()` does not remove quarantined copies (deliberate: evidence is kept).
- **Rewards (`core/game_state.py`) — Implemented, Tested.** `claim_victory()` was not idempotent (a second call on the same wave paid again: gold 155 → 190). The app was only protected by a UI flag (`victory_claimed`). The method now returns `[]` for a wave it already paid; a new or replaced wave pays normally. The marker is transient and not saved, so the save format is unchanged.
- **New tests (+2):** quarantine/backup behaviour; no double claim. Suite is now 88 tests, still 2 pygame-only errors.
- Settings corruption preservation and profile-store backup already had tests; not re-verified here beyond the unit run.

## Checkpoint 5 — screenshot review and title screen
- Viewed four archived screenshots (older build); findings and statuses are in `QA/VISUAL_REVIEW_2026-10-26.md`. The prompt's "overlapping notifications" screenshot (`boss_trio`) was a real old defect, already addressed by the 4-toast / 340px policy, but needs re-capture.
- **Implemented (`main.py`, title screen):** subtitle now on a dark plate with brighter ink; class labels sit under each hero via shared `TITLE_PREVIEW_X0/DX/Y` constants (hero placement uses the same constants). Test added for the layout maths. **Visually Unverified** — nothing could be rendered.

## Checkpoint 6 — combat robustness (no pygame needed; real `CombatSystem`)
- **Fuzz results (Tested):** 260 seeded fights over all 8 classes, parties of 1–3, Easy/Normal/Hard, stages 1/3/4/6/12: no exceptions, no HP/MP/stamina outside 0..max, every fight reached Victory or Defeat. Separately, 18,683 probes sending every key during RESOLVE/ENEMY changed nothing, and keys/updates after the fight ended changed nothing. No combat bug was found, so no combat code was changed.
- **Implemented:** `tests/test_combat_robustness.py` (2 tests, ~0.1 s) keeps a small seeded version of both checks.
- **Tooling fix:** `tools/headless_bootstrap.py`'s pygame stub now maps key names like the stub in `test_save_and_progression.py` (it returned "101" instead of "e"), so results no longer depend on which test file is imported first. Checked in both orders.
- **Limits:** the fuzz drives combat logic only. It says nothing about animation timing, rendering, or whether QTE prompts look right.

## Checkpoint 7 — effect bounds (`ui/vfx.py`)
- **Audit (code reading):** particles were already bounded (40 per burst, 400 total); toasts (4) and alerts (3) were bounded. Floating damage/heal numbers had no count cap and their vertical stacking grew without limit when many hits landed on one spot.
- **Implemented, Tested:** `MAX_FLOATERS = 24` (oldest dropped) and `FLOATER_STACK_MAX = 4` steps of stacking. Reduced motion already suppressed particles, shake, lunges and flashes; a test now confirms it still shows damage numbers (information is kept).
- **Tests (+2):** 200 events stay within the caps and everything expires after `update`; reduced-motion behaviour. Suite: 93 collected, same 2 pygame-only errors.
- **Not verified:** how crowded 24 numbers look on screen; the cap value may need tuning after a visual check.

## Documentation inconsistencies
- Test count: **resolved** — current reports say 83 (+73 subtests), matching the 83 collected at baseline; the older 81 in `CHANGELOG_V2.md` is now annotated as historical. Subtest count still needs real pygame to confirm. Collected count here is 83, which matches. Subtest count unverifiable without pygame.
- Version label: **resolved** — standardised on V2.0 (code `TITLE`, title screen and release packager all say V2.0; no git tags; V3.0 was only a docs pass label).

## Not started (needs a machine with pygame-ce)
Character art, backgrounds, menu/HUD layout, animation/VFX, audio mixing. Changing these blind would risk regressions with no way to render or listen. Status: **Not implemented / Unverified**.

## Next steps
1. `pip install -r requirements.txt pytest`, then run the four baseline commands and update `TEST_REPORT.md` with real numbers.
2. Capture fresh screenshots (the archived ones are stale); `toast_stack` is a stress fixture of the 5-toast era. Then review the table in `QA/VISUAL_REVIEW_2026-10-26.md`.
3. Then proceed in priority order: HUD/menu → characters/environments → VFX → audio.
4. Audio verification requires physical listening: **Audio verified: no**.
