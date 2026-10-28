"""R2 art/audio integration layer.

* Loads PNG sprite sheets from ``Assets/Generated/R2`` (paths are relative to the project, never absolute).
* ``Animation`` is a pure, time-based frame player (no pygame needed) - it honours fps, looping,
  one-shot playback and reduced-motion.  Frames are opaque objects so it can be unit-tested directly.
* ``AssetLibrary`` caches surfaces, owns per-actor loop state and transient one-shot effects, and
  *never raises for a missing or unreadable asset*: every accessor returns ``None`` and the caller falls
  back to the existing procedural art.

Pygame is imported lazily so this module can be imported (and its logic tested) on a machine without it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

LOG = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
R2_ROOT = PROJECT_ROOT / "Assets" / "Generated" / "R2"
MAX_SHOTS = 12
REDUCED_SHOT_SECONDS = 0.25


# ---------------------------------------------------------------------------------------------
# animation specs (cell order is row-major, see Assets/Generated/R2/characters/fallen_angel/FRAME_MAP.md)
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AnimSpec:
    rel: str                     # sheet path relative to R2_ROOT
    cell: tuple[int, int]        # (w, h) of one cell
    cols: int
    rows: int
    fps: float
    loop: bool
    count: int = 0               # frames to use (0 = cols*rows)

    @property
    def frame_count(self) -> int:
        return self.count or self.cols * self.rows

    @property
    def sheet_size(self) -> tuple[int, int]:
        return self.cell[0] * self.cols, self.cell[1] * self.rows


_EL = "vfx/elements/"
ANIMATIONS: dict[str, AnimSpec] = {
}
for _name in ("flame", "frost", "storm", "verdant", "umbral", "radiant"):
    ANIMATIONS[f"el_{_name}"] = AnimSpec(f"{_EL}{_name}_sheet_3x2.png", (128, 128), 3, 2, 12.0, False)

PORTRAITS: dict[str, str] = {   # class key -> file under R2_ROOT/portraits (cropped from concept boards)
    "warrior": "portraits/warrior.png", "tank": "portraits/tank.png", "rogue": "portraits/rogue.png",
    "witch": "portraits/witch.png", "fallen_angel": "portraits/fallen_angel.png",
    "kitsune": "portraits/kitsune.png", "vampire": "portraits/vampire.png",
    "dragonkin": "portraits/dragonkin.png",
}
TITLE_KEY_ART = "backgrounds/title_keyart_left_720.png"
TITLE_LOGO = "ui/title_logo.png"
MODELS: dict[str, str] = {k: f"models/{k}.png" for k in PORTRAITS}      # feathered anime busts used as combat models
MODEL_GLOW: dict[str, tuple[int, int, int]] = {
    "warrior": (255, 120, 90), "tank": (150, 190, 255), "rogue": (120, 235, 160), "witch": (190, 120, 255),
    "fallen_angel": (225, 215, 255), "kitsune": (110, 160, 255), "vampire": (255, 80, 120), "dragonkin": (255, 140, 60),
}
# restraint kind -> boxes as fractions (x, y, w, h) of the drawn model rectangle
MODEL_HIT_FRACTIONS: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "CROWN_OF_THORNS": ((0.28, 0.00, 0.44, 0.22),),
    "SACRED_RUNE_BINDINGS": ((0.00, 0.12, 0.22, 0.45), (0.78, 0.12, 0.22, 0.45)),
    "GOTHIC_CHAINS": ((0.25, 0.45, 0.50, 0.28),),
    "SHADOW_THORN_VINES": ((0.20, 0.72, 0.60, 0.22),),
}
RESTRAINT_KIND_ICON = {"CROWN_OF_THORNS": "halo", "SACRED_RUNE_BINDINGS": "seal",
                       "GOTHIC_CHAINS": "chains", "SHADOW_THORN_VINES": "backlash"}


def model_hit_boxes(rect_x: float, rect_y: float, rect_w: float, rect_h: float, anchor_x: float, anchor_y: float,
                    scale: float) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Restraint hover boxes for a drawn model, in the renderer's convention: 1x units relative to the floor point."""
    out = []
    sc = max(scale, 1e-6)
    for name, boxes in MODEL_HIT_FRACTIONS.items():
        for fx, fy, fw, fh in boxes:
            out.append((name, (int((rect_x + fx * rect_w - anchor_x) / sc), int((rect_y + fy * rect_h - anchor_y) / sc),
                               max(1, int(fw * rect_w / sc)), max(1, int(fh * rect_h / sc)))))
    return out


def fit_model_height(scale: float, aspect: float, neighbour_gap: float) -> float:
    """Pixel height for a hero bust: 300 px at scale 1, shrunk so a crowded party doesn't smother itself."""
    h = 300.0 * scale
    if neighbour_gap > 0 and aspect > 0:
        h = min(h, neighbour_gap * 1.45 / aspect)
    return max(120.0, h)
BOARD_ICONS: tuple[str, ...] = ("slash", "fireball", "ice_burst", "heal", "shield", "lightning", "dark_magic", "explosion")
POP_SECONDS = 0.8
MAX_POPS = 10

_SLASH_KEYS = {"slash", "dash", "cleave", "rend", "execute", "bash", "quick", "assassinate", "pierce", "stab", "strike"}
_FIRE_WORDS = ("fire", "flame", "ember", "inferno", "ignite", "breath", "scorch", "heat")
_ICE_WORDS = ("frost", "ice", "freeze", "chill")


def icon_for_action(key: str, action_type: str = "ability") -> Optional[str]:
    """Map a committed action key to one of the board icons (presentation only); None = no popup."""
    k = str(key or "").lower()
    if not k:
        return None
    if action_type == "item":
        return "heal" if any(w in k for w in ("tonic", "salve", "potion", "heal", "mana", "vigor", "lucid")) else None
    if k in _SLASH_KEYS:
        return "slash"
    if any(w in k for w in _FIRE_WORDS):
        return "fireball"
    if any(w in k for w in _ICE_WORDS):
        return "ice_burst"
    if k in {"guard", "provoke", "barrier", "aegis", "scale_guard", "bastion"}:
        return "shield"
    if k == "halo":
        return "explosion"
    if k in {"bolt", "spark", "storm"}:
        return "lightning"
    if k in {"curse", "drain", "writhe", "hex", "vanish"}:
        return "dark_magic"
    if "heal" in k:
        return "heal"
    return None


SOUNDS: dict[str, str] = {
    "chain_tighten": "audio/chain_tighten.wav", "seal_success": "audio/seal_success.wav",
    "qte_failure": "audio/qte_failure.wav", "resonance_pulse": "audio/resonance_pulse.wav",
}
RESTRAINT_ICONS: dict[str, str] = {
    k: f"ui/restraints/restraint_{k}.png"
    for k in ("chains", "halo", "seal", "wings", "lucidity", "backlash", "release")
}


# ---------------------------------------------------------------------------------------------
# pure animation player
# ---------------------------------------------------------------------------------------------
class Animation:
    """Time-based frame player. ``update(dt)`` advances by real elapsed time, independent of frame rate."""

    def __init__(self, frames: Sequence[Any], fps: float, loop: bool) -> None:
        if not frames:
            raise ValueError("Animation needs at least one frame")
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.frames = list(frames)
        self.fps = float(fps)
        self.loop = bool(loop)
        self.time = 0.0
        self.reduced = False

    @property
    def duration(self) -> float:
        return REDUCED_SHOT_SECONDS if (self.reduced and not self.loop) else len(self.frames) / self.fps

    @property
    def done(self) -> bool:
        return (not self.loop) and self.time >= self.duration

    @property
    def index(self) -> int:
        n = len(self.frames)
        if self.reduced:
            return 0 if self.loop else n // 2        # static pose / single peak frame
        i = int(self.time * self.fps + 1e-6)     # epsilon: 8 x 0.1 s must land on frame 8, not 7.999..
        return i % n if self.loop else min(i, n - 1)

    @property
    def frame(self) -> Any:
        return self.frames[self.index]

    def update(self, dt: float, reduced: bool = False) -> None:
        self.reduced = bool(reduced)
        if dt > 0:
            self.time += min(dt, 0.25)               # a stall must not skip a whole animation

    def reset(self) -> None:
        self.time = 0.0


@dataclass
class _Shot:
    uid: int
    key: str
    anim: Animation
    dx: float = 0.0
    dy: float = 0.0


# ---------------------------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------------------------
class AssetLibrary:
    def __init__(self, root: Path = R2_ROOT, reduced_motion: bool = False, enabled: bool = True) -> None:
        self.root = Path(root)
        self.reduced_motion = bool(reduced_motion)
        self.enabled = bool(enabled)
        self.models_enabled = True           # separate switch: anime hero models vs the original procedural ones
        self._images: dict[str, Any] = {}
        self._frames: dict[str, Optional[list[Any]]] = {}
        self._scaled: dict[tuple, Any] = {}
        self._missing: set[str] = set()
        self._loops: dict[tuple[int, str], Animation] = {}
        self._shots: list[_Shot] = []
        self._pops: list[list] = []          # [uid, icon_name, age]

    # ---- availability --------------------------------------------------------------------
    def _warn_once(self, rel: str, why: str) -> None:
        if rel not in self._missing:
            self._missing.add(rel)
            LOG.warning("R2 asset %s unavailable (%s); using procedural fallback", rel, why)

    def has_file(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def disable(self, reason: str) -> None:
        if self.enabled:
            LOG.warning("R2 art disabled: %s", reason)
        self.enabled = False

    # ---- images --------------------------------------------------------------------------
    def image(self, rel: str) -> Optional[Any]:
        if not self.enabled:
            return None
        if rel in self._images:
            return self._images[rel]
        path = self.root / rel
        if not path.is_file():
            self._warn_once(rel, "file missing")
            return None
        try:
            import pygame
            surf = pygame.image.load(str(path))
            surf = surf.convert_alpha() if pygame.display.get_surface() is not None else surf
        except Exception as exc:  # noqa: BLE001 - pygame.error, missing pygame, corrupt file: all mean "fall back"
            self._warn_once(rel, f"{type(exc).__name__}: {exc}")
            return None
        self._images[rel] = surf
        return surf

    def sheet_frames(self, key: str) -> Optional[list[Any]]:
        """Slice an animation sheet into independent surfaces (cached)."""
        if not self.enabled or key not in ANIMATIONS:
            return None
        if key in self._frames:
            return self._frames[key]
        spec = ANIMATIONS[key]
        sheet = self.image(spec.rel)
        frames: Optional[list[Any]] = None
        if sheet is not None:
            try:
                import pygame
                if sheet.get_size() != spec.sheet_size:
                    raise ValueError(f"sheet is {sheet.get_size()}, expected {spec.sheet_size}")
                cw, ch = spec.cell
                frames = []
                for i in range(spec.frame_count):
                    col, row = i % spec.cols, i // spec.cols
                    frames.append(sheet.subsurface(pygame.Rect(col * cw, row * ch, cw, ch)).copy())
            except Exception as exc:  # noqa: BLE001
                self._warn_once(spec.rel, f"slice failed: {exc}")
                frames = None
        self._frames[key] = frames
        return frames

    def portrait(self, class_key: str, size: Optional[tuple[int, int]] = None, face: bool = False) -> Optional[Any]:
        """Class portrait; ``face`` crops the upper square for small HUD thumbnails."""
        rel = PORTRAITS.get(class_key)
        img = self.image(rel) if rel else None
        if img is None:
            return None
        ck = ("portrait", class_key, size, face)
        if ck in self._scaled:
            return self._scaled[ck]
        try:
            import pygame
            src = img
            if face:
                w, h = img.get_size()
                side = min(w, int(h * 0.88))          # board crops are ~square busts: keep the head, trim the chest
                src = img.subsurface(pygame.Rect(max(0, (w - side) // 2), 0, side, side))
            out = pygame.transform.smoothscale(src, size) if size else src.copy()
        except Exception as exc:  # noqa: BLE001
            self._warn_once(f"portrait:{class_key}", str(exc))
            return None
        self._cache(ck, out)
        return out

    def image_fit_width(self, rel: str, width: int) -> Optional[Any]:
        """Image smooth-scaled to ``width`` px wide (aspect kept, cached)."""
        img = self.image(rel)
        if img is None:
            return None
        ck = ("fitw", rel, int(width))
        if ck not in self._scaled:
            try:
                import pygame
                w, h = img.get_size()
                self._cache(ck, pygame.transform.smoothscale(img, (int(width), max(1, int(h * width / w)))))
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"fitw:{rel}", str(exc))
                return None
        return self._scaled[ck]

    def model_aspect(self, class_key: str) -> Optional[float]:
        if not self.models_enabled:
            return None
        img = self.image(MODELS.get(class_key, "")) if class_key in MODELS else None
        if img is None:
            return None
        w, h = img.get_size()
        return w / h if h else None

    def model(self, class_key: str, height: int) -> Optional[Any]:
        """Anime bust scaled to ``height`` px (cached; heights are snapped to 8 px steps)."""
        if not self.models_enabled:
            return None
        img = self.image(MODELS.get(class_key, "")) if class_key in MODELS else None
        if img is None:
            return None
        height = max(8, int(round(height / 8.0)) * 8)
        ck = ("model", class_key, height)
        if ck not in self._scaled:
            try:
                import pygame
                w, h = img.get_size()
                self._cache(ck, pygame.transform.smoothscale(img, (max(1, int(w * height / h)), height)))
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"model:{class_key}", str(exc))
                return None
        return self._scaled[ck]

    def glow(self, class_key: str, size: tuple[int, int]) -> Optional[Any]:
        """Soft class-coloured halo drawn behind a model."""
        ck = ("glow", class_key, size)
        if ck not in self._scaled:
            try:
                import pygame
                w, h = size
                surf = pygame.Surface((w, h), pygame.SRCALPHA)
                r, g, b = MODEL_GLOW.get(class_key, (200, 160, 255))
                for i in range(9):
                    inset = int(i * min(w, h) * 0.055)
                    pygame.draw.ellipse(surf, (r, g, b, 7 + i * 5), pygame.Rect(inset, inset, max(2, w - 2 * inset), max(2, h - 2 * inset)))
                self._cache(ck, surf)
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"glow:{class_key}", str(exc))
                return None
        return self._scaled[ck]

    def icon(self, name: str, size: int = 32) -> Optional[Any]:
        rel = RESTRAINT_ICONS.get(name)
        img = self.image(rel) if rel else None
        if img is None:
            return None
        ck = ("icon", name, size)
        if ck not in self._scaled:
            try:
                import pygame
                self._cache(ck, pygame.transform.smoothscale(img, (size, size)))
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"icon:{name}", str(exc))
                return None
        return self._scaled[ck]

    def _cache(self, key: tuple, surf: Any) -> None:
        if len(self._scaled) > 256:
            self._scaled.clear()
        self._scaled[key] = surf

    def scaled_frame(self, key: str, index: int, factor: float) -> Optional[Any]:
        frames = self.sheet_frames(key)
        if not frames:
            return None
        ck = ("frame", key, index, round(factor, 2))
        if ck not in self._scaled:
            try:
                import pygame
                f = frames[index]
                w, h = f.get_size()
                self._cache(ck, pygame.transform.scale(f, (max(1, int(w * factor)), max(1, int(h * factor)))))
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"scale:{key}", str(exc))
                return None
        return self._scaled[ck]

    # ---- animation state -----------------------------------------------------------------
    def _loop(self, uid: int, key: str) -> Optional[Animation]:
        anim = self._loops.get((uid, key))
        if anim is None:
            frames = self.sheet_frames(key)
            if not frames:
                return None
            spec = ANIMATIONS[key]
            anim = Animation(frames, spec.fps, spec.loop)
            self._loops[(uid, key)] = anim
        return anim

    def actor_frame(self, uid: int, key: str, factor: float) -> Optional[Any]:
        """Current scaled frame of a looping/one-shot actor animation, or None."""
        anim = self._loop(uid, key)
        if anim is None:
            return None
        return self.scaled_frame(key, anim.index, factor)

    def update(self, dt: float) -> None:
        for anim in self._loops.values():
            anim.update(dt, self.reduced_motion)
        for shot in self._shots:
            shot.anim.update(dt, self.reduced_motion)
        self._shots = [s for s in self._shots if not s.anim.done]
        ttl = POP_SECONDS * (0.5 if self.reduced_motion else 1.0)
        for pop in self._pops:
            pop[2] += min(max(dt, 0.0), 0.25)
        self._pops = [p for p in self._pops if p[2] < ttl]

    def icon_pop(self, uid: int, name: str) -> bool:
        """Show a short, non-blocking skill icon above an actor. False when the art is unavailable."""
        if name not in BOARD_ICONS or self.board_icon(name, 56) is None:
            return False
        self._pops.append([uid, name, 0.0])
        del self._pops[:-MAX_POPS]
        return True

    def board_icon(self, name: str, size: int) -> Optional[Any]:
        img = self.image(f"icons_boards/{name}.png") if name in BOARD_ICONS else None
        if img is None:
            return None
        ck = ("board_icon", name, size)
        if ck not in self._scaled:
            try:
                import pygame
                self._cache(ck, pygame.transform.smoothscale(img, (size, size)))
            except Exception as exc:  # noqa: BLE001
                self._warn_once(f"board_icon:{name}", str(exc))
                return None
        return self._scaled[ck]

    def draw_pops(self, surface: Any, uid: int, x: float, y_top: float, scale: float) -> None:
        ttl = POP_SECONDS * (0.5 if self.reduced_motion else 1.0)
        mine = [p for p in self._pops if p[0] == uid]
        for slot, (_u, name, age) in enumerate(mine[-3:]):
            icon = self.board_icon(name, max(24, int(56 * min(1.2, max(0.6, scale)))))
            if icon is None:
                continue
            try:
                t = age / ttl
                alpha = int(255 * (1.0 - t) ** 1.5 if t > 0.5 else 255)
                rise = 0.0 if self.reduced_motion else 28.0 * t
                img = icon.copy()
                img.set_alpha(max(0, min(255, alpha)))
                surface.blit(img, (int(x - img.get_width() / 2 + (slot - 1) * (img.get_width() + 4)),
                                   int(y_top - img.get_height() - rise)))
            except Exception as exc:  # noqa: BLE001
                self.disable(f"icon pop blit failed: {exc}")
                return

    def trigger(self, uid: int, key: str, dx: float = 0.0, dy: float = 0.0) -> bool:
        """Start a one-shot effect on an actor. Returns False if the asset is unavailable."""
        frames = self.sheet_frames(key)
        if not frames:
            return False
        spec = ANIMATIONS[key]
        anim = Animation(frames, spec.fps, False)
        anim.reduced = self.reduced_motion
        self._shots.append(_Shot(uid, key, anim, dx, dy))
        del self._shots[:-MAX_SHOTS]
        return True

    def active_shots(self, uid: Optional[int] = None) -> list[_Shot]:
        return [s for s in self._shots if uid is None or s.uid == uid]

    def draw_shots(self, surface: Any, uid: int, x: float, y: float, factor: float) -> None:
        """Blit active one-shots anchored bottom-centre at (x, y)."""
        for shot in self.active_shots(uid):
            img = self.scaled_frame(shot.key, shot.anim.index, factor)
            if img is None:
                continue
            try:
                w, h = img.get_size()
                surface.blit(img, (int(x - w / 2 + shot.dx * factor), int(y - h + shot.dy * factor)))
            except Exception as exc:  # noqa: BLE001 - never break the frame for decoration
                self.disable(f"one-shot blit failed: {exc}")
                return

    def forget_actor(self, uid: int) -> None:
        for k in [k for k in self._loops if k[0] == uid]:
            del self._loops[k]
        self._shots = [s for s in self._shots if s.uid != uid]
        self._pops = [p for p in self._pops if p[0] != uid]

    def clear_effects(self) -> None:
        """Called on scene changes so no effect or loop state leaks between screens."""
        self._loops.clear()
        self._shots.clear()
        self._pops.clear()

    # ---- audio ---------------------------------------------------------------------------
    def sound_paths(self) -> dict[str, Path]:
        return {name: self.root / rel for name, rel in SOUNDS.items() if (self.root / rel).is_file()}



def title_sparkles(t: float, count: int = 44, width: int = 1280, height: int = 720
                   ) -> list[tuple[int, int, int, tuple[int, int, int]]]:
    """Deterministic drifting ember positions (x, y, radius, colour) for the menu; pure so it can be tested."""
    out = []
    for i in range(count):
        x = (i * 97.3 + 9.0 * t * (1 + i % 3)) % width
        y = height - ((i * 53.7 + 22.0 * t * (1 + i % 4)) % (height + 20))
        out.append((int(x), int(y), 2 if i % 4 == 0 else 1, (255, 150 + (i * 7) % 80, 100 + (i * 11) % 60)))
    return out


CUTIN_SECONDS = 0.9
CUTIN_REDUCED_SECONDS = 0.45


def cutin_motion(age: float, reduced: bool = False) -> tuple[float, int]:
    """(x offset in px, alpha 0-255) for the turn-start character cut-in at ``age`` seconds.

    Slides in over the first 0.3 s with an ease-out curve, holds, then fades over the last quarter.
    Under reduced motion there is no slide and a shorter fade. Outside [0, duration] it is fully transparent.
    """
    total = CUTIN_REDUCED_SECONDS if reduced else CUTIN_SECONDS
    if age < 0 or age >= total:
        return 0.0, 0
    slide = 0.0
    if not reduced:
        t = min(1.0, age / 0.3)
        slide = -280.0 * (1.0 - t) ** 3                          # starts off to the left, eases out to 0
    fade_start = total * 0.75
    alpha = 255 if age < fade_start else int(255 * (1.0 - (age - fade_start) / (total - fade_start)))
    return slide, max(0, min(255, alpha))
