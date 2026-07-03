"""Natural-language mixing assistant backed by a local Ollama model.

The model receives the current mixer settings and returns a complete,
schema-constrained settings object; everything is validated and clamped
server-side before it ever reaches the audio engine.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from core.dsp import MODES

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("STEREO_SPLITTER_MODEL", "gemma4:12b")
TIMEOUT_S = 180


class OllamaError(RuntimeError):
    pass


# ------------------------------------------------------------------ health

def health() -> dict:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            tags = json.load(r)
        models = [m.get("name", "") for m in tags.get("models", [])]
        base = MODEL.split(":")[0]
        pulled = any(m == MODEL or m.split(":")[0] == base for m in models)
        return {"available": True, "model": MODEL, "model_pulled": pulled, "error": None}
    except Exception as exc:
        return {"available": False, "model": MODEL, "model_pulled": False, "error": str(exc)}


# ------------------------------------------------------------------ validation

def _clamp(v, lo, hi, dflt):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return dflt
    return float(min(hi, max(lo, v)))


def validate_settings(s: dict, stems: list, current: dict | None) -> dict:
    """Clamp every value into range; fall back to current, then defaults."""
    cur = current or {}
    cur_stems = cur.get("stems", {}) or {}
    cur_glob = cur.get("global", {}) or {}
    got_stems = (s or {}).get("stems", {}) or {}
    got_glob = (s or {}).get("global", {}) or {}

    out = {"stems": {}, "global": {}}
    for name in stems:
        c = got_stems.get(name, {}) or {}
        base = cur_stems.get(name, {}) or {}
        mode = c.get("mode", base.get("mode", "center"))
        if mode not in MODES:
            mode = base.get("mode") if base.get("mode") in MODES else "center"
        sync = c.get("sync_beats", base.get("sync_beats"))
        if sync is not None:
            try:
                sync = float(min(64.0, max(0.25, float(sync))))
            except (TypeError, ValueError):
                sync = None
        out["stems"][name] = {
            "mode": mode,
            "gain_db": _clamp(c.get("gain_db", base.get("gain_db", 0)), -24, 6, 0.0),
            "haas_ms": _clamp(c.get("haas_ms", base.get("haas_ms", 18)), 5, 35, 18.0),
            "rate_hz": _clamp(c.get("rate_hz", base.get("rate_hz", 0.25)), 0.05, 4, 0.25),
            "depth": _clamp(c.get("depth", base.get("depth", 1)), 0, 1, 1.0),
            "sync_beats": sync,
        }
    out["global"] = {
        "speed": _clamp(got_glob.get("speed", cur_glob.get("speed", 1)), 0.65, 1.2, 1.0),
        "reverb": _clamp(got_glob.get("reverb", cur_glob.get("reverb", 0)), 0, 1, 0.0),
        "loudness_match": bool(got_glob.get("loudness_match", cur_glob.get("loudness_match", True))),
    }
    return out


# ------------------------------------------------------------------ schema

def _response_schema(stems: list) -> dict:
    stem_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": list(MODES)},
            "gain_db": {"type": "number"},
            "haas_ms": {"type": "number"},
            "rate_hz": {"type": "number"},
            "depth": {"type": "number"},
            "sync_beats": {"type": ["number", "null"]},
        },
        "required": ["mode", "gain_db", "haas_ms", "rate_hz", "depth", "sync_beats"],
    }
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "changed": {"type": "boolean"},
            "settings": {
                "type": "object",
                "properties": {
                    "stems": {
                        "type": "object",
                        "properties": {s: stem_schema for s in stems},
                        "required": list(stems),
                    },
                    "global": {
                        "type": "object",
                        "properties": {
                            "speed": {"type": "number"},
                            "reverb": {"type": "number"},
                            "loudness_match": {"type": "boolean"},
                        },
                        "required": ["speed", "reverb", "loudness_match"],
                    },
                },
                "required": ["stems", "global"],
            },
            "action": {"type": "string", "enum": ["preview", "full", "none"]},
        },
        "required": ["reply", "changed", "settings", "action"],
    }


# ------------------------------------------------------------------ prompt

_SYSTEM = """You are the mixing assistant inside Stereo Splitter, a local tool \
that has already split a song into stems and can re-pan each stem and apply \
master effects. The user speaks casually; translate their intent into settings.

CONTROLS
Per stem ({stem_list}):
- mode: center | hard_left | hard_right | wide | autopan | eightd
  center = normal, anchored in both speakers.
  hard_left / hard_right = that speaker only (old Beatles-style stereo).
  wide = Haas doubling, wraps around the listener's head. haas_ms 5-35 \
(default 18; higher = wider, more slap).
  autopan = sweeps left-right. rate_hz 0.05-4 (speed); depth 0-1; sync_beats \
= beats per full sweep, overrides rate_hz when set (1 or 2 = rhythmic bounce).
  eightd = circular 8D orbit with darkening behind the head and light reverb. \
rate_hz 0.05-0.5 (one orbit takes 1/rate seconds; 0.125 = 8 s); sync_beats = \
beats per orbit (8 or 16 feels right).
- gain_db: -24 to +6 (0 = unchanged volume)
Global:
- speed: 0.65-1.2 (1 = normal; 0.8-0.9 = classic slowed, pitch drops too; \
1.1-1.2 = sped up / nightcore)
- reverb: 0-1 (0.3-0.5 = dreamy; 0.7+ = drowned in a cathedral)
- loudness_match: keep true unless the user asks otherwise.

VOCABULARY
"wrap around my head" / "in my head" / "malibu sleep effect" -> vocals wide, \
everything else center.
"spin" / "circle" / "orbit" / "8d" -> eightd on the stem they mention \
(vocals if unspecified), slow orbit unless asked faster.
"bounce" / "ping-pong" / "back and forth" -> autopan, tempo-synced \
(sync_beats 1 or 2) when BPM is known.
"slowed" / "slowed and reverb" / "daycore" -> speed ~0.85, reverb ~0.35.
"nightcore" / "sped up" -> speed ~1.15.
"dreamy" / "underwater" / "far away" -> raise reverb, maybe slow slightly.
"strip it back" / "acapella-ish" -> drop other stems' gain_db, keep vocals.
Change ONLY what the user asked for; keep every other value exactly as it is \
in CURRENT SETTINGS.

RESPONSE (JSON only, matching the schema)
- reply: one or two short plain sentences saying what you changed. If the \
request is truly ambiguous, ask ONE brief question and set changed=false.
- changed: true if settings differ from current.
- settings: the COMPLETE settings object (every stem + global) after edits.
- action: "preview" when you changed something worth hearing (the default), \
"full" only if they asked to render/export the whole song, else "none".

CURRENT STATE
Song: {name} | BPM: {bpm} | stems: {stem_list}
CURRENT SETTINGS:
{current_json}
"""


# ------------------------------------------------------------------ chat

def chat(messages: list, current_settings: dict, stems: list, bpm, name: str) -> dict:
    clean = [
        {"role": m["role"], "content": str(m["content"])[:2000]}
        for m in (messages or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ][-12:]
    if not clean:
        raise OllamaError("no messages")

    current = validate_settings(current_settings, stems, current_settings)
    system = _SYSTEM.format(
        stem_list=", ".join(stems),
        name=name,
        bpm=bpm if bpm else "unknown",
        current_json=json.dumps(current, indent=1),
    )
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}] + clean,
        "stream": False,
        "format": _response_schema(stems),
        "options": {"temperature": 0.2, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:300]
        raise OllamaError(f"Ollama error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise OllamaError(
            f"Can't reach Ollama at {OLLAMA_URL} -- is it running?"
        ) from exc

    try:
        data = json.loads(resp["message"]["content"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise OllamaError("model returned invalid JSON") from exc

    changed = bool(data.get("changed"))
    settings = validate_settings(data.get("settings"), stems, current) if changed else None
    action = data.get("action") if data.get("action") in ("preview", "full", "none") else "none"
    if not changed:
        action = "none"
    return {
        "reply": str(data.get("reply", ""))[:1000] or "Done.",
        "settings": settings,
        "action": action,
    }
