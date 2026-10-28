"""File-backed save, menu integration, and endless-progression regression tests.

Run with: python -m unittest discover -s tests -v

If Pygame-CE is unavailable, a minimal import-only module is installed before importing
player/UI code. GameState, SaveManager, Enemy and CombatSystem remain the real project code;
these tests do not replace game logic with mocks.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _install_pygame_import_stub_if_missing() -> None:
    try:
        import pygame  # noqa: F401
        return
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
    pg.transform = types.SimpleNamespace()
    pg.font = types.SimpleNamespace(Font=type("Font", (), {}))
    pg.event = types.SimpleNamespace(Event=type("Event", (), {}))
    pg.key = types.SimpleNamespace(name=lambda key: {
        pg.K_RETURN: "return", pg.K_KP_ENTER: "kp enter", pg.K_SPACE: "space",
        pg.K_UP: "up", pg.K_DOWN: "down", pg.K_LEFT: "left", pg.K_RIGHT: "right",
        pg.K_e: "e", pg.K_ESCAPE: "escape", pg.K_BACKSPACE: "backspace",
    }.get(key, str(key)))
    sys.modules["pygame"] = pg


_install_pygame_import_stub_if_missing()

from core.config import PlayerClass, max_single_hit  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.enemy import BOSS_ROSTER  # noqa: E402
from entities.base_entity import Status  # noqa: E402
from systems.combat_system import CombatEvent, CombatSystem, EventKind  # noqa: E402
from systems.save_system import SaveCorruptError, SaveManager, SlotStatus  # noqa: E402
from systems.inventory_system import Shop  # noqa: E402
from entities.player import Dragonkin, FallenAngel, Kitsune, Vampire, Restraint  # noqa: E402
from systems.leaderboard import LeaderboardError, LocalLeaderboard  # noqa: E402
from systems.settings_system import SettingsError, SettingsStore  # noqa: E402
from ui.vfx import FLOATER_STACK_MAX, MAX_FLOATERS, TOAST_MAX, TOAST_MAX_W, VFX  # noqa: E402
from ui.renderer import Character, CharacterKind, SpritePainter  # noqa: E402
import main  # noqa: E402


SLOT_NAMES = ("autosave", "slot1", "slot2", "slot3")


def make_state(seed: int, classes: tuple[PlayerClass, ...], stage: int, gold: int,
               difficulty: str = "Normal") -> GameState:
    state = GameState(seed=seed)
    configs = [PlayerConfig(f"Hero{i + 1}", pclass) for i, pclass in enumerate(classes)]
    state.new_run(configs, difficulty, endless=True)
    # Test every serialized difficulty value independently of the Fallen Angel's
    # intentional difficulty bump at new-run creation.
    state.difficulty_name = difficulty
    state.stage = stage
    state.best_stage = stage + 2
    state.gold = gold
    state.modifiers = [m.key for m in state._plan_modifiers(stage)] if stage > 12 else []
    state.inventory.add("health", min(1 + seed % 3, 4))
    state.inventory.add("mana", 1 + seed % 2)
    state.inventory.add("smoke", 1)
    for index, hero in enumerate(state.players):
        hero.hp = max(1, hero.max_hp - (seed % 11 + index + 1))
        hero.stamina = max(0, min(hero.max_stamina, hero.stamina - (seed % 7 + index + 1)))
        hero.mana = max(0, min(hero.max_mana, hero.mana - (seed % 5 + index + 1)))
        hero.level = 2 + index + (seed % 2)
        hero.xp = 13 + index * 9 + seed % 17
        hero.base_attack += seed % 6 + index
        hero.base_defense += seed % 4 + index
        hero.speed += index
        if isinstance(hero, FallenAngel):
            hero.lucidity = max(0.0, hero.lucidity - (seed % 13 + index + 1))
            # Keep the saved Angel empty by default to exercise empty-enum-container round-trips.
            hero.restraints.clear()
    return state


def make_app(saves: SaveManager) -> main.GameApp:
    """Create the real GameApp class without opening a graphical window."""
    app = main.GameApp.__new__(main.GameApp)
    app.saves = saves
    app._combat_cls = CombatSystem
    app.leaderboard = LocalLeaderboard(saves.save_dir / "leaderboard.json")
    app.run_mode = "endless"
    app.leaderboard_filter = "all"
    app.slot_info = {}
    app.slot_details = {}
    app.slot_known = False
    app.popups = []
    app.audio = main._SilentAudio()
    app._visual_restraint_map = {}
    app.chars = []
    app.state = None
    app.combat = None
    app.shop = None
    app.paused = False
    app.victory_claimed = False
    app.reward_lines = []
    app.won = False
    app.running = True
    app.screen = main.Screen.TITLE
    app._to_title()
    return app


class FileBackedSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.saves = SaveManager(self.temp.name, slot_names=SLOT_NAMES)

    def test_four_real_slots_round_trip_distinct_game_states(self) -> None:
        fixtures = [
            make_state(101, (PlayerClass.ANGEL, PlayerClass.WITCH), 15, 811, "Easy"),
            make_state(202, (PlayerClass.WARRIOR,), 5, 922, "Normal"),
            make_state(303, (PlayerClass.ROGUE, PlayerClass.TANK), 8, 1033, "Hard"),
            make_state(404, (PlayerClass.WITCH, PlayerClass.ANGEL, PlayerClass.WARRIOR), 18, 1144, "Insane"),
        ]
        for slot, state in enumerate(fixtures, start=1):
            saved = self.saves.save(slot, state)
            self.assertEqual(saved.status, SlotStatus.VALID)
            time.sleep(0.012)  # avoid timestamp ties in a fast CI filesystem

        infos = self.saves.list_slots()
        self.assertEqual([i.status for i in infos], [SlotStatus.VALID] * 4)
        for slot, original in enumerate(fixtures, start=1):
            with self.subTest(slot=slot):
                loaded = self.saves.load(slot)
                self.assertEqual(len(loaded.players), len(original.players))
                for actual, expected in zip(loaded.players, original.players):
                    for attr in ("pclass", "name", "max_hp", "hp", "base_attack", "base_defense", "speed",
                                 "max_stamina", "stamina", "max_mana", "mana", "level", "xp", "cooldowns",
                                 "statuses", "burn_power"):
                        self.assertEqual(getattr(actual, attr), getattr(expected, attr),
                                         f"slot {slot}: {attr} did not round-trip for {expected.name}")
                    if isinstance(expected, FallenAngel):
                        self.assertEqual(actual.restraints, expected.restraints)
                        self.assertEqual(actual.lucidity, expected.lucidity)
                self.assertEqual(loaded.gold, original.gold)
                self.assertEqual(loaded.stage, original.stage)
                self.assertEqual(loaded.best_stage, original.best_stage)
                self.assertEqual(loaded.difficulty_name, original.difficulty_name)
                self.assertEqual(loaded.endless, original.endless)
                self.assertEqual(loaded.modifiers, original.modifiers)
                self.assertEqual(loaded.inventory.count("health"), original.inventory.count("health"))
                self.assertEqual(loaded.inventory.count("mana"), original.inventory.count("mana"))
                self.assertEqual(loaded.inventory.count("smoke"), original.inventory.count("smoke"))
                self.assertEqual(loaded.players[0].hp, original.players[0].hp)
                self.assertEqual(loaded.players[0].stamina, original.players[0].stamina)
                self.assertEqual(loaded.players[0].mana, original.players[0].mana)
        angel = self.saves.load(1).players[0]
        self.assertIsInstance(angel, FallenAngel)
        self.assertEqual(angel.restraints, set())
        self.assertGreaterEqual(len(self.saves.slot_names), 4)

    def test_all_party_sizes_and_all_eight_classes_round_trip(self) -> None:
        all_classes = tuple(PlayerClass)
        self.assertEqual(len(all_classes), 8, "expected the complete eight-class v2.0 roster")
        for idx, pclass in enumerate(all_classes):
            with self.subTest(single_class_round_trip=pclass.value):
                state = make_state(680 + idx, (pclass,), 2, 120 + idx)
                if pclass is PlayerClass.VAMPIRE:
                    state.players[0].blood = 73
                elif pclass is PlayerClass.DRAGONKIN:
                    state.players[0].heat = 81
                    state.players[0].overheated_turns = 1
                loaded = GameState.from_dict(state.to_dict())
                self.assertEqual(loaded.players[0].pclass, pclass)
                if pclass is PlayerClass.VAMPIRE:
                    self.assertEqual(loaded.players[0].blood, 73)
                elif pclass is PlayerClass.DRAGONKIN:
                    self.assertEqual((loaded.players[0].heat, loaded.players[0].overheated_turns), (81, 1))
        parties = (
            (all_classes[0],),
            (all_classes[1], all_classes[2]),
            (all_classes[3], all_classes[4], all_classes[0]),
        )
        for slot, party in enumerate(parties, start=1):
            with self.subTest(party_size=len(party)):
                state = make_state(700 + slot, party, 13 + slot, 400 + slot, "Hard")
                self.saves.save(slot, state)
                loaded = self.saves.load(slot)
                self.assertEqual([p.pclass for p in loaded.players], list(party))
                self.assertEqual(len(loaded.players), len(party))
                for actual, expected in zip(loaded.players, state.players):
                    self.assertEqual((actual.hp, actual.stamina, actual.mana, actual.level, actual.xp),
                                     (expected.hp, expected.stamina, expected.mana, expected.level, expected.xp))

    def test_nonempty_restraints_and_lucidity_round_trip(self) -> None:
        state = make_state(505, (PlayerClass.ANGEL, PlayerClass.WITCH), 16, 717, "Hard")
        angel = state.players[0]
        self.assertIsInstance(angel, FallenAngel)
        angel.restraints.update({Restraint.ANCHOR, Restraint.MANACLES})
        angel.lucidity = 23.5
        self.saves.save(1, state)
        loaded = self.saves.load(1)
        self.assertEqual(loaded.players[0].restraints, {Restraint.ANCHOR, Restraint.MANACLES})
        self.assertEqual(loaded.players[0].lucidity, 23.5)

    def test_continue_uses_latest_valid_manual_slot_and_menu_saves_loads(self) -> None:
        states = [
            make_state(11, (PlayerClass.WARRIOR,), 4, 111, "Easy"),
            make_state(22, (PlayerClass.TANK,), 7, 222, "Normal"),
            make_state(33, (PlayerClass.ROGUE,), 9, 333, "Hard"),
        ]
        self.saves.save(2, states[0])
        time.sleep(0.02)
        self.saves.save(3, states[1])
        time.sleep(0.02)
        self.saves.save(4, states[2])
        info, latest = self.saves.continue_latest()
        self.assertEqual(info.index, 4)
        self.assertEqual(latest.gold, 333)

        app = make_app(self.saves)
        continue_item = next(item for item in app.title_menu.items if item.tag == "continue")
        self.assertTrue(continue_item.enabled, "manual saves must enable Continue even with empty autosave")
        # Exercise the actual title-menu keyboard path, not a replacement callback.
        app._key_title(SimpleNamespace(key=sys.modules["pygame"].K_DOWN, unicode=""))
        app._key_title(SimpleNamespace(key=sys.modules["pygame"].K_RETURN, unicode=""))
        self.assertEqual(app.state.gold, 333)
        self.assertEqual(app.screen, main.Screen.HUB)

        # The Save Game menu selection must invoke SaveManager.save on its selected slot.
        app.state = make_state(44, (PlayerClass.WITCH,), 19, 1444, "Insane")
        app._open_slots("save", main.Screen.HUB)
        self.assertEqual(app.slot_mode, "save")
        app._key_slots(SimpleNamespace(key=sys.modules["pygame"].K_RETURN, unicode=""))
        self.assertEqual(app.screen, main.Screen.HUB)
        self.assertEqual(self.saves.load(2).gold, 1444)

        # The Load Game menu must call the real SaveManager.load and restore state.
        app._open_slots("load", main.Screen.TITLE)
        app.slot_menu.idx = 1  # autosave is empty; manual Slot 1 is the next row
        app._key_slots(SimpleNamespace(key=sys.modules["pygame"].K_RETURN, unicode=""))
        self.assertEqual(app.state.gold, 1444)
        self.assertEqual(app.screen, main.Screen.HUB)

    def test_saving_over_a_damaged_slot_quarantines_it_and_keeps_the_good_backup(self) -> None:
        self.saves.save(2, make_state(71, (PlayerClass.WARRIOR,), 3, 701))
        self.saves.save(2, make_state(71, (PlayerClass.WARRIOR,), 4, 702))  # first save becomes the .bak
        damaged = "{ half written save"
        path = self.saves.slot_path(2)
        path.write_text(damaged, encoding="utf-8")
        self.saves.save(2, make_state(71, (PlayerClass.WARRIOR,), 5, 703))
        quarantined = sorted(path.parent.glob(f"{path.name}.corrupt-*"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_text(encoding="utf-8"), damaged)
        self.assertEqual(self.saves.load(2).gold, 703)
        self.assertEqual(self.saves.load(2, allow_backup=True).gold, 703)  # primary valid again
        backup = path.with_name(path.name + ".bak")
        self.assertTrue(backup.is_file(), "damaged file must never replace the last good backup")

    def test_floating_numbers_and_particles_stay_bounded_and_expire(self) -> None:
        from systems.combat_system import CombatEvent, EventKind
        vfx = VFX({"big": object(), "mid": object()})
        vfx.anchors = {7: (300.0, 300.0)}
        events = [CombatEvent(EventKind.DAMAGE if i % 2 else EventKind.CRIT, uid=7, amount=10 + i) for i in range(200)]
        vfx.consume(events)
        self.assertLessEqual(len(vfx.floaters), MAX_FLOATERS)
        self.assertLessEqual(len(vfx.particles), 400)
        self.assertGreaterEqual(min(f.y for f in vfx.floaters), 300.0 - FLOATER_STACK_MAX * 22 - 1)
        vfx.update(5.0)
        self.assertEqual(vfx.floaters, [])
        self.assertEqual(vfx.particles, [])

    def test_reduced_motion_spawns_no_particles_but_keeps_damage_numbers(self) -> None:
        from systems.combat_system import CombatEvent, EventKind
        vfx = VFX({"big": object(), "mid": object()})
        vfx.reduced_motion = True
        vfx.anchors = {7: (300.0, 300.0)}
        vfx.consume([CombatEvent(EventKind.DAMAGE, uid=7, amount=12), CombatEvent(EventKind.SHAKE, power=1.0)])
        self.assertEqual(vfx.particles, [])
        self.assertEqual(vfx.trauma, 0.0)
        self.assertEqual(vfx.offset(), (0, 0))
        self.assertEqual(len(vfx.floaters), 1, "damage information must survive reduced motion")

    def test_victory_rewards_cannot_be_claimed_twice_for_one_wave(self) -> None:
        state = make_state(81, (PlayerClass.WARRIOR,), 2, 100)
        state.spawn_encounter()
        first = state.claim_victory()
        gold_after_first = state.gold
        xp_after_first = state.players[0].xp
        self.assertTrue(first)
        self.assertEqual(state.claim_victory(), [])
        self.assertEqual(state.gold, gold_after_first)
        self.assertEqual(state.players[0].xp, xp_after_first)
        state.spawn_encounter()  # the next wave pays out normally
        self.assertTrue(state.claim_victory())
        self.assertGreater(state.gold, gold_after_first)

    def test_corrupt_slot_is_reported_and_continue_falls_back(self) -> None:
        self.saves.save(2, make_state(61, (PlayerClass.WARRIOR,), 6, 611))
        time.sleep(0.02)
        self.saves.save(4, make_state(62, (PlayerClass.WITCH,), 9, 622))
        self.saves.slot_path(4).write_text("{ definitely not json", encoding="utf-8")
        info = self.saves.inspect(4)
        self.assertEqual(info.status, SlotStatus.CORRUPT)
        with self.assertRaises(SaveCorruptError):
            self.saves.load(4)
        fallback_info, fallback_state = self.saves.continue_latest()
        self.assertEqual(fallback_info.index, 2)
        self.assertEqual(fallback_state.gold, 611)

        app = make_app(self.saves)
        app._open_slots("load", main.Screen.TITLE)
        corrupt_index = next(i for i, item in enumerate(app.slot_menu.items) if item.tag == "4")
        self.assertIn("corrupt", app.slot_menu.items[corrupt_index].label.lower())
        self.assertTrue(app.slot_menu.items[corrupt_index].enabled)
        app.slot_menu.idx = corrupt_index
        app._key_slots(SimpleNamespace(key=sys.modules["pygame"].K_RETURN, unicode=""))
        self.assertEqual(app.screen, main.Screen.SLOTS)
        self.assertTrue(any("Load failed" in p.text for p in app.popups))


class EndlessAndCombatRegressionTests(unittest.TestCase):
    def test_combat_initializes_for_all_classes_and_party_sizes(self) -> None:
        class_sets = [(pclass,) for pclass in PlayerClass]
        class_sets.extend([
            (PlayerClass.WARRIOR, PlayerClass.WITCH),
            (PlayerClass.ANGEL, PlayerClass.TANK, PlayerClass.ROGUE),
        ])
        for seed, classes in enumerate(class_sets, start=1):
            with self.subTest(classes=classes):
                state = GameState(seed=12000 + seed)
                state.new_run([PlayerConfig(f"Hero{i + 1}", cls) for i, cls in enumerate(classes)], "Normal")
                state.spawn_encounter()
                combat = CombatSystem(state)
                self.assertEqual([p.pclass for p in state.players], list(classes))
                self.assertTrue(state.enemies)
                self.assertTrue(combat.players_alive())
                events = combat.drain()
                self.assertFalse(
                    [event for event in events if event.kind is EventKind.ERROR],
                    f"combat initialization emitted an error for {classes}",
                )
                if getattr(combat.phase, "name", "") == "MENU":
                    self.assertTrue(any(item.enabled for item in combat.menu))

    def test_endless_bosses_keep_rotating_after_stage_twelve(self) -> None:
        names = []
        for stage in (16, 20, 24, 28):
            state = make_state(stage, (PlayerClass.WARRIOR,), stage - 1, 100, "Normal")
            banner = state.spawn_encounter()
            self.assertTrue(state.is_boss_stage(stage))
            self.assertEqual(state.stage, stage)
            self.assertEqual(len(state.enemies), 1)
            self.assertTrue(state.enemies[0].boss)
            self.assertIn(state.enemies[0].profile, BOSS_ROSTER)
            self.assertTrue(banner)
            names.append(state.enemies[0].name)
        self.assertEqual(len(set(names)), 4, f"boss identities did not rotate: {names}")
        self.assertTrue(all(state_stage not in (13, 14, 15, 17, 18, 19) for state_stage in (16, 20, 24, 28)))

    def test_endless_regular_waves_and_modifiers_vary(self) -> None:
        state = make_state(8128, (PlayerClass.WARRIOR, PlayerClass.WITCH), 12, 120, "Normal")
        regular_combos = set()
        modifier_sets = set()
        reward_multipliers = set()
        for stage in range(13, 24):
            state.stage = stage - 1
            state.spawn_encounter()
            self.assertEqual(state.stage, stage)
            modifier_sets.add(tuple(state.modifiers))
            reward_multipliers.add(state._reward_multipliers())
            if not state.is_boss_stage(stage):
                regular_combos.add(tuple(enemy.arch.key for enemy in state.enemies))
        self.assertGreater(len(regular_combos), 1, "endless waves should vary their archetype mix")
        self.assertGreater(len(modifier_sets), 1, "endless modifiers should vary by stage")
        self.assertGreater(len(reward_multipliers), 1, "endless reward multipliers should vary")
        self.assertTrue(state.is_boss_stage(999) is False)  # cadence continues, it does not stop at 12
        self.assertTrue(state.is_boss_stage(1000))

    def test_enemy_single_hit_damage_is_capped_and_emits_lucidity_events(self) -> None:
        state = make_state(9001, (PlayerClass.ANGEL,), 5, 50, "Normal")
        state.spawn_encounter()
        hero = state.players[0]
        self.assertIsInstance(hero, FallenAngel)
        combat = CombatSystem(state)
        foe = state.enemies[0]
        foe.base_attack = 100_000
        before = hero.hp
        combat._enemy_hit(foe, hero, 100.0, heavy=True)
        dealt = before - hero.hp
        self.assertLessEqual(dealt, max_single_hit(hero.max_hp))
        self.assertEqual(dealt, max_single_hit(hero.max_hp))
        kinds = [event.kind for event in combat.drain()]
        self.assertIn(EventKind.DAMAGE, kinds)
        # A binding curse emits both restraint and lucidity events through real combat logic.
        for restraint in list(hero.restraints):
            hero.restraints.remove(restraint)
        hero.lucidity = 100.0
        combat._bind_angels(foe, 2)
        events = combat.drain()
        self.assertTrue(any(event.kind is EventKind.RESTRAINT_APPLIED for event in events))
        self.assertTrue(any(event.kind is EventKind.LUCIDITY and event.amount > 0 for event in events))

    def test_vfx_toasts_stack_with_a_cap_and_expire(self) -> None:
        vfx = VFX({"big": object(), "mid": object()})
        for i in range(8):
            self.assertTrue(vfx.push_toast(f"Combat event {i}", category="status"))
        self.assertEqual(len(vfx.toasts), TOAST_MAX, "eight distinct pushes must be capped at the authoritative TOAST_MAX")
        self.assertEqual(TOAST_MAX, 4, "documented notification policy is four visible toasts")
        # Avoid drawing/font dependencies while exercising the real lifetime and stack logic.
        for toast in vfx.toasts:
            toast.surface = SimpleNamespace(get_height=lambda: 30)
        vfx._update_toasts(10.0)
        self.assertEqual(vfx.toasts, [], "temporary popups should fade out and be removed")

    def test_vfx_anchors_real_entity_uids_and_routes_combat_popups(self) -> None:
        state = make_state(9010, (PlayerClass.WARRIOR,), 4, 80, "Normal")
        state.spawn_encounter()
        player = state.players[0]
        app = main.GameApp.__new__(main.GameApp)
        app.state = state
        app.chars = [main.Character(main._kind_for(player, 0), player.name, 150.0, 596.0, 0.95)]
        app.painter = SimpleNamespace(t=0.0)
        app.vfx = VFX({"big": object(), "mid": object()})
        app._update_vfx_anchors()
        self.assertIn(player.uid, app.vfx.anchors)
        self.assertTrue(all(enemy.uid in app.vfx.anchors for enemy in state.enemies))

        app.vfx.consume([
            CombatEvent(EventKind.DAMAGE, uid=player.uid, amount=12),
            CombatEvent(EventKind.RESTRAINT_APPLIED, uid=player.uid, amount=1, text="Anchor"),
            CombatEvent(EventKind.LUCIDITY, uid=player.uid, amount=15, text="Seraphine loses 15 lucidity"),
            CombatEvent(EventKind.GOLD, amount=130, text="+130 gold"),
        ])
        self.assertTrue(any(f.text.startswith("12") for f in app.vfx.floaters))
        categories = {toast.category for toast in app.vfx.toasts}
        self.assertTrue({"restrained", "lucidity", "reward"}.issubset(categories))

    def test_real_shop_purchase_and_enemy_turn_progression(self) -> None:
        import random
        from systems.inventory_system import Shop

        state = make_state(9020, (PlayerClass.WARRIOR, PlayerClass.WITCH), 4, 500, "Normal")
        shop = Shop(random.Random(9020), state.players)
        purchase_row = next(
            i for i, (item, price) in enumerate(shop.stock)
            if price <= state.gold and state.inventory.room(item.key) > 0 and shop.remaining(i) > 0
        )
        item, price = shop.stock[purchase_row]
        before_count = state.inventory.count(item.key)
        shop.cursor = purchase_row
        state.gold = shop.buy(state.gold, state.inventory)
        self.assertEqual(state.gold, 500 - price)
        self.assertEqual(state.inventory.count(item.key), before_count + 1)
        self.assertEqual(shop.remaining(purchase_row), shop.supply[item.key])

        state.spawn_encounter()
        combat = CombatSystem(state)
        self.assertTrue(state.enemies and combat.players_alive())
        # Drive at least one real enemy turn through CombatSystem.update instead of calling
        # the enemy action routine directly. Player turns are fast-forwarded by advancing
        # RESOLVE timers and choosing each actor's basic action when needed.
        starting_hp = sum(p.hp for p in state.players)
        enemy_uids = {foe.uid for foe in state.enemies}
        enemy_damage_events = 0
        for _ in range(250):
            phase = getattr(combat.phase, "name", str(combat.phase)).upper()
            if phase in ("VICTORY", "DEFEAT"):
                break
            if phase == "MENU":
                idx = next((i for i, m in enumerate(combat.menu)
                            if m.enabled and m.ability is not None and m.ability.key in ("attack", "slash", "strike")), None)
                if idx is None:
                    idx = next((i for i, m in enumerate(combat.menu) if m.enabled), 0)
                combat.menu_idx = idx
                combat.handle_key("return")
                if getattr(combat.phase, "name", "") == "TARGET":
                    combat.handle_key("return")
                elif getattr(combat.phase, "name", "") == "QTE":
                    q = combat.qte
                    if hasattr(q, "word"):
                        for letter in q.word:
                            combat.handle_key(letter, letter)
                    elif getattr(q, "kind", None) is not None:
                        # Don't skip an active QTE; advance it safely to its real timeout.
                        pass
            else:
                combat.update(2.0)
            enemy_damage_events += sum(
                event.kind is EventKind.DAMAGE and event.source_uid in enemy_uids
                for event in combat.drain()
            )
        self.assertTrue(
            enemy_damage_events > 0 or getattr(combat.phase, "name", "") in ("VICTORY", "DEFEAT"),
            "the real combat loop should resolve an enemy attack or reach an encounter outcome",
        )
        self.assertLessEqual(sum(p.hp for p in state.players), starting_hp,
                             "enemy actions must not increase the party's total HP")

    def test_e_key_is_not_swallowed_by_hovered_restraint_during_qte(self) -> None:
        pg = sys.modules["pygame"]
        calls = []
        combat = SimpleNamespace(phase="QTE", qte=None,
                                 handle_key=lambda key, text="": calls.append((key, text)))
        app = main.GameApp.__new__(main.GameApp)
        app.screen = main.Screen.COMBAT
        app.combat = combat
        app.paused = False
        app.audio = main._SilentAudio()
        app.renderer = SimpleNamespace(handle_event=lambda _event: self.fail("renderer must not consume QTE keys"))
        event = SimpleNamespace(type=pg.KEYDOWN, key=pg.K_e, unicode="e")
        app.handle_event(event)
        self.assertEqual(calls, [("e", "e")])


class ShopRenderingContractTests(unittest.TestCase):
    def test_shop_rows_is_a_count_and_display_rows_use_real_stock(self) -> None:
        state = make_state(987, (PlayerClass.ANGEL,), 3, 500, "Normal")
        shop = Shop(random.Random(123), state.players)
        self.assertIsInstance(shop.rows, int)
        self.assertEqual(shop.rows, len(shop.stock) + 1)
        display_rows = main._shop_display_rows(shop)
        self.assertEqual(len(display_rows), shop.rows)
        self.assertTrue(display_rows[-1][3], "last row must be Proceed")
        self.assertFalse(display_rows[shop.cursor][3])
        self.assertIs(display_rows[shop.cursor][0], shop.stock[shop.cursor][0])
        self.assertEqual(display_rows[shop.cursor][1], float(shop.stock[shop.cursor][1]))

    def test_actual_shop_painter_no_longer_iterates_integer_rows_and_draws_description(self) -> None:
        state = make_state(988, (PlayerClass.WARRIOR,), 3, 500, "Normal")
        shop = Shop(random.Random(456), state.players)
        captured: list[str] = []

        class FakeRect:
            def __init__(self, x, y, width, height):
                self.x, self.y, self.width, self.height = x, y, width, height
                self.right, self.bottom = x + width, y + height
                self.centerx, self.centery = x + width // 2, y + height // 2
                self.center = (self.centerx, self.centery)

        class FakeSurface:
            def blit(self, *_args, **_kwargs):
                return None

        class FakeFont:
            def size(self, text):
                return (len(str(text)) * 6, 12)

        painter = main.Painter.__new__(main.Painter)
        painter.veil = object()
        painter.f = {name: FakeFont() for name in ("huge", "big", "mid", "small", "tiny")}
        painter.renderer = types.SimpleNamespace(time=0.0)

        def capture(_surf, _font, text, *_args, **_kwargs):
            captured.append(str(text))
            return None

        with mock.patch.object(main.pygame, "Rect", FakeRect), \
             mock.patch.object(main, "panel", lambda *_a, **_k: None), \
             mock.patch.object(main, "draw_text", capture):
            painter.shop(FakeSurface(), shop, state)

        self.assertTrue(any("Health Potion" in text for text in captured))
        self.assertTrue(any("Restore 40% max HP" in text for text in captured))
        self.assertTrue(any("Proceed to the next stage" in text for text in captured) or
                        any("Proceed" in text for text in captured), "the shop must show a Proceed row")

    def test_action_history_persists_and_old_save_without_log_still_loads(self) -> None:
        state = make_state(989, (PlayerClass.ANGEL, PlayerClass.WITCH), 15, 740, "Hard")
        state.add_log("A chain tightens around Seraphine.", (190, 126, 255))
        state.add_log("Morrigan casts Hex Bolt.", (96, 140, 255))
        save_data = state.to_dict()
        restored = GameState.from_dict(save_data)
        self.assertEqual([entry.text for entry in restored.log], [entry.text for entry in state.log])
        self.assertEqual(restored.log[-1].color, state.log[-1].color)
        with tempfile.TemporaryDirectory() as directory:
            disk_saves = SaveManager(directory, slot_names=SLOT_NAMES)
            disk_saves.save(1, state)
            disk_restored = disk_saves.load(1)
            self.assertEqual([entry.text for entry in disk_restored.log], [entry.text for entry in state.log])
        legacy = dict(save_data)
        legacy.pop("log")
        legacy_loaded = GameState.from_dict(legacy)
        self.assertEqual(len(legacy_loaded.log), 0)

    def test_all_active_restraints_expose_labels_and_descriptions(self) -> None:
        state = make_state(990, (PlayerClass.ANGEL,), 2, 50, "Normal")
        angel = state.players[0]
        angel.restraints.update(Restraint)
        details = main._active_restraint_details(angel)
        self.assertEqual(len(details), len(Restraint))
        self.assertEqual({label for label, _desc in details}, {r.label for r in Restraint})
        self.assertTrue(all(desc for _label, desc in details))

    def test_always_visible_sidebar_renders_history_and_all_six_restraint_descriptions(self) -> None:
        state = make_state(993, (PlayerClass.ANGEL,), 2, 50, "Normal")
        angel = state.players[0]
        angel.restraints.update(Restraint)
        for i in range(5):
            state.add_log(f"Past action {i}: the party presses onward.", (232, 224, 244))

        class FakeRect:
            def __init__(self, x, y, width, height):
                self.x, self.y, self.width, self.height = x, y, width, height
                self.right, self.bottom = x + width, y + height
                self.centerx, self.centery = x + width // 2, y + height // 2
                self.center = (self.centerx, self.centery)

        class FakeFont:
            def size(self, text):
                return (len(str(text)) * 6, 12)

        class FakeSurface:
            pass

        painter = main.Painter.__new__(main.Painter)
        painter.f = {name: FakeFont() for name in ("huge", "big", "mid", "small", "tiny")}
        painter.renderer = SimpleNamespace(time=0.0)
        captured: list[str] = []

        def capture(_surf, _font, text, *_args, **_kwargs):
            captured.append(str(text))
            return None

        with mock.patch.object(main.pygame, "Rect", FakeRect), \
             mock.patch.object(main.pygame, "draw", SimpleNamespace(rect=lambda *_a, **_k: None), create=True), \
             mock.patch.object(main, "panel", lambda *_a, **_k: None), \
             mock.patch.object(main, "draw_text", capture):
            painter.run_sidebar(FakeSurface(), state)

        display = " ".join(captured)
        self.assertIn("PAST ACTIONS", display)
        self.assertIn("Past action 4", display)
        for restraint in Restraint:
            self.assertIn(restraint.label, display)
            self.assertIn(restraint.desc.split(" ")[0], display)

    def test_gameapp_shop_purchase_is_logged_and_proceed_autosaves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            saves = SaveManager(directory, slot_names=SLOT_NAMES)
            state = make_state(991, (PlayerClass.WARRIOR,), 3, 500, "Normal")
            shop = Shop(random.Random(789), state.players)
            app = make_app(saves)
            app.state, app.shop, app.screen = state, shop, main.Screen.SHOP
            pg = sys.modules["pygame"]
            item_key, _price = shop.stock[shop.cursor][0].key, shop.stock[shop.cursor][1]
            old_gold = state.gold
            app._key_shop(SimpleNamespace(key=pg.K_RETURN))
            self.assertLess(state.gold, old_gold)
            self.assertGreater(state.inventory.count(item_key), 0)
            self.assertIn("Bought", state.log[-1].text)

            shop.cursor = shop.rows - 1
            app._key_shop(SimpleNamespace(key=pg.K_RETURN))
            self.assertEqual(app.screen, main.Screen.HUB)
            self.assertTrue(saves.inspect(1).is_valid, "Proceed must invoke the real autosave method")
            restored = saves.load(1)
            self.assertTrue(any("leaves the merchant" in entry.text for entry in restored.log))

    def test_journal_navigation_does_not_dispatch_keys_to_gameplay(self) -> None:
        pg = sys.modules["pygame"]
        state = make_state(992, (PlayerClass.WARRIOR,), 1, 50, "Normal")
        for i in range(40):
            state.add_log(f"Past action {i}", (232, 224, 244))
        app = main.GameApp.__new__(main.GameApp)
        app.state = state
        app.screen = main.Screen.HUB
        app.combat = None
        app.show_journal = False
        app.journal_offset = 0
        app.journal_restraint_offset = 0
        app.journal_focus = "history"
        app.renderer = SimpleNamespace(handle_event=lambda _event: None)
        app.paused = False
        app.audio = main._SilentAudio()
        app.popups = []
        app.running = True

        app.handle_event(SimpleNamespace(type=pg.KEYDOWN, key=getattr(pg, "K_h", -9999), unicode="h"))
        self.assertTrue(app.show_journal)
        app.handle_event(SimpleNamespace(type=pg.KEYDOWN, key=getattr(pg, "K_PAGEUP", -9998), unicode=""))
        self.assertEqual(app.journal_offset, 16)
        app.handle_event(SimpleNamespace(type=pg.KEYDOWN, key=pg.K_TAB, unicode="\t"))
        self.assertEqual(app.journal_focus, "restraints")
        app.handle_event(SimpleNamespace(type=pg.KEYDOWN, key=getattr(pg, "K_PAGEUP", -9998), unicode=""))
        self.assertEqual(app.journal_restraint_offset, 0)  # empty restraint list cannot move out of bounds
        app.handle_event(SimpleNamespace(type=pg.KEYDOWN, key=pg.K_ESCAPE, unicode=""))
        self.assertFalse(app.show_journal)


class ClassIdentityRegressionTests(unittest.TestCase):
    EXPECTED_ABILITIES = {
        PlayerClass.WARRIOR: {"cleave", "rend", "execute", "sweep"},
        PlayerClass.TANK: {"bash", "guard", "provoke", "aegis"},
        PlayerClass.ROGUE: {"quick", "assassinate", "vanish", "twin_fang"},
        PlayerClass.WITCH: {"bolt", "barrier", "curse", "drain"},
        PlayerClass.ANGEL: {"slash", "dash", "halo", "writhe", "pierce", "break"},
        PlayerClass.KITSUNE: {"foxfire", "paper_moon", "ninefold", "masquerade", "ascend"},
        PlayerClass.VAMPIRE: {"crimson_mark", "sanguine_lunge", "veil_night", "blood_pact", "eclipse_feast"},
        PlayerClass.DRAGONKIN: {"scale_guard", "ember_breath", "dragon_challenge", "wingbeat", "ancient_aspect"},
    }

    def test_each_class_has_its_distinct_ability_kit(self) -> None:
        observed: dict[PlayerClass, set[str]] = {}
        for pclass, expected in self.EXPECTED_ABILITIES.items():
            state = GameState(seed=610 + len(observed))
            state.new_run([PlayerConfig("Solo", pclass)], "Normal", endless=True)
            player = state.players[0]
            abilities = player.abilities()
            keys = {ability.key for ability in abilities}
            self.assertEqual(keys, expected, pclass.value)
            self.assertTrue(all(ability.hint for ability in abilities), f"{pclass.value} has an unexplained action")
            observed[pclass] = keys
        self.assertEqual(len({frozenset(keys) for keys in observed.values()}), len(self.EXPECTED_ABILITIES))

    def test_core_class_mechanics_actually_change_in_combat(self) -> None:
        action_by_class = {
            PlayerClass.WARRIOR: "cleave",
            PlayerClass.TANK: "bash",
            PlayerClass.ROGUE: "quick",
            PlayerClass.WITCH: "bolt",
            PlayerClass.ANGEL: "slash",
            PlayerClass.KITSUNE: "foxfire",
            PlayerClass.VAMPIRE: "crimson_mark",
            PlayerClass.DRAGONKIN: "dragon_challenge",
        }
        for pclass, action in action_by_class.items():
            with self.subTest(player_class=pclass.value):
                state = GameState(seed=920 + len(action))
                state.new_run([PlayerConfig("Solo", pclass)], "Normal", endless=True)
                state.spawn_encounter()
                combat = CombatSystem(state)
                player = state.players[0]
                enemy = next(e for e in state.enemies if e.alive)
                hp_before = enemy.hp
                player.use(action, enemy, True, combat)
                self.assertLess(enemy.hp, hp_before, f"{pclass.value}'s core attack did not damage its target")


    def test_level_cap_records_mastery_overflow_without_infinite_stat_growth(self) -> None:
        from entities.player import create_player
        hero = create_player("Veteran", PlayerClass.WARRIOR)
        hero.level = hero.MAX_LEVEL - 1
        hero.xp = 0
        before = (hero.max_hp, hero.base_attack, hero.base_defense)
        leveled = hero.gain_xp(80 * hero.level + 500)
        self.assertTrue(leveled)
        self.assertEqual(hero.level, hero.MAX_LEVEL)
        self.assertEqual(hero.xp, 0)
        self.assertEqual(hero.mastery_xp, 500)
        capped_stats = (hero.max_hp, hero.base_attack, hero.base_defense)
        hero.gain_xp(1234)
        self.assertEqual(hero.level, hero.MAX_LEVEL)
        self.assertEqual((hero.max_hp, hero.base_attack, hero.base_defense), capped_stats)
        self.assertEqual(hero.mastery_xp, 1734)
        self.assertGreater(capped_stats[0], before[0])

    def test_expanded_class_actions_resolve_through_the_shared_combat_pipeline(self) -> None:
        # Warrior: an all-enemy sweep consumes Rage and does not rely on a UI draw path.
        warrior_state = GameState(seed=701)
        warrior_state.new_run([PlayerConfig("Mara", PlayerClass.WARRIOR)], "Normal")
        warrior_state.spawn_encounter()
        warrior_combat = CombatSystem(warrior_state)
        warrior = warrior_state.players[0]
        warrior.rage = 70
        foe = warrior_state.enemies[0]
        hp = foe.hp
        warrior.use("sweep", None, True, warrior_combat)
        self.assertLess(foe.hp, hp)
        self.assertEqual(warrior.rage, 0)

        # Tank: Aegis distributes its actual WARDED status to the living party and has a cooldown.
        tank_state = GameState(seed=702)
        tank_state.new_run([PlayerConfig("Bram", PlayerClass.TANK), PlayerConfig("Mara", PlayerClass.WARRIOR)], "Normal")
        tank_state.spawn_encounter()
        tank_combat = CombatSystem(tank_state)
        tank = tank_state.players[0]
        tank.use("aegis", None, True, tank_combat)
        self.assertTrue(all(hero.has(Status.WARDED) for hero in tank_state.players))
        self.assertEqual(tank.cooldowns.get("aegis"), 4)

        # Rogue: the two-hit QTE action damages a live target and increases combo.
        rogue_state = GameState(seed=703)
        rogue_state.new_run([PlayerConfig("Shade", PlayerClass.ROGUE)], "Normal")
        rogue_state.spawn_encounter()
        rogue_combat = CombatSystem(rogue_state)
        rogue = rogue_state.players[0]
        foe = rogue_state.enemies[0]
        hp = foe.hp
        rogue.use("twin_fang", foe, True, rogue_combat)
        self.assertLess(foe.hp, hp)
        self.assertGreaterEqual(rogue.combo, 2)

        # Witch: Soul Drain pays the mana cost, deals real damage, and heals the caster.
        witch_state = GameState(seed=704)
        witch_state.new_run([PlayerConfig("Morrigan", PlayerClass.WITCH)], "Normal")
        witch_state.spawn_encounter()
        witch_combat = CombatSystem(witch_state)
        witch = witch_state.players[0]
        foe = witch_state.enemies[0]
        witch.hp = max(1, witch.max_hp - 25)
        hp, mana, foe_hp = witch.hp, witch.mana, foe.hp
        witch.use("drain", foe, True, witch_combat)
        self.assertLess(foe.hp, foe_hp)
        self.assertLess(witch.mana, mana)
        self.assertGreater(witch.hp, hp)

    def test_manacled_angel_uses_the_fatal_rare_word_trial(self) -> None:
        from systems.combat_system import MenuEntry
        from systems.qte_system import TypingQTE
        state = GameState(seed=779)
        state.new_run([PlayerConfig("Seraphine", PlayerClass.ANGEL)], "Normal", endless=True)
        state.spawn_encounter()
        combat = CombatSystem(state)
        angel = state.players[0]
        enemy = next(e for e in state.enemies if e.alive)
        angel.restraints = {Restraint.MANACLES}
        slash = next(a for a in angel.abilities() if a.key == "slash")
        combat.active = angel
        combat._entry = MenuEntry("Dark Blade Slash", ability=slash)
        combat._begin_execute(enemy)
        self.assertIsInstance(combat.qte, TypingQTE)
        self.assertTrue(combat.qte.fatal_mistake)
        self.assertGreaterEqual(len(combat.qte.word), 12)

    def test_bound_angel_damage_is_suppressed_by_restraints_and_tightness(self) -> None:
        state = GameState(seed=778)
        state.new_run([PlayerConfig("Seraphine", PlayerClass.ANGEL)], "Normal", endless=True)
        state.spawn_encounter()
        combat = CombatSystem(state)
        angel = state.players[0]
        enemy = next(e for e in state.enemies if e.alive)
        angel.restraints.clear()
        angel.tightness = 0
        damage_free = combat.strike(angel, enemy, 1.0, true_damage=True)
        enemy.hp = enemy.max_hp
        angel.restraints = {Restraint.MANACLES, Restraint.ANCHOR, Restraint.BARBED_WINGS}
        angel.tightness = 2
        damage_bound = combat.strike(angel, enemy, 1.0, true_damage=True)
        self.assertLess(damage_bound, damage_free)

    def test_fallen_angel_restraint_cascade_and_failed_escape_are_costly(self) -> None:
        state = GameState(seed=777)
        state.new_run([PlayerConfig("Seraphine", PlayerClass.ANGEL)], "Normal", endless=True)
        state.spawn_encounter()
        combat = CombatSystem(state)
        angel = state.players[0]
        self.assertIsInstance(angel, FallenAngel)
        angel.restraints.clear()
        angel.tightness = 0
        angel.lucidity = 100.0
        angel.stamina = angel.max_stamina
        for _ in range(5):
            angel.on_turn_start(combat)
        self.assertGreaterEqual(len(angel.restraints), 5, "the Angel must face escalating restraint pressure")
        self.assertLess(angel.lucidity, 100.0, "multiple restraints must become dangerous to lucidity")

        angel.restraints = {Restraint.ANCHOR}
        angel.tightness = 0
        angel.stamina = angel.max_stamina
        angel.hp = angel.max_hp
        angel.lucidity = 80.0
        hp_before, lucidity_before = angel.hp, angel.lucidity
        angel.use("break", None, False, combat)
        self.assertIn(Restraint.ANCHOR, angel.restraints, "failed escape must not remove the chain")
        self.assertLess(angel.hp, hp_before, "failed escape must cost HP")
        self.assertLess(angel.lucidity, lucidity_before, "failed escape must cost lucidity")
        self.assertGreater(angel.tightness, 0, "failed escape must tighten restraints")

if __name__ == "__main__":
    unittest.main()

class ReleaseCandidatePolishTests(unittest.TestCase):
    def test_all_eight_classes_map_to_unique_runtime_sprite_kinds(self) -> None:
        kinds = [main._kind_for(SimpleNamespace(pclass=cls), i) for i, cls in enumerate(PlayerClass)]
        self.assertEqual(len(kinds), 8)
        self.assertEqual(len(set(kinds)), 8)
        self.assertEqual(main.CharacterKind.WARRIOR, kinds[0])
        self.assertEqual(main.CharacterKind.TANK, kinds[1])
        self.assertEqual(main.CharacterKind.ROGUE, kinds[2])
        self.assertEqual([kind for kind, _ in main.TITLE_PREVIEW_SPECS], kinds,
                         "the title screen preview registry must include every playable class exactly once")

    def test_title_preview_slots_are_evenly_spaced_on_screen_with_unique_labels(self) -> None:
        count = len(main.TITLE_PREVIEW_SPECS)
        xs = [main.TITLE_PREVIEW_X0 + main.TITLE_PREVIEW_DX * i for i in range(count)]
        self.assertEqual(count, 8)
        self.assertGreater(xs[0], 40)
        self.assertLess(xs[-1], main.W - 40)
        self.assertGreaterEqual(main.TITLE_PREVIEW_DX, 140, "labels need room beside their neighbours")
        labels = [kind.name.replace("_", " ") for kind, _ in main.TITLE_PREVIEW_SPECS]
        self.assertEqual(len(set(labels)), count)
        self.assertIn("FALLEN ANGEL", labels)

    def test_party_cards_show_vampire_blood_and_dragonkin_heat_gauges(self) -> None:
        from entities.player import create_player
        captured: list[str] = []
        fonts = {"small": object(), "tiny": object(), "mid": object()}
        painter = main.Painter.__new__(main.Painter)
        painter.f = fonts
        class RectStub:
            def __init__(self, x, y, w, h):
                self.x, self.y, self.width, self.height = x, y, w, h
                self.right, self.bottom = x + w, y + h
                self.size, self.center = (w, h), (x + w // 2, y + h // 2)
                self.centerx, self.centery = x + w // 2, y + h // 2
        for pclass, expected in ((PlayerClass.VAMPIRE, "BLOOD"), (PlayerClass.DRAGONKIN, "HEAT"),
                                 (PlayerClass.WARRIOR, "RAGE"), (PlayerClass.TANK, "BASTION"),
                                 (PlayerClass.ROGUE, "COMBO"), (PlayerClass.KITSUNE, "SPIRIT"),
                                 (PlayerClass.ANGEL, "LUC")):
            captured.clear()
            hero = create_player("HUD Hero", pclass)
            with self.subTest(resource=expected), patch.object(main, "panel", lambda *a, **k: None), \
                 patch.object(main, "draw_bar", lambda *a, **k: None), \
                 patch.object(main, "draw_text", lambda *a, **k: captured.append(str(a[2]))), \
                 patch.object(main, "fit_text", lambda font, text, width: str(text)), \
                 patch.object(main.pygame, "Rect", RectStub):
                painter.party_cards(object(), [hero], None)
            self.assertTrue(any(expected in item for item in captured), f"{expected} hidden on party HUD")

    def test_all_character_painters_execute_without_display_services(self) -> None:
        from entities.player import _PAINTERS as ENTITY_PAINTERS, _paint_generic, create_player

        class BrushRecorder:
            def __init__(self):
                self.calls = []
            def __getattr__(self, name):
                def record(*args, **kwargs):
                    self.calls.append(name)
                return record

        self.assertEqual(set(ENTITY_PAINTERS), set(PlayerClass))
        self.assertTrue(all(fn is not _paint_generic for fn in ENTITY_PAINTERS.values()),
                        "every class should have its own entity portrait painter")
        # Exercise both render paths. This catches method-name/signature mistakes in art code
        # while deliberately avoiding a false claim that a real pygame window was drawn.
        for kind in CharacterKind:
            with self.subTest(scene_kind=kind.value):
                ch = Character(kind, kind.value.title(), 400, 600, 0.4)
                brush = BrushRecorder()
                painter = SpritePainter(brush, 1.25, ch)
                painter.paint()
                self.assertGreaterEqual(len(brush.calls), 12)
        for pclass in (PlayerClass.WARRIOR, PlayerClass.TANK, PlayerClass.ROGUE,
                       PlayerClass.VAMPIRE, PlayerClass.DRAGONKIN):
            with self.subTest(entity_class=pclass.value):
                hero = create_player("Art Check", pclass)
                canvas = BrushRecorder()
                ENTITY_PAINTERS[pclass](canvas, hero, 1.25, "slash", 0.35)
                self.assertGreaterEqual(len(canvas.calls), 10)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.saves = SaveManager(self.temp.name, slot_names=SLOT_NAMES)

    def test_party_sprites_are_clear_of_left_chronicle_sidebar(self) -> None:
        app = make_app(self.saves)
        app.state = make_state(707, (PlayerClass.WARRIOR, PlayerClass.ANGEL, PlayerClass.WITCH), 2, 50)
        app._bind_state()
        self.assertEqual(len(app.chars), 3)
        # Conservatively reserve 235 local units for the Angel's largest wing span.
        # The whole party must fit between the chronicle (right edge 236) and enemy lane (x=690).
        self.assertTrue(all(ch.x - 235 * ch.scale > 236 for ch in app.chars),
                        [(ch.x, ch.scale) for ch in app.chars])
        self.assertTrue(all(ch.x + 235 * ch.scale < 690 for ch in app.chars),
                        [(ch.x, ch.scale) for ch in app.chars])

    def test_f11_toggles_fullscreen_and_back_to_resizable_window(self) -> None:
        app = make_app(self.saves)
        app.fullscreen = False
        fake_display = SimpleNamespace(set_mode=mock.Mock(side_effect=lambda size, flags: (size, flags)))
        with mock.patch.object(main.pygame, "display", fake_display, create=True), \
             mock.patch.object(main.pygame, "K_F11", 1100, create=True), \
             mock.patch.object(main.pygame, "FULLSCREEN", 2, create=True), \
             mock.patch.object(main.pygame, "RESIZABLE", 1, create=True):
            app.handle_event(SimpleNamespace(type=main.pygame.KEYDOWN, key=1100, unicode=""))
            self.assertTrue(app.fullscreen)
            self.assertEqual(fake_display.set_mode.call_args.args, ((0, 0), 2))
            app.handle_event(SimpleNamespace(type=main.pygame.KEYDOWN, key=1100, unicode=""))
            self.assertFalse(app.fullscreen)
            self.assertEqual(fake_display.set_mode.call_args.args, ((main.W, main.H), 1))

    def test_solo_angel_is_centered_and_wing_clear_of_both_lanes(self) -> None:
        app = make_app(self.saves)
        app.state = make_state(706, (PlayerClass.ANGEL,), 2, 50)
        app._bind_state()
        angel = app.chars[0]
        self.assertEqual(angel.x, 463.0)
        self.assertGreater(angel.x - 235 * angel.scale, 236)
        self.assertLess(angel.x + 235 * angel.scale, 690)

    def test_hub_menu_has_only_shop_and_next_stage(self) -> None:
        app = make_app(self.saves)
        app.state = make_state(808, (PlayerClass.WARRIOR,), 2, 50)
        app._to_hub()
        self.assertEqual([item.tag for item in app.hub_menu.items], ["shop", "next"])
        self.assertFalse(any(item.tag in {"rest", "save", "load", "menu"} for item in app.hub_menu.items))

    def test_hub_escape_opens_pause_menu_for_save_load_and_title(self) -> None:
        app = make_app(self.saves)
        app.state = make_state(909, (PlayerClass.WARRIOR,), 2, 50)
        app._to_hub()
        ev = types.SimpleNamespace(key=main.pygame.K_ESCAPE)
        app._key_hub(ev)
        self.assertTrue(app.paused)
        self.assertEqual([item.tag for item in app.pause_menu.items], ["resume", "save", "load", "title", "quit"])


class V2IntegratedSystemsTests(unittest.TestCase):
    def test_kitsune_spirit_illusion_evasion_and_awakening_are_bounded(self) -> None:
        state = GameState(seed=0xC0FFEE)
        state.new_run([PlayerConfig("Kiri", PlayerClass.KITSUNE), PlayerConfig("Bram", PlayerClass.TANK)], "Normal")
        state.spawn_encounter()
        combat = CombatSystem(state)
        kiri = state.players[0]
        self.assertIsInstance(kiri, Kitsune)
        enemy = state.enemies[0]
        enemy_hp = enemy.hp
        kiri.use("foxfire", enemy, True, combat)
        self.assertLess(enemy.hp, enemy_hp, "Foxfire must resolve real combat damage")
        self.assertGreater(kiri.spirit, 0, "successful attacks must build Spirit")
        kiri.spirit = 1000
        self.assertEqual(kiri.gain_spirit(10), 0)
        self.assertEqual(kiri.spirit, Kitsune.SPIRIT_MAX)
        kiri.use("paper_moon", None, None, combat)
        self.assertEqual(kiri.spirit, 75)
        self.assertEqual(kiri.decoy_turns, 1)
        self.assertGreaterEqual(kiri.evasion_charges, 1)
        hp = kiri.hp
        combat._enemy_hit(enemy, kiri, 1.0, heavy=False)
        self.assertEqual(kiri.hp, hp, "a prepared single-target evade must prevent the hit")
        self.assertEqual(kiri.evasion_charges, 0)
        self.assertTrue(any(event.kind is EventKind.DODGE for event in combat.drain()))
        kiri.spirit = 100
        kiri.use("ascend", None, None, combat)
        self.assertEqual(kiri.spirit, 35)
        self.assertEqual(kiri.awakened_turns, 3)
        kiri.after_battle()
        self.assertEqual(kiri.awakened_turns, 0)
        self.assertEqual(kiri.evasion_charges, 0)
        self.assertLessEqual(kiri.spirit, 25)

    def test_kitsune_dynamic_fields_round_trip_and_legacy_saves_still_load(self) -> None:
        state = make_state(616, (PlayerClass.KITSUNE, PlayerClass.WARRIOR), 4, 100)
        hero = state.players[0]
        self.assertIsInstance(hero, Kitsune)
        hero.spirit = 61
        hero.evasion_charges = 2
        hero.decoy_turns = 1
        hero.awakened_turns = 2
        raw = state.to_dict()
        loaded = GameState.from_dict(raw)
        actual = loaded.players[0]
        self.assertIsInstance(actual, Kitsune)
        self.assertEqual((actual.spirit, actual.evasion_charges, actual.decoy_turns, actual.awakened_turns),
                         (61, 2, 1, 2))
        old = dict(raw)
        old.pop("run_id", None)
        restored = GameState.from_dict(old)
        self.assertTrue(restored.run_id)

    def test_vampire_blood_loop_and_healing_are_bounded(self) -> None:
        state = GameState(seed=1730)
        state.new_run([PlayerConfig("Noct", PlayerClass.VAMPIRE)], "Normal", endless=True)
        state.spawn_encounter()
        combat = CombatSystem(state)
        vampire = state.players[0]
        self.assertIsInstance(vampire, Vampire)
        enemy = next(e for e in state.enemies if e.alive)
        vampire.blood = 70
        vampire.hp = vampire.max_hp - 20
        hp_before = vampire.hp
        enemy_hp = enemy.hp
        vampire.use("eclipse_feast", enemy, None, combat)
        self.assertLess(enemy.hp, enemy_hp)
        self.assertLessEqual(vampire.hp - hp_before, 24)
        self.assertGreaterEqual(vampire.blood, 0)
        self.assertLessEqual(vampire.blood, Vampire.BLOOD_MAX)
        vampire.blood = 99
        vampire.on_deal_damage(1)
        self.assertEqual(vampire.blood, Vampire.BLOOD_MAX)

    def test_dragonkin_overheat_vents_and_applies_a_real_vulnerability(self) -> None:
        state = GameState(seed=1731)
        state.new_run([PlayerConfig("Vaelor", PlayerClass.DRAGONKIN)], "Normal", endless=True)
        state.spawn_encounter()
        combat = CombatSystem(state)
        dragon = state.players[0]
        self.assertIsInstance(dragon, Dragonkin)
        dragon.heat = 96
        enemy = next(e for e in state.enemies if e.alive)
        combat.strike(dragon, enemy, 0.1)
        self.assertEqual(dragon.heat, 55, "crossing 100 Heat must vent to the post-overheat level")
        self.assertEqual(dragon.overheated_turns, 1)
        self.assertTrue(dragon.has(Status.EXPOSED), "overheat should create a tactical vulnerability")
        dragon.on_turn_start(combat)
        self.assertTrue(any("vent furnace heat" in entry.text for entry in state.log))

    def test_leaderboard_is_atomic_mode_aware_sorted_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            board = LocalLeaderboard(Path(directory) / "records.json")
            high = make_state(1, (PlayerClass.KITSUNE, PlayerClass.WITCH), 9, 900)
            high.run_id = "run-high"
            low = make_state(2, (PlayerClass.WARRIOR,), 3, 50)
            low.run_id = "run-low"
            story = make_state(3, (PlayerClass.TANK,), 5, 200)
            story.endless = False
            story.run_id = "run-story"
            record, inserted = board.add_result(high, True, high.run_id)
            self.assertTrue(inserted)
            duplicate, inserted_again = board.add_result(high, False, high.run_id)
            self.assertFalse(inserted_again)
            self.assertEqual(duplicate, record, "revisiting results must not mutate a saved run record")
            board.add_result(low, False, low.run_id)
            board.add_result(story, True, story.run_id)
            records = board.records("endless", 10)
            self.assertEqual([r["record_id"] for r in records], ["run-high", "run-low"])
            self.assertEqual([r["record_id"] for r in board.records("story")], ["run-story"])
            self.assertEqual(len(board.records("all")), 3)
            self.assertEqual(json.loads((Path(directory) / "records.json").read_text())["schema"], 1)

    def test_leaderboard_preserves_malformed_file_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            path.write_text("{definitely not json", encoding="utf-8")
            board = LocalLeaderboard(path)
            with self.assertRaises(LeaderboardError):
                board.add_result(make_state(4, (PlayerClass.WARRIOR,), 1, 0), False, "run")
            self.assertEqual(path.read_text(encoding="utf-8"), "{definitely not json")

    def test_title_mode_selection_starts_the_chosen_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = SaveManager(directory, slot_names=SLOT_NAMES)
            app = make_app(manager)
            app.seed = 123
            app.setup = main.PartySetup(3)
            app.classes = list(PlayerClass)
            app.mode_menu = main.MenuList([main.MenuItem("story", "Story"), main.MenuItem("endless", "Endless")])
            app.mode_menu.idx = 0
            app._key_mode_select(SimpleNamespace(key=sys.modules["pygame"].K_RETURN, unicode=""))
            self.assertEqual(app.run_mode, "story")
            self.assertEqual(app.screen, main.Screen.SETUP)
            app._start_run("Normal")
            self.assertIsNotNone(app.state)
            self.assertFalse(app.state.endless)
            self.assertEqual(app.screen, main.Screen.COMBAT)



class SettingsAndReleaseHardeningTests(unittest.TestCase):
    def test_settings_round_trip_defaults_clamp_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            self.assertEqual(store.load()["music_volume"], 0.55)
            settings = store.defaults()
            settings["music_volume"] = 1.4
            settings["sfx_volume"] = -0.2
            settings["reduced_motion"] = True
            store.save(settings)
            loaded = store.load()
            self.assertEqual(loaded["music_volume"], 1.0)
            self.assertEqual(loaded["sfx_volume"], 0.0)
            self.assertTrue(loaded["reduced_motion"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], 1)
            self.assertFalse(any(path.parent.glob("settings.json.*.tmp")))

    def test_settings_reject_non_finite_and_preserve_corrupted_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"schema": 1, "music_volume": NaN}', encoding="utf-8")
            store = SettingsStore(path)
            with self.assertRaises(SettingsError):
                store.load()
            self.assertEqual(path.read_text(encoding="utf-8"), '{"schema": 1, "music_volume": NaN}')
            with self.assertRaises(SettingsError):
                store.save({**store.defaults(), "music_volume": float("inf")})

    def test_settings_menu_changes_values_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            saves = SaveManager(directory, slot_names=SLOT_NAMES)
            app = make_app(saves)
            app.settings_store = SettingsStore(Path(directory) / "settings.json")
            app.settings = app.settings_store.defaults()
            app.vfx = VFX({"big": object(), "mid": object()})
            app.renderer = SimpleNamespace(motion_scale=1.0)
            app._refresh_settings_menu()
            app.screen = main.Screen.SETTINGS
            # First row is music volume: right increases exactly five percentage points.
            app._key_settings(SimpleNamespace(key=sys.modules["pygame"].K_RIGHT))
            self.assertEqual(app.settings["music_volume"], 0.60)
            persisted = app.settings_store.load()
            self.assertEqual(persisted["music_volume"], 0.60)
            # Walk to reduced motion and turn it on; this also updates VFX and renderer.
            for _ in range(5):
                app._key_settings(SimpleNamespace(key=sys.modules["pygame"].K_DOWN))
            self.assertEqual(app.settings_menu.selected.tag, "reduced_motion")
            app._key_settings(SimpleNamespace(key=sys.modules["pygame"].K_RETURN))
            self.assertTrue(app.settings["reduced_motion"])
            self.assertTrue(app.vfx.reduced_motion)
            self.assertEqual(app.renderer.motion_scale, 0.25)
            self.assertTrue(app.settings_store.load()["reduced_motion"])

    def test_death_vfx_respects_reduced_motion_and_shake_settings(self) -> None:
        vfx = VFX({"big": object(), "mid": object()})
        vfx.anchors[7] = (100.0, 200.0)
        vfx.screen_shake_enabled = False
        vfx.particles_enabled = False
        vfx.consume([CombatEvent(EventKind.DEATH, uid=7)])
        self.assertEqual(vfx.trauma, 0.0, "death impact must respect the screen-shake preference")
        self.assertEqual(vfx.particles, [], "death effects must respect the particle preference")
        vfx.screen_shake_enabled = True
        vfx.reduced_motion = True
        vfx.consume([CombatEvent(EventKind.DEATH, uid=7)])
        self.assertEqual(vfx.trauma, 0.0, "reduced motion must suppress death camera impulses")


class FinalPassRegressionTests(unittest.TestCase):
    def test_formation_sizes_are_explicit_and_reject_invalid_parties(self) -> None:
        expected = {
            1: ((463.0,), 0.90),
            2: ((402.0, 524.0), 0.70),
            3: ((360.0, 463.0, 566.0), 0.52),
        }
        for size, formation in expected.items():
            self.assertEqual(main.party_formation(size), formation)
            xs, scale = formation
            self.assertTrue(all(a < b for a, b in zip(xs, xs[1:])))
            self.assertGreater(scale, 0.0)
        for invalid in (0, 4, True, 1.0, "2"):
            with self.subTest(size=invalid), self.assertRaises(ValueError):
                main.party_formation(invalid)

    def test_notify_uses_one_vfx_stack_and_honors_lifetime(self) -> None:
        app = main.GameApp.__new__(main.GameApp)
        app.vfx = VFX({"big": object(), "mid": object()})
        app.popups = []
        app.notify("A longer combat notification", (255, 255, 255), 4.5)
        app.notify("A longer combat notification", (255, 255, 255), 5.0)
        self.assertEqual(app.popups, [])
        self.assertEqual(len(app.vfx.toasts), 1)
        self.assertEqual(app.vfx.toasts[0].life, 5.0)
        self.assertEqual(app.vfx.toasts[0].max_life, 5.0)
        self.assertEqual(app.vfx.toasts[0].count, 2)

    def test_long_toasts_wrap_within_the_bounded_panel_when_pygame_is_installed(self) -> None:
        pg = sys.modules["pygame"]
        if not hasattr(getattr(pg, "font", None), "SysFont"):
            self.skipTest("pygame-ce font rendering is unavailable")
        pg.font.init()
        font = main.load_font(13)
        vfx = VFX({"big": font, "mid": font})
        vfx.push_toast("The displayed combat notification is long enough to wrap cleanly across two readable lines",
                       category="status")
        surface = vfx._render_toast(vfx.toasts[0])
        self.assertIsNotNone(surface)
        self.assertLessEqual(surface.get_width(), TOAST_MAX_W)
        self.assertGreater(surface.get_height(), font.get_height() + 12)

    def test_maximum_wrapped_toast_stack_stays_above_enemy_cards_when_pygame_is_installed(self) -> None:
        pg = sys.modules["pygame"]
        if not hasattr(getattr(pg, "font", None), "SysFont"):
            self.skipTest("pygame-ce font rendering is unavailable")
        pg.font.init()
        font = main.load_font(13)
        vfx = VFX({"big": font, "mid": font})
        for i in range(TOAST_MAX + 1):
            vfx.push_toast(f"Long combat notice {i} wraps across two lines without hiding the enemy intent card",
                           category="status", priority=i)
        vfx._update_toasts(0.05)
        bottom = max(float(t.y or 0) + float(t.surface.get_height()) for t in vfx.toasts)
        self.assertLessEqual(bottom, 303, "the complete toast stack must not cover the solo-enemy card")

    def test_action_guard_and_dodge_events_create_bounded_actor_cues(self) -> None:
        vfx = VFX({"big": object(), "mid": object()})
        vfx.consume([
            CombatEvent(EventKind.ACTION, uid=12, data={"action_key": "guard", "action_type": "ability"}),
            CombatEvent(EventKind.INTERCEPT, uid=13),
            CombatEvent(EventKind.DODGE, uid=14),
        ])
        self.assertEqual(vfx.actor_effects[12][0], "guard")
        self.assertEqual(vfx.actor_effects[13][0], "guard")
        self.assertEqual(vfx.actor_effects[14][0], "dodge")
        vfx.update(0.73)
        self.assertEqual(vfx.actor_effects, {}, "actor cues must expire and release entity state")

    def test_credits_screen_returns_to_title(self) -> None:
        app = main.GameApp.__new__(main.GameApp)
        app.title_menu = main.MenuList([main.MenuItem("credits", "Credits / About")])
        app.screen = main.Screen.TITLE
        app._key_title(SimpleNamespace(key=sys.modules["pygame"].K_RETURN))
        self.assertIs(app.screen, main.Screen.CREDITS)
        app.screen = main.Screen.CREDITS
        app._key_credits(SimpleNamespace(key=sys.modules["pygame"].K_ESCAPE))
        self.assertIs(app.screen, main.Screen.TITLE)
        self.assertEqual(main.CREDIT_URL, "https://github.com/riberii/TBS-Combat-Simulator")
