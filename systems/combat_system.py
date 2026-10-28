"""Turn resolution, damage maths, aggro, intercepts, enemy actions and the player menu flow.

Pure logic (no pygame). The UI feeds key names via `handle_key`, calls `update(dt)` and
drains `events` to drive logs and visual effects.

Tactical layer
--------------
* Telegraphs: every round each enemy's intent is announced with an `EventKind.INTENT` event and
  is available on demand through `intent_preview(foe)` (label, hint, damage, target, hits).
  Single-target attacks lock onto a hero at round start; Provoke and Guard intercepts are the
  counter-play. Sensory Deprivation (`intent_hidden`) masks the preview for the acting hero.
* Boss phases: bosses (`Enemy.is_boss`, or any enemy that has shown CHARGE/DEVASTATE) change at
  66% HP (ENRAGED: +20% power, staggered) and 33% HP (DESPERATE: +40% power, extra flurry hit,
  an extra chain on the Fallen Angel, intent re-rolled).
* Every state change the UI cares about is a structured `CombatEvent` (see `EventKind`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional

from core.config import Color, Pal, QteKind, max_single_hit
from entities.base_entity import Ability, BaseEntity, Status, Target
from entities.enemy import Enemy, IntentKind
from entities.player import FallenAngel, Player, Restraint, Tank
from systems.inventory_system import ItemDef, apply_item
from systems.qte_system import ANGEL_WORDS, QTE, TypingQTE, create_qte
from systems.restraint_trials import build_trial, scale_time

if TYPE_CHECKING:
    from core.game_state import GameState

_LOG = logging.getLogger(__name__)

RESOLVE_DELAY = 0.9
ENEMY_DELAY = 0.75
QTE_WATCHDOG = 30.0            # seconds before a stuck QTE is force-failed
MAX_QUEUE_SKIPS = 64           # hard stop for dead/duplicate entries in the turn queue
MAX_STALLED_ROUNDS = 3         # rounds in a row with no actor before the encounter is aborted
GUARD_HEAVY_FACTOR = 0.6       # Guard keeps 60% of heavy / area / boss damage
BOSS_PHASE_THRESHOLDS = (0.66, 0.33)   # HP ratios that open phase 2 and phase 3
BOSS_PHASE_POWER = (1.0, 1.2, 1.4)     # enemy attack multiplier per boss phase
LOW_STAMINA = 20
_PHASE_NAMES = {2: "ENRAGED", 3: "DESPERATE"}
_RESOURCE_ATTRS = ("hp", "stamina", "mana", "lucidity")


class Phase(Enum):
    MENU = "menu"
    TARGET = "target"
    QTE = "qte"
    RESOLVE = "resolve"
    ENEMY = "enemy"
    VICTORY = "victory"
    DEFEAT = "defeat"


class EventKind(Enum):
    DAMAGE = "damage"
    CRIT = "crit"
    HEAL = "heal"
    LOG = "log"
    ALERT = "alert"
    SHAKE = "shake"
    LUNGE = "lunge"
    DEATH = "death"
    # --- structured events for UI popups -------------------------------------------------
    INTENT = "intent"                        # enemy telegraph (uid=foe, amount=dmg/hit, source_uid=target hero)
    INTERCEPT = "intercept"                  # uid=intercepting tank, source_uid=hero that was protected
    BOSS_PHASE = "boss_phase"                # uid=boss, amount=new phase (2 or 3), power=attack multiplier
    RESTRAINT_APPLIED = "restraint_applied"  # uid=angel, amount=chains now worn, text=label
    RESTRAINT_BROKEN = "restraint_broken"    # uid=angel, amount=chains still worn, text=label
    GOLD = "gold"                            # amount=total gold earned (victory only)
    XP = "xp"                                # amount=total XP earned (victory only)
    ERROR = "error"                          # recoverable problem; text explains it
    ACTION = "action"                        # committed player action; data carries action/item key for UI/audio
    LUCIDITY = "lucidity"                    # Fallen Angel lost lucidity; amount is the loss
    DODGE = "dodge"                          # prepared evasion avoids a committed single-target hit


@dataclass
class CombatEvent:
    kind: EventKind
    uid: int = 0
    amount: int = 0
    text: str = ""
    color: Color = Pal.TEXT
    power: float = 0.0
    source_uid: int = 0                      # entity that caused the event (0 = none/unknown)
    data: dict[str, Any] = field(default_factory=dict)   # extra structured payload (see emit sites)


@dataclass
class MenuEntry:
    label: str
    cost: str = ""
    enabled: bool = True
    hint: str = ""
    ability: Optional[Ability] = None
    item: Optional[ItemDef] = None


@dataclass(frozen=True)
class IntentPreview:
    """What the UI should show above an enemy. `hidden` previews carry no information."""
    uid: int
    kind: Optional[IntentKind]
    label: str
    hint: str
    power: float = 0.0
    hits: int = 1
    damage: int = 0            # raw damage per hit before armour / Guard
    target_uid: int = 0        # hero the attack is locked on (0 = random / everyone / none)
    area: bool = False
    hidden: bool = False
    phase: int = 1
    color: Color = Pal.TEXT


_GUARD_CUT = round((1.0 - GUARD_HEAVY_FACTOR) * 100)
_INTENT_INFO: dict[IntentKind, tuple[str, str, Color]] = {
    IntentKind.SKIP: ("Dazed", "Loses its turn.", Pal.DIM),
    IntentKind.ATTACK: ("Attack", "One hit on the marked hero. A guarding Tank intercepts; Provoke redirects.", Pal.TEXT),
    IntentKind.HEAVY: ("Heavy strike", f"Big hit on the marked hero. Guard cuts it by {_GUARD_CUT}%; a guarding Tank intercepts.", Pal.ORANGE),
    IntentKind.MULTI: ("Flurry", "Several hits on random heroes. A guarding Tank intercepts each one.", Pal.TEXT),
    IntentKind.CHARGE: ("Gathering power", "Next turn it DEVASTATES everyone. Stun or burst it down now.", Pal.ORANGE),
    IntentKind.DEVASTATE: ("Devastation", f"Hits every hero, cannot be intercepted. Guard cuts it by {_GUARD_CUT}%.", Pal.RED),
    IntentKind.CURSE: ("Binding curse", "Chains the Fallen Angel and drains lucidity. Break chains or kill it first.", Pal.PURPLE),
}
_DAMAGE_KINDS = frozenset({IntentKind.ATTACK, IntentKind.HEAVY, IntentKind.MULTI, IntentKind.DEVASTATE})
_TARGETED_KINDS = frozenset({IntentKind.ATTACK, IntentKind.HEAVY})


class CombatSystem:
    """Runs one encounter from first round to victory/defeat."""

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.rng = state.rng
        self.events: list[CombatEvent] = []
        self.phase = Phase.RESOLVE
        self.timer = 0.0
        self.round_no = 0
        self.active: Optional[BaseEntity] = None
        self.menu: list[MenuEntry] = []
        self.menu_idx = 0
        self.in_items = False
        self.targets: list[BaseEntity] = []
        self.target_idx = 0
        self.qte: Optional[QTE] = None
        self.rewards: tuple[int, int] = (0, 0)   # (gold, xp) reported on victory
        self._entry: Optional[MenuEntry] = None
        self._target: Optional[BaseEntity] = None
        self._reported: set[int] = set()
        self._acted: set[int] = set()                    # uids that already took a turn this round
        self._locked: dict[int, int] = {}                # foe uid -> hero uid named by the telegraph
        self._intent_sig: dict[int, tuple] = {}          # last announced telegraph per foe
        self._opened: set[int] = set()                   # hero uids that already made their opening strike (perk)
        self._boss_phase: dict[int, int] = {}
        self._boss_like: set[int] = set()
        self._staggered: set[int] = set()
        self._restraint_snap: dict[int, frozenset] = {}
        self._turns_this_round = 0
        self._stalled_rounds = 0
        self._phase_clock = 0.0
        self._outcome_done = False
        self._init_boss_phases()
        self._sync_restraints()
        self._begin_round()

    # ======================= event helpers (used by entities) ===========================
    def _emit(self, kind: EventKind, uid: int = 0, amount: int = 0, text: str = "",
              color: Color = Pal.TEXT, power: float = 0.0, source_uid: int = 0,
              data: Optional[dict[str, Any]] = None) -> None:
        self.events.append(CombatEvent(kind, uid, int(amount), text, color, power, source_uid,
                                       dict(data) if data else {}))

    def drain(self) -> list[CombatEvent]:
        out, self.events = self.events, []
        return out

    def log(self, text: str, color: Color = Pal.TEXT) -> None:
        self.state.add_log(text, color)
        self._emit(EventKind.LOG, text=text, color=color)

    def alert(self, text: str, color: Color = Pal.GOLD) -> None:
        self.state.add_log(text, color)
        self._emit(EventKind.ALERT, text=text, color=color)

    def shake(self, power: float) -> None:
        self._emit(EventKind.SHAKE, power=power)

    def _error(self, text: str) -> None:
        """Recoverable problem: logged for developers, shown to the UI, never raised."""
        _LOG.warning("combat: %s", text)
        self.state.add_log(text, Pal.RED)
        self._emit(EventKind.ERROR, text=text, color=Pal.RED)

    def _guarded(self, label: str, fn: Callable[..., Any], *args: Any) -> bool:
        """Run entity/item code; a crash becomes an ERROR event instead of a dead encounter."""
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 - deliberate: keep the encounter alive
            _LOG.exception("combat: %s raised", label)
            self._error(f"{label} failed; the turn continues.")
            return False
        return True

    def enemies_alive(self) -> list[Enemy]:
        return [e for e in self.state.enemies if e.alive]

    def players_alive(self) -> list[Player]:
        return [p for p in self.state.players if p.alive]

    @property
    def intent_hidden(self) -> bool:
        """Sensory Deprivation hides enemy intent from the acting hero."""
        return isinstance(self.active, Player) and self.active.blackout

    @property
    def pending_entry(self) -> Optional[MenuEntry]:
        """Action currently being targeted, exposed read-only for the combat HUD."""
        return self._entry

    # ============================= damage API ==========================================
    def strike(self, attacker: BaseEntity, defender: BaseEntity, mult: float, *, true_damage: bool = False,
               crit_chance: float = 0.0, force_crit: bool = False) -> int:
        """Resolve one attack. Returns damage dealt (0 if either side is already dead)."""
        if not attacker.alive or not defender.alive:
            return 0
        raw = max(0.0, attacker.attack_power * mult)
        pet = getattr(self.state, "pet", None)
        if isinstance(attacker, Player) and pet == "hound":
            raw *= 1.10
        elif isinstance(defender, Player) and pet == "beetle":
            raw = max(0.0, raw - 3.0)
        if isinstance(attacker, FallenAngel) and attacker.restraints:
            if attacker.release_window > 0:
                attacker.release_window -= 1          # Brief Release: this strike ignores the chains
            else:
                # Remaining bound is never a free cosmetic state: every chain suppresses weapon output.
                bound_factor = max(0.34, 1.0 - 0.105 * len(attacker.restraints) - 0.075 * attacker.tightness)
                raw *= bound_factor
        if isinstance(attacker, Player):
            raw *= self._offence_perks(attacker, defender)
        crit = force_crit or self.rng.random() < min(1.0, max(0.0, crit_chance))
        if crit:
            raw *= 1.8 + (attacker.perk("crit_dmg") if isinstance(attacker, Player) else 0.0)
        dealt = max(0, defender.take_damage(defender.mitigate(raw, true_damage=true_damage)))
        if isinstance(attacker, Player) and dealt > 0 and attacker.perk("lifesteal") > 0 and attacker.alive:
            self.heal(attacker, max(1, int(dealt * attacker.perk("lifesteal"))))
        self._emit(EventKind.CRIT if crit else EventKind.DAMAGE, defender.uid, dealt,
                   source_uid=attacker.uid, data={"crit": crit, "true": true_damage})
        self._emit(EventKind.LUNGE, attacker.uid)
        self.shake(min(1.0, dealt / max(1, defender.max_hp) * 4 + (0.25 if crit else 0.0)))
        attacker.on_deal_damage(dealt)
        defender.on_hit_taken(dealt)
        color = Pal.GREEN if isinstance(attacker, Player) else Pal.RED
        self.log(f"{attacker.name} hits {defender.name} for {dealt}{' (CRIT!)' if crit else ''}.", color)
        self._check_death(defender)
        self._update_boss_phases()
        return dealt

    def hurt_self(self, player: Player, amount: int, *, lethal: bool = False) -> int:
        """Self-inflicted HP cost (Overcast, Writhe...). Never lethal unless asked."""
        if not player.alive:
            return 0
        amount = amount if lethal else min(amount, player.hp - 1)
        if amount <= 0:
            return 0
        dealt = max(0, player.take_damage(amount))
        self._emit(EventKind.DAMAGE, player.uid, dealt, source_uid=player.uid, data={"self": True})
        self._check_death(player)
        return dealt

    def _offence_perks(self, attacker: Player, defender: BaseEntity) -> float:
        """Damage multiplier from skill-tree perks (1.0 when none apply)."""
        mult = 1.0 + attacker.perk("dealt")
        if attacker.hp < attacker.max_hp * 0.5:
            mult += attacker.perk("wounded_dealt")
        if defender.hp < defender.max_hp * 0.4:
            mult += attacker.perk("execute")
        if attacker.uid not in self._opened:
            self._opened.add(attacker.uid)
            mult += attacker.perk("opener")
        return max(0.1, mult)

    def _defence_perks(self, target: Player, dmg: float) -> float:
        """Incoming-damage adjustments from skill-tree perks."""
        dmg *= 1.0 + target.perk("taken")
        if target.hp < target.max_hp * 0.35:
            dmg *= max(0.0, 1.0 - target.perk("laststand"))
        if target.perk("reduce") > 0 and dmg > 0:
            dmg = max(1.0, dmg - target.perk("reduce"))
        return dmg

    def heal(self, target: BaseEntity, amount: int) -> int:
        healed = max(0, target.heal(max(0, amount)))
        if healed > 0:
            self._emit(EventKind.HEAL, target.uid, healed)
        return healed

    def report_rewards(self, gold: int = 0, xp: int = 0) -> None:
        """Emit GOLD / XP popups. Events only: the caller still owns granting the rewards."""
        gold, xp = max(0, int(gold)), max(0, int(xp))
        self.rewards = (gold, xp)
        if gold:
            self._emit(EventKind.GOLD, amount=gold, text=f"+{gold} gold", color=Pal.GOLD)
        if xp:
            self._emit(EventKind.XP, amount=xp, text=f"+{xp} XP", color=Pal.CYAN)

    def _check_death(self, entity: BaseEntity) -> None:
        if not entity.alive and entity.uid not in self._reported:
            self._reported.add(entity.uid)
            self._emit(EventKind.DEATH, entity.uid)
            self.log(f"{entity.name} falls!", Pal.GOLD if isinstance(entity, Enemy) else Pal.RED)
            if isinstance(entity, Player):
                self.state.party_deaths = getattr(self.state, "party_deaths", 0) + 1
            elif isinstance(entity, Enemy) and getattr(entity, "boss", False):
                self.state.elites_slain = getattr(self.state, "elites_slain", 0) + 1

    # ===================== consistency pass (runs after every action) ==================
    def _settle(self) -> None:
        """Clamp resources, report deaths/restraints/phases and refresh telegraphs."""
        for entity in [*self.state.players, *self.state.enemies]:
            self._clamp_resources(entity)
            if entity.alive:
                self._reported.discard(entity.uid)   # revived: a later death must be reported again
            else:
                self._check_death(entity)
        for p in self.state.players:
            if p.alive:
                self.state.lowest_hero_hp = min(getattr(self.state, "lowest_hero_hp", 999), p.hp)
        self._sync_restraints()
        self._update_boss_phases()
        self._refresh_intents()

    @staticmethod
    def _clamp_resources(entity: BaseEntity) -> None:
        for attr in _RESOURCE_ATTRS:
            value = getattr(entity, attr, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
                try:
                    setattr(entity, attr, type(value)(0))
                except (AttributeError, TypeError):
                    pass

    # ============================ restraints ===========================================
    def _sync_restraints(self, source: Optional[BaseEntity] = None) -> None:
        """Diff every Fallen Angel's chains against the last snapshot and announce changes."""
        for hero in self.state.players:
            if not isinstance(hero, FallenAngel):
                continue
            now = frozenset(hero.restraints)
            before = self._restraint_snap.get(hero.uid, frozenset())
            if now == before:
                continue
            self._restraint_snap[hero.uid] = now
            for restraint in Restraint:
                if restraint in now and restraint not in before:
                    if source is not None:
                        self.alert(f"{source.name} binds {hero.name}: {restraint.label}", Pal.PURPLE)
                    else:
                        self.alert(f"{hero.name} is bound: {restraint.label}", Pal.PURPLE)
                    self._emit(EventKind.RESTRAINT_APPLIED, hero.uid, len(now), restraint.label, Pal.PURPLE,
                               source_uid=source.uid if source is not None else 0,
                               data={"restraint": restraint.name, "count": len(now)})
                elif restraint in before and restraint not in now:
                    self.log(f"{hero.name} breaks free: {restraint.label}", Pal.CYAN)
                    self._emit(EventKind.RESTRAINT_BROKEN, hero.uid, len(now), restraint.label, Pal.CYAN,
                               data={"restraint": restraint.name, "count": len(now)})

    def _bind_angels(self, source: BaseEntity, count: int) -> bool:
        """Chain every living Fallen Angel with up to `count` new restraints. Returns True if any was targeted."""
        hit = False
        for hero in self.players_alive():
            if not isinstance(hero, FallenAngel):
                continue
            hit = True
            free = [r for r in Restraint if r not in hero.restraints]
            picks = self.rng.sample(free, min(max(0, count), len(free)))
            for restraint in picks:
                hero.restraints.add(restraint)
            # Already fully chained: the curse bites into lucidity instead of fizzling.
            lucidity_before = hero.lucidity
            hero.lucidity = max(0.0, hero.lucidity - (15.0 if picks else 25.0))
            lost = lucidity_before - hero.lucidity
            if lost > 0:
                self._emit(EventKind.LUCIDITY, hero.uid, int(round(lost)),
                           f"{hero.name} loses {lost:g} lucidity", Pal.PURPLE,
                           source_uid=source.uid, data={"lost": lost, "reason": "binding curse"})
            self._sync_restraints(source)
        return hit

    # ============================ boss phases ==========================================
    def _is_boss(self, foe: Enemy) -> bool:
        flag = getattr(foe, "is_boss", None)
        if callable(flag):
            flag = flag()
        if flag is not None:
            return bool(flag)
        return foe.uid in self._boss_like

    @staticmethod
    def _phase_for(foe: Enemy) -> int:
        ratio = foe.hp / max(1, foe.max_hp)
        return 1 + sum(1 for threshold in BOSS_PHASE_THRESHOLDS if ratio <= threshold)

    def _phase_of(self, foe: Enemy) -> int:
        return self._boss_phase.get(foe.uid, 1) if self._is_boss(foe) else 1

    def _phase_power(self, foe: Enemy) -> float:
        return BOSS_PHASE_POWER[min(self._phase_of(foe), len(BOSS_PHASE_POWER)) - 1]

    def _init_boss_phases(self) -> None:
        for foe in self.state.enemies:
            if self._is_boss(foe):
                self._boss_phase[foe.uid] = self._phase_for(foe)

    def _note_boss_like(self, foe: Enemy) -> None:
        """Fallback boss detection: CHARGE / DEVASTATE are boss-only signature moves."""
        intent = foe.intent
        if intent is not None and intent.kind in (IntentKind.CHARGE, IntentKind.DEVASTATE) \
                and foe.uid not in self._boss_like:
            self._boss_like.add(foe.uid)
            self._boss_phase.setdefault(foe.uid, self._phase_for(foe))

    def _update_boss_phases(self) -> None:
        for foe in self.enemies_alive():
            if not self._is_boss(foe):
                continue
            current = self._boss_phase.get(foe.uid)
            target = self._phase_for(foe)
            if current is None:
                self._boss_phase[foe.uid] = target     # first sighting: adopt silently
                continue
            while current < target:                    # phases only ever advance
                current += 1
                self._boss_phase[foe.uid] = current
                self._boss_transition(foe, current)

    def _cancel_charge(self, foe: Enemy) -> None:
        if getattr(foe, "charging", False):
            foe.charging = False
            self.log(f"{foe.name}'s gathered power scatters!", Pal.CYAN)

    def _boss_transition(self, foe: Enemy, phase: int) -> None:
        mult = BOSS_PHASE_POWER[min(phase, len(BOSS_PHASE_POWER)) - 1]
        pct = round((mult - 1.0) * 100)
        name = _PHASE_NAMES.get(phase, f"PHASE {phase}")
        self._cancel_charge(foe)
        if phase == 2:
            # ENRAGED: stronger, but the transition staggers it - a window for the party.
            self.alert(f"{foe.name} IS {name}! +{pct}% power, but it reels and loses its next action.", Pal.RED)
            self.shake(0.7)
            self._staggered.add(foe.uid)
        else:
            # DESPERATE: stronger, extra flurry hit, chains lash at the Angel, new plan.
            self.alert(f"{foe.name} GROWS {name}! +{pct}% power, extra flurry hit, chains lash out.", Pal.RED)
            self.shake(1.0)
            self._bind_angels(foe, 1)
            if foe.uid not in self._acted and foe.uid not in self._staggered:
                foe.intent = foe.choose_intent(self.rng, self.state.has_angel)
                self._lock_target(foe)
        self._emit(EventKind.BOSS_PHASE, foe.uid, phase, f"{foe.name}: {name}", Pal.RED, power=mult,
                   data={"phase": phase, "name": name, "power_mult": mult, "staggered": foe.uid in self._staggered})

    # ============================ telegraphs ===========================================
    def _expected_target(self, foe: Enemy) -> Optional[Player]:
        """Hero a single-target attack will hit right now, or None if it is still random."""
        heroes = self.players_alive()
        locked_uid = self._locked.get(foe.uid)
        locked = next((h for h in heroes if h.uid == locked_uid), None)
        provokers = [h for h in heroes if h.has(Status.PROVOKE)]
        if provokers:
            if locked in provokers:
                return locked
            return provokers[0] if len(provokers) == 1 else None
        return locked

    def _lock_target(self, foe: Enemy) -> None:
        intent = foe.intent
        if intent is None or intent.kind not in _TARGETED_KINDS:
            self._locked.pop(foe.uid, None)
            return
        target = self._pick_target()
        if target is None:
            self._locked.pop(foe.uid, None)
        else:
            self._locked[foe.uid] = target.uid

    @staticmethod
    def _has_status(entity: BaseEntity, name: str) -> bool:
        member = getattr(Status, name, None)
        return member is not None and entity.has(member)

    def _hits_for(self, foe: Enemy, intent: Any) -> int:
        base = max(1, int(getattr(intent, "hits", 1) or 1))
        return base + (1 if self._phase_of(foe) >= 3 else 0)

    def intent_preview(self, foe: Enemy) -> Optional[IntentPreview]:
        """Telegraph for the UI. None when the foe is dead, has no plan, or already acted this round."""
        intent = foe.intent
        if not foe.alive or intent is None or foe.uid in self._acted:
            return None
        if self.intent_hidden:
            return IntentPreview(foe.uid, None, "???", "Sensory Deprivation hides what it intends.",
                                 hidden=True, color=Pal.DIM)
        kind = intent.kind
        phase = self._phase_of(foe)
        if foe.uid in self._staggered:
            return IntentPreview(foe.uid, IntentKind.SKIP, "Staggered",
                                 "Reeling from its phase change: it loses its next action.", phase=phase, color=Pal.DIM)
        if self._has_status(foe, "STUN"):
            return IntentPreview(foe.uid, IntentKind.SKIP, "Stunned", "Loses its turn.", phase=phase, color=Pal.DIM)
        label, hint, color = _INTENT_INFO.get(kind, (kind.name.replace("_", " ").title(), "", Pal.TEXT))
        power = float(intent.power) * self._phase_power(foe)
        hits = self._hits_for(foe, intent) if kind is IntentKind.MULTI else 1
        damage = int(max(0.0, foe.attack_power * power)) if kind in _DAMAGE_KINDS else 0
        target = self._expected_target(foe) if kind in _TARGETED_KINDS else None
        return IntentPreview(foe.uid, kind, label, hint, power, hits, damage,
                             target.uid if target is not None else 0, kind is IntentKind.DEVASTATE,
                             False, phase, color)

    def _intent_text(self, foe: Enemy, preview: IntentPreview) -> str:
        if preview.hidden:
            return f"{foe.name}: ???"
        parts = [f"{foe.name}: {preview.label}"]
        hero = next((h for h in self.state.players if h.uid == preview.target_uid), None) if preview.target_uid else None
        if hero is not None:
            parts.append(f"-> {hero.name}")
        if preview.area:
            parts.append("(all heroes)")
        if preview.damage:
            parts.append(f"~{preview.damage}" + (f" x{preview.hits}" if preview.hits > 1 else ""))
        return " ".join(parts)

    def _refresh_intents(self, *, force: bool = False) -> None:
        """Emit an INTENT event for every telegraph that is new or changed since last announced."""
        for foe in self.state.enemies:
            preview = self.intent_preview(foe)
            if preview is None:
                self._intent_sig.pop(foe.uid, None)
                continue
            sig = (preview.label, preview.damage, preview.hits, preview.target_uid, preview.hidden, preview.phase)
            if not force and self._intent_sig.get(foe.uid) == sig:
                continue
            self._intent_sig[foe.uid] = sig
            self._emit(EventKind.INTENT, foe.uid, preview.damage, self._intent_text(foe, preview), preview.color,
                       power=preview.power, source_uid=preview.target_uid,
                       data={"kind": preview.kind.name if preview.kind else "HIDDEN", "label": preview.label,
                             "hint": preview.hint, "hits": preview.hits, "area": preview.area,
                             "hidden": preview.hidden, "phase": preview.phase})

    # ============================= round flow ==========================================
    def _check_outcome(self) -> bool:
        """Move to VICTORY/DEFEAT when one side is gone. True if the encounter is over."""
        if self.phase in (Phase.VICTORY, Phase.DEFEAT):
            return True
        if not self.enemies_alive():
            self._set_outcome(Phase.VICTORY)
        elif not self.players_alive():
            self._set_outcome(Phase.DEFEAT)
        else:
            return False
        return True

    @staticmethod
    def _reward_of(foe: Enemy, attr: str) -> int:
        try:
            return max(0, int(getattr(foe, attr, 0) or 0))
        except (TypeError, ValueError):
            return 0

    def _set_outcome(self, phase: Phase) -> None:
        self.phase = phase
        self.qte = None
        self._entry = self._target = None
        if self._outcome_done:
            return
        self._outcome_done = True
        if phase is Phase.VICTORY:
            gold = sum(self._reward_of(f, "gold") for f in self.state.enemies)
            xp = sum(self._reward_of(f, "xp") for f in self.state.enemies)
            self.report_rewards(gold, xp)
        else:
            self.alert("The party has fallen...", Pal.RED)

    def _begin_round(self) -> None:
        st = self.state
        if self._check_outcome():
            return
        self.round_no += 1
        self.active = None
        self._acted.clear()
        self._locked.clear()
        self._intent_sig.clear()
        self._turns_this_round = 0
        st.queue.build(st.players, st.enemies)
        for foe in self.enemies_alive():
            foe.intent = foe.choose_intent(self.rng, st.has_angel)
            self._note_boss_like(foe)
        for hero in st.players:
            hero.aggro *= 0.7
        for foe in self.enemies_alive():
            self._lock_target(foe)
        self.log(f"-- Round {self.round_no} --", Pal.DIM)
        self._refresh_intents(force=True)
        self._start_turn()

    def _start_turn(self) -> None:
        if self._check_outcome():
            return
        queue = self.state.queue
        actor = queue.current
        skips = 0
        # Skip the dead and anyone who already acted this round (no double turns).
        while actor is not None and (not actor.alive or actor.uid in self._acted):
            skips += 1
            if skips > MAX_QUEUE_SKIPS or not queue.advance():
                actor = None
                break
            actor = queue.current
        if actor is None:
            self._end_round()
            return
        self._acted.add(actor.uid)
        self._turns_this_round += 1
        self.active = actor
        if isinstance(actor, Player):
            self._begin_player_turn(actor)
        else:
            self._refresh_intents()
            self.phase, self.timer = Phase.ENEMY, ENEMY_DELAY

    def _begin_player_turn(self, hero: Player) -> None:
        lucidity_before = float(hero.lucidity) if isinstance(hero, FallenAngel) else 0.0
        self._guarded(f"{hero.name}'s turn start", hero.on_turn_start, self)
        if hero.alive and hero.perk("regen") > 0 and hero.hp < hero.max_hp:
            self.heal(hero, max(1, int(hero.max_hp * hero.perk("regen"))))
        if isinstance(hero, FallenAngel) and hero.lucidity < lucidity_before:
            lost = lucidity_before - hero.lucidity
            self._emit(EventKind.LUCIDITY, hero.uid, int(round(lost)),
                       f"{hero.name} loses {lost:g} lucidity", Pal.PURPLE,
                       data={"lost": lost, "reason": "turn start"})
        self._settle()                       # also re-evaluates intent_hidden (blackout)
        pet = getattr(self.state, "pet", None)
        if pet == "wisp" and hero.alive:
            hero.mana = min(hero.max_mana, hero.mana + 5)
            hero.stamina = min(hero.max_stamina, hero.stamina + 5)
        elif pet == "sprite" and hero.alive and hero.hp < hero.max_hp:
            self.heal(hero, 5)
        if self._check_outcome():
            return
        if not hero.alive:
            self.phase, self.timer = Phase.RESOLVE, 0.0
            return
        if hero.stamina < LOW_STAMINA:
            self.alert(f"{hero.name}: LOW STAMINA", Pal.ORANGE)
        if hero.hp_ratio < 0.25:
            self.alert(f"{hero.name}: CRITICAL HEALTH", Pal.RED)
        if isinstance(hero, FallenAngel) and hero.bloodlust_turns > 0:
            self._bloodlust_turn(hero)
        else:
            self._open_menu()

    def _bloodlust_turn(self, angel: FallenAngel) -> None:
        self.alert(f"{angel.name} FLAILS IN BLOODLUST!", Pal.RED)
        for _ in range(2):
            foes = self.enemies_alive()
            if not foes or not angel.alive:
                break
            self.strike(angel, self.rng.choice(foes), 1.3)
            if angel.alive:
                self.hurt_self(angel, max(1, int(angel.max_hp * 0.06)))
        angel.bloodlust_turns = max(0, angel.bloodlust_turns - 1)
        if angel.bloodlust_turns <= 0:
            angel.lucidity = 35.0
            self.log(f"{angel.name} gasps; awareness crawls back.", Pal.CYAN)
        self._settle()
        self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY

    def _finish_turn(self) -> None:
        self._settle()
        if self._check_outcome():
            return
        if self.state.queue.advance():
            self._start_turn()
        else:
            self._end_round()

    def _end_round(self) -> None:
        for entity in [*self.state.players, *self.state.enemies]:
            if not entity.alive:
                continue
            burn = entity.end_round()
            if burn and burn > 0:
                self._emit(EventKind.DAMAGE, entity.uid, burn, data={"burn": True})
                self.log(f"{entity.name} burns for {burn}.", Pal.ORANGE)
                self._check_death(entity)
        self._settle()
        if self._check_outcome():
            return
        if self._turns_this_round == 0:
            self._stalled_rounds += 1
            if self._stalled_rounds >= MAX_STALLED_ROUNDS:
                self._error("The turn queue produced no actors; ending the encounter.")
                self._set_outcome(Phase.DEFEAT)
                return
        else:
            self._stalled_rounds = 0
        self._begin_round()

    # ============================ enemy behaviour ======================================
    def _pick_target(self) -> Optional[Player]:
        heroes = self.players_alive()
        if not heroes:
            return None
        provokers = [h for h in heroes if h.has(Status.PROVOKE)]
        if provokers:
            return self.rng.choice(provokers)
        return self.rng.choices(heroes, weights=[max(1.0, h.aggro) for h in heroes])[0]

    def _resolve_target(self, foe: Enemy) -> Optional[Player]:
        """Honour the telegraph unless Provoke / death changed things since it was announced."""
        expected = self._expected_target(foe)
        target = expected if expected is not None else self._pick_target()
        if target is not None and not target.has(Status.PROVOKE):
            decoys = [hero for hero in self.players_alive()
                      if getattr(hero, "decoy_turns", 0) > 0 and getattr(hero, "evasion_charges", 0) > 0]
            if decoys:
                target = decoys[0]
                self.log(f"{foe.name} follows the Paper Moon instead of the real target.", Pal.CYAN)
        locked_uid = self._locked.get(foe.uid)
        if target is not None and locked_uid and target.uid != locked_uid and target.has(Status.PROVOKE):
            self.log(f"{foe.name} is drawn to {target.name}!", Pal.BLUE)
        return target

    def _intercept(self, target: Player) -> Player:
        tanks = [t for t in self.players_alive()
                 if isinstance(t, Tank) and t.has(Status.GUARD) and t is not target]
        if not tanks:
            return target
        tank = max(tanks, key=lambda t: t.hp)
        self.log(f"{tank.name} intercepts the blow meant for {target.name}!", Pal.BLUE)
        self._emit(EventKind.INTERCEPT, tank.uid, text=f"{tank.name} intercepts!", color=Pal.BLUE,
                   source_uid=target.uid)
        return tank

    def _enemy_hit(self, foe: Enemy, target: Optional[Player], power: float, *, heavy: bool, aoe: bool = False) -> None:
        if target is None or not foe.alive or not target.alive:
            return
        # Evasion is resolved by the simulation, before shield interception or damage.
        evade = getattr(target, "consume_evasion", None)
        if not aoe and callable(evade) and evade():
            self._emit(EventKind.DODGE, target.uid, 0, f"{target.name} evades {foe.name}'s strike", Pal.CYAN,
                       source_uid=foe.uid, data={"prepared": True})
            self.log(f"{target.name} dissolves into foxfire; {foe.name} strikes an afterimage.", Pal.CYAN)
            return
        if not aoe:
            target = self._intercept(target)
        if not aoe and isinstance(target, Player) and target.perk("evade") > 0 \
                and self.rng.random() < min(0.6, target.perk("evade")):
            self._emit(EventKind.DODGE, target.uid, 0, f"{target.name} slips away from {foe.name}'s strike", Pal.CYAN,
                       source_uid=foe.uid, data={"perk": True})
            self.log(f"{target.name} avoids {foe.name}'s strike entirely.", Pal.CYAN)
            return
        dmg = target.mitigate(foe.attack_power * power * self._phase_power(foe))
        if heavy and target.has(Status.GUARD):
            dmg = max(1, int(dmg * GUARD_HEAVY_FACTOR))  # Guard mitigates heavy / boss damage
        if isinstance(target, Player):
            dmg = self._defence_perks(target, dmg)
        # A single ordinary hit cannot delete a full-health hero. Multi-hit
        # enemy intents still matter because this cap applies independently per hit.
        dmg = min(max(0, int(dmg)), max_single_hit(target.max_hp))
        dealt = max(0, target.take_damage(max(0, dmg)))
        self._emit(EventKind.DAMAGE, target.uid, dealt, source_uid=foe.uid, data={"heavy": heavy, "aoe": aoe})
        self.shake(min(1.0, dealt / max(1, target.max_hp) * 3 + (0.3 if heavy else 0.0)))
        lucidity_before = float(target.lucidity) if isinstance(target, FallenAngel) else 0.0
        target.on_hit_taken(dealt)
        if isinstance(target, FallenAngel) and target.lucidity < lucidity_before:
            lost = lucidity_before - target.lucidity
            self._emit(EventKind.LUCIDITY, target.uid, int(round(lost)),
                       f"{target.name} loses {lost:g} lucidity", Pal.PURPLE,
                       source_uid=foe.uid, data={"lost": lost, "reason": "damage"})
        self.log(f"{foe.name} hits {target.name} for {dealt}.", Pal.RED)
        if isinstance(target, Player) and target.alive and foe.alive and target.perk("thorns") > 0:
            reflected = max(0, foe.take_damage(int(target.perk("thorns"))))
            self._emit(EventKind.DAMAGE, foe.uid, reflected, source_uid=target.uid, data={"thorns": True})
            self.log(f"{foe.name} takes {reflected} reflected damage.", Pal.GREEN)
            self._check_death(foe)
        self._check_death(target)

    def _enemy_act(self, foe: Enemy) -> None:
        intent = foe.intent
        if foe.uid in self._staggered:
            self._staggered.discard(foe.uid)
            self._cancel_charge(foe)
            self.log(f"{foe.name} reels from the transformation; its action is lost.", Pal.DIM)
            return
        if intent is None or intent.kind is IntentKind.SKIP or self._has_status(foe, "STUN"):
            if getattr(foe, "charging", False):
                foe.charging = False
                self.alert(f"{foe.name}'s charge is interrupted!", Pal.CYAN)
            self.log(f"{foe.name} stumbles, dazed.", Pal.DIM)
            return
        self._emit(EventKind.LUNGE, foe.uid)
        kind = intent.kind
        if kind in (IntentKind.ATTACK, IntentKind.HEAVY):
            self._enemy_hit(foe, self._resolve_target(foe), intent.power, heavy=kind is IntentKind.HEAVY)
        elif kind is IntentKind.MULTI:
            for _ in range(self._hits_for(foe, intent)):
                if not self.players_alive():
                    break
                self._enemy_hit(foe, self._pick_target(), intent.power, heavy=False)
        elif kind is IntentKind.CHARGE:
            foe.charging = True
            self.alert(f"{foe.name} GATHERS RUINOUS POWER!", Pal.RED)
            self.shake(0.35)
        elif kind is IntentKind.DEVASTATE:
            foe.charging = False
            self.alert(f"{foe.name} UNLEASHES DEVASTATION!", Pal.RED)
            self.shake(1.0)
            for hero in self.players_alive():
                self._enemy_hit(foe, hero, intent.power, heavy=True, aoe=True)
        elif kind is IntentKind.CURSE:
            count = 3 if self._phase_of(foe) >= 3 else 2
            if not self._bind_angels(foe, count):
                self.log(f"{foe.name}'s curse finds no vessel.", Pal.DIM)
        else:
            self.log(f"{foe.name} hesitates.", Pal.DIM)

    # ============================ player menu flow =====================================
    def _open_menu(self) -> None:
        hero = self.active
        if not isinstance(hero, Player) or not hero.alive:
            self.phase, self.timer = Phase.RESOLVE, 0.0
            return
        self.in_items = False
        self.menu = [MenuEntry(a.label, a.cost, a.enabled, a.hint, ability=a) for a in hero.abilities()]
        has_items = bool(self.state.inventory.usable(self.state.players))
        self.menu.append(MenuEntry("Items", "party bag", has_items, "Use a shared party item."))
        if not any(m.enabled for m in self.menu):
            self.alert(f"{hero.name} has no usable action and loses the turn.", Pal.ORANGE)
            self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY
            return
        self.menu_idx = next((i for i, m in enumerate(self.menu) if m.enabled), 0)
        self.phase = Phase.MENU

    def can_struggle(self, owner: FallenAngel, restraint: Restraint) -> bool:
        """True when [E] on a hovered restraint may start the Break Restraint QTE right now."""
        if self.phase is not Phase.MENU or owner is not self.active or restraint not in owner.restraints:
            return False
        return any(m.ability and m.ability.key == "break" and m.enabled for m in self.menu)

    def struggle(self, owner: FallenAngel, restraint: Restraint) -> bool:
        """Hover + [E]: run Break Restraint aimed at one specific chain instead of the highest-priority one."""
        if not self.can_struggle(owner, restraint):
            return False
        entry = next(m for m in self.menu if m.ability and m.ability.key == "break")
        owner.struggle_target = restraint
        self._activate(entry)
        return self.phase is not Phase.MENU

    def _open_items(self) -> None:
        inv = self.state.inventory
        usable = list(inv.usable(self.state.players))
        if not usable:
            self._error("No usable items.")
            self._open_menu()
            return
        self.in_items = True
        self.menu = [MenuEntry(i.name, f"x{inv.count(i.key)}", True, i.desc, item=i) for i in usable]
        self.menu.append(MenuEntry("Back", "", True, "Return to actions."))
        self.menu_idx = 0

    def _move_menu(self, delta: int) -> None:
        for _ in range(len(self.menu)):
            self.menu_idx = (self.menu_idx + delta) % len(self.menu)
            if self.menu[self.menu_idx].enabled:
                return

    @staticmethod
    def _ability_ready(hero: Player, ability: Ability) -> bool:
        return any(a.key == ability.key and a.enabled for a in hero.abilities())

    def _activate(self, entry: MenuEntry) -> None:
        hero = self.active
        if self.phase is not Phase.MENU or not entry.enabled or not isinstance(hero, Player) or not hero.alive:
            return
        if entry.ability is None and entry.item is None:
            if entry.label == "Items":
                self._open_items()
            else:
                self._open_menu()
            return
        # Re-validate against live state: costs/stock may have changed since the menu was built.
        if entry.ability is not None and not self._ability_ready(hero, entry.ability):
            self._error(f"{entry.label} is not available right now.")
            self._open_menu()
            return
        if entry.item is not None and self.state.inventory.count(entry.item.key) <= 0:
            self._error(f"No {entry.item.name} left.")
            self._open_menu()
            return
        self._entry = entry
        target_kind = entry.ability.target if entry.ability else entry.item.target  # type: ignore[union-attr]
        if target_kind is Target.ENEMY:
            self.targets = list(self.enemies_alive())
        elif target_kind is Target.ALLY:
            self.targets = list(self.players_alive())
        else:
            self.targets = [hero]
        if not self.targets:
            self._error("There is no valid target.")
            self._open_menu()
            return
        self.target_idx = 0
        if target_kind in (Target.ENEMY, Target.ALLY) and len(self.targets) > 1:
            self.phase = Phase.TARGET
        else:
            self._begin_execute(None if target_kind is Target.ALL_ENEMIES else self.targets[0])

    def _begin_execute(self, target: Optional[BaseEntity]) -> None:
        entry, hero = self._entry, self.active
        if entry is None or not isinstance(hero, Player):
            self._error("The chosen action was lost.")
            self._open_menu()
            return
        self._target = target
        kind: Optional[QteKind] = entry.ability.qte if entry.ability else hero.item_qte()
        if kind is None:
            self._execute(None)
            return
        title = "SWALLOW!" if entry.item else None
        try:
            tier = 1 + self.state.stage // 4
            if isinstance(hero, FallenAngel) and entry.ability is not None and entry.ability.key == "break":
                # R2: Break Restraint uses the data-driven trial library (anti-spam, varied families).
                self.qte, trial_id = build_trial(self.rng, tier, [r.name for r in hero.restraints],
                                                 hero.recent_trials, hero.tightness)
                hero.note_trial(trial_id)
                scale_time(self.qte, 1.0 + hero.perk("trial_time"))
            elif isinstance(hero, FallenAngel) and kind is QteKind.TYPING and Restraint.MANACLES in hero.restraints:
                word = self.rng.choice(ANGEL_WORDS)
                self.qte = TypingQTE(word, limit=max(5.2, 2.7 + len(word) * 0.34 - min(0.8, tier * 0.08)), fatal_mistake=True)
            else:
                self.qte = create_qte(kind, self.rng, tier, title)
        except Exception:  # noqa: BLE001 - never strand the player on a broken minigame
            _LOG.exception("combat: create_qte(%s) raised", kind)
            self._error("The timing challenge failed to start; resolving without it.")
            self._execute(None)
            return
        self._phase_clock = 0.0
        self.phase = Phase.QTE

    def _execute(self, ok: Optional[bool]) -> None:
        entry, hero = self._entry, self.active
        self.qte = None
        if entry is None or not isinstance(hero, Player):
            self._error("The action lost its context; the turn is skipped.")
            self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY
            return
        target = self._target
        if target is not None and not target.alive:
            pool: list[BaseEntity] = list(self.enemies_alive() if isinstance(target, Enemy) else self.players_alive())
            if not pool:
                self._error("The target is gone; the action fizzles.")
                self._entry = self._target = None
                self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY
                return
            target = pool[0]
            self.log(f"{hero.name} retargets {target.name}.", Pal.DIM)
        if entry.ability:
            self._emit(EventKind.ACTION, hero.uid, text=entry.ability.label,
                       data={"action_key": entry.ability.key, "action_type": "ability"})
            lucidity_before = float(hero.lucidity) if isinstance(hero, FallenAngel) else 0.0
            self._guarded(entry.label, hero.use, entry.ability.key, target, ok, self)
        elif entry.item:
            self._emit(EventKind.ACTION, hero.uid, text=entry.item.name,
                       data={"action_key": entry.item.key, "action_type": "item"})
            lucidity_before = float(hero.lucidity) if isinstance(hero, FallenAngel) else 0.0
            self._guarded(entry.label, apply_item, self.state.inventory, entry.item, hero, target, ok, self)
        else:
            lucidity_before = float(hero.lucidity) if isinstance(hero, FallenAngel) else 0.0
        if isinstance(hero, FallenAngel) and hero.lucidity < lucidity_before:
            lost = lucidity_before - hero.lucidity
            self._emit(EventKind.LUCIDITY, hero.uid, int(round(lost)),
                       f"{hero.name} loses {lost:g} lucidity", Pal.PURPLE,
                       data={"lost": lost, "reason": "action"})
        self._entry = self._target = None
        self._settle()
        self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY

    # ============================ input & update =======================================
    def handle_key(self, key: str, text: str = "") -> None:
        if not isinstance(key, str):
            return
        if key.startswith("[") and key.endswith("]") and key[1:-1].isdecimal():
            key = key[1:-1]
        elif key.startswith("kp ") and key[3:].isdecimal():
            key = key[3:]
        if self.phase is Phase.MENU:
            if not self.menu:
                return
            if key in ("up", "w"):
                self._move_menu(-1)
            elif key in ("down", "s"):
                self._move_menu(1)
            elif key in ("return", "space"):
                if 0 <= self.menu_idx < len(self.menu):
                    self._activate(self.menu[self.menu_idx])
            elif key == "escape" and self.in_items:
                self._open_menu()
            elif key.isdecimal() and 0 < int(key) <= len(self.menu):
                self.menu_idx = int(key) - 1
                self._activate(self.menu[self.menu_idx])
        elif self.phase is Phase.TARGET:
            self.targets = [t for t in self.targets if t.alive]
            if not self.targets:
                self._open_menu()
                return
            self.target_idx %= len(self.targets)
            if key in ("left", "up", "a", "w"):
                self.target_idx = (self.target_idx - 1) % len(self.targets)
            elif key in ("right", "down", "d", "s"):
                self.target_idx = (self.target_idx + 1) % len(self.targets)
            elif key in ("return", "space"):
                self._begin_execute(self.targets[self.target_idx])
            elif key == "escape":
                self._open_menu()
        elif self.phase is Phase.QTE and self.qte is not None:
            self.qte.handle_key(key, text)

    def update(self, dt: float) -> None:
        dt = dt if dt > 0 else 0.0
        if self.phase is Phase.QTE:
            if self.qte is None:                       # nothing to wait for: recover instead of hanging
                self._execute(None)
                return
            self._phase_clock += dt
            self.qte.update(dt)
            if self.qte.done:
                self._execute(self.qte.success)
            elif self._phase_clock > QTE_WATCHDOG:
                self._error("The timing challenge stalled; it counts as failed.")
                self._execute(False)
        elif self.phase is Phase.RESOLVE:
            self.timer -= dt
            if self.timer <= 0:
                self._finish_turn()
        elif self.phase is Phase.ENEMY:
            self.timer -= dt
            if self.timer <= 0:
                foe = self.active
                acted = isinstance(foe, Enemy) and foe.alive
                if acted:
                    self._guarded(f"{foe.name}'s action", self._enemy_act, foe)  # type: ignore[union-attr]
                    self._settle()
                self.phase, self.timer = Phase.RESOLVE, RESOLVE_DELAY if acted else 0.0
        elif self.phase is Phase.MENU:
            if not self.menu:
                self._open_menu()
        elif self.phase is Phase.TARGET:
            self.targets = [t for t in self.targets if t.alive]
            if not self.targets:
                self._open_menu()
