"""Save manager for the GameState ``to_dict()`` / ``from_dict()`` contract.

Files live in the per-user ``AbyssalChoir/saves`` data directory by default, one JSON file per named
slot (``slot1.json``, ``slot2.json``, ``slot3.json``) plus a ``.bak`` copy of the previous valid save.
Legacy project-local JSON files are copied (never moved) into an empty user-data directory on first run.

File layout (envelope schema 1)::

    {"format": "game-state-save", "schema": 1, "saved_at": "<ISO-8601 UTC>",
     "saved_at_epoch": <float>, "sha256": "<hash of canonical 'game' JSON>", "game": <GameState.to_dict()>}

The envelope schema is versioned independently of ``GameState``'s own ``version`` field, which
``GameState.from_dict`` keeps validating. Bare ``to_dict()`` JSON (no envelope) is accepted as a
legacy file and upgraded in memory.

Public API
----------
``SaveManager(save_dir=None, slot_names=DEFAULT_SLOT_NAMES)``
    ``ensure_directory()``      create the saves directory safely and check it is writable.
    ``slot_path(slot)``         path of a slot file; ``slot`` is a 1-based int or a slot name.
    ``save(slot, state)``       validate, then atomically write; returns ``SlotInfo``.
    ``load(slot)``              return a ``GameState``; ``allow_backup=True`` falls back to the ``.bak``.
    ``inspect(slot)``           ``SlotInfo`` (status, timestamp, summary, error) without raising.
    ``list_slots()``            ``SlotInfo`` for every slot, in slot order.
    ``latest_slot()``           newest valid ``SlotInfo`` or ``None``.
    ``has_save()``              True when Continue should be enabled (cache it; it reads files).
    ``continue_latest()``       ``(SlotInfo, GameState)`` for the newest loadable save.
    ``delete(slot)``            remove a slot and its backup; returns whether a save existed.
``default_manager()``           shared ``SaveManager`` using the default directory and slots.

Errors (all subclass ``SaveSystemError``): ``InvalidSlotError``, ``SaveNotFoundError``,
``SaveCorruptError``, ``SaveVersionError``, ``SaveIOError``.

Only the standard library is used; data is JSON only (never pickle).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from core.game_state import GameState, SaveDataError, UnsupportedSaveVersionError

__all__ = [
    "BACKUP_SUFFIX", "DEFAULT_SAVE_DIR", "DEFAULT_SLOT_NAMES", "ENVELOPE_VERSION", "FORMAT_ID",
    "MAX_SAVE_BYTES", "SAVE_SUFFIX",
    "InvalidSlotError", "SaveCorruptError", "SaveIOError", "SaveManager", "SaveNotFoundError",
    "SaveSystemError", "SaveVersionError", "SlotInfo", "SlotStatus", "default_manager",
]

FORMAT_ID = "game-state-save"
ENVELOPE_VERSION = 1
DEFAULT_SLOT_NAMES: tuple[str, ...] = ("slot1", "slot2", "slot3")
PROJECT_SAVE_DIR = Path(__file__).resolve().parent.parent / "saves"  # legacy location used by pre-V2 builds


def _user_data_root() -> Path:
    """Return a per-user writable data root without requiring administrator access."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base).expanduser() if base else Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"


DEFAULT_SAVE_DIR = _user_data_root() / "AbyssalChoir" / "saves"
SAVE_SUFFIX = ".json"
BACKUP_SUFFIX = ".bak"
MAX_SAVE_BYTES = 8 * 1024 * 1024

_SLOT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

# schema N -> function returning a schema N+1 envelope. Register an entry here when ENVELOPE_VERSION is bumped.
_ENVELOPE_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


# ---- errors -------------------------------------------------------------------
class SaveSystemError(Exception):
    """Base class for every error raised by this module."""

    def __init__(self, message: str, *, slot: Optional[str] = None, path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.slot = slot
        self.path = path


class InvalidSlotError(SaveSystemError, ValueError):
    """The slot number or name is not one of the manager's slots."""


class SaveNotFoundError(SaveSystemError):
    """The slot is empty, or no loadable save exists."""


class SaveCorruptError(SaveSystemError):
    """The file is unreadable, malformed, tampered with, or rejected by ``GameState.from_dict``."""


class SaveVersionError(SaveSystemError):
    """The save was written by a newer or otherwise unsupported version."""


class SaveIOError(SaveSystemError):
    """The save could not be written or deleted. Any existing valid save is left untouched."""


# ---- slot info ----------------------------------------------------------------
class SlotStatus(Enum):
    EMPTY = "empty"
    VALID = "valid"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SlotInfo:
    """Read-only description of one slot, suitable for a load/save menu."""

    slot: str
    index: int                       # 1-based position
    path: Path
    status: SlotStatus
    saved_at: Optional[datetime] = None          # timezone-aware UTC
    saved_at_epoch: Optional[float] = None
    mtime_ns: int = 0
    summary: dict[str, Any] = field(default_factory=dict)   # stage, gold, best_stage, bosses_defeated, difficulty, endless, party
    error: Optional[str] = None
    has_backup: bool = False

    @property
    def is_valid(self) -> bool:
        return self.status is SlotStatus.VALID

    @property
    def is_empty(self) -> bool:
        return self.status is SlotStatus.EMPTY


# ---- helpers ------------------------------------------------------------------
def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name} is not allowed")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _checksum(game: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(game).encode("utf-8")).hexdigest()


def _corrupt(slot: str, path: Path, message: str) -> SaveCorruptError:
    return SaveCorruptError(f"slot '{slot}' ({path}) is damaged: {message}", slot=slot, path=path)


def _validate_slot_names(names: Sequence[str]) -> tuple[str, ...]:
    if isinstance(names, str):
        raise InvalidSlotError("slot_names must be a sequence of names, not a single string")
    result = tuple(names)
    if not result:
        raise InvalidSlotError("at least one slot name is required")
    seen: set[str] = set()
    for name in result:
        if not isinstance(name, str) or not _SLOT_NAME_RE.fullmatch(name):
            raise InvalidSlotError(
                f"invalid slot name {name!r}: use 1-32 letters, digits, '_' or '-', starting with a letter or digit"
            )
        folded = name.lower()
        if folded in _RESERVED_NAMES:
            raise InvalidSlotError(f"slot name {name!r} is reserved by the operating system")
        if folded in seen:
            raise InvalidSlotError(f"duplicate slot name {name!r} (names are case-insensitive)")
        seen.add(folded)
    return result


def _epoch_to_datetime(epoch: float) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _summarize(game: dict[str, Any]) -> dict[str, Any]:
    """Pull display fields out of a validated ``to_dict()`` payload (raw stored values)."""

    def _int(key: str) -> int:
        value = game.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    party: list[dict[str, str]] = []
    players = game.get("players")
    if isinstance(players, list):
        for entry in players:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str) and isinstance(entry.get("class"), str):
                party.append({"name": entry["name"], "class": entry["class"]})
    difficulty = game.get("difficulty")
    return {
        "stage": _int("stage"),
        "gold": _int("gold"),
        "best_stage": _int("best_stage"),
        "bosses_defeated": _int("bosses_defeated"),
        "difficulty": difficulty if isinstance(difficulty, str) else "",
        "endless": game.get("endless") is True,
        "party": party,
    }


def _migrate_envelope(env: dict[str, Any], slot: str, path: Path) -> dict[str, Any]:
    schema = env.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        raise _corrupt(slot, path, "missing or invalid 'schema'")
    if schema > ENVELOPE_VERSION:
        raise SaveVersionError(
            f"slot '{slot}' ({path}) uses save schema {schema}, but this build supports up to {ENVELOPE_VERSION}; "
            "it was probably written by a newer version of the game",
            slot=slot, path=path,
        )
    while schema < ENVELOPE_VERSION:
        step = _ENVELOPE_MIGRATIONS.get(schema)
        if step is None:
            raise SaveVersionError(
                f"slot '{slot}' ({path}) uses save schema {schema}, and no upgrade path to {ENVELOPE_VERSION} exists",
                slot=slot, path=path,
            )
        env = step(dict(env))
        upgraded = env.get("schema")
        if isinstance(upgraded, bool) or not isinstance(upgraded, int) or upgraded <= schema:
            raise _corrupt(slot, path, f"migration from schema {schema} failed")
        schema = upgraded
    return env


def _validate_envelope(raw: Any, slot: str, path: Path, mtime: float) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _corrupt(slot, path, "top-level JSON value must be an object")
    if "format" not in raw:
        # Legacy file: a bare GameState.to_dict() payload.
        if "version" not in raw or "players" not in raw:
            raise _corrupt(slot, path, "not a recognised save file")
        raw = {
            "format": FORMAT_ID,
            "schema": ENVELOPE_VERSION,
            "saved_at_epoch": mtime,
            "sha256": _checksum(raw),
            "game": raw,
        }
    if raw.get("format") != FORMAT_ID:
        raise _corrupt(slot, path, f"unexpected file format {raw.get('format')!r}")
    env = _migrate_envelope(raw, slot, path)

    epoch = env.get("saved_at_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch) or epoch < 0:
        raise _corrupt(slot, path, "missing or invalid 'saved_at_epoch'")
    digest = env.get("sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise _corrupt(slot, path, "missing or invalid 'sha256'")
    game = env.get("game")
    if not isinstance(game, dict):
        raise _corrupt(slot, path, "missing or invalid 'game' payload")
    try:
        actual = _checksum(game)
    except (TypeError, ValueError, RecursionError) as exc:
        raise _corrupt(slot, path, f"game payload cannot be hashed: {exc}") from exc
    if actual != digest:
        raise _corrupt(slot, path, "checksum mismatch (the file was modified or partially written)")
    return env


def _build_state(game: dict[str, Any], slot: str, path: Path) -> GameState:
    try:
        return GameState.from_dict(game)
    except UnsupportedSaveVersionError as exc:
        raise SaveVersionError(f"slot '{slot}' ({path}): {exc}", slot=slot, path=path) from exc
    except SaveDataError as exc:
        raise _corrupt(slot, path, str(exc)) from exc
    except Exception as exc:  # from_dict drives game-side hooks; never let one crash a menu
        raise _corrupt(slot, path, f"unexpected {type(exc).__name__} while restoring state: {exc}") from exc


def _fsync_directory(directory: Path) -> None:
    """Best effort: persist the rename itself (POSIX only)."""
    if os.name != "posix":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


# ---- manager ------------------------------------------------------------------
class SaveManager:
    """Named-slot save/load manager. Safe to share between threads."""

    def __init__(
        self,
        save_dir: Optional[os.PathLike[str] | str] = None,
        slot_names: Sequence[str] = DEFAULT_SLOT_NAMES,
    ) -> None:
        self._names = _validate_slot_names(slot_names)
        self._index = {name: i for i, name in enumerate(self._names, start=1)}
        self._dir = Path(save_dir).expanduser() if save_dir is not None else DEFAULT_SAVE_DIR
        self._migrate_legacy = save_dir is None
        self._lock = threading.RLock()

    # ---- basic info -----------------------------------------------------
    @property
    def save_dir(self) -> Path:
        return self._dir

    @property
    def slot_names(self) -> tuple[str, ...]:
        return self._names

    def ensure_directory(self) -> Path:
        """Create the saves directory, safely migrate legacy saves, and confirm writability."""
        directory = self._dir
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise SaveIOError(f"cannot create save directory '{directory}': {exc}", path=directory) from exc
        if not directory.is_dir():
            raise SaveIOError(f"save path '{directory}' is not a directory", path=directory)
        if not os.access(directory, os.W_OK | os.X_OK):
            raise SaveIOError(f"save directory '{directory}' is not writable", path=directory)
        if self._migrate_legacy:
            self._migrate_legacy_files(directory)
            self._migrate_legacy = False
        return directory

    @staticmethod
    def _migrate_legacy_files(directory: Path) -> None:
        """Copy legacy project-local JSON files once; never delete the originals."""
        legacy = PROJECT_SAVE_DIR
        try:
            if legacy.resolve() == directory.resolve() or not legacy.is_dir():
                return
            if any(directory.iterdir()):
                return  # the user-data directory already has data; never overwrite it
            candidates = [p for p in legacy.iterdir()
                          if p.is_file() and (p.name.endswith(".json") or p.name.endswith(".json.bak"))]
            for source in candidates:
                target = directory / source.name
                # Destination is empty by the check above; copy, do not move, to preserve rollback.
                shutil.copy2(source, target)
        except OSError as exc:
            raise SaveIOError(
                f"could not migrate legacy saves from '{legacy}' to '{directory}': {exc}; "
                "the original files were left in place", path=directory
            ) from exc

    def slot_path(self, slot: int | str) -> Path:
        name, _ = self._resolve(slot)
        return self._dir / f"{name}{SAVE_SUFFIX}"

    def _resolve(self, slot: int | str) -> tuple[str, int]:
        if isinstance(slot, int) and not isinstance(slot, bool):
            if 1 <= slot <= len(self._names):
                return self._names[slot - 1], slot
        elif isinstance(slot, str):
            key = slot.strip()
            if key in self._index:
                return key, self._index[key]
        raise InvalidSlotError(
            f"unknown save slot {slot!r}; valid slots: "
            + ", ".join(f"{i} ({n})" for i, n in enumerate(self._names, start=1))
        )

    @staticmethod
    def _backup_path(path: Path) -> Path:
        return path.with_name(path.name + BACKUP_SUFFIX)

    # ---- reading --------------------------------------------------------
    def _read_envelope(self, path: Path, slot: str) -> dict[str, Any]:
        try:
            info = path.stat()
        except FileNotFoundError:
            raise SaveNotFoundError(f"slot '{slot}' is empty (no file at {path})", slot=slot, path=path) from None
        except OSError as exc:
            raise _corrupt(slot, path, f"cannot access file: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise _corrupt(slot, path, "path is not a regular file")
        if info.st_size == 0:
            raise _corrupt(slot, path, "file is empty")
        if info.st_size > MAX_SAVE_BYTES:
            raise _corrupt(slot, path, f"file is larger than the {MAX_SAVE_BYTES} byte limit")
        try:
            with path.open("rb") as handle:
                payload = handle.read(MAX_SAVE_BYTES + 1)
        except OSError as exc:
            raise _corrupt(slot, path, f"cannot read file: {exc}") from exc
        if len(payload) > MAX_SAVE_BYTES:
            raise _corrupt(slot, path, f"file is larger than the {MAX_SAVE_BYTES} byte limit")
        try:
            raw = json.loads(payload.decode("utf-8-sig"), parse_constant=_reject_constant)
        except (ValueError, RecursionError) as exc:  # includes UnicodeDecodeError and JSONDecodeError
            raise _corrupt(slot, path, f"invalid JSON: {exc}") from exc
        return _validate_envelope(raw, slot, path, info.st_mtime)

    def inspect(self, slot: int | str, *, deep: bool = True) -> SlotInfo:
        """Describe a slot without raising for bad files.

        With ``deep=True`` the payload is also run through ``GameState.from_dict`` so that
        ``VALID`` means "will actually load". ``deep=False`` only checks the file and checksum.
        """
        name, index = self._resolve(slot)
        path = self.slot_path(name)
        has_backup = self._backup_path(path).is_file()
        base = {"slot": name, "index": index, "path": path, "has_backup": has_backup}
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        try:
            env = self._read_envelope(path, name)
            if deep:
                _build_state(env["game"], name, path)
        except SaveNotFoundError:
            return SlotInfo(status=SlotStatus.EMPTY, **base)
        except SaveVersionError as exc:
            return SlotInfo(status=SlotStatus.UNSUPPORTED, mtime_ns=mtime_ns, error=str(exc), **base)
        except SaveCorruptError as exc:
            return SlotInfo(status=SlotStatus.CORRUPT, mtime_ns=mtime_ns, error=str(exc), **base)
        epoch = float(env["saved_at_epoch"])
        return SlotInfo(
            status=SlotStatus.VALID,
            saved_at=_epoch_to_datetime(epoch),
            saved_at_epoch=epoch,
            mtime_ns=mtime_ns,
            summary=_summarize(env["game"]),
            **base,
        )

    def list_slots(self, *, deep: bool = True) -> list[SlotInfo]:
        """``SlotInfo`` for every slot, in slot order."""
        return [self.inspect(name, deep=deep) for name in self._names]

    @staticmethod
    def _recency(info: SlotInfo) -> tuple[float, int, int]:
        return (info.saved_at_epoch or 0.0, info.mtime_ns, -info.index)

    def latest_slot(self, *, deep: bool = True) -> Optional[SlotInfo]:
        """Newest valid slot (by save time, then file mtime), or ``None``."""
        valid = [info for info in self.list_slots(deep=deep) if info.is_valid]
        return max(valid, key=self._recency) if valid else None

    def has_save(self) -> bool:
        """True if at least one slot can be loaded. Reads files, so cache it rather than calling per frame."""
        return self.latest_slot() is not None

    def load(self, slot: int | str, *, allow_backup: bool = False) -> GameState:
        """Load a slot into a new ``GameState``.

        Raises ``SaveNotFoundError`` (empty), ``SaveCorruptError``, ``SaveVersionError`` or
        ``InvalidSlotError``. With ``allow_backup=True`` a damaged primary falls back to the
        ``.bak`` copy of the previous valid save.
        """
        name, _ = self._resolve(slot)
        path = self.slot_path(name)
        try:
            return _build_state(self._read_envelope(path, name)["game"], name, path)
        except SaveCorruptError as primary:
            backup = self._backup_path(path)
            if not backup.is_file():
                raise
            if not allow_backup:
                raise SaveCorruptError(
                    f"{primary} A backup of the previous save exists; retry with allow_backup=True.",
                    slot=name, path=path,
                ) from primary
            try:
                return _build_state(self._read_envelope(backup, name)["game"], name, backup)
            except SaveSystemError:
                raise primary from None

    def continue_latest(self) -> tuple[SlotInfo, GameState]:
        """Load the newest save that actually loads; older slots are tried if newer ones fail.

        Raises ``SaveNotFoundError`` (with per-slot reasons) when nothing can be loaded.
        """
        infos = self.list_slots(deep=False)
        candidates = sorted((i for i in infos if i.is_valid), key=self._recency, reverse=True)
        problems = [i.error for i in infos if i.error]
        for info in candidates:
            try:
                return info, self.load(info.slot)
            except SaveSystemError as exc:
                problems.append(str(exc))
        message = "no save available to continue"
        if problems:
            message += ": " + " | ".join(problems)
        raise SaveNotFoundError(message, path=self._dir)

    # ---- writing --------------------------------------------------------
    def save(self, slot: int | str, state: GameState, *, verify: bool = True) -> SlotInfo:
        """Atomically write ``state`` to ``slot`` and return its ``SlotInfo``.

        Nothing on disk changes unless the new data serialises, passes ``GameState.from_dict``
        (``verify=True``), is written to a temp file in the same directory, and re-reads cleanly.
        Only then is the temp file moved over the slot; the previous valid save is kept as ``.bak``.
        Raises ``SaveIOError`` on any failure, leaving the existing save intact.
        """
        if not isinstance(state, GameState):
            raise TypeError(f"state must be a GameState, got {type(state).__name__}")
        name, _ = self._resolve(slot)
        path = self.slot_path(name)

        try:
            data = state.to_dict()
            game_text = json.dumps(data, allow_nan=False)
        except Exception as exc:  # to_dict() reaches into every party member and the inventory
            raise SaveIOError(
                f"cannot save slot '{name}': game state could not be serialised "
                f"({type(exc).__name__}: {exc}); existing save left untouched",
                slot=name, path=path,
            ) from exc
        game = json.loads(game_text)  # the exact form that will be on disk
        if verify:
            try:
                GameState.from_dict(json.loads(game_text))
            except Exception as exc:
                raise SaveIOError(
                    f"cannot save slot '{name}': the state would not load back "
                    f"({type(exc).__name__}: {exc}); existing save left untouched",
                    slot=name, path=path,
                ) from exc

        epoch = time.time()
        envelope = {
            "format": FORMAT_ID,
            "schema": ENVELOPE_VERSION,
            "saved_at": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds"),
            "saved_at_epoch": epoch,
            "sha256": _checksum(game),
            "game": game,
        }
        try:
            payload = json.dumps(envelope, indent=2, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SaveIOError(f"cannot save slot '{name}': {exc}", slot=name, path=path) from exc
        if len(payload) > MAX_SAVE_BYTES:
            raise SaveIOError(
                f"cannot save slot '{name}': save is {len(payload)} bytes, over the {MAX_SAVE_BYTES} byte limit",
                slot=name, path=path,
            )

        with self._lock:
            directory = self.ensure_directory()
            self._atomic_write(directory, path, name, payload)
        return self.inspect(name, deep=False)

    def _atomic_write(self, directory: Path, path: Path, slot: str, payload: bytes) -> None:
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(directory))
        except OSError as exc:
            raise SaveIOError(f"cannot save slot '{slot}': cannot create temp file in {directory}: {exc}",
                              slot=slot, path=path) from exc
        tmp = Path(tmp_name)
        try:
            try:
                handle = os.fdopen(fd, "wb")
            except BaseException:
                os.close(fd)
                raise
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                self._read_envelope(tmp, slot)  # what hit the disk must parse and match its checksum
            except SaveSystemError as exc:
                raise SaveIOError(f"cannot save slot '{slot}': written data failed verification ({exc}); "
                                  "existing save left untouched", slot=slot, path=path) from exc
            self._rotate_backup(path, slot)
            os.replace(tmp, path)
            _fsync_directory(directory)
        except SaveIOError:
            raise
        except OSError as exc:
            raise SaveIOError(f"cannot save slot '{slot}' to {path}: {exc}; existing save left untouched",
                              slot=slot, path=path) from exc
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass  # already moved into place, or never created

    CORRUPT_KEEP = 3

    def _quarantine_damaged(self, path: Path) -> None:
        """Best effort: copy a non-empty damaged slot file to ``<slot>.json.corrupt-<ms>`` (newest few kept)."""
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return
            target = path.with_name(f"{path.name}.corrupt-{int(time.time() * 1000)}")
            shutil.copyfile(path, target)
            older = sorted(path.parent.glob(f"{path.name}.corrupt-*"))
            for stale in older[:-self.CORRUPT_KEEP]:
                stale.unlink()
        except OSError:
            pass  # preserving evidence must never block the player's save

    def _rotate_backup(self, path: Path, slot: str) -> None:
        """Copy the current slot file to ``.bak`` if (and only if) it is itself a valid save. Best effort."""
        try:
            self._read_envelope(path, slot)
        except SaveSystemError:
            # Damaged primary: never replace a good backup with it, but do not let the next save
            # silently destroy it either -- keep a quarantined copy for inspection or manual recovery.
            self._quarantine_damaged(path)
            return
        backup = self._backup_path(path)
        staging = backup.with_name(f".{backup.name}.tmp")
        try:
            shutil.copyfile(path, staging)
            os.replace(staging, backup)
        except OSError:
            try:
                staging.unlink()
            except OSError:
                pass

    def delete(self, slot: int | str) -> bool:
        """Delete a slot and its backup. Returns True if a save file existed."""
        name, _ = self._resolve(slot)
        path = self.slot_path(name)
        existed = False
        with self._lock:
            for target in (path, self._backup_path(path)):
                try:
                    target.unlink()
                    existed = existed or target == path
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise SaveIOError(f"cannot delete '{target}': {exc}", slot=name, path=target) from exc
        return existed


_default_manager: Optional[SaveManager] = None
_default_lock = threading.Lock()


def default_manager() -> SaveManager:
    """Shared ``SaveManager`` using ``DEFAULT_SAVE_DIR`` and ``DEFAULT_SLOT_NAMES``."""
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = SaveManager()
        return _default_manager
