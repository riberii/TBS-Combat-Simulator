"""Asset loading and frame animation for Chains of the Abyssal Choir (R2).

Design rules (from the R2 brief):
  * every path is resolved relative to the project root, never an absolute machine path;
  * surfaces are cached; a missing or unreadable optional file returns ``None`` (one warning, no crash) so
    callers can fall back to the procedural art that already exists;
  * animation timing is driven by elapsed seconds (``Animation.update(dt)``), not by frame count, so it is
    identical at 30 and 144 FPS; ``loop=False`` gives one-shot playback for cast/release/backlash effects;
  * ``reduced_motion`` freezes an animation on a representative still frame.

The timing logic (``Animation``) has no pygame dependency and is unit-tested headless.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "Assets"
R2 = "Generated/R2"
_LOG = logging.getLogger("coac.assets")


@dataclass(frozen=True)
class SheetSpec:
    """Row-major sprite sheet description (see Assets/Generated/R2/characters/fallen_angel/FRAME_MAP.md)."""

    path: str
    cell_w: int
    cell_h: int
    cols: int
    rows: int
    fps: float
    loop: bool
    frames: int = 0  # 0 => cols * rows


# name -> sheet. Frame sizes/fps are taken from the R2 manifest / FRAME_MAP and re-checked by tests/test_assets.py.
SHEETS: dict[str, SheetSpec] = {
    "angel_idle": SheetSpec(f"{R2}/characters/fallen_angel/fallen_angel_idle_sheet_4x2.png", 192, 224, 4, 2, 9.0, True),
    "angel_restrained": SheetSpec(f"{R2}/characters/fallen_angel/fallen_angel_restrained_sheet_4x2.png", 192, 224, 4, 2, 10.0, True),
    "angel_slash": SheetSpec(f"{R2}/characters/fallen_angel/fallen_angel_chain_slash_sheet_4x2.png", 192, 224, 4, 2, 13.3, False),
    "angel_cast": SheetSpec(f"{R2}/vfx/fallen_angel/fallen_angel_chain_cast_sheet_4x2.png", 192, 224, 4, 2, 11.8, False),
    "angel_release": SheetSpec(f"{R2}/vfx/fallen_angel/fallen_angel_release_sheet_4x2.png", 192, 224, 4, 2, 10.0, False),
    "angel_backlash": SheetSpec(f"{R2}/vfx/fallen_angel/fallen_angel_backlash_sheet_4x2.png", 192, 224, 4, 2, 11.1, False),
    "icons_restraint": SheetSpec(f"{R2}/ui/restraints/restraint_icons_sheet_4x2.png", 96, 96, 4, 2, 1.0, True, 7),
}
for _el in ("flame", "frost", "storm", "verdant", "umbral", "radiant"):
    SHEETS[f"fx_{_el}"] = SheetSpec(f"{R2}/vfx/elements/{_el}_sheet_3x2.png", 128, 128, 3, 2, 10.0, False)

CLASS_PORTRAITS = ("warrior", "tank", "rogue", "witch", "fallen_angel", "kitsune", "vampire", "dragonkin")
RESTRAINT_ICONS = {
    "chains": f"{R2}/ui/restraints/restraint_chains.png",
    "halo": f"{R2}/ui/restraints/restraint_halo.png",
    "seal": f"{R2}/ui/restraints/restraint_seal.png",
    "wings": f"{R2}/ui/restraints/restraint_wings.png",
    "lucidity": f"{R2}/ui/restraints/restraint_lucidity.png",
    "backlash": f"{R2}/ui/restraints/restraint_backlash.png",
    "release": f"{R2}/ui/restraints/restraint_release.png",
}


# Boss name fragment -> portrait file in Assets/Art/bosses (cut from the supplied concept boards, see ART_SOURCES.json).
BOSS_ART: dict[str, str] = {
    "maelis": "boss_elysia", "orrick": "boss_seraphine", "vael": "boss_umbral", "elowen": "boss_briar",
}
BOSS_ART_FALLBACK = ("boss_elysia", "boss_seraphine", "boss_umbral")


def boss_art_key(name: str) -> str:
    """Portrait key for a boss name (stable; unknown bosses cycle the seraph set by name hash)."""
    low = str(name).lower()
    for frag, key in BOSS_ART.items():
        if frag in low:
            return key
    return BOSS_ART_FALLBACK[sum(map(ord, low)) % len(BOSS_ART_FALLBACK)]


class Animation:
    """Time-driven frame player. ``frames`` may be pygame surfaces or any objects (tests use ints)."""

    def __init__(self, frames: Sequence[Any], fps: float, loop: bool = True, reduced_motion: bool = False) -> None:
        if not frames:
            raise ValueError("Animation needs at least one frame")
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.frames = list(frames)
        self.fps = float(fps)
        self.loop = bool(loop)
        self.reduced_motion = bool(reduced_motion)
        self.elapsed = 0.0

    def reset(self) -> None:
        self.elapsed = 0.0

    @property
    def duration(self) -> float:
        return len(self.frames) / self.fps

    @property
    def done(self) -> bool:
        return (not self.loop) and self.elapsed >= self.duration

    def update(self, dt: float) -> None:
        if dt > 0 and not self.reduced_motion:
            self.elapsed += dt
            if self.loop:
                self.elapsed %= self.duration
            else:
                self.elapsed = min(self.elapsed, self.duration)

    @property
    def index(self) -> int:
        if self.reduced_motion:
            # one-shot effects settle on their last frame (the result), loops on their first (the pose)
            return 0 if self.loop else len(self.frames) - 1
        i = int(self.elapsed * self.fps)
        return min(i, len(self.frames) - 1)

    @property
    def frame(self) -> Any:
        return self.frames[self.index]


class AssetManager:
    """Cached, fail-soft loader. Construct once after the display exists (needs ``convert_alpha``)."""

    def __init__(self, root: Path = ASSET_ROOT) -> None:
        self.root = Path(root)
        self._images: dict[tuple[str, Optional[tuple[int, int]]], Any] = {}
        self._frames: dict[str, list[Any]] = {}
        self._missing: set[str] = set()
        self.reduced_motion = False

    # -- files ---------------------------------------------------------------------------------------
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"asset path escapes the asset root: {rel!r}")
        return p

    def exists(self, rel: str) -> bool:
        try:
            return self.path(rel).is_file()
        except ValueError:
            return False

    def image(self, rel: str, size: Optional[tuple[int, int]] = None, smooth: bool = True) -> Optional[Any]:
        """Return a (cached) surface, optionally scaled to ``size``; ``None`` if missing/unreadable."""
        key = (rel, size)
        if key in self._images:
            return self._images[key]
        surf = None
        if rel not in self._missing:
            try:
                import pygame
                surf = pygame.image.load(str(self.path(rel)))
                surf = surf.convert_alpha() if rel.lower().endswith(".png") else surf.convert()
            except Exception as exc:  # noqa: BLE001 - optional art must never crash the game
                self._missing.add(rel)
                _LOG.warning("optional asset unavailable: %s (%s)", rel, exc)
                surf = None
        if surf is not None and size is not None and surf.get_size() != tuple(size):
            import pygame
            scale = pygame.transform.smoothscale if smooth else pygame.transform.scale
            surf = scale(surf, (max(1, int(size[0])), max(1, int(size[1]))))
        self._images[key] = surf
        if len(self._images) > 400:  # bounded cache
            self._images.pop(next(iter(self._images)))
        return surf

    def fit(self, rel: str, box: tuple[int, int], cover: bool = False) -> Optional[Any]:
        """Scale keeping aspect ratio to fit (or cover) ``box``."""
        base = self.image(rel)
        if base is None:
            return None
        bw, bh = base.get_size()
        k = (max if cover else min)(box[0] / bw, box[1] / bh)
        return self.image(rel, (max(1, round(bw * k)), max(1, round(bh * k))))

    # -- sheets / animations ----------------------------------------------------------------------------
    def sheet_frames(self, name: str) -> list[Any]:
        if name in self._frames:
            return self._frames[name]
        spec = SHEETS[name]
        out: list[Any] = []
        sheet = self.image(spec.path)
        if sheet is not None:
            import pygame
            total = spec.frames or spec.cols * spec.rows
            if sheet.get_width() < spec.cols * spec.cell_w or sheet.get_height() < spec.rows * spec.cell_h:
                _LOG.warning("sheet %s is smaller than its spec; ignoring", spec.path)
            else:
                for i in range(total):
                    c, r = i % spec.cols, i // spec.cols
                    out.append(sheet.subsurface(pygame.Rect(c * spec.cell_w, r * spec.cell_h, spec.cell_w, spec.cell_h)).copy())
        self._frames[name] = out
        return out

    def animation(self, name: str) -> Optional[Animation]:
        """A fresh ``Animation`` instance (own clock) for a named sheet, or ``None`` if the art is missing."""
        spec = SHEETS[name]
        frames = self.sheet_frames(name)
        if not frames:
            return None
        return Animation(frames, spec.fps, spec.loop, self.reduced_motion)

    # -- named art -----------------------------------------------------------------------------------
    def model(self, class_key: str) -> Optional[Any]:
        """Full-figure RGBA cut-out of a class heroine (``Art/models/<class>.png``), or None."""
        return self.image(f"Art/models/{class_key}.png")

    def background(self, name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/backgrounds/{name}.jpg", size)

    def icon(self, name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/icons/{name}.png", size)

    def fx(self, name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/fx/{name}.png", size)

    def card(self, name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/cards/{name}.png", size)

    def boss_portrait(self, boss_name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/bosses/{boss_art_key(boss_name)}.png", size)

    def banner(self, name: str, size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/bosses/{name}.png", size)

    def keyart(self, name: str = "title_keyart", size: Optional[tuple[int, int]] = None) -> Optional[Any]:
        return self.image(f"Art/keyart/{name}.jpg", size)

    # -- convenience ---------------------------------------------------------------------------------
    def portrait(self, class_key: str, size: Optional[tuple[int, int]] = None, cover: bool = True) -> Optional[Any]:
        rel = f"Art/portraits/{class_key}.png"
        if size is None:
            return self.image(rel)
        return self.fit(rel, size, cover=cover)

    def restraint_icon(self, key: str, size: int = 32) -> Optional[Any]:
        rel = RESTRAINT_ICONS.get(key)
        return self.image(rel, (size, size)) if rel else None


# Fallen Angel restraint label fragment -> icon key in RESTRAINT_ICONS (one distinct icon per restraint).
_RESTRAINT_ICON_BY_LABEL = (("manacle", "chains"), ("gag", "seal"), ("depriv", "lucidity"),
                            ("sabaton", "backlash"), ("wing", "wings"), ("anchor", "halo"))


def restraint_icon_key(label: str) -> str:
    low = str(label).lower()
    for frag, key in _RESTRAINT_ICON_BY_LABEL:
        if frag in low:
            return key
    return "chains"


def class_portrait_key(name: str) -> str:
    """Map a PlayerClass name/label ('FALLEN_ANGEL', 'Fallen Angel', 'ANGEL') to a portrait file key."""
    k = str(name).strip().lower().replace(" ", "_")
    return "fallen_angel" if k in ("angel", "fallen_angel") else k


# stage -> background art (names in Assets/Art/backgrounds). Regions follow main._region_for_stage.
STAGE_BACKGROUNDS: dict[int, str] = {
    1: "ruined_cathedral", 2: "forest_path", 3: "terrace",
    4: "boss_arena", 5: "chapel", 6: "main_hall",
    7: "library", 8: "boss_arena", 9: "hidden_room",
    10: "academy_hall_night", 11: "abyssal_academy", 12: "boss_arena",
}
FALLBACK_BACKGROUNDS = ("abyssal_realm", "abyssal_academy", "terrace")


def background_for_stage(stage: int) -> str:
    """Deterministic art-background name for a stage number (13+ cycles the abyssal set)."""
    st = max(1, int(stage))
    if st in STAGE_BACKGROUNDS:
        return STAGE_BACKGROUNDS[st]
    return FALLBACK_BACKGROUNDS[(st - 13) % len(FALLBACK_BACKGROUNDS)]
