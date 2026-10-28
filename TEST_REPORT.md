# Test Report — V2.0 Final Release Candidate

## Environment

- OS: Windows 11
- Python: 3.14.2 (64-bit)
- pygame-ce: 2.5.6 / SDL 2.32.10
- NumPy: 2.4.4 installed
- pytest: 9.1.1 installed

## Test Execution Summary

Every automated verification command was executed directly in the project workspace:

```powershell
python -B -m compileall -q .
$env:SDL_VIDEODRIVER="dummy"; $env:SDL_AUDIODRIVER="dummy"; python -m pytest tests/ -v
python -B tools/validate_content.py
python -B tools/smoke_test.py
python tools/package_release.py
```

### Verification Results

1. **Syntax & Compilation (`compileall`)**:
   - Status: **PASS** (exit code 0)
   - Zero syntax errors, circular imports, or invalid modules across the entire codebase.

2. **Automated Unit & Regression Suite (`pytest` & `unittest`)**:
   - Status: **PASS** (83 passed, 73 subtests passed in 2.66s)
   - Zero regressions across the entire suite.
   - Verified features in `tests/test_v2_features.py` and `tests/test_save_and_progression.py`:
     - **All 24 Skill Tree Nodes**: Every node across all 8 classes maps to a live runtime hook (rage_regen, sta_regen, crit_bonus, combo_cap, spell_mult, mp_regen, max_spirit, fox_mult, decoy_extra, blood_mult, veil_bonus, heat_cap, max_hp, atk_mult, def_mult, break_bonus, lucidity_start).
     - **All 5 Companion Passives**: Raven (+20% gold), Wisp (+5 MP/STA round start), Hound (+10% ATK), Beetle (+3 DEF), Sprite (heal lowest HP hero +5) active in live simulation.
     - **Honest Daily Task Evaluation**: Verified exact success conditions for reaching stages, surviving without merchant heals, elite/boss kills, remaining above HP threshold, and arena rounds without deaths. The previous `stage >= 2` shortcut is completely removed.
     - **Mode Persistence**: Verified `run_mode` ("story", "endless", "boss_rush", "arena") persists across `to_dict()` and `from_dict()` serialization.
     - **Profile Corruption Safety**: Corrupted profile JSON is automatically preserved to `.corrupt.<timestamp>.bak` with a warning, and a fresh default profile is created without data loss.
     - **Regional Shop Pricing**: Validated price scaling across regions (`oath_road`, `cathedral`, `sanctum`, `choir_heart`, `abyss`) and class affinities.
     - **Cosmetic Skin Palettes**: Tested all 4 skin attire themes across all 8 classes; verifies accent and trim colors correctly update the render models.

3. **Content & Cross-Reference Validation (`validate_content.py`)**:
   - Status: **PASS** (exit code 0)
   - Playable classes: 8 (Warrior, Tank, Rogue, Witch, Fallen Angel, Kitsune, Vampire, Dragonkin).
   - Unique battlefield sprites: 8 distinct procedural vector silhouettes.
   - Abilities validated: 37 total across the full roster.
   - Enemy archetypes: 8 (Beast, Void, Nature, Construct, Cultist, Hunter, Undead, Cinder).
   - Boss profiles: 4 distinct boss profiles with multi-phase intent cycles.
   - Authored halls: 12 with rich atmospheric introductions.

4. **Deterministic Headless Smoke Test (`smoke_test.py`)**:
   - Status: **PASS** (exit code 0)
   - Result: `seed=20261024, stage=1, turns=14, score=881`.
   - Party HP after encounter: 105/120; rewards: `Victory! +35 gold, +40 XP each`.
   - Save/load and idempotent local leaderboard insertion verified without mutating live player saves.

5. **Release Packaging & Extracted Verification (`package_release.py`)**:
   - Status: **PASS** (exit code 0)
   - Package: `Chains_of_the_Abyssal_Choir_V2.0_Release.zip` (clean archive, 67 files, 0 `.git` entries, 0 cache entries, 0 personal saves).
   - Extracted package verification: `pytest`, `validate_content.py`, and `smoke_test.py` all pass from the freshly extracted archive.

## Visual & Layout Redesign (Matching Authored Reference Images)

- **Warrior (Image 4 Reference)**:
  - Art Nouveau style, silver/white flowing hair with golden butterfly hair clip.
  - Ornate silver plate armor with gold filigree breastplate, tiered pauldrons, flowing white/black cape.
  - Radiant golden two-handed holy blade with momentum light trail.
  - Accent/trim skin palette applied to breastplate, filigree, and cape lining.

- **Tank (Image 1 Reference)**:
  - Blonde/light brown hair, immaculate white and gold enameled heavy plate armor.
  - Sacred cross tabard with pink/white silk backing and gold chain tassels.
  - Massive winged pauldrons and broad protective stance.
  - Colossal holy greatsword with deep blue sapphire enamel inlay and gold filigree.
  - Accent/trim skin palette applied to tabard, enameling, and pauldrons.

- **Witch (Image 2 Reference)**:
  - Chocolate brown hair with soft bangs, cute furry raccoon ears with pink/white inner fluff.
  - Large wide tattered witch hat with ragged frayed brim, twin pale flower pins, and zig-zag lightning tear.
  - Off-the-shoulder grey sweater dress with keyhole chest cutout and ribbon ties on sleeves.
  - Striped thigh-high stockings (alternating dark charcoal and light grey) with garter strap.
  - Fluffy white fur boot cuffs above Mary-Jane shoes with heart buckles.
  - Grand fluffy striped raccoon tail billowing and swaying behind her.
  - Accent/trim skin palette applied to sweater knit, ribbons, and hatband.

- **Fallen Angel (Image 5 Reference)**:
  - Long silver/white hair with lilac tint, glowing luminous purple eyes.
  - Curved obsidian dragon horns framing the head with glowing violet runes.
  - Segmented spiky dragon/demon tail coiling around her legs.
  - 3-tier feathered and clawed wing system with floating soul-fire motes.
  - Gothic black armored corset and glossy thigh-high boots with restraint chains.
  - Accent/trim skin palette applied to wing rims, runes, and halo.

- **Kitsune & Dragonkin (Image 3 Reference)**:
  - Dragonkin: Pure white hair, crimson dragon horns, shrine-maiden miko robes, pleated red hakama, sinuous tail, and floating furnace embers.
  - Kitsune: Flowing amber/cream hair, fox ears, grand billowing fox tail, dusty-rose off-shoulder kimono with crimson obi, and lace-up boots.
  - Accent/trim skin palette applied to robes, obi, and spirit flames.

- **Rogue & Vampire**:
  - Rogue: Asymmetrical hood, split coat, neon green eye slits, paired daggers; skin palette tints coat and blade glow.
  - Vampire: High collar, wine-red coat tails, floating blood sigil fragments, silver rapier; skin palette tints coat and sigil glow.

## Note on Desktop / GUI Verification

The verification commands above were run in a headless environment with dummy video/audio drivers (`SDL_VIDEODRIVER="dummy"` and `SDL_AUDIODRIVER="dummy"`). Functional rendering paths are exercised via smoke test and headless integration tests. Physical display color calibration and speaker listening tests remain owner-side checks.


## Final V2.0 Implementation Pass — 2026-10-25 (Latest)

### B-Series Bug Fixes & Sparring Fix Verified (All 83 Tests Passing)

| ID  | Fix | Status |
|-----|-----|--------|
| B1  | All 24 skill-tree nodes wired to live runtime stat hooks (`rage_regen`, `sta_regen`, `crit_bonus`, `combo_cap`, `spell_mult`, `mp_regen`, `max_spirit`, `fox_mult`, `decoy_extra`, `blood_mult`, `veil_bonus`, `heat_cap`) | ✅ VERIFIED |
| B2  | All 5 companion passives (Raven, Wisp, Hound, Beetle, Sprite) integrated into `CombatSystem` round-start/end and `GameState.claim_victory()` | ✅ VERIFIED |
| B3  | Skin palette runtime application wired into all 8 class renderers via `SpritePainter`; `Character.skin_key` populated from `state.skin` | ✅ VERIFIED |
| B4  | Honest daily task evaluation with explicit per-template success predicates; `stage >= 2` shortcut removed; metrics tracked in `GameState` | ✅ VERIFIED |
| B5  | Regional shop pricing wired into live `Shop()` constructor via `_region_for_stage(stage)` mapping | ✅ VERIFIED |
| B6  | NPC dialogue system (`Screen.DIALOGUE`, hub `[T]` key) with Archivist Voren, Sister Moira, Hollow Peddler | ✅ VERIFIED |
| B7  | Mode persistence — exact `run_mode` ("story", "endless", "boss_rush", "arena") survives `to_dict()` / `from_dict()` and `_restore_loaded_state()` | ✅ VERIFIED |
| B8  | Profile corruption safety — corrupt JSON backed up to `.corrupt.<timestamp>.bak` with `warnings.warn`; fresh default profile created | ✅ VERIFIED |

### Hero Character Redesigns (Vector Art — Headless, Not Physically Inspected)

All 8 hero classes have been redesigned in `ui/renderer.py` matching the supplied anime character reference images:

| Class | Key Design Features |
|-------|-------------------|
| Warrior | Art Nouveau silver hair, gold butterfly ornament, gold filigree armor, radiant golden two-handed blade |
| Tank | Platinum blonde hair, white/gold enameled plate, sacred cross tabard, colossal greatsword with deep blue sapphire inlay |
| Witch | Raccoon ears, large tattered grey hat with flower pin & lightning tear, chocolate brown hair, off-shoulder keyhole sweater dress, striped thigh-high stockings with garter, fluffy boot cuffs, Mary-Jane shoes, grand fluffy striped raccoon tail |
| Fallen Angel | Silver-white hair with lilac tint, glowing violet eyes, curved obsidian dragon horns, 3-tier feathered/clawed wings, segmented barbed dragon tail, floating soul-fire embers |
| Kitsune | Cascading amber/orange fox hair, pointed fox ears with cream tufts, off-shoulder dusty rose kimono, crimson obi, white slip, bare thighs, glossy dark lace-up thigh-high boots, grand fluffy amber tail, ambient azure foxfire |
| Dragonkin | Pure white hair, crimson dragon horns, shrine-maiden miko robes, pleated red hakama, sinuous scaled tail, furnace embers |
| Rogue | Asymmetric hood, split coat, neon-green eye slits, paired daggers, palette-tinted coat and blade glow |
| Vampire | High collar, wine-red coat tails, floating blood sigil fragments, silver rapier, palette-tinted coat and glow |

### Package Verification
- **Release ZIP:** `Chains_of_the_Abyssal_Choir_V2.0_Release.zip` — clean archive, excludes `.git`, `__pycache__`, `.pytest_cache`, personal saves
- **SHA-256:** Recorded in `SHA256SUMS.txt` (see parent directory)
- **Extracted verification:** `pytest`, `validate_content.py`, `smoke_test.py` all pass from freshly extracted archive

## Polish pass environment check — 2026-10-26 (partial; pygame-ce and pytest unavailable)

- Python 3.12.3, NumPy 2.4.4. `pygame-ce` could not be installed (no network), so the figures above were **not re-run** here.
- `python -m unittest discover -s tests`: baseline 83 tests collected (matches the 83 reported above); after this pass 93 collected. 2 tests error only because pygame is absent (`test_all_skins_palette_changes_render_model`, `test_tutorial_sparring_fight_launches_for_all_classes`); 2 are skipped. No pass count or subtest count is claimed for this environment.
- `compileall`, `tools/validate_content.py` (content/imports only) and `tools/smoke_test.py` (import-only pygame stub) pass.
- Rerun the full suite with real pygame-ce before treating any number here as current.
