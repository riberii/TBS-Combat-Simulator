"""Fallen Angel restraint trials (R2): a data-driven, anti-spam challenge library.

Why this exists
    The R1 "Break Restraint" was a mash QTE, so repeatedly hitting Space was the universally best answer.
    Every trial here is built so that blind mashing is *not* optimal:
      * ``ThrashTrial`` (the only mash-like trial) runs through ``SpamGuard``: a minimum accepted interval,
        fatigue that makes faster-than-sustainable presses worth nothing, and a rote-hand detector.
      * Alternating / rhythm / rune / conditional / precision trials punish repeated or off-pattern input
        (slips) instead of rewarding volume.
    Holding a key never helps either: the game never enables key-repeat and ``SpamGuard`` rejects presses
    closer together than a human can legitimately produce.

Pure logic, no pygame import. The UI feeds key *names* (pygame.key.name) and reads ``render_data()``.
Every trial exposes ``solution_script()`` -> [(seconds_since_start, key, text)], a timed input list that
solves it. ``tests/test_restraint_trials.py`` replays those scripts to prove each trial is solvable and
that naive spam/hold scripts are not.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Iterable, Optional, Sequence

from core.config import QteKind
from systems.qte_system import ANGEL_WORDS, ARROWS, QTE, TypingQTE

Script = list[tuple[float, str, str]]

TIER_NAMES = {1: "Initiate", 2: "Bound", 3: "Condemned", 4: "Judgment"}
MAX_TIER = 4
OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up"}
CLOCKWISE = {"left": "up", "up": "right", "right": "down", "down": "left"}
GLYPH = {"left": "◄", "up": "▲", "right": "►", "down": "▼"}
# Keys a trial may ever ask for. validate_trial() rejects anything else ("unavailable input").
VALID_KEYS = frozenset(set(ARROWS) | {"space", "e", "a", "d"} | set("abcdefghijklmnopqrstuvwxyz"))

LITURGY_WORDS: tuple[str, ...] = (
    "excommunicate", "transfiguration", "consubstantial", "indefatigable", "incorruptible",
    "ecclesiastical", "contemplation", "supplication", "intercession", "propitiation",
    "benediction", "absolutionist", "interdiction", "reconsecration", "sanctification",
    "perpetuation", "inexorability", "unforgiveness", "predestination", "annunciation",
)
TRIAL_WORDS: tuple[str, ...] = tuple(dict.fromkeys(ANGEL_WORDS + LITURGY_WORDS))


def clamp_tier(tier: int) -> int:
    return max(1, min(MAX_TIER, int(tier)))


# ---------------------------------------------------------------------------------------------------
# anti-spam
# ---------------------------------------------------------------------------------------------------
class SpamGuard:
    """Turns raw presses into progress weights in [0, 1] so volume alone cannot win.

    * ``min_interval``: presses closer than this are rejected (also catches OS key-repeat bursts) and add a
      small fatigue penalty.
    * fatigue: each accepted press adds ``per_press``; it drains at ``decay`` per second. Weight is
      ``1 - fatigue``, so a sustainable pace (~4-5 presses/s) keeps weight high while 9+/s drives it to 0.
    * rote detector: if the last ``robot_samples`` accepted intervals have a standard deviation under
      ``robot_stdev`` seconds (a macro/turbo key; humans are 10-40 ms), weight is quartered.
    """

    def __init__(self, min_interval: float = 0.11, per_press: float = 0.12, decay: float = 0.6,
                 reject_penalty: float = 0.04, robot_stdev: float = 0.004, robot_samples: int = 10) -> None:
        self.min_interval = min_interval
        self.per_press = per_press
        self.decay = decay
        self.reject_penalty = reject_penalty
        self.robot_stdev = robot_stdev
        self.robot_samples = robot_samples
        self.fatigue = 0.0
        self.last_t: Optional[float] = None
        self._intervals: Deque[float] = deque(maxlen=robot_samples)
        self.mechanical = False
        self.accepted = 0
        self.rejected = 0

    def fatigue_at(self, now: float) -> float:
        if self.last_t is None:
            return self.fatigue
        return max(0.0, self.fatigue - self.decay * max(0.0, now - self.last_t))

    def press(self, now: float) -> float:
        """Register a press at time ``now`` (seconds). Returns the progress weight (0 if rejected)."""
        f = self.fatigue_at(now)
        if self.last_t is not None and now - self.last_t < self.min_interval:
            self.rejected += 1
            self.fatigue = min(1.2, f + self.reject_penalty)
            # do not move last_t: a held/auto-repeating key cannot "reset" its own spacing
            return 0.0
        if self.last_t is not None:
            self._intervals.append(now - self.last_t)
        self.last_t = now
        self.accepted += 1
        weight = max(0.0, 1.0 - f)
        self.fatigue = min(1.2, f + self.per_press)
        self.mechanical = (len(self._intervals) >= self.robot_samples
                           and statistics.pstdev(self._intervals) < self.robot_stdev)
        return weight * (0.25 if self.mechanical else 1.0)

    def clone(self) -> "SpamGuard":
        c = SpamGuard(self.min_interval, self.per_press, self.decay, self.reject_penalty,
                      self.robot_stdev, self.robot_samples)
        c.fatigue, c.last_t, c._intervals = self.fatigue, self.last_t, deque(self._intervals, maxlen=self.robot_samples)
        c.mechanical, c.accepted, c.rejected = self.mechanical, self.accepted, self.rejected
        return c


# ---------------------------------------------------------------------------------------------------
# base mixin
# ---------------------------------------------------------------------------------------------------
class TrialMixin:
    """Shared trial surface (feedback, slips, quality, UI data). Mixed into QTE subclasses."""

    family = "trial"
    rule_text = ""
    tier = 1
    slips = 0
    max_slips = 0
    feedback = ""
    last_ok: Optional[bool] = None

    def _init_trial(self, tier: int, max_slips: int, title: str, rule: str) -> None:
        self.tier = clamp_tier(tier)
        self.max_slips = max(0, int(max_slips))
        self.slips = 0
        self.title = title
        self.rule_text = rule
        self.feedback = ""
        self.last_ok = None

    def _slip(self, why: str) -> None:
        self.slips += 1
        self.feedback, self.last_ok = why, False
        if self.slips > self.max_slips:
            self.finish(False)  # type: ignore[attr-defined]

    def _ok(self, msg: str) -> None:
        self.feedback, self.last_ok = msg, True

    @property
    def quality(self) -> str:
        if not getattr(self, "success", False):
            return "failed"
        return "flawless" if self.slips == 0 else "ragged"

    @property
    def tier_name(self) -> str:
        return TIER_NAMES[clamp_tier(self.tier)]

    def render_data(self) -> dict[str, Any]:
        limit = float(getattr(self, "limit", 0.0))
        elapsed = float(getattr(self, "elapsed", 0.0))
        data = {
            "family": self.family, "title": self.title, "rule": self.rule_text, "tier": self.tier,
            "tier_name": self.tier_name, "slips": self.slips, "max_slips": self.max_slips,
            "feedback": self.feedback, "last_ok": self.last_ok, "limit": limit,
            "time_left": max(0.0, limit - elapsed), "done": bool(getattr(self, "done", False)),
        }
        data.update(self._extra())
        return data

    def _extra(self) -> dict[str, Any]:
        return {}

    def solution_script(self) -> Script:  # pragma: no cover - overridden
        raise NotImplementedError

    @property
    def hint(self) -> str:  # QTE's abstract property
        return self.rule_text


class Trial(TrialMixin, QTE):
    kind = QteKind.TRIAL

    def __init__(self, limit: float, tier: int, max_slips: int, title: str, rule: str) -> None:
        QTE.__init__(self, limit)
        self._init_trial(tier, max_slips, title, rule)

    def handle_key(self, key: str, text: str = "") -> None:  # pragma: no cover - overridden
        raise NotImplementedError


def _jitter(i: int) -> float:
    """Deterministic +-15 ms wobble so scripted 'human' input does not look like a macro."""
    return (0.0, 0.012, -0.009, 0.015, -0.014, 0.006, -0.011, 0.01)[i % 8]


# ---------------------------------------------------------------------------------------------------
# 1. Thrash - the only mash-like trial, throttled by SpamGuard
# ---------------------------------------------------------------------------------------------------
class ThrashTrial(Trial):
    family = "thrash"
    KEYS = frozenset({"e", "space"})

    def __init__(self, target: float, tier: int, title: str = "STRAIN AGAINST THE LINKS", guard: Optional[SpamGuard] = None) -> None:
        self.target = float(target)
        self.progress_units = 0.0
        self.guard = guard or SpamGuard()
        self._script, best_time = self._plan()
        super().__init__(best_time * 1.5 + 1.0, tier, 99, title,
                         "Strain with [E]/[SPACE], but pace yourself: mashing tires you out and wastes the effort.")

    def _plan(self) -> tuple[Script, float]:
        """Search paced strategies with a fresh guard; the best one defines the limit (limit = 1.5x best + 1s)."""
        best: Optional[tuple[float, Script]] = None
        for gap in (0.16, 0.18, 0.2, 0.22, 0.25, 0.28, 0.32):
            g = SpamGuard(self.guard.min_interval, self.guard.per_press, self.guard.decay, self.guard.reject_penalty,
                          self.guard.robot_stdev, self.guard.robot_samples)
            t, prog, script = 0.0, 0.0, []
            for i in range(400):
                t += gap + _jitter(i)
                w = g.press(t)
                script.append((round(t, 4), "space" if i % 2 == 0 else "e", ""))
                prog += w
                if prog >= self.target:
                    break
            if prog >= self.target and (best is None or t < best[0]):
                best = (t, script)
        assert best is not None, "ThrashTrial target unreachable with paced input"
        return best[1], best[0]

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or key not in self.KEYS:
            return
        w = self.guard.press(self.elapsed)
        if w <= 0.0:
            self.feedback, self.last_ok = "TOO FAST - you are exhausted", False
            return
        self.progress_units += w
        if self.guard.mechanical:
            self.feedback, self.last_ok = "A rote hand: the seal barely feels it", False
        else:
            self._ok("RATTLE" if w < 0.7 else "STRAIN")
        if self.progress_units >= self.target:
            self.finish(True)

    @property
    def progress(self) -> float:  # type: ignore[override]
        return min(1.0, self.progress_units / self.target)

    def _extra(self) -> dict[str, Any]:
        return {"progress": self.progress, "fatigue": min(1.0, self.guard.fatigue_at(self.elapsed)),
                "mechanical": self.guard.mechanical}

    def solution_script(self) -> Script:
        return list(self._script)


# ---------------------------------------------------------------------------------------------------
# 2. Alternating keys
# ---------------------------------------------------------------------------------------------------
class AlternatingTrial(Trial):
    family = "alternate"

    def __init__(self, keys: tuple[str, str], needed: int, tier: int, max_slips: int,
                 title: str = "ALTERNATING HANDS", min_interval: float = 0.045) -> None:
        if keys[0] == keys[1]:
            raise ValueError("alternating keys must differ")
        self.keys = keys
        self.needed = needed
        self.count = 0
        self.last_key: Optional[str] = None
        self.min_interval = min_interval
        self._last_t: Optional[float] = None
        limit = needed * 0.34 + 2.2
        a, b = (k.upper() if len(k) == 1 else k.upper() for k in keys)
        super().__init__(limit, tier, max_slips, title,
                         f"Alternate [{a}] and [{b}], starting with [{a}]. The same key twice is a slip.")

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or key not in self.keys:
            return
        if self._last_t is not None and self.elapsed - self._last_t < self.min_interval:
            self.feedback, self.last_ok = "too fast to count", False
            return
        self._last_t = self.elapsed
        expected = self.keys[0] if self.last_key is None else (self.keys[1] if self.last_key == self.keys[0] else self.keys[0])
        if key == expected:
            self.count += 1
            self.last_key = key
            self._ok(f"{self.count}/{self.needed}")
            if self.count >= self.needed:
                self.finish(True)
        else:
            self.count = max(0, self.count - 2)
            self.last_key = key
            self._slip("Same hand twice - the chain bites back" if self.last_key else "Wrong start key")

    def _extra(self) -> dict[str, Any]:
        return {"progress": self.count / self.needed, "keys": self.keys, "next_key": self.keys[0] if self.last_key is None else
                (self.keys[1] if self.last_key == self.keys[0] else self.keys[0]), "count": self.count, "needed": self.needed}

    def solution_script(self) -> Script:
        out, t = [], 0.0
        for i in range(self.needed):
            t += 0.17 + _jitter(i)
            out.append((round(t, 4), self.keys[i % 2], ""))
        return out


# ---------------------------------------------------------------------------------------------------
# 3. Rhythm / counter-rhythm
# ---------------------------------------------------------------------------------------------------
class RhythmTrial(Trial):
    family = "rhythm"
    LEAD_BEATS = 4

    def __init__(self, bpm: float, hits: int, tier: int, max_slips: int, window: float = 0.14,
                 counter: bool = False, title: Optional[str] = None) -> None:
        self.period = 60.0 / bpm
        self.hits = hits
        self.window = window
        self.counter = counter
        offset = self.period / 2.0 if counter else 0.0
        self.targets = [self.LEAD_BEATS * self.period + i * self.period + offset for i in range(hits)]
        self._claimed = [False] * hits
        self.hits_done = 0
        self.family = "counter" if counter else "rhythm"
        limit = self.targets[-1] + window + 0.6
        rule = ("Press [SPACE] BETWEEN the beats - on the off-beat '&'." if counter
                else "Press [SPACE] exactly on the beat once the count-in ends.")
        super().__init__(limit, tier, max_slips, title or ("COUNTER-RHYTHM" if counter else "THE CHOIR'S TOLL"), rule)

    def _tick(self, dt: float) -> None:
        for i, t in enumerate(self.targets):
            if not self._claimed[i] and self.elapsed > t + self.window:
                self._claimed[i] = True
                self._slip("Missed the beat")
                if self.done:
                    return

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or key != "space":
            return
        now = self.elapsed
        if now < self.targets[0] - self.window - (0.0 if not self.counter else 0.0) and now < self.LEAD_BEATS * self.period - self.window:
            self.feedback, self.last_ok = "wait for the count-in", None
            return
        best, best_d = -1, 1e9
        for i, t in enumerate(self.targets):
            if not self._claimed[i] and abs(now - t) < best_d:
                best, best_d = i, abs(now - t)
        if best >= 0 and best_d <= self.window:
            self._claimed[best] = True
            self.hits_done += 1
            self._ok("ON THE BEAT" if best_d < self.window / 2 else "close")
            if self.hits_done >= self.hits:
                self.finish(True)
        else:
            self._slip("Off the beat")

    def beat_phase(self) -> float:
        """0..1 position inside the current beat (UI metronome)."""
        return (self.elapsed / self.period) % 1.0

    def _extra(self) -> dict[str, Any]:
        nxt = next((t for i, t in enumerate(self.targets) if not self._claimed[i]), self.targets[-1])
        return {"progress": self.hits_done / self.hits, "period": self.period, "beat_phase": self.beat_phase(),
                "counter": self.counter, "window": self.window, "next_target_in": nxt - self.elapsed,
                "count_in": self.elapsed < self.LEAD_BEATS * self.period, "hits_done": self.hits_done, "hits": self.hits}

    def solution_script(self) -> Script:
        return [(round(t, 4), "space", "") for t in self.targets]


# ---------------------------------------------------------------------------------------------------
# 4. Rune sequence with a rule that must be observed first
# ---------------------------------------------------------------------------------------------------
RUNE_RULES = {
    "direct": ("ECHO", "Repeat each rune exactly."),
    "mirror": ("MIRROR", "Press the OPPOSITE direction of each rune."),
    "reverse": ("REVERSAL", "Press the runes in REVERSE order."),
    "shift": ("TURNING WHEEL", "Press the NEXT direction clockwise: left>up>right>down>left."),
}


class RuneSequenceTrial(Trial):
    family = "rune"

    def __init__(self, runes: Sequence[str], mode: str, tier: int, max_slips: int = 0,
                 title: Optional[str] = None, hide_rule_after_show: bool = False) -> None:
        if mode not in RUNE_RULES:
            raise ValueError(f"unknown rune rule {mode!r}")
        self.runes = list(runes)
        if not self.runes or any(r not in ARROWS for r in self.runes):
            raise ValueError("runes must be non-empty arrow names")
        self.mode = mode
        self.index = 0
        self.show_time = 1.3 + 0.5 * len(self.runes)
        self.hide_rule_after_show = hide_rule_after_show
        name, text = RUNE_RULES[mode]
        super().__init__(self.show_time + 1.7 * len(self.runes) + 2.5, tier, max_slips, title or f"RUNE TRIAL: {name}", text)

    def expected(self) -> list[str]:
        if self.mode == "direct":
            return list(self.runes)
        if self.mode == "mirror":
            return [OPPOSITE[r] for r in self.runes]
        if self.mode == "reverse":
            return self.runes[::-1]
        return [CLOCKWISE[r] for r in self.runes]

    @property
    def showing(self) -> bool:
        return self.elapsed < self.show_time

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or self.showing or key not in ARROWS:
            return
        want = self.expected()[self.index]
        if key == want:
            self.index += 1
            self._ok(f"{self.index}/{len(self.runes)}")
            if self.index >= len(self.runes):
                self.finish(True)
        else:
            self._slip(f"Wrong rune - the {RUNE_RULES[self.mode][0].lower()} rule demanded {want.upper()}")

    def _extra(self) -> dict[str, Any]:
        rule_visible = self.showing or not self.hide_rule_after_show
        return {"showing": self.showing, "runes": list(self.runes) if self.showing else [], "glyphs": [GLYPH[r] for r in self.runes],
                "mode": self.mode, "rule_name": RUNE_RULES[self.mode][0], "rule_visible": rule_visible,
                "progress": self.index / len(self.runes), "index": self.index, "length": len(self.runes),
                "show_left": max(0.0, self.show_time - self.elapsed)}

    def solution_script(self) -> Script:
        t = self.show_time + 0.25
        out = []
        for i, k in enumerate(self.expected()):
            t += 0.38 + _jitter(i)
            out.append((round(t, 4), k, ""))
        return out


# ---------------------------------------------------------------------------------------------------
# 5. Conditional sequence: observe a colour->key table, then apply it
# ---------------------------------------------------------------------------------------------------
SIGIL_COLOURS = ("crimson", "violet", "silver")


class ConditionalTrial(Trial):
    family = "conditional"

    def __init__(self, mapping: dict[str, str], prompts: Sequence[str], tier: int, max_slips: int,
                 hide_table: bool, rule_time: float = 2.6, title: str = "SIGIL COURT") -> None:
        if set(mapping) != set(SIGIL_COLOURS) or len(set(mapping.values())) != 3 or any(v not in ARROWS for v in mapping.values()):
            raise ValueError("mapping must assign three distinct arrow keys to the three sigils")
        if not prompts or any(p not in mapping for p in prompts):
            raise ValueError("prompts must be non-empty sigil names")
        self.mapping = dict(mapping)
        self.prompts = list(prompts)
        self.hide_table = hide_table
        self.rule_time = rule_time
        self.index = 0
        super().__init__(rule_time + 1.5 * len(self.prompts) + 3.0, tier, max_slips, title,
                         "Learn which arrow answers each sigil, then answer every sigil that appears.")

    @property
    def observing(self) -> bool:
        return self.elapsed < self.rule_time

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or self.observing or key not in ARROWS:
            return
        want = self.mapping[self.prompts[self.index]]
        if key == want:
            self.index += 1
            self._ok(f"{self.index}/{len(self.prompts)}")
            if self.index >= len(self.prompts):
                self.finish(True)
        else:
            self._slip(f"{self.prompts[self.index].title()} answers {want.upper()}, not {key.upper()}")

    def _extra(self) -> dict[str, Any]:
        table_visible = self.observing or not self.hide_table
        return {"observing": self.observing, "table": dict(self.mapping) if table_visible else {}, "table_visible": table_visible,
                "current": None if self.observing or self.index >= len(self.prompts) else self.prompts[self.index],
                "progress": self.index / len(self.prompts), "index": self.index, "length": len(self.prompts),
                "observe_left": max(0.0, self.rule_time - self.elapsed)}

    def solution_script(self) -> Script:
        t = self.rule_time + 0.25
        out = []
        for i, p in enumerate(self.prompts):
            t += 0.42 + _jitter(i)
            out.append((round(t, 4), self.mapping[p], ""))
        return out


# ---------------------------------------------------------------------------------------------------
# 6. Precision: several timed stops, each faster and narrower
# ---------------------------------------------------------------------------------------------------
def _tri(x: float) -> float:
    """Triangle wave 0..1..0 with period 2."""
    x = x % 2.0
    return x if x <= 1.0 else 2.0 - x


class PrecisionTrial(Trial):
    family = "precision"

    def __init__(self, rng: random.Random, stages: int, speed: float, zone: float, tier: int, max_slips: int,
                 title: str = "HAIRLINE SEAL") -> None:
        self.stages = stages
        self.stage = 0
        self.speeds = [speed * (1.12 ** i) for i in range(stages)]
        self.zones = [max(0.03, zone * (0.88 ** i)) for i in range(stages)]
        self.centres = [rng.uniform(0.22, 0.78) for _ in range(stages)]
        self.phases = [rng.uniform(0.0, 2.0) for _ in range(stages)]
        self.stage_t = 0.0
        limit = sum(2.2 / s for s in self.speeds) + 1.5 * stages + 2.0
        super().__init__(limit, tier, max_slips, title, "Press [SPACE] when the cursor crosses the bright seam. Every stop is faster and narrower.")

    def _tick(self, dt: float) -> None:
        self.stage_t += dt

    def cursor(self) -> float:
        i = min(self.stage, self.stages - 1)
        return _tri(self.phases[i] + self.speeds[i] * self.stage_t)

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done or key != "space":
            return
        i = self.stage
        if abs(self.cursor() - self.centres[i]) <= self.zones[i] / 2.0:
            self.stage += 1
            self.stage_t = 0.0
            self._ok(f"STOP {self.stage}/{self.stages}")
            if self.stage >= self.stages:
                self.finish(True)
        else:
            self._slip("Missed the seam")
            self.stage_t = 0.0 if False else self.stage_t  # the cursor keeps sweeping; no free reset

    @property
    def zone(self) -> tuple[float, float]:
        i = min(self.stage, self.stages - 1)
        return (self.centres[i] - self.zones[i] / 2.0, self.centres[i] + self.zones[i] / 2.0)

    def _extra(self) -> dict[str, Any]:
        return {"cursor": self.cursor(), "zone": self.zone, "stage": min(self.stage + 1, self.stages), "stages": self.stages,
                "progress": self.stage / self.stages}

    def solution_script(self) -> Script:
        out, t = [], 0.0
        for i in range(self.stages):
            dt = 0.0
            step = 1.0 / 480.0
            while dt < 12.0:
                pos = _tri(self.phases[i] + self.speeds[i] * dt)
                if dt > 0.35 and abs(pos - self.centres[i]) <= self.zones[i] * 0.2:
                    break
                dt += step
            t += dt
            out.append((round(t, 4), "space", ""))
        return out


# ---------------------------------------------------------------------------------------------------
# 7. Forbidden word (exact transcription)
# ---------------------------------------------------------------------------------------------------
class ForbiddenWordTrial(TrialMixin, TypingQTE):
    """Exact transcription. ``echo=True`` hides the word after a short reveal (type it from memory)."""

    family = "word"

    def __init__(self, word: str, tier: int, limit: Optional[float] = None, fatal: bool = True, echo: bool = False,
                 title: str = "FORBIDDEN WORD") -> None:
        if not word or not word.isascii() or not word.isalpha():
            raise ValueError("forbidden words must be ASCII letters")
        self.echo = echo
        self.reveal_time = 2.2 if echo else 0.0
        base = limit if limit is not None else max(5.2, 2.7 + len(word) * 0.34 - min(0.8, tier * 0.08))
        TypingQTE.__init__(self, word, limit=base + self.reveal_time, fatal_mistake=fatal)
        self._init_trial(tier, 0 if fatal else 99, title, "")
        self.rule_text = (f"Type {word.upper()} exactly. One wrong letter fails immediately." if fatal else
                          f"Type {word.upper()} exactly. A wrong letter resets progress.")
        if echo:
            self.rule_text = "Memorise the word, then type it from memory. One wrong letter fails."

    @property
    def revealed(self) -> bool:
        return (not self.echo) or self.elapsed < self.reveal_time

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done:
            return
        if not self.revealed and self.elapsed < self.reveal_time:
            return
        if self.echo and self.elapsed < self.reveal_time:
            return
        before = self.slips
        TypingQTE.handle_key(self, key, text)
        if self.slips > before:
            self.feedback, self.last_ok = "Wrong letter", False
        elif len(self.typed):
            self._ok(f"{len(self.typed)}/{len(self.word)}")

    def _extra(self) -> dict[str, Any]:
        shown = self.word if self.revealed else "".join("•" for _ in self.word[len(self.typed):])
        return {"word": self.word, "typed": self.typed, "revealed": self.revealed, "echo": self.echo,
                "remaining_display": (self.word[len(self.typed):] if self.revealed else shown), "progress": self.progress,
                "fatal": self.fatal_mistake}

    @property
    def hint(self) -> str:  # type: ignore[override]
        return self.rule_text

    def solution_script(self) -> Script:
        t = self.reveal_time + 0.3
        out = []
        for i, ch in enumerate(self.word):
            t += 0.21 + _jitter(i)
            out.append((round(t, 4), ch, ch))
        return out


# ---------------------------------------------------------------------------------------------------
# 8. Multi-stage seal
# ---------------------------------------------------------------------------------------------------
class SealBreakTrial(Trial):
    """Chains several trials; every stage must be solved, in order. A failed stage fails the seal."""

    family = "seal"

    def __init__(self, stages: Sequence[Trial], tier: int, title: str = "SEAL OF JUDGMENT") -> None:
        if len(stages) < 2:
            raise ValueError("a seal needs at least two stages")
        self.stages = list(stages)
        self.stage_index = 0
        super().__init__(sum(s.limit for s in stages) + 1.0, tier, 0, title, self.stages[0].rule_text)

    @property
    def current(self) -> Trial:
        return self.stages[min(self.stage_index, len(self.stages) - 1)]

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.elapsed += dt
        cur = self.current
        cur.update(dt)
        self._after_stage(cur)

    def _after_stage(self, cur: Trial) -> None:
        if not cur.done:
            return
        if cur.success:
            self.slips += cur.slips
            self.stage_index += 1
            self._ok(f"Stage {self.stage_index}/{len(self.stages)} broken")
            if self.stage_index >= len(self.stages):
                self.finish(True)
            else:
                self.rule_text = self.stages[self.stage_index].rule_text
        else:
            self.feedback, self.last_ok = cur.feedback or "The seal holds", False
            self.finish(False)

    def handle_key(self, key: str, text: str = "") -> None:
        if self.done:
            return
        cur = self.current
        cur.handle_key(key, text)
        self._after_stage(cur)

    def _extra(self) -> dict[str, Any]:
        cur = self.current.render_data()
        return {"stage_index": min(self.stage_index + 1, len(self.stages)), "stage_count": len(self.stages),
                "inner": cur, "stage_family": self.current.family, "progress": self.stage_index / len(self.stages)}

    @property
    def title_full(self) -> str:
        return f"{self.title} {min(self.stage_index + 1, len(self.stages))}/{len(self.stages)}"

    def solution_script(self) -> Script:
        out: Script = []
        offset = 0.0
        for st in self.stages:
            sc = st.solution_script()
            for t, k, tx in sc:
                out.append((round(offset + t, 4), k, tx))
            offset += sc[-1][0]
        return out


# ---------------------------------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TrialDef:
    id: str
    family: str
    title: str
    tiers: tuple[int, int]
    restraints: tuple[str, ...]          # Restraint enum names this trial is themed for; () = generic
    build: Callable[[random.Random, int], TrialMixin]
    boss: Optional[str] = None           # substring of a boss name (case-insensitive)
    blurb: str = ""

    def allows(self, tier: int) -> bool:
        return self.tiers[0] <= tier <= self.tiers[1]


def _pick_dirs(rng: random.Random, n: int) -> list[str]:
    seq: list[str] = []
    for _ in range(n):
        choices = [d for d in ARROWS if not seq or d != seq[-1]]
        seq.append(rng.choice(choices))
    return seq


def _pick_word(rng: random.Random, tier: int) -> str:
    lo = 11 + tier
    pool = [w for w in TRIAL_WORDS if len(w) >= 12 and len(w) <= lo + 4] or list(TRIAL_WORDS)
    return rng.choice(pool)


def _thrash(rng: random.Random, tier: int) -> TrialMixin:
    return ThrashTrial((14, 18, 22, 26)[clamp_tier(tier) - 1], tier)


def _alt(rng: random.Random, tier: int) -> TrialMixin:
    keys = ("a", "d") if rng.random() < 0.5 else ("left", "right")
    return AlternatingTrial(keys, (14, 18, 22, 28)[clamp_tier(tier) - 1], tier, max_slips=(3, 2, 1, 1)[clamp_tier(tier) - 1])


def _rhythm(rng: random.Random, tier: int) -> TrialMixin:
    t = clamp_tier(tier)
    return RhythmTrial(bpm=(84, 96, 108, 120)[t - 1], hits=(5, 6, 7, 8)[t - 1], tier=tier, max_slips=(2, 1, 1, 0)[t - 1],
                       window=(0.16, 0.14, 0.12, 0.10)[t - 1])


def _counter(rng: random.Random, tier: int) -> TrialMixin:
    t = clamp_tier(tier)
    return RhythmTrial(bpm=(80, 90, 100, 110)[t - 1], hits=(5, 6, 7, 8)[t - 1], tier=tier, max_slips=(2, 1, 1, 0)[t - 1],
                       window=(0.16, 0.14, 0.12, 0.10)[t - 1], counter=True)


def _rune(mode: str) -> Callable[[random.Random, int], TrialMixin]:
    def build(rng: random.Random, tier: int) -> TrialMixin:
        t = clamp_tier(tier)
        n = (4, 5, 6, 7)[t - 1] if mode != "direct" else (4, 5, 6, 8)[t - 1]
        return RuneSequenceTrial(_pick_dirs(rng, n), mode, tier, max_slips=(1, 0, 0, 0)[t - 1], hide_rule_after_show=t >= 3)
    return build


def _cond(rng: random.Random, tier: int) -> TrialMixin:
    t = clamp_tier(tier)
    dirs = list(ARROWS)
    rng.shuffle(dirs)
    mapping = dict(zip(SIGIL_COLOURS, dirs[:3]))
    n = (4, 5, 7, 9)[t - 1]
    prompts = [rng.choice([c for c in SIGIL_COLOURS if not out or c != out[-1]]) for out in [[]] for _ in range(1)]
    prompts = []
    for _ in range(n):
        prompts.append(rng.choice([c for c in SIGIL_COLOURS if not prompts or c != prompts[-1]]))
    return ConditionalTrial(mapping, prompts, tier, max_slips=(2, 1, 1, 0)[t - 1], hide_table=t >= 2)


def _precision(stages: int, bump: int = 0) -> Callable[[random.Random, int], TrialMixin]:
    def build(rng: random.Random, tier: int) -> TrialMixin:
        t = clamp_tier(tier)
        return PrecisionTrial(rng, stages, speed=0.82 + 0.1 * t, zone=0.13 - 0.01 * t, tier=tier, max_slips=max(0, 2 - t // 2 + bump))
    return build


def _word(echo: bool = False) -> Callable[[random.Random, int], TrialMixin]:
    def build(rng: random.Random, tier: int) -> TrialMixin:
        return ForbiddenWordTrial(_pick_word(rng, tier), tier, echo=echo)
    return build


def _seal(*makers: Callable[[random.Random, int], TrialMixin], title: str = "SEAL OF JUDGMENT") -> Callable[[random.Random, int], TrialMixin]:
    def build(rng: random.Random, tier: int) -> TrialMixin:
        return SealBreakTrial([m(rng, max(1, tier - 1)) for m in makers], tier, title)  # type: ignore[arg-type]
    return build


TRIAL_DEFS: tuple[TrialDef, ...] = (
    # --- single-family trials -------------------------------------------------------------------------------
    TrialDef("thrash_anchor", "thrash", "STRAIN AGAINST THE ANCHOR", (1, 4), ("ANCHOR",), _thrash, blurb="Paced strain; spam exhausts you."),
    TrialDef("alt_manacles", "alternate", "ALTERNATING HANDS", (1, 4), ("MANACLES",), _alt, blurb="Left, right, left - one hand twice is a slip."),
    TrialDef("rhythm_wings", "rhythm", "THE CHOIR'S TOLL", (1, 4), ("BARBED_WINGS",), _rhythm, blurb="Match the bell on the beat."),
    TrialDef("counter_wings", "counter", "COUNTER-RHYTHM", (2, 4), ("BARBED_WINGS", "MANACLES"), _counter, blurb="Strike between the beats."),
    TrialDef("rune_echo", "rune", "RUNE TRIAL: ECHO", (1, 2), ("DEPRIVATION",), _rune("direct"), blurb="Repeat the runes you saw."),
    TrialDef("rune_mirror", "rune", "RUNE TRIAL: MIRROR", (1, 4), ("DEPRIVATION",), _rune("mirror"), blurb="Press the opposite of each rune."),
    TrialDef("rune_reverse", "rune", "RUNE TRIAL: REVERSAL", (2, 4), ("DEPRIVATION", "IRON_GAG"), _rune("reverse"), blurb="Last rune first."),
    TrialDef("rune_wheel", "rune", "RUNE TRIAL: TURNING WHEEL", (3, 4), ("DEPRIVATION",), _rune("shift"), blurb="One step clockwise."),
    TrialDef("sigil_court", "conditional", "SIGIL COURT", (1, 4), ("IRON_GAG", "SABATONS"), _cond, blurb="Learn the table, then answer each sigil."),
    TrialDef("seam_sabatons", "precision", "HAIRLINE SEAL", (1, 4), ("SABATONS",), _precision(2), blurb="Stop the cursor on the seam."),
    TrialDef("seam_triple", "precision", "TRIPLE SEAM", (3, 4), ("SABATONS", "ANCHOR"), _precision(3), blurb="Three faster stops."),
    TrialDef("word_gag", "word", "FORBIDDEN WORD", (1, 4), ("IRON_GAG", "MANACLES"), _word(False), blurb="Exact transcription."),
    TrialDef("word_echo", "word", "ECHOED WORD", (3, 4), ("IRON_GAG",), _word(True), blurb="Type it after it fades."),
    # --- multi-stage seals ---------------------------------------------------------------------------------------
    TrialDef("seal_two", "seal", "TWOFOLD SEAL", (2, 4), (), _seal(_alt, _rune("mirror"), title="TWOFOLD SEAL"), blurb="Hands, then runes."),
    TrialDef("seal_three", "seal", "THREEFOLD SEAL", (3, 4), (), _seal(_rhythm, _cond, _precision(2), title="THREEFOLD SEAL"),
             blurb="Rhythm, sigils, precision."),
    TrialDef("seal_judgment", "seal", "SEAL OF JUDGMENT", (4, 4), (), _seal(_word(False), _rune("reverse"), _counter, title="SEAL OF JUDGMENT"),
             blurb="Word, reversal, counter-rhythm."),
    # --- boss-specific trials --------------------------------------------------------------------------------------
    TrialDef("boss_maelis", "seal", "WARDEN'S TUMBLERS", (1, 4), (), _seal(_precision(2), _alt, title="WARDEN'S TUMBLERS"), boss="maelis",
             blurb="Ten thousand keys: stop the tumblers, then work the lock."),
    TrialDef("boss_orrick", "seal", "CHOIRMASTER'S CADENCE", (1, 4), (), _seal(_rhythm, _counter, title="CHOIRMASTER'S CADENCE"), boss="orrick",
             blurb="Follow the baton, then answer against it."),
    TrialDef("boss_vael", "seal", "THE SILENT THREAD", (1, 4), (), _seal(_rune("mirror"), _cond, _word(False), title="THE SILENT THREAD"), boss="vael",
             blurb="Vael's silence: mirror, sigils, then the unspeakable word."),
)
TRIAL_BY_ID: dict[str, TrialDef] = {d.id: d for d in TRIAL_DEFS}


def validate_trial(trial: TrialMixin) -> None:
    """Raise ValueError if a built trial cannot be solved with available inputs (generation-time guard)."""
    script = trial.solution_script()
    if not script:
        raise ValueError("trial has no solution script")
    last_t = -1.0
    for t, key, _text in script:
        if key not in VALID_KEYS:
            raise ValueError(f"trial requires unavailable input {key!r}")
        if t < last_t:
            raise ValueError("solution script is not time-ordered")
        last_t = t
    if script[-1][0] >= trial.limit - 0.25:  # type: ignore[attr-defined]
        raise ValueError("trial time limit leaves no margin for its own solution")


class TrialLibrary:
    """Seeded, anti-repetition picker over ``TRIAL_DEFS``."""

    def __init__(self, defs: Iterable[TrialDef] = TRIAL_DEFS, recent: int = 6) -> None:
        self.defs = tuple(defs)
        self.history: Deque[str] = deque(maxlen=recent)

    def candidates(self, restraint: Optional[str], tier: int, boss: Optional[str] = None,
                   families: Optional[Sequence[str]] = None) -> list[tuple[TrialDef, float]]:
        tier = clamp_tier(tier)
        boss_l = (boss or "").lower()
        out: list[tuple[TrialDef, float]] = []
        for d in self.defs:
            if not d.allows(tier) or (families and d.family not in families):
                continue
            if d.boss:
                if boss_l and d.boss in boss_l:
                    out.append((d, 5.0))
                continue
            w = 3.0 if restraint and restraint in d.restraints else (1.0 if not d.restraints else 0.4)
            out.append((d, w))
        if not out and families:  # family filter too strict for this tier: relax tier, keep family
            for d in self.defs:
                if d.family in families and not d.boss:
                    out.append((d, 1.0))
        return out

    def pick(self, restraint: Optional[str], tier: int, rng: random.Random, boss: Optional[str] = None,
             families: Optional[Sequence[str]] = None) -> tuple[TrialDef, TrialMixin]:
        tier = clamp_tier(tier)
        cands = self.candidates(restraint, tier, boss, families)
        if not cands:
            cands = [(TRIAL_BY_ID["thrash_anchor"], 1.0)]
        last = self.history[-1] if self.history else None
        if len(cands) > 1:
            cands = [(d, w) for d, w in cands if d.id != last] or cands
        weighted = [(d, w * (0.3 if d.id in self.history else 1.0)) for d, w in cands]
        for _attempt in range(6):
            total = sum(w for _, w in weighted)
            r = rng.uniform(0.0, total)
            acc, chosen = 0.0, weighted[-1][0]
            for d, w in weighted:
                acc += w
                if r <= acc:
                    chosen = d
                    break
            try:
                trial = chosen.build(rng, tier)
                validate_trial(trial)
            except (ValueError, AssertionError):
                weighted = [(d, w) for d, w in weighted if d.id != chosen.id] or [(TRIAL_BY_ID["thrash_anchor"], 1.0)]
                continue
            self.history.append(chosen.id)
            return chosen, trial
        fallback = TRIAL_BY_ID["thrash_anchor"]
        self.history.append(fallback.id)
        return fallback, fallback.build(rng, tier)


def trial_tier(stage: int, tightness: int = 0, restraint_count: int = 0) -> int:
    """Difficulty tier 1-4 (Initiate / Bound / Condemned / Judgment) from stage and how tightly she is bound."""
    return clamp_tier(1 + stage // 4 + (tightness + (1 if restraint_count >= 4 else 0)) // 2)


def run_script(trial: Any, script: Script, dt: float = 1 / 120, tail: float = 0.5) -> bool:
    """Replay a timed input script against a trial (tests/simulations). Returns trial.success."""
    t = 0.0
    for when, key, text in sorted(script, key=lambda s: s[0]):
        while t + 1e-9 < when and not trial.done:
            step = min(dt, when - t)
            trial.update(step)
            t += step
        if trial.done:
            break
        trial.handle_key(key, text)
    end = t + tail
    while not trial.done and t < end:
        trial.update(dt)
        t += dt
    return bool(trial.done and trial.success)


__all__ = [
    "SpamGuard", "TrialMixin", "Trial", "ThrashTrial", "AlternatingTrial", "RhythmTrial", "RuneSequenceTrial", "ConditionalTrial",
    "PrecisionTrial", "ForbiddenWordTrial", "SealBreakTrial", "TrialDef", "TRIAL_DEFS", "TRIAL_BY_ID", "TrialLibrary",
    "validate_trial", "trial_tier", "run_script", "TIER_NAMES", "TRIAL_WORDS",
]
