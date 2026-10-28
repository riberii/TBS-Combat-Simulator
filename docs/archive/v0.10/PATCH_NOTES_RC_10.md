# Chains of the Abyssal Choir — v0.10 RC visual/combat pass

## Implemented

- **Angel placement and formation:** party formation now adapts to 1, 2, or 3 heroes. A solo Angel is centered farther into the world; full parties use a compact, evenly spaced formation that reserves the left chronicle and right enemy lane. The formation test checks the Angel's conservative maximum wing envelope.
- **Distinct class models:** the renderer now has dedicated Warrior, Tank, and Rogue silhouettes instead of alternating non-Angel classes between the Angel and Witch models. Warrior receives a greatsword and red war-cloak; Tank has a broad plated frame and tower shield; Rogue has a hood, slim coat and paired knives. The title screen previews all five classes.
- **Enemy silhouettes:** enemy art is now selected by actual archetype, not a fallback/aliased sprite key: Beast, Void, Nature, Construct, Cultist, and a bespoke winged Boss form have different anatomy, equipment, and accent palettes. The title screen includes a boss silhouette.
- **Attack/hit motion:** combat `LUNGE` events drive a short attacker movement and slash arc for both players and enemies. Incoming-hit events shake the corresponding sprite while damage VFX continue to handle impact particles and floaters.
- **Environment art:** the generated procedural cathedral backdrop now layers a blood eclipse, broken orbital rings, asymmetric ruined spires, floating masonry shards, chains, and a fragmented ritual circle over the existing fog/embers/light shafts.
- **Fullscreen/resizing:** F11 toggles fullscreen and back to a resizable 1280×720 window; the fixed-resolution game canvas scales to the display, and mouse-hover coordinates are remapped for restraint targeting.
- **Harder QTEs:** Angel Manacles use a randomized rare word of at least 12 characters; any wrong printable input fails that attack immediately. Other typing QTEs retain their existing reset-on-typo rule. Timing QTEs use a randomized, much narrower target zone, and only Space can trigger the check—Enter is no longer accepted as a shortcut.
- **Restraints matter mechanically:** Angel damage falls as restraint count/tightness rises, non-escape actions drain lucidity in proportion to the bindings, and attacking while carrying multiple restraints tightens them further. `Break Restraint` and `Pierce Palm` remain management actions.

## Verification actually run

- `python -m compileall -q .` — passed.
- `python -m unittest discover -s tests -v` — **41 tests passed, 0 failed**.
- New regression coverage includes: all five classes resolve to distinct runtime sprite kinds; solo and full-party placement leave the chronicle/enemy lane clear; F11 toggles fullscreen/windowed display modes (via a mocked display API); manacled Angel QTEs use the fatal rare-word check; wrong printable input fails immediately; timing checks accept Space only; and restrained/tightened Angel attacks deal less damage.

## Not verified in this environment

Pygame-CE is not installed in this environment (`import pygame` raises `ModuleNotFoundError`). Therefore the new sprite painters and animated frame-by-frame output compile, but I could not run a real Pygame window here to visually inspect them, verify display-driver fullscreen behavior, or confirm physical audio output. The suite exercises real game/combat/QTE/state logic, but the new drawing geometry still needs a desktop launch/playtest before claiming visual sign-off.
