"""Panning / stereo-effects engine.

Stems come in as (n, 2) stereo or (n,) mono numpy arrays.
Output of every public function is (n, 2) float32 (n may grow for
modes that add a reverb tail).
"""

from __future__ import annotations

import numpy as np

MODES = ("center", "hard_left", "hard_right", "wide", "autopan", "eightd")


def to_mono(x: np.ndarray) -> np.ndarray:
    if x.ndim == 2:
        return x.mean(axis=1)
    return x


def to_stereo(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        return np.stack([x, x], axis=1)
    return x


def apply_mode(
    x: np.ndarray,
    sr: int,
    mode: str = "center",
    haas_ms: float = 18.0,
    rate_hz: float = 0.25,
    depth: float = 1.0,
) -> np.ndarray:
    """Apply a panning mode to one stem.

    center     -- leave the stem exactly as mixed (anchored, both speakers)
    hard_left  -- stem fully in the left speaker
    hard_right -- stem fully in the right speaker
    wide       -- Haas effect: dry mono left, copy delayed by `haas_ms` right
    autopan    -- equal-power LFO pan; `rate_hz` sweep speed, `depth` 0..1
    eightd     -- circular orbit: equal-power pan + high-cut and level dip on
                  the "behind you" phase + a light baked-in reverb
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {MODES}")

    if mode == "center":
        return to_stereo(x).astype(np.float32)

    m = to_mono(x).astype(np.float32)
    n = len(m)
    out = np.zeros((n, 2), dtype=np.float32)

    if mode == "hard_left":
        out[:, 0] = m

    elif mode == "hard_right":
        out[:, 1] = m

    elif mode == "wide":
        d = max(1, int(round(sr * float(haas_ms) / 1000.0)))
        out[:, 0] = m
        out[d:, 1] = m[: n - d]
        out *= 0.85  # both channels carry full energy; keep level steady

    elif mode == "autopan":
        dep = float(np.clip(depth, 0.0, 1.0))
        t = np.arange(n, dtype=np.float32) / sr
        # theta 0 -> hard left, pi/2 -> hard right, pi/4 -> center
        theta = (np.pi / 4.0) * (1.0 + dep * np.sin(2.0 * np.pi * rate_hz * t))
        out[:, 0] = m * np.cos(theta)
        out[:, 1] = m * np.sin(theta)

    elif mode == "eightd":
        from core import effects

        dep = float(np.clip(depth, 0.0, 1.0))
        t = np.arange(n, dtype=np.float32) / sr
        ph = 2.0 * np.pi * rate_hz * t
        theta = (np.pi / 4.0) * (1.0 + dep * np.sin(ph))
        # sin drives left/right; cos drives front/back. rear = behind you.
        rear = np.clip(-np.cos(ph), 0.0, 1.0).astype(np.float32) * dep
        lp = effects.lowpass(m, sr, 3500.0)
        m2 = m * (1.0 - rear) + lp * rear          # darker behind the head
        m2 *= 1.0 - 0.22 * rear                    # slightly quieter too
        out = np.stack([m2 * np.cos(theta), m2 * np.sin(theta)], axis=1)
        out = effects.apply_reverb(out.astype(np.float32), sr, 0.25)

    return out.astype(np.float32)


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def mix(stems: list, gains_db: list | None = None) -> np.ndarray:
    """Sum processed stereo stems with per-stem gain; peak-protect the sum."""
    if not stems:
        raise ValueError("no stems to mix")
    if gains_db is None:
        gains_db = [0.0] * len(stems)

    n = max(len(s) for s in stems)
    out = np.zeros((n, 2), dtype=np.float32)
    for s, g in zip(stems, gains_db):
        s = to_stereo(s)
        out[: len(s)] += s * db_to_gain(g)

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out
