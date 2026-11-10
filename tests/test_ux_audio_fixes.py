"""Regression checks for the action/QTE/audio fixes in Abyssal Choir.

Run with: python -m unittest discover -s tests -v
Requires the project's requirements.txt (NumPy is used by procedural sound tests).
"""
from __future__ import annotations

import unittest

import numpy as np

from systems.audio_system import AudioSystem, _SFX_SYNTHS, _render_level1, _render_level2, _render_level3
from systems.qte_system import ANGEL_WORDS, TimingQTE, TypingQTE


class TypingQTETests(unittest.TestCase):
    def test_exact_word_succeeds(self) -> None:
        qte = TypingQTE("chains", limit=8.0)
        for char in "chains":
            qte.handle_key(char, char)
        self.assertTrue(qte.done)
        self.assertTrue(qte.success)
        self.assertEqual(qte.typed, "chains")

    def test_wrong_letter_resets_progress(self) -> None:
        qte = TypingQTE("chains", limit=8.0)
        qte.handle_key("c", "c")
        qte.handle_key("h", "h")
        qte.handle_key("x", "x")
        self.assertEqual(qte.typed, "")
        self.assertFalse(qte.done)

    def test_backspace_removes_one_letter(self) -> None:
        qte = TypingQTE("chains", limit=8.0)
        qte.handle_key("c", "c")
        qte.handle_key("h", "h")
        qte.handle_key("backspace", "")
        self.assertEqual(qte.typed, "c")

    def test_non_single_ascii_text_cannot_skip_letters(self) -> None:
        qte = TypingQTE("chains", limit=8.0)
        qte.handle_key("c", "chains")
        qte.handle_key("é", "é")
        self.assertEqual(qte.typed, "")
        self.assertEqual(qte.slips, 0)
        self.assertEqual(qte.progress, 0.0)
        self.assertEqual(qte.remaining, "chains")

    def test_typing_hint_names_the_actual_word(self) -> None:
        qte = TypingQTE("sorrow", limit=8.0)
        self.assertIn("SORROW", qte.hint)


class AngelAndTimingQTETests(unittest.TestCase):
    def test_angel_word_pool_is_long_and_nontrivial(self) -> None:
        self.assertGreaterEqual(len(ANGEL_WORDS), 12)
        self.assertTrue(all(len(word) >= 12 and word.isascii() and word.isalpha() for word in ANGEL_WORDS))

    def test_fatal_typing_qte_fails_on_first_wrong_letter(self) -> None:
        qte = TypingQTE("apokatastasis", limit=8.0, fatal_mistake=True)
        qte.handle_key("a", "a")
        self.assertEqual(qte.typed, "a")
        qte.handle_key("x", "x")
        self.assertTrue(qte.done)
        self.assertFalse(qte.success)
        self.assertEqual(qte.slips, 1)
        self.assertIn("One wrong letter fails immediately", qte.hint)
        punctuation = TypingQTE("apokatastasis", limit=8.0, fatal_mistake=True)
        punctuation.handle_key("!", "!")
        self.assertTrue(punctuation.done)
        self.assertFalse(punctuation.success)

    def test_timing_qte_requires_space_and_exact_random_zone(self) -> None:
        import random
        qte = TimingQTE(random.Random(44), speed=2.0, zone_width=0.04, limit=4.5)
        qte.pos = (qte.zone[0] + qte.zone[1]) / 2
        qte.handle_key("return", "")
        self.assertFalse(qte.done, "Enter must not count as a timing input")
        qte.handle_key("space", " ")
        self.assertTrue(qte.done)
        self.assertTrue(qte.success)
        miss = TimingQTE(random.Random(44), speed=2.0, zone_width=0.04, limit=4.5)
        miss.pos = 0.0 if miss.zone[0] > 0.05 else 1.0
        miss.handle_key("space", " ")
        self.assertTrue(miss.done)
        self.assertFalse(miss.success)


class ProceduralAudioTests(unittest.TestCase):
    def test_every_sfx_has_a_generator_and_alias_registry_matches(self) -> None:
        self.assertGreaterEqual(len(_SFX_SYNTHS), 10)
        self.assertEqual(set(AudioSystem.SFX_NAMES), set(_SFX_SYNTHS))
        for alias, target in AudioSystem.SFX_ALIASES.items():
            self.assertIn(target, _SFX_SYNTHS, f"alias {alias!r} points to missing sound {target!r}")

    def test_every_sfx_generates_finite_stereo_samples(self) -> None:
        rng = np.random.default_rng(2026)
        for name, synth in _SFX_SYNTHS.items():
            with self.subTest(sound=name):
                samples = synth(22050, rng)
                self.assertEqual(samples.ndim, 2)
                self.assertEqual(samples.shape[1], 2)
                self.assertGreater(samples.shape[0], 0)
                self.assertTrue(np.isfinite(samples).all())
                self.assertLessEqual(float(np.max(np.abs(samples))), 1.0)


    def test_gameplay_feedback_sounds_have_their_own_generators(self) -> None:
        """Victory/defeat/death/ward/enemy attacks must not be silent aliases of unrelated cues."""
        for name in ("enemy_swing", "ward", "death", "victory", "defeat"):
            with self.subTest(sound=name):
                self.assertIn(name, _SFX_SYNTHS)
                self.assertNotIn(name, AudioSystem.SFX_ALIASES)

    def test_sfx_are_unclipped_click_free_and_without_dc_offset(self) -> None:
        sr = 22050
        for name, synth in _SFX_SYNTHS.items():
            for seed in (1, 2, 3):
                with self.subTest(sound=name, seed=seed):
                    x = synth(sr, np.random.default_rng(seed))
                    self.assertLessEqual(float(np.max(np.abs(x))), 0.96, "peak headroom")
                    self.assertLess(abs(float(np.mean(x))), 0.01, "DC offset")
                    self.assertLess(float(np.max(np.abs(x[0]))), 0.02, "start click")
                    self.assertLess(float(np.max(np.abs(x[-1]))), 0.02, "end click")
                    self.assertLessEqual(x.shape[0] / sr, 2.0, "cue too long for combat feedback")


    def test_music_loops_wrap_without_a_discontinuity_and_keep_headroom(self) -> None:
        """Numeric loop check only; it cannot judge whether the music sounds good."""
        sr = 22050
        for level, render in ((1, _render_level1), (2, _render_level2), (3, _render_level3)):
            with self.subTest(level=level):
                x = np.asarray(render(sr), dtype=float)
                self.assertEqual(x.ndim, 2)
                self.assertTrue(np.isfinite(x).all())
                self.assertLessEqual(float(np.max(np.abs(x))), 0.95)
                step_cap = float(np.percentile(np.max(np.abs(np.diff(x, axis=0)), axis=1), 99.9))
                wrap_step = float(np.max(np.abs(x[0] - x[-1])))
                self.assertLessEqual(wrap_step, step_cap, "loop seam must be no larger than an ordinary sample step")


if __name__ == "__main__":
    unittest.main()
