"""Render GameApp screens to PNG using the DEV-ONLY PIL pygame emulation (tools/devpygame).

NOT a real Pygame-ce capture. Use it to catch Python errors in draw paths and to eyeball layout. Output
names carry the suffix ``_emulated`` so they can never be mistaken for real screenshots.
Usage: python tools/render_preview.py OUTDIR [screen ...]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "devpygame"))
sys.path.insert(1, str(ROOT))
os.environ.setdefault("COAC_PREVIEW", "1")
_home = tempfile.mkdtemp(prefix="coac_preview_home_")
os.environ["HOME"] = _home
os.environ["XDG_DATA_HOME"] = _home
os.environ["APPDATA"] = _home

import pygame  # noqa: E402  (the emulation, by sys.path order)
assert getattr(pygame, "IS_EMULATION", False), "emulation not active"
pygame.mixer.available = False
import main as game  # noqa: E402


def snap(app, path: Path, frames: int = 3) -> None:
    for _ in range(frames):
        app.update(1 / 30)
        app.draw()
    pygame.image.save(app.display, str(path))


def start_party(app, classes: list[str], difficulty: str = "Easy") -> None:
    names = [c.name for c in app.classes]
    app.setup.size = len(classes)
    for i, c in enumerate(classes):
        app.setup.class_idx[i] = names.index(c)
        app.setup.names[i] = ""
    app.run_mode = "endless"
    app._start_run(difficulty)


SCREENS = ("title", "setup", "combat", "combat_blackout", "restraints", "trials", "draft", "shrine", "boss", "fx", "hub", "rewards", "shop", "victory", "defeat", "combat_solo", "hand_peek", "hand_focus", "hand_target", "hand_piles", "hand_play", "mode", "settings", "skill_tree", "wardrobe", "tutorials")


def main(argv: list[str]) -> int:
    out = Path(argv[0] if argv else "preview_out")
    want = set(argv[1:]) or set(SCREENS)
    out.mkdir(parents=True, exist_ok=True)
    app = game.GameApp(seed=20261026)
    S = game.Screen
    if "title" in want:
        snap(app, out / "title_emulated.png"); print("title ok")
    if "setup" in want:
        app.screen = S.SETUP; snap(app, out / "setup_emulated.png"); print("setup ok")
    if "mode" in want:
        app.screen = S.MODE_SELECT; snap(app, out / "mode_emulated.png"); print("mode ok")
    if "settings" in want:
        app.screen = S.SETTINGS; snap(app, out / "settings_emulated.png"); print("settings ok")
    if "skill_tree" in want:
        app.screen = S.SKILL_TREE; snap(app, out / "skill_tree_emulated.png"); print("skill_tree ok")
    if "wardrobe" in want:
        app.screen = S.WARDROBE; snap(app, out / "wardrobe_emulated.png"); print("wardrobe ok")
    if "tutorials" in want:
        app.screen = S.TUTORIALS; snap(app, out / "tutorials_emulated.png"); print("tutorials ok")
    if "combat" in want:
        start_party(app, ["ANGEL", "WARRIOR", "WITCH"])
        snap(app, out / "combat_emulated.png", 6); print("combat ok")
    if "combat_blackout" in want:
        # Sensory Deprivation on the acting Fallen Angel: enemy intent must be fully blacked out.
        from entities.player import FallenAngel, Restraint
        start_party(app, ["ANGEL", "WARRIOR"])
        for _ in range(40):
            app.update(1 / 30)
        angel = next(p for p in app.state.players if isinstance(p, FallenAngel))
        angel.restraints.add(Restraint.DEPRIVATION) if hasattr(angel.restraints, "add") else angel.restraints.append(Restraint.DEPRIVATION)
        app.combat.active = angel
        app.combat._refresh_intents(force=True)
        snap(app, out / "combat_blackout_emulated.png", 4); print("combat_blackout ok",
             "hidden=", app.combat.intent_hidden)
    if "restraints" in want:
        from entities.player import Restraint
        start_party(app, ["ANGEL", "WARRIOR"])
        app.state.players[0].restraints = {Restraint.MANACLES, Restraint.IRON_GAG, Restraint.BARBED_WINGS, Restraint.SABATONS}
        snap(app, out / "restraints_emulated.png", 4); print("restraints ok")
        app.show_journal = True
        snap(app, out / "journal_emulated.png", 2); print("journal ok")
        app.show_journal = False
    if "trials" in want:
        import random
        from systems.combat_system import Phase
        from systems.restraint_trials import TRIAL_BY_ID, run_script
        start_party(app, ["ANGEL", "WARRIOR"])
        for _ in range(30):
            app.update(1 / 30)
        for tid, tier, part in (("thrash_anchor", 2, 0.4), ("alt_manacles", 2, 0.4), ("rhythm_wings", 2, 0.5), ("rune_mirror", 3, 0.0),
                                ("sigil_court", 3, 0.0), ("seam_triple", 2, 0.3), ("word_gag", 3, 0.3), ("counter_wings", 3, 0.3), ("seal_three", 4, 0.3)):
            d = TRIAL_BY_ID.get(tid)
            if d is None:
                continue
            tr = d.build(random.Random(4), tier)
            script = [x for x in tr.solution_script() if x[0] < tr.limit * part * 0.5]
            for when, key, text in script:
                while tr.elapsed < when and not tr.done:
                    tr.update(1 / 60)
                tr.handle_key(key, text)
            app.combat.qte = tr
            app.combat.phase = Phase.QTE
            snap(app, out / f"trial_{tid}_emulated.png", 2); print("trial", tid, "ok")
    if "draft" in want:
        start_party(app, ["WITCH", "ANGEL"])
        app.state.stage = 5
        assert app._start_draft(), "draft should open"
        snap(app, out / "draft_emulated.png", 3); print("draft ok")
        app.draft_session.mode, app.draft_session.action = "deck", "upgrade"
        snap(app, out / "draft_deck_emulated.png", 2); print("draft_deck ok")
    if want & {"hub", "rewards", "shop", "victory", "defeat"}:
        start_party(app, ["WARRIOR", "KITSUNE", "DRAGONKIN"])
        app.state.stage = 4
        if "hub" in want:
            app._to_hub(); snap(app, out / "hub_emulated.png", 3); print("hub ok")
        if "rewards" in want:
            app.reward_lines = ["Victory! +35 gold, +40 XP each.", "Loot: Ember Charm", "Witch reached level 3!"]
            app.screen = game.Screen.REWARDS; snap(app, out / "rewards_emulated.png", 3); print("rewards ok")
        if "shop" in want:
            app._to_hub(); app.state.gold = 140
            app.hub_menu.index = 0
            app._key_hub(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
            snap(app, out / "shop_emulated.png", 3); print("shop ok", app.screen)
        if "victory" in want:
            app._finish(True); snap(app, out / "victory_emulated.png", 4); print("victory ok")
        if "defeat" in want:
            app._finish(False); snap(app, out / "defeat_emulated.png", 4); print("defeat ok")
    if "fx" in want:
        start_party(app, ["ANGEL", "WITCH"])
        snap(app, out / "_warm.png", 2)
        anchors = dict(app.vfx.anchors)
        foes = [e.uid for e in app.state.enemies][:1]
        pl = [p.uid for p in app.state.players]
        for dn in ("FIRE", "FROST", "STORM", "HOLY", "SHADOW"):
            pass
        pos = [(760, 330), (860, 330), (960, 330), (1060, 330), (1160, 330)]
        for dn, ps in zip(("FIRE", "FROST", "STORM", "HOLY", "SHADOW"), pos):
            app.vfx.spawn_element_fx(dn, ps)
        app.vfx.spawn_ring_fx("bind", (260, 360))
        app.vfx.spawn_ring_fx("free", (420, 360))
        app.vfx.spawn_ring_fx("backlash", (560, 360))
        for sp in app.vfx.sprites:
            sp.life = sp.max_life * 0.7
            if sp.anim is not None:
                sp.anim.elapsed = sp.anim.duration * 0.3
        app.paused = False
        pygame.image.save(app.display, str(out / "_pre.png"))
        app.draw()
        pygame.image.save(app.display, str(out / "fx_emulated.png")); print("fx ok", len(app.vfx.sprites))
    if "shrine" in want:
        start_party(app, ["WARRIOR", "ANGEL"])
        app.state.stage = 3
        app.state.gold = 200
        assert app._start_shrine()
        snap(app, out / "shrine_emulated.png", 3); print("shrine ok")
    if "boss" in want:
        start_party(app, ["WARRIOR", "ANGEL"])
        app.state.stage = 7
        app._start_combat(app.state.spawn_encounter() or "")
        assert app.boss_intro is not None, "stage 8 should be a boss"
        app.boss_intro["t"] = 2.0
        snap(app, out / "boss_intro_emulated.png", 2); print("boss ok", app.boss_intro and app.boss_intro["name"])
        app.boss_intro = None
        snap(app, out / "boss_combat_emulated.png", 3)
    if "combat_solo" in want:
        start_party(app, ["VAMPIRE"])
        snap(app, out / "combat_solo_emulated.png", 6); print("combat_solo ok")
    if want & {"hand_peek", "hand_focus", "hand_target", "hand_piles", "hand_play"}:
        from systems.combat_system import Phase

        def hero_turn(classes):
            start_party(app, classes)
            c = app.combat
            for _ in range(600):
                app.update(1 / 30)
                if c.phase is Phase.MENU and c.card_battles.get(c.active.uid) is not None:
                    break
            for _ in range(40):                      # let the opening deal settle
                app.update(1 / 30)
                app.draw()
            return c

        if "hand_peek" in want:
            hero_turn(["ANGEL", "WARRIOR", "WITCH"])
            snap(app, out / "hand_peek_emulated.png", 2); print("hand_peek ok")
        if "hand_focus" in want:
            c = hero_turn(["ANGEL", "WARRIOR", "WITCH"])
            c.handle_key("tab"); c.handle_key("right"); c.handle_key("right")
            snap(app, out / "hand_focus_emulated.png", 30); print("hand_focus ok")
        if "hand_target" in want:
            c = hero_turn(["WARRIOR", "WITCH"])
            import copy
            from entities.base_entity import BaseEntity
            twin = copy.deepcopy(app.state.enemies[0]); twin.uid = next(BaseEntity._uids); twin.name = "Gutter Wolf II"
            app.state.enemies.append(twin)
            cb = c.card_battles[c.active.uid]
            cb.hand = ["strike", "brace", "mark_prey", "break_mark", "catch_breath"][:len(cb.hand) or 5]
            c.active.stamina = 100
            c.handle_key("tab"); c.handle_key("return")
            snap(app, out / "hand_target_emulated.png", 30); print("hand_target ok", c.phase.name)
        if "hand_piles" in want:
            c = hero_turn(["WITCH"])
            c.handle_key("v")
            snap(app, out / "hand_piles_emulated.png", 3); print("hand_piles ok")
        if "hand_play" in want:
            c = hero_turn(["WARRIOR"])
            cb = c.card_battles[c.active.uid]
            cb.hand = ["strike", "brace", "mark_prey", "break_mark", "rending_cleave"]
            c.active.stamina = 100
            c.handle_key("tab"); c.handle_key("return")
            if c.phase is Phase.TARGET:
                c.handle_key("return")
            snap(app, out / "hand_play_emulated.png", 6); print("hand_play ok", c.phase.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
