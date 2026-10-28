# Visual Review — archived screenshots (2026-10-26)

**Scope and limits.** I viewed four PNGs in `QA/screenshots/` (title, boss_trio, combat_baseline_archive, toast_stack). They are dated 2026-10-24, so they show an *older build*, not the current code (the title capture lacks the Sanctum/daily badge that `main.py` now draws). No fresh capture was possible (no pygame-ce in this environment). Everything below is **Reviewed on archived images only; current build Unverified**.

## Findings
| # | Screen | Finding | Status |
|---|---|---|---|
| 1 | `boss_trio` | Five oversized toasts cover the boss card ("Vael, the Silent Seraph" name and HP text). This is the overlap the master prompt mentions, and it is a real old defect, not a fixture. The later `toast_stack` capture already uses smaller text and sits above the enemy cards, and the current code caps toasts at 4 (`TOAST_MAX`, 340px). | Fixed in code earlier; **re-capture needed** |
| 2 | `toast_stack` | Shows 5 toasts, but policy is 4, so the image is stale. Toast text is dim grey on dark; may be a mid-fade frame, but contrast should be checked at full alpha. | **Unverified** |
| 3 | combat (all) | The left "Past Actions / Bound" panel is ~550px tall and mostly empty, while heroes are only ~85–100px tall and enemies ~140px. The arena feels small and the left strip wastes space. Suggest: shorten the panel to its content or enlarge the heroes (without shrinking the HUD). | Not implemented (needs visual iteration) |
| 4 | combat | Bottom input hint and the "RAGE 0/100" label are low-contrast against the dark panels. | Not implemented |
| 5 | `title` | Subtitle "V2.0 · A descent in turns" was grey text over the rose window and nearly unreadable. | **Implemented** (dark plate + brighter ink in `main.py`); visually **Unverified** |
| 6 | `title` | The eight class names were one centred string that did not line up with the heroes above them. | **Implemented** (one label under each hero, using the same x constants as the heroes; layout unit test added); visually **Unverified** |
| 7 | `title` | Boss silhouette's wing tip touches the menu panel edge; the Rogue, Vampire and Dragonkin previews are dark against the floor and hard to read at 0.52 scale. | Not implemented |

## Next visual steps (on a machine with pygame-ce)
1. Re-capture all screens with the current build and compare with this table.
2. Check fixes 5 and 6 on screen; adjust the plate padding and label colour if needed.
3. Try findings 3, 4, 7 one at a time, with before/after captures.
