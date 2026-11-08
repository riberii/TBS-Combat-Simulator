# CHANGELOG — R2

R2 builds on V2.0 without removing its systems. Verification level for every item is in `TEST_REPORT.md`; **nothing below has run on real Pygame-ce.**

## Fallen Angel restraints
- Restraints stay central and non-bypassable. New data-driven **restraint trial library**: 19 trials in 8 families (thrash, alternate, rhythm/counter, rune, conditional, precision, word, seal) with tiers Initiate / Bound / Condemned / Judgment and three boss trials.
- **Anti-spam:** `SpamGuard` rate-limits and fatigues repeated input; tests prove mashing/holding at 8–60 Hz clears nothing. Every trial has a reference solution proven solvable at every allowed tier.
- Failed trials have **visible causes** and heavier consequences, with a recovery path (failed trials build break momentum, +0.10 break chance per step, capped at 3) so a bad streak is not a death spiral.
- Trials use the combat seed, avoid immediate repeats, and are guarded by a watchdog.
- **Fixed (user report):** Sensory Deprivation now blacks out enemy intent on the enemy cards, not only in the preview.

## Skills and perks
- 6 nodes per class (48 total), each with a runtime hook; perks are declared in `Player.__init__` so they persist through save/load. Fixed dead/mismatched nodes (Grace Touched, Veil of Mist).

## Elements
- Damage types Physical / Fire / Frost / Storm / Holy / Shadow; per-archetype and per-class affinities (bosses keep half the swing); statuses Burn, Chill, Shock, Suppressed, Mark. Element-tinted floaters, WEAK/resist tags and `W:`/`R:` lines on enemy cards.

## Cards (hybrid prototype)
- 24 cards, 6 relics, class decks, hand 5 (opening 4), draw/discard/exhaust/reshuffle, mulligan, tags SETUP/STRIKE/WARD/SHIFT/SILENCE/DETONATE, Angel cards that interact with restraints, dead-hand prevention, enemy intent always visible.
- Between-fight **draft screen**: three offers (card / relic / upgrade / remove / transmute), skip for gold. Seeded per run, saved with the run.

## Shrine (optional risk/reward)
- Once per hall the camp menu offers **Kneel at the Shrine**: three seeded bargains from Blood Pact (party bleeds 30% current HP for a relic), Gilded Penance (gold for a card upgrade), Burnt Offering (burn a card for gold) and Choir's Gamble (coin toss: gold or 25% HP). Costs are shown on the card, never lethal (HP never drops below 1), declining is free, and the use is saved with the run. Logic in `systems/shrine.py`, 8 tests plus an emulated flow check.

## Fallen Angel outfit
- On request, the Fallen Angel's standee and portrait now wear a white-lavender dress top over the chest, sampled from the white dress she already wears (`tools/cover_angel.py`: skin-coloured pixels in a hand-set chest region are recoloured while the chains, straps and shading stay on top). `tools/extract_art.py` applies it automatically, it is idempotent, and `tests/test_angel_cover.py` fails if bare skin reappears in that region. Only the Fallen Angel was changed; the legs/thighs and the other seven heroes are as cut from the concept boards.

## Art, UI, audio
- Anime-style cut-out standees, portraits, backgrounds, card art and boss portraits from the supplied concept boards; setup class stage; boss intro banner.
- Element sheet animations and chain-ring restraint FX; restraint icons in the sidebar and journal; reduced-motion support in the animation helper (`ui/assets.py::Animation`).
- Four generated R2 WAVs loaded with procedural fallback; trial/card event sounds.
- Layout fixes: sidebar overlap on draft/ending, hub hint, ending title.

## Tooling and tests
- `tools/render_preview.py` (emulated screens), `tools/balance_sim.py`, `tools/draft_flow_check.py`, `tools/headless_bootstrap.py`; validator covers cards and trials; 205 tests (was 93).
- V2 tests updated on purpose: skill tree 24 → 48 nodes; hub menu now also lists the shrine.
