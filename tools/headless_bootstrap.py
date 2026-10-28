"""Import-only Pygame stub for validation on hosts without pygame-ce.

This stub supplies names needed while modules/classes are imported. It deliberately
cannot create surfaces or exercise drawing/input; it must never be used for live play.
"""
from __future__ import annotations

import sys
import types


def install_import_stub_if_missing() -> bool:
    try:
        import pygame  # noqa: F401
        return False
    except ImportError:
        pass
    pg = types.ModuleType("pygame")
    pg.Surface = type("Surface", (), {})
    pg.Rect = type("Rect", (), {})
    pg.error = Exception
    pg.SRCALPHA = 1
    pg.BLEND_RGB_ADD = 1
    pg.BLEND_RGBA_MULT = 2
    pg.KEYDOWN = 2
    pg.QUIT = 12
    pg.K_UP, pg.K_DOWN, pg.K_LEFT, pg.K_RIGHT = 273, 274, 276, 275
    pg.K_w, pg.K_a, pg.K_s, pg.K_d = 119, 97, 115, 100
    pg.K_TAB, pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE = 9, 13, 271, 32
    pg.K_ESCAPE, pg.K_e, pg.K_F2, pg.K_p, pg.K_BACKSPACE = 27, 101, 283, 112, 8
    pg.K_F11 = 1073741892
    pg.transform = types.SimpleNamespace()
    pg.font = types.SimpleNamespace(Font=type("Font", (), {}))
    pg.event = types.SimpleNamespace(Event=type("Event", (), {}))
    # Same key-name mapping as the real pygame.key.name for the keys the game reads, so tests do not
    # depend on which stub happened to be installed first.
    pg.key = types.SimpleNamespace(name=lambda key: {
        pg.K_RETURN: "return", pg.K_KP_ENTER: "kp enter", pg.K_SPACE: "space",
        pg.K_UP: "up", pg.K_DOWN: "down", pg.K_LEFT: "left", pg.K_RIGHT: "right",
        pg.K_e: "e", pg.K_ESCAPE: "escape", pg.K_BACKSPACE: "backspace",
        pg.K_TAB: "tab", pg.K_w: "w", pg.K_a: "a", pg.K_s: "s", pg.K_d: "d", pg.K_p: "p",
    }.get(key, str(key)))
    sys.modules["pygame"] = pg
    return True
