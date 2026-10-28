# Crop provenance (R2 assets cut from the supplied concept boards)

Source boards are the AI-generated concept images in the user's `More Assets 1-4` ZIPs (1536x1024). They are not
included in this release. Rebuild everything with `python tools/r2_build_models.py <folder with the unzipped boards>`.
Crops are plain rectangles (shown in the 1344-wide review space the boards were inspected at; the tool scales them to
1536 px). No character was repainted; the only edits are feathered alpha edges, sharpening, and the title-art patch below.

| Output | Source board | Crop (display space) |
|---|---|---|
| `models/<class>.png` - 480 px tall feathered RGBA busts used as combat/hub/setup hero models | Warrior, Rogue: `More Assets 1/Fantasy RPG Anime Asset Showcase-15.png`; Tank, Witch, Fallen Angel, Kitsune, Vampire, Dragonkin: `More Assets 2/Chains of the Abyssal Choir-3.png` | warrior 3,34,104,226 · rogue 208,34,306,226 · tank 270,395,490,680 · witch 640,395,850,680 · fallen_angel 30,30,330,325 · kitsune 380,55,640,330 · vampire 640,85,900,335 · dragonkin 810,395,1000,622 |
| `portraits/<class>.png` - opaque face/bust crops (party cards, setup screen, cut-in) | same crops | (small crops are upscaled 2x) |
| `backgrounds/title_keyart_left_720.png` - menu key art | key-art board, crop 0,0,1120,940 (real px) scaled to 720 px tall, 18% darker, right 170 px faded out | The board's baked male Warrior was blacked out and replaced by the female Warrior bust with a matching "Warrior - Blade and Momentum" plaque so every hero is a woman |
| `ui/title_logo.png` | key-art board | 975,25,1335,228, keyed to transparency by brightness |
| `icons_boards/<name>.png` - 8 spell icons | `More Assests 4/Fallen Sanctum RPG Art Pack-6.png` ("Skill & VFX examples") | 63x63 px each, resized to 128x128 |

Why the Warrior and Rogue come from a different board: the key-art board's Warrior is a man, and its Rogue is
mostly hood and daggers; the showcase board's versions are women with clear faces.

Limits: sources are 120-345 px wide, so models are upscaled 1.4-4x and look soft; the Warrior/Rogue are the softest.
Concept boards are AI-generated; their licence/usage terms are the user's responsibility. Content is adult-styled but
non-explicit.
