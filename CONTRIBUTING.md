# CONTRIBUTING

## Setup
```bash
python3 -m pip install -r requirements.txt     # pygame-ce, numpy
python3 main.py
```

## Before you push
```bash
python3 -m compileall -q .
python3 tools/validate_content.py
python3 tools/smoke_test.py
python3 -m unittest discover -s tests         # 2 tests need real pygame-ce; see TEST_REPORT.md
python3 tools/balance_sim.py --runs 10        # tripwire for crashes / stuck fights / big shifts
```
With pygame-ce installed, the 2 stub-only errors should pass; if they do not, that is a real bug.

## Rules of the house
- **Never claim a feature works that no test or run proved.** Say which level proved it (static / stub / emulated / real).
- New skill node → add its runtime hook and a test. New card → `systems/card_system.py` data + `validate_cards()` must stay clean. New restraint trial → add a `TrialDef`, give it a `solution_script()`; the solvability and anti-spam tests then cover it automatically.
- Anything saved must be declared in `__init__` (the save system restores only attributes that already exist).
- All randomness in combat goes through the seeded combat RNG.
- Assets: put them under `Assets/`, load through `ui/assets.py` (fail-soft, path-jailed), record the source in `Assets/Art/ART_SOURCES.json` or `ASSET_MANIFEST_R2.md`, and keep statuses honest (GENERATED / REFERENCE ONLY / INTEGRATED / VISUALLY VERIFIED).
- `tools/devpygame` and `tools/render_preview.py` are dev-only emulation; their PNGs are named `*_emulated` and are never evidence of real rendering.
