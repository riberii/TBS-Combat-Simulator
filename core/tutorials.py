"""Tutorials & Codex: tactical training guides and class-specific combat manuals."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core.config import PlayerClass


@dataclass(frozen=True)
class TutorialLesson:
    id: str
    title: str
    topic: str
    summary: str
    tips: tuple[str, ...]


GENERAL_TUTORIALS: Final[list[TutorialLesson]] = [
    TutorialLesson(
        "basics",
        "Combat Fundamentals",
        "Turn Order & Flow",
        "Combat proceeds in turn order determined by entity speed. Each round, you issue commands to active party members.",
        (
            "Enemies telegraph their upcoming actions with an Intent icon and label above their health bar.",
            "Crushing Blows and Flurries can be mitigated with Guard or crowd-control abilities.",
            "Devastating attacks are preceded by 'Gathering Power'. Break them or prepare heavy defensive buffs.",
            "Items in the party satchel can be consumed during a hero's turn without spending their turn action.",
        ),
    ),
    TutorialLesson(
        "qte",
        "Quick-Time Precision",
        "Timing & Memory QTEs",
        "Many abilities trigger a timing or sequence challenge. Success boosts damage, applies extra status effects, or refunds resources.",
        (
            "Timing QTE: Press Enter or Space when the indicator aligns with the target marker.",
            "Memory / Sequence QTE: Memorize the rune pattern and press the matching letters in order.",
            "Failing a QTE does not cancel the attack, but delivers a diminished strike.",
            "Certain debilitating enemy restraints (such as an Iron Gag) add QTE checks to standard item usage.",
        ),
    ),
    TutorialLesson(
        "restraints",
        "The Prime Evil's Chains",
        "Restraints & Lucidity",
        "The Fallen Angel starts bound in ritual chains. Every turn, active restraints reduce output and drain Lucidity.",
        (
            "Use 'Break Restraint' or struggle against specific chains on your turn to break free.",
            "Bolt Cutters from the merchant immediately sever one restraint without costing a struggle turn.",
            "At 0 Lucidity, the Angel falls into Bloodlust, attacking recklessly until soothed.",
            "Below 30% HP, Martyrdom activates, doubling all offensive output.",
        ),
    ),
]

CLASS_TUTORIALS: Final[dict[PlayerClass, TutorialLesson]] = {
    PlayerClass.WARRIOR: TutorialLesson(
        "warrior",
        "The Vanguard Warrior",
        "Momentum & Bleed",
        "Frontline brawler who builds Rage with every strike and fuels brutal execution finishers.",
        (
            "Slash applies Bleed, dealing damage over time every turn.",
            "Heavy Blow delivers crushing single-target impact to exposed targets.",
            "Battle Cry taunts foes away from fragile allies while granting team empowerment.",
            "Whirlwind strikes the entire enemy line with clean timing QTEs.",
        ),
    ),
    PlayerClass.TANK: TutorialLesson(
        "tank",
        "The Iron Bulwark",
        "Mitigation & Threat",
        "Impenetrable wall that draws enemy threat and absorbs devastating attacks with stamina-fueled shields.",
        (
            "Shield Slam interrupts charging enemies and stuns the target.",
            "Iron Wall triples defense for a turn, rendering crushing blows harmless.",
            "Taunt redirects dangerous single-target intents directly to your armored plate.",
            "Hold stamina in reserve to ensure defensive stances are never starved.",
        ),
    ),
    PlayerClass.ROGUE: TutorialLesson(
        "rogue",
        "The Shadow Rogue",
        "Combo & Critical Punish",
        "Agile assassin who exploits status ailments, blinds foes with smoke, and scores lethal critical strikes.",
        (
            "Quick Strike builds Combo points at low stamina cost.",
            "Smoke Bomb blinds enemy ranks, causing their upcoming intents to fizzle.",
            "Eviscerate consumes stored combo points for massive critical multipliers.",
            "Positioning and timing turn enemy aggression into counter-strikes.",
        ),
    ),
    PlayerClass.WITCH: TutorialLesson(
        "witch",
        "The Pyre Witch",
        "Ether & Elemental Overcast",
        "Glass-cannon spellcaster who incinerates enemies with burn stacks and explosive arcane overcasts.",
        (
            "Fireball inflicts burning status that ticks each turn.",
            "Ether Surge restores MP to allies at the cost of slight self-strain.",
            "Overcast channels health directly into raw spell power when mana is low.",
            "Chain Lightning shocks multiple targets, exposing them to subsequent physical strikes.",
        ),
    ),
    PlayerClass.ANGEL: TutorialLesson(
        "angel",
        "The Fallen Angel",
        "Shattered Shackles & Bloodlust",
        "Cast out of the choir; bound in six chains. High risk, unmatched damage ceiling under martyrdom.",
        (
            "Prioritize breaking the Sabatons (speed) and Manacles (attack) first.",
            "Keep Lucidity Draughts ready to prevent untimely Bloodlust during boss telegraphs.",
            "Under 30% HP, Martyrdom doubles your damage—balance health near the edge.",
            "Writhe builds momentum even while bound.",
        ),
    ),
    PlayerClass.KITSUNE: TutorialLesson(
        "kitsune",
        "The Fox-Spirit Tactician",
        "Spirit & Paper Moon Decoys",
        "Illusionist who misdirects enemy attacks with decoys and awakens ninefold celestial fire.",
        (
            "Foxfire Thread builds Spirit cleanly on successful timing QTEs.",
            "Paper Moon Double places a decoy that completely negates the next single-target enemy strike.",
            "Ninefold Step prepares guaranteed evasion charges.",
            "Spend 65 Spirit on Nine-Tail Ascendance for a 3-turn surge of enhanced power.",
        ),
    ),
    PlayerClass.VAMPIRE: TutorialLesson(
        "vampire",
        "The Night Duelist",
        "Blood Gauge & Bounded Sustain",
        "Aristocratic night-stalker whose blood pool fuels devastating lunges and protective mist.",
        (
            "Striking and taking damage builds Blood.",
            "Sanguine Lunge converts damage dealt into up to 24 HP of restored health.",
            "Veil of Night grants a one-turn protective ward and drops enemy threat.",
            "Eclipse Feast finishes low-health targets (below 35% HP) with massive damage.",
        ),
    ),
    PlayerClass.DRAGONKIN: TutorialLesson(
        "dragonkin",
        "The Furnace Dragonkin",
        "Heat Gauge & Overheat Balance",
        "Draconic bruiser whose scales grow hotter as battles drag on, unleashing searing breath at high heat.",
        (
            "Taking and dealing damage generates Heat in your internal furnace.",
            "Scale Guard triples defense and channels incoming kinetic force into heat.",
            "Ember Breath sweeps the entire enemy wave with burning embers.",
            "Warning: Hitting 100 Heat triggers Overheat, venting the furnace and leaving you Exposed!",
        ),
    ),
}
