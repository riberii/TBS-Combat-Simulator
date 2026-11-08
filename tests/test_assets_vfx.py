"""Asset-path, sheet-geometry, Animation-timing and art-effect lifecycle checks (no real display needed)."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from PIL import Image  # noqa: E402

from core.elements import DamageType  # noqa: E402
from entities.base_entity import Status  # noqa: E402,F401
from systems.combat_system import CombatEvent, EventKind  # noqa: E402
from entities.enemy import BOSS_ROSTER  # noqa: E402
from ui.assets import ASSET_ROOT, BOSS_ART, BOSS_ART_FALLBACK, boss_art_key, RESTRAINT_ICONS, SHEETS, Animation, AssetManager, background_for_stage  # noqa: E402
from ui.vfx import ELEMENT_SHEET, FX_SPRITE_MAX, FX_STATIC_TIME, RING_FX, VFX  # noqa: E402


class _FakeAssets:
    """Stands in for AssetManager: frames are ints, so no pygame surface is needed."""

    def __init__(self, reduced=False, missing=()):
        self.reduced_motion, self.missing = reduced, set(missing)

    def animation(self, name):
        return None if name in self.missing else Animation([0, 1, 2, 3, 4, 5], 10.0, False, self.reduced_motion)

    def fx(self, name):
        return None if name in self.missing else object()


def _vfx(assets):
    v = VFX({"big": object(), "mid": object()})
    v.assets = assets
    v.anchors = {7: (100.0, 200.0)}
    return v


class SheetAndPathTests(unittest.TestCase):
    def test_every_sheet_file_exists_and_covers_its_grid(self):
        for name, s in SHEETS.items():
            with self.subTest(sheet=name):
                p = ASSET_ROOT / s.path
                self.assertTrue(p.is_file(), f"missing {s.path}")
                with Image.open(p) as im:
                    w, h = im.size
                self.assertGreaterEqual(w, s.cols * s.cell_w)
                self.assertGreaterEqual(h, s.rows * s.cell_h)
                self.assertGreater(s.fps, 0)
                self.assertLessEqual(s.frames or s.cols * s.rows, s.cols * s.rows)

    def test_restraint_icons_and_ring_art_exist(self):
        for k, rel in RESTRAINT_ICONS.items():
            self.assertTrue((ASSET_ROOT / rel).is_file(), k)
        for cue, spec in RING_FX.items():
            self.assertTrue((ASSET_ROOT / "Art" / "fx" / f"{spec[0]}.png").is_file(), cue)

    def test_element_sheet_mapping_is_valid(self):
        for dname, sheet in ELEMENT_SHEET.items():
            self.assertIn(dname, DamageType.__members__)
            self.assertIn(sheet, SHEETS)
        self.assertNotIn("PHYSICAL", ELEMENT_SHEET)

    def test_stage_backgrounds_resolve_to_real_files(self):
        for stage in range(1, 30):
            self.assertTrue((ASSET_ROOT / "Art" / "backgrounds" / f"{background_for_stage(stage)}.jpg").is_file(), stage)

    def test_asset_manager_is_fail_soft_and_jailed(self):
        am = AssetManager()
        self.assertFalse(am.exists("Art/does_not_exist.png"))
        self.assertFalse(am.exists("../../etc/passwd"))
        with self.assertRaises(ValueError):
            am.path("../outside.png")
        self.assertIsNone(am.image("Art/does_not_exist.png"))      # warns once, returns None, never raises


class BossArtTests(unittest.TestCase):
    def test_every_boss_has_existing_portrait_art(self):
        for b in BOSS_ROSTER:
            key = boss_art_key(b.name)
            self.assertTrue((ASSET_ROOT / "Art" / "bosses" / f"{key}.png").is_file(), b.name)
        for key in list(BOSS_ART.values()) + list(BOSS_ART_FALLBACK):
            self.assertTrue((ASSET_ROOT / "Art" / "bosses" / f"{key}.png").is_file(), key)

    def test_boss_roster_portraits_are_distinct_and_unknown_names_are_stable(self):
        keys = [boss_art_key(b.name) for b in BOSS_ROSTER]
        self.assertEqual(len(keys), len(set(keys)), "each rostered boss should look different")
        self.assertEqual(boss_art_key("Some New Boss"), boss_art_key("Some New Boss"))


class AnimationTimingTests(unittest.TestCase):
    def test_one_shot_runs_to_last_frame_and_finishes(self):
        a = Animation(list(range(6)), 10.0, loop=False)
        self.assertEqual((a.index, a.done), (0, False))
        a.update(0.25)
        self.assertEqual(a.index, 2)
        a.update(5.0)
        self.assertEqual((a.index, a.done), (5, True))

    def test_loop_wraps(self):
        a = Animation(list(range(4)), 8.0, loop=True)
        a.update(0.55)
        self.assertEqual(a.index, 0 + int((0.55 % 0.5) * 8))
        self.assertFalse(a.done)

    def test_reduced_motion_freezes(self):
        loop = Animation(list(range(4)), 8.0, loop=True, reduced_motion=True)
        shot = Animation(list(range(4)), 8.0, loop=False, reduced_motion=True)
        for a in (loop, shot):
            a.update(10.0)
        self.assertEqual(loop.index, 0, "loops hold their pose")
        self.assertEqual(shot.index, 3, "one-shots show their result")

    def test_bad_arguments_rejected(self):
        with self.assertRaises(ValueError):
            Animation([], 10.0)
        with self.assertRaises(ValueError):
            Animation([1], 0.0)


class FxLifecycleTests(unittest.TestCase):
    def _hit(self, dtype="FIRE", crit=False):
        return CombatEvent(EventKind.CRIT if crit else EventKind.DAMAGE, uid=7, amount=12, data={"dtype": dtype})

    def test_elemental_hit_spawns_art_and_it_expires(self):
        v = _vfx(_FakeAssets())
        v.consume([self._hit("FROST")])
        self.assertEqual(len(v.sprites), 1)
        for _ in range(40):
            v.update(0.05)
        self.assertEqual(v.sprites, [], "effect must clean itself up")

    def test_physical_hit_has_no_art_effect(self):
        v = _vfx(_FakeAssets())
        v.consume([self._hit("PHYSICAL")])
        self.assertEqual(v.sprites, [])

    def test_restraint_events_spawn_rings(self):
        v = _vfx(_FakeAssets())
        v.consume([CombatEvent(EventKind.RESTRAINT_APPLIED, uid=7), CombatEvent(EventKind.RESTRAINT_BROKEN, uid=7),
                   CombatEvent(EventKind.LUCIDITY, uid=7, amount=5)])
        self.assertEqual(sorted(s.kind for s in v.sprites), ["ring"] * 3)

    def test_missing_art_degrades_to_nothing(self):
        v = _vfx(_FakeAssets(missing={"fx_flame", "chain_ring_red_a"}))
        v.consume([self._hit("FIRE"), CombatEvent(EventKind.RESTRAINT_APPLIED, uid=7)])
        self.assertEqual(v.sprites, [])
        self.assertEqual(len(v.floaters), 1, "the damage number must still appear")
        v2 = _vfx(None)
        v2.consume([self._hit("FIRE")])
        self.assertEqual(v2.sprites, [])

    def test_reduced_motion_effects_are_brief_stills(self):
        v = _vfx(_FakeAssets(reduced=True))
        v.reduced_motion = True
        v.consume([self._hit("STORM")])
        self.assertAlmostEqual(v.sprites[0].life, FX_STATIC_TIME)
        self.assertEqual(v.sprites[0].anim.index, 5)

    def test_sprite_count_is_bounded(self):
        v = _vfx(_FakeAssets())
        v.consume([self._hit("FIRE") for _ in range(FX_SPRITE_MAX * 3)])
        self.assertLessEqual(len(v.sprites), FX_SPRITE_MAX)


if __name__ == "__main__":
    unittest.main()
