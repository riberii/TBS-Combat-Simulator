# Codex handoff — read this first (written 2026-10-26)

Use this together with the full master prompt. It tells you what is already done so you do not redo it, and what could not be checked.

## Ground rules
- Keep the game in pygame-ce. No rewrite, no new engine, no feature bloat.
- Branch `polish-pass-checkpoint-2026-10-26` is the recovery point from before these changes. Do not delete it.
- The previous session had **no pygame-ce, no pytest, no display and no audio device**. Everything marked Unverified below has never been rendered or heard.

## Step 0 (do first, in this order)
1. `pip install -r requirements.txt pytest`
2. `python -m compileall -q .`, `python -m pytest tests/ -q`, `python tools/validate_content.py`, `python tools/smoke_test.py`
3. Put the real numbers into `TEST_REPORT.md` (expected: 93 tests collected; the earlier "83 passed, 73 subtests" figure was not re-run). If the 2 tests that errored without pygame (`test_all_skins_palette_changes_render_model`, `test_tutorial_sparring_fight_launches_for_all_classes`) still fail with real pygame, fix them first.
4. Capture fresh screenshots (title, party setup, combat with 1/2/3 heroes, boss, QTE, skill tree, settings, victory, defeat). The ones in `QA/screenshots/` are from 2026-10-24 and out of date.

## Already done (code + tests; visually/audibly unverified)
- Notification policy unified: `TOAST_MAX = 4`, 340px, docs and tests agree.
- Five new sounds (`enemy_swing`, `ward`, `death`, `victory`, `defeat`) in `systems/audio_system.py`. Numerically clean, **never listened to**: tune by ear with `python systems/audio_system.py`.
- Saves: a damaged slot is quarantined as `slotN.json.corrupt-<ms>` before a new save overwrites it.
- `GameState.claim_victory()` is idempotent per wave.
- Title screen: subtitle plate and per-hero class labels (`TITLE_PREVIEW_X0/DX/Y` in `main.py`). **Check on screen.**
- Floating damage numbers capped (`MAX_FLOATERS = 24`). **Check on screen.**
- Combat fuzz (260 fights, all classes) and input-spam checks found no logic bugs; kept as `tests/test_combat_robustness.py`.
- Version label standardised on V2.0.

## Still to do (priority order from the master prompt)
1. HUD/layout — see the findings table in `QA/VISUAL_REVIEW_2026-10-26.md` (empty tall left panel, small heroes, low-contrast hints, dark class previews).
2. Character silhouettes and environment depth.
3. Animation and VFX timing.
4. Audio balance by ear.
5. Release docs: update `QA/RELEASE_READINESS.md` and `RELEASE_ACCEPTANCE_CHECKLIST.md` only with evidence you actually produced.

## Honesty rules
Use the statuses Implemented / Tested / Visually verified / Audio verified / Unverified / Blocked / Not implemented. Never mark something Visually or Audio verified unless a person looked at or listened to it.
