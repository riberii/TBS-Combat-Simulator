"""Restraint trials: the Fallen Angel's "Break Restraint" challenge library (R2).

Replaces the old flat ``MashQTE`` (10+ presses in 3.5 s, trivially beaten by hammering Space) with a
small data-driven library.  Every trial is a normal ``QTE`` subclass, so the combat loop
(``qte.handle_key`` / ``qte.update`` / ``qte.done`` / ``qte.success``) is unchanged.

Rules shared by all trials
    * Time is the QTE's own clock (``self.elapsed``), never wall-clock, so behaviour is deterministic
      and unit-testable.
    * Every trial exposes ``panel_lines`` -> list[(text, role)] which the QTE panel renders generically.
    * Every trial exposes ``is_solvable()``: an ideal player can finish inside ``limit``.

Anti-spam (``PacedMashQTE``)
    * presses closer than ``MIN_GAP`` are *jams* (no progress) - defeats macros / key-repeat bursts;
    * presses faster than ``FAST_GAP`` earn half credit and build *fatigue*;
    * fatigue scales all credit down and only decays with time, so sustained hammering stalls;
    * an even cadence earns full credit, a ragged one is slightly penalised.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from core.config import QteKind
from systems.qte_system import ANGEL_WORDS, ARROWS, QTE, STRUGGLE_KEYS, MemoryQTE, TypingQTE

Line = tuple[str, str]   # (text, role) role in head/body/hint/good/bad


def _is_struggle_key(key: str, text: str) -> bool:
    return key in STRUGGLE_KEYS or (bool(text) and text.lower() == "e")


# ---------------------------------------------------------------------------------------------
# 1. paced mash (anti-spam)
# ---------------------------------------------------------------------------------------------
class PacedMashQTE(QTE):
    kind = QteKind.MASH
    title = "STRAIN THE LINKS: KEEP A STEADY PULL"

    MIN_GAP = 0.07        # faster than this = jam (no credit)
    FAST_GAP = 0.16       # faster than this = half credit + fatigue
    SLOW_GAP = 0.60       # slower than this = reduced credit
    FATIGUE_FAST = 0.14
    FATIGUE_JAM = 0.10
    FATIGUE_GOOD = 0.03
    FATIGUE_DECAY = 0.5   # per second
    FATIGUE_CAP = 0.85
    STEADY_TOL = 0.45     # |gap - prev_gap| / prev_gap allowed for the steady bonus

    def __init__(self, need: float, limit: float) -> None:
        super().__init__(limit)
        self.need = float(need)
        self.credit = 0.0
        self.accepted = 0
        self.jams = 0
        self.fatigue = 0.0
        self.last_press: Optional[float] = None
        self.prev_gap: Optional[float] = None
        self.last_result = ""

    @property
    def progress(self) -> float:
        return min(1.0, self.credit / self.need)

    def _tick(self, dt: float) -> None:
        self.fatigue = max(0.0, self.fatigue - self.FATIGUE_DECAY * dt)

    def handle_key(self, key: str, text: str) -> None:
        if self.done or not _is_struggle_key(key, text):
            return
        gap = float("inf") if self.last_press is None else self.elapsed - self.last_press
        if gap < self.MIN_GAP:
            self.jams += 1
            self.fatigue = min(self.FATIGUE_CAP, self.fatigue + self.FATIGUE_JAM)
            self.last_result = "JAMMED"
            return
        if gap < self.FAST_GAP:
            weight, self.last_result = 0.5, "TOO FAST"
            self.fatigue = min(self.FATIGUE_CAP, self.fatigue + self.FATIGUE_FAST)
        elif gap <= self.SLOW_GAP:
            weight, self.last_result = 1.0, "STEADY"
            self.fatigue = min(self.FATIGUE_CAP, self.fatigue + self.FATIGUE_GOOD)
            if self.prev_gap is not None and abs(gap - self.prev_gap) / self.prev_gap > self.STEADY_TOL:
                weight, self.last_result = 0.7, "RAGGED"
        else:
            weight, self.last_result = 0.6, "SLOW"
        if gap != float("inf"):
            self.prev_gap = gap
        self.last_press = self.elapsed
        self.accepted += 1
        self.credit += weight * (1.0 - self.fatigue)
        if self.credit >= self.need:
            self.finish(True)

    def is_solvable(self) -> bool:
        # An ideal 0.25 s cadence yields 4 credit/s.
        return self.need / 4.0 <= self.limit * 0.75

    @property
    def hint(self) -> str:
        return "Pull in a steady rhythm. Hammering jams the links and tires you out."

    @property
    def panel_lines(self) -> list[Line]:
        tired = int(round(self.fatigue * 100))
        return [
            (f"LINKS LOOSENED {int(self.progress * 100)}%", "head"),
            (f"Fatigue {tired}%   {self.last_result}".rstrip(), "bad" if tired >= 50 else "body"),
            ("Press [SPACE] about 4 times a second. Faster only tires you.", "hint"),
        ]


# ---------------------------------------------------------------------------------------------
# 2. alternating keys
# ---------------------------------------------------------------------------------------------
class AlternatingQTE(QTE):
    kind = QteKind.MEMORY
    title = "RUNE SWAP: ALTERNATE LEFT / RIGHT"
    MAX_STUMBLES = 3
    _MAP = {"left": "left", "a": "left", "right": "right", "d": "right"}

    def __init__(self, need: int, limit: float) -> None:
        super().__init__(limit)
        self.need = int(need)
        self.streak = 0
        self.stumbles = 0
        self.last_side: Optional[str] = None

    def handle_key(self, key: str, text: str) -> None:
        side = self._MAP.get(key)
        if self.done or side is None:
            return
        if side == self.last_side:
            self.stumbles += 1
            self.streak = 0
            if self.stumbles >= self.MAX_STUMBLES:
                self.finish(False)
            return
        self.last_side = side
        self.streak += 1
        if self.streak >= self.need:
            self.finish(True)

    def is_solvable(self) -> bool:
        return self.need * 0.2 <= self.limit * 0.75

    @property
    def hint(self) -> str:
        return "Alternate LEFT and RIGHT. Repeating a side is a stumble and resets the chain."

    @property
    def panel_lines(self) -> list[Line]:
        nxt = "LEFT or RIGHT" if self.last_side is None else ("RIGHT" if self.last_side == "left" else "LEFT")
        return [(f"CHAIN {self.streak}/{self.need}", "head"),
                (f"Next: {nxt}      Stumbles {self.stumbles}/{self.MAX_STUMBLES}",
                 "bad" if self.stumbles else "body"),
                ("Repeating a side resets the chain.", "hint")]


# ---------------------------------------------------------------------------------------------
# 3. conditional sigils (observe the rule, then obey it)
# ---------------------------------------------------------------------------------------------
_OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up"}
_SEAL_COLOURS = ("CRIMSON", "VIOLET", "SILVER", "GILDED")


class ConditionalSigilQTE(QTE):
    kind = QteKind.MEMORY
    title = "SIGIL LAW: OBEY THE RULE"

    def __init__(self, rng: random.Random, length: int, limit: float, inverted: bool = False) -> None:
        super().__init__(limit)
        colours = list(_SEAL_COLOURS[:3])
        arrows = list(ARROWS)
        rng.shuffle(arrows)
        self.rule: dict[str, str] = {c: arrows[i] for i, c in enumerate(colours)}
        self.inverted = bool(inverted)
        self.prompts: list[tuple[str, bool]] = []
        for _ in range(length):
            self.prompts.append((rng.choice(colours), self.inverted and rng.random() < 0.4))
        self.index = 0
        self.slips = 0

    @property
    def sequence(self) -> list[tuple[str, bool]]:
        return self.prompts

    def expected(self) -> str:
        colour, flip = self.prompts[self.index]
        arrow = self.rule[colour]
        return _OPPOSITE[arrow] if flip else arrow

    def handle_key(self, key: str, text: str) -> None:
        if self.done or key not in ARROWS:
            return
        if key == self.expected():
            self.index += 1
            if self.index >= len(self.prompts):
                self.finish(True)
        else:
            self.slips += 1
            self.finish(False)

    def is_solvable(self) -> bool:
        return len(self.prompts) * 0.9 <= self.limit * 0.75 and len(set(self.rule.values())) == len(self.rule)

    @property
    def hint(self) -> str:
        return "Match each sigil colour to its arrow. A wrong arrow breaks the seal."

    @property
    def panel_lines(self) -> list[Line]:
        rule = "   ".join(f"{c} = {a.upper()}" for c, a in self.rule.items())
        if self.done:
            return [("SIGIL LAW", "head"), (rule, "body")]
        colour, flip = self.prompts[self.index]
        shown = f"{'REVERSED ' if flip else ''}{colour}"
        return [(f"SIGIL {self.index + 1}/{len(self.prompts)}:  {shown}", "head"),
                (rule, "body"),
                ("REVERSED sigils want the opposite arrow." if self.inverted else "One wrong arrow fails.", "hint")]


# ---------------------------------------------------------------------------------------------
# 4. counter-rhythm (hit the off-beat)
# ---------------------------------------------------------------------------------------------
class CounterRhythmQTE(QTE):
    kind = QteKind.TIMING
    title = "HOLLOW BEAT: STRIKE BETWEEN THE TOLLS"
    MAX_MISSES = 3

    def __init__(self, need: int, period: float, limit: float, lead_beats: float = 2.0) -> None:
        super().__init__(limit)
        self.need = int(need)
        self.period = float(period)
        self.window = 0.22 * self.period       # half-width of the accepted off-beat window
        self.lead = lead_beats * self.period
        self.hits = 0
        self.misses = 0
        self.last_result = ""
        self._used: set[int] = set()

    def _offbeat_index(self) -> Optional[int]:
        """Index k of the off-beat (k+0.5) period the clock is inside, else None."""
        t = self.elapsed - self.lead
        if t < 0:
            return None
        k = int(t // self.period)
        centre = (k + 0.5) * self.period
        return k if abs(t - centre) <= self.window else None

    @property
    def beat_phase(self) -> float:
        return ((self.elapsed - self.lead) / self.period) % 1.0 if self.elapsed >= self.lead else 0.0

    def handle_key(self, key: str, text: str) -> None:
        if self.done or not _is_struggle_key(key, text):
            return
        k = self._offbeat_index()
        if k is not None and k not in self._used:
            self._used.add(k)
            self.hits += 1
            self.last_result = "OFF-BEAT"
            if self.hits >= self.need:
                self.finish(True)
            return
        self.misses += 1
        self.last_result = "ON THE TOLL" if self.elapsed >= self.lead else "WAIT"
        if self.misses >= self.MAX_MISSES:
            self.finish(False)

    def is_solvable(self) -> bool:
        return self.lead + (self.need + 0.5) * self.period <= self.limit * 0.9

    @property
    def hint(self) -> str:
        return "The bell tolls on the beat. Press [SPACE] exactly halfway between tolls."

    @property
    def panel_lines(self) -> list[Line]:
        wait = self.elapsed < self.lead
        return [(f"OFF-BEATS {self.hits}/{self.need}", "head"),
                ("Listen..." if wait else f"{self.last_result}   Misses {self.misses}/{self.MAX_MISSES}",
                 "body" if not self.misses else "bad"),
                ("Strike between the tolls, never on them.", "hint")]


# ---------------------------------------------------------------------------------------------
# 5. wrappers: forbidden word, rune memory, multi-stage seal
# ---------------------------------------------------------------------------------------------
class RuneMemoryQTE(MemoryQTE):
    title = "RUNE RECALL"

    def is_solvable(self) -> bool:
        return len(self.sequence) * 0.6 <= self.limit * 0.75

    @property
    def panel_lines(self) -> list[Line]:
        names = {"left": "LEFT", "up": "UP", "right": "RIGHT", "down": "DOWN"}
        if self.showing:
            return [("MEMORISE THE RUNES", "head"), ("  ".join(names[k] for k in self.sequence), "body")]
        return [(f"RECALL {self.index}/{len(self.sequence)}", "head"), ("Arrow keys in the same order.", "hint")]


class ForbiddenWordQTE(TypingQTE):
    title = "FORBIDDEN WORD"

    def __init__(self, word: str, limit: float) -> None:
        super().__init__(word, limit, fatal_mistake=True)

    def is_solvable(self) -> bool:
        return len(self.word) * 0.35 + 1.0 <= self.limit * 0.9

    @property
    def panel_lines(self) -> list[Line]:
        return [(f"TYPE: {self.word.upper()}", "head"),
                (f"{self.typed.upper() or '-'}   ({len(self.typed)}/{len(self.word)})", "body"),
                ("One wrong letter fails the seal.", "hint")]


def describe(qte: Any) -> list[Line]:
    lines = getattr(qte, "panel_lines", None)
    return list(lines) if lines else [(str(getattr(qte, "hint", "")), "body")]


class SealStagesQTE(QTE):
    """Run several trials back to back; every stage must succeed."""

    kind = QteKind.MEMORY

    def __init__(self, stages: Sequence[QTE], label: str) -> None:
        if not stages:
            raise ValueError("SealStagesQTE needs at least one stage")
        self.stages = list(stages)
        self.stage_index = 0
        self.label = label
        super().__init__(sum(s.limit for s in self.stages))
        self.title = f"{label.upper()}"

    @property
    def current(self) -> QTE:
        return self.stages[min(self.stage_index, len(self.stages) - 1)]

    @property
    def time_ratio(self) -> float:
        return self.current.time_ratio

    def update(self, dt: float) -> None:
        if self.done:
            return
        stage = self.current
        stage.update(dt)
        self.elapsed = sum(s.elapsed for s in self.stages)
        self._advance()

    def handle_key(self, key: str, text: str) -> None:
        if self.done:
            return
        self.current.handle_key(key, text)
        self._advance()

    def _advance(self) -> None:
        stage = self.current
        if not stage.done:
            return
        if not stage.success:
            self.finish(False)
        elif self.stage_index + 1 >= len(self.stages):
            self.finish(True)
        else:
            self.stage_index += 1

    def is_solvable(self) -> bool:
        return all(getattr(s, "is_solvable", lambda: True)() for s in self.stages)

    @property
    def hint(self) -> str:
        return self.current.hint

    @property
    def panel_lines(self) -> list[Line]:
        head = (f"{self.label.upper()}  -  STAGE {self.stage_index + 1}/{len(self.stages)}", "head")
        return [head, *describe(self.current)]

    # time left display in the QTE panel reads these two
    @property
    def remaining_time(self) -> float:
        return max(0.0, self.current.limit - self.current.elapsed)


# ---------------------------------------------------------------------------------------------
# data-driven library
# ---------------------------------------------------------------------------------------------
Builder = Callable[[random.Random, int], QTE]


def _paced(rng: random.Random, tier: int) -> QTE:
    need = 10 + 2 * tier
    return PacedMashQTE(need, limit=need / 4.0 + 2.5)


def _alternating(rng: random.Random, tier: int) -> QTE:
    need = 8 + 2 * tier
    return AlternatingQTE(need, limit=need * 0.45 + 2.5)


def _sigils(rng: random.Random, tier: int) -> QTE:
    length = min(8, 3 + tier)
    return ConditionalSigilQTE(rng, length, limit=2.0 + 1.4 * length, inverted=tier >= 3)


def _rhythm(rng: random.Random, tier: int) -> QTE:
    need = min(8, 3 + tier)
    period = max(0.42, 0.70 - 0.04 * tier)
    return CounterRhythmQTE(need, period, limit=2.0 * period + (need + 1.5) * period + 3.0)


def _word(rng: random.Random, tier: int) -> QTE:
    word = rng.choice(ANGEL_WORDS)
    return ForbiddenWordQTE(word, limit=max(5.2, 2.7 + len(word) * 0.34 - min(0.8, tier * 0.08)))


def _runes(rng: random.Random, tier: int) -> QTE:
    n = min(7, 3 + tier)
    return RuneMemoryQTE([rng.choice(ARROWS) for _ in range(n)], show_time=0.5 * n + 0.6, limit=2.0 + 0.8 * n)


_FAMILIES: dict[str, Builder] = {
    "paced_mash": _paced, "alternating": _alternating, "conditional": _sigils,
    "counter_rhythm": _rhythm, "typing": _word, "memory": _runes,
}


@dataclass(frozen=True)
class TrialDef:
    id: str
    label: str
    families: tuple[str, ...]        # one family = single trial, several = multi-stage seal
    min_tier: int = 1
    weight: int = 2
    affinity: tuple[str, ...] = ()   # Restraint enum names that favour this trial


TRIAL_LIBRARY: tuple[TrialDef, ...] = (
    TrialDef("paced_pull", "Strain the Links", ("paced_mash",), 1, 3, ("IRON_GAG", "BARBED_WINGS")),
    TrialDef("rune_swap", "Rune Swap", ("alternating",), 1, 2, ("SABATONS", "ANCHOR")),
    TrialDef("sigil_law", "Sigil Law", ("conditional",), 1, 2, ("DEPRIVATION",)),
    TrialDef("forbidden_word", "Forbidden Word", ("typing",), 1, 2, ("MANACLES",)),
    TrialDef("rune_recall", "Rune Recall", ("memory",), 1, 2, ("DEPRIVATION",)),
    TrialDef("hollow_beat", "Hollow Beat", ("counter_rhythm",), 2, 2, ("ANCHOR", "BARBED_WINGS")),
    TrialDef("double_seal", "Double Seal", ("conditional", "paced_mash"), 3, 2),
    TrialDef("oathbreaker", "Oathbreaker's Seal", ("typing", "counter_rhythm"), 4, 2, ("MANACLES",)),
    TrialDef("judgment_seal", "Seal of Judgment", ("alternating", "conditional", "counter_rhythm"), 6, 2),
)
_BY_ID = {d.id: d for d in TRIAL_LIBRARY}


def scale_time(trial: QTE, factor: float) -> None:
    """Give a trial more (factor > 1) time. Multi-stage seals scale every stage."""
    if factor <= 1.0:
        return
    stages = getattr(trial, "stages", None)
    if stages:
        for stage in stages:
            scale_time(stage, factor)
        trial.limit = sum(st.limit for st in stages)
    else:
        trial.limit *= factor


def trial_ids() -> list[str]:
    return [d.id for d in TRIAL_LIBRARY]


def make_trial(trial_id: str, rng: random.Random, tier: int = 1) -> QTE:
    """Build one specific trial (also used by tests to cover every definition)."""
    d = _BY_ID[trial_id]
    tier = max(1, int(tier))
    stages = [_FAMILIES[f](rng, tier) for f in d.families]
    trial = stages[0] if len(stages) == 1 else SealStagesQTE(stages, d.label)
    if len(stages) == 1:
        trial.title = d.label.upper() + ": " + trial.title.split(":", 1)[-1].strip()
    trial.trial_id = d.id                      # type: ignore[attr-defined]
    return trial


def build_trial(rng: random.Random, tier: int = 1, restraints: Sequence[str] = (),
                recent: Sequence[str] = (), tightness: int = 0) -> tuple[QTE, str]:
    """Pick a trial for the current situation.

    * effective tier = tier + tightness (tighter chains demand more mastery);
    * the last two trials are excluded (anti-repetition) unless nothing else qualifies;
    * trials tied to an active restraint are weighted up.
    """
    eff = max(1, int(tier) + max(0, int(tightness)))
    pool = [d for d in TRIAL_LIBRARY if d.min_tier <= eff]
    fresh = [d for d in pool if d.id not in tuple(recent)[-2:]] or pool
    weights = [d.weight + (3 if any(r in d.affinity for r in restraints) else 0) for d in fresh]
    chosen = rng.choices(fresh, weights=weights, k=1)[0]
    trial = make_trial(chosen.id, rng, eff)
    return trial, chosen.id


__all__ = ["PacedMashQTE", "AlternatingQTE", "ConditionalSigilQTE", "CounterRhythmQTE", "SealStagesQTE",
           "RuneMemoryQTE", "ForbiddenWordQTE", "TRIAL_LIBRARY", "build_trial", "make_trial", "trial_ids",
           "describe", "scale_time"]
