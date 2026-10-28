# Asset Credits and Provenance

This build does not bundle third-party art, commercial game sprites, remote images, purchased fonts, recorded performances, or copyrighted music. No third-party media attribution is required for bundled game assets.

- **Characters, enemies, restraints, cathedral environment and combat effects:** procedural drawings implemented in `entities/player.py`, `entities/enemy.py`, `ui/renderer.py`, `main.py`, and `ui/vfx.py`; no external image files are bundled.
- **Sound effects and simple music layers:** generated at runtime by `systems/audio_system.py`; NumPy and pygame-ce are used locally. No network fetch or streamed audio is required.
- **Fonts:** OS/system serif fallbacks by default. A user may optionally supply a local `.ttf` as `assets/fonts/main.ttf`; it is not bundled here.
- **UI icons and ornaments:** procedurally drawn with the game renderer.

The supplied fantasy portrait was treated as a visual reference only and is not included in the game package. The linked [TBS-Combat-Simulator](https://github.com/riberii/TBS-Combat-Simulator) is cited as a project reference in `CREDITS.md`, not as a media asset. The existing MIT notice and copyright are preserved in `LICENSE.txt`. Essential gameplay visuals and audio generation are local/offline; optional font loading falls back to system fonts.
