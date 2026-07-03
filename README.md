# Stereo Splitter

Pull any song apart. Put it back anywhere in the room.

Splits a track into stems (vocals / drums / bass / other) with AI separation,
then lets you re-pan and re-space each one — the "Malibu Sleep" wrap-around
effect, Beatles-style hard pans, 8D orbits, slowed + reverb edits. Everything
runs locally in your browser against a small Python server.

## Get it

```bash
git clone https://github.com/danguez4065-oss/stereo-splitter.git
cd stereo-splitter
```

Then either **double-click `Start Stereo Splitter.command`** in Finder — first
run sets everything up (a few minutes), after that it just launches and opens
the app — or do the manual setup below.

## Setup (Mac, one time)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg        # enables mp3 input/output (skip if installed)
```

## Run

```bash
source venv/bin/activate   # if not already active
python app.py
```

Open **http://localhost:5001** and drop in a song.

## What it does

**Per stem** — six placement modes:

- **Center** — untouched, anchored in both speakers
- **Wide (Haas)** — doubled hard L+R with a 5–35 ms delay; the classic
  wrap-around-headphones vocal (default for vocals)
- **Hard Left / Hard Right** — one speaker only
- **Auto-pan** — sweeps between speakers; free-rate in Hz or tempo-synced to
  the detected BPM (beats per sweep)
- **8D** — circular orbit: equal-power pan plus a high-cut and level dip when
  the sound passes "behind" you, with a light built-in reverb

**Master effects** — Slowed (65–120% speed, pitch follows like real slowed
edits), Reverb (synthesized hall, keeps the tail), and Match loudness (render
comes back as loud as the original, with a transparent soft limiter so it
never clips).

**Downloads** — the render as WAV or 320k MP3, plus individual stems:
a cappella, instrumental, drums, bass, other.

**Assistant (chat)** — describe what you want in plain English ("wrap the
vocals around my head and slow it down a little") and a local LLM turns it
into mixer settings, updates every control, and auto-previews. Runs against
[Ollama](https://ollama.com) with `gemma4:12b` by default:

```bash
brew install ollama          # or download from ollama.com
ollama pull gemma4:12b       # ~7.6 GB, one time
```

Use a different model with `STEREO_SPLITTER_MODEL=<tag> python app.py`
(any Ollama chat model works; responses are schema-constrained and every
value is clamped server-side, so a small model can't break the mixer).
The chat panel shows a status dot — it tells you if Ollama isn't running
or the model isn't pulled. Nothing leaves your machine.

**Quality-of-life**

- Stems are cached by file content — re-upload the same song and it opens
  instantly, even after restarting the server.
- **Preview 20s** renders just the loudest section (usually the chorus) so you
  can dial in settings before committing to a full render.
- Runs separation on your Mac's GPU (Apple Silicon / MPS) when available —
  several times faster than CPU — and falls back to CPU automatically.
- BPM detection powers the tempo-sync options.
- A mono-compatibility meter warns you if an edit will collapse on a single
  speaker (Haas doubling and hard pans can partially cancel in mono).

## Notes

- First-ever run downloads the Demucs model (~300 MB), one time only.
- Separation takes roughly the length of the song on CPU, much less on GPU.
- Listen on headphones — that's where the spatial effects live.
- Everything stays on your machine; nothing is uploaded anywhere.
- These edits are derivative works of the original recording — fine for
  personal listening; expect Content ID claims if you publish them.

## Files

- `app.py` — thin shim so `python app.py` still works; the real server lives
  in `server/`
- `core/` — the audio core:
  - `core/dsp.py` — panning modes (pure numpy)
  - `core/effects.py` — reverb, slowed, loudness match, soft limiter
  - `core/analysis.py` — BPM estimation, mono metrics, preview-window picker
- `intent/engine.py` — Ollama client, mixing-assistant prompt, settings
  validation
- `server/app.py` — Flask server: upload, cache, Demucs jobs, render,
  downloads, chat (routes only)
- `shells/web/index.html` — the UI (single file, no external dependencies)
- `schema/mix_document.schema.json` — the Mix Document: the one contract the
  UI, the assistant, and the audio core all speak
- `tests/` — DSP, server, and chat suites (separation is mocked, so they run
  without the Demucs model)
- `docs/` — `ROADMAP.md` (strategy) and `LOOPS.md` (how it gets built)
- `cache/` — created at runtime; separated stems live here (safe to delete)

## Development

The tests are plain Python scripts — no runner needed:

```bash
python tests/test_dsp.py
python tests/test_server.py
python tests/test_chat.py
```

CI (GitHub Actions) runs the same three suites on every push and pull
request, installing from `requirements-ci.txt` (no Demucs/torch — separation
is mocked in tests).

The build process is a sequence of small, verified loops — see
`docs/LOOPS.md` for the methodology, the loop log, and the backlog, and
`docs/ROADMAP.md` for the strategy behind it.

## License

No license yet — all rights reserved until one is chosen (see
docs/ROADMAP.md §5).
