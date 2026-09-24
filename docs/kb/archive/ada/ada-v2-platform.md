---
kind: archive-report
bank: chaba-archive
source_repo: ada
source_commit: HEAD-at-archive (manifest ada.yml)
topic: ada-v2-platform
status: historical
period: [2025-12, 2026-02]
follows: [chaba0-era assistant prototypes]
superseded_by: ada-pi (voice) + chaba memory/HA ecosystem
covers:
  - ada_v2/**
extracted: 2026-09-24
extracted_by: devin
---

# Ada v2 platform — archive of ada repo

## Summary

**A.D.A = Advanced Design Assistant** — the direct ancestor of ada-pi.
An Electron+React desktop app backed by a Python FastAPI/Socket.IO
server, built on **Gemini 2.5 Native Audio** for low-latency voice with
interrupt handling. Beyond chat it had real actuators: parametric CAD
generation (build123d → STL), 3D printing (OrcaSlicer + Moonraker/
OctoPrint), MediaPipe gesture UI ("Minority Report"), face-landmarker
biometric login, Playwright web agent, TP-Link Kasa smart-home control,
and file-based project memory.

## Timeline

- 2025-12: ada_v2 codebase present in repo
- 2026-02-02: repo last pushed; frozen
- 2026-02+: voice/design split — voice path evolved into ada-pi
  (Raspberry Pi + HA cards), CAD/print/gesture features dropped
- 2026-09-24: repo distilled → chaba-archive; archived on GitHub

## Still-true facts

- [still-true] Gemini Live/Native-Audio remains the voice engine —
  ada-pi uses the same provider family.
- [still-true] Tool-per-domain backend pattern (cad_agent,
  printer_agent, kasa_agent, web_agent as separate modules) — the same
  shape as ada-pi's tool_runner + domain tools.
- [still-true] Socket.IO/streaming architecture for realtime voice —
  ada-pi uses WS + PCM worklets; same realtime model.
- [historical] CAD/3D-printing features (build123d, OrcaSlicer,
  Moonraker) — no successor in ada-pi; dormant capability.
- [historical] MediaPipe gesture UI + face-landmarker auth — dropped;
  ada-pi uses voiceprint + API keys instead.
- [historical] Electron+React desktop — replaced by PWA + HA cards
  (decision ada-ha-native-primary-ui).
- [historical] Kasa smart-home agent — superseded by Home Assistant
  integration (broader device coverage).
- [historical] File-based JSON "project memory" — superseded by MDDB
  memory banks.

## Key details

**Backend (Python 3.11, FastAPI + Socket.IO)**: `server.py` (56KB) was
the hub; `ada.py` (113KB) wrapped the Gemini Live session; agents were
separate modules: `cad_agent.py` (build123d parametric models → STL),
`printer_agent.py` (OrcaSlicer slicing + Moonraker/OctoPrint submit),
`kasa_agent.py` (python-kasa device control), `web_agent.py`
(Playwright browser automation), `authenticator.py` (MediaPipe face
auth), `capture_face.py`, `project_manager.py` (JSON project memory),
`tools.py`, `temp_cad_gen.py`.

**Gesture model**: pinch = confirm/click, open palm = release window,
fist = grab+drag window — a hand-tracking window manager.

**Lineage note**: the name "Ada" + Gemini voice + tool-agent shape all
originate here; ada-pi kept the voice+tools core and traded the
CAD/vision/gesture surface for memory banks + HA integration.

## Source map

- `ada_v2/README.md` → Summary, capabilities table, architecture
- `ada_v2/backend/*.py` → Key details (module responsibilities from
  headers/docstrings; code-level detail not distilled — see Not
  preserved)
- `ada_v2/frontend/`, Dockerfiles, Caddyfile, ci.yml → deployment
  shape (Electron build + containerized backend)

## Not preserved

- Per-module code internals (~300KB of agent/server code) — concepts
  captured; code stays in git history if ever resurrected.
- `face_landmarker.task` (3.7MB MediaPipe model) — binary asset,
  excluded-noise.
- CAD feature parameters, printer profiles, gesture thresholds —
  implementation details of dropped features.
- `.env.example` contents — superseded by current secrets layout.
