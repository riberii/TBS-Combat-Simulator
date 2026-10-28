# Game Design — V2.0 Implemented Scope

## Engine decision

Remain on Python 3.10+ and pygame-ce. The repository already has one application loop (`main.py`), modular simulation/entities/persistence, an extensive headless test harness, custom procedural vector art, and generated procedural audio. Switching to Godot/Arcade would risk discarding working saves and combat without a demonstrated payoff. pygame-ce is the single runtime; it is not a launcher for another engine.

## Loop and state ownership

`GameApp` owns presentation/navigation. `GameState` is authoritative for party, enemies, stage, RNG, run mode, gold, rewards, and saved log. `CombatSystem` owns the phase machine, target/action validation, turn order, enemy intent, QTE, action resolution, death/victory detection and structured combat events. `Renderer`, `VFX`, and audio consume presentation cues; they do not decide damage. `SaveManager` serializes state to versioned JSON. The UI supports one person commanding 1–3 heroes.

```text
TITLE → MODE_SELECT → PARTY_SETUP → DIFFICULTY → COMBAT
                                                  ├─ victory → REWARDS → HUB → SHOP/next fight
                                                  ├─ defeat  → RESULTS
                                                  └─ final Story victory → RESULTS + epilogue
TITLE ← RESULTS / pause menu / ESC navigation
```

## Combat math and timing

For a normal strike, `raw = max(0, attacker.attack_power × multiplier)`. Critical damage multiplies raw by 1.8 before defense. Non-true damage is mitigated as `raw × DEF_K / (DEF_K + defense_power)`, where `DEF_K = 30`; final hit damage is integer-clamped by the entity pipeline. `Exposed` doubles incoming damage. Each combat action is resolved by the simulation and emits damage/heal/critical/death/log/alert/animation events for presentation. No blocking sleeps are used for attack feedback.

Enemy intents are explicit kinds: normal attack, crushing blow, flurry, charge, curse, dazed, brace, rally, and devastation. Enemies select from role-specific weights; bosses use profile cycles, telegraph charge before devastation, and switch into an enrage pattern at low HP. A per-hit ceiling protects against sudden enemy one-shots. Endless mode seeds generation from run RNG, caps enemy stat scaling at stage 999 and threat multiplier at 6×, while the visible stage counter can continue; encounter modifiers after the first campaign arc are bounded.

## Classes

| Class | Resource loop | Main tactical choice |
|---|---|---|
| Warrior | Rage (earned through attack/taking hits; decays while idle) | Build enough momentum for Executioner's Verdict or area sweep. |
| Tank | Bastion (guard/interception/hits) | Spend protection turns now or preserve stacks for a harder Shield Bash. |
| Rogue | Combo + Shadowed opener | Set up an opening, avoid damage that breaks tempo, then cash out. |
| Witch | Mana, cooldowns, Barrier | Control multiple enemies or save resources for a vulnerable target. |
| Fallen Angel | Lucidity, restraints, Bloodlust, tightness | Spend an action breaking a chain versus attacking under compounding penalties. |
| Kitsune | Spirit, decoy/evasion charges, temporary Ascendance | Trade Spirit for a guaranteed sidestep, misdirection, or a short empowered window. |
| Vampire | Blood (deal/take hits; cap 100) | Spend Blood on protection/team tempo or a capped heal/finisher; sustain is not infinite. |
| Dragonkin | Heat (deal/take hits and guard; cap 100) | Convert Heat to area pressure; reaching the cap vents to 55 and applies a temporary Exposed liability. |

Vampire's Sanguine Lunge/Eclipse Feast healing is bounded at 24 HP per use. Dragonkin's Heat can be spent before it reaches the cap; overheat causes real increased incoming damage while exposed. Resource caps and skill cooldowns are part of the class design, not decoration.

## Enemies and story bosses

Enemy roles in `entities/enemy.py` are Beast (skirmishing multi-hit), Void (charging/cursing), Nature (durable pressure), Construct (guard/armor), and Cultist (support/rally). Boss identities are Warden Maelis, Choirmaster Orrick, Vael the Silent Seraph, and Sister Elowen, with distinct intent cycles reused across later Endless milestones. Story is a finite 12-hall arc with boss gates at halls 4, 8 and 12; stage and boss lines come from `core/story.py`.

## Progression/economy

Each living hero gains the same encounter XP award. The threshold is `80 × current level`; a level grants +12 max HP, +2 attack, +1 defense, and +5 max Mana if used. Level is capped at 30. Overflow becomes `mastery_xp` up to 10,000,000 and has no stat effect/unlocks in this version. Gold comes from enemy/boss rewards; the merchant uses bounded stock and explicit prices/effect descriptions. Story restores the party automatically after non-final victories; Endless recovery is adjusted by stage/encounter recovery rules.

## Records and fairness

`LocalLeaderboard` stores offline JSON results, keyed by `run_id` so a repeated result transition cannot double-insert. It sorts deterministically and filters Story versus Endless. Score is `stage × 100 + bosses × 350 + (sum(level−1) × 50) + floor(gold/5) + (750 for victory)`, clamped to 2,000,000. This score rewards depth and boss clears, but does not claim any global comparison. Training/debug records are not a shipped mode.

## Current scope exclusions

Only Story Campaign and Endless Rift appear in the shipped mode menu. Arena, Boss Rush, Training Grounds, rotating challenge, route-map choices, online multiplayer, and mastery unlock trees are not implemented and are not advertised in menus.
