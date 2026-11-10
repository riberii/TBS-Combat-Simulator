"""V3: animation + layout state for the combat card tray (pure Python, no pygame, unit-tested).

``HandAnimator.update(view, dt)`` consumes the card events of a ``systems.hand_view.HandView`` (draw / play / exhaust /
discard / mulligan), keeps one animated slot per card in the hand, and exposes ``slots`` and ``ghosts`` for the painter.
If the animation state ever disagrees with the real hand it is rebuilt from the hand, so a missed or truncated event can
only cost an animation, never show the wrong cards.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final, Optional

CARD_W: Final[int] = 112
CARD_H: Final[int] = 156
REGION_L: Final[int] = 124           # tray area: right of the pile counters, left of the command panel
REGION_R: Final[int] = 790
Y_PEEK: Final[int] = 566             # only the top ~44px shows above the party cards
Y_RAISED: Final[int] = 440
Y_SELECTED: Final[int] = 418
Y_PENDING: Final[int] = 522
PILE_POS: Final[tuple[float, float]] = (62.0, 640.0)
PLAY_POS: Final[tuple[float, float]] = (960.0, 360.0)
GHOST_TTL: Final[float] = 0.5
FOLLOW: Final[float] = 14.0          # exponential follow rate (1/s)


@dataclass
class Slot:
    ref: str
    x: float
    y: float
    alpha: float = 0.0


@dataclass
class Ghost:
    ref: str
    x: float
    y: float
    tx: float
    ty: float
    kind: str                         # play / exhaust / discard
    age: float = 0.0
    ttl: float = GHOST_TTL

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.age / self.ttl))

    def pos(self) -> tuple[float, float]:
        e = 1.0 - (1.0 - self.progress) ** 3
        return self.x + (self.tx - self.x) * e, self.y + (self.ty - self.y) * e

    @property
    def alpha(self) -> float:
        return 1.0 - self.progress


def layout(n: int, selected: int, focused: bool, pending: int) -> list[tuple[float, float]]:
    """Target top-left corner for each of ``n`` cards."""
    if n <= 0:
        return []
    avail = REGION_R - REGION_L
    step = 0.0 if n == 1 else min(CARD_W + 8.0, (avail - CARD_W) / (n - 1))
    total = CARD_W + step * (n - 1)
    left = REGION_L + (avail - total) / 2.0
    out: list[tuple[float, float]] = []
    for i in range(n):
        if focused:
            y = Y_SELECTED if i == selected else Y_RAISED
        elif i == pending:
            y = Y_PENDING
        else:
            y = Y_PEEK
        out.append((left + step * i, float(y)))
    return out


@dataclass
class HandAnimator:
    slots: list[Slot] = field(default_factory=list)
    ghosts: list[Ghost] = field(default_factory=list)
    uid: Optional[int] = None
    seen: dict[int, int] = field(default_factory=dict)      # hero uid -> last card-event serial applied

    # -- events ------------------------------------------------------------------------------------
    def _apply(self, kind: str, ref: str, index: int, pos: dict[int, tuple[float, float]]) -> None:
        if kind == "draw":
            slot = Slot(ref, PILE_POS[0], PILE_POS[1], 0.0)
            i = index if 0 <= index <= len(self.slots) else len(self.slots)
            self.slots.insert(i, slot)
        elif kind in ("play", "exhaust", "discard"):
            if 0 <= index < len(self.slots) and self.slots[index].ref == ref:
                s = self.slots.pop(index)
                tx, ty = (PILE_POS if kind == "discard" else PLAY_POS)
                self.ghosts.append(Ghost(ref, s.x, s.y, tx, ty, kind))
        elif kind == "mulligan":
            for s in self.slots:
                self.ghosts.append(Ghost(s.ref, s.x, s.y, PILE_POS[0], PILE_POS[1], "discard"))
            self.slots = []

    def update(self, view: Any, dt: float) -> None:
        dt = max(0.0, min(0.1, dt))
        if view is None:
            self._advance_ghosts(dt)
            return
        if view.hero_uid != self.uid:
            self.uid = view.hero_uid
            self.slots, self.ghosts = [], []
        seen = self.seen.get(view.hero_uid, 0)
        for serial, kind, ref, index in view.events:
            if serial > seen:
                self._apply(kind, ref, index, {})
                seen = serial
        self.seen[view.hero_uid] = max(seen, view.event_serial)
        refs = [c.ref for c in view.cards]
        if [s.ref for s in self.slots] != refs:          # drifted (missed event, swap, test code editing the hand)
            old = self.slots
            self.slots = [old[i] if i < len(old) and old[i].ref == r else Slot(r, PILE_POS[0], PILE_POS[1], 0.0)
                          for i, r in enumerate(refs)]
        targets = layout(len(self.slots), view.selected, view.focused, view.pending)
        k = 1.0 - math.exp(-FOLLOW * dt)
        for s, (tx, ty) in zip(self.slots, targets):
            s.x += (tx - s.x) * k
            s.y += (ty - s.y) * k
            s.alpha = min(1.0, s.alpha + dt * 5.0)
        self._advance_ghosts(dt)

    def _advance_ghosts(self, dt: float) -> None:
        for g in self.ghosts:
            g.age += dt
        self.ghosts = [g for g in self.ghosts if g.age < g.ttl][:16]

    def settle(self, view: Any) -> None:
        """Snap everything to its final position (used by screenshots / tests)."""
        for _ in range(40):
            self.update(view, 0.1)
