"""Stereo Splitter -- split a song into stems and re-pan them.

Run:  python app.py   then open http://localhost:5001
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import Flask, jsonify, request, send_file, send_from_directory

from core import analysis, dsp, effects
from intent import engine as assistant

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

STEM_NAMES = ["vocals", "drums", "bass", "other"]
DEMUCS_MODEL = "htdemucs"
ALLOWED_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"}
FFMPEG = shutil.which("ffmpeg") is not None

app = Flask(__name__, static_folder=str(ROOT / "shells" / "web"))
JOBS: dict = {}  # job_id -> {state, error, progress, dir, stems, name, bpm, ...}


def pick_device() -> str:
    try:
        import torch

        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


DEVICE = pick_device()


# --------------------------------------------------------------------- separation

def _analyze(job: dict) -> None:
    """Post-separation analysis: duration, reference loudness, BPM."""
    stems_dir = Path(job["dir"]) / "stems"
    arrays, sr = {}, 44100
    for name in job["stems"]:
        arrays[name], sr = sf.read(stems_dir / f"{name}.wav", dtype="float32", always_2d=True)
    n = max(len(a) for a in arrays.values())
    ref = np.zeros((n, 2), dtype=np.float32)
    for a in arrays.values():
        ref[: len(a)] += a

    job["sr"] = sr
    job["duration_s"] = round(n / sr, 2)
    job["ref_rms"] = analysis.rms(ref)

    bpm_src = arrays.get("drums")
    if bpm_src is None or analysis.rms(bpm_src) < 1e-4:
        bpm_src = ref
    try:
        job["bpm"] = analysis.estimate_bpm(bpm_src, sr)
    except Exception:
        job["bpm"] = None


def _write_meta(job: dict) -> None:
    meta = {k: job[k] for k in ("name", "stems", "sr", "duration_s", "ref_rms", "bpm")}
    (Path(job["dir"]) / "meta.json").write_text(json.dumps(meta))


def run_separation(job_id: str) -> None:
    job = JOBS[job_id]
    d = Path(job["dir"])
    input_path = job["input"]
    try:
        sep_out = d / "sep"
        env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        devices = [DEVICE] if DEVICE == "cpu" else [DEVICE, "cpu"]
        tail, rc = b"", 1
        for device in devices:
            shutil.rmtree(sep_out, ignore_errors=True)
            cmd = [
                sys.executable, "-m", "demucs",
                "-n", DEMUCS_MODEL, "-d", device,
                "--out", str(sep_out), str(input_path),
            ]
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
            )
            tail = b""
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                tail = (tail + chunk)[-4000:]
                pcts = re.findall(rb"(\d{1,3})%", chunk)
                if pcts:
                    job["progress"] = min(99, int(pcts[-1]))
            rc = proc.wait()
            if rc == 0:
                job["device_used"] = device
                break
        if rc != 0:
            raise RuntimeError(
                "demucs failed:\n" + tail.decode(errors="ignore")[-1500:]
            )

        model_dir = sep_out / DEMUCS_MODEL
        track_dirs = [p for p in model_dir.iterdir() if p.is_dir()]
        if not track_dirs:
            raise RuntimeError("demucs produced no output")

        stems_dir = d / "stems"
        stems_dir.mkdir(exist_ok=True)
        found = []
        for name in STEM_NAMES:
            src = track_dirs[0] / f"{name}.wav"
            if src.exists():
                shutil.move(str(src), stems_dir / f"{name}.wav")
                found.append(name)
        shutil.rmtree(sep_out, ignore_errors=True)
        if not found:
            raise RuntimeError("no stem files found in demucs output")

        job["stems"] = found
        _analyze(job)
        _write_meta(job)
        job["progress"] = 100
        job["state"] = "ready"
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc)


def _load_cached(job_id: str, d: Path, name: str):
    """If this file was separated before, restore the job from disk."""
    meta_p = d / "meta.json"
    if not meta_p.exists():
        return None
    try:
        meta = json.loads(meta_p.read_text())
    except Exception:
        return None
    stems_dir = d / "stems"
    if not all((stems_dir / f"{s}.wav").exists() for s in meta.get("stems", [])):
        return None
    job = {
        "state": "ready", "error": None, "progress": 100,
        "dir": str(d), "input": None, "name": meta.get("name", name),
        "stems": meta["stems"], "sr": meta["sr"],
        "duration_s": meta["duration_s"], "ref_rms": meta["ref_rms"],
        "bpm": meta.get("bpm"), "cached": True,
    }
    JOBS[job_id] = job
    return job


# --------------------------------------------------------------------- helpers

def _get_job(job_id: str):
    return JOBS.get(job_id)


def _load_stems(job: dict) -> dict:
    stems_dir = Path(job["dir"]) / "stems"
    out = {}
    for name in job["stems"]:
        arr, _ = sf.read(stems_dir / f"{name}.wav", dtype="float32", always_2d=True)
        out[name] = arr
    return out


def _to_mp3(wav_path: Path) -> Path:
    mp3_path = wav_path.with_suffix(".mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-codec:a", "libmp3lame", "-b:a", "320k", str(mp3_path)],
        check=True,
    )
    return mp3_path


def _send_audio(wav_path: Path, fmt: str, download_name: str):
    if fmt == "mp3":
        if not FFMPEG:
            return jsonify(error="ffmpeg not installed; mp3 unavailable"), 400
        p = _to_mp3(wav_path)
        return send_file(p, mimetype="audio/mpeg", download_name=download_name + ".mp3")
    return send_file(wav_path, mimetype="audio/wav", download_name=download_name + ".wav")


# --------------------------------------------------------------------- routes

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/config")
def config():
    return jsonify(ffmpeg=FFMPEG, device=DEVICE)


@app.post("/upload")
def upload():
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify(error="no file uploaded"), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify(error=f"unsupported file type {ext}"), 400

    data = f.read()
    if not data:
        return jsonify(error="empty file"), 400
    job_id = hashlib.sha256(data).hexdigest()[:16]
    d = CACHE / job_id
    d.mkdir(exist_ok=True)
    name = Path(f.filename).stem

    existing = JOBS.get(job_id)
    if existing and existing["state"] in ("separating", "ready"):
        return jsonify(job_id=job_id, state=existing["state"])

    cached = _load_cached(job_id, d, name)
    if cached:
        return jsonify(job_id=job_id, state="ready")

    input_path = d / f"input{ext}"
    input_path.write_bytes(data)
    JOBS[job_id] = {
        "state": "separating", "error": None, "progress": 0,
        "dir": str(d), "input": input_path, "name": name,
        "stems": [], "bpm": None, "duration_s": None, "cached": False,
    }
    threading.Thread(target=run_separation, args=(job_id,), daemon=True).start()
    return jsonify(job_id=job_id, state="separating")


@app.get("/status/<job_id>")
def status(job_id: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    return jsonify(
        state=job["state"], error=job["error"], progress=job.get("progress"),
        stems=job["stems"], name=job["name"], bpm=job.get("bpm"),
        duration_s=job.get("duration_s"), device=DEVICE,
    )


@app.post("/render/<job_id>")
def render(job_id: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    if job["state"] != "ready":
        return jsonify(error=f"job is {job['state']}, not ready"), 400

    cfg = request.get_json(silent=True) or {}
    stems_cfg = cfg.get("stems", {})
    g = cfg.get("global", {})
    speed = float(g.get("speed", 1.0))
    reverb = float(g.get("reverb", 0.0))
    loudness_match = bool(g.get("loudness_match", True))
    preview = bool(cfg.get("preview", False))

    sr = job["sr"]
    arrays = _load_stems(job)

    if preview:
        src = arrays.get("vocals", next(iter(arrays.values())))
        start, length = analysis.best_window(src, sr, 20.0)
        arrays = {k: v[start : start + length] for k, v in arrays.items()}

    bpm = job.get("bpm")
    processed, gains = [], []
    for name, arr in arrays.items():
        c = stems_cfg.get(name, {})
        mode = c.get("mode", "center")
        rate_hz = float(c.get("rate_hz", 0.25))
        sync_beats = c.get("sync_beats")
        if sync_beats and bpm:
            rate_hz = (bpm / 60.0) / float(sync_beats)
        try:
            processed.append(
                dsp.apply_mode(
                    arr, sr, mode=mode,
                    haas_ms=float(c.get("haas_ms", 18.0)),
                    rate_hz=rate_hz,
                    depth=float(c.get("depth", 1.0)),
                )
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        gains.append(float(c.get("gain_db", 0.0)))

    out = dsp.mix(processed, gains)
    if abs(speed - 1.0) >= 1e-3:
        out = effects.change_speed(out, speed)
    if reverb > 0:
        out = effects.apply_reverb(out, sr, reverb)
    if loudness_match:
        out = effects.match_loudness(out, job["ref_rms"])
    out = effects.soft_limit(out)

    metrics = analysis.mono_metrics(out)
    wav_path = Path(job["dir"]) / "mix.wav"
    sf.write(wav_path, out, sr, subtype="PCM_16")
    mp3_stale = wav_path.with_suffix(".mp3")
    mp3_stale.unlink(missing_ok=True)

    peak = float(np.max(np.abs(out))) + 1e-12
    return jsonify(
        url=f"/result/{job_id}",
        mono=metrics,
        duration_s=round(len(out) / sr, 2),
        peak_db=round(20.0 * np.log10(peak), 2),
    )


@app.get("/result/<job_id>")
def result(job_id: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    wav_path = Path(job["dir"]) / "mix.wav"
    if not wav_path.exists():
        return jsonify(error="not rendered yet"), 404
    fmt = request.args.get("fmt", "wav")
    return _send_audio(wav_path, fmt, f"{job['name']} (stereo edit)")


@app.get("/stem/<job_id>/<name>")
def stem(job_id: str, name: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    if job["state"] != "ready":
        return jsonify(error="stems not ready"), 400
    fmt = request.args.get("fmt", "wav")
    stems_dir = Path(job["dir"]) / "stems"

    if name == "instrumental":
        others = [s for s in job["stems"] if s != "vocals"]
        if not others:
            return jsonify(error="no instrumental stems"), 404
        inst_path = Path(job["dir"]) / "instrumental.wav"
        if not inst_path.exists():
            arrays = []
            sr = job["sr"]
            for s in others:
                a, sr = sf.read(stems_dir / f"{s}.wav", dtype="float32", always_2d=True)
                arrays.append(a)
            out = dsp.mix(arrays)
            sf.write(inst_path, out, sr, subtype="PCM_16")
        return _send_audio(inst_path, fmt, f"{job['name']} (instrumental)")

    if name not in job["stems"]:
        return jsonify(error=f"unknown stem {name!r}"), 404
    label = "a cappella" if name == "vocals" else name
    return _send_audio(stems_dir / f"{name}.wav", fmt, f"{job['name']} ({label})")


@app.get("/chat/health")
def chat_health():
    return jsonify(assistant.health())


@app.post("/chat/<job_id>")
def chat_route(job_id: str):
    job = _get_job(job_id)
    if job is None:
        return jsonify(error="unknown job"), 404
    if job["state"] != "ready":
        return jsonify(error="song not ready yet"), 400
    body = request.get_json(silent=True) or {}
    try:
        out = assistant.chat(
            messages=body.get("messages", []),
            current_settings=body.get("settings") or {},
            stems=job["stems"],
            bpm=job.get("bpm"),
            name=job["name"],
        )
    except assistant.OllamaError as exc:
        return jsonify(error=str(exc)), 502
    return jsonify(out)


@app.post("/cleanup/<job_id>")
def cleanup(job_id: str):
    # forget the job but keep the stem cache on disk -- that's the point of it
    JOBS.pop(job_id, None)
    return jsonify(ok=True)


def main():
    dev = {"mps": "Apple GPU (MPS)", "cuda": "NVIDIA GPU"}.get(DEVICE, "CPU")
    print(f"\n  Stereo Splitter -> http://localhost:5001   [{dev}, ffmpeg={'yes' if FFMPEG else 'no'}]\n")
    app.run(host="127.0.0.1", port=5001, debug=False)


if __name__ == "__main__":
    main()
