"""Render contact sheets of the R2 animations *as ui.r2_assets slices them* (PIL stand-in, not pygame-ce).

Usage: python tools/r2_asset_preview.py [out_dir]
These sheets prove the cell slicing/ordering of the real PNGs. They are NOT in-game screenshots.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image, ImageDraw  # noqa: E402


def main(out: Path) -> list[Path]:
    import pil_pygame_shim
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with mock.patch.dict(sys.modules, {"pygame": pil_pygame_shim.make_module()}):
        from ui import r2_assets as r2
        lib = r2.AssetLibrary()
        groups = {"elements": [k for k in r2.ANIMATIONS if k.startswith("el_")]}
        for name, keys in groups.items():
            cw = max(r2.ANIMATIONS[k].cell[0] for k in keys)
            chh = max(r2.ANIMATIONS[k].cell[1] for k in keys)
            n = max(r2.ANIMATIONS[k].frame_count for k in keys)
            sheet = Image.new("RGBA", (n * cw + 90, len(keys) * chh), (28, 22, 40, 255))
            d = ImageDraw.Draw(sheet)
            for row, key in enumerate(keys):
                d.text((4, row * chh + 4), key, fill=(255, 220, 120, 255))
                for i, frame in enumerate(lib.sheet_frames(key) or []):
                    sheet.alpha_composite(frame.im, (90 + i * cw, row * chh))
            path = out / f"{name}.png"
            sheet.convert("RGB").save(path)
            written.append(path)
    return written


if __name__ == "__main__":
    for p in main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "QA" / "r2_previews"):
        print("wrote", p)
