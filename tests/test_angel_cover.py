"""The Fallen Angel's standee and portrait must have no bare skin left in the chest region (tools/cover_angel.py)."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tools.cover_angel import ART, REGIONS, _skin_mask, cover


class AngelCoverTests(unittest.TestCase):
    def _skin_in_region(self, rel: str) -> int:
        im = Image.open(ART / rel).convert("RGBA")
        rgb = np.asarray(im).astype(np.float32)[..., :3]
        region = Image.new("L", im.size, 0)
        ImageDraw.Draw(region).polygon(REGIONS[rel], fill=255)
        return int((_skin_mask(rgb) & (np.asarray(region) > 0)).sum())

    def test_no_bare_skin_left_in_chest_region(self):
        for rel in REGIONS:
            with self.subTest(art=rel):
                self.assertLess(self._skin_in_region(rel), 60, "chest region still shows skin-coloured pixels")

    def test_cover_is_idempotent(self):
        import shutil, tempfile
        with tempfile.TemporaryDirectory() as td:
            for rel in REGIONS:
                dst = Path(td) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ART / rel, dst)
                with Image.open(dst) as a:
                    before = a.tobytes()
                cover(dst)
                with Image.open(dst) as b:
                    self.assertEqual(before, b.tobytes(), "second pass must change nothing")

    def test_files_keep_size_and_alpha(self):
        with Image.open(ART / "models/fallen_angel.png") as m:
            self.assertEqual((m.size, m.mode), ((305, 460), "RGBA"))
        with Image.open(ART / "portraits/fallen_angel.png") as p:
            self.assertEqual(p.size, (256, 256))


if __name__ == "__main__":
    unittest.main()
