# Stereo Splitter — Technical Map & Three-Year Plan

*Status: prototype (v0). This document is the integrating architecture for all
three product destinies and the stage-gated plan to build toward them.*

## 1. The integrating idea

Three plausible destinies, one architecture:

- **Destiny A — OSS tool.** A respected open-source stem-panning utility.
- **Destiny B — consumer edit app.** Spatial/slowed edits for the
  TikTok/YouTube edit-culture audience.
- **Destiny C — natural-language mixing engine.** "Describe the sound, get
  the mix" as an interface layer, eventually licensable on its own.

They are not forks. They are different surfaces over the same four layers,
integrated by one artifact: the **Mix Document** — the versioned settings JSON
that already exists today as the render payload. Every layer speaks it and
only it. The UI produces it, the chat assistant produces it, the audio core
executes it, and later it becomes the project file and the shareable "recipe."
Because settings are data rather than rendered audio, recipes can be shared
publicly without distributing copyrighted derivative audio — the community
feature and the legal mitigation are the same design decision.

## 2. Technical map, layer by layer

### L0 — Mix Document (the contract)

Today: the `{stems: {...}, global: {...}}` JSON validated by `chat.py` and
consumed by `/render`. Evolution: (1) add `version`, song fingerprint, and
metadata → becomes the **project file**; (2) strip the fingerprint → becomes
the **recipe**, applyable to any song; (3) freeze a public schema → becomes
the API surface for Destiny C. Rule that keeps the architecture honest: no
layer talks to another except through this schema.

### L1 — Audio Core (Destiny A kernel)

Exists: Demucs separation with MPS/CUDA + CPU fallback and content-hash
caching; offline numpy DSP (six panning modes, reverb, slowed, loudness
match, limiter); analysis (BPM, mono compatibility, preview window).
To build: **SeparationProvider abstraction** (local | cloud GPU | in-browser
WebGPU/ONNX) so shells don't care where stems come from; and the **real-time
engine** — the single biggest technical cliff. The offline renderer stays as
the export path; a second executor (Web Audio/AudioWorklet first, native
later) plays the same Mix Document live so sliders are heard instantly.
Building the real-time executor against the same schema is what makes it a
refactor instead of a rewrite.

### L2 — Intent Engine (Destiny C asset)

Exists: schema-constrained chat via Ollama/Gemma 4 with server-side clamping —
the model can only ever emit a valid Mix Document. To build, in order:
**provider abstraction** (any local or cloud LLM behind one interface);
**preset/reference library** (named sounds — "Malibu Sleep," "stadium,"
"AM radio" — as retrievable recipe fragments the model composes instead of
inventing); **critic loop** (extract audio features from the render, feed
them back, let the model self-correct — the step from "translates requests"
to "has taste"). This layer is deliberately thin on dependencies: it maps
language to a documented parameter space, which is exactly what makes it
extractable as an SDK in Year 3.

### L3 — Interface Shells (Destiny B surface)

Exists: local Flask + single-file web UI. To build: **Tauri desktop wrapper**
(signed, notarized, auto-update — Y1); **browser/PWA** once in-browser
separation is viable (Y2); **mobile companion** (Y3, cloud-render dependent).
Shells contain zero audio logic; they render state and emit Mix Documents.

### L4 — Services (optional, revenue-bearing)

All deferred until demand proves itself: cloud GPU rendering (speed + mobile
enabler), accounts/sync, recipe community, and the Intent API/SDK. Nothing in
L0–L3 depends on L4 — the local-first product must remain whole without it,
both as an OSS promise (Destiny A) and as a trust position.

## 3. Three-year plan (traditional stage-gated build)

### Year 1 — Productize. Prototype → v1.0. Solo + occasional contractor.

- **Q1:** Repo, CI running the existing test suite, versioned releases,
  Mix Document v1 formalized (version field, project save/reopen).
  *Gate: a stranger can install from a release and succeed unassisted.*
- **Q2:** Real-time preview engine (Web Audio executor for all six modes +
  master effects); offline renderer becomes export-only.
  *Gate: slider-to-ear latency under 100 ms.*
- **Q3:** Tauri desktop app, signed + notarized; waveform view; undo;
  Windows support. *Gate: double-click install on a clean Mac and PC.*
- **Q4:** v1.0 launch — GitHub, demo videos, small community channel;
  opt-in crash reporting. *Gate: 1,000 installs and a retention signal
  (are people opening it a second week?).*

Cost: near zero cash; nights-and-weekends scale, or ~$10–15K in contracting
(code signing, Windows QA, design polish).

### Year 2 — Differentiate. v1.x → the NL-mixing product. Team of 2–4.

- **H1:** Intent engine v2 — provider abstraction, preset/reference library,
  multi-turn refinement; separation provider abstraction with cloud GPU
  option. *Gate: NL requests succeed on first try for ~80% of a test corpus.*
- **H2:** Browser version (WebGPU separation proof-of-concept); critic loop
  prototype; **monetization gate** — free local forever, paid cloud
  (instant separation, sync, mobile-enabling). Decide funded-company vs.
  sustainable indie based on Year-1 retention.

Cost: 2–4 people ≈ $300–600K/yr loaded if salaried; equity/part-time
otherwise. This is the year that decides whether Destinies B/C are real.

### Year 3 — Platform. Pick the lane the Year-2 data supports. Team of 5–8.

- **Lane B (creator suite):** mobile app, video pairing, publish pipeline —
  requires confronting licensing head-on (label deals or recipe-only sharing).
- **Lane C (engine):** Intent API/SDK licensed into DAWs and creator tools;
  the app becomes the reference client. More defensible; smaller TAM;
  B2B sales motion.
- **Lane A (deliberate smallness):** best-in-class OSS tool, sponsorware
  revenue. A valid outcome, chosen rather than defaulted into.

Funding gate sits here: Lane B almost certainly needs capital; Lane C can
bootstrap on licensing; Lane A needs none.

## 4. Risks and their architectural answers

- **Copyright at distribution scale** — the structural risk of the category.
  Mitigation is baked into L0: share recipes (settings), never rendered
  audio. Rendering stays on-device with the user's own files.
- **Commoditization from above** (Logic ships stem splitting; a platform
  ships stem controls). Mitigation: the defensible layer is L2 — the
  language-to-mix interface — not separation. Treat separation as a
  replaceable commodity from day one (provider abstraction).
- **Local-model dependency** (Ollama/Gemma quality and availability).
  Mitigation: provider abstraction + schema constraint means any model that
  can emit JSON works; quality degrades gracefully to "worse suggestions,"
  never to "broken mixer."
- **The real-time cliff.** Biggest engineering risk; scheduled first
  (Y1 Q2) precisely because everything in Years 2–3 assumes it exists.

## 5. What this changes today

The repo should be laid out to match the map so the seams are real from
commit one:

```
stereo-splitter/
  core/        # L1: separation providers, dsp, effects, analysis
  intent/      # L2: chat providers, prompts, validation, presets
  server/      # Flask app (thin: routes only)
  shells/web/  # L3: the UI
  schema/      # L0: Mix Document JSON schema, versioned
  docs/        # this file
```

License: private repo now; choose MIT (Destiny A) vs. source-available/AGPL
(protects L2 from cloud copycats) before the first outside contributor —
that's the only irreversible-ish choice in the stack.
