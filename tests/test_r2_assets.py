"""R2 asset tests: file formats vs. declared specs, pure animation timing, fallbacks, settings default.

Real-file checks use PIL/wave only.  The AssetLibrary logic is executed with real pygame-ce when installed,
otherwise with tests/pil_pygame_shim.py (a PIL stand-in - see its docstring for what that does NOT prove).
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

try:
    from PIL import Image
except ImportError as exc:  # Pillow is a dev-only dependency (requirements-dev.txt)
    raise unittest.SkipTest("Pillow not installed: pip install -r requirements-dev.txt") from exc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import r2_assets as r2  # noqa: E402

try:
    import pygame as _real_pygame  # noqa: F401
    HAVE_PYGAME = hasattr(_real_pygame, "image") and hasattr(_real_pygame, "transform") and hasattr(_real_pygame.transform, "scale")
except ImportError:
    HAVE_PYGAME = False


def pygame_context():
    if HAVE_PYGAME:
        return mock.patch.dict(sys.modules, {})
    import pil_pygame_shim
    return mock.patch.dict(sys.modules, {"pygame": pil_pygame_shim.make_module()})


class AnimationTimingTests(unittest.TestCase):
    def test_loop_wraps_and_uses_elapsed_time(self) -> None:
        a = r2.Animation(list("abcd"), fps=10, loop=True)
        seen = []
        for _ in range(9):
            seen.append(a.frame)
            a.update(0.1)
        self.assertEqual("".join(seen), "abcdabcda")

    def test_frame_rate_independent(self) -> None:
        a, b = r2.Animation(list(range(8)), 8, True), r2.Animation(list(range(8)), 8, True)
        for _ in range(30):
            a.update(1 / 60)
        for _ in range(15):
            b.update(1 / 30)
        self.assertEqual(a.index, b.index)

    def test_one_shot_holds_last_frame_then_done(self) -> None:
        a = r2.Animation(list(range(4)), 8, False)
        self.assertFalse(a.done)
        for _ in range(49):
            a.update(0.01)
        self.assertEqual(a.index, 3)
        self.assertFalse(a.done)
        a.update(0.02)
        self.assertTrue(a.done)
        self.assertEqual(a.index, 3)

    def test_reduced_motion(self) -> None:
        loop = r2.Animation(list(range(8)), 9, True)
        loop.update(0.5, reduced=True)
        self.assertEqual(loop.index, 0, "looping art is a static pose under reduced motion")
        shot = r2.Animation(list(range(8)), 10, False)
        shot.update(0.01, reduced=True)
        self.assertEqual(shot.index, 4)
        shot.update(r2.REDUCED_SHOT_SECONDS, reduced=True)
        self.assertTrue(shot.done, "one-shots shorten to a brief peak frame")

    def test_stall_cannot_skip_a_whole_animation(self) -> None:
        a = r2.Animation(list(range(8)), 10, False)
        a.update(5.0)
        self.assertLessEqual(a.time, 0.25)
        self.assertFalse(a.done)

    def test_invalid_construction(self) -> None:
        with self.assertRaises(ValueError):
            r2.Animation([], 10, True)
        with self.assertRaises(ValueError):
            r2.Animation([1], 0, True)


class AssetFileTests(unittest.TestCase):
    """Every declared asset exists and matches the dimensions/format the code assumes."""

    def test_sheets_match_specs(self) -> None:
        for key, spec in r2.ANIMATIONS.items():
            path = r2.R2_ROOT / spec.rel
            self.assertTrue(path.is_file(), f"{key}: {path} missing")
            im = Image.open(path)
            self.assertEqual(im.size, spec.sheet_size, key)
            self.assertEqual(im.mode, "RGBA", key)
            for i in range(spec.frame_count):
                cw, ch = spec.cell
                cell = im.crop(((i % spec.cols) * cw, (i // spec.cols) * ch, (i % spec.cols + 1) * cw, (i // spec.cols + 1) * ch))
                self.assertGreater(cell.getchannel("A").getbbox() is not None, 0, f"{key} frame {i} is fully transparent")

    def test_rejected_chibi_pack_is_not_shipped_or_referenced(self) -> None:
        self.assertFalse((r2.R2_ROOT / "characters" / "fallen_angel").exists())
        self.assertFalse((r2.R2_ROOT / "vfx" / "fallen_angel").exists())
        self.assertFalse([k for k in r2.ANIMATIONS if k.startswith(("fa_", "fx_"))])

    def test_portraits_exist_for_all_eight_classes(self) -> None:
        self.assertEqual(set(r2.PORTRAITS), {"warrior", "tank", "rogue", "witch", "fallen_angel", "kitsune", "vampire", "dragonkin"})
        for k, rel in r2.PORTRAITS.items():
            with Image.open(r2.R2_ROOT / rel) as im:
                im.load()
                self.assertGreaterEqual(min(im.size), 190, k)
                self.assertTrue(0.4 <= im.width / im.height <= 1.4, f"{k} aspect {im.size}")

    def test_models_are_feathered_rgba_busts_for_all_classes(self) -> None:
        self.assertEqual(set(r2.MODELS), set(r2.PORTRAITS))
        for k, rel in r2.MODELS.items():
            with Image.open(r2.R2_ROOT / rel) as im:
                im.load()
                self.assertEqual(im.mode, "RGBA", k)
                self.assertEqual(im.height, 480, k)
                self.assertTrue(0.4 <= im.width / im.height <= 1.2, f"{k} {im.size}")
                w, h = im.size
                for corner in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                    self.assertEqual(im.getpixel(corner)[3], 0, f"{k} corner {corner} must be transparent")
                self.assertEqual(im.getpixel((w // 2, h // 3))[3], 255, f"{k} centre must be opaque")
                self.assertLess(im.getpixel((w // 2, h - 1))[3], 8, f"{k} bottom fades out")

    def test_title_logo_is_keyed_over_transparency(self) -> None:
        with Image.open(r2.R2_ROOT / r2.TITLE_LOGO) as logo:
            logo.load()
            self.assertEqual(logo.mode, "RGBA")
            alphas = logo.getchannel("A")
            lo, hi = alphas.getextrema()
            self.assertEqual(lo, 0)
            self.assertGreater(hi, 200)

    def test_board_icons_and_title_art(self) -> None:
        for name in r2.BOARD_ICONS:
            with Image.open(r2.R2_ROOT / "icons_boards" / f"{name}.png") as im:
                self.assertEqual(im.size, (128, 128), name)
        with Image.open(r2.R2_ROOT / r2.TITLE_KEY_ART) as art:
            art.load()
            self.assertEqual(art.height, 720)
            self.assertLess(art.width, 1280, "title art must leave the right side free for the menu")
            self.assertEqual(art.mode, "RGBA")
            self.assertEqual(art.getpixel((art.width - 1, 360))[3], 0, "right edge fades to transparent")
            self.assertEqual(art.getpixel((10, 360))[3], 255)

    def test_icons(self) -> None:
        for name, rel in r2.RESTRAINT_ICONS.items():
            im = Image.open(r2.R2_ROOT / rel)
            self.assertEqual((im.size, im.mode), ((96, 96), "RGBA"), name)

    def test_wavs_numerically_sane(self) -> None:
        """Numerical checks only - these files have NOT been listened to."""
        for name, rel in r2.SOUNDS.items():
            with wave.open(str(r2.R2_ROOT / rel), "rb") as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100), name)
                raw = w.readframes(w.getnframes())
            import array
            samples = array.array("h", raw)
            peak = max(abs(v) for v in samples) / 32768.0
            dc = abs(sum(samples) / len(samples)) / 32768.0
            self.assertLess(peak, 0.999, f"{name} clips")
            self.assertGreater(peak, 0.05, f"{name} is nearly silent")
            self.assertLess(dc, 0.01, f"{name} has DC offset")
            self.assertLess(abs(samples[0]) / 32768.0, 0.05, f"{name} starts with a click")
            self.assertLess(abs(samples[-1]) / 32768.0, 0.05, f"{name} ends with a click")
            self.assertTrue(all(math.isfinite(v) for v in samples[:10]))

    def test_hit_boxes_cover_every_restraint_kind(self) -> None:
        from tools.headless_bootstrap import install_import_stub_if_missing
        install_import_stub_if_missing()
        from ui.renderer import RestraintKind
        self.assertEqual({k.name for k in RestraintKind}, set(r2.MODEL_HIT_FRACTIONS))


class AssetLibraryTests(unittest.TestCase):
    def test_slicing_scaling_and_one_shots(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary()
            for key, spec in r2.ANIMATIONS.items():
                frames = lib.sheet_frames(key)
                self.assertIsNotNone(frames, key)
                self.assertEqual(len(frames), spec.frame_count, key)
                self.assertTrue(all(f.get_size() == spec.cell for f in frames), key)
            img = lib.scaled_frame("el_flame", 3, 0.5)
            self.assertEqual(img.get_size(), (64, 64))
            self.assertTrue(lib.trigger(7, "el_frost"))
            self.assertEqual(len(lib.active_shots(7)), 1)
            lib.update(0.3)
            self.assertEqual(len(lib.active_shots(7)), 1)
            lib.update(1.0)
            lib.update(1.0)
            self.assertEqual(lib.active_shots(7), [], "finished one-shots are removed")

    def test_shot_cap_and_clear(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary()
            for _ in range(40):
                lib.trigger(1, "el_storm")
            self.assertLessEqual(len(lib.active_shots()), r2.MAX_SHOTS)
            lib.clear_effects()
            self.assertEqual(lib.active_shots(), [])

    def test_portraits_and_face_crop(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary()
            for k in r2.PORTRAITS:
                face = lib.portrait(k, (42, 42), face=True)
                self.assertIsNotNone(face, k)
                self.assertEqual(face.get_size(), (42, 42))

    def test_missing_assets_fall_back_without_raising(self) -> None:
        with pygame_context(), tempfile.TemporaryDirectory() as empty:
            lib = r2.AssetLibrary(root=Path(empty))
            self.assertIsNone(lib.image("nope.png"))
            self.assertIsNone(lib.sheet_frames("el_flame"))
            self.assertIsNone(lib.actor_frame(1, "el_flame", 1.0))
            self.assertIsNone(lib.portrait("warrior", (10, 10)))
            self.assertIsNone(lib.icon("chains"))
            self.assertFalse(lib.trigger(1, "el_storm"))
            self.assertEqual(lib.sound_paths(), {})
            lib.update(0.1)
            lib.draw_shots(object(), 1, 0, 0, 1.0)

    def test_corrupt_png_falls_back(self) -> None:
        with pygame_context(), tempfile.TemporaryDirectory() as d:
            bad = Path(d) / r2.ANIMATIONS["el_flame"].rel
            bad.parent.mkdir(parents=True)
            bad.write_bytes(b"not a png")
            lib = r2.AssetLibrary(root=Path(d))
            self.assertIsNone(lib.sheet_frames("el_flame"))

    def test_wrong_sheet_size_is_rejected(self) -> None:
        with pygame_context(), tempfile.TemporaryDirectory() as d:
            p = Path(d) / r2.ANIMATIONS["el_flame"].rel
            p.parent.mkdir(parents=True)
            Image.new("RGBA", (100, 100)).save(p)
            self.assertIsNone(r2.AssetLibrary(root=Path(d)).sheet_frames("el_flame"))

    def test_models_switch_restores_procedural_models_only(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary()
            self.assertIsNotNone(lib.model_aspect("fallen_angel"))
            lib.models_enabled = False
            self.assertIsNone(lib.model_aspect("fallen_angel"), "renderer falls back to the original procedural model")
            self.assertIsNone(lib.model("fallen_angel", 200))
            self.assertIsNotNone(lib.portrait("fallen_angel", (40, 40), face=True), "portraits/title art are separate")
            self.assertIsNotNone(lib.image(r2.TITLE_KEY_ART))

    def test_disabled_library_returns_nothing(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary(enabled=False)
            self.assertIsNone(lib.sheet_frames("el_flame"))
            self.assertIsNone(lib.portrait("tank", (10, 10)))

    def test_icon_pops_lifecycle_and_reduced_motion(self) -> None:
        with pygame_context():
            lib = r2.AssetLibrary()
            self.assertTrue(lib.icon_pop(5, "slash"))
            self.assertFalse(lib.icon_pop(5, "not_an_icon"))
            for _ in range(5):
                lib.update(0.1)
            self.assertEqual(len(lib._pops), 1)
            for _ in range(5):
                lib.update(0.1)
            self.assertEqual(lib._pops, [], "pops expire")
            lib.reduced_motion = True
            lib.icon_pop(5, "heal")
            for _ in range(5):
                lib.update(0.1)
            self.assertEqual(lib._pops, [], "reduced motion shortens pops")
            for _ in range(40):
                lib.icon_pop(1, "slash")
            self.assertLessEqual(len(lib._pops), r2.MAX_POPS)

    def test_icon_pop_draw_never_raises_and_title_art_loads(self) -> None:
        with pygame_context():
            import pil_pygame_shim as shim
            lib = r2.AssetLibrary()
            lib.icon_pop(3, "fireball")
            canvas = shim.Surface((300, 300))
            lib.draw_pops(canvas, 3, 150, 200, 1.0)
            self.assertIsNotNone(lib.image(r2.TITLE_KEY_ART))
            self.assertTrue(lib.enabled)

    def test_icon_for_action_mapping(self) -> None:
        self.assertEqual(r2.icon_for_action("slash"), "slash")
        self.assertEqual(r2.icon_for_action("dragon_breath"), "fireball")
        self.assertEqual(r2.icon_for_action("guard"), "shield")
        self.assertEqual(r2.icon_for_action("halo"), "explosion")
        self.assertEqual(r2.icon_for_action("curse"), "dark_magic")
        self.assertEqual(r2.icon_for_action("tonic", "item"), "heal")
        self.assertIsNone(r2.icon_for_action("cutters", "item"))
        self.assertIsNone(r2.icon_for_action(""))
        self.assertIsNone(r2.icon_for_action("totally_unknown"))
        for key in ("slash", "bolt", "guard", "halo", "curse", "inferno", "frost_nova"):
            self.assertIn(r2.icon_for_action(key), r2.BOARD_ICONS)

    def test_fit_model_height(self) -> None:
        self.assertAlmostEqual(r2.fit_model_height(0.9, 0.75, 0.0), 270.0)
        self.assertAlmostEqual(r2.fit_model_height(0.52, 1.0, 103.0), 103 * 1.45)     # crowded party shrinks the bust
        self.assertEqual(r2.fit_model_height(0.1, 1.0, 0.0), 120.0)                   # never unreadably small
        self.assertLess(r2.fit_model_height(0.7, 1.04, 122.0), 0.7 * 300)

    def test_model_hit_boxes_roundtrip_to_the_drawn_rect(self) -> None:
        boxes = r2.model_hit_boxes(100, 200, 200, 300, 200, 500, 0.5)
        names = {n for n, _ in boxes}
        self.assertEqual(names, set(r2.MODEL_HIT_FRACTIONS))
        for name, (hx, hy, hw, hh) in boxes:       # convert back like Renderer.draw does
            x, y = 200 + hx * 0.5, 500 + hy * 0.5
            self.assertGreaterEqual(x, 100 - 1)
            self.assertLessEqual(x + hw * 0.5, 300 + 1)
            self.assertGreaterEqual(y, 200 - 1)
            self.assertLessEqual(y + hh * 0.5, 500 + 1)

    def test_model_glow_and_scaling_with_stand_in(self) -> None:
        with pygame_context():
            import pil_pygame_shim as shim
            shim_mod = sys.modules["pygame"]
            shim_mod.SRCALPHA = 0x10000
            shim_mod.draw = types.SimpleNamespace(ellipse=lambda *a, **k: None)
            lib = r2.AssetLibrary()
            for k in r2.MODELS:
                self.assertGreater(lib.model_aspect(k), 0.4)
                m = lib.model(k, 250)
                self.assertEqual(m.get_size()[1], 248)             # snapped to 8 px steps
                self.assertIsNotNone(lib.glow(k, (200, 260)))
            self.assertIsNone(lib.model("unknown", 100))
            self.assertIsNone(lib.model_aspect("unknown"))


class SettingsDefaultTests(unittest.TestCase):
    def test_r2_art_defaults_on_and_old_files_still_load(self) -> None:
        from systems.settings_system import DEFAULT_SETTINGS, SettingsStore
        self.assertTrue(DEFAULT_SETTINGS["r2_art"])
        self.assertTrue(DEFAULT_SETTINGS["r2_models"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text('{"schema": 1, "music_volume": 0.3, "sfx_volume": 0.4, "muted": false, "fullscreen": false,'
                            ' "screen_shake": true, "particles": true, "reduced_motion": false}')
            store = SettingsStore(path)
            loaded = store.load()
            self.assertTrue(loaded["r2_art"])
            loaded["r2_art"] = False
            store.save(loaded)
            self.assertFalse(SettingsStore(path).load()["r2_art"])


if __name__ == "__main__":
    unittest.main()
