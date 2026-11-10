"""Defaults for every permanent-perk attribute a hero can carry (skill tree / profile bonuses).

Heroes are persisted attribute-by-attribute and ``_apply_attrs`` only restores attributes that already exist on a
freshly built hero. Declaring every perk up-front (instead of creating it lazily in ``apply_profile_bonuses``)
is what lets the bonuses survive a save/load round trip.
"""
from __future__ import annotations

from typing import Any, Final

PERK_DEFAULTS: Final[dict[str, Any]] = {
    # original tier 1-3 hooks
    "rage_bonus": 0, "sta_regen_bonus": 0, "crit_bonus": 0.0, "combo_max": 5, "spell_mult": 0.0,
    "mp_regen_bonus": 0, "spirit_bonus": 0, "fox_mult": 0.0, "decoy_extra": 0, "blood_mult": 0.0,
    "veil_bonus": 0, "heat_cap_bonus": 0, "_profile_break_bonus": 0.0,
    # R2 tier 4-6 hooks (consumed by CombatSystem / FallenAngel)
    "perk_dmg": 0.0,          # outgoing damage multiplier bonus (capped at +50%)
    "perk_guard": 0.0,        # incoming damage reduction (capped at 40%, never applies to true damage)
    "perk_crit_dmg": 0.0,     # extra critical-hit multiplier
    "perk_kill_heal": 0,      # HP restored when this hero lands a killing blow
    "perk_regen_hp": 0,       # HP restored at the start of this hero's turn
    "perk_thorns": 0.0,       # fraction of damage taken that is reflected at the attacker
    "perk_lastgasp": 0,       # lethal hits survived at 1 HP per battle
    "lastgasp_used": 0,       # charges spent this battle (reset after battle)
    "lucidity_recover": 0,    # Fallen Angel: extra Lucidity regained after each battle (Grace Touched)
    "trial_slip": 0,          # Fallen Angel: extra mistakes allowed on non-fatal restraint trials
    "trial_clarity": 0,       # Fallen Angel: Lucidity regained on every passed restraint trial
    "momentum_start": 0,      # Fallen Angel: break momentum carried into every battle
}
PERK_CAPS: Final[dict[str, float]] = {"perk_dmg": 0.50, "perk_guard": 0.40, "perk_thorns": 0.60}


def init_perks(hero: Any) -> None:
    """Give ``hero`` every perk attribute at its default (idempotent: never overwrites)."""
    for key, value in PERK_DEFAULTS.items():
        if key not in hero.__dict__:
            setattr(hero, key, value)
