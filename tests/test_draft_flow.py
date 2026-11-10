"""Card-draft screen flow (pick / skip / forge / back) driven through GameApp under the DEV-ONLY pygame emulation.

This is NOT real Pygame-ce; it checks the game logic of the draft screens only.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DraftFlowTests(unittest.TestCase):
    def test_draft_flow_under_emulation(self):
        p = subprocess.run([sys.executable, str(ROOT / "tools" / "draft_flow_check.py")], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        out = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "{}"
        self.assertEqual(p.returncode, 0, f"{out}\n{p.stderr[-1500:]}")
        self.assertTrue(all(json.loads(out).values()), out)


if __name__ == "__main__":
    unittest.main()
