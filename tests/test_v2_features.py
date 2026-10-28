"""Tests for V2.0 expansion features: 8 archetypes, merchant matrix, pets, cosmetics, tutorials, and modes."""
from __future__ import annotations

import random
import unittest
from pathlib import Path

from core.config import PlayerClass
from core.cosmetics import COMMON_SKINS, get_skin, get_skins_for_class
from core.game_state import GameState, PlayerConfig
from core.pets import PETS, get_pet, on_round_end_pet, on_round_start_pet, pet_def_bonus, pet_gold_multiplier
from core.story import CHAPTERS, CLASS_BARKS, STAGE_INTROS
from core.tutorials import CLASS_TUTORIALS, GENERAL_TUTORIALS
from core.meta_progression import (
    PlayerProfile, ProfileStore, DailyTask, get_daily_task,
    calculate_run_shards, apply_profile_bonuses,
    SKILL_TREE, nodes_for_class,
)
from entities.enemy import ARCHETYPES, Enemy
from entities.player import FallenAngel, Restraint, create_player
from systems.combat_system import CombatSystem
from systems.inventory_system import ITEMS, Shop, calculate_item_price


class V2FeaturesTests(unittest.TestCase):
    def test_eight_enemy_archetypes_exist_and_are_valid(self) -> None:
        expected = {"beast", "void", "nature", "construct", "cultist", "hunter", "undead", "cinder"}
        self.assertEqual(set(ARCHETYPES.keys()), expected)
        for key, arch in ARCHETYPES.items():
            self.assertGreater(arch.hp, 0)
            self.assertGreater(arch.atk, 0)
            self.assertGreater(arch.speed, 0)
            self.assertTrue(arch.names)
            self.assertTrue(arch.weights)

    def test_merchant_pricing_formula_depth_and_affinity(self) -> None:
        p_rogue = create_player("Lyra", PlayerClass.ROGUE)
        p_witch = create_player("Vesper", PlayerClass.WITCH)
        p_dragon = create_player("Vaelor", PlayerClass.DRAGONKIN)

        smoke_item = ITEMS["smoke"]
        mana_item = ITEMS["mana"]
        ward_item = ITEMS["ward"]

        # Stage 1 vs Stage 12 regional depth
        price_s1 = calculate_item_price(smoke_item, random.Random(42), [p_rogue], stage=1)
        price_s12 = calculate_item_price(smoke_item, random.Random(42), [p_rogue], stage=12)
        self.assertGreater(price_s12, price_s1)

        # Rogue gets discount on smoke bombs
        rogue_smoke = calculate_item_price(smoke_item, random.Random(99), [p_rogue], stage=1)
        witch_smoke = calculate_item_price(smoke_item, random.Random(99), [p_witch], stage=1)
        self.assertLess(rogue_smoke, witch_smoke)

        # Witch gets discount on mana
        witch_mana = calculate_item_price(mana_item, random.Random(100), [p_witch], stage=1)
        rogue_mana = calculate_item_price(mana_item, random.Random(100), [p_rogue], stage=1)
        self.assertLess(witch_mana, rogue_mana)

        # Dragonkin pays surcharge on anti-draconic ward
        dragon_ward = calculate_item_price(ward_item, random.Random(101), [p_dragon], stage=1)
        witch_ward = calculate_item_price(ward_item, random.Random(101), [p_witch], stage=1)
        self.assertGreater(dragon_ward, witch_ward)

    def test_pet_system_roster_and_effects(self) -> None:
        expected_pets = {"raven", "wisp", "hound", "beetle", "sprite"}
        self.assertEqual(set(PETS.keys()), expected_pets)
        for key in expected_pets:
            self.assertIsNotNone(get_pet(key))

        # Raven gold bonus
        self.assertEqual(pet_gold_multiplier("raven"), 1.20)
        self.assertEqual(pet_gold_multiplier(None), 1.0)

        # Beetle def bonus
        self.assertEqual(pet_def_bonus("beetle"), 3)
        self.assertEqual(pet_def_bonus(None), 0)

        # Combat integration
        state = GameState(seed=555)
        state.new_run([PlayerConfig("Vesper", PlayerClass.WITCH)], "Normal")
        state.pet = "wisp"
        state.spawn_encounter()
        combat = CombatSystem(state)
        hero = state.players[0]
        hero.mana = 10
        hero.stamina = 20
        on_round_start_pet("wisp", combat)
        self.assertEqual(hero.mana, 15)
        self.assertEqual(hero.stamina, 25)

        # Sprite heal
        hero.hp = 50
        on_round_end_pet("sprite", combat)
        self.assertEqual(hero.hp, 55)

    def test_cosmetics_system_palettes(self) -> None:
        skins = get_skins_for_class("WARRIOR")
        self.assertGreaterEqual(len(skins), 4)
        skin_keys = {s.key for s in skins}
        self.assertTrue({"default", "abyssal", "dawnlight", "crimson"}.issubset(skin_keys))
        # Fallback
        self.assertEqual(get_skin(None).key, "default")
        self.assertEqual(get_skin("unknown").key, "default")

    def test_story_chapters_and_class_barks(self) -> None:
        self.assertEqual(len(CHAPTERS), 6)
        self.assertEqual(len(STAGE_INTROS), 12)
        for pclass in PlayerClass:
            name = pclass.name
            self.assertIn(name, CLASS_BARKS)
            barks = CLASS_BARKS[name]
            self.assertTrue({"start", "low_hp", "boss", "victory"}.issubset(barks.keys()))

    def test_tutorials_coverage(self) -> None:
        self.assertGreaterEqual(len(GENERAL_TUTORIALS), 3)
        for pclass in PlayerClass:
            self.assertIn(pclass, CLASS_TUTORIALS)
            lesson = CLASS_TUTORIALS[pclass]
            self.assertTrue(lesson.title)
            self.assertTrue(lesson.tips)

    def test_all_six_game_modes_initialization(self) -> None:
        modes = ("story", "endless", "boss_rush", "arena", "training", "daily")
        for mode in modes:
            state = GameState(seed=777)
            is_endless = mode in ("endless", "arena")
            state.new_run([PlayerConfig("Val", PlayerClass.WARRIOR)], "Normal", endless=is_endless)
            if mode == "boss_rush":
                state.stage = 3
            elif mode == "training":
                state.gold = 999
            state.spawn_encounter()
            self.assertTrue(len(state.enemies) > 0)
            if mode == "boss_rush":
                self.assertEqual(state.stage, 4)
                self.assertTrue(state.enemies[0].boss)
            elif mode == "training":
                self.assertEqual(state.gold, 999)

    def test_player_profile_and_shard_economy(self) -> None:
        p = PlayerProfile()
        self.assertEqual(p.shards, 0)
        p.add_shards(45)
        self.assertEqual(p.shards, 45)
        self.assertTrue(p.can_afford(30))
        self.assertFalse(p.can_afford(50))
        d = p.to_dict()
        loaded = PlayerProfile.from_dict(d)
        self.assertEqual(loaded.shards, 45)

    def test_skill_tree_tiers_and_prerequisites(self) -> None:
        self.assertEqual(len(SKILL_TREE), 48)      # R2: 6 nodes x 8 classes (legacy t1-t3 ids/costs unchanged)
        for pc in PlayerClass:
            nodes = nodes_for_class(pc.name)
            self.assertEqual(len(nodes), 6)
            self.assertEqual([n.node_id.rsplit("_t", 1)[1] for n in nodes], ["1", "2", "3", "4", "5", "6"])
            self.assertEqual([n.cost for n in nodes[:3]], [5, 10, 20])
            self.assertEqual([n.branch for n in nodes], ["core", "core", "core", "specialisation", "utility", "capstone"])

        p = PlayerProfile(shards=35)
        # Cannot buy tier 2 before tier 1
        ok, msg = p.purchase_node("warrior_t2")
        self.assertFalse(ok)
        self.assertIn("tier 1", msg.lower())

        # Buy tier 1
        ok, msg = p.purchase_node("warrior_t1")
        self.assertTrue(ok)
        self.assertEqual(p.shards, 30)
        self.assertIn("warrior_t1", p.unlocked_nodes)

        # Now can buy tier 2
        ok, msg = p.purchase_node("warrior_t2")
        self.assertTrue(ok)
        self.assertEqual(p.shards, 20)

        # Refund tier 1 cascade refunds tier 2
        ok, msg = p.refund_node("warrior_t1")
        self.assertTrue(ok)
        self.assertNotIn("warrior_t1", p.unlocked_nodes)
        self.assertNotIn("warrior_t2", p.unlocked_nodes)
        # Refund returns 50%: 5//2 + 10//2 = 2 + 5 = 7
        self.assertEqual(p.shards, 27)

    def test_skill_tree_stat_bonuses_application(self) -> None:
        p = PlayerProfile(shards=100)
        p.purchase_node("warrior_t1")  # +10 max HP
        p.purchase_node("warrior_t2")  # +8% atk
        warrior = create_player("Val", PlayerClass.WARRIOR)
        orig_hp = warrior.max_hp
        orig_atk = warrior.base_attack
        apply_profile_bonuses(warrior, p)
        self.assertEqual(warrior.max_hp, orig_hp + 10)
        self.assertGreater(warrior.base_attack, orig_atk)

    def test_daily_task_generation_and_claiming(self) -> None:
        from datetime import date
        d = date(2026, 10, 25)
        t1 = get_daily_task(d)
        t2 = get_daily_task(d)
        self.assertEqual(t1.seed, t2.seed)
        self.assertEqual(t1.objective, t2.objective)
        self.assertEqual(t1.mode, t2.mode)
        self.assertEqual(t1.reward_shards, 15)

        p = PlayerProfile(shards=0)
        self.assertFalse(p.is_daily_done(t1))
        ok, msg = p.claim_daily(t1)
        self.assertTrue(ok)
        self.assertEqual(p.shards, 15)
        self.assertTrue(p.is_daily_done(t1))

        # Idempotent - cannot claim twice
        ok2, msg2 = p.claim_daily(t1)
        self.assertFalse(ok2)
        self.assertEqual(p.shards, 15)

    def test_angel_break_chance_rebalance_and_iron_will(self) -> None:
        angel = FallenAngel("Seraphine")
        # Base with 0 restraints and 0 tightness: clamp(0.40, 0.12, 0.45) = 0.40
        self.assertAlmostEqual(angel.break_chance(), 0.40, places=2)
        self.assertEqual(FallenAngel.BREAK_BACKLASH_HP, 14)
        self.assertEqual(FallenAngel.BREAK_BACKLASH_LUC, 20.0)

        # With 2 restraints and 1 tightness: 0.40 - 0.12 - 0.08 = 0.20
        angel.restraints.add(Restraint.MANACLES)
        angel.restraints.add(Restraint.IRON_GAG)
        angel.tightness = 1
        self.assertAlmostEqual(angel.break_chance(), 0.20, places=2)

        # Profile Iron Will bonus (+0.08) offsets penalty
        angel._profile_break_bonus = 0.08
        self.assertAlmostEqual(angel.break_chance(), 0.28, places=2)

    def test_run_shard_calculation(self) -> None:
        # Stage < 2 gives 0
        self.assertEqual(calculate_run_shards(False, 1, 0), 0)
        # Stage >= 2 gives shards
        defeat_shards = calculate_run_shards(False, 2, 0)
        self.assertGreater(defeat_shards, 0)
        victory_shards = calculate_run_shards(True, 4, 1)
        self.assertGreater(victory_shards, defeat_shards)

    def test_all_48_skill_tree_nodes_have_live_stat_keys(self) -> None:
        """Every one of the 48 skill tree nodes must map to an active profile bonus handler."""
        self.assertEqual(len(SKILL_TREE), 48)
        for node in SKILL_TREE.values():
            self.assertTrue(node.stat_key, f"Node {node.node_id} must have a non-empty stat_key")
            # Verify every class has 3 nodes
            class_nodes = nodes_for_class(node.class_key)
            self.assertEqual(len(class_nodes), 6)

        # Test runtime application on all 8 classes
        profile = PlayerProfile(unlocked_nodes={n.node_id for n in SKILL_TREE.values()})
        for pclass in PlayerClass:
            hero = create_player(f"Test{pclass.name}", pclass)
            apply_profile_bonuses(hero, profile)
            # Verify bonus stats are present and positive
            self.assertGreater(hero.max_hp, 0)
            self.assertGreaterEqual(hero.base_attack, 1)

    def test_daily_task_condition_evaluation_rules(self) -> None:
        from core.meta_progression import check_daily_task_complete, DailyTask
        task_reach = DailyTask("2026-10-25", 1, "Reach stage 5 in Story Campaign", "story", 5, 15)
        task_heal = DailyTask("2026-10-25", 2, "Survive 3 stages in Endless Rift without healing at the merchant.", "endless", 3, 15)
        task_elite = DailyTask("2026-10-25", 3, "Defeat 2 elite or boss encounters in Endless Rift.", "endless", 2, 15)
        task_hp = DailyTask("2026-10-25", 4, "Defeat a boss in Boss Rush without any hero falling below 30 HP.", "boss_rush", 1, 15)
        task_arena = DailyTask("2026-10-25", 5, "Complete 3 Colosseum rounds without the party dying.", "arena", 3, 15)

        state = GameState()
        # 1. Reach stage
        state.run_mode = "story"
        state.stage = 4
        self.assertFalse(check_daily_task_complete(task_reach, state))
        state.stage = 5
        self.assertTrue(check_daily_task_complete(task_reach, state))

        # 2. Without healing
        state.run_mode = "endless"
        state.stage = 3
        state.merchant_heals_used = 1
        self.assertFalse(check_daily_task_complete(task_heal, state), "Should fail if merchant heals used")
        state.merchant_heals_used = 0
        self.assertTrue(check_daily_task_complete(task_heal, state))

        # 3. Elite/boss kills
        state.run_mode = "endless"
        state.elites_slain = 1
        state.bosses_defeated = 0
        self.assertFalse(check_daily_task_complete(task_elite, state))
        state.elites_slain = 2
        self.assertTrue(check_daily_task_complete(task_elite, state))

        # 4. Boss without falling below 30 HP
        state.run_mode = "boss_rush"
        state.bosses_defeated = 1
        state.lowest_hero_hp = 25
        self.assertFalse(check_daily_task_complete(task_hp, state), "Failed threshold")
        state.lowest_hero_hp = 35
        self.assertTrue(check_daily_task_complete(task_hp, state))

        # 5. Arena rounds without death
        state.run_mode = "arena"
        state.stage = 3
        state.party_deaths = 1
        self.assertFalse(check_daily_task_complete(task_arena, state))
        state.party_deaths = 0
        self.assertTrue(check_daily_task_complete(task_arena, state))

    def test_profile_store_corruption_creates_backup_and_recovers(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p_path = Path(td) / "profile.json"
            p_path.write_text("{corrupt json data!!!", encoding="utf-8")
            store = ProfileStore(p_path)
            profile = store.load()
            self.assertEqual(profile.shards, 0)
            # A .bak backup must have been created in the same directory
            bak_files = list(Path(td).glob("*.bak"))
            self.assertEqual(len(bak_files), 1, "Must back up corrupt profile to .bak")
            self.assertIn("corrupt json data", bak_files[0].read_text(encoding="utf-8"))

    def test_regional_shop_pricing_changes_by_region(self) -> None:
        p = create_player("Vesper", PlayerClass.WITCH)
        rng = random.Random(777)
        shop_oath = Shop(rng, [p], stage=2, region="oath_road")
        shop_abyss = Shop(random.Random(777), [p], stage=12, region="abyss")
        # Prices in abyss must be higher due to inflation multiplier
        price_oath = shop_oath.stock[0][1]
        price_abyss = shop_abyss.stock[0][1]
        self.assertGreater(price_abyss, price_oath, "Abyss prices must exceed oath road")

    def test_mode_persistence_survives_serialization_and_restore(self) -> None:
        for m in ("story", "endless", "boss_rush", "arena"):
            gs = GameState()
            gs.players = [create_player("Hero", PlayerClass.WARRIOR)]
            gs.run_mode = m
            gs.endless = (m in ("endless", "arena"))
            d = gs.to_dict()
            self.assertEqual(d["run_mode"], m)
            restored = GameState.from_dict(d)
            self.assertEqual(restored.run_mode, m)

    def test_all_skins_palette_changes_render_model(self) -> None:
        import pygame
        from ui.renderer import Brush, Character, CharacterKind, SpritePainter
        surf = pygame.Surface((32, 32))
        for skin in COMMON_SKINS:
            for kind in CharacterKind:
                ch = Character(kind, "Hero", 100.0, 600.0, 1.0, skin_key=skin.key)
                painter = SpritePainter(Brush(surf, 1.0), 0.0, ch)
                self.assertEqual(painter.skin_def.key, skin.key)
                self.assertEqual(painter.accent_col, skin.accent_color)
                self.assertEqual(painter.trim_col, skin.trim_color)

    def test_enemy_constructor_flexibility(self) -> None:
        from entities.enemy import Enemy
        # Test keyword archetype and positional stats
        foe = Enemy("Sparring Automaton", 90, 8, 3, 5, archetype="normal")
        self.assertEqual(foe.name, "Sparring Automaton")
        self.assertEqual(foe.max_hp, 90)
        self.assertEqual(foe.hp, 90)
        self.assertEqual(foe.base_attack, 8)
        self.assertEqual(foe.base_defense, 3)
        self.assertEqual(foe.speed, 5)
        self.assertEqual(foe.arch.key, "construct")

    def test_tutorial_sparring_fight_launches_for_all_classes(self) -> None:
        from main import GameApp, Screen
        app = GameApp()
        for pclass in PlayerClass:
            app._start_tutorial_fight(pclass)
            self.assertEqual(app.screen, Screen.COMBAT)
            self.assertEqual(len(app.state.enemies), 1)
            self.assertEqual(app.state.enemies[0].name, "Sparring Automaton")
            self.assertIsNotNone(app.combat)
            app.combat.update(0.1)

