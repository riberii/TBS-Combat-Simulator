"""Validated, versioned local settings with atomic writes and safe defaults."""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

SETTINGS_SCHEMA = 1


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value} is not allowed in settings")


DEFAULT_SETTINGS: dict[str, Any] = {
    "schema": SETTINGS_SCHEMA,
    "music_volume": 0.55,
    "sfx_volume": 0.80,
    "muted": False,
    "fullscreen": False,
    "screen_shake": True,
    "particles": True,
    "reduced_motion": False,
    "r2_art": True,          # R2: use the generated portrait/title/icon art when its files are present
    "r2_models": True,       # R2: draw heroes as anime models (off = the original procedural models)
}


class SettingsError(RuntimeError):
    """Settings could not be parsed or persisted safely."""


class SettingsStore:
    """Stores user preferences outside the project tree; corrupt input is never overwritten silently."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    @staticmethod
    def defaults() -> dict[str, Any]:
        return dict(DEFAULT_SETTINGS)

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return self.defaults()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise SettingsError(f"Cannot read settings at {self.path}: {exc}") from exc
            if not isinstance(raw, dict):
                raise SettingsError(f"Settings file {self.path} must contain a JSON object; it was preserved.")
            schema = raw.get("schema", 1)
            if isinstance(schema, bool) or not isinstance(schema, int) or schema > SETTINGS_SCHEMA or schema < 1:
                raise SettingsError(f"Unsupported settings schema in {self.path}: {schema!r}; file preserved.")
            data = self.defaults()
            for key in ("music_volume", "sfx_volume"):
                value = raw.get(key, data[key])
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise SettingsError(f"Invalid {key} in {self.path}; expected a number in [0, 1]; file preserved.")
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise SettingsError(f"Invalid {key} in {self.path}; expected a finite number in [0, 1]; file preserved.")
                data[key] = max(0.0, min(1.0, numeric))
            for key in ("muted", "fullscreen", "screen_shake", "particles", "reduced_motion", "r2_art", "r2_models"):
                value = raw.get(key, data[key])
                if not isinstance(value, bool):
                    raise SettingsError(f"Invalid {key} in {self.path}; expected true/false; file preserved.")
                data[key] = value
            data["schema"] = SETTINGS_SCHEMA
            return data

    def save(self, settings: dict[str, Any]) -> None:
        # Validate through the same contract used on read before modifying disk.
        candidate = dict(settings)
        candidate["schema"] = SETTINGS_SCHEMA
        for key in ("music_volume", "sfx_volume"):
            value = candidate.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(f"Invalid {key}: expected a number in [0, 1].")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise SettingsError(f"Invalid {key}: expected a finite number in [0, 1].")
            candidate[key] = max(0.0, min(1.0, numeric))
        for key in ("muted", "fullscreen", "screen_shake", "particles", "reduced_motion", "r2_art", "r2_models"):
            if not isinstance(candidate.get(key), bool):
                raise SettingsError(f"Invalid {key}: expected true/false.")
        payload = json.dumps({key: candidate[key] for key in DEFAULT_SETTINGS}, indent=2,
                             ensure_ascii=False, allow_nan=False) + "\n"
        with self._lock:
            tmp_path: Path | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, raw_path = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
                tmp_path = Path(raw_path)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_path, self.path)
                tmp_path = None
            except OSError as exc:
                raise SettingsError(f"Cannot safely save settings to {self.path}: {exc}") from exc
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
