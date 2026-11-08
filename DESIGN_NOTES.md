# DESIGN_NOTES — R2

## 1. Fallen Angel restraints
**Goal:** keep her a demanding, non-bypassable challenge class, but make every failure legible and recoverable, and make the challenge un-spammable.

- Six restraints (manacles, gag, sensory deprivation, sabatons, barbed wings, anchor) cascade as before. Breaking one runs a **trial** chosen by `TrialLibrary.pick` from the restraint's theme, the tier from `trial_tier(stage, restraints, tightness)`, and the combat RNG (reproducible per seed).
- **Tiers:** Initiate / Bound / Condemned / Judgment. A trial is only offered inside its allowed tier range; boss trials only for their boss.
- **Anti-spam rules** (enforced in `restraint_trials.py`, proven in tests): a minimum press interval, fatigue that rises under sustained fast input (rejected presses add to it), detection of machine-regular timing, and trial rules that need specific keys/timing so blind mashing or holding one key cannot clear them. A trial must be *read*, not mashed.
- **Consequences** always name their cause (which trial, which mistake) and give a path back: each failed trial also builds *break momentum* (+0.10 break chance per step, max 3, reset on a break or after battle), so the next attempt is easier and a streak of failures does not become a death spiral.
- Everything is fantasy-restraint mechanics (chains, seals, runes, curses). No sexual mechanics were added.

## 2. Skill trees and perks
Six nodes per class, 48 total, each with a runtime hook in `core/perks.py` (`PERK_DEFAULTS` pre-declares every perk attribute because the save system only restores attributes that exist on a fresh object). A node that cannot change behaviour is a bug; `test_skill_perks.py` checks each one.

## 3. Elements
Table-driven (`core/elements.py`). Heroes are mostly neutral with small signature affinities; enemies by archetype (beast weak to fire, undead to holy, cinder to frost…). Bosses keep half of their archetype's swing so no element trivialises them. A weakness hit always applies its status; neutral hits 30%; resisted hits never. Statuses are small and readable: Burn (DoT), Chill (-20% attack), Shock (next hit +25%), Suppressed (-35% attack, 1 turn), Mark (cards cash it in).

## 4. Card system — assessment of the hybrid prototype
**What it is:** an optional layer. Each hero has a deck (starter by class, 6–30 cards). Each turn the hero may play an ability *or* open "Cards" and play one card from a hand of up to 5 (opening 4, +1 per turn). Piles reshuffle; exhaust removes a card for the fight. Draft after each victory.
**Design choices**
- Cards sit *beside* abilities, never replacing them, so V2's class identity and tests are intact.
- Tags create combos without text bloat: SETUP (Mark/Burn/Shock) → STRIKE/DETONATE payoffs; WARD and SHIFT defend; SILENCE makes a foe lose its next action. Angel cards scale with restraints and spend Lucidity or HP.
- **Dead-hand prevention:** if nothing in hand is playable, the hand is redrawn (`ensure_playable`), plus a free fallback card (Catch Breath).
- RNG is seeded from run seed, stage, party slot and class — never from process-global uids — so draws reproduce.
- Enemy intent stays visible (unless Sensory Deprivation hides it — the restraint's cost).
**Honest assessment:** it works as a prototype and tests cover the rules, but it is *not* tuned or play-tested by a human. In the simulator, card-play initially lagged abilities badly; card damage was raised ~30%. Open questions: is a free-action fallback needed at higher depth, are drafts too generous (three options, +12 gold to skip), and is the hand best shown as drawn cards rather than menu rows (current UI is menu rows).
**Recommendation:** keep it as an opt-in layer until a human playtest says which classes want it; the card art frames exist (`Assets/Art/cards`) but are only used on the draft screen.

## 5. Visual direction
The user's direction: cute, adult, anime-styled heroines in the manner of Nikke / Azur Lane. Standees and portraits are cut from the supplied concept boards (GrabCut, `tools/extract_art.py`, records in `Assets/Art/ART_SOURCES.json`). Bosses use feathered concept-art portraits. Regular enemies remain procedural silhouettes because the boards contain none. The supplied R2 Fallen Angel frame sheets show the older low-poly chibi body, which clashes with the new art, so they are kept as reference only and the restraint effects use the chain-ring art instead.

## 6. Out of scope / not done
Added late: the optional Shrine (`systems/shrine.py`) as the risk/reward encounter; its payouts are untuned guesses. Branching rewards, room modifiers beyond V2's omens, formations and companion boons were not added. Real-Pygame verification is the largest gap (see `TEST_REPORT.md`).
