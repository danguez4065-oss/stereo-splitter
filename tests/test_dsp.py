import sys, json
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import dsp, effects, analysis

sr = 44100
n = sr * 30  # 30s
t = np.arange(n) / sr
mono = (np.sin(2*np.pi*220*t) * 0.4).astype(np.float32)

# ---- v1 modes still good ----
for mode in ("center","hard_left","hard_right","wide","autopan"):
    out = dsp.apply_mode(mono[:sr*2], sr, mode)
    assert out.shape[1] == 2 and out.dtype == np.float32, mode
print("v1 modes ok")

# ---- 8D: stereo varies over orbit, has reverb tail, darker at rear ----
out = dsp.apply_mode(mono[:sr*10], sr, "eightd", rate_hz=0.2, depth=1.0)
assert out.shape[0] > sr*10, "8D missing reverb tail"
# channel energies must trade places over the orbit
w = sr
eL = [np.sqrt(np.mean(out[i:i+w,0]**2)) for i in range(0, sr*10-w, w)]
eR = [np.sqrt(np.mean(out[i:i+w,1]**2)) for i in range(0, sr*10-w, w)]
ratios = [l/(r+1e-9) for l,r in zip(eL,eR)]
assert max(ratios) > 2.0 and min(ratios) < 0.5, f"8D orbit not audible: {ratios}"
print("8D ok")

# ---- reverb: tail present, wet energy scales with amount ----
imp = np.zeros((sr, 2), np.float32); imp[0] = 1.0
rv = effects.apply_reverb(imp, sr, 1.0)
tail = rv[sr//2:]
assert np.sqrt(np.mean(tail**2)) > 1e-4, "no reverb tail"
rv_half = effects.apply_reverb(imp, sr, 0.5)
assert np.abs(rv_half[sr//2:]).max() < np.abs(rv[sr//2:]).max(), "amount not scaling"
print("reverb ok")

# ---- slowed: 0.8x speed -> 1.25x length, DC-safe ----
x = np.stack([mono[:sr*4]]*2, 1)
sl = effects.change_speed(x, 0.8)
assert abs(len(sl)/len(x) - 1.25) < 0.01, f"speed ratio wrong {len(sl)/len(x)}"
assert effects.change_speed(x, 1.0) is not None and len(effects.change_speed(x, 1.0)) == len(x)
print("slowed ok")

# ---- loudness match + soft limit ----
quiet = x * 0.5
matched = effects.match_loudness(quiet, analysis.rms(x))
assert abs(analysis.rms(matched)/analysis.rms(x) - 1) < 0.05, "loudness match off"
hot = x * 5
lim = effects.soft_limit(hot)
assert np.abs(lim).max() <= 0.986, "limiter ceiling breached"
soft = effects.soft_limit(x * 0.5)
assert np.allclose(soft, x*0.5), "limiter not transparent below knee"
print("loudness/limit ok")

# ---- BPM: click track at 120 ----
clicks = np.zeros(n, np.float32)
beat = int(sr * 0.5)  # 120 bpm
for i in range(0, n, beat):
    clicks[i:i+200] = np.random.default_rng(1).standard_normal(200).astype(np.float32)
bpm = analysis.estimate_bpm(np.stack([clicks]*2,1), sr)
assert bpm is not None and abs(bpm - 120) < 3, f"bpm={bpm}"
# silence -> None
assert analysis.estimate_bpm(np.zeros((sr*5,2), np.float32), sr) is None
print(f"bpm ok ({bpm})")

# ---- mono metrics ----
mm = analysis.mono_metrics(np.stack([mono[:sr], mono[:sr]], 1))
assert mm["correlation"] > 0.99 and abs(mm["mono_loss_db"]) < 0.1
anti = np.stack([mono[:sr], -mono[:sr]], 1)
mm2 = analysis.mono_metrics(anti)
assert mm2["correlation"] < -0.99 and mm2["mono_loss_db"] < -30
print("mono metrics ok")

# ---- best window finds the loud section ----
song = np.zeros((n, 2), np.float32)
song[sr*18:sr*23] = 0.8  # loud burst at 18-23s
start, length = analysis.best_window(song, sr, 20.0)
assert start <= sr*18 < start + length, f"window missed chorus (start={start/sr}s)"
print("best window ok")
