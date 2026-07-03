"""Analysis: loudness, BPM estimation, mono compatibility, preview window."""

import numpy as np
from scipy import signal


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def mono_metrics(x: np.ndarray) -> dict:
    """How badly does this stereo render collapse on a mono speaker?"""
    L, R = x[:, 0], x[:, 1]
    denom = float(np.sqrt(np.mean(L**2) * np.mean(R**2))) + 1e-12
    corr = float(np.mean(L * R) / denom)
    rms_mono = rms((L + R) / 2.0)
    rms_stereo = float(np.sqrt((np.mean(L**2) + np.mean(R**2)) / 2.0))
    loss_db = 20.0 * np.log10((rms_mono + 1e-12) / (rms_stereo + 1e-12))
    return {"correlation": round(corr, 3), "mono_loss_db": round(float(loss_db), 2)}


def best_window(x: np.ndarray, sr: int, dur_s: float = 20.0):
    """Loudest contiguous window -- a decent 'find the chorus' heuristic.
    Returns (start_sample, length_samples)."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    n = len(m)
    w = int(sr * dur_s)
    if n <= w:
        return 0, n
    hop = sr // 2
    env = np.sqrt(
        np.mean(
            np.square(m[: (n // hop) * hop].reshape(-1, hop)), axis=1
        )
    )
    k = max(1, int(dur_s * 2))  # window length in hops
    if len(env) <= k:
        return 0, w
    sums = np.convolve(env, np.ones(k, dtype=np.float32), mode="valid")
    start = int(np.argmax(sums)) * hop
    return min(start, n - w), w


def estimate_bpm(x: np.ndarray, sr: int, lo: float = 60.0, hi: float = 185.0):
    """Spectral-flux onset envelope + autocorrelation. Good enough for
    steady pop/hip-hop/R&B beats; returns None when it can't tell."""
    m = x.mean(axis=1) if x.ndim == 2 else x
    m = m.astype(np.float32)

    # decimate to ~11 kHz for speed
    if sr > 16000:
        dec = int(sr // 11025)
        if dec > 1:
            m = signal.decimate(m, dec, ftype="fir", zero_phase=True)
            sr = sr / dec

    hop, nfft = 256, 1024
    if len(m) < nfft * 8:
        return None
    _, _, Z = signal.stft(m, fs=sr, nperseg=nfft, noverlap=nfft - hop, padded=False)
    S = np.abs(Z)
    flux = np.maximum(S[:, 1:] - S[:, :-1], 0.0).sum(axis=0)
    if len(flux) < 128 or float(flux.std()) < 1e-9:
        return None
    flux = flux - flux.mean()

    env_sr = sr / hop
    ac = signal.correlate(flux, flux, mode="full")[len(flux) - 1 :]
    ac /= ac[0] + 1e-9
    lag_min = max(1, int(env_sr * 60.0 / hi))
    lag_max = min(len(ac) - 1, int(env_sr * 60.0 / lo))
    if lag_min >= lag_max:
        return None
    lag = lag_min + int(np.argmax(ac[lag_min:lag_max]))
    if ac[lag] < 0.05:  # no periodicity worth trusting
        return None
    bpm = 60.0 * env_sr / lag
    while bpm < lo:
        bpm *= 2.0
    while bpm > hi:
        bpm /= 2.0
    return round(float(bpm), 1)
