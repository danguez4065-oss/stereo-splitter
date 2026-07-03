import sys, json, threading, io, hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---- mock Ollama on :11434 ----
CANNED = {
    "reply": "Vocals now orbit your head; slowed to 85% with a dreamy hall.",
    "changed": True,
    "settings": {
        "stems": {
            "vocals": {"mode": "eightd", "gain_db": 99, "haas_ms": 18, "rate_hz": 9.0, "depth": 1.4, "sync_beats": 16},
            "drums": {"mode": "center", "gain_db": 0, "haas_ms": 18, "rate_hz": 0.25, "depth": 1, "sync_beats": None},
            "bass": {"mode": "bogusmode", "gain_db": 0, "haas_ms": 18, "rate_hz": 0.25, "depth": 1, "sync_beats": None},
            "other": {"mode": "center", "gain_db": -3, "haas_ms": 18, "rate_hz": 0.25, "depth": 1, "sync_beats": None},
        },
        "global": {"speed": 0.85, "reverb": 0.4, "loudness_match": True},
    },
    "action": "preview",
}
class Mock(BaseHTTPRequestHandler):
    captured = {}
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({"models": [{"name": "gemma4:12b"}, {"name": "llama3:8b"}]}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path == "/api/chat":
            n = int(self.headers["Content-Length"]); req = json.loads(self.rfile.read(n))
            Mock.captured["req"] = req
            body = json.dumps({"message": {"role": "assistant", "content": json.dumps(CANNED)}}).encode()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

server = HTTPServer(("127.0.0.1", 11434), Mock)
threading.Thread(target=server.serve_forever, daemon=True).start()

from intent import engine as assistant
from server import app as srv

# health: up + pulled
h = assistant.health()
assert h == {"available": True, "model": "gemma4:12b", "model_pulled": True, "error": None}, h
print("health ok", h)

# fake ready job
sr, n = 44100, 44100*10
t = np.arange(n)/sr
job_id = "chatjob"
d = srv.CACHE / job_id; stems_dir = d/"stems"; stems_dir.mkdir(parents=True, exist_ok=True)
for name, f0 in {"vocals":440,"drums":110,"bass":55,"other":880}.items():
    s = (np.sin(2*np.pi*f0*t)*0.25).astype(np.float32)
    sf.write(stems_dir/f"{name}.wav", np.stack([s,s],1), sr)
srv.JOBS[job_id] = {"state":"ready","error":None,"dir":str(d),"stems":["vocals","drums","bass","other"],
                    "name":"chattest","sr":sr,"duration_s":10.0,"ref_rms":0.3,"bpm":120.0}
client = srv.app.test_client()

# /chat/health route
r = client.get("/chat/health"); assert r.get_json()["available"] is True

# chat happy path with hostile values -> clamped
current = {"stems": {s: {"mode":"center","gain_db":0,"haas_ms":18,"rate_hz":0.25,"depth":1,"sync_beats":None}
                     for s in ["vocals","drums","bass","other"]},
           "global": {"speed":1.0,"reverb":0.0,"loudness_match":True}}
r = client.post(f"/chat/{job_id}", json={"messages":[{"role":"user","content":"make the vocals spin around my head and slow it down"}],
                                          "settings": current})
j = r.get_json(); assert r.status_code == 200, j
v = j["settings"]["stems"]["vocals"]
assert v["mode"] == "eightd" and v["gain_db"] == 6.0 and v["rate_hz"] == 4.0 and v["depth"] == 1.0, v  # clamped
assert j["settings"]["stems"]["bass"]["mode"] == "center", "bogus mode not sanitized"
assert j["settings"]["global"]["speed"] == 0.85 and j["action"] == "preview"
assert "orbit" in j["reply"]
print("chat + clamping ok")

# system prompt got current state; format schema sent; model correct
req = Mock.captured["req"]
assert req["model"] == "gemma4:12b"
assert req["messages"][0]["role"] == "system" and "CURRENT SETTINGS" in req["messages"][0]["content"]
assert "BPM: 120.0" in req["messages"][0]["content"]
assert req["format"]["properties"]["settings"]["properties"]["stems"]["required"] == ["vocals","drums","bass","other"]
assert req["stream"] is False
print("request shape ok")

# rendered settings actually work end-to-end through /render
r = client.post(f"/render/{job_id}", json={"stems": j["settings"]["stems"], "global": j["settings"]["global"], "preview": True})
assert r.status_code == 200, r.get_json()
print("chat settings render ok")

# unknown job / not ready
assert client.post("/chat/nope", json={}).status_code == 404

# Ollama down -> 502 with helpful error
server.shutdown(); server.server_close()
assistant.TIMEOUT_S = 4
h = assistant.health(); assert h["available"] is False
r = client.post(f"/chat/{job_id}", json={"messages":[{"role":"user","content":"hi"}], "settings": current})
assert r.status_code == 502 and "Ollama" in r.get_json()["error"]
print("downtime handling ok")
print("ALL CHAT TESTS PASSED")
