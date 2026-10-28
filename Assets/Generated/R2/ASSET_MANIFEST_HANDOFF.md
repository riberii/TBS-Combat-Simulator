# ASSET_MANIFEST — Chains of the Abyssal Choir R2 Handoff

**Status date:** 2026-10-26  
**Purpose:** Inventory the art/audio files created for the Claude/Codex implementation handoff. This is not a claim that they are integrated into the Pygame game.

## Status definitions

- **GENERATED** — a standalone file was created in this handoff. It still needs a visual review and game integration.
- **REFERENCE ONLY** — a collage/concept board used for mood and composition; do not use directly as a sprite, UI screen, or animation strip.
- **INTEGRATED** — loaded and used by the actual game renderer/system. None of these files are marked integrated yet.
- **VISUALLY VERIFIED** — viewed in a fresh capture from the actual Pygame-ce application at intended in-game scale. None are visually verified yet.

## Style lock: Fallen Angel — Seraph of the Fractured Oath

Dark gothic nun / seraph, violet-black hair, red eyes, silver cross details, fractured halo, layered dark wings, black/violet outfit, red-silver supernatural chains, regal but strained pose. Palette anchors from `ART_BIBLE.md`: abyssal black `#1E1E2E`, deep violet `#7B2CBF`, patent black `#11111B`, silver cross `#D8DEE9`; restraint FX use controlled crimson and violet. The procedural sprite pack is a stylized chibi/placeholder implementation asset, not a replacement for the mature full-body art direction.

## Generated assets

| Path (relative to this folder) | Status | Approx. size | Purpose / integration note |
|---|---|---:|---|
| `characters/fallen_angel/fallen_angel_body_base.png` | GENERATED | 192×224 RGBA | Base body layer; composite behind halo and in front of wings. |
| `characters/fallen_angel/wings_folded.png` | GENERATED | 192×224 RGBA | Standalone restrained/folded wing layer; draw behind body. |
| `characters/fallen_angel/wings_spread.png` | GENERATED | 192×224 RGBA | Standalone spread-wing layer; draw behind body during cast/release. |
| `characters/fallen_angel/fractured_halo.png` | GENERATED | 192×224 RGBA | Separate fractured halo layer. |
| `characters/fallen_angel/chains_overlay.png` | GENERATED | 192×224 RGBA | Transparent overlay intended to be drawn over torso; test compositing before use. |
| `characters/fallen_angel/idle_00.png`…`idle_07.png` | GENERATED | 192×224 RGBA each | Eight subtle idle frames, breathing/halo/wings motion; ready for sheet/GIF slicing. |
| `characters/fallen_angel/fallen_angel_idle_sheet_4x2.png` | GENERATED | 768×448 RGBA | Idle sheet, 4 columns × 2 rows, frames row-major, 192×224 cells. |
| `characters/fallen_angel/fallen_angel_idle.gif` | GENERATED | 8 frames | Preview loop. GIF is for preview; use PNG frames/sheet in Pygame. |
| `characters/fallen_angel/attack_00.png`…`attack_07.png`, `fallen_angel_chain_slash_sheet_4x2.png`, `fallen_angel_chain_slash.gif` | GENERATED | 192×224 per frame | Frame-based chain slash animation, 4×2 sheet and preview GIF. |
| `characters/fallen_angel/fallen_angel_fullbody_starter.png` | GENERATED | 576×672 RGBA | Upscaled layered full-body starter render. |
| `characters/fallen_angel/fallen_angel_portrait_starter.png` | GENERATED | 512×512 RGBA | Character portrait/badge starter. |
| `characters/fallen_angel/FRAME_MAP.md` | GENERATED | text | Frame dimensions, order, recommended durations. |
| `characters/fallen_angel/restrained_00.png`…`restrained_07.png` | GENERATED | 192×224 RGBA each | Restrained idle with animated chains. |
| `characters/fallen_angel/fallen_angel_restrained_sheet_4x2.png` | GENERATED | 768×448 RGBA | Restrained animation sheet; row-major, 192×224 cells. |
| `characters/fallen_angel/fallen_angel_restrained.gif` | GENERATED | 8 frames | Preview loop for restraint state. |
| `vfx/fallen_angel/fallen_angel_chain_cast_sheet_4x2.png` | GENERATED | 768×448 RGBA | Eight-frame cast/chain QTE effect sequence. |
| `vfx/fallen_angel/fallen_angel_chain_cast.gif` | GENERATED | 8 frames | Preview of cast effect; not a substitute for engine timing. |
| `vfx/fallen_angel/fallen_angel_release_sheet_4x2.png` | GENERATED | 768×448 RGBA | Eight-frame partial/full release sequence. |
| `vfx/fallen_angel/fallen_angel_release.gif` | GENERATED | 8 frames | Preview loop; use event-driven one-shot playback in game. |
| `vfx/fallen_angel/fallen_angel_backlash_sheet_4x2.png`, `fallen_angel_backlash.gif` | GENERATED | 8 frames | Restraint-backlash event animation, 4×2 sheet + preview GIF. |
| `vfx/fallen_angel/chain_ring_00.png`…`chain_ring_07.png` | GENERATED | 256×256 RGBA each | Separate chain arc VFX frames. |
| `ui/restraints/restraint_chains.png`, `restraint_halo.png`, `restraint_seal.png`, `restraint_wings.png`, `restraint_lucidity.png`, `restraint_backlash.png`, `restraint_release.png` | GENERATED | 96×96 RGBA each | Seven individual transparent status/event icons; labels must be rendered by game UI. |
| `ui/restraints/restraint_icons_sheet_4x2.png` | GENERATED | 384×192 RGBA | 4×2 icon sheet, 96×96 cells, last cell transparent. |
| `backgrounds/cathedral_of_unheard_hymns_1280x720.png` | GENERATED | 1280×720 RGB | Original procedural gothic cathedral background; 16:9, no embedded labels; leave UI negative space in foreground. |
| `audio/chain_tighten.wav` | GENERATED | 44.1 kHz mono, 16-bit | Synthesized chain-tension cue. |
| `audio/seal_success.wav` | GENERATED | 44.1 kHz mono, 16-bit | Synthesized seal/QTE success cue. |
| `audio/qte_failure.wav` | GENERATED | 44.1 kHz mono, 16-bit | Synthesized QTE failure cue. |
| `audio/resonance_pulse.wav` | GENERATED | 44.1 kHz mono, 16-bit | Synthesized resonance pulse. |
| `README_ASSET_PACK.md` | GENERATED | text | Import and animation notes. |

| `vfx/elements/{flame,frost,storm,verdant,umbral,radiant}_00.png`…`_05.png`, `*_sheet_3x2.png`, `*.gif` | GENERATED | 128×128 per frame | Six elemental effect families, six-frame loop previews and 3×2 sheets. |
| `items/{potion,lucid_draught,choir_shard,sealed_scroll,silver_key,bolt_cutters,relic_ring}.png` | GENERATED | 96×96 RGBA | Individual transparent inventory icon starters, no text baked in. |
| `cards/card_frame_{common,rare,epic,fallen_angel_signature}.png` | GENERATED | 256×384 RGBA | Four blank frame tiers; render card text/cost/effects in Pygame. |
| `companions/spectral_owl_starter.png` | GENERATED | 256×256 RGBA | Standalone spectral owl companion starter. |
| `ui/panels/gothic_panel_512x256.png` | GENERATED | 512×256 RGBA | Translucent panel starter; use nine-slice scaling to preserve corners. |

## Reference-only moodboards

The following are large concept-board images with many fused panels, text, or inconsistent example designs; treat them only as visual references, not production resources:

- `a_large_detailed_concept_art_asset_sheet_collage.png`
- `a_large_detailed_concept_art_asset_sheet_and_deve.png`
- `a_dark_polished_concept_art_asset_board_and_devel.png`
- `a_detailed_cinematic_high_resolution_concept_art.png`
- `a_wide_detailed_concept_art_asset_pack_and_design.png`
- `a_wide_composite_promotional_asset_sheet_image_wi.png`
- `a_wide_detailed_collage_style_concept_art_asset_s.png`
- `wide_detailed_game_concept_asset_sheet_collage_in.png`
- All collage boards supplied in `rework.zip/Assets/`

## Animation construction notes

Animation is assembled from layered transparent components and deterministic frame variations: body/base, wings (folded/spread), halo, chain overlay, and event-specific ring/glow effects. PNG sprite sheets are row-major with fixed cell dimensions; the corresponding GIFs are previews. For Pygame, load sheets or individual PNGs, slice by exact cell size, cache surfaces, and use elapsed time rather than frame-count-per-tick. Implement non-looping playback for cast/release actions, loop idle, reset animations on scene changes, and respect reduced-motion settings.

## Known limitations

- This pack is a useful procedural starter pack in a stylized chibi/graphic treatment; it is not high-end hand-painted production character art.
- The code-generated frames use a consistent model, but should be reviewed at target scale and refined before shipping.
- Nothing in this manifest has been hooked into `ui/renderer.py` or actual game events yet.
- WAV cues are synthesized and numerically generated but not auditioned by listening.
- Current project checkpoint reports say Pygame-ce was not available in the earlier environment; fresh rendering and testing are still required.
