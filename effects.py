"""Master-bus effects: reverb, slowed (speed/pitch), loudness, limiting."""

from fractions import Fraction

import numpy as np
from scipy import signal

_IR_CACHE: dict = {}


def _to2(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], axis=1) if x.ndim == 1 else x


def lowpass(x: np.ndarray, sr: int, fc: float = 3500.0, order: int = 4) -> np.ndarray:
    sos = signal.butter(order, fc, btype="low", fs=sr, output="sos")
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


def make_reverb_ir(sr: int, t60: float = 2.2, predelay_ms: float = 18.0) -> np.ndarray:
    """Synthesized stereo impulse response: exponentially decaying noise,
    darkened tail, short pre-delay. Energy-normalized so wet RMS ~ dry RMS."""
    key = (sr, round(t60, 2), round(predelay_ms, 1))
    if key in _IR_CACHE:
        return _IR_CACHE[key]

    rng = np.random.default_rng(71)
    n = int(sr * t60)
    t = np.arange(n, dtype=np.float32) / sr
    decay = np.power(10.0, -3.0 * t / t60).astype(np.float32)  # -60 dB at t60
    ir = rng.standard_normal((n, 2)).astype(np.float32) * decay[:, None]
    ir = lowpass(ir, sr, 7000.0, order=2)
    pre = np.zeros((int(sr * predelay_ms / 1000.0), 2), dtype=np.float32)
    ir = np.vstack([pre, ir])
    ir /= float(np.sqrt(np.sum(ir**2))) + 1e-9
    _IR_CACHE[key] = ir
    return ir


def apply_reverb(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Parallel convolution reverb. Keeps the tail (output is longer)."""
    amount = float(np.clip(amount, 0.0, 1.0))
    x2 = _to2(np.asarray(x, dtype=np.float32))
    if amount <= 0.0:
        return x2
    ir = make_reverb_ir(sr)
    wet = signal.fftconvolve(x2, ir, mode="full", axes=0).astype(np.float32)
    out = np.zeros_like(wet)
    out[: len(x2)] += x2
    out += wet * (0.85 * amount)
    return out


def change_speed(x: np.ndarray, speed: float) -> np.ndarray:
    """Classic 'slowed' edit: resample so pitch and tempo move together.
    speed 0.85 -> 15% slower and lower-pitched, like slowed+reverb edits."""
    speed = float(np.clip(speed, 0.5, 1.5))
    if abs(speed - 1.0) < 1e-3:
        return _to2(np.asarray(x, dtype=np.float32))
    fr = Fraction(1.0 / speed).limit_denominator(100)
    out = signal.resample_poly(_to2(x), fr.numerator, fr.denominator, axis=0)
    return out.astype(np.float32)


def match_loudness(x: np.ndarray, ref_rms: float, max_gain_db: float = 12.0) -> np.ndarray:
    """Bring the render back to the loudness of the original song."""
    cur = float(np.sqrt(np.mean(np.square(x)))) + 1e-9
    gain = min(ref_rms / cur, 10.0 ** (max_gain_db / 20.0))
    return (x * gain).astype(np.float32)


def soft_limit(x: np.ndarray, knee: float = 0.9, ceiling: float = 0.985) -> np.ndarray:
    """Transparent below the knee, smooth tanh compression above, never clips."""
    y = np.asarray(x, dtype=np.float32).copy()
    a = np.abs(y)
    over = a > knee
    if np.any(over):
        span = ceiling - knee
        y[over] = np.sign(y[over]) * (knee + span * np.tanh((a[over] - knee) / span))
    return y
