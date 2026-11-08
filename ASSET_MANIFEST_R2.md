# ASSET_MANIFEST_R2

Status words: **GENERATED** (file exists), **REFERENCE ONLY** (not used by the game), **INTEGRATED** (loaded by game code), **VISUALLY VERIFIED** (seen in a *real* Pygame-ce capture). **Nothing is VISUALLY VERIFIED** — only emulated renders were viewed.

| Path | Status | Used by |
|---|---|---|
| `Assets/Art/models/*.png` (8 classes) | INTEGRATED | battle/hub/title/setup standees (cut from concept boards; the Fallen Angel's chest is covered by `tools/cover_angel.py`) |
| `Assets/Art/portraits/*.png` (8) | INTEGRATED | party cards, class stage (Fallen Angel portrait also covered) |
| `Assets/Art/backgrounds/*.jpg` (13) | INTEGRATED | stage backgrounds via `background_for_stage` |
| `Assets/Art/bosses/boss_*.png` (4) | INTEGRATED | boss combat art, boss intro banner |
| `Assets/Art/bosses/vael_banner.png` | GENERATED, unused | — |
| `Assets/Art/cards/*.png` (9) | INTEGRATED | draft screen card frames/faces (not yet in combat) |
| `Assets/Art/fx/chain_ring_*.png` | INTEGRATED | restraint apply / break / lucidity-loss rings |
| `Assets/Art/fx/` others, `Assets/Art/icons/*`, `Assets/Art/companions/snow_owl.png` | GENERATED, unused | — |
| `Assets/Generated/R2/vfx/elements/*_sheet_3x2.png` (flame, frost, storm, radiant, umbral) | INTEGRATED | element hit effects |
| `…/elements/verdant_*` | GENERATED, unused | no verdant damage type |
| `Assets/Generated/R2/ui/restraints/restraint_*.png` | INTEGRATED | sidebar + journal restraint icons |
| `Assets/Generated/R2/audio/*.wav` (4) | INTEGRATED, numerically checked, **not listened to** | restraint/trial/card event sounds |
| `Assets/Generated/R2/characters/fallen_angel/*`, `…/vfx/fallen_angel/*` | REFERENCE ONLY | low-poly chibi body clashes with the new art; sheet geometry is still tested |
| `Assets/Generated/R2/{cards,items,companions,backgrounds}`, `ui/panels` | GENERATED, unused | — |
| `Assets/ASSET_MANIFEST_HANDOFF.md` | REFERENCE | original handoff inventory |

The concept boards (`More Assets 1–4`) are source material only and are **not shipped** in the release ZIP.
