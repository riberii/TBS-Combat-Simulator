"""Drives GameApp's card-draft flow under the DEV-ONLY pygame emulation (not real Pygame). Prints JSON; exit 0 on pass."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "devpygame"))
sys.path.insert(1, str(ROOT))
os.environ.setdefault("COAC_PREVIEW", "1")
_home = tempfile.mkdtemp(prefix="coac_draft_home_")
for k in ("HOME", "XDG_DATA_HOME", "APPDATA"):
    os.environ[k] = _home

import pygame  # noqa: E402
assert getattr(pygame, "IS_EMULATION", False)
pygame.mixer.available = False
import main as game  # noqa: E402
from tools.render_preview import start_party  # noqa: E402


def key(app, k):
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k)) if hasattr(app, "handle_event") else app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=k))


def fresh(stage=3, seed=None):
    app = game.GameApp()
    start_party(app, ["WITCH", "ANGEL"])
    app.state.stage = stage
    if seed is not None:
        app.state.seed = seed
    assert app._start_draft()
    return app


def main() -> int:
    res = {}
    app = fresh(seed=1234)
    res["opens"] = app.screen is game.Screen.DRAFT and len(app.draft_session.options) >= 2
    a2 = fresh(seed=1234)
    res["deterministic"] = [o.key for o in app.draft_session.options] == [o.key for o in a2.draft_session.options]
    # Skip -> +gold, back to hub.
    gold = app.state.gold
    app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    res["skip"] = app.state.gold == gold + game.DRAFT_SKIP_GOLD and app.screen is game.Screen.HUB and app.draft_session is None
    # Take the first card/relic option.
    app = fresh()
    hero = app.state.players[app.draft_session.hero_index]
    n = len(hero.deck_cards); relics = len(app.state.relics)
    idx = next((i for i, o in enumerate(app.draft_session.options) if o.kind in ("card", "relic")), None)
    if idx is None:
        res["take"] = True
    else:
        app.draft_session.idx = idx
        app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        res["take"] = (len(hero.deck_cards) == n + 1 or len(app.state.relics) == relics + 1) and app.screen is game.Screen.HUB
    # Deck mode: upgrade then back out with ESC.
    app = fresh()
    app.draft_session.mode, app.draft_session.action, app.draft_session.sub_idx = "deck", "upgrade", 0
    hero = app.state.players[app.draft_session.hero_index]
    before = list(hero.deck_cards)
    app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    res["upgrade"] = hero.deck_cards[0].endswith("+") and hero.deck_cards[1:] == before[1:] and app.screen is game.Screen.HUB
    app = fresh()
    app.draft_session.mode, app.draft_session.action = "deck", "purge"
    app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    res["esc_back"] = app.draft_session.mode == "pick" and app.screen is game.Screen.DRAFT
    # Shrine: opens from the hub, walk-away is free, an accepted bargain is spent once per hall.
    app = fresh(stage=3, seed=77)
    app._finish_draft("")
    res["hub_shrine_item"] = any(i.tag == "shrine" and i.enabled for i in app.hub_menu.items)
    assert app._start_shrine()
    res["shrine_opens"] = app.screen is game.Screen.DRAFT and app.draft_session.source == "shrine" and len(app.draft_session.options) == 3
    app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    res["shrine_walk_away_free"] = app.screen is game.Screen.HUB and app.state.shrine_stage == 0
    app.state.gold = 1000
    app._start_shrine()
    app.draft_session.idx = next(i for i, o in enumerate(app.draft_session.options) if o.key in ("gilded_penance", "choirs_gamble", "burnt_offering"))
    app._key_draft(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    res["shrine_accept_spends_hall"] = app.state.shrine_stage == 3 and app.screen is game.Screen.HUB
    res["shrine_once_per_hall"] = (not app._start_shrine()) and any(i.tag == "shrine" and not i.enabled for i in app.hub_menu.items)
    print(json.dumps(res))
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
