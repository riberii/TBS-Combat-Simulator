"""R2 skill trees: 6 nodes per class, every node has a live runtime effect, perks hold in combat and survive saves."""
from __future__ import annotations

import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from core.meta_progression import (MAX_TIER, SKILL_TREE, PlayerProfile, apply_profile_bonuses,  # noqa: E402
                                   nodes_for_class)
from core.perks import PERK_DEFAULTS  # noqa: E402
from entities.base_entity import Status  # noqa: E402
from entities.enemy import Enemy  # noqa: E402
from entities.player import FallenAngel, Restraint, create_player  # noqa: E402
from systems.combat_system import CombatSystem  # noqa: E402

# stat_key -> attribute (or callable reading it) that must change after unlocking that single node.
ATTR = {"max_hp": "max_hp", "max_mp": "max_mana", "max_sta": "max_stamina", "atk_mult": "base_attack",
        "def_mult": "base_defense", "break_bonus": "_profile_break_bonus", "lucidity_start": "lucidity",
        "rage_regen": "rage_bonus", "sta_regen": "sta_regen_bonus", "crit_bonus": "crit_bonus", "combo_cap": "combo_max",
        "spell_mult": "spell_mult", "mp_regen": "mp_regen_bonus", "max_spirit": "spirit_bonus", "fox_mult": "fox_mult",
        "decoy_extra": "decoy_extra", "blood_mult": "blood_mult", "veil_bonus": "veil_bonus", "heat_cap": "heat_cap_bonus"}


def _fight(classes=(PlayerClass.WARRIOR,), stage=2, seed=5):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(classes)], "Normal", endless=False)
    st.stage = stage - 1
    st.spawn_encounter()
    return st, CombatSystem(st)


class TreeShapeTests(unittest.TestCase):
    def test_six_nodes_per_class_with_rising_costs(self):
        self.assertEqual(MAX_TIER, 6)
        for pc in PlayerClass:
            nodes = nodes_for_class(pc.name)
            self.assertEqual([n.tier for n in nodes], [1, 2, 3, 4, 5, 6])
            costs = [n.cost for n in nodes]
            self.assertEqual(costs, sorted(costs))
            self.assertEqual(len({n.name for n in nodes}), 6, "node names must be unique within a class")

    def test_every_node_has_a_live_runtime_effect(self):
        for node in SKILL_TREE.values():
            with self.subTest(node=node.node_id):
                pc = PlayerClass[node.class_key]
                base, hero = create_player("B", pc), create_player("H", pc)
                apply_profile_bonuses(hero, PlayerProfile(unlocked_nodes={node.node_id}))
                attr = ATTR.get(node.stat_key, node.stat_key)
                self.assertTrue(hasattr(hero, attr), f"{attr} missing on {pc.name}")
                self.assertNotEqual(getattr(hero, attr), getattr(base, attr), f"{node.node_id} changed nothing")

    def test_prerequisite_chain_and_refund_cascade_for_all_tiers(self):
        for pc in PlayerClass:
            key = pc.name.lower()
            p = PlayerProfile(shards=1000)
            ok, _ = p.purchase_node(f"{key}_t6")
            self.assertFalse(ok, "tier 6 must need tier 5")
            for t in range(1, 7):
                ok, msg = p.purchase_node(f"{key}_t{t}")
                self.assertTrue(ok, msg)
            ok, _ = p.refund_node(f"{key}_t2")
            self.assertTrue(ok)
            self.assertEqual({n for n in p.unlocked_nodes if n.startswith(key + "_")}, {f"{key}_t1"})

    def test_profile_roundtrip_keeps_all_six_tiers(self):
        p = PlayerProfile(shards=0, unlocked_nodes={n.node_id for n in SKILL_TREE.values()})
        self.assertEqual(PlayerProfile.from_dict(p.to_dict()).unlocked_nodes, p.unlocked_nodes)


class CombatPerkTests(unittest.TestCase):
    def _hit(self, hero_class, perk=None, value=0, foe_hp_mult=1.0):
        st, c = _fight((hero_class,))
        hero, foe = st.players[0], c.enemies_alive()[0]
        if perk:
            setattr(hero, perk, value)
        foe.hp = foe.max_hp = int(10_000 * foe_hp_mult)
        c.rng.random = lambda: 0.99      # no crits / no status procs
        return c, hero, foe

    def test_damage_perk_scales_and_is_capped(self):
        c0, h0, f0 = self._hit(PlayerClass.WARRIOR)
        base = c0.strike(h0, f0, 1.0)
        c1, h1, f1 = self._hit(PlayerClass.WARRIOR, "perk_dmg", 0.10)
        boosted = c1.strike(h1, f1, 1.0)
        c2, h2, f2 = self._hit(PlayerClass.WARRIOR, "perk_dmg", 5.0)
        capped = c2.strike(h2, f2, 1.0)
        self.assertGreater(boosted, base)
        self.assertLessEqual(capped, int(base * 1.5) + 2)

    def test_crit_damage_perk(self):
        c0, h0, f0 = self._hit(PlayerClass.ROGUE)
        base = c0.strike(h0, f0, 1.0, force_crit=True)
        c1, h1, f1 = self._hit(PlayerClass.ROGUE, "perk_crit_dmg", 0.5)
        self.assertGreater(c1.strike(h1, f1, 1.0, force_crit=True), base)

    def test_guard_perk_reduces_incoming_damage_and_never_beats_the_cap(self):
        st, c = _fight((PlayerClass.TANK,))
        hero, foe = st.players[0], c.enemies_alive()[0]
        hero.hp = hero.max_hp = 100000
        c.rng.random = lambda: 0.99
        base = c._enemy_hit.__self__  # noqa: F841 (documenting that the same method is exercised)
        before = hero.hp
        c._enemy_hit(foe, hero, 1.0, heavy=False)
        plain = before - hero.hp
        hero.hp = before
        hero.perk_guard = 9.0
        c._enemy_hit(foe, hero, 1.0, heavy=False)
        guarded = before - hero.hp
        self.assertLess(guarded, plain)
        self.assertGreaterEqual(guarded, int(plain * 0.6) - 1, "guard is capped at 40%")

    def test_last_gasp_saves_once_per_battle_and_resets(self):
        st, c = _fight((PlayerClass.VAMPIRE,))
        hero, foe = st.players[0], c.enemies_alive()[0]
        hero.perk_lastgasp = 1
        foe.base_attack = 10_000
        hero.hp = 20
        c._enemy_hit(foe, hero, 5.0, heavy=True)
        self.assertEqual(hero.hp, 1, "first lethal blow is survived at 1 HP")
        hero.hp = 20
        c._enemy_hit(foe, hero, 5.0, heavy=True)
        self.assertFalse(hero.alive, "the gasp is once per battle")
        hero.lastgasp_used = 1
        hero.after_battle()
        self.assertEqual(hero.lastgasp_used, 0)

    def test_thorns_reflect_to_the_attacker(self):
        st, c = _fight((PlayerClass.TANK,))
        hero, foe = st.players[0], c.enemies_alive()[0]
        hero.hp = hero.max_hp = 100000
        hero.perk_thorns = 0.5
        before = foe.hp
        c._enemy_hit(foe, hero, 2.0, heavy=False)
        self.assertLess(foe.hp, before)

    def test_kill_heal_and_turn_regen(self):
        c, hero, foe = self._hit(PlayerClass.WARRIOR, "perk_kill_heal", 7)
        hero.hp = hero.max_hp - 30
        foe.hp = 1
        c.strike(hero, foe, 1.0)
        self.assertFalse(foe.alive)
        self.assertEqual(hero.hp, hero.max_hp - 30 + 7)
        hero.perk_regen_hp = 4
        before = hero.hp
        hero.on_turn_start(c)
        self.assertEqual(hero.hp, before + 4)


class AngelPerkTests(unittest.TestCase):
    def _angel(self):
        st, c = _fight((PlayerClass.ANGEL,))
        angel = st.players[0]
        angel.restraints.update({Restraint.ANCHOR, Restraint.MANACLES})
        return st, c, angel

    def test_practiced_hands_adds_mistakes_only_to_forgiving_trials(self):
        import random
        from systems.restraint_trials import TRIAL_BY_ID
        _st, c, angel = self._angel()
        alt = TRIAL_BY_ID["alt_manacles"].build(random.Random(1), 2)
        word = TRIAL_BY_ID["word_gag"].build(random.Random(1), 2)
        a0, w0 = alt.max_slips, word.max_slips
        c._grant_slips(alt, 2)
        c._grant_slips(word, 2)
        self.assertEqual(alt.max_slips, a0 + 2)
        self.assertEqual(word.max_slips, w0, "fatal trials stay unforgiving")

    def test_lucid_penance_and_measured_release(self):
        _st, c, angel = self._angel()
        angel.trial_clarity = 8
        angel.lucidity = 40.0
        c.active = angel

        class _Done:  # minimal finished trial
            pass
        from systems.restraint_trials import TRIAL_BY_ID, run_script
        import random
        t = TRIAL_BY_ID["alt_manacles"].build(random.Random(2), 1)
        self.assertTrue(run_script(t, t.solution_script()))
        c._record_trial(t)
        self.assertEqual(angel.lucidity, 48.0)
        st2 = GameState(seed=1)
        st2.new_run([PlayerConfig("A", PlayerClass.ANGEL)], "Normal", endless=False)
        st2.players[0].momentum_start = 2
        st2.spawn_encounter()
        CombatSystem(st2)
        self.assertEqual(st2.players[0].break_momentum, 2)


class GraceTouchedTests(unittest.TestCase):
    def test_grace_touched_recovers_extra_lucidity_after_battle(self):
        a, b = create_player("A", PlayerClass.ANGEL), create_player("B", PlayerClass.ANGEL)
        b.lucidity_recover = 8
        a.lucidity = b.lucidity = 40.0
        a.after_battle()
        b.after_battle()
        self.assertEqual(b.lucidity - a.lucidity, 8.0)


class PerkPersistenceTests(unittest.TestCase):
    def test_every_perk_attribute_exists_on_every_hero(self):
        for pc in PlayerClass:
            hero = create_player("H", pc)
            for k, v in PERK_DEFAULTS.items():
                self.assertEqual(getattr(hero, k), v, f"{pc.name}.{k}")

    def test_unlocked_perks_survive_save_and_load(self):
        profile = PlayerProfile(unlocked_nodes={n.node_id for n in SKILL_TREE.values()})
        st = GameState(seed=3)
        st.new_run([PlayerConfig("W", PlayerClass.WARRIOR), PlayerConfig("A", PlayerClass.ANGEL)], "Normal", endless=False)
        for p in st.players:
            apply_profile_bonuses(p, profile)
        loaded = GameState.from_dict(st.to_dict())
        for orig, new in zip(st.players, loaded.players):
            for k in PERK_DEFAULTS:
                self.assertEqual(getattr(new, k), getattr(orig, k), f"{orig.pclass.name}.{k} lost on load")
        self.assertGreater(loaded.players[0].perk_dmg, 0)


if __name__ == "__main__":
    unittest.main()
