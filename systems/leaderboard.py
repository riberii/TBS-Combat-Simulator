"""Validated offline run records with atomic JSON writes and idempotent result insertion."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = 1
MAX_RECORDS = 2000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SCORE = 2_000_000


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value} is not allowed in local records")


class LeaderboardError(RuntimeError):
    """The local leaderboard cannot be read or safely written."""


class LocalLeaderboard:
    """Small, offline, mode-aware record table stored beside the existing save slots."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    @staticmethod
    def score(state: Any, won: bool) -> int:
        """Transparent bounded score: stage progress, bosses, levels, coin, and clear bonus."""
        stage = min(999, max(0, int(getattr(state, "best_stage", getattr(state, "stage", 0)) or 0)))
        bosses = min(999, max(0, int(getattr(state, "bosses_defeated", 0) or 0)))
        levels = sum(min(30, max(1, int(getattr(p, "level", 1) or 1))) - 1 for p in getattr(state, "players", ()))
        gold = min(1_000_000, max(0, int(getattr(state, "gold", 0) or 0)))
        return min(2_000_000, stage * 100 + bosses * 350 + levels * 50 + gold // 5 + (750 if won else 0))

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            if self.path.stat().st_size > MAX_FILE_BYTES:
                raise LeaderboardError(f"Local records file {self.path} exceeds the {MAX_FILE_BYTES}-byte safety limit.")
            raw = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        except LeaderboardError:
            raise
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
            raise LeaderboardError(f"Cannot read local records at {self.path}: {exc}") from exc
        schema = raw.get("schema") if isinstance(raw, dict) else None
        if (not isinstance(schema, int) or isinstance(schema, bool) or schema != SCHEMA
                or not isinstance(raw.get("records"), list)):
            raise LeaderboardError(f"Local records file {self.path} has an unsupported or malformed schema.")
        if len(raw["records"]) > MAX_RECORDS:
            raise LeaderboardError(f"Local records file {self.path} contains more than {MAX_RECORDS} records.")
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, source in enumerate(raw["records"]):
            row = index + 1
            if not isinstance(source, dict):
                raise LeaderboardError(f"Local record {row} in {self.path} is not an object.")
            required = ("record_id", "created_utc", "mode", "result", "score", "stage", "seed", "classes", "difficulty")
            if any(key not in source for key in required):
                raise LeaderboardError(f"Local record {row} in {self.path} is missing a required field.")
            record = dict(source)
            if not isinstance(record["record_id"], str) or not record["record_id"] or len(record["record_id"]) > 96:
                raise LeaderboardError(f"Local record {row} has an invalid record_id.")
            if record["record_id"] in seen_ids:
                raise LeaderboardError(f"Local records file {self.path} repeats record_id {record['record_id']!r}.")
            seen_ids.add(record["record_id"])
            if record["mode"] not in ("story", "endless") or record["result"] not in ("victory", "defeat"):
                raise LeaderboardError(f"Local record {row} has an invalid mode/result.")
            limits = {"score": MAX_SCORE, "stage": 999, "bosses": 999, "gold": 1_000_000}
            for key, ceiling in limits.items():
                value = record.get(key, 0)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= ceiling:
                    raise LeaderboardError(f"Local record {row} has invalid {key}.")
            if not isinstance(record["created_utc"], str) or len(record["created_utc"]) > 64:
                raise LeaderboardError(f"Local record {row} has invalid created_utc.")
            try:
                datetime.fromisoformat(record["created_utc"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise LeaderboardError(f"Local record {row} has invalid created_utc.") from exc
            for key, cap in (("seed", 96), ("difficulty", 24)):
                if not isinstance(record[key], str) or len(record[key]) > cap:
                    raise LeaderboardError(f"Local record {row} has invalid {key}.")
            classes = record["classes"]
            if not isinstance(classes, list) or not 1 <= len(classes) <= 3 or not all(
                    isinstance(value, str) and value and len(value) <= 32 for value in classes):
                raise LeaderboardError(f"Local record {row} has invalid class composition.")
            display_name = record.get("display_name", "Player")
            if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 40:
                raise LeaderboardError(f"Local record {row} has invalid display_name.")
            record["display_name"] = display_name.strip()
            records.append(record)
        return records

    def records(self, mode: str = "all", limit: int = 10) -> list[dict[str, Any]]:
        valid_modes = ("all", "story", "endless", "boss_rush", "arena", "daily")
        if mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}")
        limit = max(1, min(100, int(limit)))
        with self._lock:
            items = self._read()
        if mode != "all":
            items = [r for r in items if r["mode"] == mode]
        items.sort(key=lambda r: (-r["score"], -r["stage"], r["created_utc"], r["record_id"]))
        return items[:limit]

    def add_result(self, state: Any, won: bool, run_id: str) -> tuple[dict[str, Any], bool]:
        """Insert once per run_id; returns (record, inserted). Existing duplicate is never duplicated."""
        if not isinstance(run_id, str) or not run_id or len(run_id) > 96:
            raise ValueError("run_id must be a non-empty string up to 96 characters")
        raw_mode = str(getattr(state, "mode", getattr(state, "run_mode", ""))).lower().strip()
        if raw_mode in ("training", "sparring"):
            # Practice runs never enter the competitive leaderboard
            return {
                "record_id": run_id, "display_name": "Player", "mode": "training",
                "result": "practice", "score": 0, "stage": 0, "bosses": 0, "gold": 0, "classes": []
            }, False
        if raw_mode in ("boss_rush", "arena", "daily"):
            mode = raw_mode
        else:
            mode = "endless" if bool(getattr(state, "endless", True)) else "story"
        stage = min(999, max(0, int(getattr(state, "best_stage", getattr(state, "stage", 0)) or 0)))
        record = {
            "record_id": run_id,
            "display_name": "Player",
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "result": "victory" if won else "defeat",
            "score": self.score(state, won),
            "seed": str(getattr(state, "seed", "unknown"))[:96],
            "difficulty": str(getattr(state, "difficulty_name", "Normal"))[:24],
            "stage": stage,
            "bosses": min(999, max(0, int(getattr(state, "bosses_defeated", 0) or 0))),
            "gold": min(1_000_000, max(0, int(getattr(state, "gold", 0) or 0))),
            "classes": [str(getattr(getattr(p, "pclass", "Unknown"), "value", getattr(p, "pclass", "Unknown")))[:32]
                        for p in getattr(state, "players", ())],
        }
        with self._lock:
            records = self._read()
            prior = next((r for r in records if r["record_id"] == run_id), None)
            if prior is not None:
                return prior, False
            records.append(record)
            records = records[-MAX_RECORDS:]
            payload = json.dumps({"schema": SCHEMA, "records": records}, ensure_ascii=False,
                                 indent=2, allow_nan=False) + "\n"
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(tmp, self.path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            except OSError as exc:
                raise LeaderboardError(f"Cannot write local records to {self.path}: {exc}") from exc
        return record, True
