"""Permanent Meta-Progression: RunCurrency, ClassUnlockTree, DailyTask system.

RunCurrency ("Choir Shards") is earned by:
  - Completing a run (victory or defeat after stage 2+)
  - Completing daily tasks
  - Defeating bosses

It survives death, defeat, new runs and mode changes. It is bound to the
player profile (stored in the settings/save directory alongside leaderboard.json)
and persists through save/load.

ClassUnlockTree: each of the 8 classes has 6 passive nodes (a tier chain) costing 5/10/20/30/45/60 shards.
  Tiers 1-3 are stat passives; tiers 4-6 (R2) are combat perks consumed by CombatSystem / FallenAngel.
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
from core.perks import PERK_DEFAULTS

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
    tier: int                      # 1..MAX_TIER
    cost: int                      # shard cost
    name: str
    description: str
    stat_key: str                  # which stat it modifies (or "passive")
    stat_delta: float              # amount added / multiplied


MAX_TIER: Final[int] = 6
NODE_COSTS: Final[tuple[int, ...]] = (5, 10, 20, 30, 45, 60)


# Define 6 tiers × 8 classes = 48 nodes
def _build_tree() -> dict[str, SkillNode]:
    specs: list[tuple[str, list[tuple[str, str, str, float]]]] = [
        ("WARRIOR", [
            ("Iron Resolve",    "Gain +10 max HP.",              "max_hp",       10.0),
            ("Keen Edge",       "+8% attack power.",             "atk_mult",      0.08),
            ("Momentum Master", "+1 Rage generated per strike.", "rage_regen",    1.0),
            ("Battle Cry",      "+6% damage dealt.",              "perk_dmg",      0.06),
            ("Bloodrush",       "Heal 4 HP on every kill.",       "perk_kill_heal",4.0),
            ("Unbroken",        "Once per battle, a lethal blow leaves you at 1 HP.", "perk_lastgasp", 1.0),
        ]),
        ("TANK", [
            ("Thick Plates",    "+12 max HP.",                   "max_hp",       12.0),
            ("Shield Mastery",  "+10% damage mitigation.",       "def_mult",      0.10),
            ("Vigilance",       "+5 Stamina per turn.",          "sta_regen",     5.0),
            ("Bulwark Drills", "Take 6% less damage.",           "perk_guard",    0.06),
            ("Spiked Aegis",    "Reflect 15% of damage taken.",   "perk_thorns",   0.15),
            ("Immovable",       "Once per battle, a lethal blow leaves you at 1 HP.", "perk_lastgasp", 1.0),
        ]),
        ("ROGUE", [
            ("Shadow Step",     "+8 max Stamina.",               "max_sta",       8.0),
            ("Lethal Precision","+10% crit chance.",             "crit_bonus",    0.10),
            ("Combo Mastery",   "+1 Combo point cap.",           "combo_cap",     1.0),
            ("Deep Cuts",      "+25% critical damage.",          "perk_crit_dmg", 0.25),
            ("Cutpurse",        "Heal 3 HP on every kill.",       "perk_kill_heal",3.0),
            ("Killer's Instinct","+10% damage dealt.",            "perk_dmg",      0.10),
        ]),
        ("WITCH", [
            ("Deep Wellspring", "+15 max Mana.",                 "max_mp",       15.0),
            ("Arcane Surge",    "+8% spell power.",              "spell_mult",    0.08),
            ("Ether Affinity",  "+3 MP regen per turn.",         "mp_regen",      3.0),
            ("Warded Heartbeat","Recover 3 HP at the start of your turn.", "perk_regen_hp", 3.0),
            ("Forbidden Index", "+6% damage dealt.",              "perk_dmg",      0.06),
            ("Event Horizon",   "+30% critical damage.",          "perk_crit_dmg", 0.30),
        ]),
        ("ANGEL", [
            ("Martyrs Endurance", "+12 max HP.",                 "max_hp",       12.0),
            ("Grace Touched",   "Regain +8 Lucidity after every battle.", "lucidity_recover", 8.0),
            ("Iron Will",       "Break attempts +8% chance.",    "break_bonus",   0.08),
            ("Practiced Hands","+1 mistake allowed in forgiving restraint trials.", "trial_slip", 1.0),
            ("Lucid Penance",   "Every passed restraint trial restores 8 Lucidity.", "trial_clarity", 8.0),
            ("Measured Release","Begin each battle with +1 break momentum.", "momentum_start", 1.0),
        ]),
        ("KITSUNE", [
            ("Spirit Affinity", "+10 max Spirit.",               "max_spirit",   10.0),
            ("Fox Fire Focus",  "+8% foxfire damage.",           "fox_mult",      0.08),
            ("Trickster Mark",  "Decoys last +1 extra turn.",    "decoy_extra",   1.0),
            ("Nine Tails' Grace","Take 5% less damage.",         "perk_guard",    0.05),
            ("Trickster's Purse","Heal 3 HP on every kill.",     "perk_kill_heal",3.0),
            ("Foxfire Crown",   "+8% damage dealt.",              "perk_dmg",      0.08),
        ]),
        ("VAMPIRE", [
            ("Dark Vitality",   "+10 max HP.",                   "max_hp",       10.0),
            ("Blood Thirst",    "+8% Blood generated per hit.",  "blood_mult",    0.08),
            ("Veil of Mist",    "Veil of Night lasts +1 turn.",  "veil_bonus",    1.0),
            ("Sanguine Pact",  "Heal 5 HP on every kill.",       "perk_kill_heal",5.0),
            ("Crimson Hunger",  "+6% damage dealt.",              "perk_dmg",      0.06),
            ("Undying Night",   "Once per battle, a lethal blow leaves you at 1 HP.", "perk_lastgasp", 1.0),
        ]),
        ("DRAGONKIN", [
            ("Furnace Heart",   "+10 max HP.",                   "max_hp",       10.0),
            ("Scale Temper",    "+8% physical mitigation.",      "def_mult",      0.08),
            ("Controlled Burn", "Overheat threshold +10.",       "heat_cap",     10.0),
            ("Scaled Hide",    "Take 6% less damage.",           "perk_guard",    0.06),
            ("Dragonfire Heart","Recover 3 HP at the start of your turn.", "perk_regen_hp", 3.0),
            ("Wyrm's Wrath",    "+30% critical damage.",          "perk_crit_dmg", 0.30),
        ]),
    ]
    COSTS = list(NODE_COSTS)
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
            )
    return nodes


SKILL_TREE: Final[dict[str, SkillNode]] = _build_tree()


def nodes_for_class(class_key: str) -> list[SkillNode]:
    """Return the skill nodes (tier 1..MAX_TIER) for the given class (by PlayerClass.name)."""
    key = class_key.upper()
    return sorted(
        [n for n in SKILL_TREE.values() if n.class_key == key],
        key=lambda n: n.tier,
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
        # Check tier prerequisite: tier 2 needs tier 1, tier 3 needs tier 2
        if node.tier > 1:
            prev_id = f"{node.class_key.lower()}_t{node.tier - 1}"
            if prev_id not in self.unlocked_nodes:
                prev = SKILL_TREE.get(prev_id)
                if prev:
                    return False, f"Unlock {prev.name} first (tier {node.tier - 1})."
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
        # Remove this node and higher tiers in the same class
        to_remove = {node_id}
        for tier in range(node.tier + 1, MAX_TIER + 1):
            dep = f"{node.class_key.lower()}_t{tier}"
            if dep in self.unlocked_nodes:
                to_remove.add(dep)
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
    for stat_key, delta in bonuses.items():
        if stat_key == "max_hp":
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
        elif stat_key in PERK_DEFAULTS:
            # R2 tier 4-6 perks: plain accumulating attributes read by CombatSystem / FallenAngel.
            base = getattr(player, stat_key, PERK_DEFAULTS[stat_key])
            add = int(delta) if isinstance(PERK_DEFAULTS[stat_key], int) else float(delta)
            setattr(player, stat_key, base + add)
