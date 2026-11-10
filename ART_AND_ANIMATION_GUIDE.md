# Art and Animation Guide

## Direction

Original procedural 2D dark-fantasy vectors: gothic silhouettes, near-black/wine shadows, restrained warm highlights, purple/cyan arcane accents, and red/orange damage and heat cues. Character outline, equipment and pose do the primary class-identification work; colour is a secondary cue. The arena backdrop is a layered cathedral with parallax structures, drifting fog, embers, glows, light shafts and a vignette.

## Class silhouettes

- Warrior: split war-cloak, plated greaves, a diagonal greatsword and red fuller.
- Tank: broad plated torso, kite shield and blue tabard.
- Rogue: asymmetric hood, slim split coat and paired daggers.
- Witch: pale flowing hair, gothic hood/gown and rune staff.
- Fallen Angel: pale bandaged figure, dark/violet wings, halo and thorn/c chain details.
- Kitsune: tall fox ears, three animated tails, talisman sash and foxfire glow.
- Vampire: high collar, long wine-red split coat, pale duelist face, rapier and orbiting crimson sigils.
- Dragonkin: horned scaled head, plated torso, shoulder spurs, articulated tail and molten core.

The `CharacterKind` registry in `ui/renderer.py` is the presentation identity map; `_kind_for` in `main.py` maps the authoritative `PlayerClass` to it. `entities/player.py` also contains reusable vector painters for the hero-level render API. The title preview, party sprites and combat sprite path use the eight distinct kinds; resource accents for Vampire/Dragonkin mirror their simulation state for presentation only. Party cards now include the first active class-specific resource bar (Rage, Bastion, Combo, Barrier, Lucidity, Spirit, Blood or Heat), alongside HP/Mana/Stamina.

## Animation and VFX contract

The main renderer uses elapsed time/delta time, per-character phase offsets and cached procedural sprites. Idle variation is continuous without a per-pixel animation cost. Combat events trigger a lunge/attack arc, hit shake, damage/heal/critical accents, bounded cast/guard/dodge actor cues, status toasts and death effects. Actor cues expire after 0.72 seconds and are suppressed by reduced motion. Toasts share one capped queue, preserve up to 120 characters, wrap to two lines in the tiny UI font and use their requested lifetime; four maximum-height toasts (`TOAST_MAX = 4`, width budget 340px) start at y=52 and stay above the solo boss intent card at y=303. Skill methods may call `play_anim` for the entity-level portrait renderer; this only chooses presentation pose, never resolves combat. Boss intent labels and target selection stay anchored to gameplay state.

Use short anticipations/impacts/recoveries rather than blocking `sleep()`. Tank has slower/sturdier motion; Rogue has quick dashes; Witch/Angel use spell/halo accents; Kitsune's tails/embers respond to awakening; Vampire's sigils intensify at higher Blood; Dragonkin's core/embers respond to Heat and overheat. The VFX layer caps effects and responds to screen-shake/particle/reduced-motion settings.

## Window and readability

The game renders to a 1280×720 logical canvas and scales to the current display. Title previews use 0.52 sprite scale. Party formations are explicit: solo x=430 at 0.66 scale, duo x=380/560 at 0.48, trio x=335/462/589 at 0.40. These positions keep the widest 235-unit silhouette estimate between the Chronicle (right edge x=236) and enemy lane (starts x=690); regression tests check each party size and solo Angel clearance. Single- and two-enemy fields use 1.10/1.04 base scales, bosses receive an additional 8%, and dense multi-row fields remain at 0.72. The game uses 1280×720 logical coordinates; F11 switches fullscreen/windowed mode. Only the 1280×720 composition received a final visual inspection in this pass; resized aspect ratios need manual validation. Avoid putting labels inside artwork; UI text should be rendered by game code so it remains legible and translated later.

## Extending art

Add an enum value to `CharacterKind`, a specific `SpritePainter` method and mapping, a `_kind_for` case, and a matching preview in `GameApp.previews`; add a resource-state field only if the simulation actually owns it. Keep hitboxes separate from decorative art. No third-party art packs or remote assets are currently required. Optional user-provided TTF files belong at `assets/fonts/main.ttf`.
