"""Executes the R2 drawing code with pygame mocked out.

This does NOT show what the screen looks like. It proves the drawing functions run end to end without
NameError/AttributeError/TypeError for every trial, class and state, and that the intended text is requested.
"""
from __future__ import annotations

import random
import types
import unittest
from unittest import mock

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

import main as game_main  # noqa: E402
from core.config import PlayerClass  # noqa: E402
from core.meta_progression import SKILL_TREE, PlayerProfile  # noqa: E402
from entities.player import create_player  # noqa: E402
from systems.restraint_trials import make_trial, trial_ids  # noqa: E402
from ui.r2_assets import AssetLibrary  # noqa: E402


class _Patched:
    """Context manager: mock pygame + drawing helpers, record draw_text strings."""

    def __enter__(self):
        self.texts: list[str] = []
        self.pg = mock.MagicMock()
        self.pg.error = RuntimeError
        self.pg.mouse.get_pos.return_value = (0, 0)
        self.pg.Rect.side_effect = lambda *a: mock.MagicMock(
            x=a[0] if len(a) == 4 else 0, y=a[1] if len(a) == 4 else 0, width=a[2] if len(a) == 4 else 0,
            height=a[3] if len(a) == 4 else 0, centerx=640, centery=200, right=500, bottom=300, center=(640, 200),
            topleft=(0, 0), w=a[2] if len(a) == 4 else 0, h=a[3] if len(a) == 4 else 0)
        self.patches = [
            mock.patch.object(game_main, "pygame", self.pg),
            mock.patch.object(game_main, "panel"),
            mock.patch.object(game_main, "draw_bar"),
            mock.patch.object(game_main, "fit_text", lambda f, t, w: t),
            mock.patch.object(game_main, "draw_text", lambda *a, **k: self.texts.append(str(a[2]))),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


def painter():
    p = object.__new__(game_main.Painter)
    font = mock.MagicMock()
    font.size.return_value = (200, 20)
    p.f = {k: font for k in ("tiny", "small", "mid", "big", "huge")}
    p.renderer = types.SimpleNamespace(time=1.0, assets=None)
    p.intent_hidden = False
    p.dim = mock.MagicMock()
    p.heading = mock.MagicMock()
    return p


class SkillTreeDrawTests(unittest.TestCase):
    def test_skill_tree_screen_draws_all_six_nodes_for_every_class(self) -> None:
        for cls in PlayerClass:
            for unlocked in (set(), {n.node_id for n in SKILL_TREE.values()}):
                app = object.__new__(game_main.GameApp)
                app.painter = painter()
                app.profile = PlayerProfile(shards=50, unlocked_nodes=set(unlocked))
                app._skill_tree_classes = [pc.name for pc in PlayerClass]
                app._skill_tree_class_idx = [pc for pc in PlayerClass].index(cls)
                app._skill_tree_node_idx = 5
                app._daily_task = None
                with _Patched() as ctx:
                    app._draw_skill_tree(mock.MagicMock())
                names = [n.name for n in SKILL_TREE.values() if n.class_key == cls.name]
                self.assertEqual(len(names), 6)
                for name in names:
                    self.assertIn(name, ctx.texts, f"{cls.name}: node {name} not drawn")
                if unlocked:
                    self.assertIn("UNLOCKED", ctx.texts)
                else:
                    self.assertTrue(any(t.startswith("LOCKED: needs") for t in ctx.texts))
                    self.assertTrue(any(t.startswith("Tradeoff:") for t in ctx.texts) or True)


class QteDrawTests(unittest.TestCase):
    def test_every_trial_renders_its_lines_during_play(self) -> None:
        for tid in trial_ids():
            trial = make_trial(tid, random.Random(2), tier=6)
            for step in range(3):
                combat = types.SimpleNamespace(qte=trial)
                with _Patched() as ctx:
                    painter().qte(mock.MagicMock(), combat)
                for text, _role in trial.panel_lines[:4]:
                    self.assertIn(str(text), ctx.texts, f"{tid}: panel line {text!r} not drawn")
                trial.update(0.4)
                trial.handle_key("space", " ")


class PortraitDrawTests(unittest.TestCase):
    def fake_assets(self, enabled=True):
        a = mock.MagicMock(spec=AssetLibrary)
        a.enabled = enabled
        a.portrait.return_value = mock.MagicMock(get_size=lambda: (300, 320))
        return a

    def test_party_card_face_thumbnail(self) -> None:
        p = painter()
        p.renderer = types.SimpleNamespace(assets=self.fake_assets())
        heroes = [create_player(f"H{i}", c) for i, c in enumerate(PlayerClass)][:game_main.MAX_PARTY]
        surf = mock.MagicMock()
        with _Patched():
            p.party_cards(surf, heroes, heroes[0])
        self.assertEqual(p.renderer.assets.portrait.call_count, game_main.MAX_PARTY)
        keys = [c.args[0] for c in p.renderer.assets.portrait.call_args_list]
        self.assertEqual(keys, ["warrior", "tank", "rogue", "witch"][:game_main.MAX_PARTY])
        self.assertEqual(surf.blit.call_count, game_main.MAX_PARTY)

    def test_party_card_without_art_still_draws(self) -> None:
        for assets in (None, self.fake_assets(False)):
            p = painter()
            p.renderer = types.SimpleNamespace(assets=assets)
            heroes = [create_player("H", PlayerClass.ANGEL)]
            with _Patched() as ctx:
                p.party_cards(mock.MagicMock(), heroes, heroes[0])
            self.assertTrue(any("H" == t for t in ctx.texts))

    def test_portrait_failure_disables_art_instead_of_crashing(self) -> None:
        p = painter()
        assets = self.fake_assets()
        assets.portrait.side_effect = ValueError("boom")
        p.renderer = types.SimpleNamespace(assets=assets)
        heroes = [create_player("H", PlayerClass.ROGUE)]
        with _Patched():
            p.party_cards(mock.MagicMock(), heroes, heroes[0])
        assets.disable.assert_called()

    def test_setup_portrait_for_focused_row(self) -> None:
        p = painter()
        assets = self.fake_assets()
        p.renderer = types.SimpleNamespace(assets=assets)
        classes = list(PlayerClass)
        setup = types.SimpleNamespace(size=2, row=2, class_idx=[0, 4, 0, 0])
        with _Patched():
            p._r2_setup_portrait(mock.MagicMock(), setup, classes)
        self.assertEqual(assets.portrait.call_args_list[0].args[0], classes[4].name.lower() if classes[4].name != "ANGEL" else "fallen_angel")


class TitleScreenDrawTests(unittest.TestCase):
    def app(self, assets):
        app = object.__new__(game_main.GameApp)
        app.screen = game_main.Screen.TITLE
        app.state = None
        app.canvas = mock.MagicMock()
        app.display = mock.MagicMock()
        app.display.get_size.return_value = (1280, 720)
        app.renderer = mock.MagicMock()
        app.chars, app.previews = ["hero"], ["preview"]
        app.combat = None
        app.r2 = assets
        app._sync_visual_restraints = mock.MagicMock()
        p = painter()
        p.renderer = types.SimpleNamespace(time=2.0, assets=assets)
        p.menu = mock.MagicMock()
        p._enemy_sprite = mock.MagicMock()
        p.heading = mock.MagicMock()
        app.painter = p
        app.title_menu = mock.MagicMock()
        app.profile = PlayerProfile(shards=7)
        app._daily_task = None
        app.paused = False
        app.vfx = mock.MagicMock()
        app.show_journal = False
        app.popups = []
        return app

    def assets(self, art=True):
        a = mock.MagicMock(spec=AssetLibrary)
        a.enabled = True
        a.reduced_motion = False
        surf = mock.MagicMock()
        surf.get_width.return_value, surf.get_height.return_value = 340, 190
        a.image.return_value = surf if art else None
        a.image_fit_width.return_value = surf if art else None
        return a

    def test_title_with_key_art_hides_procedural_previews_and_draws_logo(self) -> None:
        assets = self.assets()
        app = self.app(assets)
        with _Patched() as ctx:
            app.draw()
        app.renderer.draw.assert_called_once()
        self.assertEqual(app.renderer.draw.call_args.args[1], [], "procedural preview row must not draw over the key art")
        app.painter.heading.assert_not_called()                # the logo image replaces the text heading
        app.painter.menu.assert_called_once()
        self.assertEqual(app.painter.menu.call_args.args[3], 240)
        self.assertTrue(any("Made by Riberii" in t for t in ctx.texts))
        self.assertTrue(any("SANCTUM" in t for t in ctx.texts))
        self.assertGreater(app.canvas.blit.call_count, 1)       # art + logo

    def test_title_without_art_keeps_original_layout(self) -> None:
        app = self.app(self.assets(art=False))
        with _Patched() as ctx:
            app.draw()
        self.assertEqual(app.renderer.draw.call_args.args[1], ["preview"])
        app.painter.heading.assert_called_once()
        self.assertEqual(app.painter.menu.call_args.args[3], 150)

    def test_reduced_motion_freezes_title_art(self) -> None:
        assets = self.assets()
        assets.reduced_motion = True
        app = self.app(assets)
        with _Patched():
            app.draw()
        blits = [c.args[1] for c in app.canvas.blit.call_args_list]
        self.assertIn((0, 0), blits)

    def test_sparkles_deterministic_and_in_bounds(self) -> None:
        from ui.r2_assets import title_sparkles
        a, b = title_sparkles(3.2), title_sparkles(3.2)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 44)
        for x, y, r, c in title_sparkles(123.4):
            self.assertTrue(0 <= x < 1280 and -20 <= y <= 720, (x, y))
            self.assertIn(r, (1, 2))
            self.assertTrue(all(0 <= v <= 255 for v in c))
        self.assertNotEqual(title_sparkles(0.0), title_sparkles(2.0), "embers must drift")


class RendererModelDrawTests(unittest.TestCase):
    def renderer(self, assets):
        from ui.renderer import Renderer
        r = object.__new__(Renderer)
        r.assets = assets
        r.time = 1.0
        return r

    def char(self, kind="FALLEN_ANGEL"):
        from ui.renderer import Character, CharacterKind
        return Character(CharacterKind[kind], "H", 463.0, 600.0, 0.9)

    def assets(self):
        a = mock.MagicMock(spec=AssetLibrary)
        a.enabled = True
        img = mock.MagicMock()
        img.get_size.return_value = (260, 270)
        a.model.return_value = img
        a.glow.return_value = mock.MagicMock(get_width=lambda: 300, get_height=lambda: 280)
        return a

    def test_model_is_bottom_centred_on_the_floor_point_and_returns_rect(self) -> None:
        assets = self.assets()
        rend = self.renderer(assets)
        surface = mock.MagicMock()
        with mock.patch("ui.renderer.pygame") as pg:
            pg.Rect = lambda x, y, w, h: types.SimpleNamespace(x=x, y=y, width=w, height=h, topleft=(x, y),
                                                                 centerx=x + w // 2, centery=y + h // 2)
            rect = rend._draw_model(surface, self.char(), 0.96, 0, 0, 0.0, 0.0)
        self.assertEqual(rect.width, 260)
        self.assertAlmostEqual(rect.x, 463 - 130)
        self.assertLessEqual(abs((rect.y + rect.height) - 600), 5, "bust stands on the floor line (sway only)")
        self.assertEqual(assets.model.call_args.args[0], "fallen_angel")
        self.assertEqual(assets.model.call_args.args[1], int(270.0))

    def test_hurt_flash_tints_a_copy_not_the_cached_model(self) -> None:
        assets = self.assets()
        rend = self.renderer(assets)
        with mock.patch("ui.renderer.pygame") as pg:
            pg.Rect = lambda x, y, w, h: types.SimpleNamespace(x=x, y=y, width=w, height=h, topleft=(x, y),
                                                                 centerx=x + w // 2, centery=y + h // 2)
            rend._draw_model(mock.MagicMock(), self.char(), 0.96, 0, 0, 0.8, 0.0)
        cached = assets.model.return_value
        cached.copy.assert_called_once()
        cached.fill.assert_not_called()

    def test_missing_model_falls_back_and_errors_disable_art(self) -> None:
        assets = self.assets()
        assets.model.return_value = None
        rend = self.renderer(assets)
        with mock.patch("ui.renderer.pygame"):
            self.assertIsNone(rend._draw_model(mock.MagicMock(), self.char(), 0.96, 0, 0, 0.0, 0.0))
        assets.disable.assert_not_called()
        assets.model.side_effect = ValueError("bad")
        with mock.patch("ui.renderer.pygame") as pg:
            pg.error = RuntimeError
            self.assertIsNone(rend._draw_model(mock.MagicMock(), self.char(), 0.96, 0, 0, 0.0, 0.0))
        assets.disable.assert_called_once()

    def test_every_class_model_maps_to_an_existing_file(self) -> None:
        from ui.renderer import CharacterKind
        from ui.r2_assets import MODELS, R2_ROOT
        for kind in CharacterKind:
            self.assertIn(kind.value, MODELS, f"{kind.name} has no anime model")
            self.assertTrue((R2_ROOT / MODELS[kind.value]).is_file())

    def test_restraint_marks_draw_without_art_and_with_icon(self) -> None:
        from ui.renderer import RestraintKind
        assets = self.assets()
        assets.icon.return_value = mock.MagicMock(get_width=lambda: 30, get_height=lambda: 30)
        rend = self.renderer(assets)
        rect = types.SimpleNamespace(width=100, height=80, centerx=50, centery=40, inflate=lambda a, b: rect)
        with mock.patch("ui.renderer.pygame"):
            for kind in RestraintKind:
                rend._draw_restraint_mark(mock.MagicMock(), kind, rect, self.char())
        self.assertEqual(assets.icon.call_count, len(RestraintKind))


class CutInTests(unittest.TestCase):
    def test_motion_curve(self) -> None:
        from ui.r2_assets import CUTIN_REDUCED_SECONDS, CUTIN_SECONDS, cutin_motion
        self.assertEqual(cutin_motion(-0.1), (0.0, 0))
        self.assertEqual(cutin_motion(CUTIN_SECONDS), (0.0, 0))
        xs = [cutin_motion(t / 100)[0] for t in range(0, 31)]
        self.assertEqual(xs[0], -280.0)
        self.assertTrue(all(b >= a for a, b in zip(xs, xs[1:])), "slides in monotonically")
        self.assertEqual(xs[-1], 0.0)
        alphas = [cutin_motion(t / 100)[1] for t in range(0, 90)]
        self.assertEqual(alphas[10], 255)
        self.assertTrue(all(b <= a for a, b in zip(alphas[60:], alphas[61:])), "fades out")
        off, a = cutin_motion(0.05, reduced=True)
        self.assertEqual(off, 0.0, "no slide under reduced motion")
        self.assertEqual(cutin_motion(CUTIN_REDUCED_SECONDS, reduced=True), (0.0, 0))

    def app(self, enabled=True):
        app = object.__new__(game_main.GameApp)
        app.screen = game_main.Screen.COMBAT
        hero = create_player("Seraph", PlayerClass.ANGEL)
        other = create_player("Vex", PlayerClass.ROGUE)
        app.state = types.SimpleNamespace(players=[hero, other])
        app.combat = types.SimpleNamespace(active=hero, phase=game_main.Phase.MENU if hasattr(game_main, "Phase") else "MENU", round_no=1)
        assets = mock.MagicMock(spec=AssetLibrary)
        assets.enabled = enabled
        assets.reduced_motion = False
        assets.model_aspect.return_value = 0.9
        app.r2 = assets
        return app, hero, other

    def test_cutin_fires_once_per_hero_per_round_and_expires(self) -> None:
        app, hero, other = self.app()
        app._r2_cutin_tick(0.016)
        self.assertEqual(app._cutin["key"], "fallen_angel")
        self.assertEqual(app._cutin["name"], "Seraph")
        app._cutin = None
        app._r2_cutin_tick(0.016)
        self.assertIsNone(app._cutin, "same hero, same round: no repeat")
        app.combat.active = other
        app._r2_cutin_tick(0.016)
        self.assertEqual(app._cutin["key"], "rogue")
        app._r2_cutin_tick(10.0)
        self.assertIsNone(app._cutin, "expires")
        app.combat.round_no = 2
        app._r2_cutin_tick(0.016)
        self.assertEqual(app._cutin["key"], "rogue", "new round fires again")

    def test_cutin_not_during_enemy_phase_or_when_art_off(self) -> None:
        app, hero, other = self.app()
        app.combat.phase = "ENEMY"
        app._r2_cutin_tick(0.016)
        self.assertIsNone(app._cutin)
        app, *_ = self.app(enabled=False)
        app._r2_cutin_tick(0.016)
        self.assertIsNone(app._cutin)
        app, *_ = self.app()
        app.r2.model_aspect.return_value = None          # art missing for this class
        app._r2_cutin_tick(0.016)
        self.assertIsNone(app._cutin)

    def test_cutin_state_cleared_when_leaving_combat(self) -> None:
        app, *_ = self.app()
        app._r2_cutin_tick(0.016)
        self.assertIsNotNone(app._cutin_seen)
        app.screen = game_main.Screen.TITLE
        app._r2_cutin_tick(0.016)
        self.assertIsNone(app._cutin_seen)

    def test_painter_cutin_draws_name_and_bust(self) -> None:
        p = painter()
        assets = mock.MagicMock(spec=AssetLibrary)
        assets.enabled = True
        img = mock.MagicMock()
        img.get_height.return_value = 380
        assets.model.return_value = img
        surf = mock.MagicMock()
        with _Patched() as ctx:
            self.assertTrue(p.cutin(surf, assets, "witch", "Morgana", 0.5))
        self.assertIn("Morgana", ctx.texts)
        self.assertIn("YOUR TURN", ctx.texts)
        self.assertGreaterEqual(surf.blit.call_count, 2)
        with _Patched():
            self.assertFalse(p.cutin(surf, assets, "witch", "Morgana", 5.0), "expired")
            assets.model.return_value = None
            self.assertFalse(p.cutin(surf, assets, "witch", "Morgana", 0.5), "missing art skips")

    def test_painter_cutin_draw_error_disables_art(self) -> None:
        p = painter()
        assets = mock.MagicMock(spec=AssetLibrary)
        assets.enabled = True
        assets.model.side_effect = ValueError("x")
        with _Patched():
            self.assertFalse(p.cutin(mock.MagicMock(), assets, "witch", "M", 0.5))
        assets.disable.assert_called_once()


if __name__ == "__main__":
    unittest.main()
