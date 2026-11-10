"""Numerical checks of the shipped R2 WAV effects (clipping, DC offset, edge clicks, length) and the loader.

These are signal checks only - nobody has listened to these files; do not read a pass as 'sounds good'.
"""
from __future__ import annotations

import unittest

import numpy as np

from systems.audio_system import FILE_SFX, R2_AUDIO_DIR, load_wav_stereo


class R2AudioNumericTests(unittest.TestCase):
    def test_files_exist_and_load_stereo_at_target_rate(self):
        for name, fname in FILE_SFX.items():
            with self.subTest(sfx=name):
                self.assertTrue((R2_AUDIO_DIR / fname).is_file())
                for rate in (44100, 22050, 48000):
                    d = load_wav_stereo(R2_AUDIO_DIR / fname, rate)
                    self.assertEqual(d.ndim, 2)
                    self.assertEqual(d.shape[1], 2)
                    self.assertAlmostEqual(len(d) / rate, 1.0, delta=0.5)

    def test_signal_quality(self):
        for name, fname in FILE_SFX.items():
            with self.subTest(sfx=name):
                d = load_wav_stereo(R2_AUDIO_DIR / fname, 44100)
                self.assertTrue(np.isfinite(d).all())
                peak = float(np.abs(d).max())
                self.assertGreater(peak, 0.05, "silent")
                self.assertLess(peak, 0.99, "clipping risk")
                self.assertLess(abs(float(d.mean())), 0.01, "DC offset")
                self.assertLess(float(np.abs(d[:8]).max()), 0.02, "click at start")
                self.assertLess(float(np.abs(d[-8:]).max()), 0.02, "click at end")
                self.assertLess(float(np.abs(np.diff(d[:, 0])).max()), 0.6, "discontinuity inside the sample")

    def test_bad_files_raise_instead_of_returning_garbage(self):
        import tempfile, wave, os
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "x.wav")
            with wave.open(p, "wb") as w:
                w.setnchannels(1); w.setsampwidth(1); w.setframerate(8000); w.writeframes(b"\x80" * 50)
            with self.assertRaises(ValueError):
                load_wav_stereo(p, 44100)
            with self.assertRaises(Exception):
                load_wav_stereo(os.path.join(td, "missing.wav"), 44100)


if __name__ == "__main__":
    unittest.main()
