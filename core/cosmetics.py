"""Cosmetics & Skin System: visual attire variations and palette themes for all 8 hero classes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional


@dataclass(frozen=True)
class SkinDef:
    key: str
    name: str
    title: str
    desc: str
    accent_color: tuple[int, int, int]
    trim_color: tuple[int, int, int]


COMMON_SKINS: Final[list[SkinDef]] = [
    SkinDef("default", "Classic Penitence", "The Original Oath",
            "Worn travel cloaks and standard forged battle-gear.",
            (210, 195, 175), (105, 95, 85)),
    SkinDef("abyssal", "Choir Vestments", "Hymn of the Deep",
            "Tainted dark silk and void-touched twilight trims.",
            (160, 95, 230), (45, 25, 65)),
    SkinDef("dawnlight", "Gilded Dawn", "Memory of Emberfall",
            "Luminescent gold plate and ivory-embroidered mantle.",
            (245, 210, 110), (180, 140, 50)),
    SkinDef("crimson", "Blood Moon Rite", "Vow of the Eclipse",
            "Deep obsidian leather with sharp vermilion piping.",
            (230, 55, 75), (75, 15, 25)),
]


def get_skins_for_class(pclass_name: str) -> list[SkinDef]:
    return list(COMMON_SKINS)


def get_skin(skin_key: Optional[str]) -> SkinDef:
    if not skin_key:
        return COMMON_SKINS[0]
    for s in COMMON_SKINS:
        if s.key == skin_key:
            return s
    return COMMON_SKINS[0]
