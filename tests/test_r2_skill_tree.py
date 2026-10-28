"""R2 skill tree (48 nodes) and Sensory Deprivation intent blackout.

Every perk is verified through the real CombatSystem / entities - not by reading attributes back.
"""
from __future__ import annotations

import json
import logging
import random
import types
import unittest
from unittest import mock

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from core.meta_progression import (PERK_HELP, SKILL_TREE, PlayerProfile, apply_profile_bonuses,  # noqa: E402
                                   nodes_for_class)
from entities.player import FallenAngel, Restraint, Vampire, create_player  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402
from systems.restraint_trials import PacedMashQTE, SealStagesQTE, AlternatingQTE, scale_time  # noqa: E402


def fight(cls: PlayerClass = PlayerClass.WARRIOR, seed: int = 3, stage: int = 1):
    state = GameState(seed=seed)
    state.new_run([PlayerConfig("Hero", cls)], "Normal", endless=False)
    state.stage = stage
    state.spawn_encounter()
    combat = CombatSystem(state)
    hero, foe = state.players[0], state.enemies[0]
    foe.max_hp = foe.hp = 10 ** 6
    hero.max_hp = hero.hp = 1000
    hero.base_attack = 500          # large numbers so integer rounding cannot blur the ratios
    return state, combat, hero, foe


def hit(combat, hero, foe, **kw) -> int:
    foe.hp = foe.max_hp
    return combat.strike(hero, foe, 1.0, crit_chance=0.0, **kw)


class TreeShapeTests(unittest.TestCase):
    def test_shape_branches_and_costs(self) -> None:
        self.assertEqual(len(SKILL_TREE), 48)
        for pc in PlayerClass:
            nodes = {n.node_id.rsplit("_t", 1)[1]: n for n in nodes_for_class(pc.name)}
            self.assertEqual(sorted(nodes), ["1", "2", "3", "4", "5", "6"])
            self.assertEqual({n.branch for n in nodes.values()}, {"core", "specialisation", "utility", "capstone"})
            self.assertEqual(nodes["4"].requires, (f"{pc.name.lower()}_t1",))
            self.assertEqual(nodes["5"].requires, (f"{pc.name.lower()}_t1",))
            self.assertEqual(set(nodes["6"].requires), {nodes[k].node_id for k in ("3", "4", "5")})
            self.assertTrue(nodes["6"].tradeoff, f"{pc.name} capstone must state its downside")
            self.assertTrue(nodes["6"].extra, f"{pc.name} capstone must carry a mechanical tradeoff/extra")
            self.assertEqual([nodes[k].cost for k in "123456"], [5, 10, 20, 12, 12, 30])

    def test_no_cycles_and_all_requirements_exist(self) -> None:
        for node in SKILL_TREE.values():
            seen, stack = set(), list(node.requires)
            while stack:
                r = stack.pop()
                self.assertIn(r, SKILL_TREE)
                self.assertNotEqual(r, node.node_id)
                if r not in seen:
                    seen.add(r)
                    stack.extend(SKILL_TREE[r].requires)

    def test_every_perk_key_is_documented_and_unique_per_class_effect(self) -> None:
        for node in SKILL_TREE.values():
            for key, _d in ((node.stat_key, node.stat_delta), *node.extra):
                if key.startswith("perk_"):
                    self.assertIn(key[5:], PERK_HELP, f"{node.node_id}: {key}")
        for pc in PlayerClass:
            names = [n.name for n in nodes_for_class(pc.name)]
            descs = [n.description for n in nodes_for_class(pc.name)]
            self.assertEqual(len(set(names)), 6)
            self.assertEqual(len(set(descs)), 6)

    def test_purchase_and_refund_rules(self) -> None:
        p = PlayerProfile(shards=200)
        ok, msg = p.purchase_node("warrior_t4")
        self.assertFalse(ok)
        self.assertIn("tier 1", msg.lower())
        for nid in ("warrior_t1", "warrior_t2", "warrior_t3", "warrior_t4"):
            self.assertTrue(p.purchase_node(nid)[0], nid)
        ok, msg = p.purchase_node("warrior_t6")
        self.assertFalse(ok, "capstone needs the utility node too")
        self.assertTrue(p.purchase_node("warrior_t5")[0])
        self.assertTrue(p.purchase_node("warrior_t6")[0])
        spent = 200 - p.shards
        self.assertEqual(spent, 5 + 10 + 20 + 12 + 12 + 30)
        self.assertTrue(p.refund_node("warrior_t4")[0])
        self.assertNotIn("warrior_t6", p.unlocked_nodes, "capstone depends on the refunded node")
        self.assertIn("warrior_t3", p.unlocked_nodes)
        self.assertTrue(p.refund_node("warrior_t1")[0])
        self.assertEqual(p.unlocked_nodes, set())
        self.assertEqual(p.shards, 200 - 89 + (12 // 2 + 30 // 2) + (5 // 2 + 10 // 2 + 20 // 2 + 12 // 2), "50% refund of every removed node")

    def test_legacy_profile_with_old_nodes_still_valid(self) -> None:
        p = PlayerProfile.from_dict({"shards": 40, "unlocked_nodes": ["warrior_t1", "warrior_t2", "rogue_t1"]})
        self.assertEqual(p.unlocked_nodes, {"warrior_t1", "warrior_t2", "rogue_t1"})
        self.assertFalse(p.purchase_node("warrior_t6")[0])
        self.assertTrue(p.purchase_node("warrior_t3")[0])


class PerkApplicationTests(unittest.TestCase):
    def test_apply_is_idempotent_for_perks_and_includes_extras(self) -> None:
        profile = PlayerProfile(unlocked_nodes={n.node_id for n in SKILL_TREE.values()})
        for pc in PlayerClass:
            hero = create_player("T", pc)
            apply_profile_bonuses(hero, profile)
            first = dict(hero.perks)
            apply_profile_bonuses(hero, profile)
            self.assertEqual(hero.perks, first, f"{pc.name} perks must not stack")
            cap = nodes_for_class(pc.name)[5]
            for key, delta in ((cap.stat_key, cap.stat_delta), *cap.extra):
                self.assertIn(key[5:], hero.perks, f"{pc.name} {key}")

    def test_perks_survive_save_and_load(self) -> None:
        state = GameState(seed=1)
        state.new_run([PlayerConfig("Hero", PlayerClass.TANK)], "Normal", endless=False)
        state.players[0].perks = {"thorns": 6.0, "dealt": -0.1}
        data = json.loads(json.dumps(state.to_dict()))
        loaded = GameState.from_dict(data)
        self.assertEqual(loaded.players[0].perks, {"thorns": 6.0, "dealt": -0.1})


class OffencePerkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state, self.combat, self.hero, self.foe = fight()

    def ratio(self, perks: dict, setup=None, **kw) -> float:
        self.hero.perks = {}
        self.combat._opened.clear()
        base = hit(self.combat, self.hero, self.foe, **kw)
        self.hero.perks = dict(perks)
        self.combat._opened.clear()
        if setup:
            setup()
        return hit(self.combat, self.hero, self.foe, **kw) / base

    def test_dealt(self) -> None:
        self.assertAlmostEqual(self.ratio({"dealt": 0.2}), 1.2, delta=0.03)
        self.assertAlmostEqual(self.ratio({"dealt": -0.1}), 0.9, delta=0.03)

    def test_wounded_dealt_needs_low_hp(self) -> None:
        self.assertAlmostEqual(self.ratio({"wounded_dealt": 0.35}), 1.0, delta=0.02)
        self.hero.hp = 400
        self.assertAlmostEqual(self.ratio({"wounded_dealt": 0.35}), 1.35, delta=0.03)

    def test_execute_needs_low_target(self) -> None:
        self.hero.perks = {"execute": 0.3}
        self.combat._opened.add(self.hero.uid)
        self.foe.hp = self.foe.max_hp
        high = self.combat.strike(self.hero, self.foe, 1.0)
        self.foe.hp = int(self.foe.max_hp * 0.3)
        low = self.combat.strike(self.hero, self.foe, 1.0)
        self.assertAlmostEqual(low / high, 1.3, delta=0.03)

    def test_opener_only_first_strike(self) -> None:
        self.hero.perks = {"opener": 0.6}
        self.combat._opened.clear()
        first = hit(self.combat, self.hero, self.foe)
        second = hit(self.combat, self.hero, self.foe)
        self.assertAlmostEqual(first / second, 1.6, delta=0.03)

    def test_crit_damage(self) -> None:
        r = self.ratio({"crit_dmg": 0.5}, force_crit=True)
        self.assertAlmostEqual(r, 2.3 / 1.8, delta=0.03)

    def test_lifesteal(self) -> None:
        self.hero.perks = {"lifesteal": 0.12}
        self.hero.hp = 500
        dealt = hit(self.combat, self.hero, self.foe)
        self.assertEqual(self.hero.hp, 500 + max(1, int(dealt * 0.12)))

    def test_regen_at_turn_start(self) -> None:
        self.hero.hp = 500
        self.hero.perks = {}
        self.combat._begin_player_turn(self.hero)
        base = self.hero.hp
        self.hero.hp = 500
        self.hero.perks = {"regen": 0.04}
        self.combat._begin_player_turn(self.hero)
        self.assertEqual(self.hero.hp - base, 40)


class DefencePerkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state, self.combat, self.hero, self.foe = fight(PlayerClass.TANK, seed=5)
        self.foe.max_hp = self.foe.hp = 10 ** 6

    def loss(self, perks: dict, hp: int = 1000) -> int:
        self.hero.perks = dict(perks)
        self.hero.hp = hp
        self.foe.hp = self.foe.max_hp
        self.combat._enemy_hit(self.foe, self.hero, 1.0, heavy=False)
        return hp - self.hero.hp

    def test_flat_reduction(self) -> None:
        base = self.loss({})
        self.assertGreater(base, 4)
        self.assertEqual(base - self.loss({"reduce": 3.0}), 3)

    def test_taken_tradeoff_increases_damage(self) -> None:
        base = self.loss({})
        self.assertAlmostEqual(self.loss({"taken": 0.2}) / base, 1.2, delta=0.1)

    def test_laststand_only_when_low(self) -> None:
        base_low = self.loss({}, hp=300)
        self.assertLess(self.loss({"laststand": 0.4}, hp=300), base_low)
        self.assertEqual(self.loss({"laststand": 0.4}, hp=900), self.loss({}, hp=900))

    def test_evade(self) -> None:
        self.hero.perks = {"evade": 0.6}
        dodged = 0
        for _ in range(300):
            self.hero.hp = 1000
            self.foe.hp = self.foe.max_hp
            self.combat._enemy_hit(self.foe, self.hero, 1.0, heavy=False)
            dodged += self.hero.hp == 1000
        self.assertTrue(110 < dodged < 250, dodged)
        self.hero.perks = {}
        self.hero.hp = 1000
        self.combat._enemy_hit(self.foe, self.hero, 1.0, heavy=False)
        self.assertLess(self.hero.hp, 1000)

    def test_thorns_reflect_exact_damage(self) -> None:
        self.hero.perks = {"thorns": 6.0}
        self.hero.hp = 1000
        before = self.foe.hp
        self.combat._enemy_hit(self.foe, self.hero, 1.0, heavy=False)
        self.assertEqual(before - self.foe.hp, 6)

    def test_thorns_can_kill_a_weak_attacker(self) -> None:
        self.hero.perks = {"thorns": 6.0}
        self.foe.hp = 3
        self.combat._enemy_hit(self.foe, self.hero, 1.0, heavy=False)
        self.assertFalse(self.foe.alive)


class ClassSpecificPerkTests(unittest.TestCase):
    def test_vampire_veil_absorbs_hp_as_described(self) -> None:
        state, combat, hero, foe = fight(PlayerClass.VAMPIRE)
        self.assertIsInstance(hero, Vampire)
        hero.veil_bonus = 5.0
        hero.blood = 60
        hero.use("veil_night", None, None, combat)
        self.assertEqual(hero.veil_pool, 5)
        hero.hp = 100
        hero.take_damage(8)
        hero.on_hit_taken(8)
        self.assertEqual(hero.hp, 97)
        self.assertEqual(hero.veil_pool, 0)

    def test_angel_lucid_ledger_softens_backlash_and_delays_correction(self) -> None:
        a = create_player("A", PlayerClass.ANGEL)
        self.assertEqual((a.break_backlash(), a.correction_after), ((14, 20.0), 2))
        a.perks = {"break_soft": 1.0}
        self.assertEqual((a.break_backlash(), a.correction_after), ((11, 15.0), 3))
        a.failed_breaks = 1
        self.assertEqual(a.break_backlash(), (14, 20.0))

    def test_angel_penitent_focus_scales_trial_time(self) -> None:
        q = PacedMashQTE(12, 5.0)
        scale_time(q, 1.25)
        self.assertAlmostEqual(q.limit, 6.25)
        seal = SealStagesQTE([AlternatingQTE(2, 4.0), AlternatingQTE(2, 6.0)], "S")
        scale_time(seal, 1.5)
        self.assertAlmostEqual(seal.limit, 15.0)
        q2 = PacedMashQTE(12, 5.0)
        scale_time(q2, 1.0)
        self.assertEqual(q2.limit, 5.0)

    def test_angel_penitent_focus_in_real_break(self) -> None:
        state, combat, hero, foe = fight(PlayerClass.ANGEL, seed=4, stage=2)
        hero.restraints = {Restraint.IRON_GAG}
        limits = []
        for perks in ({}, {"trial_time": 0.25}):
            hero.perks = dict(perks)
            s2, c2, h2, f2 = fight(PlayerClass.ANGEL, seed=4, stage=2)
            h2.restraints = {Restraint.IRON_GAG}
            h2.perks = dict(perks)
            for _ in range(400):
                if c2.phase is Phase.MENU:
                    break
                c2.update(0.05)
            c2.menu_idx = next(i for i, e in enumerate(c2.menu) if e.ability and e.ability.key == "break")
            c2.handle_key("return")
            limits.append(c2.qte.limit)
        self.assertAlmostEqual(limits[1] / limits[0], 1.25, delta=0.01)

    def test_angel_brief_release_ignores_restraint_penalty_once(self) -> None:
        state, combat, hero, foe = fight(PlayerClass.ANGEL, seed=6)
        self.assertIsInstance(hero, FallenAngel)
        hero.restraints = {Restraint.IRON_GAG, Restraint.MANACLES}
        bound = hit(combat, hero, foe)
        hero.release_window = 1
        free = hit(combat, hero, foe)
        again = hit(combat, hero, foe)
        self.assertGreater(free, bound * 1.2)
        self.assertEqual(hero.release_window, 0)
        self.assertEqual(again, bound, "the release lasts exactly one strike")

    def test_angel_brief_release_trigger_and_cost(self) -> None:
        class C:
            rng = random.Random(1)
            def log(self, *a, **k): pass
            def alert(self, *a, **k): pass
            def hurt_self(self, hero, n): hero.hp -= n
        a = create_player("A", PlayerClass.ANGEL)
        a.restraints = {Restraint.MANACLES}
        a.stamina = a.max_stamina
        a.lucidity = 60.0
        a.perks = {"release": 1.0, "release_cost": 8.0}
        a.use("break", None, True, C())
        self.assertEqual(len(a.restraints), 0)
        self.assertEqual(a.release_window, 1)
        self.assertEqual(a.lucidity, 52.0)
        a.after_battle()
        self.assertEqual(a.release_window, 0)


class FullTreeFightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    def test_every_class_with_all_nodes_finishes_fights_in_bounds(self) -> None:
        profile = PlayerProfile(unlocked_nodes={n.node_id for n in SKILL_TREE.values()})
        keys = ["up", "down", "left", "right", "return", "space", "escape", "a", "d", "1", "2", "3", "4"]
        for cls in PlayerClass:
            for seed in (11, 12, 13):
                rng = random.Random(seed)
                state = GameState(seed=seed)
                state.new_run([PlayerConfig("H", cls)], "Normal", endless=False)
                for pl in state.players:
                    apply_profile_bonuses(pl, profile)
                state.stage = rng.choice((1, 4, 12))
                state.spawn_encounter()
                combat = CombatSystem(state)
                steps = 0
                while combat.phase not in (Phase.VICTORY, Phase.DEFEAT) and steps < 4000:
                    steps += 1
                    if combat.phase in (Phase.RESOLVE, Phase.ENEMY):
                        combat.update(rng.choice((0.05, 0.3, 1.0)))
                    elif combat.phase is Phase.QTE:
                        combat.update(31.0) if rng.random() < 0.5 else combat.handle_key(rng.choice(keys))
                    else:
                        combat.handle_key(rng.choice(keys))
                    for p in state.players:
                        self.assertTrue(0 <= p.hp <= p.max_hp + 1e-6, f"{cls.name} seed {seed}: hp {p.hp}/{p.max_hp}")
                self.assertIn(combat.phase, (Phase.VICTORY, Phase.DEFEAT), f"{cls.name} seed {seed} never ended")


class IntentBlackoutTests(unittest.TestCase):
    def deprived_fight(self):
        state, combat, hero, foe = fight(PlayerClass.ANGEL, seed=8, stage=2)
        hero.restraints = {Restraint.DEPRIVATION}
        for _ in range(400):
            if combat.phase is Phase.MENU:
                break
            combat.update(0.05)
        return state, combat, hero, foe

    def test_combat_masks_intent_for_deprived_angel(self) -> None:
        state, combat, hero, foe = self.deprived_fight()
        self.assertTrue(combat.intent_hidden)
        prev = combat.intent_preview(foe)
        self.assertTrue(prev.hidden)
        self.assertEqual(prev.label, "???")
        self.assertEqual(prev.damage, 0)
        hero.restraints = set()
        self.assertFalse(combat.intent_hidden)

    def _card_texts(self, hidden: bool):
        import main as game_main
        painter = object.__new__(game_main.Painter)
        painter.f = {"small": "S", "tiny": "T", "mid": "M"}
        painter.intent_hidden = hidden
        enemy = types.SimpleNamespace(
            name="Gilded Sentinel", hp=89, max_hp=89, atk=17,
            intent=types.SimpleNamespace(kind=types.SimpleNamespace(name="HEAVY"), power=1.7, hits=1))
        calls = []
        fake_pg = mock.MagicMock()
        with mock.patch.object(game_main, "pygame", fake_pg), mock.patch.object(game_main, "panel"), \
                mock.patch.object(game_main, "draw_bar"), mock.patch.object(game_main, "fit_text", lambda f, t, w: t), \
                mock.patch.object(game_main, "draw_text", lambda *a, **k: calls.append(a[2])):
            painter._enemy_card(mock.MagicMock(), enemy, 300, 400, 200, False)
        return calls, fake_pg

    def test_enemy_card_blacks_out_intent_when_hidden(self) -> None:
        calls, fake_pg = self._card_texts(True)
        self.assertIn("> ???", calls)
        self.assertFalse([c for c in calls if isinstance(c, str) and c.startswith("> ") and c != "> ???"],
                         f"intent text leaked: {calls}")
        self.assertTrue(fake_pg.draw.rect.called, "a black bar must be drawn over the intent line")

    def test_enemy_card_shows_intent_normally(self) -> None:
        calls, _ = self._card_texts(False)
        self.assertTrue([c for c in calls if isinstance(c, str) and c.startswith("> ") and c != "> ???"], calls)
        self.assertNotIn("> ???", calls)


if __name__ == "__main__":
    unittest.main()
