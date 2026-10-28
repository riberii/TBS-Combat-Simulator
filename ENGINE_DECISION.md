# Engine and Architecture Decision — Chains of the Abyssal Choir V2.0

**Decision Date:** 25 October 2026  
**Auditor / Architect:** Principal Game Architect & Lead Systems Engineer  
**Target Project:** Chains of the Abyssal Choir V2.0  
**Status:** Authoritative Decision Approved

---

## 1. Technical Environment Audit

A direct inspection of the execution environment was performed on 25 October 2026:

| Tool / Runtime | Observed Status | Version / Detail |
| :--- | :--- | :--- |
| **Operating System** | Present | Windows 11 (AMD64) |
| **Python** | Present | Python 3.14.2 (active), Python 3.12 (available) |
| **pygame-ce** | Present | pygame-ce 2.5.6 (SDL 2.32.10) |
| **NumPy** | Present | Available for vector audio/math processing |
| **Godot Engine** | **ABSENT** | `where godot` / `Get-Command godot`: not installed, not in PATH |
| **Blender** | **ABSENT** | `where blender` / `Get-Command blender`: not installed, not in PATH |
| **winget / choco** | Unavailable / restricted | Container environment without elevated installer privileges |

---

## 2. Evaluation of Alternatives

### Option A: Complete Migration to Godot 4.7.2
- **Pros:** Native scene graphs, built-in 2D/3D lighting, animation trees, visual shader editor.
- **Cons:** 
  1. Godot runtime binary is **not installed** in the execution environment.
  2. Attempting a blind migration without the engine compiler or headless Godot test runner would produce an unverified, unrunnable codebase, directly violating the prompt's mandatory anti-slop rules and Gate 1 criteria: *"No second engine dependency at runtime, no fake launcher that opens an unbuilt project, and no 'TODO, migrate later' release."*
  3. All 75 existing passing domain tests, combat systems, saves, and content validators are authored in Python.

### Option B: High-Fidelity Asset-Driven 2D Pipeline in Python + pygame-ce (CHOSEN)
- **Pros:**
  1. Python 3.14.2 and **pygame-ce 2.5.6** are fully installed and verified operational.
  2. Full test suite (75 unit/integration tests, content validator, smoke test) runs natively and deterministically.
  3. Pygame-ce 2.5.6 provides advanced surface blitting, alpha blending, hardware-accelerated SDL2 backends, high-resolution rendering (1920×1080 logical scaling to 1280×720), and sub-pixel vector rendering.
  4. Real physical assets (WAV audio files, high-res portraits, authored sprites, palettes, and data tables) can be packaged, loaded, cached, and tested directly.
  5. 100% self-contained, offline-first, reproducible on any standard Python installation with `pip install -r requirements.txt`.

---

## 3. Authoritative Architectural Decision

**The game will remain on Python 3.10+ and pygame-ce 2.5.6 as the single authoritative runtime.**

We will fulfill all V2.0 visual, tactical, and audio directives within this authoritative pipeline:
1. **Visual Pipeline:** High-resolution rendering at 1280×720 canvas (scalable to 1920×1080 / fullscreen), authored vector character models matching the 6 adult anime reference images, dynamic palette re-coloring per skin, and layered lighting with depth planes.
2. **Combat Engine:** Expansion to the Choir / Counterpoint system (tactical tags: `SETUP`, `STRIKE`, `WARD`, `SHIFT`, `SILENCE`, `DETONATE`), full integration of all 24 skill tree nodes, companion live combat hooks, and multi-phase telegraphed boss mechanics.
3. **Audio Pipeline:** Bundled physical WAV sound files in `assets/audio/` with an authoritative `AudioSystem` bus architecture, volume controls, and procedural synthesis fallback.
4. **Data & Persistence:** Atomic profile storage with corruption backup, exact mode restoration, regional shop pricing, and honest daily objective verification.
