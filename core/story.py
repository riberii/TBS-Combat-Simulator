"""All narrative text: prologue, stage intros, boss entrances, lore, epilogues, chapters, and class barks."""
from __future__ import annotations

from typing import Final

PROLOGUE: Final[list[tuple[str, str]]] = [
    ("The Silence of Emberfall",
     "For nine hundred years the Dawn Bell rang from the highest tower of Emberfall, and the dark kept its distance.\n\n"
     "Three nights ago it stopped. No crack, no toll. Only silence, and then the singing began: "
     "a choir of ten thousand discordant voices rising from the cathedral that sleeps beneath the world."),
    ("The Descent",
     "The Abyssal Choir has stolen the Bell's heart and chained it below the Sunken Cathedral of Vael. "
     "The elders of Emberfall have no army left. They have you.\n\n"
     "Twelve halls lie between the surface and the Heart of the Bell. Three jailers hold the gates. "
     "Take what coin you can, break the silence, ring the Bell again, and let the dawn return."),
]

CHAPTERS: Final[dict[int, tuple[str, str, str]]] = {
    1: ("Chapter I: The Cinder Threshold", "Stages 1 - 2",
        "The upper catacombs are choked with cold ash from the silenced furnaces. Ashfang beasts prowl the collapsed cloisters."),
    2: ("Chapter II: The Weeping Vaults", "Stages 3 - 4",
        "Water seeps through black masonry as the descent steepens. Warden Maelis guards the Gilded Gate with ten thousand keys."),
    3: ("Chapter III: The Drowned Reliquary", "Stages 5 - 6",
        "Submerged sanctuaries where floating tallow candles cast long shadows across defaced seraphim statues."),
    4: ("Chapter IV: The Gallery of Echoes", "Stages 7 - 8",
        "Corridors of tarnished silver mirrors reflecting false memories. Choirmaster Orrick conducts his choir of shades."),
    5: ("Chapter V: The Iron Garden", "Stages 9 - 10",
        "Thorn gardens of cold black iron bloom without light. The ossuary steps vibrate with the Bell's muffled grief."),
    6: ("Chapter VI: The Silent Throne", "Stages 11 - 12",
        "The highest sanctum of the sunken abyss. The Bell's heart hangs bound in silver chain before the throne of Vael."),
}

STAGE_INTROS: Final[dict[int, str]] = {
    1: ("Hall of Ash. Cold cinders crunch underfoot, and something is breathing in the dark.\n"
        "Faded frescoes of the first dawn-bearers line the cracked stone walls, their gilded halos long ago scraped away."),
    2: ("The Weeping Descent. The stairs weep black water that smells of salt and old tallow.\n"
        "Hymns echo from walls that have no mouths; every drop that strikes stone sounds like a distant chime."),
    3: ("The Gilded Ante-Chamber. Gilded doors hang open ahead, torn from their hinges by immense force.\n"
        "Beyond them: footsteps, too many, too eager, accompanied by the dry clink of iron shackles dragging across tile."),
    4: ("The Gilded Gate. The great portcullis stands locked between the upper tomb and the sunken crypts.\n"
        "Warden Maelis rattles his massive ring of ten thousand keys, each one filed to a razor point."),
    5: ("The Drowned Nave. Pews rot beneath a vaulted ceiling adrift with thousands of floating black candles.\n"
        "The black water ripples silently around half-submerged altars where choir acolytes murmur unholy verses."),
    6: ("The Defaced Cloister. Statues of kneeling seraphim line the arcade, their stone faces frantically scratched out.\n"
        "Iron briars weave between shattered reliquaries, humming with stolen hymns."),
    7: ("The Corridor of Silver Mirrors. Every tarnished glass pane reflects an older, wearier version of yourself.\n"
        "Every reflection mouths the same whispered cadence: 'Lay down your arms... stay and join the verse.'"),
    8: ("The Choir Loft. Enormous lead pipe organs breathe cold air into the grand cavern.\n"
        "Choirmaster Orrick lifts his obsidian baton, and the entire cathedral inhales in chilling unison."),
    9: ("The Ossuary Stair. Ribcages and calcified skulls form the spiral treads beneath your boots.\n"
        "The bones hum in dissonant harmony as you climb, vibrating with the sorrow of nine centuries of lost penitents."),
    10: ("Gardens of Black Iron. Thorns forged of cold iron bloom in pitch-black soil, their razor petals tasting of rust and dried blood.\n"
         "The scent of crushed herbs and ozone hangs thick in the breathless air."),
    11: ("The Sanctum Threshold. The heartbeat of the Dawn Bell is audible now: a deep, rhythmic pulse that rattles your teeth.\n"
         "The air is cold enough to freeze sweat on your brow. Beyond this archway lies the core of the abyss."),
    12: ("The Throne of Vael. The stolen Heart of the Bell hangs bound in three concentric rings of runic chains.\n"
         "Before it, a colossal winged seraph sits motionless upon a throne of white bone, her wings sewn shut with silver thread."),
}

BOSS_INTROS: Final[dict[int, str]] = {
    4: "WARDEN MAELIS: 'Every soul that enters is a key I have not yet turned. Lay your wrists upon the anvil.'",
    8: "CHOIRMASTER ORRICK: 'You are flat. A discord in my sanctuary. Be still, penitents... let me tune you.'",
    12: "VAEL, THE SILENT SERAPH: 'I was the first voice that sang the dawn. I will be the last to hush it into peace. Kneel, and be quiet.'",
}

BOSS_PHASE2_LINES: Final[dict[str, str]] = {
    "Warden Maelis": "MAELIS: 'The lock breaks! Blood will oil the tumblers!'",
    "Choirmaster Orrick": "ORRICK: 'Crescendo! From the diaphragm, let your marrow scream!'",
    "Vael": "VAEL: 'The silver thread snaps... witness the silence that follows the dawn!'",
    "Sister Elowen": "ELOWEN: 'The briars drink deep... the garden claims your blood!'",
}

ANGEL_LORE: Final[str] = (
    "THE PRIME EVIL\n\n"
    "You were cast out of the Choir for refusing the Silencing, and the Abyss remembers.\n\n"
    "Every turn it will bind you in a new chain: Manacles, a Gag, Sabatons, Blindness, Barbed Wings, an Anchor. "
    "They stay until you break them.\n\n"
    "Pain bleeds away your Lucidity. At zero you fall into Bloodlust and swing at anything that moves. "
    "Below 30% HP your Martyrdom doubles your damage.\n\n"
    "You are weak. You are bound. You are going to be magnificent."
)

ANGEL_BOSS_LINE: Final[str] = "VAEL (to the Fallen): 'Sister. You wear my chains so beautifully.'"

VICTORY_EPILOGUE: Final[str] = (
    "The Bell's heart breaks free of its chains and tolls once, a single clear note that shakes the cathedral to dust.\n\n"
    "Far above, in Emberfall, the sky splits with gold. The Choir falls silent, not in victory but in relief.\n\n"
    "You climb into the dawn. Whatever else happens, the world will wake tomorrow because of you."
)

VICTORY_ANGEL_EPILOGUE: Final[str] = (
    "Vael's silver stitches unravel. Her wings open, and for one breath she is only your sister again.\n\n"
    "'Ring it,' she whispers. You do, and the last of your chains turn to light.\n\n"
    "The Fallen is fallen no more. She walks into the dawn on bleeding, unbroken feet."
)

DEFEAT_EPILOGUE: Final[str] = (
    "The singing swells. One by one, your names are added to the verse.\n\n"
    "Emberfall waits in silence for heroes who will not come."
)

# Class-specific barks for atmospheric and tactical flavor
CLASS_BARKS: Final[dict[str, dict[str, list[str]]]] = {
    "WARRIOR": {
        "start": ["Steel remembers.", "Hold the line and strike true.", "Let them taste cold iron."],
        "low_hp": ["Bleeding is just proof I'm still standing!", "Not yet... my blade has work left!"],
        "boss": ["An overgrown jailer. Nothing my edge can't split.", "Stand firm, party! Strike as one!"],
        "victory": ["The path is clear. Onward.", "Clean steel, steady breath."],
    },
    "TANK": {
        "start": ["Get behind my shield!", "My armor is the wall between you and the abyss.", "Brace yourselves!"],
        "low_hp": ["Dents in the plate... I can take worse!", "Focus on me, fiends! I'm still here!"],
        "boss": ["Hit me with everything you've got!", "You won't break this bulwark, monstrosity!"],
        "victory": ["Shield held. Everyone intact?", "The wall stands unbroken."],
    },
    "ROGUE": {
        "start": ["Stay in the shadows.", "They won't see the cut until it's finished.", "Eyes sharp, pockets lighter."],
        "low_hp": ["Too close for comfort...", "Time to slip behind their guard!"],
        "boss": ["Big target, big blind spots.", "One precise cut between the joints is all it takes."],
        "victory": ["Clean work. Check the corpses for coin.", "Shadows keep our secrets."],
    },
    "WITCH": {
        "start": ["The ether ripples with corruption.", "A hex upon their hollow hearts.", "Flames of the pyre, answer my call."],
        "low_hp": ["The seals are fraying...", "Blood fuels the incantation just as well!"],
        "boss": ["Such ancient, rotting magic... I'll tear it apart.", "Your discordant chant ends here!"],
        "victory": ["The ether settles once more.", "Knowledge bought with cinder and ash."],
    },
    "ANGEL": {
        "start": ["The chains tighten... but I still breathe.", "I remember the sky.", "Break the links, one by one."],
        "low_hp": ["Martyrdom calls... I feel the fire!", "Pain is just another chain to shatter!"],
        "boss": ["Sister... Choirmaster... your choir ends today.", "I will ring the Bell with my broken hands."],
        "victory": ["Another shackle broken. The dawn comes closer.", "One step nearer to the open sky."],
    },
    "KITSUNE": {
        "start": ["Nine paths through the dark, and each ends in foxfire.", "Strike the shadow, miss the fox.", "Let the masquerade begin."],
        "low_hp": ["My tails are scorched, but my mind is clear.", "An illusion fades, but I remain!"],
        "boss": ["Such heavy steps for such a pompous foe.", "Dance with me, tyrant—if you can keep up!"],
        "victory": ["Tricked, burnt, and scattered to ash.", "A playful smile for a deadly job."],
    },
    "VAMPIRE": {
        "start": ["The dark welcomes its rightful aristocracy.", "A measured sip before the feast.", "Blood speaks louder than hymns."],
        "low_hp": ["The thirst deepens... desperate times.", "I require fresh vintage immediately."],
        "boss": ["Such ancient vitality... let us see how sweet it runs.", "Bow your head before true noble blood!"],
        "victory": ["Appetite sated. For now.", "Clean vintage, though a bit cold."],
    },
    "DRAGONKIN": {
        "start": ["Furnace is stoked!", "Scales of iron, breath of cinder!", "Feel the heat of the primeval wyrms!"],
        "low_hp": ["Scales cracking... furnace burning hotter!", "I will melt this stone before I fall!"],
        "boss": ["A grand beast! Worthy of my furnace!", "Roar all you like—dragons answer with flame!"],
        "victory": ["Ashes to ashes. Scales intact.", "The furnace rests."],
    },
}

NPC_DIALOGUES: Final[dict[str, list[tuple[str, str]]]] = {
    "Archivist Voren": [
        ("On the Dawn Bell", "Nine centuries ago, the First Bell-Ringer cast it from meteoritic ore and quenched it in holy springwater. Its toll resonated with the ley lines, repelling the subterranean dark. When Vael silenced it, the resonance inverted."),
        ("On the Chained Angel", "The Fallen was once the lead cantor of the Choir. When she discovered Vael intended to quench the Bell's flame permanently, she rebelled. They bound her in six ritual restraints, each designed to bleed her lucidity away."),
        ("On the Three Jailers", "Maelis holds the keys of the catacombs; Orrick tunes the souls of the dead; and Vael... Vael waits upon her bone throne, dreaming of eternal silence."),
    ],
    "Sister Moira": [
        ("On the Waters", "Do not drink the black water of the fifth hall, penitents. It carries the tears of a thousand unhallowed funerals. Wash your blade in it, perhaps, but keep your lips sealed."),
        ("On Emberfall", "Above us, our brothers and sisters gather around dying hearths. Without the Dawn Bell, the crops rot in the frost and children forget what sunrise looks like. Ring the bell, I beg of you."),
    ],
    "The Hollow Peddler": [
        ("On his wares", "Where do I get them? Heh heh... from those who didn't make it to stage four, of course! A slightly dented breastplate, half-drunk tonics... recycled salvation, penitent!"),
        ("On coin", "Gold doesn't rot, even in the dark. It gleams like little pieces of the sun. Give me your gold, and I will give you tomorrow."),
    ],
}
