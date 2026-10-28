"""
abyssal_choir/systems/audio_system.py
=====================================

Fully procedural audio for ABYSSAL CHOIR.  Every sound effect and every
background-music loop is synthesised at runtime with ``numpy`` and played
through ``pygame.mixer`` -- no external audio files are required.

Public API
----------
    from abyssal_choir.systems.audio_system import (
        AudioSystem, get_audio_system, play_sfx, play_bgm, stop_bgm,
    )

    audio = get_audio_system()          # lazily creates the singleton
    audio.play_sfx("slash")             # or the module level play_sfx("slash")
    audio.play_bgm(1)                   # or the module level play_bgm(1)

Sound effects (``play_sfx``):
    "slash"           white-noise sweep for blade attacks
    "magic_bolt"      FM sine rise for spell casting
    "chain_clank"     inharmonic metallic ring for metal restraints
    "thorn_snap"      friction scratch + wood crack for thorn vines
    "struggle_burst"  bass thump + glass-shatter synth for breaking bondage

Level BGM (``play_bgm(level)``):
    1  dark A-minor ambient pad (drones, detuned pads, glints, cave wind)
    2  gothic cathedral organ + formant choir (D minor, cathedral reverb, bells)
    3  high-tempo (160 BPM) arpeggiator boss battle (E minor, drums, bass, lead)

Safety:
    * If numpy / pygame are missing, or no audio device can be opened, the
      system silently disables itself: every method keeps working and simply
      returns ``False``.  The game never crashes because of audio.
    * BGM loops are rendered on a background thread so the game loop never
      stalls; loops are rendered once and cached.
    * All loops are built from circular (wrap-around) mixing and circular FFT
      reverb, so they repeat seamlessly.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    import numpy as np
except Exception:  # numpy missing -> audio disabled gracefully
    np = None

try:
    import pygame
except Exception:  # pygame missing -> audio disabled gracefully
    pygame = None

__all__ = [
    "AudioSystem",
    "AudioManager",
    "get_audio_system",
    "init_audio",
    "play_sfx",
    "play_bgm",
    "stop_bgm",
    "set_sfx_volume",
    "set_bgm_volume",
    "toggle_mute",
    "shutdown_audio",
]

LOGGER = logging.getLogger("abyssal_choir.audio")

TWO_PI = 2.0 * math.pi


# ======================================================================
# Low level DSP helpers
# ======================================================================

def _midi_to_hz(midi: float) -> float:
    """Convert a MIDI note number to a frequency in Hz."""
    return 440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0))


def _num_samples(seconds: float, sr: int) -> int:
    """Number of samples for a duration (always at least one)."""
    return max(1, int(round(seconds * sr)))


def _time_axis(n: int, sr: int):
    """Time vector in seconds for ``n`` samples."""
    return np.arange(n, dtype=np.float64) / float(sr)


def _normalize(x, peak: float = 0.9):
    """Scale an array so its absolute peak equals ``peak``."""
    if x.size == 0:
        return x
    m = float(np.max(np.abs(x)))
    if m > 1e-12:
        return x * (peak / m)
    return x


def _pan_gains(pan: float):
    """Equal-power pan law.  pan in [-1 (left), +1 (right)]."""
    pan = min(1.0, max(-1.0, float(pan)))
    angle = (pan + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _mix_into(buf, start: int, seg, pan: float = 0.0, gain: float = 1.0, wrap: bool = False) -> None:
    """
    Add a mono segment into a stereo float buffer (n, 2) at ``start``.

    wrap=True  : the segment wraps around the end of the buffer (seamless loops)
    wrap=False : the segment is clipped at the buffer edges
    """
    n = buf.shape[0]
    length = seg.shape[0]
    start = int(start)
    if n == 0 or length == 0:
        return
    left_gain, right_gain = _pan_gains(pan)
    left_gain *= gain
    right_gain *= gain

    if wrap:
        start %= n
        if length > n:
            seg = seg[:n]
            length = n
    else:
        if start >= n or start + length <= 0:
            return
        if start < 0:
            seg = seg[-start:]
            length = seg.shape[0]
            start = 0
        if start + length > n:
            length = n - start
            seg = seg[:length]

    first = min(length, n - start)
    buf[start:start + first, 0] += seg[:first] * left_gain
    buf[start:start + first, 1] += seg[:first] * right_gain
    rest = length - first
    if rest > 0:
        buf[:rest, 0] += seg[first:first + rest] * left_gain
        buf[:rest, 1] += seg[first:first + rest] * right_gain


def _fft_filter(x, sr: int, low: Optional[float] = None, high: Optional[float] = None):
    """Smooth zero-phase band filter (12 dB/oct style) applied in the FFT domain."""
    n = x.shape[0]
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    mask = np.ones_like(freqs)
    if high is not None:
        mask = mask / (1.0 + (freqs / float(high)) ** 4)
    if low is not None:
        mask = mask / (1.0 + (float(low) / np.maximum(freqs, 1e-9)) ** 4)
    return np.fft.irfft(spectrum * mask, n)


def _adsr(n: int, sr: int, attack: float, decay: float, sustain: float, release: float):
    """Linear ADSR envelope; the release is applied at the very end of the buffer."""
    env = np.full(n, float(sustain))
    na = min(n, max(1, int(attack * sr)))
    env[:na] = np.linspace(0.0, 1.0, na, endpoint=False)
    nd = int(decay * sr)
    end_d = min(n, na + nd)
    if end_d > na:
        env[na:end_d] = np.linspace(1.0, sustain, end_d - na, endpoint=False)
    nr = min(n, int(release * sr))
    if nr > 0:
        env[n - nr:] *= np.linspace(1.0, 0.0, nr)
    return env


def _stack(phase, amps: Sequence[float], f_max: float, sr: int):
    """
    Additive harmonic stack.  ``phase`` is the fundamental's phase (radians),
    ``amps[k]`` is the amplitude of harmonic k+1.  Uses the Chebyshev
    recurrence sin((h+1)p) = 2 cos(p) sin(hp) - sin((h-1)p), so only two
    transcendental calls are needed no matter how many harmonics are summed.
    Harmonics above 0.45 * sample-rate (based on ``f_max``) are skipped.
    """
    out = np.zeros_like(phase)
    if len(amps) == 0:
        return out
    s_prev = np.zeros_like(phase)
    s_cur = np.sin(phase)
    c2 = 2.0 * np.cos(phase)
    harmonic = 1
    for a in amps:
        if harmonic * f_max >= sr * 0.45:
            break
        if a != 0.0:
            out += a * s_cur
        s_next = c2 * s_cur - s_prev
        s_prev = s_cur
        s_cur = s_next
        harmonic += 1
    return out


def _inharmonic(freq: float, dur: float, sr: int, ratios: Sequence[float], amps: Sequence[float],
                decays: Sequence[float], rng=None, attack: float = 0.0008):
    """Bank of exponentially decaying sine partials (bells, metal, wood)."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    out = np.zeros(n)
    for ratio, amp, decay in zip(ratios, amps, decays):
        f = freq * ratio
        if f >= sr * 0.45:
            continue
        phi = rng.uniform(0.0, TWO_PI) if rng is not None else 0.0
        out += amp * np.sin(TWO_PI * f * t + phi) * np.exp(-t / decay)
    if attack > 0.0:
        na = min(n, max(1, int(attack * sr)))
        out[:na] *= np.linspace(0.0, 1.0, na)
    return out


def _swept_noise(duration: float, sr: int, rng, f_start: float, f_end: float,
                 width_oct: float = 1.0, frame: int = 512):
    """
    White noise run through a band-pass whose centre frequency sweeps
    exponentially from ``f_start`` to ``f_end`` (STFT overlap-add, Hann/50 %).
    """
    n = _num_samples(duration, sr)
    hop = frame // 2
    padded = n + 2 * frame
    noise = rng.uniform(-1.0, 1.0, padded)
    window = 0.5 - 0.5 * np.cos(TWO_PI * np.arange(frame) / frame)
    freqs = np.fft.rfftfreq(frame, 1.0 / sr)
    log_f = np.log2(np.maximum(freqs, 1.0))
    out = np.zeros(padded)
    frames = (padded - frame) // hop + 1
    ratio = f_end / f_start
    for i in range(frames):
        pos = i * hop
        progress = min(1.0, max(0.0, (pos + frame / 2.0 - frame) / float(n)))
        centre = f_start * (ratio ** progress)
        mask = np.exp(-0.5 * ((log_f - math.log2(centre)) / width_oct) ** 2)
        spectrum = np.fft.rfft(noise[pos:pos + frame] * window) * mask
        out[pos:pos + frame] += np.fft.irfft(spectrum, frame)
    return _normalize(out[frame:frame + n], 1.0)


def _fade_edges(buf, sr: int, fade_in: float = 0.001, fade_out: float = 0.012):
    """Short fades on a stereo buffer to avoid clicks at the start / end."""
    n = buf.shape[0]
    fi = min(n, max(1, int(fade_in * sr)))
    fo = min(n, max(1, int(fade_out * sr)))
    buf[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    buf[n - fo:] *= np.linspace(1.0, 0.0, fo)[:, None]
    return buf


def _circular_reverb(buf, sr: int, rng, decay_s: float, wet: float,
                     lowpass_hz: float = 5500.0, highpass_hz: float = 120.0,
                     predelay_s: float = 0.02):
    """
    Stereo noise-burst reverb using *circular* FFT convolution, so the reverb
    tail wraps around the loop point and the loop stays seamless.
    """
    n = buf.shape[0]
    pre = int(predelay_s * sr)
    ir_len = int(min(n - pre - 1, sr * decay_s * 1.25))
    if ir_len < 16:
        return buf.copy()
    t = np.arange(ir_len) / float(sr)
    envelope = np.exp(-6.9078 * t / decay_s)  # -60 dB at decay_s seconds
    out = np.empty_like(buf)
    for ch in range(buf.shape[1]):
        noise = rng.standard_normal(ir_len) * envelope
        noise = _fft_filter(noise, sr, highpass_hz, lowpass_hz)
        noise = noise / (math.sqrt(float(np.sum(noise * noise))) + 1e-12)
        ir = np.zeros(n)
        ir[pre:pre + ir_len] = noise
        dry = buf[:, ch]
        wet_sig = np.fft.irfft(np.fft.rfft(dry) * np.fft.rfft(ir), n)
        out[:, ch] = dry * (1.0 - wet) + wet_sig * wet * 1.3
    return out


def _finalize_music(buf, target_rms: float):
    """Remove DC, level to a target RMS and gently soft-clip (memoryless -> loop safe)."""
    buf = buf - np.mean(buf, axis=0, keepdims=True)
    rms = float(np.sqrt(np.mean(buf * buf)))
    if rms > 1e-9:
        buf = buf * (target_rms / rms)
    return np.tanh(buf * 1.25) * 0.92


def _pack_samples(stereo, channels: int, fmt: int):
    """Convert a float stereo array (n, 2) to the raw sample format the mixer expects."""
    if channels == 1:
        data = stereo.mean(axis=1, keepdims=True)
    elif channels == 2:
        data = stereo
    else:
        data = np.stack([stereo[:, i % 2] for i in range(channels)], axis=1)
    data = np.clip(data, -1.0, 1.0)
    if fmt == 16:
        out = (data * 32767.0 + 32768.0).astype(np.uint16)
    elif fmt == -8:
        out = (data * 127.0).astype(np.int8)
    elif fmt == 8:
        out = (data * 127.0 + 128.0).astype(np.uint8)
    elif fmt in (32, -32):
        out = data.astype(np.float32)
    else:  # -16 (signed 16-bit) and anything unknown
        out = (data * 32767.0).astype(np.int16)
    return np.ascontiguousarray(out)


# ======================================================================
# Sound effect synthesis
# ======================================================================

def _synth_slash(sr: int, rng):
    """Blade attack: a bright white-noise sweep with a darker body, panned left -> right."""
    dur = 0.34
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    jitter = rng.uniform(0.9, 1.12)
    hiss = _swept_noise(dur, sr, rng, 1800.0 * jitter, 11000.0, width_oct=1.15)
    body = _swept_noise(dur, sr, rng, 350.0 * jitter, 2400.0, width_oct=1.0)
    hiss_env = (1.0 - np.exp(-t / 0.004)) * np.exp(-t / 0.075)
    body_env = (1.0 - np.exp(-t / 0.010)) * np.exp(-t / 0.110)
    mono = hiss * hiss_env + 0.45 * body * body_env
    theta = np.linspace(0.25, 1.30, n)
    out = np.stack([mono * np.cos(theta), mono * np.sin(theta)], axis=1)
    out = _normalize(out, 0.9)
    return _fade_edges(out, sr)


def _synth_magic_bolt(sr: int, rng):
    """Spell cast: exponentially rising FM sine with shimmer, tremolo and echoes."""
    total = 1.1
    body_dur = 0.75
    n = _num_samples(total, sr)
    t = _time_axis(n, sr)
    prog = np.clip(t / body_dur, 0.0, 1.0)
    f_lo = 260.0 * rng.uniform(0.95, 1.06)
    f_hi = 1500.0
    carrier = f_lo * (f_hi / f_lo) ** (prog ** 1.35)
    modulator = carrier * 2.0
    phase_c = TWO_PI * np.cumsum(carrier) / sr
    phase_m = TWO_PI * np.cumsum(modulator) / sr
    index = 1.5 + 4.5 * np.sin(math.pi * np.clip(prog * 1.15, 0.0, 1.0))
    core = np.sin(phase_c + index * np.sin(phase_m))
    shimmer = np.sin(2.0 * phase_c + 0.8 * np.sin(1.5 * phase_m))
    tremolo = 1.0 + 0.18 * np.sin(TWO_PI * 16.0 * t)
    env = np.minimum(1.0, t / 0.03) * (1.0 - prog ** 4)
    mono = (core + 0.28 * shimmer) * env * tremolo

    wet = mono.copy()
    delay = int(0.085 * sr)
    for k in (1, 2, 3):
        d = delay * k
        if d < n:
            wet[d:] += mono[:n - d] * (0.38 ** k)

    haas = max(1, int(0.0006 * sr))
    right = np.concatenate([np.zeros(haas), wet[:-haas]])
    out = np.stack([wet, right], axis=1)
    out = _normalize(out, 0.85)
    return _fade_edges(out, sr, 0.002, 0.02)


def _synth_chain_clank(sr: int, rng):
    """Metal restraints: free-bar inharmonic partials struck several times plus link rattle."""
    dur = 1.1
    n = _num_samples(dur, sr)
    buf = np.zeros((n, 2))
    ratios = (1.0, 2.76, 5.40, 8.93, 13.34, 18.64)
    amps = (1.0, 0.75, 0.55, 0.40, 0.25, 0.15)
    decays = (0.30, 0.20, 0.13, 0.085, 0.05, 0.03)
    hits = (
        (0.000, 1.00, 540.0, -0.30),
        (0.090, 0.70, 655.0, 0.25),
        (0.175, 0.50, 490.0, -0.10),
        (0.310, 0.35, 720.0, 0.40),
    )
    for t_start, gain, f0, pan in hits:
        f0 = f0 * rng.uniform(0.97, 1.03)
        seg = _inharmonic(f0, dur - t_start, sr, ratios, amps, decays, rng)
        click_n = _num_samples(0.02, sr)
        click = _fft_filter(rng.uniform(-1.0, 1.0, click_n), sr, 2500.0, 9000.0)
        click = click * np.exp(-_time_axis(click_n, sr) / 0.004)
        seg[:click_n] += 1.4 * click
        _mix_into(buf, int(t_start * sr), seg, pan, gain)

    rattle_n = _num_samples(0.5, sr)
    bursts = np.zeros(rattle_n)
    for _ in range(14):
        onset = int(rng.uniform(0.0, 0.4) * sr)
        tau = rng.uniform(0.004, 0.012)
        length = min(rattle_n - onset, int(tau * 6.0 * sr))
        if length > 1:
            bursts[onset:onset + length] += rng.uniform(0.2, 1.0) * np.exp(-np.arange(length) / sr / tau)
    rattle = _fft_filter(rng.uniform(-1.0, 1.0, rattle_n), sr, 2800.0, 8500.0) * bursts
    _mix_into(buf, 0, rattle, 0.0, 0.45)

    buf = _normalize(buf, 0.9)
    return _fade_edges(buf, sr, 0.0005, 0.03)


def _synth_thorn_snap(sr: int, rng):
    """Thorn vines: scratchy friction rising into a sharp wooden crack with splinters."""
    dur = 0.6
    n = _num_samples(dur, sr)
    buf = np.zeros((n, 2))

    friction_dur = 0.17
    fn = _num_samples(friction_dur, sr)
    ft = _time_axis(fn, sr)
    scratch = _fft_filter(rng.uniform(-1.0, 1.0, fn), sr, 900.0, 4200.0)
    knots = rng.uniform(0.15, 1.0, int(friction_dur * 90) + 2)
    jitter = np.interp(np.linspace(0, len(knots) - 1, fn), np.arange(len(knots)), knots)
    friction = scratch * jitter * (ft / friction_dur) ** 1.6
    _mix_into(buf, 0, _normalize(friction, 1.0), -0.10, 0.55)

    snap_at = int(friction_dur * sr)
    crack_n = _num_samples(0.06, sr)
    crack = _fft_filter(rng.uniform(-1.0, 1.0, crack_n), sr, 1800.0, 9000.0)
    crack = _normalize(crack * np.exp(-_time_axis(crack_n, sr) / 0.010), 1.0)
    _mix_into(buf, snap_at, crack, 0.0, 1.2)

    wood = _inharmonic(rng.uniform(170.0, 210.0), 0.25, sr,
                       (1.0, 2.35, 4.10, 6.30), (1.0, 0.70, 0.45, 0.25),
                       (0.055, 0.040, 0.025, 0.015), rng)
    _mix_into(buf, snap_at, wood, 0.0, 0.7)

    for _ in range(4):
        onset = friction_dur + rng.uniform(0.03, 0.30)
        tick_n = _num_samples(0.012, sr)
        tick = _fft_filter(rng.uniform(-1.0, 1.0, tick_n), sr, 3000.0, None)
        tick = tick * np.exp(-_time_axis(tick_n, sr) / 0.003)
        _mix_into(buf, int(onset * sr), _normalize(tick, 1.0), rng.uniform(-0.7, 0.7), rng.uniform(0.15, 0.40))

    buf = _normalize(buf, 0.9)
    return _fade_edges(buf, sr, 0.001, 0.03)


def _synth_struggle_burst(sr: int, rng):
    """Breaking free: saturated sub-bass thump layered with a glass-shatter synth."""
    dur = 1.2
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    buf = np.zeros((n, 2))

    # --- bass thump: pitch-dropping sine, warmed up with saturation -------------
    pitch = 38.0 + 95.0 * np.exp(-t / 0.06)
    thump = np.sin(TWO_PI * np.cumsum(pitch) / sr) * np.exp(-t / 0.20)
    thump = np.tanh(2.4 * thump)
    knock_n = _num_samples(0.05, sr)
    knock = _fft_filter(rng.uniform(-1.0, 1.0, knock_n), sr, None, 450.0)
    knock = _normalize(knock * np.exp(-_time_axis(knock_n, sr) / 0.012), 1.0)
    _mix_into(buf, 0, thump, 0.0, 1.0)
    _mix_into(buf, 0, knock, 0.0, 0.9)

    # --- glass shatter: many short, bright, inharmonic shards -------------------
    for _ in range(90):
        f0 = rng.uniform(2200.0, 12500.0)
        onset = min(0.6, rng.exponential(0.08))
        tau = rng.uniform(0.025, 0.20) * (1.15 - min(1.0, f0 / 14000.0))
        start = int(onset * sr)
        length = min(n - start - 1, int(tau * 7.0 * sr))
        if length < 8:
            continue
        st = _time_axis(length, sr)
        shard = np.sin(TWO_PI * f0 * st + rng.uniform(0.0, TWO_PI))
        if f0 * 2.31 < sr * 0.45:
            shard += 0.45 * np.sin(TWO_PI * f0 * 2.31 * st + rng.uniform(0.0, TWO_PI))
        shard *= np.exp(-st / tau)
        _mix_into(buf, start, shard, rng.uniform(-0.9, 0.9), rng.uniform(0.08, 0.28))

    # --- the initial "crack" of the glass --------------------------------------
    crack_n = _num_samples(0.25, sr)
    crack = _fft_filter(rng.uniform(-1.0, 1.0, crack_n), sr, 4500.0, None)
    crack = _normalize(crack * np.exp(-_time_axis(crack_n, sr) / 0.05), 1.0)
    _mix_into(buf, int(0.01 * sr), crack, 0.0, 0.5)

    buf = _normalize(buf, 0.95)
    return _fade_edges(buf, sr, 0.0005, 0.05)


def _synth_impact(sr: int, rng):
    """Short, weighty impact for damage received (low thump + sharp contact noise)."""
    dur = 0.24
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    pitch = 132.0 * np.exp(-t / 0.045) + 42.0
    body = np.sin(TWO_PI * np.cumsum(pitch) / sr) * np.exp(-t / 0.125)
    noise = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 700.0, 8500.0)
    noise *= np.exp(-t / 0.026)
    mono = 0.85 * body + 0.62 * noise
    pan = rng.uniform(-0.25, 0.25)
    left, right = _pan_gains(pan)
    out = np.stack((mono * left, mono * right), axis=1)
    return _fade_edges(_normalize(out, 0.88), sr, 0.0005, 0.045)


def _synth_critical(sr: int, rng):
    """Impact accented by a bright, short metallic sting."""
    out = _synth_impact(sr, rng) * 0.70
    dur = 0.34
    n = min(out.shape[0], _num_samples(dur, sr))
    t = _time_axis(n, sr)
    tone = (np.sin(TWO_PI * rng.uniform(880.0, 1040.0) * t)
            + 0.48 * np.sin(TWO_PI * rng.uniform(1320.0, 1570.0) * t))
    tone *= np.exp(-t / 0.095)
    out[:n, 0] += tone * 0.22
    out[:n, 1] += tone * 0.28
    return _fade_edges(_normalize(out, 0.92), sr, 0.0005, 0.05)


def _synth_heal(sr: int, rng):
    """Soft ascending three-note glass bell for recovery and healing."""
    dur = 0.62
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    mono = np.zeros(n, dtype=np.float64)
    base = rng.uniform(500.0, 590.0)
    for i, semitones in enumerate((0, 4, 7)):
        onset = int((0.0 + i * 0.105) * sr)
        length = n - onset
        if length <= 0:
            continue
        tt = _time_axis(length, sr)
        freq = base * (2.0 ** (semitones / 12.0))
        tone = (np.sin(TWO_PI * freq * tt) + 0.28 * np.sin(TWO_PI * freq * 2.01 * tt))
        tone *= np.exp(-tt / (0.19 + i * 0.025))
        mono[onset:] += tone * (0.68 - i * 0.12)
    out = np.stack((mono * 0.70, mono * 0.78), axis=1)
    return _fade_edges(_normalize(out, 0.82), sr, 0.002, 0.08)


def _synth_ui_move(sr: int, rng):
    """Very short, quiet navigation tick."""
    dur = 0.075
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    f = rng.uniform(560.0, 680.0)
    mono = (np.sin(TWO_PI * f * t) + 0.18 * np.sin(TWO_PI * 2.0 * f * t)) * np.exp(-t / 0.022)
    out = np.stack((mono * 0.72, mono * 0.72), axis=1)
    return _fade_edges(_normalize(out, 0.62), sr, 0.001, 0.018)


def _synth_ui_confirm(sr: int, rng):
    """Warm two-note menu confirmation."""
    dur = 0.18
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    f = rng.uniform(690.0, 760.0)
    env = np.minimum(1.0, t / 0.004) * np.exp(-t / 0.075)
    mono = (np.sin(TWO_PI * f * t) + 0.35 * np.sin(TWO_PI * f * 1.5 * t)) * env
    onset = int(0.055 * sr)
    if onset < n:
        tt = _time_axis(n - onset, sr)
        mono[onset:] += 0.48 * np.sin(TWO_PI * f * 1.26 * tt) * np.exp(-tt / 0.06)
    out = np.stack((mono * 0.75, mono * 0.78), axis=1)
    return _fade_edges(_normalize(out, 0.72), sr, 0.001, 0.025)


def _synth_qte_start(sr: int, rng):
    """Focused rising warning pulse that announces a skill check."""
    dur = 0.26
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    prog = np.clip(t / dur, 0.0, 1.0)
    freq = 420.0 * (1.9 ** prog)
    phase = TWO_PI * np.cumsum(freq) / sr
    mono = np.sin(phase) * np.sin(np.pi * np.minimum(1.0, t / dur)) ** 0.65
    out = np.stack((mono * 0.78, mono * 0.88), axis=1)
    return _fade_edges(_normalize(out, 0.78), sr, 0.001, 0.035)


def _synth_qte_success(sr: int, rng):
    """Clear ascending success chime."""
    dur = 0.38
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    mono = np.zeros(n, dtype=np.float64)
    for onset_s, freq in ((0.0, 660.0), (0.085, 830.0), (0.17, 990.0)):
        onset = int(onset_s * sr)
        tt = _time_axis(n - onset, sr)
        tone = (np.sin(TWO_PI * freq * tt) + 0.25 * np.sin(TWO_PI * freq * 2.01 * tt)) * np.exp(-tt / 0.14)
        mono[onset:] += tone * 0.55
    out = np.stack((mono * 0.74, mono * 0.86), axis=1)
    return _fade_edges(_normalize(out, 0.84), sr, 0.001, 0.06)


def _synth_qte_fail(sr: int, rng):
    """Short falling dissonant cue; deliberately softer than combat impacts."""
    dur = 0.26
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    freq = 480.0 * (0.63 ** np.clip(t / dur, 0.0, 1.0))
    phase = TWO_PI * np.cumsum(freq) / sr
    mono = (np.sin(phase) + 0.25 * np.sin(phase * 1.48)) * np.exp(-t / 0.13)
    out = np.stack((mono * 0.66, mono * 0.72), axis=1)
    return _fade_edges(_normalize(out, 0.70), sr, 0.001, 0.04)


def _synth_enemy_telegraph(sr: int, rng):
    """Low ominous two-pulse signal for boss phase changes and incoming danger."""
    dur = 0.42
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    low = np.sin(TWO_PI * 92.0 * t) * np.exp(-t / 0.18)
    high = np.sin(TWO_PI * 330.0 * t) * np.exp(-t / 0.085)
    gate = (t < 0.14).astype(float) + ((t > 0.22) & (t < 0.36)).astype(float)
    mono = (low + 0.48 * high) * gate
    out = np.stack((mono * 0.76, mono * 0.82), axis=1)
    return _fade_edges(_normalize(out, 0.78), sr, 0.001, 0.05)


def _synth_shadow_step(sr: int, rng):
    """Airy, low-volume fade for stealth and evasive actions."""
    dur = 0.22
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    noise = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 300.0, 2600.0)
    mono = noise * np.sin(np.pi * np.clip(t / dur, 0.0, 1.0)) * np.exp(-t / 0.15)
    out = np.stack((mono * 0.72, mono * 0.72), axis=1)
    return _fade_edges(_normalize(out, 0.65), sr, 0.002, 0.045)


def _synth_enemy_swing(sr: int, rng):
    """Enemy attack wind-up: a dark, falling whoosh with a low thump (distinct from the player's bright slash)."""
    dur = 0.40
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    jitter = rng.uniform(0.92, 1.08)
    whoosh = _swept_noise(dur, sr, rng, 1500.0 * jitter, 170.0, width_oct=1.05)
    whoosh_env = (1.0 - np.exp(-t / 0.030)) * np.exp(-t / 0.115)
    pitch = 118.0 * np.exp(-t / 0.060) + 46.0
    thump = np.sin(TWO_PI * np.cumsum(pitch) / sr) * np.exp(-t / 0.095)
    thump *= np.clip((t - 0.045) / 0.01, 0.0, 1.0)  # lands just after the whoosh begins
    mono = 0.80 * whoosh * whoosh_env + 0.55 * thump
    theta = np.linspace(1.30, 0.25, n)  # right -> left: enemies stand on the right lane
    out = np.stack([mono * np.cos(theta), mono * np.sin(theta)], axis=1)
    return _fade_edges(_normalize(out, 0.86), sr, 0.001, 0.05)


def _synth_ward(sr: int, rng):
    """Barrier / guard: a swelling glassy shimmer that settles into a soft ring (protection, not damage)."""
    dur = 0.62
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    base = rng.uniform(392.0, 420.0)
    ring = _inharmonic(base, dur, sr, (1.0, 2.01, 2.76, 4.07, 5.4),
                       (1.0, 0.55, 0.38, 0.22, 0.12), (0.30, 0.22, 0.16, 0.10, 0.07), rng, attack=0.035)
    shimmer = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 3500.0, 9500.0)
    shimmer *= np.clip(t / 0.10, 0.0, 1.0) * np.exp(-t / 0.16) * 0.28
    sub = np.sin(TWO_PI * (base / 4.0) * t) * np.exp(-t / 0.20) * 0.30
    mono = ring + shimmer + sub
    out = np.stack((mono * 0.78, mono * 0.78), axis=1)
    return _fade_edges(_normalize(out, 0.80), sr, 0.004, 0.09)


def _synth_death(sr: int, rng):
    """Defeated unit: a heavy falling tone with a short dusty noise tail."""
    dur = 0.72
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    pitch = 150.0 * np.exp(-t / 0.22) + 38.0
    body = np.sin(TWO_PI * np.cumsum(pitch) / sr) * np.exp(-t / 0.26)
    dust = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 160.0, 2400.0)
    dust *= np.clip(t / 0.02, 0.0, 1.0) * np.exp(-t / 0.18)
    mono = 0.85 * body + 0.34 * dust
    pan = rng.uniform(-0.2, 0.2)
    left, right = _pan_gains(pan)
    out = np.stack((mono * left, mono * right), axis=1)
    return _fade_edges(_normalize(out, 0.84), sr, 0.001, 0.10)


def _synth_victory(sr: int, rng):
    """Short open-fifth bell fanfare climbing A3 -> E4 -> A4 -> E5; resolved and relieved, never loud."""
    dur = 1.55
    n = _num_samples(dur, sr)
    mono = np.zeros(n, dtype=np.float64)
    for onset_s, midi, gain in ((0.00, 57, 0.60), (0.15, 64, 0.62), (0.30, 69, 0.66), (0.48, 76, 0.80)):
        onset = int(onset_s * sr)
        freq = _midi_to_hz(midi)
        seg_n = n - onset
        tt = _time_axis(seg_n, sr)
        bell = _inharmonic(freq, seg_n / sr, sr, (1.0, 2.0, 3.01, 4.2), (1.0, 0.45, 0.22, 0.10),
                           (0.55, 0.38, 0.26, 0.16), rng, attack=0.004)
        warm = np.sin(TWO_PI * freq * tt) * np.exp(-tt / 0.45) * 0.35
        mono[onset:onset + bell.shape[0]] += (bell + warm[:bell.shape[0]]) * gain
    out = np.stack((mono * 0.74, mono * 0.86), axis=1)
    return _fade_edges(_normalize(out, 0.80), sr, 0.001, 0.25)


def _synth_defeat(sr: int, rng):
    """Slow descending minor sigh (A3 -> F3 -> E3 -> A2) on a soft organ-like tone; heavy but not harsh."""
    dur = 1.65
    n = _num_samples(dur, sr)
    mono = np.zeros(n, dtype=np.float64)
    for onset_s, midi, gain, tau in ((0.00, 57, 0.62, 0.30), (0.26, 53, 0.62, 0.32),
                                     (0.52, 52, 0.66, 0.36), (0.80, 45, 0.85, 0.55)):
        onset = int(onset_s * sr)
        freq = _midi_to_hz(midi)
        seg_n = n - onset
        tt = _time_axis(seg_n, sr)
        vib = 1.0 + 0.004 * np.sin(TWO_PI * 4.6 * tt)
        phase = TWO_PI * freq * tt * vib
        tone = np.sin(phase) + 0.42 * np.sin(2.0 * phase) + 0.18 * np.sin(3.0 * phase)
        env = np.clip(tt / 0.03, 0.0, 1.0) * np.exp(-tt / tau)
        mono[onset:] += tone * env * gain
    out = np.stack((mono * 0.80, mono * 0.80), axis=1)
    return _fade_edges(_normalize(out, 0.78), sr, 0.002, 0.30)


_SFX_SYNTHS: Dict[str, Callable] = {
    "slash": _synth_slash,
    "magic_bolt": _synth_magic_bolt,
    "chain_clank": _synth_chain_clank,
    "thorn_snap": _synth_thorn_snap,
    "struggle_burst": _synth_struggle_burst,
    "impact": _synth_impact,
    "critical": _synth_critical,
    "heal": _synth_heal,
    "ui_move": _synth_ui_move,
    "ui_confirm": _synth_ui_confirm,
    "qte_start": _synth_qte_start,
    "qte_success": _synth_qte_success,
    "qte_fail": _synth_qte_fail,
    "enemy_telegraph": _synth_enemy_telegraph,
    "shadow_step": _synth_shadow_step,
    "enemy_swing": _synth_enemy_swing,
    "ward": _synth_ward,
    "death": _synth_death,
    "victory": _synth_victory,
    "defeat": _synth_defeat,
}


# ======================================================================
# Level 1 -- dark minor-scale ambient pad  (A natural minor)
# ======================================================================

_PAD_AMPS = (1.0, 0.52, 0.34, 0.20, 0.13, 0.08, 0.05)

# Am(add9) -> Fmaj7 -> Dm(add9) -> Em  (all diatonic to A natural minor)
_AMBIENT_CHORDS = (
    (45, 52, 57, 60, 64),
    (41, 48, 53, 57, 64),
    (38, 45, 50, 53, 64),
    (40, 47, 52, 55, 59),
)

_GLINTS = ((2.6, 76, -0.5), (9.4, 72, 0.4), (14.8, 79, -0.2), (20.3, 69, 0.6))


def _pad_voice(freq: float, dur: float, sr: int, rng, attack: float = 2.2, release: float = 3.0):
    """Two detuned, soft saw-like oscillators with a slow breathing LFO."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    out = np.zeros(n)
    for cents in (-8.0, 7.0):
        f = freq * (2.0 ** (cents / 1200.0))
        out += _stack(TWO_PI * f * t + rng.uniform(0.0, TWO_PI), _PAD_AMPS, f, sr)
    breath = 1.0 + 0.18 * np.sin(TWO_PI * rng.uniform(0.08, 0.20) * t + rng.uniform(0.0, TWO_PI))
    return out * breath * _adsr(n, sr, attack, 1.5, 0.85, release)


def _render_level1(sr: int):
    """Dark ambient pad: 24 s seamless loop."""
    rng = np.random.default_rng(101)
    chord_len = 6.0
    chord_n = _num_samples(chord_len, sr)
    n = chord_n * len(_AMBIENT_CHORDS)
    loop_s = n / float(sr)
    buf = np.zeros((n, 2))

    for ci, chord in enumerate(_AMBIENT_CHORDS):
        start = ci * chord_n
        count = len(chord)
        for ni, midi in enumerate(chord):
            seg = _pad_voice(_midi_to_hz(midi), chord_len + 3.0, sr, rng)
            pan = -0.6 + 1.2 * ni / float(count - 1)
            _mix_into(buf, start, seg, pan, 0.20, wrap=True)
        # sub drone on the chord root
        dn = _num_samples(chord_len + 3.0, sr)
        dt = _time_axis(dn, sr)
        root_f = _midi_to_hz(chord[0])
        drone = np.sin(TWO_PI * root_f * dt) + 0.35 * np.sin(TWO_PI * root_f * 2.0 * dt)
        drone *= _adsr(dn, sr, 2.0, 1.0, 0.9, 3.0)
        _mix_into(buf, start, drone, 0.0, 0.30, wrap=True)

    # sparse, cold glints (reverb will turn them into distant echoes)
    for when, midi, pan in _GLINTS:
        seg = _inharmonic(_midi_to_hz(midi), 6.0, sr, (1.0, 2.0, 3.01, 4.2),
                          (1.0, 0.4, 0.2, 0.1), (3.0, 2.0, 1.2, 0.6), rng, attack=0.01)
        _mix_into(buf, int(when * sr), seg, pan, 0.07, wrap=True)

    # cave wind: filtered noise whose LFOs are periodic over the loop length
    wind = _normalize(_fft_filter(rng.standard_normal(n), sr, 140.0, 700.0), 1.0)
    t = _time_axis(n, sr)
    lfo_a = 0.5 + 0.5 * np.sin(TWO_PI * (2.0 / loop_s) * t + 0.7)
    lfo_b = 0.6 + 0.4 * np.sin(TWO_PI * (5.0 / loop_s) * t)
    wind_env = (0.35 + 0.65 * lfo_a) * lfo_b
    buf[:, 0] += 0.07 * wind * wind_env
    buf[:, 1] += 0.07 * np.roll(wind, 1500) * wind_env

    buf = _circular_reverb(buf, sr, rng, decay_s=5.5, wet=0.5, lowpass_hz=4200.0, predelay_s=0.03)
    return _finalize_music(buf, 0.17)


# ======================================================================
# Level 2 -- gothic cathedral organ + formant choir  (D minor)
# ======================================================================

# (formant centre Hz, bandwidth Hz, gain)
_VOWELS = {
    "ah": ((750.0, 100.0, 1.00), (1150.0, 120.0, 0.55), (2600.0, 180.0, 0.25), (3300.0, 200.0, 0.10)),
    "oh": ((460.0, 80.0, 1.00), (850.0, 100.0, 0.45), (2600.0, 160.0, 0.12)),
    "oo": ((330.0, 60.0, 1.00), (800.0, 90.0, 0.18), (2500.0, 150.0, 0.05)),
}

# Dm - Bb - Gm - A  (smooth voice leading, major dominant for the gothic pull)
_CHOIR_PROGRESSION = (
    {"bass": 50, "tenor": 62, "alto": 65, "soprano": 69, "vowel": "oh"},
    {"bass": 46, "tenor": 62, "alto": 65, "soprano": 70, "vowel": "ah"},
    {"bass": 43, "tenor": 62, "alto": 67, "soprano": 70, "vowel": "oo"},
    {"bass": 45, "tenor": 61, "alto": 64, "soprano": 69, "vowel": "ah"},
)

# (part name, pan, gain)
_CHOIR_PARTS = (
    ("bass", -0.35, 0.95),
    ("tenor", -0.12, 0.85),
    ("alto", 0.15, 0.75),
    ("soprano", 0.38, 0.65),
)

_ORGAN_DRAWBARS = (1.0, 0.70, 0.42, 0.50, 0.0, 0.22, 0.0, 0.12)

_BELL_RATIOS = (0.5, 1.0, 1.183, 1.506, 2.0, 2.514, 2.662, 3.011, 4.166)
_BELL_AMPS = (0.65, 1.0, 0.70, 0.50, 0.60, 0.35, 0.30, 0.22, 0.14)
_BELL_DECAYS = (5.5, 4.5, 3.2, 2.8, 2.3, 1.8, 1.4, 1.0, 0.7)


def _formant_amps(f0: float, vowel: str, sr: int, max_hz: float = 4500.0):
    """Harmonic amplitudes shaped by vowel formants (source-filter in the additive domain)."""
    count = int(min(max_hz, sr * 0.45) // f0)
    count = max(1, count)
    harmonics = np.arange(1, count + 1, dtype=np.float64)
    freqs = harmonics * f0
    amps = np.zeros(count)
    for centre, bandwidth, gain in _VOWELS[vowel]:
        amps += gain * np.exp(-0.5 * ((freqs - centre) / bandwidth) ** 2)
    amps += 0.04 / harmonics
    amps = amps / np.sum(amps)
    significant = np.nonzero(amps > np.max(amps) * 0.01)[0]
    last = int(significant[-1]) if significant.size else 0
    return amps[:last + 1]


def _choir_voice(midi: float, vowel: str, dur: float, sr: int, rng, cents: float):
    """One sung voice: formant-filtered harmonics with delayed vibrato and a slow swell."""
    f0 = _midi_to_hz(midi) * (2.0 ** (cents / 1200.0))
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    vib_rate = rng.uniform(4.8, 5.9)
    vib_depth = 0.0042 * np.clip((t - 0.5) / 1.2, 0.0, 1.0)
    freq = f0 * (1.0 + vib_depth * np.sin(TWO_PI * vib_rate * t + rng.uniform(0.0, TWO_PI)))
    phase = TWO_PI * np.cumsum(freq) / sr + rng.uniform(0.0, TWO_PI)
    voice = _stack(phase, _formant_amps(f0, vowel, sr), f0 * 1.01, sr)
    swell = 1.0 + 0.08 * np.sin(TWO_PI * rng.uniform(0.15, 0.30) * t + rng.uniform(0.0, TWO_PI))
    return voice * swell * _adsr(n, sr, 0.9, 0.8, 0.85, 1.4)


def _organ_note(freq: float, dur: float, sr: int, rng, pedal: bool = False):
    """Pipe-organ voice: drawbar harmonics, a 16' sub rank and a gentle tremulant."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    phase = TWO_PI * freq * t
    out = _stack(phase, _ORGAN_DRAWBARS, freq, sr)
    if freq > 80.0:
        out += 0.55 * np.sin(0.5 * phase)
    if pedal:
        out += 0.6 * np.sin(phase)
    tremulant = 1.0 + 0.025 * np.sin(TWO_PI * 5.6 * t + rng.uniform(0.0, TWO_PI))
    return out * tremulant * _adsr(n, sr, 0.05, 0.15, 0.92, 0.7)


def _render_level2(sr: int):
    """Gothic organ + choir: 16 s seamless loop with cathedral reverb and bell tolls."""
    rng = np.random.default_rng(202)
    chord_len = 4.0
    chord_n = _num_samples(chord_len, sr)
    n = chord_n * len(_CHOIR_PROGRESSION)
    buf = np.zeros((n, 2))

    for ci, chord in enumerate(_CHOIR_PROGRESSION):
        start = ci * chord_n

        # organ manual + pedal
        manual = (chord["bass"], chord["tenor"], chord["alto"], chord["soprano"], chord["soprano"] + 12)
        for midi in manual:
            seg = _organ_note(_midi_to_hz(midi), chord_len + 0.8, sr, rng)
            _mix_into(buf, start, seg, rng.uniform(-0.4, 0.4), 0.16, wrap=True)
        pedal = _organ_note(_midi_to_hz(chord["bass"] - 12), chord_len + 0.8, sr, rng, pedal=True)
        _mix_into(buf, start, pedal, 0.0, 0.34, wrap=True)

        # pipe "chiff" at each chord change
        chiff_n = _num_samples(0.07, sr)
        chiff = _fft_filter(rng.uniform(-1.0, 1.0, chiff_n), sr, 800.0, 3500.0)
        chiff = _normalize(chiff * np.exp(-_time_axis(chiff_n, sr) / 0.02), 1.0)
        _mix_into(buf, start, chiff, 0.0, 0.05, wrap=True)

        # four-part choir, two detuned singers per part
        for part, pan, gain in _CHOIR_PARTS:
            for cents, pan_offset in ((-7.0, -0.12), (7.0, 0.12)):
                seg = _choir_voice(chord[part], chord["vowel"], chord_len + 1.6, sr, rng, cents)
                _mix_into(buf, start, seg, pan + pan_offset, gain * 0.5, wrap=True)

    # distant bell tolls
    for when, midi, gain, pan in ((0.0, 50, 0.20, -0.2), (8.0, 43, 0.17, 0.2)):
        seg = _inharmonic(_midi_to_hz(midi), 7.0, sr, _BELL_RATIOS, _BELL_AMPS, _BELL_DECAYS, rng)
        _mix_into(buf, int(when * sr), seg, pan, gain, wrap=True)

    buf = _circular_reverb(buf, sr, rng, decay_s=7.0, wet=0.55, lowpass_hz=4800.0, predelay_s=0.03)
    return _finalize_music(buf, 0.19)


# ======================================================================
# Level 3 -- high-tempo arpeggiator boss battle  (E minor, 160 BPM)
# ======================================================================

_BOSS_PROGRESSION = ((40, "min"), (36, "maj"), (45, "min"), (47, "maj")) * 2  # Em C Am B (x2)
_ARP_PATTERN_A = (0, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3)
_ARP_PATTERN_B = (0, 2, 4, 2, 1, 3, 5, 3, 0, 2, 4, 2, 1, 3, 5, 4)
_BASS_OFFSETS = (0, 0, 12, 0, 0, 0, 12, 7)
_HAT_ACCENTS = (1.0, 0.35, 0.60, 0.35)

# (midi, start beat, length in beats) for bars 5-8 of the loop
_LEAD_PHRASE = (
    ((76, 0.0, 1.5), (74, 1.5, 0.5), (71, 2.0, 1.0), (74, 3.0, 1.0)),
    ((72, 0.0, 1.5), (71, 1.5, 0.5), (67, 2.0, 1.0), (72, 3.0, 1.0)),
    ((76, 0.0, 1.0), (72, 1.0, 1.0), (69, 2.0, 1.0), (72, 3.0, 1.0)),
    ((78, 0.0, 1.0), (75, 1.0, 1.0), (71, 2.0, 1.0), (75, 3.0, 1.0)),
)


def _arp_note(freq: float, dur: float, sr: int):
    """Plucky detuned saw: a dull body plus a bright layer that decays quickly."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    bright_amps = tuple(1.0 / h for h in range(1, 15))
    out = np.zeros(n)
    for cents in (-6.0, 6.0):
        f = freq * (2.0 ** (cents / 1200.0))
        phase = TWO_PI * f * t
        dull = _stack(phase, (1.0, 0.45, 0.20), f, sr)
        bright = _stack(phase, bright_amps, f, sr)
        out += dull + 0.9 * bright * np.exp(-t / 0.05)
    env = np.minimum(1.0, t / 0.002) * np.exp(-t / 0.11) * np.clip((dur - t) / 0.01, 0.0, 1.0)
    return out * env * 0.5


def _bass_note(freq: float, dur: float, sr: int):
    """Driving bass: filtered saw plus a sine sub."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    phase = TWO_PI * freq * t
    saw = _stack(phase, tuple(1.0 / h for h in range(1, 9)), freq, sr)
    sub = np.sin(phase)
    env = np.minimum(1.0, t / 0.003) * (0.55 + 0.45 * np.exp(-t / 0.07)) * np.clip((dur - t) / 0.015, 0.0, 1.0)
    return (0.7 * saw + 0.9 * sub) * env


def _power_pad(freq: float, dur: float, sr: int, rng):
    """Held saw pad that thickens the boss track."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    out = np.zeros(n)
    amps = tuple(1.0 / h for h in range(1, 7))
    for cents in (-5.0, 5.0):
        f = freq * (2.0 ** (cents / 1200.0))
        out += _stack(TWO_PI * f * t + rng.uniform(0.0, TWO_PI), amps, f, sr)
    return out * _adsr(n, sr, 0.03, 0.10, 0.90, 0.10)


def _lead_note(freq: float, dur: float, sr: int):
    """Hard square/saw hybrid lead with delayed vibrato."""
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    vibrato = 1.0 + 0.007 * np.clip((t - 0.12) / 0.2, 0.0, 1.0) * np.sin(TWO_PI * 6.0 * t)
    phase = TWO_PI * np.cumsum(freq * vibrato) / sr
    odd = (1.0, 0.0, 1.0 / 3.0, 0.0, 1.0 / 5.0, 0.0, 1.0 / 7.0, 0.0, 1.0 / 9.0, 0.0, 1.0 / 11.0)
    sig = _stack(phase, odd, freq * 1.01, sr)
    sig += 0.5 * _stack(phase * 1.0035, (1.0, 0.5, 0.33, 0.25), freq * 1.01, sr)
    return sig * _adsr(n, sr, 0.008, 0.12, 0.75, 0.06)


def _drum_kick(sr: int, rng):
    dur = 0.32
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    pitch = 48.0 + 130.0 * np.exp(-t / 0.028)
    body = np.sin(TWO_PI * np.cumsum(pitch) / sr) * np.exp(-t / 0.10)
    out = np.tanh(1.8 * body)
    click_n = _num_samples(0.01, sr)
    click = _fft_filter(rng.uniform(-1.0, 1.0, click_n), sr, 1500.0, None)
    out[:click_n] += 0.5 * click * np.exp(-_time_axis(click_n, sr) / 0.002)
    return _normalize(out, 1.0)


def _drum_snare(sr: int, rng):
    dur = 0.26
    n = _num_samples(dur, sr)
    t = _time_axis(n, sr)
    noise = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 1400.0, 8500.0) * np.exp(-t / 0.065)
    tone = (np.sin(TWO_PI * 185.0 * t) + 0.5 * np.sin(TWO_PI * 330.0 * t)) * np.exp(-t / 0.035)
    return _normalize(0.9 * _normalize(noise, 1.0) + 0.55 * tone, 1.0)


def _drum_hat(sr: int, rng, decay: float):
    n = _num_samples(decay * 6.0, sr)
    t = _time_axis(n, sr)
    noise = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 7000.0, None) * np.exp(-t / decay)
    return _normalize(noise, 1.0)


def _drum_crash(sr: int, rng):
    n = _num_samples(1.6, sr)
    t = _time_axis(n, sr)
    noise = _fft_filter(rng.uniform(-1.0, 1.0, n), sr, 4500.0, None)
    noise = noise * np.exp(-t / 0.45) * (1.0 - np.exp(-t / 0.003))
    return _normalize(noise, 1.0)


def _render_level3(sr: int):
    """Boss battle: 8 bars at 160 BPM (12 s seamless loop)."""
    rng = np.random.default_rng(303)
    bpm = 160.0
    beat = 60.0 / bpm
    bars = 8
    steps_total = bars * 16
    n = _num_samples(bars * 4 * beat, sr)
    step_samples = n / float(steps_total)

    music = np.zeros((n, 2))
    drums = np.zeros((n, 2))

    kick = _drum_kick(sr, rng)
    snare = _drum_snare(sr, rng)
    hats = (_drum_hat(sr, rng, 0.018), _drum_hat(sr, rng, 0.024))
    open_hat = _drum_hat(sr, rng, 0.10)
    crash = _drum_crash(sr, rng)

    arp_cache: Dict[int, object] = {}
    bass_cache: Dict[int, object] = {}
    kick_starts: List[int] = []

    for bar in range(bars):
        root, quality = _BOSS_PROGRESSION[bar]
        second_half = bar >= 4
        third = 4 if quality == "maj" else 3
        base = root + 24
        arp_tones = (base, base + third, base + 7, base + 12, base + 12 + third, base + 19)
        pattern = _ARP_PATTERN_B if second_half else _ARP_PATTERN_A

        # --- arpeggiator with ping-pong pan and a dotted echo -------------------
        for s in range(16):
            gstep = bar * 16 + s
            start = int(round(gstep * step_samples))
            midi = arp_tones[pattern[s]]
            if midi not in arp_cache:
                arp_cache[midi] = _arp_note(_midi_to_hz(midi), beat / 4.0 * 1.8, sr)
            seg = arp_cache[midi]
            pan = -0.5 if s % 2 == 0 else 0.5
            _mix_into(music, start, seg, pan, 0.55, wrap=True)
            _mix_into(music, start + int(round(3.0 * step_samples)), seg, -pan, 0.20, wrap=True)

        # --- driving eighth-note bass -------------------------------------------
        for j in range(8):
            start = int(round((bar * 16 + j * 2) * step_samples))
            midi = root + _BASS_OFFSETS[j]
            if midi not in bass_cache:
                bass_cache[midi] = _bass_note(_midi_to_hz(midi), beat / 2.0 * 0.92, sr)
            _mix_into(music, start, bass_cache[midi], 0.0, 0.70, wrap=True)

        # --- held power-chord pad -----------------------------------------------
        bar_start = int(round(bar * 16 * step_samples))
        for offset, pan in ((12, -0.3), (19, 0.3), (24, 0.0)):
            seg = _power_pad(_midi_to_hz(root + offset), 4.0 * beat, sr, rng)
            _mix_into(music, bar_start, seg, pan, 0.10, wrap=True)

        # --- lead melody in the second half -------------------------------------
        if second_half:
            for midi, start_beat, length_beats in _LEAD_PHRASE[bar - 4]:
                start = int(round((bar * 16 + start_beat * 4.0) * step_samples))
                seg = _lead_note(_midi_to_hz(midi), length_beats * beat * 0.95, sr)
                _mix_into(music, start, seg, 0.0, 0.17, wrap=True)

        # --- drums ----------------------------------------------------------------
        kick_steps = [0, 4, 8, 12] + ([10] if second_half else [])
        for s in kick_steps:
            start = int(round((bar * 16 + s) * step_samples))
            kick_starts.append(start)
            _mix_into(drums, start, kick, 0.0, 1.0, wrap=True)

        snare_hits = [(4, 0.85), (12, 0.85)]
        if bar == bars - 1:
            snare_hits += [(13, 0.45), (14, 0.60), (15, 0.80)]
        for s, gain in snare_hits:
            start = int(round((bar * 16 + s) * step_samples))
            _mix_into(drums, start, snare, 0.05, gain * 0.8, wrap=True)

        for s in range(16):
            start = int(round((bar * 16 + s) * step_samples))
            if s == 14 and bar != bars - 1:
                _mix_into(drums, start, open_hat, 0.2, 0.26, wrap=True)
            else:
                hat = hats[(bar + s) % 2]
                _mix_into(drums, start, hat, -0.2 if s % 2 == 0 else 0.2, 0.28 * _HAT_ACCENTS[s % 4], wrap=True)

        if bar % 4 == 0:
            _mix_into(drums, bar_start, crash, 0.0, 0.35, wrap=True)

    # sidechain-style pumping of the music bed on every kick hit
    duck = np.ones(n)
    duck_len = int(0.15 * sr)
    curve = 1.0 - 0.40 * np.exp(-np.arange(duck_len) / sr / 0.06)
    for start in kick_starts:
        end = min(n, start + duck_len)
        duck[start:end] = np.minimum(duck[start:end], curve[:end - start])
    music *= duck[:, None]

    music = _circular_reverb(music, sr, rng, decay_s=1.2, wet=0.18, lowpass_hz=6500.0, predelay_s=0.01)
    return _finalize_music(music + drums, 0.22)


_BGM_RENDERERS: Dict[int, Callable] = {
    1: _render_level1,
    2: _render_level2,
    3: _render_level3,
}


# ======================================================================
# AudioSystem
# ======================================================================

class AudioSystem:
    """
    Procedural audio manager built on ``pygame.mixer``.

    Every public method is exception-safe: when audio is unavailable
    (no numpy, no pygame, no sound device) ``enabled`` is False and all calls
    become harmless no-ops that return False.
    """

    SFX_NAMES = tuple(_SFX_SYNTHS)
    SFX_ALIASES = {
        "magic": "magic_bolt",
        "spell": "magic_bolt",
        "chain": "chain_clank",
        "chains": "chain_clank",
        "restrain": "chain_clank",
        "restrained": "chain_clank",
        "thorn": "thorn_snap",
        "thorns": "thorn_snap",
        "struggle": "struggle_burst",
        "escape": "struggle_burst",
        "break_free": "struggle_burst",
        "damage": "impact",
        "hit": "impact",
        "crit": "critical",
        "menu_move": "ui_move",
        "confirm": "ui_confirm",
        "success": "qte_success",
        "failure": "qte_fail",
        "alert": "enemy_telegraph",
        "lucidity": "enemy_telegraph",
    }
    BGM_LEVELS = (1, 2, 3)
    SFX_VARIANTS = 3
    MIN_SFX_INTERVAL = 0.035

    def __init__(self, sfx_volume: float = 0.85, bgm_volume: float = 0.5,
                 async_bgm: bool = True, auto_init: bool = True) -> None:
        self.enabled: bool = False
        self.sample_rate: int = 44100
        self.channels: int = 2
        self.mixer_format: int = -16
        self.sfx_volume: float = self._clamp01(sfx_volume)
        self.bgm_volume: float = self._clamp01(bgm_volume)
        self.async_bgm: bool = async_bgm

        self._muted: bool = False
        self._sfx_bank: Dict[str, list] = {}
        self._bgm_cache: Dict[int, object] = {}
        self._bgm_channels: list = []
        self._active_channel: int = 0
        self._current_level: Optional[int] = None
        self._requested_level: Optional[int] = None
        self._render_threads: Dict[int, threading.Thread] = {}
        self._last_sfx_time: Dict[str, float] = {}
        self._lock = threading.RLock()

        if auto_init:
            self.initialize()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _clamp01(value: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 1.0

    def initialize(self) -> bool:
        """Open the mixer and pre-render the sound effects.  Safe to call repeatedly."""
        if self.enabled:
            return True
        if pygame is None or np is None:
            LOGGER.warning("Audio disabled: %s is not available.", "pygame" if pygame is None else "numpy")
            return False
        try:
            if not pygame.mixer.get_init():
                self._open_mixer()
            info = pygame.mixer.get_init()
            if not info:
                raise RuntimeError("pygame.mixer did not initialise")
            self.sample_rate = int(info[0])
            self.mixer_format = int(info[1])
            self.channels = int(info[2])
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(2)  # channels 0 and 1 are reserved for BGM crossfades
            self._bgm_channels = [pygame.mixer.Channel(0), pygame.mixer.Channel(1)]
            self.enabled = True
        except Exception as exc:
            LOGGER.warning("Audio disabled (no usable audio device): %s", exc)
            self.enabled = False
            return False

        self._build_sfx_bank()
        return True

    @staticmethod
    def _open_mixer() -> None:
        """Try a few mixer configurations before giving up."""
        attempts = (
            (44100, -16, 2, 512),
            (44100, -16, 2, 1024),
            (22050, -16, 2, 1024),
            (22050, -16, 1, 2048),
        )
        last_error: Optional[Exception] = None
        for frequency, size, channels, buffer_size in attempts:
            try:
                pygame.mixer.quit()
                pygame.mixer.init(frequency=frequency, size=size, channels=channels, buffer=buffer_size)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError(str(last_error) if last_error else "mixer initialisation failed")

    def _to_sound(self, stereo):
        """Convert a float (n, 2) array into a pygame Sound matching the mixer format."""
        packed = _pack_samples(stereo, self.channels, self.mixer_format)
        return pygame.mixer.Sound(buffer=packed.tobytes())

    def _build_sfx_bank(self) -> None:
        """Synthesise every sound effect (a few randomised variants each)."""
        bank: Dict[str, list] = {}
        for name, synth in _SFX_SYNTHS.items():
            sounds = []
            for variant in range(self.SFX_VARIANTS):
                try:
                    seed = 7919 * (variant + 1) + sum(ord(c) for c in name)
                    data = synth(self.sample_rate, np.random.default_rng(seed))
                    sounds.append(self._to_sound(data))
                except Exception as exc:
                    LOGGER.warning("Could not synthesise sfx '%s' (variant %d): %s", name, variant, exc)
            if sounds:
                bank[name] = sounds
        with self._lock:
            self._sfx_bank = bank

    # -------------------------------------------------------------------- SFX
    def load_file_sfx(self, name: str, path: Any) -> bool:
        """Register a WAV/OGG file as an effect (R2 assets). Never raises; False means unavailable."""
        if not self.enabled:
            return False
        try:
            sound = pygame.mixer.Sound(str(path))
        except (pygame.error, FileNotFoundError, OSError) as exc:
            LOGGER.warning("Could not load sfx file %s: %s", path, exc)
            return False
        if not hasattr(self, "_file_sfx"):
            self._file_sfx: dict[str, list] = {}
        self._file_sfx[str(name).strip().lower()] = [sound]
        return True

    def play_sfx(self, name: str, volume: float = 1.0) -> bool:
        """Play a synthesised sound effect.  Returns True if a sound was started."""
        if not self.enabled or self._muted:
            return False
        try:
            key = str(name).strip().lower()
            key = self.SFX_ALIASES.get(key, key)
            sounds = self._sfx_bank.get(key) or getattr(self, "_file_sfx", {}).get(key)
            if not sounds:
                LOGGER.debug("Unknown or unavailable sfx: %r", name)
                return False
            now = time.monotonic()
            if now - self._last_sfx_time.get(key, 0.0) < self.MIN_SFX_INTERVAL:
                return False
            self._last_sfx_time[key] = now
            channel = random.choice(sounds).play()
            if channel is None:
                return False
            channel.set_volume(self._clamp01(self.sfx_volume * float(volume)))
            return True
        except Exception as exc:
            LOGGER.debug("play_sfx failed: %s", exc)
            return False

    # -------------------------------------------------------------------- BGM
    def _normalise_level(self, level) -> int:
        try:
            value = int(level)
        except (TypeError, ValueError):
            value = 1
        return max(self.BGM_LEVELS[0], min(self.BGM_LEVELS[-1], value))

    def _effective_bgm_volume(self) -> float:
        return 0.0 if self._muted else self.bgm_volume

    def play_bgm(self, level: int, fade_ms: int = 1500) -> bool:
        """
        Start the background music for a level (1-3), crossfading from the
        current track.  If the loop has not been rendered yet it is rendered on a
        worker thread and starts automatically when ready.
        """
        if not self.enabled:
            return False
        try:
            level = self._normalise_level(level)
            with self._lock:
                self._requested_level = level
                if level == self._current_level and self._bgm_channels[self._active_channel].get_busy():
                    return True
                sound = self._bgm_cache.get(level)
            if sound is not None:
                self._start_bgm(level, sound, fade_ms)
                return True

            if self.async_bgm:
                self._spawn_render(level, autoplay=True, fade_ms=fade_ms)
            else:
                self._render_and_play(level, True, fade_ms)
            return True
        except Exception as exc:
            LOGGER.warning("play_bgm failed: %s", exc)
            return False

    def _spawn_render(self, level: int, autoplay: bool, fade_ms: int) -> None:
        with self._lock:
            existing = self._render_threads.get(level)
            if existing is not None and existing.is_alive():
                return
            worker = threading.Thread(
                target=self._render_and_play,
                args=(level, autoplay, fade_ms),
                name="abyssal-bgm-%d" % level,
                daemon=True,
            )
            self._render_threads[level] = worker
        worker.start()

    def _render_and_play(self, level: int, autoplay: bool, fade_ms: int) -> None:
        sound = None
        try:
            with self._lock:
                sound = self._bgm_cache.get(level)
            if sound is None:
                data = _BGM_RENDERERS[level](self.sample_rate)
                sound = self._to_sound(data)
                with self._lock:
                    self._bgm_cache[level] = sound
        except Exception as exc:
            LOGGER.warning("Could not synthesise BGM for level %d: %s", level, exc)
            return
        finally:
            with self._lock:
                self._render_threads.pop(level, None)

        with self._lock:
            should_play = autoplay and self._requested_level == level and self.enabled
        if should_play and sound is not None:
            self._start_bgm(level, sound, fade_ms)

    def _start_bgm(self, level: int, sound, fade_ms: int) -> None:
        """Crossfade to a new BGM loop using the two reserved channels."""
        try:
            with self._lock:
                if not self.enabled:
                    return
                old = self._bgm_channels[self._active_channel]
                new_index = 1 - self._active_channel
                new = self._bgm_channels[new_index]
                sound.set_volume(self._effective_bgm_volume())
                if old.get_busy():
                    old.fadeout(int(fade_ms))
                new.set_volume(1.0)
                new.play(sound, loops=-1, fade_ms=int(fade_ms))
                self._active_channel = new_index
                self._current_level = level
        except Exception as exc:
            LOGGER.warning("Could not start BGM: %s", exc)

    def precache_bgm(self, levels: Sequence[int] = (1, 2, 3)) -> bool:
        """Render BGM loops in the background (e.g. during a loading screen) without playing them."""
        if not self.enabled:
            return False
        try:
            wanted = [self._normalise_level(lv) for lv in levels]

            def worker() -> None:
                for lv in wanted:
                    with self._lock:
                        if lv in self._bgm_cache:
                            continue
                    self._render_and_play(lv, False, 0)

            threading.Thread(target=worker, name="abyssal-bgm-precache", daemon=True).start()
            return True
        except Exception as exc:
            LOGGER.warning("precache_bgm failed: %s", exc)
            return False

    def stop_bgm(self, fade_ms: int = 800) -> None:
        """Fade out and stop the music."""
        if not self.enabled:
            return
        try:
            with self._lock:
                self._requested_level = None
                self._current_level = None
                for channel in self._bgm_channels:
                    if channel.get_busy():
                        channel.fadeout(int(fade_ms))
        except Exception as exc:
            LOGGER.debug("stop_bgm failed: %s", exc)

    def pause_bgm(self) -> None:
        if not self.enabled:
            return
        try:
            for channel in self._bgm_channels:
                channel.pause()
        except Exception as exc:
            LOGGER.debug("pause_bgm failed: %s", exc)

    def resume_bgm(self) -> None:
        if not self.enabled:
            return
        try:
            for channel in self._bgm_channels:
                channel.unpause()
        except Exception as exc:
            LOGGER.debug("resume_bgm failed: %s", exc)

    # ---------------------------------------------------------------- volume
    def _apply_bgm_volume(self) -> None:
        with self._lock:
            for sound in self._bgm_cache.values():
                sound.set_volume(self._effective_bgm_volume())

    def set_sfx_volume(self, volume: float) -> None:
        self.sfx_volume = self._clamp01(volume)

    def set_bgm_volume(self, volume: float) -> None:
        self.bgm_volume = self._clamp01(volume)
        if self.enabled:
            try:
                self._apply_bgm_volume()
            except Exception as exc:
                LOGGER.debug("set_bgm_volume failed: %s", exc)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self.enabled:
            try:
                self._apply_bgm_volume()
            except Exception as exc:
                LOGGER.debug("set_muted failed: %s", exc)

    def toggle_mute(self) -> bool:
        """Toggle mute and return the new muted state."""
        self.set_muted(not self._muted)
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted

    # ----------------------------------------------------------------- state
    @property
    def current_bgm_level(self) -> Optional[int]:
        return self._current_level

    def is_bgm_playing(self) -> bool:
        if not self.enabled:
            return False
        try:
            return any(channel.get_busy() for channel in self._bgm_channels)
        except Exception:
            return False

    def shutdown(self, quit_mixer: bool = False) -> None:
        """Stop everything.  The mixer is only closed when ``quit_mixer`` is True."""
        if not self.enabled:
            return
        try:
            with self._lock:
                self._requested_level = None
                self._current_level = None
                for channel in self._bgm_channels:
                    channel.stop()
            pygame.mixer.stop()
            if quit_mixer:
                pygame.mixer.quit()
        except Exception as exc:
            LOGGER.debug("shutdown failed: %s", exc)
        finally:
            self.enabled = False


# Friendly alias used by some game code bases.
AudioManager = AudioSystem


# ======================================================================
# Module level convenience API (lazy singleton)
# ======================================================================

_audio_system: Optional[AudioSystem] = None
_singleton_lock = threading.Lock()


def get_audio_system() -> AudioSystem:
    """Return the shared AudioSystem, creating it on first use."""
    global _audio_system
    with _singleton_lock:
        if _audio_system is None:
            try:
                _audio_system = AudioSystem()
            except Exception as exc:
                LOGGER.warning("AudioSystem creation failed, audio disabled: %s", exc)
                _audio_system = AudioSystem(auto_init=False)
        return _audio_system


def init_audio(**kwargs) -> AudioSystem:
    """Create (or replace) the shared AudioSystem with custom settings."""
    global _audio_system
    with _singleton_lock:
        if _audio_system is not None:
            _audio_system.shutdown()
        try:
            _audio_system = AudioSystem(**kwargs)
        except Exception as exc:
            LOGGER.warning("AudioSystem creation failed, audio disabled: %s", exc)
            _audio_system = AudioSystem(auto_init=False)
        return _audio_system


def play_sfx(name: str, volume: float = 1.0) -> bool:
    return get_audio_system().play_sfx(name, volume)


def play_bgm(level: int, fade_ms: int = 1500) -> bool:
    return get_audio_system().play_bgm(level, fade_ms)


def stop_bgm(fade_ms: int = 800) -> None:
    get_audio_system().stop_bgm(fade_ms)


def set_sfx_volume(volume: float) -> None:
    get_audio_system().set_sfx_volume(volume)


def set_bgm_volume(volume: float) -> None:
    get_audio_system().set_bgm_volume(volume)


def toggle_mute() -> bool:
    return get_audio_system().toggle_mute()


def shutdown_audio(quit_mixer: bool = False) -> None:
    global _audio_system
    with _singleton_lock:
        if _audio_system is not None:
            _audio_system.shutdown(quit_mixer)
            _audio_system = None


# ======================================================================
# Manual audition:  python -m abyssal_choir.systems.audio_system
# ======================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo = AudioSystem(async_bgm=False)
    if not demo.enabled:
        print("No audio device / pygame / numpy available - nothing to play.")
    else:
        for sfx_name in AudioSystem.SFX_NAMES:
            print("SFX:", sfx_name)
            demo.play_sfx(sfx_name)
            time.sleep(1.4)
        for bgm_level in AudioSystem.BGM_LEVELS:
            print("BGM level", bgm_level)
            demo.play_bgm(bgm_level, fade_ms=500)
            time.sleep(10.0)
        demo.stop_bgm(500)
        time.sleep(0.8)
        demo.shutdown(quit_mixer=True)
