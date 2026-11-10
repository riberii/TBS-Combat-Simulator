"""Seeded campaign balance sim (logic only - no rendering, no real time, no real player).

A simple bot plays full runs through the real CombatSystem. Player skill is modelled as a probability of clearing
each QTE/trial (``--skill``); restraint trials are *finished* (not typed) so this measures balance, not QTE
correctness (the unit tests cover that). It is a regression tripwire, not a tuning authority.

Usage: python tools/balance_sim.py [--runs N] [--skill 0.75] [--stages 12] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.headless_bootstrap import install_import_stub_if_missing  # noqa: E402

install_import_stub_if_missing()

from core.config import FINAL_STAGE, PlayerClass  # noqa: E402
from core.game_state import GameState, PlayerConfig  # noqa: E402
from systems.combat_system import CombatSystem, Phase  # noqa: E402

MAX_STEPS = 4000


def _kind(e) -> str:
    """Entry kind; the pre-R2 MenuEntry has no ``kind`` so fall back to its label (lets the sim run on both versions)."""
    k = getattr(e, "kind", None)
    if k is not None:
        return k
    return "items" if str(getattr(e, "label", "")).lower().startswith("items") else ""


def _pick(combat: CombatSystem, rng: random.Random, cards: str = "never") -> None:
    hero = combat.active
    if getattr(combat, "_sim_in_items", False):
        combat._sim_in_items = False
        opts = [i for i, e in enumerate(combat.menu) if e.enabled and _kind(e) != "back"]
        if opts:
            combat.menu_idx = opts[0]
            combat.handle_key("return")
            return
    low = hero is not None and getattr(hero, "max_hp", 0) and hero.hp / hero.max_hp < 0.45
    if low and rng.random() < 0.6:
        for i, e in enumerate(combat.menu):
            if e.enabled and _kind(e) == "items":
                combat._sim_in_items = True
                combat.menu_idx = i
                combat.handle_key("return")
                return
    skip = ("back", "items", "mulligan") + (("cards",) if cards == "never" else ())
    entries = [(i, e) for i, e in enumerate(combat.menu) if e.enabled and _kind(e) not in skip]
    if not entries:
        entries = [(i, e) for i, e in enumerate(combat.menu) if e.enabled and _kind(e) != "back"]
    if not entries:
        combat.handle_key("escape")
        return
    card_opts = [x for x in entries if _kind(x[1]) == "card"]
    if cards == "mixed" and not card_opts and rng.random() < 0.4:
        opener = [x for x in entries if _kind(x[1]) == "cards"]
        if opener:
            combat.menu_idx = opener[0][0]
            combat.handle_key("return")
            return
    dmg = [x for x in entries if _kind(x[1]) == "" and any(w in (x[1].hint or "").lower() for w in ("damage", "deal", "strike", "hit"))]
    if card_opts:
        cdmg = [x for x in card_opts if any(w in (x[1].hint or "").lower() for w in ("damage", "deal"))]
        pool = cdmg or card_opts           # in the card submenu: attack if any attack card is playable
    else:
        pool = dmg or entries
    combat.menu_idx = rng.choice(pool)[0]
    combat.handle_key("return")


def play_fight(state: GameState, rng: random.Random, skill: float, cards: str = "never") -> tuple[bool, int]:
    combat = CombatSystem(state)
    steps = 0
    while combat.phase not in (Phase.VICTORY, Phase.DEFEAT) and steps < MAX_STEPS:
        steps += 1
        if combat.phase is Phase.MENU:
            _pick(combat, rng, cards)
        elif combat.phase is Phase.TARGET:
            combat.handle_key("return")
        elif combat.phase is Phase.QTE:
            q = combat.qte
            if q is not None and not q.done:
                q.finish(rng.random() < skill)
            combat.update(0.0)
        else:
            combat.update(1.0)
    return combat.phase is Phase.VICTORY, steps


def play_run(party: list[PlayerClass], seed: int, skill: float, stages: int, difficulty: str = "Normal", cards: str = "never") -> dict:
    rng = random.Random(seed * 7919 + 13)
    state = GameState(seed=seed)
    state.new_run([PlayerConfig(f"H{i}", c) for i, c in enumerate(party)], difficulty, endless=False)
    reached, rounds = 0, 0
    for stage in range(1, stages + 1):
        state.spawn_encounter()
        won, steps = play_fight(state, rng, skill, cards)
        rounds += steps
        if not won or not state.party_alive:
            return {"won": False, "stage": stage, "steps": rounds, "stuck": steps >= MAX_STEPS}
        state.claim_victory()
        state.rest_party()
        reached = stage
    return {"won": True, "stage": reached, "steps": rounds, "stuck": False}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--skill", type=float, default=0.75)
    ap.add_argument("--stages", type=int, default=FINAL_STAGE)
    ap.add_argument("--cards", choices=("never", "mixed"), default="never",
                    help="'never' = abilities only (comparable with the pre-R2 game); 'mixed' = the bot also plays cards")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    logging.disable(logging.CRITICAL)
    classes = list(PlayerClass)
    configs = [("solo " + c.name, [c]) for c in classes] + [
        ("trio WARRIOR+WITCH+ANGEL", [PlayerClass.WARRIOR, PlayerClass.WITCH, PlayerClass.ANGEL]),
        ("trio TANK+ROGUE+KITSUNE", [PlayerClass.TANK, PlayerClass.ROGUE, PlayerClass.KITSUNE]),
        ("trio VAMPIRE+DRAGONKIN+ANGEL", [PlayerClass.VAMPIRE, PlayerClass.DRAGONKIN, PlayerClass.ANGEL]),
    ]
    rows, stuck, errors = [], 0, 0
    print(f"balance_sim: skill={a.skill} runs/config={a.runs} stages={a.stages} cards={a.cards}")
    print(f"{'party':32s} {'clear%':>7s} {'avg stage':>9s} {'median':>7s}")
    for label, party in configs:
        res = []
        for s in range(a.runs):
            try:
                res.append(play_run(party, 1000 + s, a.skill, a.stages, cards=a.cards))
            except Exception as exc:  # noqa: BLE001 - a crash is a finding, report it
                errors += 1
                print(f"  ERROR {label} seed {1000 + s}: {type(exc).__name__}: {exc}")
        stuck += sum(r["stuck"] for r in res)
        if res:
            clear = 100.0 * sum(r["won"] for r in res) / len(res)
            st = [r["stage"] for r in res]
            rows.append({"party": label, "clear_pct": clear, "avg_stage": statistics.mean(st), "median_stage": statistics.median(st), "runs": len(res)})
            print(f"{label:32s} {clear:6.0f}% {statistics.mean(st):9.1f} {statistics.median(st):7.1f}")
    print(f"errors={errors} stuck_fights={stuck}")
    if a.json:
        Path(a.json).write_text(json.dumps({"skill": a.skill, "rows": rows, "errors": errors, "stuck": stuck}, indent=1))
    return 1 if (errors or stuck) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
