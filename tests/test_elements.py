"""R2 damage types, affinities and elemental statuses."""
from __future__ import annotations

import random
import unittest

from tools.headless_bootstrap import install_import_stub_if_missing

install_import_stub_if_missing()

from core.config import PlayerClass  # noqa: E402
from core.elements import (ABILITY_ELEMENT, ARCHETYPE_AFFINITY, CLASS_AFFINITY, STATUS_FOR, DamageType,  # noqa: E402
                           affinity, affinity_summary, affinity_tag, attack_element, element_of_ability)
from core.game_state import GameState, PlayerConfig  # noqa: E402
from entities.base_entity import Status  # noqa: E402
from entities.enemy import ARCHETYPES, BOSS_ROSTER, Enemy  # noqa: E402
from entities.player import create_player  # noqa: E402
from systems.combat_system import CombatSystem, EventKind  # noqa: E402


def _fight(cls=PlayerClass.WITCH, seed=4, stage=2):
    st = GameState(seed=seed)
    st.new_run([PlayerConfig("H", cls)], "Normal", endless=False)
    st.stage = stage - 1
    st.spawn_encounter()
    return st, CombatSystem(st)


def _foe(c, arch, hp=100000, boss=False):
    foe = c.enemies_alive()[0]
    foe.arch = ARCHETYPES[arch]
    foe.hp = foe.max_hp = hp
    foe.boss = boss
    foe.statuses.clear()
    return foe


class TableTests(unittest.TestCase):
    def test_tables_reference_real_things(self):
        for arch in ARCHETYPE_AFFINITY:
            self.assertIn(arch, ARCHETYPES)
        for name in CLASS_AFFINITY:
            self.assertIn(name, PlayerClass.__members__)
        ability_keys = {a.key for pc in PlayerClass for a in create_player("x", pc).abilities()}
        for key in ABILITY_ELEMENT:
            self.assertIn(key, ability_keys, f"{key} is not a real ability")
        for dt, (status, turns) in STATUS_FOR.items():
            self.assertIn(status, Status.__members__)
            self.assertGreater(turns, 0)

    def test_every_damage_type_is_used_and_has_a_counter(self):
        used = set(ABILITY_ELEMENT.values()) | {DamageType.PHYSICAL}
        self.assertEqual(used, set(DamageType))
        for dt in DamageType:
            weak_somewhere = any(table.get(dt, 1) > 1.15 for table in ARCHETYPE_AFFINITY.values())
            self.assertTrue(weak_somewhere or dt is DamageType.PHYSICAL, f"nothing is weak to {dt.name}")

    def test_bosses_are_softened(self):
        e = Enemy("undead")
        e.boss = False
        full = affinity(e, DamageType.HOLY)
        e.boss = True
        soft = affinity(e, DamageType.HOLY)
        self.assertGreater(full, soft)
        self.assertGreater(soft, 1.0)

    def test_tags_and_summary(self):
        self.assertEqual(affinity_tag(1.4), "weak")
        self.assertEqual(affinity_tag(0.5), "resist")
        self.assertEqual(affinity_tag(1.0), "")
        st, c = _fight()
        weak, res = affinity_summary(_foe(c, "undead"))
        self.assertIn(DamageType.HOLY, weak)
        self.assertIn(DamageType.SHADOW, res)

    def test_ability_element_defaults_to_physical(self):
        self.assertIs(element_of_ability("cleave"), DamageType.PHYSICAL)
        self.assertIs(element_of_ability("ember_breath"), DamageType.FIRE)


class DamageTests(unittest.TestCase):
    def _dmg(self, arch, dtype, seed=4):
        st, c = _fight(seed=seed)
        foe = _foe(c, arch)
        c.rng.random = lambda: 0.99          # no crit / status proc noise
        return c.strike(st.players[0], foe, 1.0, dtype=dtype), c, foe

    def test_weakness_deals_more_and_resistance_less(self):
        neutral, _, _ = self._dmg("hunter", DamageType.SHADOW)
        weak, _, _ = self._dmg("undead", DamageType.HOLY)
        resist, _, _ = self._dmg("cinder", DamageType.FIRE)
        base, _, _ = self._dmg("hunter", DamageType.PHYSICAL)
        self.assertGreater(weak, base)
        self.assertLess(resist, base)
        self.assertEqual(neutral, base)

    def test_true_damage_ignores_affinity(self):
        st, c = _fight()
        foe = _foe(c, "cinder")
        c.rng.random = lambda: 0.99
        a = c.strike(st.players[0], foe, 1.0, true_damage=True, dtype=DamageType.FIRE)
        foe2 = _foe(c, "hunter")
        b = c.strike(st.players[0], foe2, 1.0, true_damage=True, dtype=DamageType.FIRE)
        self.assertEqual(a, b)

    def test_ability_in_flight_sets_the_element(self):
        st, c = _fight(PlayerClass.WITCH)
        foe = _foe(c, "nature")                          # fire-weak, frost-resistant
        hero = st.players[0]
        c._cur_dtype = element_of_ability("bolt")        # Witch bolt = frost
        c.rng.random = lambda: 0.99
        frost = c.strike(hero, foe, 1.0)
        c._cur_dtype = DamageType.FIRE
        fire = c.strike(hero, foe, 1.0)
        self.assertGreater(fire, frost)

    def test_event_payload_reports_type_and_affinity(self):
        st, c = _fight()
        foe = _foe(c, "undead")
        c.rng.random = lambda: 0.99
        c.strike(st.players[0], foe, 1.0, dtype=DamageType.HOLY)
        ev = [e for e in c.events if e.kind in (EventKind.DAMAGE, EventKind.CRIT)][-1]
        self.assertEqual(ev.data["dtype"], "HOLY")
        self.assertEqual(ev.data["affinity"], "weak")

    def test_enemy_attacks_use_player_affinities(self):
        st, c = _fight(PlayerClass.DRAGONKIN)
        hero = st.players[0]
        hero.hp = hero.max_hp = 100000
        foe = _foe(c, "cinder")                          # fire attacker
        self.assertIs(attack_element(foe), DamageType.FIRE)
        c._enemy_hit(foe, hero, 1.0, heavy=False)
        fire_taken = 100000 - hero.hp
        hero.hp = 100000
        foe.arch = ARCHETYPES["hunter"]                  # physical attacker, same stats
        c._enemy_hit(foe, hero, 1.0, heavy=False)
        phys_taken = 100000 - hero.hp
        self.assertLess(fire_taken, phys_taken, "Dragonkin resists fire")


class StatusTests(unittest.TestCase):
    def test_weakness_always_applies_status_resist_never_does(self):
        for seed in range(20):
            st, c = _fight(seed=seed)
            hero = st.players[0]
            foe = _foe(c, "nature")                      # weak to fire
            c.rng.random = lambda: 0.99                  # worst possible roll
            c.strike(hero, foe, 1.0, dtype=DamageType.FIRE)
            self.assertIn(Status.BURN, foe.statuses)
            self.assertGreater(foe.burn_power, 0)
            res = _foe(c, "cinder")                      # resists fire
            c.rng.random = lambda: 0.0                   # best possible roll
            c.strike(hero, res, 1.0, dtype=DamageType.FIRE)
            self.assertNotIn(Status.BURN, res.statuses)

    def test_neutral_hits_proc_by_chance_and_are_seeded(self):
        def procs(seed):
            out = []
            for i in range(30):
                st, c = _fight(seed=seed)
                c.rng.seed(seed * 100 + i)
                foe = _foe(c, "hunter")
                c.strike(st.players[0], foe, 1.0, dtype=DamageType.SHADOW)
                out.append(Status.SUPPRESSED in foe.statuses)
            return out
        a = procs(3)
        self.assertEqual(a, procs(3))
        self.assertTrue(any(a) and not all(a))

    def test_chill_weakens_attacks_and_shock_is_spent_on_the_next_hit(self):
        st, c = _fight()
        foe = _foe(c, "hunter")
        base = foe.attack_power
        foe.add_status(Status.CHILL, 2)
        self.assertAlmostEqual(foe.attack_power, base * 0.8)
        c.rng.random = lambda: 0.99
        hero = st.players[0]
        plain = c.strike(hero, foe, 1.0, dtype=DamageType.PHYSICAL)
        foe.add_status(Status.SHOCK, 2)
        shocked = c.strike(hero, foe, 1.0, dtype=DamageType.PHYSICAL)
        again = c.strike(hero, foe, 1.0, dtype=DamageType.PHYSICAL)
        self.assertGreater(shocked, plain)
        self.assertEqual(again, plain)
        self.assertNotIn(Status.SHOCK, foe.statuses)

    def test_new_statuses_expire_and_clear(self):
        e = Enemy("construct")
        e.add_status(Status.CHILL, 1)
        e.add_status(Status.SHOCK, 1)
        e.end_round()
        self.assertFalse(e.statuses)
        e.add_status(Status.CHILL, 3)
        e.clear_statuses()
        self.assertFalse(e.statuses)
        self.assertIn(Status.CHILL, __import__("entities.base_entity", fromlist=["STATUS_COLORS"]).STATUS_COLORS)


class FullFightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import logging
        logging.disable(logging.CRITICAL)      # the QTE-stall failsafe logs on purpose

    @classmethod
    def tearDownClass(cls):
        import logging
        logging.disable(logging.NOTSET)

    def test_random_fights_with_elements_still_finish(self):
        from systems.combat_system import Phase
        for seed in range(1, 10):
            rng = random.Random(seed)
            st = GameState(seed=seed)
            st.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(rng.sample(list(PlayerClass), 2))], "Normal", endless=False)
            st.stage = rng.choice((1, 4))
            st.spawn_encounter()
            c = CombatSystem(st)
            for _ in range(4000):
                if c.phase in (Phase.VICTORY, Phase.DEFEAT):
                    break
                if c.phase is Phase.QTE:
                    c.update(60.0)
                elif c.phase in (Phase.RESOLVE, Phase.ENEMY):
                    c.update(0.5)
                else:
                    c.handle_key(rng.choice(["return", "down", "1", "2", "space"]))
            self.assertIn(c.phase, (Phase.VICTORY, Phase.DEFEAT), f"seed {seed}")


if __name__ == "__main__":
    unittest.main()
