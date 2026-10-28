"""Abyssal Choir: single pygame-ce launch point for the turn-based RPG.

One Pygame loop owns every state transition:

    TITLE -> MODE_SELECT -> SETUP (1-3 heroes) -> DIFFICULTY -> COMBAT -> REWARDS
          -> HUB (merchant / next encounter) -> ... -> ENDING; SLOTS and PAUSE are reachable in a run.

Story Campaign ends after the twelve authored halls. Endless Rift continues on a bounded scaling curve.

Gameplay rules live in core.game_state / systems.*; this file only routes keys, drives the objects and paints
read-only views of their state.  ui.renderer.Renderer supplies the backdrop and hero sprites.

Controls
    Menus     UP/DOWN (or W/S) move, ENTER/SPACE confirm, ESC back
    Setup     UP/DOWN rows, LEFT/RIGHT size or class, type to name a hero, ENTER next row
    Combat    keys are forwarded to CombatSystem.handle_key;  P pauses (ESC too while enemies act)
    Shop      UP/DOWN move, ENTER buy / proceed, ESC leave        F2 mute

Run:  python main.py [--seed N] [--max-frames N]

Smoke tests (headless: SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python main.py --seed 7 --max-frames 120)
    1. Title shows New / Continue / Load / Local Records / Settings / Quit; Continue loads the newest valid save.
    2. New -> size 1..3, class cycling, typed names, duplicate names are de-duplicated, empty names get defaults.
    3. Difficulty list -> start run -> encounter banner, party cards, enemy cards with intent, gold / stage bar.
    4. Combat: MENU -> TARGET -> QTE -> RESOLVE -> ENEMY keys reach CombatSystem; popups appear and expire.
    5. Victory claims rewards exactly once, autosaves, then offers Merchant or Next stage; recovery is automatic.
    6. Pause (P) freezes combat; Resume works; Save is disabled during combat; Load restores the saved screen.
    7. Defeat (party_alive False) and run_complete both reach ENDING; New Run / Main Menu / Quit all work.
    8. Corrupt or empty slot -> popup error, no crash.
"""
from __future__ import annotations

import argparse
import importlib
import logging
import math
import os
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pygame

from core.config import Pal, PlayerClass
from core.cosmetics import COMMON_SKINS, get_skin
from core.game_state import GameState, PlayerConfig
from core.pets import PETS, get_pet
from core import story as story_content
from core.tutorials import CLASS_TUTORIALS, GENERAL_TUTORIALS
from core.meta_progression import (
    PlayerProfile, ProfileStore, DailyTask, get_daily_task,
    calculate_run_shards, apply_profile_bonuses,
    PERK_HELP, SKILL_TREE, nodes_for_class, SHARD_ICON, SHARD_CURRENCY_NAME,
)

from ui.renderer import (Character, CharacterKind, RestraintKind, Renderer as AAARenderer,
                         clamp, glow_add, load_font, mix)
from ui.vfx import VFX
from ui.r2_assets import (CUTIN_REDUCED_SECONDS, CUTIN_SECONDS, MODEL_GLOW, TITLE_KEY_ART, TITLE_LOGO, AssetLibrary,
                          cutin_motion, icon_for_action, title_sparkles)
from entities.player import FallenAngel, Restraint as PlayerRestraint
from systems.audio_system import AudioSystem as ProceduralAudioSystem
from systems.combat_system import CombatSystem
from systems.inventory_system import Shop
from systems.leaderboard import LeaderboardError, LocalLeaderboard
from systems.save_system import SaveManager, SaveSystemError
from systems.settings_system import SettingsError, SettingsStore

Color = tuple[int, int, int]
_LOG = logging.getLogger(__name__)

# ======================================================================================================
#  constants
# ======================================================================================================
W, H = 1280, 720
FPS = 60
TITLE = "Chains of the Abyssal Choir | V2.0"
MAX_PARTY = 3
NAME_MAX = 12
# SaveManager uses 1-based slots. Reserve slot 1 for the autosave and keep three
# numbered manual slots (2..4 internally; displayed as Slots 1..3).
AUTOSAVE_SLOT = 1
SAVE_SLOTS = (2, 3, 4)
POPUP_MAX = 5
DEFAULT_DIFFICULTIES = ("Easy", "Normal", "Hard")

INK: Color = (14, 9, 22)
BONE: Color = (232, 224, 244)
MUTED: Color = (150, 138, 176)
DIM: Color = (96, 88, 116)
GOLD: Color = (240, 200, 120)
BLOOD: Color = (214, 70, 86)
MANA_BLUE: Color = (96, 140, 255)
STAMINA_GOLD: Color = (226, 184, 92)
RUNE_PURPLE: Color = (190, 126, 255)
WARN: Color = (255, 170, 90)
GREEN: Color = (100, 220, 130)
CYAN: Color = (92, 212, 222)

TITLE_PREVIEW_SPECS = (
    (CharacterKind.WARRIOR, "Vanguard"),
    (CharacterKind.TANK, "Bulwark"),
    (CharacterKind.ROGUE, "Shade"),
    (CharacterKind.WITCH, "Hexweaver"),
    (CharacterKind.FALLEN_ANGEL, "Seraphine"),
    (CharacterKind.KITSUNE, "Kitsune"),
    (CharacterKind.VAMPIRE, "Noct"),
    (CharacterKind.DRAGONKIN, "Vaelor"),
)
TITLE_PREVIEW_SCALE = 0.52
TITLE_PREVIEW_X0 = 84.0   # first preview hero's x; labels under the heroes reuse these values
TITLE_PREVIEW_DX = 158.0
TITLE_PREVIEW_Y = 640.0
PARTY_FORMATIONS: dict[int, tuple[tuple[float, ...], float]] = {
    1: ((463.0,), 0.90),
    2: ((402.0, 524.0), 0.70),
    3: ((360.0, 463.0, 566.0), 0.52),
}
CREDIT_URL = "https://github.com/riberii/TBS-Combat-Simulator"


def party_formation(size: int) -> tuple[tuple[float, ...], float]:
    """Measured battle positions/scales for the one-to-three hero party."""
    if isinstance(size, bool) or not isinstance(size, int) or size not in PARTY_FORMATIONS:
        raise ValueError("party size must be between one and three")
    return PARTY_FORMATIONS[size]


def _region_for_stage(stage: int) -> str:
    """Map stage number to a named region for regional shop pricing."""
    if stage <= 3:
        return "oath_road"
    elif stage <= 6:
        return "cathedral"
    elif stage <= 9:
        return "sanctum"
    elif stage <= 12:
        return "choir_heart"
    else:
        return "abyss"

_GAME_ERRORS = (SaveSystemError, ValueError, RuntimeError, KeyError, IndexError, TypeError, AttributeError, OSError)


class Screen(Enum):
    TITLE = auto()
    MODE_SELECT = auto()
    SETUP = auto()
    DIFFICULTY = auto()
    SLOTS = auto()
    COMBAT = auto()
    REWARDS = auto()
    HUB = auto()
    SHOP = auto()
    ENDING = auto()
    LEADERBOARD = auto()
    SETTINGS = auto()
    CREDITS = auto()
    TUTORIALS = auto()
    WARDROBE = auto()
    SKILL_TREE = auto()
    DIALOGUE = auto()


# ======================================================================================================
#  defensive helpers (the game-logic objects are read, never re-implemented)
# ======================================================================================================
def _pname(phase: Any) -> str:
    return str(getattr(phase, "name", phase)).upper()


def _num(obj: Any, names: Sequence[str], default: Optional[float] = None) -> Optional[float]:
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return default


def _label(obj: Any, limit: int = 40) -> str:
    if obj is None:
        return ""
    text = ""
    if isinstance(obj, str):
        text = obj
    elif isinstance(obj, Enum):
        text = obj.name.replace("_", " ").title()
    else:
        for n in ("label", "name", "title", "text", "kind", "id"):
            v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
            if isinstance(v, Enum):
                v = v.name.replace("_", " ").title()
            if isinstance(v, str) and v:
                text = v
                break
        if not text:
            text = str(obj)
    return text if len(text) <= limit else text[: limit - 1] + "."


def _alive(obj: Any) -> bool:
    flag = getattr(obj, "alive", None)
    if isinstance(flag, bool):
        return flag
    return (_num(obj, ("hp",), 1.0) or 0.0) > 0.0


def _event_text(ev: Any) -> str:
    if isinstance(ev, str):
        return ev
    for n in ("text", "message", "msg", "popup"):
        v = ev.get(n) if isinstance(ev, dict) else getattr(ev, n, None)
        if isinstance(v, str) and v:
            return v
    return ""


def _intent_text(enemy: Any) -> str:
    for n in ("intent", "telegraph", "next_action", "planned_action", "next_move"):
        v = getattr(enemy, n, None)
        if v is None or v == "" or callable(v):
            continue
        kind_obj = getattr(v, "kind", None)
        kind_name = str(getattr(kind_obj, "name", getattr(v, "name", ""))).upper()
        atk = int(getattr(enemy, "atk", 10) or 10)
        power = float(getattr(v, "power", 1.0) or 1.0)
        hits = int(getattr(v, "hits", 1) or 1)

        if "DEVASTATE" in kind_name:
            est = max(1, int(atk * 2.5))
            return f"DEVASTATION! (~{est} dmg)"
        if "CHARGE" in kind_name:
            return "Gathering Power (Brace!)"
        if "CURSE" in kind_name:
            return "Abyssal Curse (Lucidity)"
        if "GUARD" in kind_name or "BRACE" in kind_name:
            return "Brace (+DEF buff)"
        if "RALLY" in kind_name:
            return "Rally (+Allies ATK)"
        if "SKIP" in kind_name or "DAZED" in kind_name:
            return "Dazed (Inactive)"
        if "MULTI" in kind_name:
            est_per_hit = max(1, int(atk * power))
            return f"Flurry ({hits}x ~{est_per_hit} dmg)"
        if "HEAVY" in kind_name:
            est = max(1, int(atk * power))
            return f"Crushing Blow (~{est} dmg)"
        if "ATTACK" in kind_name:
            est = max(1, int(atk * power))
            return f"Attack (~{est} dmg)"

        text = _label(v, 26)
        if power > 0:
            est = max(1, int(atk * power * hits))
            return f"{text} (~{est} dmg)"
        return text
    return ""


def _restraints(player: Any) -> str:
    raw = getattr(player, "restraints", None)
    if raw is None:
        raw = getattr(player, "bindings", None)
    if not raw:
        return ""
    try:
        items = list(raw.items()) if isinstance(raw, dict) else list(raw)
    except TypeError:
        return ""
    parts: list[str] = []
    for it in items:
        if isinstance(it, tuple) and len(it) == 2:
            name = _label(it[0], 16)
            dur = float(it[1]) if isinstance(it[1], (int, float)) and not isinstance(it[1], bool) \
                else _num(it[1], ("durability", "dur", "hp"))
        else:
            name, dur = _label(it, 16), _num(it, ("durability", "dur", "hp"))
        parts.append(f"{name} {dur:g}" if dur is not None else name)
    return ", ".join(parts)


def _stage_no(state: Any) -> int:
    return int(_num(state, ("stage",), 1.0) or 1)


def _looks_like_state(obj: Any) -> bool:
    attrs = ("players", "enemies", "inventory", "gold", "stage", "party_alive", "run_complete")
    return obj is not None and all(hasattr(obj, a) for a in attrs)


def _key_name(key: int) -> str:
    """Convert Pygame key codes into the string names used by combat/QTE logic."""
    try:
        name = pygame.key.name(key).strip().lower()
    except (AttributeError, TypeError, ValueError, pygame.error):
        return str(key).lower()
    # Normalize keypad numbers: "[1]" -> "1", "kp 1" -> "1", "keypad 1" -> "1"
    if name.startswith("[") and name.endswith("]") and name[1:-1].isdecimal():
        return name[1:-1]
    if name.startswith("kp ") and name[3:].isdecimal():
        return name[3:]
    if name.startswith("keypad ") and name[7:].isdecimal():
        return name[7:]
    # Pygame reports keypad Enter as 'enter' on some platforms; the combat API
    # uses 'return' for both regular and keypad Enter.
    return "return" if name in {"enter", "kp enter", "keypad enter"} else name


def _slot_key(x: Any) -> Optional[int]:
    """Normalize a save-slot identifier to the 1-based GameApp slot index."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if x >= 1 else None
    if isinstance(x, str):
        label = x.strip().lower()
        if "auto" in label:
            return AUTOSAVE_SLOT
        digits = "".join(ch for ch in label if ch.isdigit())
        if not digits:
            return None
        number = int(digits)
        # The public names Slot 1..Slot 3 are stored after the autosave entry.
        if label.startswith("slot") and number > 0:
            return number + 1
        return number if number >= 1 else None
    return None


def _meta_text(meta: Any) -> str:
    if isinstance(meta, str):
        return meta[:36]
    if not isinstance(meta, dict):
        summary = getattr(meta, "summary", None)
        if isinstance(summary, dict):
            meta = summary
    parts: list[str] = []
    for k in ("stage", "gold", "difficulty", "difficulty_name"):
        v = meta.get(k) if isinstance(meta, dict) else getattr(meta, k, None)
        if v not in (None, ""):
            parts.append(f"{k.split('_')[0].title()} {v}")
    return "  ".join(parts)


def _normalize_slots(raw: Any) -> tuple[dict[int, str], bool]:
    """Normalize slot listing formats and only mark loadable saves as occupied.

    SaveManager.list_slots() returns SlotInfo objects for *every* slot, including
    empty and corrupt slots. Treating every returned object as a save made Continue
    permanently enabled and made empty slots appear occupied.
    """
    info: dict[int, str] = {}
    if raw is None:
        return info, False
    try:
        entries = list(raw.items()) if isinstance(raw, dict) else list(raw)
    except TypeError:
        return info, False

    recognized = not entries  # an empty listing is still a valid, authoritative result
    for entry in entries:
        key: Optional[int] = None
        meta: Any = ""
        if isinstance(raw, dict):
            raw_key, meta = entry
            key = _slot_key(raw_key)
        elif isinstance(entry, (tuple, list)) and entry:
            key = _slot_key(entry[0])
            meta = entry[1] if len(entry) > 1 else ""
        elif isinstance(entry, dict):
            key = _slot_key(entry.get("index", entry.get("slot", entry.get("id"))))
            meta = entry
        elif isinstance(entry, (int, str)):
            key = _slot_key(entry)
        else:
            # SlotInfo-like objects expose the numeric index independently from
            # the filename (e.g. 'autosave', 'slot1', ...); prefer that index.
            index = getattr(entry, "index", None)
            key = _slot_key(index) if index is not None else _slot_key(getattr(entry, "slot", None))
            meta = entry

        if key is None:
            continue
        recognized = True

        # SlotInfo exposes is_valid/is_empty. Skip empty, corrupt and unsupported
        # saves so Continue only points at a genuinely loadable save. Generic
        # external listing formats without a status field retain presence-based behavior.
        valid = getattr(meta, "is_valid", None)
        if valid is False:
            continue
        if isinstance(meta, dict):
            status = meta.get("status")
            status = getattr(status, "value", status)
            if isinstance(status, str) and status.lower() in {"empty", "corrupt", "unsupported", "invalid"}:
                continue
            if meta.get("is_valid") is False or meta.get("is_empty") is True:
                continue
        if meta is None:
            continue
        info[key] = _meta_text(meta)
    return info, recognized


def _difficulty_names() -> list[str]:
    try:
        import core.config as cfg
    except ImportError:
        return list(DEFAULT_DIFFICULTIES)
    for attr in ("DIFFICULTIES", "DIFFICULTY_NAMES", "DIFFICULTY"):
        raw = getattr(cfg, attr, None)
        try:
            names = list(raw) if raw is not None else []
        except TypeError:
            continue
        if names and all(isinstance(n, str) for n in names):
            return names
    return list(DEFAULT_DIFFICULTIES)


def _kind_for(player: Any, idx: int) -> Any:
    pclass = None
    for n in ("pclass", "player_class", "klass", "cls", "char_class"):
        pclass = getattr(player, n, None)
        if pclass is not None:
            break
    name = str(getattr(pclass, "name", pclass)).upper()
    if "ANGEL" in name:
        return CharacterKind.FALLEN_ANGEL
    if "WITCH" in name:
        return CharacterKind.WITCH
    if "WARRIOR" in name:
        return CharacterKind.WARRIOR
    if "TANK" in name:
        return CharacterKind.TANK
    if "ROGUE" in name:
        return CharacterKind.ROGUE
    if "KITSUNE" in name:
        return CharacterKind.KITSUNE
    if "VAMPIRE" in name:
        return CharacterKind.VAMPIRE
    if "DRAGONKIN" in name:
        return CharacterKind.DRAGONKIN
    kinds = (CharacterKind.WARRIOR, CharacterKind.TANK, CharacterKind.ROGUE,
             CharacterKind.WITCH, CharacterKind.FALLEN_ANGEL, CharacterKind.KITSUNE,
             CharacterKind.VAMPIRE, CharacterKind.DRAGONKIN)
    return kinds[idx % len(kinds)]


def _target_index(combat: Any, enemies: Sequence[Any]) -> Optional[int]:
    if _pname(combat.phase) != "TARGET":
        return None
    for attr in ("target_idx", "target_index", "target_cursor", "cursor", "target"):
        v = getattr(combat, attr, None)
        if isinstance(v, int) and not isinstance(v, bool):
            if 0 <= v < len(enemies):
                return v
        elif v is not None:
            for i, e in enumerate(enemies):
                if e is v:
                    return i
    return None


def _nav(key: int) -> int:
    if key in (pygame.K_UP, pygame.K_w):
        return -1
    if key in (pygame.K_DOWN, pygame.K_s):
        return 1
    return 0


def _confirm(key: int) -> bool:
    return key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


class _SilentAudio:
    """Drop-in used when the mixer cannot start; every call is a no-op."""

    def __getattr__(self, name: str) -> Any:
        return lambda *a, **k: None


# ======================================================================================================
#  small UI models
# ======================================================================================================
@dataclass
class MenuItem:
    tag: str
    label: str
    enabled: bool = True


class MenuList:
    def __init__(self, items: Sequence[MenuItem]) -> None:
        self.items = list(items)
        self.idx = 0
        self.move(0)

    def move(self, delta: int = 0) -> None:
        n = len(self.items)
        if not n:
            self.idx = 0
            return
        step = -1 if delta < 0 else 1
        idx = (self.idx + delta) % n
        for _ in range(n):
            if self.items[idx].enabled:
                break
            idx = (idx + step) % n
        self.idx = idx

    @property
    def selected(self) -> Optional[MenuItem]:
        if self.items and self.items[self.idx].enabled:
            return self.items[self.idx]
        return None


class PartySetup:
    """Pure UI model for the 1-3 hero selection screen."""

    def __init__(self, class_count: int) -> None:
        self.class_count = max(1, class_count)
        self.size = 1
        self.row = 0
        self.class_idx = [i % self.class_count for i in range(MAX_PARTY)]
        self.names = [""] * MAX_PARTY

    @property
    def rows(self) -> int:
        return self.size + 2          # size row, one row per hero, confirm row

    def configs(self, classes: Sequence[Any]) -> list[Any]:
        out: list[Any] = []
        seen: set[str] = set()
        for i in range(self.size):
            pclass = classes[self.class_idx[i] % len(classes)]
            base = self.names[i].strip() or _label(pclass, NAME_MAX)
            name, n = base, 2
            while name.lower() in seen:
                name, n = f"{base} {n}", n + 1
            seen.add(name.lower())
            out.append(PlayerConfig(name, pclass))
        return out


@dataclass
class Popup:
    text: str
    color: Color
    ttl: float
    age: float = 0.0


# ======================================================================================================
#  drawing helpers
# ======================================================================================================
def draw_text(surf: pygame.Surface, font: pygame.font.Font, text: str, pos: tuple[float, float],
              color: Color = BONE, anchor: str = "topleft", shadow: bool = True, alpha: int = 255) -> pygame.Rect:
    img = font.render(text, True, color)
    if alpha < 255:
        img.set_alpha(alpha)
    rect = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    if shadow:
        sh = font.render(text, True, (0, 0, 0))
        sh.set_alpha(min(alpha, 200))
        surf.blit(sh, rect.move(2, 2))
    surf.blit(img, rect)
    return rect


def draw_bar(surf: pygame.Surface, rect: pygame.Rect, ratio: float, color: Color,
             back: Color = (22, 14, 34), border: Color = (92, 70, 132)) -> None:
    ratio = clamp(ratio, 0.0, 1.0)
    pygame.draw.rect(surf, back, rect, border_radius=4)
    if ratio > 0.0:
        fill = pygame.Rect(rect.x + 1, rect.y + 1, max(2, int((rect.width - 2) * ratio)), rect.height - 2)
        pygame.draw.rect(surf, color, fill, border_radius=3)
        shine = pygame.Rect(fill.x, fill.y, fill.width, max(1, fill.height // 3))
        pygame.draw.rect(surf, mix(color, (255, 255, 255), 0.3), shine, border_radius=3)
    pygame.draw.rect(surf, border, rect, 1, border_radius=4)


def panel(surf: pygame.Surface, rect: pygame.Rect, accent: Color = (92, 70, 132), alpha: int = 190) -> None:
    box = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(box, (12, 8, 22, alpha), box.get_rect(), border_radius=9)
    pygame.draw.rect(box, (*accent, 235), box.get_rect(), 1, border_radius=9)
    surf.blit(box, rect.topleft)


def add_glow(surf: pygame.Surface, x: float, y: float, radius: float, color: Color, level: int = 5) -> None:
    rad = int(clamp(radius, 6, 200)) // 2 * 2
    surf.blit(glow_add(rad, color, level), (int(x) - rad, int(y) - rad), special_flags=pygame.BLEND_RGB_ADD)


def fit_text(font: pygame.font.Font, text: str, width: int) -> str:
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "..")[0] > width:
        text = text[:-1]
    return text + ".."


def wrap_text(font: pygame.font.Font, text: str, width: int, max_lines: int = 3) -> list[str]:
    """Wrap UI text by words, clipping with an ellipsis only when the requested line cap is hit."""
    if width <= 0 or max_lines <= 0:
        return []
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if font.size(trial)[0] <= width:
            current = trial
        elif current:
            lines.append(current)
            current = word if font.size(word)[0] <= width else fit_text(font, word, width)
        else:
            current = fit_text(font, word, width)
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit_text(font, lines[-1].rstrip(" .") + "...", width)
    return lines


def _shop_display_rows(shop: Any) -> list[tuple[Any, Optional[float], int, bool]]:
    """Return real Shop stock rows plus its Proceed row. Shop.rows is a count, not a sequence."""
    stock = getattr(shop, "stock", ()) or ()
    if not isinstance(stock, (list, tuple)):
        stock = ()
    remaining_fn = getattr(shop, "remaining", None)
    result: list[tuple[Any, Optional[float], int, bool]] = []
    for index, pair in enumerate(stock):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        item, raw_price = pair
        price = float(raw_price) if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool) else None
        try:
            remaining = int(remaining_fn(index)) if callable(remaining_fn) else -1
        except (TypeError, ValueError, IndexError, KeyError):
            remaining = -1
        result.append((item, price, max(-1, remaining), False))
    result.append((None, None, 0, True))
    return result


def _active_restraint_details(player: Any) -> list[tuple[str, str]]:
    """Describe every active gameplay restraint without depending on its container's truthiness."""
    raw = getattr(player, "restraints", None)
    if raw is None:
        raw = getattr(player, "bindings", None)
    if raw is None:
        return []
    try:
        members = list(raw.keys()) if isinstance(raw, dict) else list(raw)
    except TypeError:
        return []
    details: list[tuple[str, str]] = []
    known: set[Any] = set()
    for restraint in PlayerRestraint:
        try:
            active = restraint in raw
        except TypeError:
            active = restraint in members
        if active:
            details.append((str(restraint.label), str(restraint.desc)))
            known.add(restraint)
    for member in members:
        if member in known:
            continue
        if isinstance(member, tuple) and len(member) == 2:
            name, value = member
            label = _label(name, 32)
            desc = getattr(value, "desc", getattr(value, "description", ""))
        else:
            label = str(getattr(member, "label", "") or _label(member, 32))
            desc = getattr(member, "desc", getattr(member, "description", ""))
        details.append((label, str(desc or "No description available.")))
    return details


# ======================================================================================================
#  painter: read-only views of the game objects
# ======================================================================================================
class Painter:
    intent_hidden = False       # set each frame from CombatSystem.intent_hidden (Sensory Deprivation)

    def __init__(self, fonts: dict[str, pygame.font.Font], renderer: Any) -> None:
        self.f = fonts
        self.renderer = renderer
        self.veil = pygame.Surface((W, H), pygame.SRCALPHA)
        self.veil.fill((6, 3, 12, 175))
        self.dim = pygame.Surface((W, H), pygame.SRCALPHA)
        self.dim.fill((6, 3, 12, 120))

    @property
    def t(self) -> float:
        return float(getattr(self.renderer, "time", 0.0))

    # ---- generic ----------------------------------------------------------------------------------
    def heading(self, surf: pygame.Surface, text: str, sub: str = "", color: Color = BONE, y: int = 56) -> None:
        draw_text(surf, self.f["huge"], text, (W // 2, y), color, "midtop")
        if sub:
            draw_text(surf, self.f["small"], sub, (W // 2, y + 80), MUTED, "midtop")

    def hint(self, surf: pygame.Surface, text: str) -> None:
        pulse = 0.55 + 0.45 * math.sin(self.t * 3.0)
        draw_text(surf, self.f["small"], text, (W // 2, H - 22), mix(MUTED, (255, 255, 255), 0.3 * pulse), "midbottom")

    def menu(self, surf: pygame.Surface, menu: MenuList, cx: int, top: int, width: int = 380, row_h: int = 48) -> None:
        panel(surf, pygame.Rect(cx - width // 2 - 14, top - 12, width + 28, row_h * len(menu.items) + 14))
        for i, item in enumerate(menu.items):
            sel = i == menu.idx and item.enabled
            col = GOLD if sel else (BONE if item.enabled else DIM)
            r = pygame.Rect(cx - width // 2, top + i * row_h, width, row_h - 6)
            if sel:
                panel(surf, r, accent=RUNE_PURPLE, alpha=230)
            draw_text(surf, self.f["mid"], fit_text(self.f["mid"], item.label, width - 16), r.center, col, "center")

    def top_bar(self, surf: pygame.Surface, state: Any, center: str) -> None:
        panel(surf, pygame.Rect(12, 8, W - 24, 36), alpha=210)
        diff = str(getattr(state, "difficulty_name", "") or "")
        draw_text(surf, self.f["mid"], f"Floor {_stage_no(state)}   {diff}", (28, 26), BONE, "midleft")
        draw_text(surf, self.f["mid"], center, (W // 2, 26), RUNE_PURPLE, "center")
        draw_text(surf, self.f["mid"], f"Gold {int(_num(state, ('gold',), 0.0) or 0)}", (W - 28, 26), GOLD, "midright")

    def popups(self, surf: pygame.Surface, popups: Sequence[Popup]) -> None:
        y = 52
        for p in popups:
            fade = clamp(min(1.0, (p.ttl - p.age) / 0.4, p.age / 0.12 + 0.2), 0.0, 1.0)
            r = pygame.Rect(W - 392, y, 380, 30)
            panel(surf, r, accent=p.color, alpha=int(200 * fade))
            draw_text(surf, self.f["small"], fit_text(self.f["small"], p.text, r.width - 16), (r.x + 10, r.centery),
                      p.color, "midleft", alpha=int(255 * fade))
            y += 36

    def overlay(self, surf: pygame.Surface, title: str, color: Color = BONE) -> None:
        surf.blit(self.veil, (0, 0))
        draw_text(surf, self.f["huge"], title, (W // 2, 120), color, "midtop")

    # ---- setup screens ----------------------------------------------------------------------------
    def setup(self, surf: pygame.Surface, setup: PartySetup, classes: Sequence[Any]) -> None:
        surf.blit(self.dim, (0, 0))
        self.heading(surf, "ASSEMBLE THE PARTY", "One to three heroes descend together")
        panel(surf, pygame.Rect(230, 190, 820, 90 + 56 * (setup.size + 1)))
        rows: list[tuple[str, str]] = [("Party size", f"<  {setup.size}  >")]
        blink = "_" if int(self.t * 2) % 2 == 0 else " "
        for i in range(setup.size):
            focus = setup.row == i + 1
            name = setup.names[i] + (blink if focus else "")
            if not setup.names[i] and not focus:
                name = _label(classes[setup.class_idx[i] % len(classes)], NAME_MAX)
            rows.append((f"Hero {i + 1}:  {name}", f"<  {_label(classes[setup.class_idx[i] % len(classes)], 16)}  >"))
        for i, (left, right) in enumerate(rows):
            y = 210 + i * 56
            if setup.row == i:
                panel(surf, pygame.Rect(244, y - 6, 792, 48), accent=RUNE_PURPLE, alpha=235)
            col = GOLD if setup.row == i else BONE
            draw_text(surf, self.f["mid"], left, (268, y + 18), col, "midleft")
            draw_text(surf, self.f["mid"], right, (1012, y + 18), col, "midright")
        y = 210 + len(rows) * 56
        confirm = setup.row == setup.rows - 1
        if confirm:
            panel(surf, pygame.Rect(244, y - 6, 792, 48), accent=GOLD, alpha=235)
        draw_text(surf, self.f["mid"], "Confirm party", (W // 2, y + 18), GOLD if confirm else BONE, "center")
        self.hint(surf, "[UP/DOWN] row   [LEFT/RIGHT] size / class   [type] name   [ENTER] next   [ESC] back")
        self._r2_setup_portrait(surf, setup, classes)

    def _r2_setup_portrait(self, surf: pygame.Surface, setup: PartySetup, classes: Sequence[Any]) -> None:
        """Large class portrait for the hero row being edited (right margin); skipped without art."""
        assets = getattr(getattr(self, "renderer", None), "assets", None)
        if assets is None or not assets.enabled or not classes:
            return
        hero = max(0, min(setup.size - 1, setup.row - 1))
        idx = setup.class_idx[hero] % len(classes)
        try:
            class _Probe:
                pclass = classes[idx]
            key = _kind_for(_Probe(), idx).value
            img = assets.portrait(key)
            if img is None:
                return
            w, h = img.get_size()
            box_w = 200
            box_h = min(300, int(box_w * h / max(1, w)))
            pic = assets.portrait(key, (box_w, box_h))
            if pic is None:
                return
            r = pygame.Rect(1062, 200, box_w, box_h)
            surf.blit(pic, r.topleft)
            pygame.draw.rect(surf, GOLD, r, 2)
            draw_text(surf, self.f["small"], _label(classes[idx], 16), (r.centerx, r.bottom + 8), GOLD, "midtop")
        except (pygame.error, AttributeError, ValueError, TypeError) as exc:
            assets.disable(f"setup portrait failed: {exc}")

    # ---- run screens ------------------------------------------------------------------------------
    def cutin(self, surf: pygame.Surface, assets: Any, key: str, name: str, age: float, reduced: bool = False) -> bool:
        """Turn-start cut-in: tinted band, the hero's anime bust sliding in, her name. Returns False if skipped."""
        offset, alpha = cutin_motion(age, reduced)
        if alpha <= 0 or assets is None or not assets.enabled:
            return False
        try:
            img = assets.model(key, 380)
            if img is None:
                return False
            r, g, b = MODEL_GLOW.get(key, (200, 160, 255))
            band = pygame.Surface((W, 220), pygame.SRCALPHA)
            pygame.draw.polygon(band, (r // 3, g // 3, b // 3, int(190 * alpha / 255)), [(0, 40), (W, 0), (W, 170), (0, 220)])
            pygame.draw.polygon(band, (r, g, b, int(230 * alpha / 255)), [(0, 40), (W, 0), (W, 5), (0, 45)])
            pygame.draw.polygon(band, (r, g, b, int(230 * alpha / 255)), [(0, 215), (W, 165), (W, 170), (0, 220)])
            surf.blit(band, (0, 250))
            pic = img
            if alpha < 255:
                pic = img.copy()
                pic.set_alpha(alpha)
            surf.blit(pic, (int(150 + offset), 475 - img.get_height()))
            tx = int(620 + offset * 0.5)
            draw_text(surf, self.f["small"], "YOUR TURN", (tx, 318), mix(MUTED, (r, g, b), 0.6))
            draw_text(surf, self.f["huge"], name, (tx, 340), BONE)
            return True
        except (pygame.error, AttributeError, ValueError, TypeError) as exc:
            assets.disable(f"cut-in draw failed: {exc}")
            return False

    def _r2_face(self, surf: pygame.Surface, player: Any, index: int, box: pygame.Rect, active: bool) -> None:
        """Anime face thumbnail on a party card; silently skipped when the art is unavailable."""
        assets = getattr(getattr(self, "renderer", None), "assets", None)
        if assets is None or not assets.enabled:
            return
        try:
            face = assets.portrait(_kind_for(player, index).value, (box.w, box.h), face=True)
            if face is not None:
                surf.blit(face, box.topleft)
                pygame.draw.rect(surf, GOLD if active else (92, 70, 132), box, 1)
        except (pygame.error, AttributeError, ValueError) as exc:
            assets.disable(f"portrait draw failed: {exc}")

    def party_cards(self, surf: pygame.Surface, players: Sequence[Any], active: Any) -> None:
        for i, p in enumerate(list(players)[:MAX_PARTY]):
            r = pygame.Rect(12 + i * 258, 612, 250, 98)
            is_active = p is active or (isinstance(active, int) and not isinstance(active, bool) and active == i)
            panel(surf, r, accent=GOLD if is_active else (92, 70, 132), alpha=215)
            self._r2_face(surf, p, i, pygame.Rect(r.right - 50, r.y + 26, 42, 42), is_active)
            draw_text(surf, self.f["small"], fit_text(self.f["small"], _label(p, 16), 150), (r.x + 8, r.y + 5), BONE)
            lvl = _num(p, ("level", "lvl"))
            if lvl is not None:
                draw_text(surf, self.f["tiny"], f"Lv.{lvl:.0f}", (r.right - 8, r.y + 7), MUTED, "topright")
            y = r.y + 24
            for tag, cur, mx, col in (("HP", ("hp",), ("max_hp",), BLOOD),
                                      ("MP", ("mana", "mp"), ("max_mana", "max_mp"), MANA_BLUE),
                                      ("STA", ("stamina", "sta"), ("max_stamina", "max_sta"), STAMINA_GOLD)):
                c, m = _num(p, cur), _num(p, mx)
                if c is None or m is None or m <= 0:
                    continue
                draw_bar(surf, pygame.Rect(r.x + 8, y, 118, 10), c / m, col)
                draw_text(surf, self.f["tiny"], f"{tag} {c:.0f}/{m:.0f}", (r.x + 134, y - 2), BONE, shadow=False)
                y += 15
            # Class resources are part of tactical state, not hidden in ability descriptions.
            # Use the entity's single authoritative class-bar definition; rendering only reads it.
            bars = list(p.class_bars()) if callable(getattr(p, "class_bars", None)) else []
            if bars:
                resource = bars[0]
                maximum = max(1.0, float(resource.maximum))
                value = max(0.0, min(maximum, float(resource.value)))
                draw_bar(surf, pygame.Rect(r.x + 8, y + 1, 118, 7), value / maximum, tuple(resource.color))
                draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"],
                          f"{resource.label} {value:.0f}/{maximum:.0f}", 106),
                          (r.x + 134, y - 2), tuple(resource.color), shadow=False)
            chips = _restraints(p)
            if chips:
                draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], "Bound: " + chips, r.width - 16),
                          (r.x + 8, r.bottom - 13), RUNE_PURPLE, shadow=False)
            if not _alive(p):
                shade = pygame.Surface(r.size, pygame.SRCALPHA)
                shade.fill((0, 0, 0, 150))
                surf.blit(shade, r.topleft)
                draw_text(surf, self.f["mid"], "FALLEN", r.center, BLOOD, "center")

    def enemy_field(self, surf: pygame.Surface, enemies: Sequence[Any], target: Optional[int]) -> None:
        shown = list(enemies)[:8]
        n = len(shown)
        if not n:
            return
        cols = n if n <= 4 else math.ceil(n / 2)
        two_rows = n > 4
        x0, x1 = 690.0, 1262.0
        col_w = (x1 - x0) / cols
        scale = 1.05 if two_rows else (1.60 if n == 1 else 1.50 if n == 2 else 1.38)
        for k, e in enumerate(shown):
            if not _alive(e):
                continue
            r, c = (k // cols, k % cols)
            cx = x0 + col_w * (c + 0.5)
            # Keep sprites above the bottom-right command panel (y=540..710).
            feet = (372.0, 530.0)[r] if two_rows else 530.0
            hot = target == k
            motion = getattr(self, "combat_vfx", None)
            uid = int(getattr(e, "uid", 0) or 0)
            remaining = motion.lunges.get(uid, 0.0) if motion is not None and uid else 0.0
            dx = motion.lunge_offset(uid, -1) if motion is not None and uid else 0
            hurt = motion.hit_strength(uid) if motion is not None and uid else 0.0
            cx_draw = cx + dx + (math.sin(self.t * 78 + k) * 4 * hurt if hurt else 0)
            feet_draw = feet - (8 * math.sin(math.pi * (1 - remaining / 0.28)) if remaining > 0 else 0)
            arch_obj = getattr(e, "arch", None)
            arch = "boss" if bool(getattr(e, "boss", False)) else str(getattr(arch_obj, "key", "void") or "void")
            actor_scale = scale * (1.08 if arch == "boss" else 1.0)
            self._enemy_sprite(surf, cx_draw, feet_draw, actor_scale, k, hot, archetype=arch, phase=getattr(e, "phase", 1))
            if motion is not None and uid:
                motion.draw_actor_effect(surf, uid, (cx_draw, feet_draw - 68 * actor_scale), 24 + 14 * actor_scale)
            if remaining > 0:
                pr = 1.0 - remaining / 0.28
                pygame.draw.arc(surf, (255, 110, 120), pygame.Rect(int(cx_draw-42*actor_scale), int(feet_draw-116*actor_scale), int(90*actor_scale), int(62*actor_scale)),
                                0.2 + pr * 0.8, 2.5 + pr * 0.8, max(2, int(3*actor_scale)))
            card_cap = 280 if n == 1 else (220 if n == 2 else 188)
            self._enemy_card(surf, e, cx_draw, feet - 132 * actor_scale - 8,
                             int(min(card_cap, col_w - 8)), hot)

    def _enemy_sprite(self, surf: pygame.Surface, cx: float, feet: float, scale: float, i: int, hot: bool,
                      archetype: str = "void", phase: Any = 1) -> None:
        """Archetype-specific enemy silhouettes with distinct anatomy, gear, and palette."""
        bob = math.sin(self.t * 2.0 + i) * 4.0
        sc = scale
        top, bot = feet - 132 * sc + bob, feet + bob
        col = {"beast": (214, 111, 65), "void": (155, 89, 226), "nature": (91, 181, 101),
               "construct": (165, 177, 198), "cultist": (223, 176, 79), "boss": (224, 55, 91),
               "hunter": (60, 180, 200), "undead": (120, 150, 130), "cinder": (255, 90, 40)}.get(archetype, (159, 88, 209))
        add_glow(surf, cx, top + 62 * sc, 68 * sc, BLOOD if hot else col, 5 if hot else 4)
        def pts(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
            return [(int(cx + x * sc), int(feet + y * sc + bob)) for x, y in points]
        def poly(points: list[tuple[float, float]], fill: Color, edge: Optional[Color] = None, width: int = 2) -> None:
            pp = pts(points)
            pygame.draw.polygon(surf, fill, pp)
            if edge:
                pygame.draw.polygon(surf, edge, pp, max(1, int(width * sc)))
        dark = (24, 14, 36)
        mid = mix(dark, col, 0.45)
        hi = mix(col, (255, 240, 220), 0.35)
        if archetype == "beast":
            # Four-legged cinder hound: shoulders, skull, ears, jaw, long claws and tail.
            poly([(-44,-42),(-28,-70),(4,-77),(30,-60),(48,-36),(33,-21),(-35,-20)], mid, hi, 2)
            poly([(15,-71),(35,-96),(51,-91),(49,-68),(65,-57),(56,-45),(28,-49)], dark, col, 2)
            poly([(25,-91),(20,-111),(36,-98),(40,-84)], col, hi, 1)
            poly([(48,-87),(61,-102),(59,-79)], col, hi, 1)
            poly([(-38,-39),(-54,-18),(-62,-4),(-52,-1),(-39,-17),(-23,-24)], dark, col, 2)
            poly([(20,-31),(31,-11),(37,-3),(28,-1),(16,-16)], dark, hi, 1)
            poly([(-10,-29),(-5,-10),(-1,-1),(-12,-1),(-18,-15)], dark, hi, 1)
            pygame.draw.circle(surf, (255, 108, 57), (int(cx+42*sc), int(feet-79*sc+bob)), max(2,int(4*sc)))
            pygame.draw.circle(surf, (255, 108, 57), (int(cx+27*sc), int(feet-80*sc+bob)), max(2,int(3*sc)))
            poly([(-61,-7),(-53,-13),(-50,-3)], (230,218,197), None, 1)
            poly([(-14,-2),(-8,-14),(-4,-2)], (230,218,197), None, 1)
        elif archetype in ("construct",):
            # Sentinel: square iron cuirass, crown-spikes, thick legs, tower shield and blade.
            poly([(-24,-124),(-37,-111),(-33,-57),(-21,-38),(22,-38),(35,-57),(38,-111),(23,-124)], (69,79,99), (221,197,146), 3)
            poly([(-24,-116),(0,-130),(24,-116),(17,-82),(0,-72),(-17,-82)], (133,141,157), (239,216,160), 2)
            poly([(-47,-116),(-64,-101),(-59,-65),(-43,-52),(-31,-76),(-33,-101)], (58,80,113), (201,203,215), 2)
            poly([(42,-110),(49,-102),(80,-38),(72,-34),(34,-95)], (174,185,201), (238,226,190), 2)
            for sx in (-19,-6,7,20): poly([(sx,-124),(sx-4,-139),(sx+4,-134)], (128,139,157), (225,210,171), 1)
            pygame.draw.circle(surf, (109,213,255), (int(cx), int(feet-100*sc+bob)), max(3,int(6*sc)))
            poly([(-21,-39),(-17,-11),(-5,-2),(4,-2),(6,-26),(10,-39)], dark, hi, 1)
            poly([(7,-39),(13,-13),(25,-3),(35,-3),(25,-33),(20,-39)], dark, hi, 1)
        elif archetype == "nature":
            # Thornwraith: bark torso, branching crown, root limbs, glowing seed core.
            poly([(-25,-112),(-17,-131),(0,-120),(18,-136),(28,-111),(19,-76),(9,-54),(18,-21),(7,-3),(-11,-3),(-19,-27),(-11,-57),(-21,-76)], (35,80,43), (133,202,112), 2)
            poly([(-20,-121),(-43,-145),(-39,-120),(-57,-112),(-33,-103)], (56,106,48), (156,215,124), 2)
            poly([(19,-122),(37,-150),(39,-123),(57,-116),(35,-105)], (56,106,48), (156,215,124), 2)
            poly([(-25,-78),(-46,-50),(-39,-41),(-17,-65)], (38,76,40), (139,188,104), 1)
            poly([(24,-78),(47,-50),(40,-41),(16,-65)], (38,76,40), (139,188,104), 1)
            pygame.draw.circle(surf, (236,218,112), (int(cx), int(feet-91*sc+bob)), max(3,int(7*sc)))
            for sx in (-13,12): pygame.draw.circle(surf, (230,115,91), (int(cx+sx*sc), int(feet-109*sc+bob)), max(2,int(3*sc)))
            poly([(-15,-26),(-25,-10),(-31,-1),(-19,-1),(-8,-18)], (39,77,38), hi, 1)
            poly([(14,-26),(27,-8),(35,-1),(21,-1),(9,-18)], (39,77,38), hi, 1)
        elif archetype == "cultist":
            # Acolyte with hood, layered ceremonial robe and a crooked rune staff.
            poly([(-21,-116),(-35,-83),(-45,-10),(-28,-1),(29,-1),(45,-10),(35,-83),(21,-116)], (69,38,67), (226,180,96), 2)
            poly([(-23,-130),(0,-151),(24,-129),(20,-104),(-20,-104)], (32,22,44), (237,191,104), 2)
            pygame.draw.circle(surf, (242,182,74), (int(cx), int(feet-116*sc+bob)), max(2,int(5*sc)))
            poly([(27,-95),(43,-78),(55,-26),(49,-23),(33,-75)], (117,81,45), (232,202,128), 2)
            pygame.draw.circle(surf, (255,100,72), (int(cx+53*sc), int(feet-126*sc+bob)), max(2,int(4*sc)))
            poly([(-14,-1),(-8,-16),(0,-8),(6,-1)], dark, hi, 1)
        elif archetype == "boss":
            # Winged Seraph boss used for elite encounters and title showcase.
            poly([(-12,-126),(-30,-119),(-25,-70),(-19,-28),(0,-6),(18,-28),(25,-70),(30,-119),(12,-126)], (59,23,55), (251,95,130), 2)
            for side in (-1,1):
                poly([(side*15,-103),(side*53,-136),(side*96,-145),(side*78,-112),(side*52,-96),(side*92,-82),(side*47,-78),(side*17,-88)], (46,20,49), (217,63,110), 2)
                poly([(side*24,-102),(side*64,-124),(side*89,-126)], (127,36,75), (255,147,181), 1)
            pygame.draw.circle(surf, (255,205,112), (int(cx), int(feet-150*sc+bob)), max(4,int(12*sc)), max(1,int(3*sc)))
            pygame.draw.circle(surf, (255,92,124), (int(cx), int(feet-77*sc+bob)), max(3,int(7*sc)))
            poly([(-12,-153),(-4,-171),(0,-155),(5,-173),(13,-152)], (237,191,128), (255,235,183), 2)
            poly([(-35,-25),(-58,-9),(-45,-2),(-22,-12)], (33,17,39), col, 1)
            poly([(35,-25),(58,-9),(45,-2),(22,-12)], (33,17,39), col, 1)
        elif archetype == "hunter":
            # Swift assassin silhouette: arched hooded cowl, swept dual blades, split shadow cloak.
            poly([(-18,-118),(-28,-90),(-32,-45),(-15,-12),(15,-12),(32,-45),(28,-90),(18,-118)], (20,44,52), (72,192,208), 2)
            poly([(-16,-128),(0,-144),(16,-128),(12,-102),(-12,-102)], (14,28,34), (96,218,235), 2)
            poly([(-40,-95),(-55,-40),(-42,-35),(-24,-75)], (16,36,44), (72,192,208), 2)
            poly([(40,-95),(55,-40),(42,-35),(24,-75)], (16,36,44), (72,192,208), 2)
            pygame.draw.circle(surf, (110,235,255), (int(cx-6*sc), int(feet-114*sc+bob)), max(1,int(3*sc)))
            pygame.draw.circle(surf, (110,235,255), (int(cx+6*sc), int(feet-114*sc+bob)), max(1,int(3*sc)))
            poly([(-12,-12),(-6,-1),(0,-8),(6,-1),(12,-12)], dark, hi, 1)
        elif archetype == "undead":
            # Charnel Ghoul: hunched necrotic silhouette, exposed bone ribcage, jagged burial shroud.
            poly([(-22,-105),(-34,-78),(-28,-36),(-16,-4),(16,-4),(28,-36),(34,-78),(22,-105)], (38,45,40), (145,175,152), 2)
            poly([(-14,-118),(0,-132),(14,-118),(10,-98),(-10,-98)], (24,30,26), (168,198,175), 1)
            for ry in (-68, -52, -36):
                poly([(-18,ry),(0,ry+6),(18,ry)], (210,225,215), None, 1)
            pygame.draw.circle(surf, (155,255,185), (int(cx-5*sc), int(feet-108*sc+bob)), max(2,int(3*sc)))
            pygame.draw.circle(surf, (155,255,185), (int(cx+5*sc), int(feet-108*sc+bob)), max(2,int(3*sc)))
        elif archetype == "cinder":
            # Pyre elemental: flaring volcanic core, floating obsidian shards, roaring ember crown.
            poly([(-20,-96),(-32,-68),(-24,-30),(0,-12),(24,-30),(32,-68),(20,-96)], (65,22,12), (255,120,45), 2)
            poly([(-16,-110),(0,-138),(16,-110),(8,-88),(-8,-88)], (85,28,14), (255,165,60), 2)
            for side in (-1,1):
                poly([(side*22,-80),(side*38,-105),(side*30,-62)], (120,38,15), (255,180,70), 1)
            pygame.draw.circle(surf, (255,220,90), (int(cx), int(feet-75*sc+bob)), max(3,int(7*sc)))
            pygame.draw.circle(surf, (255,90,30), (int(cx), int(feet-100*sc+bob)), max(2,int(5*sc)))
        else:  # void creature: levitating mask with tendrils and orbiting runes
            poly([(-30,-113),(-26,-89),(-38,-61),(-24,-45),(0,-32),(24,-45),(38,-61),(26,-89),(30,-113),(0,-132)], (35,24,59), (191,138,255), 2)
            poly([(-24,-110),(0,-126),(24,-110),(12,-86),(0,-79),(-12,-86)], (76,42,102), (230,200,255), 1)
            poly([(-18,-104),(-11,-98),(-18,-93)], (255,90,201), None, 1)
            poly([(18,-104),(11,-98),(18,-93)], (255,90,201), None, 1)
            for side in (-1,1):
                poly([(side*24,-68),(side*43,-44),(side*39,-15),(side*31,-3),(side*25,-27),(side*30,-44)], (37,22,57), (151,92,223), 1)
            pygame.draw.ellipse(surf, (132,66,199), pygame.Rect(int(cx-31*sc), int(feet-151*sc+bob), int(62*sc), max(3,int(8*sc))), max(1,int(2*sc)))
            pygame.draw.circle(surf, (246,134,255), (int(cx), int(feet-99*sc+bob)), max(3,int(5*sc)))
        if hot:
            pygame.draw.circle(surf, GOLD, (int(cx), int(top - 6 * sc)), max(3, int(3 * sc)))

    def _enemy_card(self, surf: pygame.Surface, e: Any, cx: float, bottom: float, cw: int, hot: bool) -> None:
        r = pygame.Rect(int(cx - cw / 2), int(max(52, bottom - 62)), cw, 62)
        panel(surf, r, accent=GOLD if hot else (92, 70, 132), alpha=215)
        name = _label(e, 36)
        name_font = self.f["small"] if cw >= 220 and len(name) <= 18 else self.f["tiny"]
        draw_text(surf, name_font, fit_text(name_font, name, cw - 12), (r.x + 8, r.y + 4), BONE)
        hp, mx = _num(e, ("hp",), 0.0) or 0.0, _num(e, ("max_hp",), 0.0) or 0.0
        bar = pygame.Rect(r.x + 8, r.y + 26, cw - 16, 11)
        draw_bar(surf, bar, hp / mx if mx > 0 else 0.0, BLOOD)
        draw_text(surf, self.f["tiny"], f"{hp:.0f}/{mx:.0f}", bar.center, BONE, "center", shadow=False)
        intent = _intent_text(e)
        if intent and getattr(self, "intent_hidden", False):
            # Sensory Deprivation: the telegraph is physically blacked out, never leaked through the card.
            bar_r = pygame.Rect(r.x + 6, r.y + 40, cw - 12, 17)
            pygame.draw.rect(surf, (4, 2, 8), bar_r)
            pygame.draw.rect(surf, (60, 44, 84), bar_r, 1)
            draw_text(surf, self.f["tiny"], "> ???", bar_r.center, (84, 66, 110), "center", shadow=False)
        elif intent:
            draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], "> " + intent, cw - 14), (r.x + 8, r.y + 42), WARN)
        if hot:
            pygame.draw.polygon(surf, GOLD, [(r.centerx - 8, r.y - 12), (r.centerx + 8, r.y - 12), (r.centerx, r.y - 2)])

    def combat_panel(self, surf: pygame.Surface, combat: Any) -> None:
        # Keep the command panel in the lower-right corner, but reserve space for the
        # selected action's actual description. Previously the menu discarded `hint`,
        # forcing players to guess what each skill did.
        r = pygame.Rect(800, 540, 468, 170)
        panel(surf, r, alpha=232)
        phase = _pname(combat.phase)
        active = getattr(combat, "active", None)
        who = _label(active, 20) if active is not None and not isinstance(active, int) else ""
        head = {"MENU": f"{who} - choose an action" if who else "Choose an action",
                "TARGET": "Choose a target - Enter confirm, Esc back",
                "QTE": "Quick-time challenge",
                "RESOLVE": "Resolving action...",
                "ENEMY": "Enemy turn...",
                "VICTORY": "Victory!",
                "DEFEAT": "Defeat..."}.get(phase, phase.title())
        draw_text(surf, self.f["small"], fit_text(self.f["small"], head, r.width - 120), (r.x + 12, r.y + 6), GOLD)
        draw_text(surf, self.f["tiny"], f"Round {getattr(combat, 'round_no', 1)}", (r.right - 12, r.y + 8), MUTED, "topright")
        if phase != "MENU":
            if phase == "TARGET":
                targets = list(getattr(combat, "targets", []) or [])
                tidx = int(getattr(combat, "target_idx", 0) or 0)
                entry = getattr(combat, "pending_entry", None)
                if targets:
                    target = targets[tidx % len(targets)]
                    draw_text(surf, self.f["mid"], f"Target: {_label(target, 30)}", (r.x + 14, r.y + 42), BONE)
                    draw_text(surf, self.f["tiny"], "LEFT/RIGHT or UP/DOWN to change target", (r.x + 14, r.y + 72), MUTED)
                if entry is not None:
                    label = str(getattr(entry, "label", "Selected action"))
                    cost = str(getattr(entry, "cost", "") or "No resource cost")
                    hint = str(getattr(entry, "hint", "") or "No description is available for this action.")
                    draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], f"{label}  |  {cost}", r.width - 28),
                              (r.x + 14, r.y + 96), GOLD)
                    draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], hint, r.width - 28),
                              (r.x + 14, r.y + 116), BONE, shadow=False)
            elif phase == "RESOLVE":
                draw_text(surf, self.f["small"], "Your action is resolving.", (r.x + 14, r.y + 46), BONE)
            elif phase == "ENEMY":
                draw_text(surf, self.f["small"], "Watch the enemy's telegraphed move.", (r.x + 14, r.y + 46), BONE)
            return

        items = list(getattr(combat, "menu", None) or [])
        if not items:
            draw_text(surf, self.f["tiny"], "No actions available.", (r.x + 14, r.y + 38), MUTED)
            return
        idx = max(0, min(int(getattr(combat, "menu_idx", 0) or 0), len(items) - 1))
        start = max(0, min(idx - 2, len(items) - 6))
        for k, item in enumerate(items[start:start + 6]):
            global_idx = start + k
            sel = global_idx == idx
            col = GOLD if sel else (BONE if bool(getattr(item, "enabled", True)) else DIM)
            label = str(getattr(item, "label", _label(item, 28)))
            cost = str(getattr(item, "cost", "") or "")
            prefix = f"{global_idx + 1}. "
            shown = prefix + label
            # Show cost beside the name when there is enough room. The detail area below
            # always carries the full cost, so a long label can safely be ellipsised.
            if cost and len(label) < 18:
                shown += f" [{cost}]"
            x = r.x + 14 + (k // 3) * 226
            y = r.y + 31 + (k % 3) * 19
            draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], shown, 214), (x, y), col)

        pygame.draw.line(surf, (100, 82, 130), (r.x + 12, r.y + 91), (r.right - 12, r.y + 91), 1)
        chosen = items[idx]
        chosen_label = str(getattr(chosen, "label", "Selected action"))
        chosen_cost = str(getattr(chosen, "cost", "") or "No resource cost")
        chosen_hint = str(getattr(chosen, "hint", "") or "No description is available for this action.")
        draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], f"SELECTED: {chosen_label}  |  COST: {chosen_cost}", r.width - 26),
                  (r.x + 14, r.y + 97), GOLD)
        font = self.f["tiny"]
        max_width = r.width - 28
        lines: list[str] = []
        for paragraph in chosen_hint.splitlines() or [chosen_hint]:
            words = paragraph.split()
            line = ""
            for word in words:
                test = word if not line else f"{line} {word}"
                if font.size(test)[0] <= max_width:
                    line = test
                else:
                    if line:
                        lines.append(line)
                    line = word
            if line:
                lines.append(line)
        for line_no, line in enumerate(lines[:3]):
            draw_text(surf, font, fit_text(font, line, max_width), (r.x + 14, r.y + 110 + line_no * 13), BONE, shadow=False)
        draw_text(surf, self.f["tiny"], "UP/DOWN select  ENTER use  number keys 1-9 quick-select",
                  (r.x + 14, r.bottom - 18), MUTED, shadow=False)

    def qte(self, surf: pygame.Surface, combat: Any) -> None:
        src = getattr(combat, "qte", None) or combat
        qte_title = str(getattr(src, "title", "") or "QUICK-TIME CHALLENGE").upper()
        hint = str(getattr(src, "hint", "") or "Follow the on-screen instruction.")
        pulse = 0.5 + 0.5 * math.sin(self.t * 10.0)
        r = pygame.Rect(W // 2 - 320, 110, 640, 180)
        panel(surf, r, accent=mix(GOLD, (255, 255, 255), 0.4 * pulse), alpha=242)
        draw_text(surf, self.f["big"], fit_text(self.f["big"], qte_title, r.width - 30),
                  (r.centerx, r.y + 8), GOLD, "midtop")

        # Each challenge gets a mechanic-specific instruction. In particular, the old
        # typing prompt never displayed `src.word`, so it literally asked the player to
        # type without telling them what to type.
        word = getattr(src, "word", None)
        typed = str(getattr(src, "typed", "") or "")
        presses = getattr(src, "presses", None)
        count = getattr(src, "count", None)
        pos = getattr(src, "pos", None)
        zone = getattr(src, "zone", None)
        sequence = getattr(src, "sequence", None)
        showing = bool(getattr(src, "showing", False))
        index = getattr(src, "index", None)

        panel_lines = getattr(src, "panel_lines", None)
        if panel_lines:
            # R2 restraint trials describe themselves: (text, role) rows rendered generically.
            role_style = {"head": ("mid", GOLD, 44), "body": ("small", BONE, 80),
                          "hint": ("tiny", MUTED, 112), "good": ("small", Pal.GREEN, 80), "bad": ("small", BLOOD, 80)}
            row_y = {"head": r.y + 44, "body": r.y + 82, "hint": r.y + 116}
            seen_roles: dict[str, int] = {}
            for text_line, role in list(panel_lines)[:4]:
                font_key, colour, _ = role_style.get(role, role_style["body"])
                slot = "body" if role in ("good", "bad") else role
                n = seen_roles.get(slot, 0)
                seen_roles[slot] = n + 1
                draw_text(surf, self.f[font_key], fit_text(self.f[font_key], str(text_line), r.width - 36),
                          (r.centerx, row_y.get(slot, r.y + 82) + 18 * n), colour, "midtop")
        elif isinstance(word, str) and word:
            draw_text(surf, self.f["small"], "TYPE THIS WORD EXACTLY", (r.centerx, r.y + 43), BONE, "midtop")
            # Colour the entered prefix separately so progress is unmistakable.
            typed_render = self.f["big"].render(typed.upper(), True, Pal.GREEN)
            rest_render = self.f["big"].render(word[len(typed):].upper(), True, BONE)
            total_w = typed_render.get_width() + rest_render.get_width()
            word_x = r.centerx - total_w // 2
            surf.blit(typed_render, (word_x, r.y + 68))
            surf.blit(rest_render, (word_x + typed_render.get_width(), r.y + 68))
            draw_text(surf, self.f["tiny"], f"Progress {len(typed)}/{len(word)}   |   Wrong letter resets progress   |   BACKSPACE erases one letter",
                      (r.centerx, r.y + 111), MUTED, "midtop")
        elif isinstance(presses, int) and isinstance(count, int):
            key_name = str(getattr(src, "key", "space")).upper()
            draw_text(surf, self.f["mid"], f"MASH {key_name}  —  {count}/{presses}", (r.centerx, r.y + 57), BONE, "midtop")
            draw_text(surf, self.f["tiny"], "Press the shown key repeatedly before time runs out.", (r.centerx, r.y + 94), MUTED, "midtop")
        elif isinstance(pos, (int, float)) and isinstance(zone, (tuple, list)) and len(zone) == 2:
            draw_text(surf, self.f["small"], "PRESS SPACE WHEN THE CURSOR IS INSIDE THE GOLD ZONE", (r.centerx, r.y + 47), BONE, "midtop")
            track = pygame.Rect(r.x + 34, r.y + 88, r.width - 68, 18)
            pygame.draw.rect(surf, (38, 29, 52), track, border_radius=5)
            left = track.x + int(max(0.0, min(1.0, float(zone[0]))) * track.width)
            right = track.x + int(max(0.0, min(1.0, float(zone[1]))) * track.width)
            pygame.draw.rect(surf, GOLD, pygame.Rect(left, track.y, max(3, right - left), track.height), border_radius=4)
            cursor = track.x + int(max(0.0, min(1.0, float(pos))) * track.width)
            pygame.draw.line(surf, (255, 255, 255), (cursor, track.y - 5), (cursor, track.bottom + 5), 3)
            draw_text(surf, self.f["tiny"], hint, (r.centerx, r.y + 119), MUTED, "midtop")
        elif isinstance(sequence, (tuple, list)) and isinstance(index, int):
            if showing:
                names = {"left": "LEFT", "up": "UP", "right": "RIGHT", "down": "DOWN"}
                seq_text = "   ".join(names.get(str(k), str(k).upper()) for k in sequence)
                draw_text(surf, self.f["small"], "MEMORISE THIS SEQUENCE", (r.centerx, r.y + 48), BONE, "midtop")
                draw_text(surf, self.f["mid"], fit_text(self.f["mid"], seq_text, r.width - 36), (r.centerx, r.y + 78), GOLD, "midtop")
            else:
                draw_text(surf, self.f["mid"], f"REPEAT THE ARROWS  —  {index}/{len(sequence)}", (r.centerx, r.y + 62), BONE, "midtop")
                draw_text(surf, self.f["tiny"], "Use the arrow keys in the exact order you memorised.", (r.centerx, r.y + 98), MUTED, "midtop")
        else:
            draw_text(surf, self.f["small"], hint, (r.centerx, r.y + 57), BONE, "midtop")

        ratio = _num(src, ("time_ratio", "progress", "ratio", "timer_ratio", "charge"))
        if ratio is not None:
            draw_bar(surf, pygame.Rect(r.x + 20, r.bottom - 18, r.width - 40, 8), ratio, GOLD)
            draw_text(surf, self.f["tiny"], f"TIME LEFT: {max(0.0, float(getattr(src, 'limit', 0.0)) - float(getattr(src, 'elapsed', 0.0))):.1f}s",
                      (r.centerx, r.bottom - 32), MUTED, "midbottom", shadow=False)

    # ---- rewards / shop / ending --------------------------------------------------------------
    def rewards(self, surf: pygame.Surface, lines: Sequence[str], complete: bool) -> None:
        surf.blit(self.veil, (0, 0))
        draw_text(surf, self.f["huge"], "VICTORY", (W // 2, 90), GOLD, "midtop")
        panel(surf, pygame.Rect(330, 190, 620, 90 + 30 * max(1, len(lines))))
        for i, line in enumerate(lines[:10] or ["The hall falls silent."]):
            draw_text(surf, self.f["mid"], fit_text(self.f["mid"], line, 580), (W // 2, 220 + i * 30), BONE, "midtop")
        self.hint(surf, "[ENTER] finish the run" if complete else "[ENTER] continue")

    def shop(self, surf: pygame.Surface, shop: Any, state: Any) -> None:
        surf.blit(self.veil, (0, 0))
        draw_text(surf, self.f["huge"], "THE MERCHANT", (W // 2, 50), GOLD, "midtop")
        # Reserve the far-left strip for the always-visible run history / restraint details.
        box = pygame.Rect(250, 150, 880, 420)
        panel(surf, box)
        draw_text(surf, self.f["mid"], f"Gold {int(_num(state, ('gold',), 0.0) or 0)}",
                  (box.right - 20, box.y + 14), GOLD, "topright")
        inv = getattr(state, "inventory", None)
        counts = getattr(inv, "counts", None)
        if isinstance(counts, dict):
            count = sum(int(v) for v in counts.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        else:
            try:
                count = len(inv) if inv is not None else 0
            except TypeError:
                count = 0
        draw_text(surf, self.f["small"], f"Pack: {count} item(s)", (box.x + 20, box.y + 18), MUTED)

        rows = _shop_display_rows(shop)
        cur = int(getattr(shop, "cursor", 0) or 0)
        cur = max(0, min(cur, len(rows) - 1))
        start = max(0, min(cur - 4, len(rows) - 9))
        visible = rows[start:start + 9]
        for k, (item, price, remaining, proceed) in enumerate(visible):
            row_index = start + k
            selected = row_index == cur
            rr = pygame.Rect(box.x + 18, box.y + 54 + k * 31, box.width - 36, 28)
            if selected:
                panel(surf, rr, accent=RUNE_PURPLE, alpha=235)
            if proceed:
                label = "Proceed to the next stage"
                col = GOLD if selected else BONE
            else:
                label = str(getattr(item, "name", None) or _label(item, 50))
                if remaining == 0:
                    label += "  [SOLD OUT]"
                elif remaining > 0:
                    label += f"  x{remaining}"
                col = GOLD if selected else (DIM if remaining == 0 else BONE)
            draw_text(surf, self.f["small"], fit_text(self.f["small"], ("> " if selected else "  ") + label, rr.width - 130),
                      (rr.x + 10, rr.centery), col, "midleft")
            if price is not None and not proceed:
                draw_text(surf, self.f["small"], f"{price:.0f}g", (rr.right - 10, rr.centery), GOLD, "midright")

        # The highlighted item always explains its effect; Proceed explains the transition.
        selected_item, selected_price, selected_left, selected_proceed = rows[cur]
        desc = ("Leave the merchant and continue deeper into the Abyss." if selected_proceed else
                str(getattr(selected_item, "desc", "") or "No description available."))
        detail_y = box.bottom - 68
        status = ""
        if not selected_proceed:
            if selected_left == 0:
                status = "SOLD OUT"
            elif selected_price is not None:
                status = f"In stock: {selected_left}   |   Price: {selected_price:.0f} gold"
        if status:
            draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], status, box.width - 40),
                      (box.x + 20, detail_y), WARN if selected_left == 0 else GOLD, shadow=False)
            detail_y += 15
        for line in wrap_text(self.f["tiny"], desc, box.width - 40, 2):
            draw_text(surf, self.f["tiny"], line, (box.x + 20, detail_y), BONE, shadow=False)
            detail_y += 14
        msg = getattr(shop, "message", "")
        if isinstance(msg, str) and msg:
            draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], msg, box.width - 40),
                      (box.centerx, box.bottom - 8), WARN, "midbottom", shadow=False)
        self.hint(surf, "[UP/DOWN] move   [ENTER] buy / proceed   [ESC] leave   [H] journal")

    def run_sidebar(self, surf: pygame.Surface, state: Any) -> None:
        """Persistent run chronicle and complete active-restraint descriptions."""
        r = pygame.Rect(12, 52, 224, 552)
        panel(surf, r, accent=RUNE_PURPLE, alpha=222)
        draw_text(surf, self.f["small"], "PAST ACTIONS", (r.x + 9, r.y + 7), GOLD, shadow=False)
        log_entries = list(getattr(state, "log", ()) or ())
        recent = log_entries[-5:]
        y = r.y + 27
        if not recent:
            draw_text(surf, self.f["tiny"], "The chronicle is quiet.", (r.x + 9, y), MUTED, shadow=False)
            y += 16
        for entry in recent:
            text = _event_text(entry) or str(entry)
            color = getattr(entry, "color", BONE)
            if not (isinstance(color, (tuple, list)) and len(color) >= 3):
                color = BONE
            for line in wrap_text(self.f["tiny"], text, r.width - 18, 2):
                draw_text(surf, self.f["tiny"], line, (r.x + 9, y), tuple(color[:3]), shadow=False)
                y += 14
            y += 2
        # Keep the status section anchored so the journal doesn't push it off-screen.
        status_top = max(r.y + 180, min(y + 5, r.y + 225))
        pygame.draw.rect(surf, (92, 70, 132), pygame.Rect(r.x + 8, status_top, r.width - 16, 1))
        y = status_top + 8
        draw_text(surf, self.f["small"], "BOUND / RESTRAINED", (r.x + 9, y), RUNE_PURPLE, shadow=False)
        y += 20
        found = False
        players = list(getattr(state, "players", ()) or ())
        for player in players:
            for label, desc in _active_restraint_details(player):
                found = True
                if y > r.bottom - 30:
                    draw_text(surf, self.f["tiny"], "More details: press H for the full journal.",
                              (r.x + 9, r.bottom - 20), GOLD, shadow=False)
                    return
                title = f"{getattr(player, 'name', 'Hero')}: {label}"
                draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], title, r.width - 18),
                          (r.x + 9, y), WARN, shadow=False)
                y += 14
                lines = wrap_text(self.f["tiny"], desc, r.width - 18, 2)
                for line in lines:
                    if y > r.bottom - 20:
                        break
                    draw_text(surf, self.f["tiny"], line, (r.x + 9, y), BONE, shadow=False)
                    y += 13
                y += 5
        if not found:
            draw_text(surf, self.f["tiny"], "No active restraints.", (r.x + 9, y), MUTED, shadow=False)

    def journal_overlay(self, surf: pygame.Surface, state: Any, offset: int = 0,
                        restraint_offset: int = 0, focus: str = "history") -> None:
        """Full history and all active restraint descriptions with independent scrolling."""
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((6, 3, 12, 220))
        surf.blit(shade, (0, 0))
        box = pygame.Rect(80, 48, W - 160, H - 96)
        panel(surf, box, accent=RUNE_PURPLE, alpha=248)
        draw_text(surf, self.f["big"], "RUN CHRONICLE", (box.centerx, box.y + 10), GOLD, "midtop")
        focus_label = "HISTORY" if focus == "history" else "RESTRAINTS"
        draw_text(surf, self.f["tiny"], f"H / ESC close   |   TAB focus: {focus_label}   |   PAGE UP / PAGE DOWN scroll",
                  (box.centerx, box.y + 49), MUTED, "midtop", shadow=False)
        split = box.x + int(box.width * 0.60)
        pygame.draw.rect(surf, (92, 70, 132), pygame.Rect(split, box.y + 78, 1, box.height - 92))
        draw_text(surf, self.f["small"], "PAST ACTIONS / CHAT HISTORY", (box.x + 18, box.y + 77), GOLD, shadow=False)
        entries = list(getattr(state, "log", ()) or ())
        page_size = 16
        offset = max(0, min(int(offset), max(0, len(entries) - page_size)))
        end = max(0, len(entries) - offset)
        start = max(0, end - page_size)
        y = box.y + 102
        for entry in entries[start:end]:
            text = _event_text(entry) or str(entry)
            color = getattr(entry, "color", BONE)
            if not (isinstance(color, (tuple, list)) and len(color) >= 3):
                color = BONE
            lines = wrap_text(self.f["tiny"], text, split - box.x - 34, 2)
            for line in lines:
                if y > box.bottom - 26:
                    break
                draw_text(surf, self.f["tiny"], line, (box.x + 18, y), tuple(color[:3]), shadow=False)
                y += 15
            y += 4
            if y > box.bottom - 26:
                break
        draw_text(surf, self.f["small"], "ACTIVE RESTRAINTS / EFFECTS", (split + 14, box.y + 77), RUNE_PURPLE, shadow=False)
        all_restraints = [
            (player, label, desc)
            for player in list(getattr(state, "players", ()) or ())
            for label, desc in _active_restraint_details(player)
        ]
        if not all_restraints:
            draw_text(surf, self.f["tiny"], "No active restraints.", (split + 14, box.y + 102), MUTED, shadow=False)
        else:
            restraint_page_size = 8
            max_restraint_offset = max(0, len(all_restraints) - restraint_page_size)
            restraint_offset = max(0, min(int(restraint_offset), max_restraint_offset))
            page = all_restraints[restraint_offset:restraint_offset + restraint_page_size]
            ry = box.y + 102
            draw_text(surf, self.f["tiny"],
                      f"Showing {restraint_offset + 1}-{restraint_offset + len(page)} of {len(all_restraints)} active restraints",
                      (split + 14, ry), MUTED, shadow=False)
            ry += 18
            for player, label, desc in page:
                draw_text(surf, self.f["tiny"], fit_text(self.f["tiny"], f"{player.name}: {label}", box.right - split - 28),
                          (split + 14, ry), WARN, shadow=False)
                ry += 15
                for line in wrap_text(self.f["tiny"], desc, box.right - split - 28, 3):
                    if ry > box.bottom - 24:
                        break
                    draw_text(surf, self.f["tiny"], line, (split + 14, ry), BONE, shadow=False)
                    ry += 14
                ry += 5

    def ending(self, surf: pygame.Surface, won: bool, state: Any) -> None:
        """Show an outcome recap and the authored campaign epilogue, not a blank results panel."""
        surf.blit(self.veil, (0, 0))
        draw_text(surf, self.f["huge"], "THE CHOIR FALLS SILENT" if won else "YOU JOIN THE CHOIR",
                  (W // 2, 82), GOLD if won else BLOOD, "midtop")
        if state is None:
            self.hint(surf, "[UP/DOWN] choose   [ENTER] confirm")
            return
        mode = "ENDLESS RIFT" if bool(getattr(state, "endless", True)) else "STORY CAMPAIGN"
        classes = ", ".join(str(getattr(getattr(p, "pclass", "Unknown"), "value", "Unknown"))
                             for p in getattr(state, "players", ()))
        score = LocalLeaderboard.score(state, won)
        line = (f"{mode} · Floor {_stage_no(state)} · Bosses {int(getattr(state, 'bosses_defeated', 0))} · "
                f"Gold {int(_num(state, ('gold',), 0.0) or 0)} · Score {score:,}")
        draw_text(surf, self.f["small"], line, (W // 2, 170), MUTED, "midtop")
        draw_text(surf, self.f["small"], f"Party: {classes or 'Unknown'} · Difficulty: {getattr(state, 'difficulty_name', '')} · Seed: {getattr(state, 'seed', '?')}",
                  (W // 2, 198), BONE, "midtop")
        panel(surf, pygame.Rect(190, 240, 900, 270), accent=GOLD if won else BLOOD, alpha=222)
        if won:
            angel_survived = any(isinstance(p, FallenAngel) for p in getattr(state, "players", ()))
            prose = story_content.VICTORY_ANGEL_EPILOGUE if angel_survived else story_content.VICTORY_EPILOGUE
        else:
            prose = story_content.DEFEAT_EPILOGUE
        lines = wrap_text(self.f["small"], prose.replace("\n\n", " ").replace("\n", " "), 820, 8)
        y = 268
        for line_text in lines:
            draw_text(surf, self.f["small"], line_text, (230, y), BONE, shadow=False)
            y += 23
        self.hint(surf, "Local run recorded when possible · [UP/DOWN] choose next action · [ENTER] confirm")


# ======================================================================================================
#  application: owns every state transition
# ======================================================================================================
class GameApp:
    # R2 art layer: class-level defaults keep objects built without __init__ (tests) safe.
    r2: Optional[AssetLibrary] = None
    _r2_sounds: frozenset = frozenset()
    _cutin: Optional[dict] = None          # turn-start character cut-in: {key, name, age}
    _cutin_seen: Optional[tuple] = None    # (hero uid, round) the cut-in last fired for

    def __init__(self, seed: Optional[int] = None, max_frames: int = 0) -> None:
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption(TITLE)
        # Keep user state outside the source tree; old project-local saves are copied, never moved.
        self.saves = SaveManager(slot_names=("autosave", "slot1", "slot2", "slot3"))
        self.storage_warning: Optional[str] = None
        try:
            self.saves.ensure_directory()
        except SaveSystemError as exc:
            self.storage_warning = str(exc)
        self.settings_store = SettingsStore(self.saves.save_dir / "settings.json")
        self.settings_warning: Optional[str] = None
        try:
            self.settings = self.settings_store.load()
        except SettingsError as exc:
            self.settings = self.settings_store.defaults()
            self.settings_warning = str(exc)
        self.fullscreen = bool(self.settings.get("fullscreen", False))
        display_flags = getattr(pygame, "FULLSCREEN", 0) if self.fullscreen else pygame.RESIZABLE
        display_size = (0, 0) if self.fullscreen else (W, H)
        self.display = pygame.display.set_mode(display_size, display_flags)
        self.canvas = pygame.Surface((W, H)).convert()
        self.clock = pygame.time.Clock()
        self.fonts = {"huge": load_font(64, True), "big": load_font(34, True), "mid": load_font(21, True),
                      "small": load_font(16), "tiny": load_font(13)}
        self.seed = seed
        self.max_frames = max(0, max_frames)
        self.frames = 0
        self.running = True
        self._closed = False
        self._audio_warning_keys: set[str] = set()
        self.show_journal = False
        self.journal_offset = 0
        self.journal_restraint_offset = 0
        self.journal_focus = "history"
        self._loading("Tuning the Choir...")
        try:
            self.audio: Any = ProceduralAudioSystem()
        except (pygame.error, OSError, RuntimeError):
            self.audio = _SilentAudio()
        self._apply_audio_settings()
        self._visual_restraint_map: dict[tuple[int, RestraintKind], PlayerRestraint] = {}
        self.renderer = AAARenderer((W, H), on_struggle=self._on_struggle_target)
        # R2 art/audio: optional files, every accessor falls back to the procedural art/audio when absent.
        self.r2 = AssetLibrary(enabled=bool(getattr(self, "settings", {}).get("r2_art", True)))
        self.renderer.assets = self.r2
        self._r2_sounds: set[str] = set()
        loader = getattr(self.audio, "load_file_sfx", None)
        if callable(loader):
            for _name, _path in self.r2.sound_paths().items():
                if loader(_name, _path):
                    self._r2_sounds.add(_name)
        self.painter = Painter(self.fonts, self.renderer)
        self._combat_cls = CombatSystem
        self._shop_cls = Shop
        self.vfx = VFX(self.fonts)
        self.renderer.combat_vfx = self.vfx
        self.painter.combat_vfx = self.vfx
        self._apply_visual_settings()
        self.leaderboard = LocalLeaderboard(self.saves.save_dir / "leaderboard.json")
        self.run_mode = "endless"
        self.leaderboard_filter = "all"
        self.classes: list[Any] = list(PlayerClass)
        if not self.classes:
            raise RuntimeError("core.config.PlayerClass has no members")
        self.difficulties = _difficulty_names()

        self.screen = Screen.TITLE
        self.paused = False
        self.state: Optional[GameState] = None
        self.combat: Any = None
        self.shop: Any = None
        self.chars: list[Any] = []
        self.previews = [
            Character(kind, name, TITLE_PREVIEW_X0 + TITLE_PREVIEW_DX * i, TITLE_PREVIEW_Y, TITLE_PREVIEW_SCALE)
            for i, (kind, name) in enumerate(TITLE_PREVIEW_SPECS)
        ]
        self.setup = PartySetup(len(self.classes))
        self.popups: list[Popup] = []
        self.reward_lines: list[str] = []
        self.victory_claimed = False
        self.won = False
        self.slot_info: dict[int, str] = {}
        self.slot_details: dict[int, Any] = {}
        self.slot_known = False
        self.slot_mode = "load"
        self.slot_back = Screen.TITLE
        self.title_menu = MenuList([])
        self.mode_menu = MenuList([])
        self.settings_menu = MenuList([])
        self.diff_menu = MenuList([])
        self.hub_menu = MenuList([])
        self.slot_menu = MenuList([])
        self.pause_menu = MenuList([])
        self.end_menu = MenuList([])
        # Wardrobe / Tutorials selection state
        self._pets_list = list(PETS.values())
        self._skins_list = list(COMMON_SKINS)
        self.selected_pet: str = list(PETS.keys())[0]   # "raven" by default
        self.selected_skin: str = COMMON_SKINS[0].key   # "default" by default
        self._wardrobe_focus: str = "pet"   # "pet" | "skin"
        self._wardrobe_pet_idx: int = 0
        self._wardrobe_skin_idx: int = 0
        self._tutorials_list = list(GENERAL_TUTORIALS) + list(CLASS_TUTORIALS.values())
        self._tutorials_idx: int = 0
        # Skill tree / meta-progression UI state
        self._skill_tree_class_idx: int = 0   # which class tab is shown
        self._skill_tree_node_idx: int = 0    # which of the class's 6 nodes is highlighted
        self._skill_tree_classes: list[str] = [pc.name for pc in PlayerClass]
        # Player profile (persistent cross-run shards + skill tree)
        self._profile_store = ProfileStore(self.saves.save_dir / "profile.json")
        self.profile: PlayerProfile = self._profile_store.load()
        self._daily_task: DailyTask = get_daily_task()
        self._dialogue_npc: str = ""
        self._dialogue_lines: list[tuple[str, str]] = []
        self._dialogue_idx: int = 0
        self._to_title()
        if self.settings_warning:
            self.notify(f"Settings were not loaded; defaults are active. {self.settings_warning}", WARN, 5.0)
        if self.storage_warning:
            self.notify(f"Save storage warning: {self.storage_warning}", WARN, 5.0)

    # ---- small utilities --------------------------------------------------------------------------
    def _loading(self, text: str) -> None:
        self.display.fill(INK)
        draw_text(self.display, self.fonts["big"], text, (W // 2, H // 2), BONE, "center")
        pygame.display.flip()

    def notify(self, text: str, color: Color = BONE, ttl: float = 2.6) -> None:
        vfx = getattr(self, "vfx", None)
        push_toast = getattr(vfx, "push_toast", None)
        if callable(push_toast):
            push_toast(text, color, category="status", priority=2, life=ttl)
            return
        self.popups.append(Popup(text, color, ttl))
        del self.popups[:-POPUP_MAX]

    def _music(self, idx: int) -> None:
        self.audio.play_bgm(int(clamp(idx, 1, 3)))

    def _apply_audio_settings(self) -> None:
        settings = getattr(self, "settings", {})
        for method, key in (("set_bgm_volume", "music_volume"), ("set_sfx_volume", "sfx_volume")):
            fn = getattr(getattr(self, "audio", None), method, None)
            if callable(fn):
                fn(float(settings.get(key, 0.5)))
        muted = getattr(getattr(self, "audio", None), "set_muted", None)
        if callable(muted):
            muted(bool(settings.get("muted", False)))

    def _apply_visual_settings(self) -> None:
        settings = getattr(self, "settings", {})
        vfx = getattr(self, "vfx", None)
        if vfx is not None:
            vfx.screen_shake_enabled = bool(settings.get("screen_shake", True))
            vfx.particles_enabled = bool(settings.get("particles", True))
            vfx.reduced_motion = bool(settings.get("reduced_motion", False))
            vfx.flash_enabled = not vfx.reduced_motion
        renderer = getattr(self, "renderer", None)
        if renderer is not None:
            renderer.motion_scale = 0.25 if settings.get("reduced_motion", False) else 1.0
        r2 = getattr(self, "r2", None)
        if r2 is not None:
            r2.reduced_motion = bool(settings.get("reduced_motion", False))
            r2.enabled = bool(settings.get("r2_art", True))
            r2.models_enabled = bool(settings.get("r2_models", True))
            if not r2.enabled:
                r2.clear_effects()

    def _save_settings(self, *, notify_user: bool = True) -> bool:
        try:
            self.settings_store.save(self.settings)
        except SettingsError as exc:
            if notify_user:
                self.notify(f"Settings not saved: {exc}", WARN, 4.0)
            return False
        if notify_user:
            self.notify("Settings saved.", GOLD, 1.8)
        return True

    def _apply_fullscreen(self, enabled: bool) -> None:
        self.fullscreen = bool(enabled)
        if self.fullscreen:
            self.display = pygame.display.set_mode((0, 0), getattr(pygame, "FULLSCREEN", 0))
        else:
            self.display = pygame.display.set_mode((W, H), getattr(pygame, "RESIZABLE", 0))

    def _play_sfx(self, name: str, volume: float = 1.0) -> None:
        """Play a procedural SFX without allowing an audio-device failure to break gameplay."""
        try:
            play = getattr(self.audio, "play_sfx", None)
            if callable(play):
                play(name, volume)
        except Exception as exc:
            # Audio is best-effort, but do not hide device/asset failures from diagnostics.
            if name not in self._audio_warning_keys:
                _LOG.warning("Optional SFX %r failed and will be skipped after this warning: %s", name, exc)
                self._audio_warning_keys.add(name)

    def _r2_cutin_tick(self, dt: float) -> None:
        """Age the cut-in and start a new one when a hero's turn menu opens (once per hero per round)."""
        if self._cutin is not None:
            self._cutin["age"] += dt
            limit = CUTIN_REDUCED_SECONDS if (self.r2 and self.r2.reduced_motion) else CUTIN_SECONDS
            if self._cutin["age"] >= limit:
                self._cutin = None
        combat = self.combat
        if self.screen is not Screen.COMBAT or combat is None or self.r2 is None or not self.r2.enabled:
            self._cutin_seen = None
            return
        active = getattr(combat, "active", None)
        if _pname(getattr(combat, "phase", "")) != "MENU" or active is None or isinstance(active, int):
            return
        marker = (getattr(active, "uid", None), getattr(combat, "round_no", 0))
        if marker == self._cutin_seen or marker[0] is None:
            return
        self._cutin_seen = marker
        players = list(getattr(self.state, "players", []) or [])
        idx = players.index(active) if active in players else 0
        try:
            key = _kind_for(active, idx).value
        except (AttributeError, KeyError, ValueError):
            return
        if self.r2.model_aspect(key):
            self._cutin = {"key": key, "name": _label(active, 18), "age": 0.0}

    def _r2_react(self, event: Any) -> None:
        """Start R2 one-shot animations/sounds for Fallen Angel events (presentation only)."""
        kind_obj = getattr(event, "kind", "")
        kind = str(getattr(kind_obj, "value", getattr(kind_obj, "name", kind_obj))).lower()
        uid = int(getattr(event, "uid", 0) or 0)
        if not uid or self.r2 is None or not self.r2.enabled:
            return
        data = getattr(event, "data", {}) or {}
        key = str(data.get("action_key", "")).lower() if isinstance(data, dict) else ""
        if kind == "action":
            icon = icon_for_action(key, str(data.get("action_type", "ability")).lower() if isinstance(data, dict) else "ability")
            if icon:
                self.r2.icon_pop(uid, icon)
        if kind == "restraint_applied" and "chain_tighten" in self._r2_sounds:
            self._play_sfx("chain_tighten", 0.6)

    def _play_combat_event_sfx(self, event: Any) -> None:
        """Translate structured combat events into audible feedback."""
        kind_obj = getattr(event, "kind", "")
        kind = str(getattr(kind_obj, "value", getattr(kind_obj, "name", kind_obj))).lower()
        data = getattr(event, "data", {}) or {}
        if not isinstance(data, dict):
            data = {}
        if kind == "action":
            key = str(data.get("action_key", "")).lower()
            action_type = str(data.get("action_type", "ability")).lower()
            if action_type == "item":
                if key == "cutters":
                    self._play_sfx("chain_clank", 0.75)
                else:
                    self._play_sfx("heal" if any(word in key for word in ("tonic", "salve", "potion", "heal", "mana", "vigor", "lucid")) else "ui_confirm", 0.75)
            elif key in {"bolt", "curse", "barrier", "halo"}:
                self._play_sfx("magic_bolt")
            elif key in {"slash", "dash", "cleave", "rend", "execute", "bash", "quick", "assassinate"}:
                self._play_sfx("slash")
            elif key in {"guard", "provoke"}:
                self._play_sfx("ward")
            elif key == "vanish":
                self._play_sfx("shadow_step")
            elif key in {"writhe", "pierce"}:
                self._play_sfx("impact", 0.7)
        elif kind == "lunge":
            uid = int(getattr(event, "uid", 0) or 0)
            enemies = getattr(self.state, "enemies", []) if self.state is not None else []
            if any(getattr(actor, "uid", None) == uid for actor in enemies):
                self._play_sfx("enemy_swing", 0.8)
        elif kind == "damage":
            self._play_sfx("impact", 0.65)
        elif kind == "crit":
            self._play_sfx("critical")
        elif kind == "heal":
            self._play_sfx("heal")
        elif kind == "restraint_applied":
            label = str(getattr(event, "text", "")).lower()
            self._play_sfx("thorn_snap" if any(word in label for word in ("thorn", "wing", "vine")) else "chain_clank")
        elif kind == "restraint_broken":
            self._play_sfx("struggle_burst")
        elif kind == "lucidity":
            self._play_sfx("magic_bolt", 0.45)
        elif kind == "death":
            self._play_sfx("death", 0.8)
        elif kind in {"boss_phase", "intent"}:
            self._play_sfx("enemy_telegraph", 0.7)
        elif kind == "error":
            self._play_sfx("qte_fail", 0.45)

    def _refresh_slots(self) -> None:
        try:
            raw = self.saves.list_slots()
            self.slot_info, self.slot_known = _normalize_slots(raw)
            self.slot_details = {
                int(getattr(info, "index")): info
                for info in raw
                if isinstance(getattr(info, "index", None), int) and not isinstance(getattr(info, "index", None), bool)
            }
        except _GAME_ERRORS as exc:
            self.slot_info, self.slot_details, self.slot_known = {}, {}, False
            self.notify(f"Cannot list saves: {exc}", BLOOD, 3.5)

    def _has_slot(self, slot: int) -> bool:
        # Fail closed if the save directory could not be inspected; an unverified
        # Continue option is worse than asking the player to use Load Game.
        return slot in self.slot_info if self.slot_known else False

    def _alive_enemies(self) -> bool:
        return self.state is not None and any(_alive(e) for e in self.state.enemies)

    def _bind_state(self) -> None:
        """Rebuild sprites after the GameState object changes (new run or load)."""
        assert self.state is not None
        self.chars = []
        party = list(self.state.players)[:MAX_PARTY]
        xs, sprite_scale = party_formation(len(party)) if party else ((), 0.0)
        for i, p in enumerate(party):
            # Formation scales by party size: the longest Angel wings clear x=236 log and x=690 enemy lane.
            char = Character(_kind_for(p, i), _label(p, NAME_MAX), xs[i], 600.0, sprite_scale,
                             entity_uid=int(getattr(p, "uid", 0) or 0),
                             skin_key=getattr(self.state, 'skin', 'default'))
            char.awakened = bool(getattr(p, "awakened_turns", 0))
            char.decoy_turns = int(getattr(p, "decoy_turns", 0) or 0)
            char.blood = int(getattr(p, "blood", 0) or 0)
            char.heat = int(getattr(p, "heat", 0) or 0)
            char.overheated = bool(getattr(p, "overheated_turns", 0))
            self.chars.append(char)
        self._sync_visual_restraints()
        self.combat = None
        self.shop = None
        self.victory_claimed = False
        self.reward_lines = []

    def _sync_visual_restraints(self) -> None:
        """Mirror game-state Fallen Angel restraints into the renderer's hoverable visuals."""
        self._visual_restraint_map.clear()
        state = self.state
        if state is None:
            for ch in self.chars:
                ch.restraints.clear()
            return
        visual_kinds = tuple(RestraintKind)
        for player, ch in zip(state.players, self.chars):
            ch.awakened = bool(getattr(player, "awakened_turns", 0))
            ch.decoy_turns = int(getattr(player, "decoy_turns", 0) or 0)
            ch.blood = max(0, min(100, int(getattr(player, "blood", 0) or 0)))
            ch.heat = max(0, min(100, int(getattr(player, "heat", 0) or 0)))
            ch.overheated = bool(getattr(player, "overheated_turns", 0))
            actual = ([r for r in PlayerRestraint if r in player.restraints]
                      if isinstance(player, FallenAngel) else [])
            # The renderer has four distinct restraint silhouettes. Show up to four
            # active game restraints with unique hit targets; additional game restraint
            # types remain accessible through the normal Break Restraint action menu.
            visible = list(zip(visual_kinds, actual[:len(visual_kinds)]))
            desired_kinds = [kind for kind, _ in visible]
            if [r.kind for r in ch.restraints] != desired_kinds:
                ch.restraints.clear()
                for kind, _ in visible:
                    ch.bind(kind)
            for kind, actual_restraint in visible:
                visual = ch.restraint(kind)
                if visual is not None:
                    visual.display_name = actual_restraint.label
                    visual.display_lore = actual_restraint.desc
                self._visual_restraint_map[(ch.uid, kind)] = actual_restraint

    def _on_struggle_target(self, target: Any) -> None:
        """Route a hovered visual restraint to the combat model's Break Restraint action."""
        if self.paused or self.screen is not Screen.COMBAT or self.state is None or self.combat is None:
            return
        hero_idx = next((i for i, ch in enumerate(self.chars) if ch is target.character), None)
        if hero_idx is None or hero_idx >= len(self.state.players):
            return
        owner = self.state.players[hero_idx]
        restraint = self._visual_restraint_map.get((target.character.uid, target.restraint.kind))
        if not isinstance(owner, FallenAngel) or restraint is None:
            return
        old_phase = _pname(getattr(self.combat, "phase", ""))
        try:
            started = self.combat.struggle(owner, restraint)
        except _GAME_ERRORS as exc:
            self.notify(f"Struggle failed: {exc}", BLOOD, 2.5)
            self._play_sfx("qte_fail", 0.5)
            return
        if started and old_phase != "QTE" and _pname(getattr(self.combat, "phase", "")) == "QTE":
            self._play_sfx("chain_clank", 0.7)
            self._play_sfx("qte_start", 0.85)
            self.vfx.push_toast(f"Struggling against {restraint.label}", category="status")
        elif not started:
            self.notify("You can only struggle on your turn, when Break Restraint is available.", MUTED, 1.8)
            self.vfx.push_toast("The restraint holds; try again on your turn.", category="struggle_failed")

    # ---- transitions ------------------------------------------------------------------------------
    def _to_title(self) -> None:
        if self.r2 is not None:
            self.r2.clear_effects()
        self._cutin = None
        self._cutin_seen = None
        self.show_journal = False
        self.journal_offset = 0
        self.journal_restraint_offset = 0
        self.journal_focus = "history"
        self._refresh_slots()
        self.state, self.combat, self.shop, self.paused = None, None, None, False
        self.title_menu = MenuList([MenuItem("new", "New Game"),
                                    MenuItem("continue", "Continue Run", bool(self.slot_info)),
                                    MenuItem("saves", "Manage Saves"),
                                    MenuItem("records", "Local Records"),
                                    MenuItem("wardrobe", "Wardrobe & Companions"),
                                    MenuItem("skill_tree", f"Skill Tree  {SHARD_ICON} {getattr(self, 'profile', None) and self.profile.shards or 0}"),
                                    MenuItem("tutorials", "Class Academy"),
                                    MenuItem("settings", "Settings"),
                                    MenuItem("credits", "Credits / About"),
                                    MenuItem("quit", "Quit")])
        self.screen = Screen.TITLE
        self._music(1)

    def _to_hub(self) -> None:
        assert self.state is not None
        self.combat, self.shop, self.paused = None, None, False
        # Keep the between-fight choices focused. Save/load and returning to title
        # live in the pause menu; recovery is automatic after a non-final victory.
        self.hub_menu = MenuList([MenuItem("shop", "Visit the Merchant"),
                                  MenuItem("next", "Descend to the next fight", not self.state.run_complete)])
        self.screen = Screen.HUB
        self._music(1)

    def _start_dialogue(self) -> None:
        import core.story as _story
        npcs = list(_story.NPC_DIALOGUES.keys())
        if not npcs:
            return
        stage = getattr(self.state, "stage", 1) if self.state else 1
        npc = npcs[stage % len(npcs)]
        lines = _story.NPC_DIALOGUES.get(npc, [])
        if lines:
            self._dialogue_npc = npc
            self._dialogue_lines = list(lines)
            self._dialogue_idx = 0
            self.screen = Screen.DIALOGUE
            if self.state:
                self.state.add_log(f"The party listens to {npc}.", GOLD)

    def _finish(self, won: bool) -> None:
        self.won = won
        self.combat, self.shop, self.paused = None, None, False
        if self.state is not None:
            self.state.run_mode = getattr(self, "run_mode", "endless")
            try:
                record, inserted = self.leaderboard.add_result(self.state, won, str(getattr(self.state, "run_id", "")))
                if inserted:
                    self.notify(f"Local record saved: {record['score']} points.", GOLD, 2.4)
            except (LeaderboardError, OSError, ValueError, TypeError) as exc:
                self.notify(f"Run ended, but local record could not be saved: {exc}", WARN, 4.0)
            # Award Choir Shards for the completed run
            profile = getattr(self, "profile", None)
            if profile is not None:
                stage = getattr(self.state, "stage", 0)
                bosses = getattr(self.state, "bosses_defeated", 0)
                shards_earned = calculate_run_shards(won, stage, bosses)
                if shards_earned > 0:
                    profile.add_shards(shards_earned, "run_end")
                    if won:
                        profile.lifetime_victories += 1
                    profile.lifetime_bosses += getattr(bosses, "__index__", lambda: bosses)()
                    try:
                        self._profile_store.save(profile)
                    except (OSError, ValueError, TypeError):
                        pass
                    self.notify(
                        f"+{shards_earned} {SHARD_ICON} {SHARD_CURRENCY_NAME}  (total: {profile.shards})",
                        RUNE_PURPLE, 3.5,
                    )
                    # Refresh title menu shard count immediately
                    try:
                        self._to_title_menu_refresh_shards()
                    except Exception:  # noqa: BLE001
                        pass
                # Check and award daily task completion
                daily = getattr(self, "_daily_task", None)
                if daily is not None and not profile.is_daily_done(daily):
                    from core.meta_progression import check_daily_task_complete
                    if check_daily_task_complete(daily, self.state, won=won):
                        ok, msg = profile.claim_daily(daily)
                        if ok:
                            try:
                                self._profile_store.save(profile)
                            except (OSError, ValueError, TypeError):
                                pass
                            self.notify(msg, GOLD, 4.0)
        self.end_menu = MenuList([MenuItem("title", "Return to Main Menu")])
        self.screen = Screen.ENDING
        self._play_sfx("victory" if won else "defeat", 0.9)
        self.audio.stop_bgm(1600)

    def _open_slots(self, mode: str, back: Screen) -> None:
        self._refresh_slots()
        self.slot_mode, self.slot_back, self.paused = mode, back, False
        ids = ((AUTOSAVE_SLOT,) if mode == "load" else ()) + SAVE_SLOTS
        items: list[MenuItem] = []
        for s in ids:
            name = "Autosave" if s == AUTOSAVE_SLOT else f"Slot {s - AUTOSAVE_SLOT}"
            detail = self.slot_details.get(s)
            status_obj = getattr(detail, "status", None)
            status = str(getattr(status_obj, "value", status_obj) or "").lower()
            used = self._has_slot(s)
            meta = self.slot_info.get(s, "")
            if used:
                items.append(MenuItem(str(s), f"{name}  {meta}".rstrip()))
            elif status in {"corrupt", "unsupported", "invalid"}:
                # Keep damaged slots visible: loading one reports the actual error,
                # while the save screen can deliberately overwrite it.
                label = f"{name}  ({status}; overwrite)" if mode == "save" else f"{name}  ({status}; inspect)"
                items.append(MenuItem(str(s), label, True))
            else:
                items.append(MenuItem(str(s), f"{name}  (empty)", mode == "save"))
        self.slot_menu = MenuList(items)
        self.screen = Screen.SLOTS

    def _begin_encounter(self) -> None:
        assert self.state is not None
        try:
            banner = self.state.spawn_encounter()
        except _GAME_ERRORS as exc:
            self.notify(f"Cannot start encounter: {exc}", BLOOD, 4.0)
            self._to_hub()
            return
        if not self._alive_enemies():
            self.notify("The hall is empty.", MUTED)
            self._to_hub()
            return
        self._start_combat(str(banner or ""))

    def _start_combat(self, banner: str) -> None:
        assert self.state is not None
        try:
            self.combat = self._combat_cls(self.state)
        except _GAME_ERRORS as exc:
            self.notify(f"Combat failed to start: {exc}", BLOOD, 4.0)
            self._to_hub()
            return
        self.victory_claimed, self.paused = False, False
        self.screen = Screen.COMBAT
        if banner:
            self.notify(banner, GOLD, 3.2)
            self.state.add_log(banner, GOLD)
        self._music(1 + min(2, max(0, _stage_no(self.state) - 1) // 2))

    def _start_run(self, difficulty: str) -> None:
        configs = self.setup.configs(self.classes)
        run_seed = self.seed
        if self.run_mode == "daily":
            from datetime import datetime
            run_seed = int(datetime.now().strftime("%Y%m%d"))
        try:
            is_endless = self.run_mode in ("endless", "arena")
            state = GameState(seed=run_seed)
            state.new_run(configs, difficulty, endless=is_endless)
            if self.run_mode == "boss_rush":
                state.stage = 3  # First encounter will be Stage 4: Warden Maelis
            elif self.run_mode == "training":
                state.gold = 999
        except _GAME_ERRORS as exc:
            self.notify(f"Cannot start run: {exc}", BLOOD, 4.0)
            return
        self.state = state
        state.pet = getattr(self, "selected_pet", list(PETS.keys())[0])
        state.skin = getattr(self, "selected_skin", COMMON_SKINS[0].key)
        # Apply permanent skill-tree bonuses from player profile
        profile = getattr(self, "profile", None)
        if profile is not None:
            for player in state.players:
                try:
                    apply_profile_bonuses(player, profile)
                except Exception:  # noqa: BLE001
                    pass
        self._bind_state()
        mode_titles = {
            "story": "Story Campaign",
            "endless": "Endless Rift",
            "arena": "Colosseum Arena",
            "boss_rush": "Boss Rush Gauntlet",
            "training": "Training Grounds",
            "daily": "Daily Challenge",
        }
        mode_label = mode_titles.get(self.run_mode, "Expedition")
        party_names = ", ".join(f"{p.name} ({p.pclass.value})" for p in state.players)
        state.add_log(f"{mode_label} begins on {state.difficulty_name} difficulty: {party_names}.", GOLD)
        if not state.endless:
            state.add_log("The Silence of Emberfall: the Dawn Bell has fallen silent; a choir sings from the cathedral below.", GOLD)
            state.add_log("Twelve halls stand between the surface and the Bell's stolen heart.", GOLD)
            if state.has_angel:
                state.add_log("The Abyss remembers Seraphine's refusal to be silenced; its chains will return each turn.", RUNE_PURPLE)
        self._begin_encounter()

    def _claim_victory(self) -> None:
        assert self.state is not None
        self.victory_claimed = True
        try:
            lines = self.state.claim_victory()
        except _GAME_ERRORS as exc:
            self.notify(f"Reward error: {exc}", BLOOD, 4.0)
            lines = []
        self.reward_lines = [str(x) for x in lines] if lines and not isinstance(lines, str) else ([lines] if lines else [])
        for line in self.reward_lines:
            self.state.add_log(line, GOLD)
        # Recover automatically between encounters instead of presenting another
        # menu option. Final campaign completion does not need a hub rest.
        if not self.state.run_complete:
            try:
                self.state.rest_party()
                self.state.add_log("The party recovers before the next descent.", MANA_BLUE)
            except _GAME_ERRORS as exc:
                self.notify(f"Rest failed: {exc}", WARN, 3.0)
        if self.run_mode == "boss_rush" and self.state.stage < 12:
            self.state.stage = min(11, self.state.stage + 3)
        self._save_slot(AUTOSAVE_SLOT, "Autosaved")
        self.combat = None
        self.screen = Screen.REWARDS

    def _save_slot(self, slot: int, message: str = "") -> bool:
        if self.state is None:
            return False
        try:
            self.saves.save(slot, self.state)
        except _GAME_ERRORS as exc:
            self.notify(f"Save failed: {exc}", BLOOD, 4.0)
            return False
        self.notify(message or f"Saved to slot {slot}", MANA_BLUE, 1.8)
        return True

    def _continue_latest(self) -> bool:
        """Continue from the newest valid save across autosave and all manual slots."""
        try:
            info, loaded = self.saves.continue_latest()
        except _GAME_ERRORS as exc:
            self.notify(f"Continue failed: {exc}", BLOOD, 4.0)
            self._refresh_slots()
            return False
        label = "autosave" if info.index == AUTOSAVE_SLOT else f"Slot {info.index - AUTOSAVE_SLOT}"
        return self._restore_loaded_state(loaded, f"Continued from {label}")

    def _load_slot(self, slot: int) -> bool:
        try:
            loaded = self.saves.load(slot)
        except _GAME_ERRORS as exc:
            self.notify(f"Load failed: {exc}", BLOOD, 4.0)
            return False
        return self._restore_loaded_state(loaded, "Game loaded")

    def _restore_loaded_state(self, loaded: Any, message: str) -> bool:
        """Bind a real deserialised GameState to the existing UI/game flow."""
        if not _looks_like_state(loaded):
            self.notify("That slot is empty or unreadable.", BLOOD, 3.0)
            return False
        self.state = loaded
        self.run_mode = str(getattr(loaded, "run_mode", None) or ("endless" if bool(getattr(loaded, "endless", True)) else "story"))
        self._bind_state()
        self.paused = False
        self.state.add_log(message, MANA_BLUE)
        self.notify(message, MANA_BLUE, 1.8)
        if not self.state.party_alive:
            self._finish(False)
        elif self.state.run_complete:
            self._finish(True)
        elif self._alive_enemies():
            self._start_combat("")
        else:
            self._to_hub()
        return True

    def _set_paused(self, value: bool) -> None:
        if value == self.paused:
            return
        self.paused = value
        if value:
            self.pause_menu = MenuList([MenuItem("resume", "Resume"),
                                        MenuItem("save", "Save game", self.screen is not Screen.COMBAT),
                                        MenuItem("load", "Load game"), MenuItem("title", "Main menu"),
                                        MenuItem("quit", "Quit")])
            self.audio.pause_bgm()
        else:
            self.audio.resume_bgm()

    # ---- input ------------------------------------------------------------------------------------
    def handle_event(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type == getattr(pygame, "VIDEORESIZE", -1) and not self.fullscreen:
            self.display = pygame.display.set_mode((max(800, ev.w), max(450, ev.h)), getattr(pygame, "RESIZABLE", 0))
            return
        if ev.type == pygame.KEYDOWN and ev.key == getattr(pygame, "K_F11", -10000):
            self._apply_fullscreen(not self.fullscreen)
            if hasattr(self, "settings"):
                self.settings["fullscreen"] = self.fullscreen
                self._save_settings(notify_user=False)
            return
        if getattr(self, "show_journal", False) and ev.type == pygame.KEYDOWN:
            if ev.key in (getattr(pygame, "K_h", -9999), pygame.K_ESCAPE):
                self.show_journal = False
                return
            if ev.key == pygame.K_TAB:
                self.journal_focus = "restraints" if self.journal_focus == "history" else "history"
                return
            if ev.key == getattr(pygame, "K_PAGEUP", -9998):
                if self.journal_focus == "restraints":
                    count = sum(len(_active_restraint_details(p)) for p in (getattr(self.state, "players", ()) or ())) if self.state is not None else 0
                    self.journal_restraint_offset = min(max(0, count - 8), self.journal_restraint_offset + 8)
                else:
                    count = len(getattr(self.state, "log", ()) or ()) if self.state is not None else 0
                    self.journal_offset = min(max(0, count - 16), self.journal_offset + 16)
                return
            if ev.key == getattr(pygame, "K_PAGEDOWN", -9997):
                if self.journal_focus == "restraints":
                    self.journal_restraint_offset = max(0, self.journal_restraint_offset - 8)
                else:
                    self.journal_offset = max(0, self.journal_offset - 16)
                return
            # Never dispatch journal navigation into combat, the shop, or an underlying menu.
            return
        # In active combat phases every key belongs to CombatSystem/QTE input.
        # Renderer.handle_event consumes E when the mouse is over a restraint;
        # that must not eat the letter E from a typing QTE.
        busy_combat_key = (ev.type == pygame.KEYDOWN and self.screen is Screen.COMBAT
                           and self.combat is not None and _pname(getattr(self.combat, "phase", "")) != "MENU")
        hovered = None if busy_combat_key else self.renderer.handle_event(ev)
        if ev.type != pygame.KEYDOWN:
            return
        if (ev.key == getattr(pygame, "K_h", -9999) and self.state is not None and
                self.screen in (Screen.COMBAT, Screen.REWARDS, Screen.HUB, Screen.SHOP, Screen.SLOTS, Screen.ENDING, Screen.DIALOGUE) and
                not busy_combat_key):
            self.show_journal = True
            self.journal_offset = 0
            self.journal_restraint_offset = 0
            self.journal_focus = "history"
            return
        if ev.key == pygame.K_e and hovered is not None:
            return  # consumed by the aimed restraint struggle handler
        if ev.key == pygame.K_F2:
            muted = bool(self.audio.toggle_mute())
            if hasattr(self, "settings"):
                self.settings["muted"] = muted
                self._save_settings(notify_user=False)
            return
        is_combat_qte = (self.screen is Screen.COMBAT and self.combat is not None
                         and _pname(getattr(self.combat, "phase", "")) == "QTE")
        if not is_combat_qte:
            if ev.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
                          pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d, pygame.K_TAB):
                self._play_sfx("ui_move", 0.30)
            elif _confirm(ev.key):
                self._play_sfx("ui_confirm", 0.35)
        if self.paused:
            self._key_pause(ev)
            return
        {Screen.TITLE: self._key_title, Screen.MODE_SELECT: self._key_mode_select, Screen.SETUP: self._key_setup,
         Screen.DIFFICULTY: self._key_difficulty, Screen.SLOTS: self._key_slots, Screen.COMBAT: self._key_combat,
         Screen.REWARDS: self._key_rewards, Screen.HUB: self._key_hub, Screen.SHOP: self._key_shop,
         Screen.ENDING: self._key_ending, Screen.LEADERBOARD: self._key_leaderboard,
         Screen.SETTINGS: self._key_settings, Screen.CREDITS: self._key_credits,
         Screen.WARDROBE: self._key_wardrobe, Screen.TUTORIALS: self._key_tutorials,
         Screen.SKILL_TREE: self._key_skill_tree, Screen.DIALOGUE: self._key_dialogue}[self.screen](ev)

    def _key_menu(self, menu: MenuList, ev: pygame.event.Event) -> Optional[MenuItem]:
        d = _nav(ev.key)
        if d:
            menu.move(d)
        elif _confirm(ev.key):
            return menu.selected
        return None

    def _key_title(self, ev: pygame.event.Event) -> None:
        item = self._key_menu(self.title_menu, ev)
        if ev.key == pygame.K_ESCAPE:
            self.running = False
        elif item is None:
            return
        elif item.tag == "new":
            self.mode_menu = MenuList([
                MenuItem("story", "Story Campaign  \u00b7  12 authored halls"),
                MenuItem("endless", "Endless Rift  \u00b7  escalating waves"),
                MenuItem("boss_rush", "Boss Rush  \u00b7  cathedral boss gauntlet"),
                MenuItem("arena", "Colosseum Arena  \u00b7  high-stakes survival"),
                MenuItem("daily", "Daily Challenge  \u00b7  today's seeded objective"),
            ])
            self.screen = Screen.MODE_SELECT
        elif item.tag == "records":
            self.leaderboard_filter = "all"
            self.screen = Screen.LEADERBOARD
        elif item.tag == "wardrobe":
            self.screen = Screen.WARDROBE
        elif item.tag == "skill_tree":
            self._skill_tree_class_idx = 0
            self._skill_tree_node_idx = 0
            self.screen = Screen.SKILL_TREE
        elif item.tag == "tutorials":
            self._tutorials_idx = 0
            self.screen = Screen.TUTORIALS
        elif item.tag == "settings":
            self._refresh_settings_menu()
            self.screen = Screen.SETTINGS
        elif item.tag == "credits":
            self.screen = Screen.CREDITS
        elif item.tag == "continue":
            self._continue_latest()
        elif item.tag == "saves":
            self._open_slots("load", Screen.TITLE)
        elif item.tag == "quit":
            self.running = False

    def _key_credits(self, ev: pygame.event.Event) -> None:
        if ev.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.screen = Screen.TITLE

    def _key_wardrobe(self, ev: pygame.event.Event) -> None:
        key = ev.key
        if key == pygame.K_ESCAPE:
            self.screen = Screen.TITLE
            return
        # TAB or LEFT/RIGHT switches between pet and skin column
        if key in (pygame.K_TAB, pygame.K_LEFT, pygame.K_RIGHT):
            self._wardrobe_focus = "skin" if self._wardrobe_focus == "pet" else "pet"
            return
        d = _nav(key)
        if d:
            if self._wardrobe_focus == "pet":
                self._wardrobe_pet_idx = (self._wardrobe_pet_idx + d) % len(self._pets_list)
                self.selected_pet = self._pets_list[self._wardrobe_pet_idx].key
            else:
                self._wardrobe_skin_idx = (self._wardrobe_skin_idx + d) % len(self._skins_list)
                self.selected_skin = self._skins_list[self._wardrobe_skin_idx].key

    def _key_tutorials(self, ev: pygame.event.Event) -> None:
        key = ev.key
        if key == pygame.K_ESCAPE:
            self.screen = Screen.TITLE
            return
        d = _nav(key)
        if d:
            self._tutorials_idx = (self._tutorials_idx + d) % len(self._tutorials_list)
            return
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_t, pygame.K_SPACE):
            # Launch interactive sparring fight for the highlighted class / lesson
            tut = self._tutorials_list[self._tutorials_idx]
            class_map = {pc.name.lower(): pc for pc in PlayerClass}
            matched_class = class_map.get(getattr(tut, "id", "").lower(), None)
            if matched_class is None:
                matched_class = PlayerClass.ANGEL if getattr(tut, "id", "") == "restraints" else PlayerClass.WARRIOR
            self._start_tutorial_fight(matched_class)

    def _to_title_menu_refresh_shards(self) -> None:
        """Refresh the Skill Tree entry in the title menu to show current shard count."""
        profile = getattr(self, "profile", None)
        shards = profile.shards if profile is not None else 0
        for item in self.title_menu.items:
            if item.tag == "skill_tree":
                item.label = f"Skill Tree  {SHARD_ICON} {shards}"
                break

    def _key_skill_tree(self, ev: pygame.event.Event) -> None:
        """Handle keyboard input on the Skill Tree screen.

        LEFT/RIGHT: cycle class tabs.
        UP/DOWN: move node cursor within the class.
        ENTER/SPACE: purchase or unlock highlighted node.
        R: refund highlighted node (50% shard return).
        ESC: return to title.
        """
        key = ev.key
        if key == pygame.K_ESCAPE:
            self._to_title_menu_refresh_shards()
            self.screen = Screen.TITLE
            return
        classes = getattr(self, "_skill_tree_classes", [pc.name for pc in PlayerClass])
        n_classes = len(classes)
        if not n_classes:
            return
        if key in (pygame.K_LEFT, pygame.K_RIGHT):
            step = -1 if key == pygame.K_LEFT else 1
            self._skill_tree_class_idx = (self._skill_tree_class_idx + step) % n_classes
            self._skill_tree_node_idx = 0
            return
        class_key = classes[self._skill_tree_class_idx]
        nodes = nodes_for_class(class_key)
        if not nodes:
            return
        d = _nav(key)
        if d:
            self._skill_tree_node_idx = (self._skill_tree_node_idx + d) % len(nodes)
            return
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            profile = getattr(self, "profile", None)
            if profile is None:
                return
            node = nodes[self._skill_tree_node_idx]
            ok, msg = profile.purchase_node(node.node_id)
            color = GREEN if ok else WARN
            self.notify(msg, color, 3.0)
            if ok:
                try:
                    self._profile_store.save(profile)
                except (OSError, TypeError, ValueError):
                    pass
                self._to_title_menu_refresh_shards()
            return
        if key == pygame.K_r:
            profile = getattr(self, "profile", None)
            if profile is None:
                return
            node = nodes[self._skill_tree_node_idx]
            ok, msg = profile.refund_node(node.node_id)
            color = CYAN if ok else WARN
            self.notify(msg, color, 3.0)
            if ok:
                try:
                    self._profile_store.save(profile)
                except (OSError, TypeError, ValueError):
                    pass
                self._to_title_menu_refresh_shards()

    def _key_mode_select(self, ev: pygame.event.Event) -> None:
        item = self._key_menu(self.mode_menu, ev)
        if ev.key == pygame.K_ESCAPE:
            self.screen = Screen.TITLE
        elif item is not None:
            self.run_mode = item.tag
            self.setup = PartySetup(len(self.classes))
            self.screen = Screen.SETUP

    def _refresh_settings_menu(self) -> None:
        s = self.settings
        self.settings_menu = MenuList([
            MenuItem("music_volume", f"Music volume: {round(s['music_volume'] * 100)}%"),
            MenuItem("sfx_volume", f"Effects volume: {round(s['sfx_volume'] * 100)}%"),
            MenuItem("muted", f"Audio muted: {'ON' if s['muted'] else 'OFF'}"),
            MenuItem("screen_shake", f"Screen shake: {'ON' if s['screen_shake'] else 'OFF'}"),
            MenuItem("particles", f"Particles: {'ON' if s['particles'] else 'OFF'}"),
            MenuItem("reduced_motion", f"Reduced motion: {'ON' if s['reduced_motion'] else 'OFF'}"),
            MenuItem("r2_art", f"Generated R2 art: {'ON' if s.get('r2_art', True) else 'OFF'}"),
            MenuItem("r2_models", f"Anime character models: {'ON' if s.get('r2_models', True) else 'OFF'}"),
            MenuItem("fullscreen", f"Fullscreen: {'ON' if s['fullscreen'] else 'OFF'}"),
            MenuItem("save", "Save settings now"),
            MenuItem("back", "Return to title"),
        ])

    def _key_settings(self, ev: pygame.event.Event) -> None:
        if ev.key == pygame.K_ESCAPE:
            self._save_settings(notify_user=False)
            self.screen = Screen.TITLE
            return
        selected = self.settings_menu.selected
        if ev.key in (pygame.K_UP, pygame.K_DOWN, pygame.K_w, pygame.K_s, pygame.K_TAB):
            self.settings_menu.move(-1 if ev.key in (pygame.K_UP, pygame.K_w) else 1)
            return
        if selected is None:
            return
        tag = selected.tag
        if tag in ("music_volume", "sfx_volume") and ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            step = -0.05 if ev.key == pygame.K_LEFT else 0.05
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                step = 0.05
            self.settings[tag] = max(0.0, min(1.0, round(float(self.settings[tag]) + step, 2)))
            self._apply_audio_settings()
        elif tag in ("muted", "screen_shake", "particles", "reduced_motion", "r2_art", "r2_models", "fullscreen") and ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.settings[tag] = not bool(self.settings[tag])
            if tag == "fullscreen":
                self._apply_fullscreen(bool(self.settings[tag]))
            self._apply_audio_settings()
            self._apply_visual_settings()
        elif tag == "save" and _confirm(ev.key):
            self._save_settings()
        elif tag == "back" and _confirm(ev.key):
            self._save_settings(notify_user=False)
            self.screen = Screen.TITLE
            return
        if tag not in ("save", "back"):
            self._save_settings(notify_user=False)
        self._refresh_settings_menu()

    def _key_leaderboard(self, ev: pygame.event.Event) -> None:
        if ev.key == pygame.K_ESCAPE or ev.key == pygame.K_BACKSPACE:
            self.screen = Screen.TITLE
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
            order = ("all", "story", "endless", "boss_rush", "arena", "daily")
            step = -1 if ev.key == pygame.K_LEFT else 1
            cur = self.leaderboard_filter if self.leaderboard_filter in order else "all"
            self.leaderboard_filter = order[(order.index(cur) + step) % len(order)]

    def _key_setup(self, ev: pygame.event.Event) -> None:
        s, key = self.setup, ev.key
        if key == pygame.K_ESCAPE:
            self.screen = Screen.TITLE
        elif key == pygame.K_UP:
            s.row = (s.row - 1) % s.rows
        elif key in (pygame.K_DOWN, pygame.K_TAB):
            s.row = (s.row + 1) % s.rows
        elif key in (pygame.K_LEFT, pygame.K_RIGHT):
            d = -1 if key == pygame.K_LEFT else 1
            if s.row == 0:
                s.size = int(clamp(s.size + d, 1, MAX_PARTY))
                s.row = min(s.row, s.rows - 1)
            elif s.row <= s.size:
                s.class_idx[s.row - 1] = (s.class_idx[s.row - 1] + d) % len(self.classes)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if s.row == s.rows - 1:
                self.diff_menu = MenuList([MenuItem(n, n) for n in self.difficulties])
                self.screen = Screen.DIFFICULTY
            else:
                s.row += 1
        elif 1 <= s.row <= s.size:
            i = s.row - 1
            if key == pygame.K_BACKSPACE:
                s.names[i] = s.names[i][:-1]
            elif ev.unicode and ev.unicode.isprintable() and len(s.names[i]) < NAME_MAX:
                s.names[i] += ev.unicode

    def _key_difficulty(self, ev: pygame.event.Event) -> None:
        item = self._key_menu(self.diff_menu, ev)
        if ev.key == pygame.K_ESCAPE:
            self.screen = Screen.SETUP
        elif item is not None:
            self._start_run(item.tag)

    def _key_slots(self, ev: pygame.event.Event) -> None:
        item = self._key_menu(self.slot_menu, ev)
        if ev.key == pygame.K_ESCAPE:
            self.screen = self.slot_back
        elif item is not None:
            slot = int(item.tag)
            if self.slot_mode == "save":
                if self._save_slot(slot):
                    self._refresh_slots()
                    self.screen = self.slot_back
            else:
                self._load_slot(slot)

    def _key_combat(self, ev: pygame.event.Event) -> None:
        c = self.combat
        if c is None:
            return
        phase = _pname(c.phase)
        if (ev.key == pygame.K_p and phase != "QTE") or (ev.key == pygame.K_ESCAPE and phase in ("RESOLVE", "ENEMY")):
            self._set_paused(True)
            return
        if phase in ("VICTORY", "DEFEAT"):
            return
        old_phase = phase
        try:
            qte = getattr(c, "qte", None)
            if phase == "QTE" and isinstance(getattr(qte, "word", None), str) and ev.unicode and ev.unicode.isalpha():
                self._play_sfx("ui_move", 0.18)
            c.handle_key(_key_name(ev.key), text=ev.unicode)
            if old_phase != "QTE" and _pname(c.phase) == "QTE":
                self._play_sfx("qte_start", 0.85)
        except _GAME_ERRORS as exc:
            self.notify(f"Input error: {exc}", BLOOD, 3.0)

    def _key_rewards(self, ev: pygame.event.Event) -> None:
        if _confirm(ev.key):
            assert self.state is not None
            self._finish(True) if self.state.run_complete else self._to_hub()
        elif ev.key == pygame.K_p:
            self._set_paused(True)

    def _key_hub(self, ev: pygame.event.Event) -> None:
        if ev.key in (pygame.K_p, pygame.K_ESCAPE):
            self._set_paused(True)
            return
        if ev.key in (pygame.K_t, pygame.K_l):
            self._start_dialogue()
            return
        item = self._key_menu(self.hub_menu, ev)
        if ev.key == pygame.K_p:
            self._set_paused(True)
        elif item is None or self.state is None:
            return
        elif item.tag == "shop":
            try:
                self.shop = self._shop_cls(self.state.rng, self.state.players, stage=self.state.stage, region=_region_for_stage(self.state.stage))
            except _GAME_ERRORS as exc:
                self.notify(f"Shop unavailable: {exc}", BLOOD, 3.5)
                return
            self.state.add_log("The party visits the Hollow Peddler.", GOLD)
            self.screen = Screen.SHOP
        elif item.tag == "dialogue":
            self._start_dialogue()
        elif item.tag == "next":
            self._begin_encounter()

    def _key_dialogue(self, ev: pygame.event.Event) -> None:
        if ev.key in (pygame.K_ESCAPE, pygame.K_p):
            self.screen = Screen.HUB
        elif ev.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self._dialogue_lines:
                self._dialogue_idx += 1
                if self._dialogue_idx >= len(self._dialogue_lines):
                    self.screen = Screen.HUB
        elif ev.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
            if self._dialogue_lines:
                self._dialogue_idx = max(0, self._dialogue_idx - 1)

    def _key_shop(self, ev: pygame.event.Event) -> None:
        shop, state = self.shop, self.state
        if shop is None or state is None:
            self._to_hub()
            return
        d = _nav(ev.key)
        if ev.key == pygame.K_ESCAPE:
            state.add_log("Left the merchant and returned to camp.", MUTED)
            self._save_slot(AUTOSAVE_SLOT, "Autosaved")
            self._to_hub()
        elif ev.key == pygame.K_p:
            self._set_paused(True)
        elif d:
            shop.move(d)
        elif _confirm(ev.key):
            proceed = shop.on_proceed
            if callable(proceed):
                proceed = proceed()
            if proceed:
                state.add_log("The party leaves the merchant and descends.", MUTED)
                self._save_slot(AUTOSAVE_SLOT, "Autosaved")
                self._to_hub()
                return
            old_gold = state.gold
            stock = getattr(shop, "stock", ()) or ()
            cursor = int(getattr(shop, "cursor", 0) or 0)
            bought_name = "an item"
            if isinstance(stock, (list, tuple)) and 0 <= cursor < len(stock):
                pair = stock[cursor]
                if isinstance(pair, (list, tuple)) and pair:
                    bought_name = str(getattr(pair[0], "name", None) or _label(pair[0], 40))
            try:
                remaining = shop.buy(state.gold, state.inventory)
            except _GAME_ERRORS as exc:
                self.notify(str(exc) or "Cannot buy that.", WARN, 3.0)
                return
            if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
                if remaining < old_gold:
                    spent = int(old_gold - remaining)
                    self.notify(f"Purchased (-{spent}g)", GOLD, 1.8)
                    state.add_log(f"Bought {bought_name} for {spent} gold.", GOLD)
                    if isinstance(stock, (list, tuple)) and 0 <= cursor < len(stock):
                        item_def = stock[cursor][0]
                        if getattr(item_def, "key", "") in ("health", "vigor", "elixir", "tonic"):
                            state.merchant_heals_used = getattr(state, "merchant_heals_used", 0) + 1
                state.gold = type(state.gold)(remaining) if isinstance(state.gold, (int, float)) else remaining

    def _key_ending(self, ev: pygame.event.Event) -> None:
        item = self._key_menu(self.end_menu, ev)
        if ev.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) or (item is not None and item.tag == "title"):
            self._to_title()

    def _key_pause(self, ev: pygame.event.Event) -> None:
        if ev.key in (pygame.K_p, pygame.K_ESCAPE):
            self._set_paused(False)
            return
        item = self._key_menu(self.pause_menu, ev)
        if item is None:
            return
        if item.tag == "resume":
            self._set_paused(False)
        elif item.tag == "save":
            self.paused = False
            self._open_slots("save", self.screen)
        elif item.tag == "load":
            self.paused = False
            self._open_slots("load", self.screen)
        elif item.tag == "title":
            self._to_title()
        elif item.tag == "quit":
            self.running = False

    # ---- update -----------------------------------------------------------------------------------
    def update(self, dt: float) -> None:
        if getattr(self, "show_journal", False):
            return  # browsing the chronicle pauses combat timers and QTE deadlines.
        self.renderer.update(dt)
        for p in self.popups:
            p.age += dt
        self.popups = [p for p in self.popups if p.age < p.ttl]
        if self.paused:
            return
        self.vfx.update(dt)
        if self.r2 is not None:
            self.r2.update(dt)
            self._r2_cutin_tick(dt)
        if self.screen is Screen.COMBAT and self.combat is not None and self.state is not None:
            self._update_combat(dt)

    def _update_combat(self, dt: float) -> None:
        assert self.state is not None
        c = self.combat
        qte_before = getattr(c, "qte", None)
        phase_before = _pname(getattr(c, "phase", ""))
        try:
            self._update_vfx_anchors()
            c.update(dt)
            events = list(c.drain() or [])
        except _GAME_ERRORS as exc:
            self.notify(f"Combat error: {exc}", BLOOD, 4.0)
            return
        phase_after = _pname(getattr(c, "phase", ""))
        if phase_before == "QTE" and qte_before is not None and getattr(qte_before, "done", False) and phase_after != "QTE":
            won = bool(getattr(qte_before, "success", False))
            r2_name = "seal_success" if won else "qte_failure"
            if hasattr(qte_before, "trial_id") and r2_name in self._r2_sounds:
                self._play_sfx(r2_name, 0.9)
            else:
                self._play_sfx("qte_success" if won else "qte_fail")
        if phase_after == "VICTORY" and phase_before != "VICTORY":
            self._play_sfx("victory", 1.0)
        elif phase_after == "DEFEAT" and phase_before != "DEFEAT":
            self._play_sfx("defeat", 0.9)
        if events:
            for event in events:
                self._play_combat_event_sfx(event)
                self._r2_react(event)
            self.vfx.consume(events)
            # VFX owns structured alerts, restraints, crits, healing, rewards and boss
            # phases. Only plain log/error events become legacy popups to avoid duplicates.
            texts = [
                _event_text(e) for e in events
                if _pname(getattr(getattr(e, "kind", None), "name", "")) in {"LOG", "ERROR"}
                and _event_text(e)
            ]
            for t in texts:
                self.notify(t, BONE, 1.8)
        phase = _pname(c.phase)
        if phase == "VICTORY" and not self.victory_claimed:
            self._claim_victory()
        elif phase == "DEFEAT" or not self.state.party_alive:
            self._finish(False)

    def _update_vfx_anchors(self) -> None:
        """Map combat entity UIDs to on-screen sprite centres for hit VFX."""
        if self.state is None or not hasattr(self.vfx, "anchors"):
            return
        anchors: dict[int, tuple[float, float]] = {}
        for player, ch in zip(self.state.players, self.chars):
            # Character.y is the feet baseline; the sprite's centre is roughly halfway
            # up its 420-unit local height, scaled with the rendered character.
            # VFX events carry the real Player UID, not the independent renderer UID.
            anchors[int(player.uid)] = (float(ch.x), float(ch.y) - 210.0 * float(ch.scale))
        shown = list(getattr(self.state, "enemies", []) or [])[:8]
        n = len(shown)
        if n:
            cols = n if n <= 4 else math.ceil(n / 2)
            two_rows = n > 4
            x0, x1 = 690.0, 1262.0
            col_w = (x1 - x0) / cols
            scale = 1.05 if two_rows else (1.60 if n == 1 else 1.50 if n == 2 else 1.38)
            t = float(getattr(self.painter, "t", 0.0))
            for k, foe in enumerate(shown):
                if not _alive(foe):
                    continue
                row, col = divmod(k, cols)
                cx = x0 + col_w * (col + 0.5)
                feet = (372.0, 530.0)[row] if two_rows else 530.0
                bob = math.sin(t * 2.0 + k) * 4.0
                foe_arch = "boss" if bool(getattr(foe, "boss", False)) else ""
                actor_scale = scale * (1.08 if foe_arch == "boss" else 1.0)
                anchors[int(foe.uid)] = (cx, feet - 68.0 * actor_scale + bob)
        self.vfx.anchors = anchors

    # ---- draw -------------------------------------------------------------------------------------
    def draw(self) -> None:
        self._sync_visual_restraints()
        cv, p, st = self.canvas, self.painter, self.state
        in_run = self.screen in (Screen.COMBAT, Screen.REWARDS, Screen.HUB, Screen.SHOP, Screen.ENDING, Screen.DIALOGUE) \
            or (self.screen is Screen.SLOTS and st is not None)
        dw, dh = self.display.get_size()
        if dw > 0 and dh > 0:
            mx, my = pygame.mouse.get_pos()
            self.renderer.mouse_override = (int(mx * W / dw), int(my * H / dh))
        key_art = None
        if self.screen is Screen.TITLE and self.r2 is not None and self.r2.enabled:
            key_art = self.r2.image(TITLE_KEY_ART)      # None when the file is missing -> procedural title
        self.renderer.draw(cv, self.chars if in_run else ([] if key_art is not None else self.previews))
        logo = None
        if key_art is not None:
            still = bool(self.r2.reduced_motion)
            drift = 0 if still else int(-8 + 8 * math.sin(p.t * 0.25))     # slow parallax: shifts the art left by up to 16 px
            cv.blit(key_art, (drift, 0))
            for sx_, sy_, sr_, sc_ in title_sparkles(0.0 if still else p.t):
                pygame.draw.circle(cv, sc_, (sx_, sy_), sr_)
            logo = self.r2.image_fit_width(TITLE_LOGO, 340)
        s = self.screen
        p.intent_hidden = bool(s is Screen.COMBAT and self.combat is not None and getattr(self.combat, "intent_hidden", False))
        if s is Screen.TITLE:
            # Enemy silhouette sits behind the title menu; all eight distinct class models line the foreground.
            if key_art is None:
                p._enemy_sprite(cv, 790, 435, 0.92, 2, False, archetype="boss")
            logo_mode = logo is not None
            if logo_mode:
                cv.blit(logo, (1055 - logo.get_width() // 2, 10))
                sub_text = "V2.0 · A descent in turns"
                draw_text(cv, p.f["small"], sub_text, (1055, 10 + logo.get_height() + 2), mix(MUTED, (255, 255, 255), 0.55), "midtop")
            else:
                p.heading(cv, "CHAINS OF THE ABYSSAL CHOIR", y=34)
                # The subtitle sits over the rose window, so give it a dark plate and brighter ink to stay legible.
                sub_font = p.f["small"]
                sub_text = "V2.0 · A descent in turns"
                sub_w, sub_h = sub_font.size(sub_text)
                panel(cv, pygame.Rect(W // 2 - sub_w // 2 - 16, 114 - 4, sub_w + 32, sub_h + 8), accent=MUTED, alpha=175)
                draw_text(cv, sub_font, sub_text, (W // 2, 114), mix(MUTED, (255, 255, 255), 0.55), "midtop")
            # With the key art the credit/badge move to the right column so the heroes stay unobstructed.
            bx, by = (890, 594) if logo_mode else (32, 192)
            if not logo_mode:
                draw_text(cv, p.f["tiny"], f"Made by Riberii  ·  {CREDIT_URL}", (32, 168), GOLD, "midleft")
            # Sanctum & Daily Task badge
            prof = getattr(self, "profile", None)
            sh_cnt = prof.shards if prof is not None else 0
            daily_t = getattr(self, "_daily_task", None)
            panel(cv, pygame.Rect(bx, by, 330 if logo_mode else 320, 100 if logo_mode else 110), accent=GOLD if daily_t and prof and not prof.is_daily_done(daily_t) else MUTED, alpha=215)
            draw_text(cv, p.f["tiny"], f"SANCTUM: {SHARD_ICON} {sh_cnt} {SHARD_CURRENCY_NAME}", (bx + 12, by + 12), RUNE_PURPLE)
            if daily_t:
                is_d = prof.is_daily_done(daily_t) if prof else False
                st_str = "✓ COMPLETED TODAY" if is_d else f"[+{daily_t.reward_shards} {SHARD_ICON} DAILY OBJECTIVE]"
                st_col = GREEN if is_d else GOLD
                draw_text(cv, p.f["tiny"], st_str, (bx + 12, by + 32), st_col)
                obj_txt = daily_t.objective if len(daily_t.objective) <= 40 else daily_t.objective[:38] + "…"
                draw_text(cv, p.f["tiny"], obj_txt, (bx + 12, by + 52), BONE)
                if logo_mode:
                    draw_text(cv, p.f["tiny"], fit_text(p.f["tiny"], f"Made by Riberii  ·  {CREDIT_URL}", 306), (bx + 12, by + 76), GOLD)
                else:
                    draw_text(cv, p.f["tiny"], "Upgrade passives in Skill Tree menu", (bx + 12, by + 84), MUTED)
            elif logo_mode:
                draw_text(cv, p.f["tiny"], fit_text(p.f["tiny"], f"Made by Riberii  ·  {CREDIT_URL}", 306), (bx + 12, by + 40), GOLD)
            # Keep the bright class preview row in the foreground; the menu panel supplies local contrast.
            p.menu(cv, self.title_menu, 1055, 240 if logo_mode else 150, 330, 34 if logo_mode else 38)
            for i, (kind, _name) in enumerate(TITLE_PREVIEW_SPECS if key_art is None else ()):  # labels sit under the preview heroes
                draw_text(cv, p.f["tiny"], kind.name.replace("_", " "), (TITLE_PREVIEW_X0 + TITLE_PREVIEW_DX * i, 676), GOLD, "midbottom")
            draw_text(cv, p.f["tiny"], "[UP/DOWN] move   [ENTER] confirm   [F11] fullscreen   [F2] mute   [ESC] quit",
                      (W // 2, H - 4), MUTED, "midbottom")
        elif s is Screen.MODE_SELECT:
            cv.blit(p.dim, (0, 0))
            p.heading(cv, "CHOOSE YOUR DESCENT", "Story ends at the Bell; Endless continues past it")
            p.menu(cv, self.mode_menu, W // 2, 270, 560, 58)
            p.hint(cv, "LEFT/RIGHT is not needed here   [ENTER] choose   [ESC] back")
        elif s is Screen.LEADERBOARD:
            self._draw_leaderboard(cv)
        elif s is Screen.SETTINGS:
            cv.blit(p.dim, (0, 0))
            p.heading(cv, "SETTINGS", "LEFT/RIGHT adjusts values · ENTER toggles or selects · settings save locally")
            p.menu(cv, self.settings_menu, W // 2, 185, 650, 44)
            p.hint(cv, "[UP/DOWN] move   [LEFT/RIGHT] adjust   [ENTER] toggle/save   [ESC] return")
        elif s is Screen.CREDITS:
            cv.blit(p.dim, (0, 0))
            p.heading(cv, "CREDITS & ABOUT", "Offline tactical RPG · local saves and records")
            panel(cv, pygame.Rect(155, 205, 970, 340), accent=GOLD, alpha=235)
            draw_text(cv, p.f["big"], "Made by Riberii", (205, 252), GOLD)
            draw_text(cv, p.f["small"], CREDIT_URL, (205, 300), BONE)
            draw_text(cv, p.f["mid"], "Reference project", (205, 365), RUNE_PURPLE)
            draw_text(cv, p.f["small"], "TBS-Combat-Simulator by Riberii — Python turn-based combat and enemy scaling.",
                      (205, 402), BONE)
            draw_text(cv, p.f["small"], "Credited as a project reference; broader code provenance is not asserted.",
                      (205, 430), BONE)
            draw_text(cv, p.f["small"], "MIT notice and copyright are preserved in LICENSE.txt. No network is needed to play.",
                      (205, 480), MUTED)
            p.hint(cv, "[ENTER] or [ESC] return to the title")
        elif s is Screen.SETUP:
            p.setup(cv, self.setup, self.classes)
        elif s is Screen.WARDROBE:
            self._draw_wardrobe(cv)
        elif s is Screen.TUTORIALS:
            self._draw_tutorials(cv)
        elif s is Screen.SKILL_TREE:
            self._draw_skill_tree(cv)
        elif s is Screen.DIFFICULTY:
            cv.blit(p.dim, (0, 0))
            p.heading(cv, "CHOOSE YOUR DREAD", "Difficulty is fixed for the run")
            p.menu(cv, self.diff_menu, W // 2, 270)
            p.hint(cv, "[UP/DOWN] move   [ENTER] descend   [ESC] back")
        elif s is Screen.SLOTS:
            p.overlay(cv, "SAVE GAME" if self.slot_mode == "save" else "LOAD GAME")
            p.menu(cv, self.slot_menu, W // 2, 250, 560)
            p.hint(cv, "[UP/DOWN] move   [ENTER] confirm   [ESC] back")
        elif st is not None:
            self._draw_run(cv, st)
        cin = self._cutin
        if cin is not None and self.screen is Screen.COMBAT and self.r2 is not None:
            p.cutin(cv, self.r2, cin["key"], cin["name"], cin["age"], self.r2.reduced_motion)
        if self.paused:
            p.overlay(cv, "PAUSED")
            p.menu(cv, self.pause_menu, W // 2, 250)
        self.vfx.draw_overlay(cv)
        if in_run and st is not None:
            # Draw the chronicle after world VFX so it remains legible over flashes/toasts.
            p.run_sidebar(cv, st)
            if self.show_journal:
                p.journal_overlay(cv, st, self.journal_offset, self.journal_restraint_offset, self.journal_focus)
        p.popups(cv, self.popups)
        if self.display.get_size() == (W, H):
            self.display.blit(cv, (0, 0))
        else:
            self.display.blit(pygame.transform.smoothscale(cv, self.display.get_size()), (0, 0))

    def _draw_leaderboard(self, surf: pygame.Surface) -> None:
        surf.blit(self.painter.dim, (0, 0))
        p = self.painter
        label = {
            "all": "ALL MODES",
            "story": "STORY CAMPAIGN",
            "endless": "ENDLESS RIFT",
            "boss_rush": "BOSS RUSH",
            "arena": "COLOSSEUM ARENA",
            "daily": "DAILY CHALLENGE",
        }.get(self.leaderboard_filter, "ALL MODES")
        p.heading(surf, "THE LOCAL CHRONICLE", f"Offline records only  ·  [{label}]  ·  LEFT/RIGHT changes filter")
        panel(surf, pygame.Rect(105, 190, 1070, 430), accent=GOLD, alpha=225)
        try:
            records = self.leaderboard.records(self.leaderboard_filter, 10)
        except LeaderboardError as exc:
            draw_text(surf, p.f["small"], f"Records could not be read: {exc}", (W // 2, 280), BLOOD, "center")
            draw_text(surf, p.f["tiny"], "The file was preserved; fix or back it up before retrying.", (W // 2, 315), MUTED, "center")
            records = []
        headers = ((132, "RANK"), (205, "SCORE"), (320, "RESULT / MODE"), (532, "PARTY"), (860, "STAGE"), (1000, "BOSSES"))
        for x, text in headers:
            draw_text(surf, p.f["tiny"], text, (x, 210), GOLD)
        if not records:
            draw_text(surf, p.f["mid"], "No completed runs recorded yet.", (W // 2, 330), MUTED, "center")
        for idx, r in enumerate(records):
            y = 244 + idx * 34
            if idx % 2 == 0:
                pygame.draw.rect(surf, (32, 24, 43), pygame.Rect(120, y - 5, 1040, 29), border_radius=4)
            col = GREEN if r["result"] == "victory" else (BONE if idx == 0 else MUTED)
            draw_text(surf, p.f["tiny"], f"{idx + 1:02d}", (132, y), col)
            draw_text(surf, p.f["tiny"], f"{r['score']:,}", (205, y), GOLD)
            draw_text(surf, p.f["tiny"], f"{r['result'].upper()} · {r['mode'].upper()}", (320, y), col)
            draw_text(surf, p.f["tiny"], fit_text(p.f["tiny"], ", ".join(r["classes"]) or "Unknown", 300), (532, y), BONE)
            draw_text(surf, p.f["tiny"], f"{r['stage']} / {r['difficulty']}", (860, y), BONE)
            draw_text(surf, p.f["tiny"], str(r.get("bosses", 0)), (1000, y), BONE)
        draw_text(surf, p.f["tiny"], "Score = stage × 100 + bosses × 350 + levels × 50 + gold ÷ 5 + 750 for a clear.",
                  (W // 2, 635), MUTED, "center")
        p.hint(surf, "[ESC] return to title")

    def _draw_wardrobe(self, cv: pygame.Surface) -> None:
        p = self.painter
        cv.blit(p.dim, (0, 0))
        p.heading(cv, "WARDROBE & COMPANIONS",
                  "TAB or LEFT/RIGHT switch column  \u00b7  UP/DOWN select  \u00b7  ESC return")
        # pet column (left)
        pet_focus = self._wardrobe_focus == "pet"
        panel(cv, pygame.Rect(80, 190, 530, 440), accent=GOLD if pet_focus else MUTED, alpha=230)
        draw_text(cv, p.f["mid"], "COMPANIONS", (345, 200), GOLD if pet_focus else MUTED, "center")
        for i, pet in enumerate(self._pets_list):
            y = 248 + i * 72
            sel = i == self._wardrobe_pet_idx
            c_col = GOLD if sel else (BONE if pet_focus else DIM)
            bg = (45, 30, 58) if sel else (28, 18, 38)
            pygame.draw.rect(cv, bg, pygame.Rect(95, y - 6, 505, 62), border_radius=6)
            if sel:
                pygame.draw.rect(cv, GOLD, pygame.Rect(95, y - 6, 505, 62), 1, border_radius=6)
            draw_text(cv, p.f["small"], pet.name, (112, y + 2), c_col)
            draw_text(cv, p.f["tiny"], pet.title, (112, y + 24), MUTED)
            draw_text(cv, p.f["tiny"], pet.passive_desc[:60], (112, y + 42), RUNE_PURPLE)
        sel_pet = self._pets_list[self._wardrobe_pet_idx]
        draw_text(cv, p.f["tiny"], f"Active companion: {sel_pet.name}", (345, 650), MANA_BLUE, "center")
        # skin column (right)
        skin_focus = self._wardrobe_focus == "skin"
        panel(cv, pygame.Rect(640, 190, 560, 440), accent=GOLD if skin_focus else MUTED, alpha=230)
        draw_text(cv, p.f["mid"], "ATTIRE / PALETTES", (920, 200), GOLD if skin_focus else MUTED, "center")
        for i, skin in enumerate(self._skins_list):
            y = 248 + i * 80
            sel = i == self._wardrobe_skin_idx
            c_col = GOLD if sel else (BONE if skin_focus else DIM)
            bg = (45, 30, 58) if sel else (28, 18, 38)
            pygame.draw.rect(cv, bg, pygame.Rect(655, y - 6, 530, 68), border_radius=6)
            if sel:
                pygame.draw.rect(cv, skin.accent_color, pygame.Rect(655, y - 6, 530, 68), 1, border_radius=6)
            pygame.draw.rect(cv, skin.accent_color, pygame.Rect(668, y + 5, 18, 18), border_radius=3)
            pygame.draw.rect(cv, skin.trim_color,   pygame.Rect(692, y + 5, 18, 18), border_radius=3)
            draw_text(cv, p.f["small"], skin.name, (718, y + 2), c_col)
            draw_text(cv, p.f["tiny"], skin.title, (718, y + 22), MUTED)
            draw_text(cv, p.f["tiny"], skin.desc[:55], (718, y + 40), DIM)
        sel_skin = self._skins_list[self._wardrobe_skin_idx]
        draw_text(cv, p.f["tiny"], f"Active attire: {sel_skin.name}", (920, 650), MANA_BLUE, "center")
        p.hint(cv, "[TAB / LEFT / RIGHT] switch column   [UP/DOWN] select   [ESC] return to title")

    def _draw_tutorials(self, cv: pygame.Surface) -> None:
        p = self.painter
        cv.blit(p.dim, (0, 0))
        tuts = self._tutorials_list
        idx = self._tutorials_idx
        p.heading(cv, "CLASS ACADEMY",
                  f"Lesson {idx + 1} / {len(tuts)}  \u00b7  UP/DOWN browse  \u00b7  ESC return")
        # sidebar: lesson index
        panel(cv, pygame.Rect(55, 188, 300, 450), accent=MUTED, alpha=220)
        row_h = max(18, 436 // max(1, len(tuts)))
        for i, tut in enumerate(tuts):
            y = 204 + i * row_h
            sel = i == idx
            col = GOLD if sel else (BONE if i < 3 else MUTED)
            prefix = "\u25b6 " if sel else "  "
            draw_text(cv, p.f["tiny"], prefix + tut.title[:26], (70, y), col)
        # main lesson panel
        lesson = tuts[idx]
        panel(cv, pygame.Rect(375, 188, 860, 450), accent=GOLD, alpha=235)
        draw_text(cv, p.f["big"], lesson.title, (805, 205), GOLD, "center")
        draw_text(cv, p.f["small"], f"Topic: {lesson.topic}", (805, 248), RUNE_PURPLE, "center")
        # summary word-wrap
        summary_words = lesson.summary.split()
        line_buf: list[str] = []
        cy = 288
        for word in summary_words:
            test = " ".join(line_buf + [word])
            if p.f["small"].size(test)[0] > 810:
                draw_text(cv, p.f["small"], " ".join(line_buf), (805, cy), BONE, "center")
                line_buf, cy = [word], cy + 26
            else:
                line_buf.append(word)
        if line_buf:
            draw_text(cv, p.f["small"], " ".join(line_buf), (805, cy), BONE, "center")
            cy += 36
        cy += 10
        draw_text(cv, p.f["tiny"], "\u2500\u2500\u2500 TACTICAL TIPS \u2500\u2500\u2500", (805, cy), MUTED, "center")
        cy += 22
        for tip in lesson.tips:
            tip_words = tip.split()
            t_buf: list[str] = ["\u2022"]
            for word in tip_words:
                test = " ".join(t_buf + [word])
                if p.f["tiny"].size(test)[0] > 800:
                    draw_text(cv, p.f["tiny"], " ".join(t_buf), (805, cy), BONE, "center")
                    t_buf, cy = ["  ", word], cy + 20
                else:
                    t_buf.append(word)
            draw_text(cv, p.f["tiny"], " ".join(t_buf), (805, cy), BONE, "center")
            cy += 28
        p.hint(cv, "[ENTER / T] start sparring combat   [UP/DOWN] browse lessons   [ESC] return to title")

    def _start_tutorial_fight(self, pclass: PlayerClass) -> None:
        """Launch an interactive sparring combat for the given class."""
        self.run_mode = "training"
        cfg = PlayerConfig(name=pclass.value, pclass=pclass)
        state = GameState(seed=20261025)
        state.new_run([cfg], "Normal", endless=False)
        state.gold = 300
        from entities.enemy import Enemy, ARCHETYPES, Scaling
        arch = ARCHETYPES.get("construct", list(ARCHETYPES.values())[0])
        construct = Enemy(arch, "Sparring Automaton", 1, Scaling(1.0, 1.0, 1.0), 1.0)
        construct.max_hp = 90
        construct.hp = 90
        construct.base_attack = 8
        construct.base_defense = 3
        construct.speed = 5
        construct.squad = [construct]
        state.stage = 1
        state.enemies = [construct]
        self.state = state
        self._bind_state()
        state.add_log(f"=== CLASS PRACTICE: {pclass.value.upper()} ===", GOLD)
        state.add_log("Practice your class abilities, resource economy, guard mitigation, and special skills.", BONE)
        state.add_log("Defeat the automaton to complete this lesson. Press ESC to return anytime.", MANA_BLUE)
        self._start_combat(f"Sparring Arena: {pclass.value}")

    def _draw_skill_tree(self, cv: pygame.Surface) -> None:
        p = self.painter
        cv.blit(p.dim, (0, 0))
        profile = getattr(self, "profile", None)
        shards = profile.shards if profile is not None else 0
        p.heading(cv, "SANCTUM OF ASCENSION",
                  f"{SHARD_ICON} {shards} {SHARD_CURRENCY_NAME}  ·  Permanent Meta-Progression Across All Expeditions")

        # Class tabs row
        classes = getattr(self, "_skill_tree_classes", [pc.name for pc in PlayerClass])
        tab_w = 140
        tab_gap = 5
        start_x = 60
        tab_y = 150
        cur_class_idx = getattr(self, "_skill_tree_class_idx", 0)
        for i, cname in enumerate(classes):
            tx = start_x + i * (tab_w + tab_gap)
            sel = (i == cur_class_idx)
            bg = (55, 34, 75) if sel else (26, 18, 36)
            border_col = GOLD if sel else (52, 38, 64)
            pygame.draw.rect(cv, bg, pygame.Rect(tx, tab_y, tab_w, 36), border_radius=6)
            pygame.draw.rect(cv, border_col, pygame.Rect(tx, tab_y, tab_w, 36), 2 if sel else 1, border_radius=6)
            display_name = cname.replace("ANGEL", "FALLEN ANGEL")[:13]
            col = GOLD if sel else (BONE if not sel else MUTED)
            draw_text(cv, p.f["tiny"], display_name, (tx + tab_w // 2, tab_y + 11), col, "center")

        # Left Panel: 3 Tiers of Skills for Active Class
        cur_class_name = classes[cur_class_idx] if cur_class_idx < len(classes) else "WARRIOR"
        nodes = nodes_for_class(cur_class_name)
        cur_node_idx = getattr(self, "_skill_tree_node_idx", 0)
        panel(cv, pygame.Rect(60, 198, 760, 440), accent=GOLD, alpha=230)
        draw_text(cv, p.f["mid"], f"{cur_class_name} ASCENSION PATH", (440, 212), GOLD, "center")
        draw_text(cv, p.f["tiny"], "Unlocked passive traits apply permanently to all heroes of this class at run start.", (440, 238), MUTED, "center")

        branch_names = {"core": "CORE", "specialisation": "SPECIALISATION", "utility": "UTILITY", "capstone": "CAPSTONE"}
        unlocked = profile.unlocked_nodes if profile is not None else set()
        card_y0, step = 258, 62
        for i, node in enumerate(nodes):
            ny = card_y0 + i * step
            is_sel = (i == cur_node_idx)
            is_unlocked = node.node_id in unlocked
            missing = [SKILL_TREE[r].name for r in node.requires if r not in unlocked and r in SKILL_TREE]
            prereq_ok = not missing
            can_buy = profile is not None and profile.can_afford(node.cost) and not is_unlocked and prereq_ok

            card_bg = (48, 28, 64) if is_sel else ((36, 24, 48) if is_unlocked else (24, 16, 32))
            border_col = GOLD if is_sel else (GREEN if is_unlocked else ((80, 56, 100) if prereq_ok else (40, 28, 50)))
            card = pygame.Rect(80, ny, 720, 58)
            pygame.draw.rect(cv, card_bg, card, border_radius=8)
            pygame.draw.rect(cv, border_col, card, 2 if is_sel else 1, border_radius=8)

            draw_text(cv, p.f["tiny"], branch_names.get(node.branch, node.branch.upper()), (96, ny + 6), RUNE_PURPLE)
            draw_text(cv, p.f["small"], node.name, (212, ny + 3), GOLD if is_sel else (BONE if is_unlocked else DIM))
            if is_unlocked:
                status_text, status_col = "UNLOCKED", GREEN
            elif not prereq_ok:
                status_text, status_col = fit_text(p.f["tiny"], "LOCKED: needs " + ", ".join(missing), 300), MUTED
            elif can_buy:
                status_text, status_col = f"READY: {node.cost} {SHARD_ICON}", GOLD
            else:
                need = node.cost - (profile.shards if profile else 0)
                status_text, status_col = f"COST: {node.cost} {SHARD_ICON} (need {need} more)", WARN
            draw_text(cv, p.f["tiny"], status_text, (784, ny + 6), status_col, "topright")
            draw_text(cv, p.f["tiny"], fit_text(p.f["tiny"], node.description, 690), (96, ny + 23), BONE)
            if node.tradeoff:
                draw_text(cv, p.f["tiny"], fit_text(p.f["tiny"], "Tradeoff: " + node.tradeoff, 690), (96, ny + 40), BLOOD)
            elif node.stat_key.startswith("perk_"):
                draw_text(cv, p.f["tiny"], "Runtime perk: " + PERK_HELP.get(node.stat_key[5:], node.stat_key[5:]),
                          (96, ny + 40), MANA_BLUE if is_unlocked else MUTED)
            else:
                draw_text(cv, p.f["tiny"], f"Permanent bonus: {node.stat_key.replace('_', ' ')} +{node.stat_delta:g}",
                          (96, ny + 40), MANA_BLUE if is_unlocked else MUTED)

        # Right Panel: Active Class Bonuses + Daily Task
        panel(cv, pygame.Rect(835, 198, 385, 440), accent=MUTED, alpha=230)
        draw_text(cv, p.f["mid"], "ACTIVE PASSIVES", (1027, 212), GOLD, "center")
        bonuses = profile.get_unlocked_bonuses(cur_class_name) if profile else {}
        if bonuses:
            by = 242
            items = list(bonuses.items())
            for k, val in items[:4]:
                label = (f"{PERK_HELP.get(k[5:], k[5:])}: {val:+g}" if k.startswith("perk_")
                         else f"{k.replace('_', ' ').upper()}: +{val:g}")
                draw_text(cv, p.f["tiny"], fit_text(p.f["tiny"], "◈ " + label, 345), (860, by), GREEN)
                by += 20
            if len(items) > 4:
                draw_text(cv, p.f["tiny"], f"+{len(items) - 4} more active", (860, by), MUTED)
        else:
            draw_text(cv, p.f["tiny"], "No passives unlocked for this class yet.", (1027, 252), MUTED, "center")
            draw_text(cv, p.f["tiny"], "Earn Choir Shards in runs to unlock nodes.", (1027, 272), MUTED, "center")

        pygame.draw.line(cv, (60, 44, 76), (855, 330), (1200, 330), 1)

        draw_text(cv, p.f["mid"], "DAILY CHOIR OBJECTIVE", (1027, 346), RUNE_PURPLE, "center")
        daily = getattr(self, "_daily_task", None)
        if daily:
            is_done = profile.is_daily_done(daily) if profile else False
            status_badge = "[COMPLETED TODAY]" if is_done else f"[REWARD: +{daily.reward_shards} {SHARD_ICON}]"
            badge_col = GREEN if is_done else GOLD
            draw_text(cv, p.f["small"], status_badge, (1027, 376), badge_col, "center")

            words = daily.objective.split()
            w_buf: list[str] = []
            oy = 408
            for w in words:
                test = " ".join(w_buf + [w])
                if p.f["tiny"].size(test)[0] > 345:
                    draw_text(cv, p.f["tiny"], " ".join(w_buf), (1027, oy), BONE, "center")
                    w_buf, oy = [w], oy + 20
                else:
                    w_buf.append(w)
            if w_buf:
                draw_text(cv, p.f["tiny"], " ".join(w_buf), (1027, oy), BONE, "center")
                oy += 22

            draw_text(cv, p.f["tiny"], f"Target Mode: {daily.mode.upper()}", (1027, oy + 12), MANA_BLUE, "center")
            draw_text(cv, p.f["tiny"], f"Date: {daily.date_str}", (1027, oy + 32), MUTED, "center")

        p.hint(cv, "[LEFT/RIGHT] class tabs   [UP/DOWN] select node   [ENTER] purchase   [R] refund (50%)   [ESC] return")

    def _draw_run(self, cv: pygame.Surface, st: Any) -> None:
        p, s = self.painter, self.screen
        if s is Screen.COMBAT and self.combat is not None:
            c = self.combat
            p.enemy_field(cv, st.enemies, _target_index(c, st.enemies))
            self.vfx.draw_world(cv)
            p.party_cards(cv, st.players, getattr(c, "active", None))
            p.combat_panel(cv, c)
            p.top_bar(cv, st, f"Round {getattr(c, 'round_no', 1)}")
            if _pname(c.phase) == "QTE":
                p.qte(cv, c)
            return
        self.vfx.draw_world(cv)
        if s is Screen.REWARDS:
            p.rewards(cv, self.reward_lines, bool(st.run_complete))
        elif s is Screen.HUB:
            cv.blit(p.dim, (0, 0))
            p.top_bar(cv, st, "Camp")
            p.menu(cv, self.hub_menu, W // 2 + 180, 110, 400, 46)
            p.party_cards(cv, st.players, None)
            p.hint(cv, "[UP/DOWN] move   [ENTER] confirm   [T] lore/tales   [P] pause")
        elif s is Screen.SHOP and self.shop is not None:
            p.shop(cv, self.shop, st)
            p.top_bar(cv, st, "Merchant")
        elif s is Screen.ENDING:
            p.ending(cv, self.won, st)
            p.menu(cv, self.end_menu, W // 2, 532, 360, 38)
        elif s is Screen.DIALOGUE:
            cv.blit(p.dim, (0, 0))
            p.top_bar(cv, st, "Camp — Tales of the Choir")
            p.party_cards(cv, st.players, None)
            self._draw_dialogue(cv)

    def _draw_dialogue(self, cv: pygame.Surface) -> None:
        p = self._palette
        pw, ph = 820, 380
        px, py = (W - pw) // 2, (H - ph) // 2
        panel_surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel_surf.fill((18, 14, 28, 240))
        cv.blit(panel_surf, (px, py))
        pygame.draw.rect(cv, GOLD, pygame.Rect(px, py, pw, ph), 2, border_radius=10)
        draw_text(cv, p.f["mid"], self._dialogue_npc, (W // 2, py + 22), GOLD, "center")
        if self._dialogue_lines:
            idx = self._dialogue_idx % len(self._dialogue_lines)
            topic, text = self._dialogue_lines[idx]
            draw_text(cv, p.f["small"], f'— {topic} —', (W // 2, py + 62), MANA_BLUE, "center")
            words = text.split()
            cur_line: list[str] = []
            lines_out: list[str] = []
            for w in words:
                test = " ".join(cur_line + [w])
                if p.f["small"].size(test)[0] > pw - 80:
                    lines_out.append(" ".join(cur_line))
                    cur_line = [w]
                else:
                    cur_line.append(w)
            if cur_line:
                lines_out.append(" ".join(cur_line))
            for li, ln in enumerate(lines_out[:7]):
                draw_text(cv, p.f["small"], ln, (px + 40, py + 106 + li * 28), BONE)
        total = len(self._dialogue_lines)
        cur = (self._dialogue_idx % max(1, total)) + 1
        draw_text(cv, p.f["tiny"], f"Topic {cur} of {total}   |   [ENTER / SPACE] next topic   |   [ESC] return to camp", (W // 2, py + ph - 28), MUTED, "center")

    # ---- main loop --------------------------------------------------------------------------------
    def run(self) -> None:
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()
            pygame.display.flip()
            self.frames += 1
            if self.max_frames and self.frames >= self.max_frames:
                self.running = False

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.audio.shutdown(quit_mixer=True)
        except (pygame.error, OSError, RuntimeError):
            pass
        pygame.quit()


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Abyssal Choir (turn-based)")
    ap.add_argument("--seed", type=int, default=None, help="deterministic GameState seed")
    ap.add_argument("--max-frames", type=int, default=0, help="exit after N frames (smoke tests)")
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    app: Optional[GameApp] = None
    try:
        app = GameApp(seed=args.seed, max_frames=args.max_frames)
        app.run()
    except ImportError as exc:
        print(f"main.py: {exc}", file=sys.stderr)
        return 2
    finally:
        if app is not None:
            app.shutdown()
        else:
            pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
