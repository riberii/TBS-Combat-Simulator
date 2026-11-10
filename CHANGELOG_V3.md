# CHANGELOG — V3

V3 builds on R2 (nothing removed). Scope chosen by the user: **drawn card hands in combat**. Verification levels are in `TEST_REPORT.md`; **nothing below has run on real Pygame-ce.**

## Card hand tray (combat)
- The acting hero's hand is drawn as cards along the bottom of the combat screen. By default it *peeks* (name and cost of each card show above the party cards) so the screen stays readable; **TAB** raises it, the selected card pops up and a tooltip shows its full rules text, tags and cost.
- Keys while the hand is raised: **LEFT/RIGHT** (or A/D) choose, **ENTER/SPACE** or **1-9** play, **M** mulligan (free, does not use the turn), **ESC** (or UP/DOWN) lowers the hand. **V** opens the pile viewer (draw / discard / exhaust; **V** or LEFT/RIGHT switch piles, any other key closes). Pile contents are listed A-Z so the draw order is never revealed.
- Unaffordable cards are dimmed and refused with a message; the turn is kept. Single-target cards on a multi-foe field enter the normal target step with the card lifted; **ESC** from targeting returns to the raised hand with nothing paid.
- Pile counters (draw / discard / exhaust / hand) are always visible beside the hand.
- Animations: opening hand and per-turn draws slide in from the draw pile, played cards fly toward the foes and fade, exhausted/discarded and mulliganed cards drop to the pile. If the animation state ever disagrees with the real hand it resyncs from the hand (it can only lose an animation, never show wrong cards).
- The plain action menu is unchanged: without TAB every key behaves as in R2, and the old **Cards** sub-menu still works.
- Added a **Card Hand** page to the in-game tutorials; the command-panel hint line changes with the hand state.

## Code
- `systems/hand_view.py`: frozen `HandView` snapshot the UI reads (the renderer never touches `CardBattle`).
- `systems/card_system.py`: `CardBattle` keeps a bounded event log (`draw/play/exhaust/discard/mulligan/shuffle`), `pile_counts()`, `pile_contents()`.
- `systems/combat_system.py`: `hand_view()`, `hand_focus` / `hand_idx` / `pile_view`, `_hand_key()`; focus resets every turn.
- `ui/hand_anim.py`: layout + animation state (pure Python). `main.py` `Painter.hand_tray()` / `pile_overlay()` draw it.
- `tools/render_preview.py`: new emulated scenes `hand_peek`, `hand_focus`, `hand_target`, `hand_piles`, `hand_play`.
- Release archive is now `ChainsOfTheAbyssalChoir_Pygame_V3.zip`.

## Not changed / not built
- Hand size, draw-per-turn, costs and card effects are exactly R2's (hands persist between turns; one card is drawn per turn). Balance is untouched and still needs a human pass.
- Still not built: branching run map, formations, companion boons.
