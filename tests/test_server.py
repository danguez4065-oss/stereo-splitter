import sys, json, hashlib, io
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import app as srv

sr = 44100
n = sr * 25
t = np.arange(n) / sr

# build a fake "already separated" cache entry whose hash matches an upload
buf = io.BytesIO()
sig = (np.sin(2*np.pi*330*t)*0.3).astype(np.float32)
sf.write(buf, np.stack([sig, sig], 1), sr, format="WAV", subtype="PCM_16")
data = buf.getvalue()
job_id = hashlib.sha256(data).hexdigest()[:16]

d = srv.CACHE / job_id
stems_dir = d / "stems"
stems_dir.mkdir(parents=True, exist_ok=True)
freqs = {"vocals": 440, "drums": 110, "bass": 55, "other": 880}
for name, f0 in freqs.items():
    s = (np.sin(2*np.pi*f0*t)*0.25).astype(np.float32)
    if name == "drums":  # give drums a 100 BPM pulse so bpm detection has something
        env = ((t % 0.6) < 0.05).astype(np.float32)
        s = s * env
    sf.write(stems_dir / f"{name}.wav", np.stack([s, s], 1), sr)
meta = {"name": "cachetest", "stems": list(freqs), "sr": sr,
        "duration_s": 25.0, "ref_rms": 0.35, "bpm": 100.0}
(d / "meta.json").write_text(json.dumps(meta))

client = srv.app.test_client()

# config
r = client.get("/config"); j = r.get_json()
assert r.status_code == 200 and isinstance(j["ffmpeg"], bool) and j["device"] in ("mps","cuda","cpu")
print("config ok", j)

# upload hits the cache -> instant ready, no demucs
r = client.post("/upload", data={"file": (io.BytesIO(data), "cachetest.wav")},
                content_type="multipart/form-data")
j = r.get_json()
assert r.status_code == 200 and j["job_id"] == job_id and j["state"] == "ready", j
r = client.get(f"/status/{job_id}"); j = r.get_json()
assert j["state"] == "ready" and j["bpm"] == 100.0 and set(j["stems"]) == set(freqs)
print("cache fast-path ok")

# full render: malibu settings + tempo-synced 8D + master fx
settings = {
  "stems": {
    "vocals": {"mode": "wide", "haas_ms": 20, "gain_db": 0},
    "drums": {"mode": "center"},
    "bass": {"mode": "center"},
    "other": {"mode": "eightd", "rate_hz": 0.125, "depth": 0.9, "sync_beats": 16, "gain_db": -2},
  },
  "global": {"speed": 0.85, "reverb": 0.4, "loudness_match": True},
  "preview": False,
}
r = client.post(f"/render/{job_id}", json=settings); j = r.get_json()
assert r.status_code == 200, j
assert "mono" in j and "correlation" in j["mono"] and j["peak_db"] <= 0
# slowed 0.85 -> duration ~ 25/0.85 ≈ 29.4 (+ reverb tail)
assert j["duration_s"] > 28, f"slowed not applied? {j['duration_s']}"
print("full render ok", j)

# result wav + mp3
r = client.get(j["url"]); assert r.status_code == 200 and r.data[:4] == b"RIFF"
r = client.get(j["url"] + "?fmt=mp3")
assert r.status_code == 200 and r.mimetype == "audio/mpeg" and len(r.data) > 10000
print("wav+mp3 ok")

# preview render: ~20s window (plus tail), much shorter than full
r = client.post(f"/render/{job_id}", json={**settings, "preview": True}); j2 = r.get_json()
assert r.status_code == 200 and j2["duration_s"] < j["duration_s"] - 4, j2
print("preview ok", j2["duration_s"])

# stem + instrumental downloads
for name in ["vocals", "drums", "instrumental"]:
    r = client.get(f"/stem/{job_id}/{name}")
    assert r.status_code == 200 and r.data[:4] == b"RIFF", name
r = client.get(f"/stem/{job_id}/vocals?fmt=mp3"); assert r.mimetype == "audio/mpeg"
r = client.get(f"/stem/{job_id}/nonsense"); assert r.status_code == 404
print("stem downloads ok")

# bad inputs
assert client.post("/upload", data={}).status_code == 400
assert client.post(f"/render/{job_id}", json={"stems": {"vocals": {"mode": "bogus"}}}).status_code == 400
assert client.get("/status/nope").status_code == 404
print("error handling ok")

# cleanup forgets job but keeps cache; re-upload restores from disk
client.post(f"/cleanup/{job_id}")
assert client.get(f"/status/{job_id}").status_code == 404
r = client.post("/upload", data={"file": (io.BytesIO(data), "cachetest.wav")},
                content_type="multipart/form-data")
assert r.get_json()["state"] == "ready"
print("cleanup + cache persistence ok")

# index page serves
r = client.get("/"); assert r.status_code == 200 and b"Stereo" in r.data
print("ALL SERVER TESTS PASSED")

# ---- the Mix Document schema is the contract: a real render payload must validate ----
import jsonschema
schema = json.loads((Path(__file__).resolve().parents[1] / "schema" / "mix_document.schema.json").read_text())
doc = {"version": 1, "stems": settings["stems"], "global": settings["global"]}
jsonschema.validate(doc, schema)
try:
    jsonschema.validate({"stems": {"vocals": {"mode": "sideways"}},
                         "global": {"speed": 1, "reverb": 0, "loudness_match": True}}, schema)
    raise AssertionError("schema accepted an invalid mode")
except jsonschema.ValidationError:
    pass
print("schema contract ok")
