# Stereo Splitter — Loop Log & Backlog

*This document is the operational counterpart to [ROADMAP.md](ROADMAP.md). The
roadmap says where we're going and why; this file says how the work actually
happens: as a sequence of small, verified, agent-executed loops. The quarterly
plan in ROADMAP §3 is restructured here into that loop backlog.*

## Methodology

Karpathy-style loops. Every unit of work is one pass through:

**spec → generate → verify → commit**

- **Spec.** A human (or the orchestrator) writes a 2–3 sentence spec with an
  explicit, checkable **gate** — the loop's definition of done.
- **Generate.** A subagent does the labor: it gets the spec, the constraints,
  and a scoped list of files it may touch. It produces a diff, nothing more.
- **Verify.** The orchestrator — not the generator — runs the full test suite
  plus the loop's gate check. Green means the gate passed, not that the code
  "looks done." Red goes back to the generator with the failing output.
- **Commit.** One loop, one commit. Small diffs, always-green tests as the
  reward signal, git history as the loop log.

Humans set direction and define gates; agents do the labor. The tests and the
Mix Document schema are what make this safe: any loop that breaks the contract
or the suite simply doesn't land.

## Completed loops

| Loop | What | Gate |
|------|------|------|
| L0 | Baseline commit — working prototype captured as-is | Repo runs; behavior is the reference for everything after |
| L1 | Layered restructure — `core/`, `intent/`, `server/`, `shells/web/`, root `app.py` shim | Identical behavior; all routes green |
| L2 | Schema + CI + docs — Mix Document schema v1, GitHub Actions workflow, this document | Schema validates render payloads |
| L3 | Test suite in repo — DSP, server, and chat suites (separation mocked) | All suites green locally |
| L4 | Fresh-clone verification | Clean clone passes the suite |

## Backlog loops

Ordered roughly by dependency, not strictly by roadmap quarter. Roadmap
mapping: **Year 1** = L6, L10 (plus L0–L4, which are Y1 Q1's "repo, CI,
Mix Document v1"); **Year 2** = L5, L7, L8, L9 (H1) and L12, L13 (H2);
**Year 3** = L11, L14.

### L5 — Separation-provider abstraction *(ROADMAP Y2 H1; §2 L1)*

Extract Demucs behind a `SeparationProvider` interface — `separate(file) →
stems` — selected by environment variable, with local Demucs as the default
and a mock provider for tests. Nothing outside the provider may import Demucs;
separation is a replaceable commodity from day one (ROADMAP §4).

**Gate:** swap provider via env var; suite green under both the mock and the
local Demucs provider.

### L6 — Web Audio real-time executor *(ROADMAP Y1 Q2 — the real-time cliff)*

Build a second executor for the Mix Document in the browser using Web
Audio/AudioWorklet: all six placement modes plus master effects, played live
so sliders are heard instantly. The offline numpy renderer stays as the export
path; both executors consume the identical document, which is what makes this
a refactor instead of a rewrite.

**Gate:** slider-to-ear latency under 100 ms; the offline render remains
byte-comparable for the same document.

### L7 — Intent provider abstraction *(ROADMAP Y2 H1; §2 L2)*

Put the LLM behind a provider interface — `complete(messages, schema) → Mix
Document` — with Ollama as the default and at least one alternative backend.
Schema constraint and server-side clamping live outside the provider, so any
backend degrades to "worse suggestions," never to "broken mixer."

**Gate:** two different LLM backends pass the NL test corpus.

### L8 — NL test corpus + eval harness *(ROADMAP Y2 H1 gate)*

Build a corpus of natural-language mixing requests paired with expected Mix
Document outcomes (exact or property-based assertions), plus a harness that
runs the corpus against the intent engine and reports first-try success rate.
This becomes the reward signal for every intent-layer loop after it, including
L7, L9, and L12.

**Gate:** at least 80% first-try success, with the score tracked per loop.

### L9 — Preset/reference library *(ROADMAP Y2 H1; §2 L2)*

Named sounds — "Malibu Sleep," "stadium," "AM radio" — stored as retrievable
recipe fragments that the model composes instead of inventing, and exposed to
the UI as one-click presets. Fragments are partial Mix Documents, validated
against the same schema as everything else.

**Gate:** named references resolve to recipe fragments.

### L10 — Tauri desktop shell *(ROADMAP Y1 Q3)*

Wrap the web shell in Tauri with code signing and notarization. The shell
contains zero audio logic — it renders state and emits Mix Documents against
the local server, exactly like the browser UI does today.

**Gate:** signed app boots on a clean macOS machine.

### L11 — Recipe sharing *(ROADMAP Y3 / §1 — the L0 evolution)*

Export a Mix Document stripped of song-specific data as a shareable recipe;
import applies it to whatever song is loaded, clamped through the schema.
Settings travel, rendered audio never does — the community feature and the
copyright mitigation are the same design decision.

**Gate:** a recipe exported from one song applies cleanly to a different song.

### L12 — Critic loop *(ROADMAP Y2 H2)*

Extract audio features from the render — loudness, stereo width, spectral
tilt — feed them back to the model, and let it self-correct the Mix Document
over one or two iterations. This is the step from "translates requests" to
"has taste."

**Gate:** self-corrected renders beat single-shot renders on the eval corpus.

### L13 — WebGPU in-browser separation PoC *(ROADMAP Y2 H2)*

Proof-of-concept `SeparationProvider` that runs separation in the browser via
WebGPU/ONNX — correctness over speed. It slots behind the L5 interface
unchanged, which is the whole point of having built L5 first.

**Gate:** one real song separates fully in-browser and its stems load into the
existing mixer; suite stays green.

### L14 — Cloud render provider *(ROADMAP Y3; §2 L4)*

Optional cloud GPU rendering behind the same provider seams — the speed play
and the mobile enabler. Nothing in the local-first product may depend on it:
with the provider disabled, the product must remain whole (the OSS promise
and the trust position from ROADMAP §2 L4).

**Gate:** the same Mix Document renders equivalently local and cloud; with
the provider disabled, the full suite still passes.

## Running a loop

### Generator prompt template

```
You are the generator for loop L<N>: <one-line spec>.

Repo: <path>. Read docs/LOOPS.md (the L<N> entry) and the relevant
ROADMAP.md section first.

Constraints:
- Touch ONLY: <explicit file/directory list for this loop>.
- All cross-layer communication goes through
  schema/mix_document.schema.json — no side channels.
- Keep the diff small; do not refactor outside the spec.
- Do not commit. The orchestrator verifies and commits.

Done means: <the gate, restated as something the orchestrator can run
or measure>.
```

### Orchestrator verification checklist

1. **Scope check** — the diff touches only in-scope files and is small enough
   to read in full.
2. **Suite** — `python tests/test_dsp.py`, `python tests/test_server.py`,
   `python tests/test_chat.py`: all green.
3. **Gate check** — run the loop's specific gate (the command or measurement
   named in its backlog entry).
4. **Contract check** — any new or changed payloads validate against
   `schema/mix_document.schema.json`.
5. **Smoke** — boot the server, exercise the routes the loop touched.
6. **Land or loop** — green: commit as `L<N>: <spec> (gate: <result>)`.
   Red: return the failing output to the generator and run the loop again.
