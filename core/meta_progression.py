"""Permanent Meta-Progression: RunCurrency, ClassUnlockTree, DailyTask system.

RunCurrency ("Choir Shards") is earned by:
  - Completing a run (victory or defeat after stage 2+)
  - Completing daily tasks
  - Defeating bosses

It survives death, defeat, new runs and mode changes. It is bound to the
player profile (stored in the settings/save directory alongside leaderboard.json)
and persists through save/load.

ClassUnlockTree: each of the 8 classes has 3 passive nodes costing 5/10/20 shards.
  Nodes are permanent across all runs.

DailyTask: one deterministic date-seeded objective per calendar day.
  Completion grants 15 shards and is marked done for that date.
  Rewards cannot be claimed twice for the same date.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final, Optional

from core.config import PlayerClass

# ---------------------------------------------------------------------------
# Currency constants
# ---------------------------------------------------------------------------
SHARD_CURRENCY_NAME: Final[str] = "Choir Shards"
SHARD_ICON: Final[str] = "◈"  # used in UI display

# Shard rewards (base amounts; run quality multiplies run_reward)
SHARD_RUN_VICTORY: Final[int] = 20
SHARD_RUN_DEFEAT: Final[int] = 8          # partial, at stage >= 2
SHARD_BOSS_KILLED: Final[int] = 12
SHARD_DAILY_COMPLETE: Final[int] = 15


# ---------------------------------------------------------------------------
# Class Skill Tree
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SkillNode:
    node_id: str
    class_key: str                 # PlayerClass.name
    tier: int                      # 1-3 core path, 2 = branch nodes, 4 = capstone
    cost: int                      # shard cost
    name: str
    description: str
    stat_key: str                  # which stat it modifies (or "passive"); "perk_*" = runtime perk (see PERK_HELP)
    stat_delta: float              # amount added / multiplied
    branch: str = "core"           # core | specialisation | utility | capstone
    requires: tuple[str, ...] = () # node ids that must all be unlocked first
    tradeoff: str = ""             # explicit downside text (capstones)
    extra: tuple[tuple[str, float], ...] = ()   # additional (stat_key, delta) effects, e.g. a tradeoff


# Runtime perks (R2). Stored in Player.perks and consumed by CombatSystem / FallenAngel.
PERK_HELP: Final[dict[str, str]] = {
    "execute": "damage vs foes under 40% HP", "opener": "damage on your first strike each battle",
    "crit_dmg": "extra critical-hit multiplier", "lifesteal": "of damage dealt returned as HP",
    "regen": "of max HP healed at the start of your turn", "reduce": "flat damage removed from each hit",
    "laststand": "damage reduction while below 35% HP", "thorns": "damage reflected to each attacker",
    "evade": "chance to completely avoid an enemy hit", "taken": "extra damage taken (tradeoff)",
    "dealt": "damage dealt", "wounded_dealt": "damage dealt while below 50% HP",
    "trial_time": "more time in restraint trials", "break_soft": "softer Break backlash and later Correction lock",
    "release": "strikes after a clean break ignore restraint penalties", "release_cost": "Lucidity lost when the release triggers",
}


# (name, description, stat_key, delta, tradeoff text, extra effects)
_BRANCH_SPECS: Final[dict[str, tuple]] = {
    "WARRIOR": (
        ("Executioner's Eye", "+30% damage against foes under 40% HP.", "perk_execute", 0.30, "", ()),
        ("Second Wind", "Heal 4% max HP at the start of each of your turns.", "perk_regen", 0.04, "", ()),
        ("Blood Oath", "+20% damage dealt.", "perk_dealt", 0.20, "You take 10% more damage.", (("perk_taken", 0.10),)),
    ),
    "TANK": (
        ("Retaliation", "Reflect 6 damage to every enemy that hits you.", "perk_thorns", 6.0, "", ()),
        ("Plate Discipline", "Every hit against you is reduced by 3 (minimum 1).", "perk_reduce", 3.0, "", ()),
        ("Immovable Object", "Take 40% less damage while below 35% HP.", "perk_laststand", 0.40,
         "You deal 10% less damage.", (("perk_dealt", -0.10),)),
    ),
    "ROGUE": (
        ("Opening Gambit", "+60% damage on your first strike each battle.", "perk_opener", 0.60, "", ()),
        ("Slippery", "10% chance to completely avoid an enemy hit.", "perk_evade", 0.10, "", ()),
        ("Assassin's Edge", "Critical hits deal +0.5x more damage.", "perk_crit_dmg", 0.50,
         "You take 15% more damage.", (("perk_taken", 0.15),)),
    ),
    "WITCH": (
        ("Hex Siphon", "Heal for 10% of the damage you deal.", "perk_lifesteal", 0.10, "", ()),
        ("Spellward", "Take 25% less damage while below 35% HP.", "perk_laststand", 0.25, "", ()),
        ("Archmage's Gamble", "+25% damage against foes under 40% HP.", "perk_execute", 0.25,
         "You take 20% more damage.", (("perk_taken", 0.20),)),
    ),
    "ANGEL": (
        ("Penitent Focus", "Restraint trials give you 25% more time.", "perk_trial_time", 0.25, "", ()),
        ("Lucid Ledger", "Failed Breaks cost 3 less HP and 5 less Lucidity, and the Choir of Correction waits for a third failure.",
         "perk_break_soft", 1.0, "", ()),
        ("Brief Release", "After a successful Break your next strike ignores restraint penalties.", "perk_release", 1.0,
         "The release costs 8 Lucidity.", (("perk_release_cost", 8.0),)),
    ),
    "KITSUNE": (
        ("Foxfire Siphon", "Heal for 8% of the damage you deal.", "perk_lifesteal", 0.08, "", ()),
        ("Mirror Mist", "10% chance to completely avoid an enemy hit.", "perk_evade", 0.10, "", ()),
        ("Nine-Tailed Pact", "+40% opening-strike damage and 8% evasion.", "perk_opener", 0.40,
         "You take 10% more damage.", (("perk_evade", 0.08), ("perk_taken", 0.10))),
    ),
    "VAMPIRE": (
        ("Sanguine Feast", "Heal for 12% of the damage you deal.", "perk_lifesteal", 0.12, "", ()),
        ("Mist Cloak", "10% chance to completely avoid an enemy hit.", "perk_evade", 0.10, "", ()),
        ("Crimson Sovereign", "+30% damage while below 50% HP, and +6% lifesteal.", "perk_wounded_dealt", 0.30,
         "You take 10% more damage.", (("perk_lifesteal", 0.06), ("perk_taken", 0.10))),
    ),
    "DRAGONKIN": (
        ("Scale Barbs", "Reflect 5 damage to every enemy that hits you.", "perk_thorns", 5.0, "", ()),
        ("Ember Mending", "Heal 3% max HP at the start of each of your turns.", "perk_regen", 0.03, "", ()),
        ("Dragon's Wrath", "+35% damage while below 50% HP.", "perk_wounded_dealt", 0.35,
         "You take 10% more damage.", (("perk_taken", 0.10),)),
    ),
}


# Define 3 tiers × 8 classes = 24 nodes
def _build_tree() -> dict[str, SkillNode]:
    specs: list[tuple[str, list[tuple[str, str, str, float]]]] = [
        ("WARRIOR", [
            ("Iron Resolve",    "Gain +10 max HP.",              "max_hp",       10.0),
            ("Keen Edge",       "+8% attack power.",             "atk_mult",      0.08),
            ("Momentum Master", "+1 Rage generated per strike.", "rage_regen",    1.0),
        ]),
        ("TANK", [
            ("Thick Plates",    "+12 max HP.",                   "max_hp",       12.0),
            ("Shield Mastery",  "+10% damage mitigation.",       "def_mult",      0.10),
            ("Vigilance",       "+5 Stamina per turn.",          "sta_regen",     5.0),
        ]),
        ("ROGUE", [
            ("Shadow Step",     "+8 max Stamina.",               "max_sta",       8.0),
            ("Lethal Precision","+10% crit chance.",             "crit_bonus",    0.10),
            ("Combo Mastery",   "+1 Combo point cap.",           "combo_cap",     1.0),
        ]),
        ("WITCH", [
            ("Deep Wellspring", "+15 max Mana.",                 "max_mp",       15.0),
            ("Arcane Surge",    "+8% spell power.",              "spell_mult",    0.08),
            ("Ether Affinity",  "+3 MP regen per turn.",         "mp_regen",      3.0),
        ]),
        ("ANGEL", [
            ("Martyrs Endurance", "+12 max HP.",                 "max_hp",       12.0),
            ("Grace Touched",   "+8 Lucidity start.",            "lucidity_start",8.0),
            ("Iron Will",       "Break attempts +8% chance.",    "break_bonus",   0.08),
        ]),
        ("KITSUNE", [
            ("Spirit Affinity", "+10 max Spirit.",               "max_spirit",   10.0),
            ("Fox Fire Focus",  "+8% foxfire damage.",           "fox_mult",      0.08),
            ("Trickster Mark",  "Decoys last +1 extra turn.",    "decoy_extra",   1.0),
        ]),
        ("VAMPIRE", [
            ("Dark Vitality",   "+10 max HP.",                   "max_hp",       10.0),
            ("Blood Thirst",    "+8% Blood generated per hit.",  "blood_mult",    0.08),
            ("Veil of Mist",    "Veil of Night absorbs +5 HP.",  "veil_bonus",    5.0),
        ]),
        ("DRAGONKIN", [
            ("Furnace Heart",   "+10 max HP.",                   "max_hp",       10.0),
            ("Scale Temper",    "+8% physical mitigation.",      "def_mult",      0.08),
            ("Controlled Burn", "Overheat threshold +10.",       "heat_cap",     10.0),
        ]),
    ]
    COSTS = [5, 10, 20]
    nodes: dict[str, SkillNode] = {}
    for class_name, node_list in specs:
        for tier, (name, desc, stat_key, delta) in enumerate(node_list, 1):
            node_id = f"{class_name.lower()}_t{tier}"
            nodes[node_id] = SkillNode(
                node_id=node_id,
                class_key=class_name,
                tier=tier,
                cost=COSTS[tier - 1],
                name=name,
                description=desc,
                stat_key=stat_key,
                stat_delta=delta,
                branch="core",
                requires=(f"{class_name.lower()}_t{tier - 1}",) if tier > 1 else (),
            )
    # ---- R2 branch nodes: t4 specialisation, t5 utility, t6 capstone (requires the whole core path + both branches)
    for class_name, (spec, util, cap) in _BRANCH_SPECS.items():
        base = class_name.lower()
        for n, (branch, tier, cost, req, data) in enumerate((
                ("specialisation", 2, 12, (f"{base}_t1",), spec),
                ("utility", 2, 12, (f"{base}_t1",), util),
                ("capstone", 4, 30, (f"{base}_t3", f"{base}_t4", f"{base}_t5"), cap)), 4):
            name, desc, stat_key, delta, tradeoff, extra = data
            nodes[f"{base}_t{n}"] = SkillNode(f"{base}_t{n}", class_name, tier, cost, name, desc, stat_key, delta,
                                              branch, req, tradeoff, tuple(extra))
    return nodes


SKILL_TREE: Final[dict[str, SkillNode]] = _build_tree()


def nodes_for_class(class_key: str) -> list[SkillNode]:
    """Return the skill nodes (t1..t6) for the given class (by PlayerClass.name), in id order."""
    key = class_key.upper()
    return sorted(
        [n for n in SKILL_TREE.values() if n.class_key == key],
        key=lambda n: int(n.node_id.rsplit("_t", 1)[1]),
    )


# ---------------------------------------------------------------------------
# Daily Task
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DailyTask:
    date_str: str          # YYYY-MM-DD
    seed: int              # deterministic int seed
    objective: str         # human-readable task
    mode: str              # run mode the task applies to
    target_value: int      # e.g. stages to reach, bosses to kill
    reward_shards: int


_TASK_TEMPLATES = [
    ("Reach stage {v} in {mode} — the deeper the descent, the louder the Choir sings.", "story",   [3, 5, 6]),
    ("Survive {v} stages in {mode} without healing at the merchant.",                  "endless",  [3, 4, 5]),
    ("Defeat {v} elite or boss encounters in {mode}.",                                 "endless",  [2, 3, 4]),
    ("Defeat a boss in {mode} without any hero falling below 30 HP.",                  "boss_rush",[1, 1, 1]),
    ("Complete {v} Colosseum rounds without the party dying.",                          "arena",    [2, 3, 4]),
]


def get_daily_task(today: Optional[date] = None) -> DailyTask:
    """Generate a deterministic daily task for the given date (default: today)."""
    if today is None:
        today = date.today()
    date_str = today.isoformat()
    # Derive a deterministic seed from the date
    seed = int(hashlib.sha256(date_str.encode()).hexdigest(), 16) % (2 ** 31)
    rng_idx = seed % len(_TASK_TEMPLATES)
    template, mode, targets = _TASK_TEMPLATES[rng_idx]
    target_val = targets[seed % len(targets)]
    mode_labels = {"story": "Story Campaign", "endless": "Endless Rift",
                   "boss_rush": "Boss Rush", "arena": "Colosseum Arena"}
    obj = template.format(v=target_val, mode=mode_labels.get(mode, mode))
    return DailyTask(
        date_str=date_str,
        seed=seed,
        objective=obj,
        mode=mode,
        target_value=target_val,
        reward_shards=SHARD_DAILY_COMPLETE,
    )


def check_daily_task_complete(task: DailyTask, state: Any, won: bool = False) -> bool:
    """Evaluate whether the given daily task was genuinely completed in the given state."""
    mode = getattr(state, "run_mode", "endless")
    if mode != task.mode and mode != "daily":
        return False
    stage = getattr(state, "stage", 0)
    bosses = getattr(state, "bosses_defeated", 0)
    elites = getattr(state, "elites_slain", 0)
    heals = getattr(state, "merchant_heals_used", 0)
    lowest_hp = getattr(state, "lowest_hero_hp", 999)
    deaths = getattr(state, "party_deaths", 0)

    # 1. Reach stage
    if "Reach stage" in task.objective:
        return stage >= task.target_value
    # 2. Without healing at the merchant
    elif "without healing at the merchant" in task.objective:
        return stage >= task.target_value and heals == 0
    # 3. Defeat elite or boss encounters
    elif "elite or boss encounters" in task.objective:
        return (elites + bosses) >= task.target_value
    # 4. Defeat a boss without any hero falling below 30 HP
    elif "without any hero falling below" in task.objective:
        return bosses >= 1 and lowest_hp >= 30
    # 5. Complete Colosseum rounds without the party dying
    elif "without the party dying" in task.objective:
        return stage >= task.target_value and deaths == 0
    else:
        return stage >= task.target_value


# ---------------------------------------------------------------------------
# Player Profile (persistent, stored alongside leaderboard)
# ---------------------------------------------------------------------------
_PROFILE_SCHEMA_VERSION = 1


@dataclass
class PlayerProfile:
    shards: int = 0
    unlocked_nodes: set[str] = field(default_factory=set)
    completed_daily: dict[str, bool] = field(default_factory=dict)  # date_str -> True
    lifetime_victories: int = 0
    lifetime_bosses: int = 0

    # ---- shard economy ------------------------------------------------
    def add_shards(self, amount: int, reason: str = "") -> None:
        self.shards = max(0, self.shards + amount)

    def can_afford(self, cost: int) -> bool:
        return self.shards >= cost

    def purchase_node(self, node_id: str) -> tuple[bool, str]:
        """Attempt to purchase a skill node. Returns (success, message)."""
        if node_id not in SKILL_TREE:
            return False, f"Unknown node: {node_id}"
        node = SKILL_TREE[node_id]
        if node_id in self.unlocked_nodes:
            return False, f"{node.name} is already unlocked."
        for req_id in node.requires:
            if req_id not in self.unlocked_nodes:
                req = SKILL_TREE.get(req_id)
                if req:
                    return False, f"Unlock {req.name} first (tier {req.tier})."
        if not self.can_afford(node.cost):
            return False, f"Need {node.cost} {SHARD_ICON} (have {self.shards})."
        self.shards -= node.cost
        self.unlocked_nodes.add(node_id)
        return True, f"{node.name} unlocked! (-{node.cost} {SHARD_ICON})"

    def refund_node(self, node_id: str) -> tuple[bool, str]:
        """Refund a node (50% back, removing it and any higher-tier dependents)."""
        if node_id not in SKILL_TREE:
            return False, f"Unknown node: {node_id}"
        node = SKILL_TREE[node_id]
        if node_id not in self.unlocked_nodes:
            return False, f"{node.name} is not unlocked."
        # Remove this node and everything that (transitively) depends on it
        to_remove = {node_id}
        changed = True
        while changed:
            changed = False
            for nid in list(self.unlocked_nodes):
                if nid not in to_remove and nid in SKILL_TREE and any(r in to_remove for r in SKILL_TREE[nid].requires):
                    to_remove.add(nid)
                    changed = True
        refund_total = 0
        for nid in to_remove:
            n = SKILL_TREE[nid]
            refund_total += n.cost // 2
            self.unlocked_nodes.discard(nid)
        self.shards += refund_total
        return True, f"Refunded {len(to_remove)} node(s) for {refund_total} {SHARD_ICON}."

    def claim_daily(self, task: DailyTask) -> tuple[bool, str]:
        """Mark daily task complete and award shards. Idempotent."""
        if self.completed_daily.get(task.date_str):
            return False, "Today's task was already completed."
        self.completed_daily[task.date_str] = True
        self.shards += task.reward_shards
        return True, f"Daily task complete! +{task.reward_shards} {SHARD_ICON}"

    def is_daily_done(self, task: DailyTask) -> bool:
        return bool(self.completed_daily.get(task.date_str))

    def get_unlocked_bonuses(self, class_key: str) -> dict[str, float]:
        """Return cumulative stat deltas for a given class from unlocked nodes."""
        bonuses: dict[str, float] = {}
        for node in nodes_for_class(class_key):
            if node.node_id in self.unlocked_nodes:
                bonuses[node.stat_key] = bonuses.get(node.stat_key, 0.0) + node.stat_delta
                for key, delta in node.extra:
                    bonuses[key] = bonuses.get(key, 0.0) + delta
        return bonuses

    # ---- persistence ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _PROFILE_SCHEMA_VERSION,
            "shards": self.shards,
            "unlocked_nodes": sorted(self.unlocked_nodes),
            "completed_daily": self.completed_daily,
            "lifetime_victories": self.lifetime_victories,
            "lifetime_bosses": self.lifetime_bosses,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlayerProfile":
        p = cls()
        p.shards = int(data.get("shards", 0))
        p.unlocked_nodes = set(data.get("unlocked_nodes", []))
        p.completed_daily = {str(k): bool(v) for k, v in data.get("completed_daily", {}).items()}
        p.lifetime_victories = int(data.get("lifetime_victories", 0))
        p.lifetime_bosses = int(data.get("lifetime_bosses", 0))
        return p


class ProfileStore:
    """Persistent player profile saved to disk (alongside leaderboard)."""

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path

    def load(self) -> PlayerProfile:
        if not self._path.exists():
            return PlayerProfile()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return PlayerProfile()
            return PlayerProfile.from_dict(data)
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
            # Back up the corrupt file before discarding it
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                bak = self._path.with_suffix(f".corrupt.{ts}.bak")
                shutil.copy2(self._path, bak)
                warnings.warn(
                    f"Profile at {self._path} was corrupt ({exc!r}); "
                    f"backed up to {bak} and starting fresh.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            except OSError:
                pass
            return PlayerProfile()

    def save(self, profile: PlayerProfile) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self._path)


# ---------------------------------------------------------------------------
# Run reward calculator (called at _finish)
# ---------------------------------------------------------------------------
def calculate_run_shards(won: bool, stage: int, bosses_defeated: int) -> int:
    """Compute shards awarded at the end of a run. Returns 0 for trivially short runs."""
    if stage < 2:
        return 0
    base = SHARD_RUN_VICTORY if won else SHARD_RUN_DEFEAT
    boss_bonus = bosses_defeated * SHARD_BOSS_KILLED
    # Slight quality bonus for deeper runs (capped at 3×)
    depth_mult = min(3.0, 1.0 + (stage - 2) * 0.15)
    return max(0, int((base + boss_bonus) * depth_mult))


# ---------------------------------------------------------------------------
# Apply profile bonuses to a freshly created Player at run start
# ---------------------------------------------------------------------------
def apply_profile_bonuses(player: Any, profile: PlayerProfile) -> None:
    """Modify a Player's base stats using unlocked skill-tree nodes.

    Called after GameState.new_run() creates players, before the first encounter.
    Handles missing attributes gracefully so it cannot crash the game.
    """
    class_key = getattr(getattr(player, "pclass", None), "name", "")
    if not class_key:
        return
    bonuses = profile.get_unlocked_bonuses(class_key)
    if hasattr(player, "perks"):
        player.perks = {}                      # perks are recomputed from the profile, never stacked
    for stat_key, delta in bonuses.items():
        if stat_key.startswith("perk_"):
            perks = getattr(player, "perks", None)
            if isinstance(perks, dict):
                perks[stat_key[5:]] = perks.get(stat_key[5:], 0.0) + delta
        elif stat_key == "max_hp":
            player.max_hp = getattr(player, "max_hp", 100) + int(delta)
            player.hp = min(player.hp + int(delta), player.max_hp) if hasattr(player, "hp") else player.max_hp
        elif stat_key == "max_mp":
            player.max_mana = getattr(player, "max_mana", 50) + int(delta)
        elif stat_key == "max_sta":
            player.max_stamina = getattr(player, "max_stamina", 60) + int(delta)
        elif stat_key == "atk_mult":
            if hasattr(player, "base_attack"):
                player.base_attack = max(1, int(player.base_attack * (1.0 + delta)))
            elif hasattr(player, "atk"):
                player.atk = max(1, int(player.atk * (1.0 + delta)))
        elif stat_key == "def_mult":
            if hasattr(player, "base_defense"):
                player.base_defense = max(0, int(player.base_defense * (1.0 + delta) + delta * 5))
            elif hasattr(player, "defense"):
                player.defense = max(0, int(player.defense * (1.0 + delta) + delta * 5))
        elif stat_key == "break_bonus":
            # Applied at runtime via FallenAngel.break_chance
            if hasattr(player, "_profile_break_bonus"):
                player._profile_break_bonus = getattr(player, "_profile_break_bonus", 0.0) + delta
            else:
                try:
                    player._profile_break_bonus = delta
                except AttributeError:
                    pass
        elif stat_key == "lucidity_start":
            if hasattr(player, "lucidity"):
                player.lucidity = min(100.0, getattr(player, "lucidity", 100.0) + delta)
        elif stat_key == "rage_regen":
            player.rage_bonus = getattr(player, "rage_bonus", 0) + int(delta)
        elif stat_key == "sta_regen":
            player.sta_regen_bonus = getattr(player, "sta_regen_bonus", 0) + int(delta)
        elif stat_key == "crit_bonus":
            player.crit_bonus = getattr(player, "crit_bonus", 0.0) + delta
        elif stat_key == "combo_cap":
            player.combo_max = getattr(player, "combo_max", 5) + int(delta)
        elif stat_key == "spell_mult":
            player.spell_mult = getattr(player, "spell_mult", 0.0) + delta
        elif stat_key == "mp_regen":
            player.mp_regen_bonus = getattr(player, "mp_regen_bonus", 0) + int(delta)
        elif stat_key == "max_spirit":
            player.spirit_bonus = getattr(player, "spirit_bonus", 0) + int(delta)
        elif stat_key == "fox_mult":
            player.fox_mult = getattr(player, "fox_mult", 0.0) + delta
        elif stat_key == "decoy_extra":
            player.decoy_extra = getattr(player, "decoy_extra", 0) + int(delta)
        elif stat_key == "blood_mult":
            player.blood_mult = getattr(player, "blood_mult", 0.0) + delta
        elif stat_key == "veil_bonus":
            player.veil_bonus = getattr(player, "veil_bonus", 0) + int(delta)
        elif stat_key == "heat_cap":
            player.heat_cap_bonus = getattr(player, "heat_cap_bonus", 0) + int(delta)
