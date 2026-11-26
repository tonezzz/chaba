#!/usr/bin/env python3
"""Asset identity and continuity control for the Ada Nest documentary pipeline.

Extends the doc-pilot pack chain (script.yml -> VYNCX VO -> LTX shots ->
assemble) with a deterministic control plane, staged P0..P3:

  P0  immutable per-shot manifest, asset IDs, scratch-VO timing,
      technical QA binding (scripts/ops/video-qc.py)
  P1  character/object/location bibles + continuity ledger +
      DWPose/depth control slots
  P2  deterministic scene slots (Blender/stock/space/Gaussian plates)
      + SCoPE camera control fields
  P3  small VBench/T2V-CompBench/VideoScore2 fixture + scene-graph
      grounding

Everything here is additive: existing packs, the LTX/VYNCX lanes, and
durable pack artifacts are untouched. The module only reads script /
storyboard / bible / ledger inputs and writes new manifest, ledger,
approved-take, and fixture artifacts.

Subcommands:
  build     script.yml + storyboard.yml -> shots/shot-manifest-v2.json
  bibles    validate assets/bibles.yml
  ledger    append|verify qc/continuity-ledger.jsonl events
  takes     ledger -> qc/approved-takes.json
  verify    stage verifier over a project dir (manifest+bibles+ledger+
            takes+optional artifact QC)
  fixture   manifest+bibles -> evals/<doc>-fixture-v1.json (P3)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_MANIFEST = "nest-doc-shot-manifest-v1"
SCHEMA_BIBLES = "nest-doc-bibles-v1"
SCHEMA_LEDGER = "nest-doc-continuity-v1"
SCHEMA_TAKES = "nest-doc-approved-takes-v1"
SCHEMA_FIXTURE = "nest-doc-eval-fixture-v1"

VO_TOLERANCE = 0.15       # measured VO may exceed the slot by 15% before fail
MIN_SHOT_SLOT_S = 0.5     # below this a shot cannot carry narration
I2V_RE = re.compile(r"^i2v-from-shot-(\d+)$")
SHOT_FILE_RE = re.compile(r"^(?:.*-)?(?:shot|vo)-(\d+)\.(?:mp4|wav)$")


# ---------------------------------------------------------------- helpers

def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


def _dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wav_seconds(path: Path) -> float | None:
    """Duration of a PCM wav via the stdlib; None when unreadable."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


def _shot_sort_key(shot: dict):
    try:
        return int(shot.get("shot", 0))
    except (TypeError, ValueError):
        return 0


def _index_by_shot(rows: list[dict]) -> dict[int, dict]:
    out = {}
    for row in rows:
        try:
            out[int(row.get("shot", row.get("id", -1)))] = row
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- build

def cmd_build(args) -> int:
    script = _load_yaml(args.script)
    storyboard = _load_yaml(args.storyboard) if args.storyboard else {}

    script_shots = _index_by_shot(script.get("shots") or [])
    board_shots = _index_by_shot(storyboard.get("shots") or [])
    shot_ids = sorted(set(script_shots) | set(board_shots))
    if not shot_ids:
        print("build: no shots found in script/storyboard", file=sys.stderr)
        return 2

    doc_id = str(script.get("doc") or storyboard.get("doc") or
                 args.doc_id or "doc")
    render = dict(storyboard.get("render") or {})
    fps = float(render.get("fps") or 24)
    frames = int(render.get("num_frames") or 0)
    slot_s = (frames / fps) if frames else None

    # scratch-VO timing: est_s from the script; measured duration when a
    # matching VO wav is present in --vo-dir (v3-vo-NN.wav / ss1-vo-NN.wav).
    vo_dir = Path(args.vo_dir) if args.vo_dir else None
    vo_files = {}
    if vo_dir and vo_dir.is_dir():
        for wav in vo_dir.glob("*.wav"):
            m = SHOT_FILE_RE.match(wav.name)
            if m:
                vo_files[int(m.group(1))] = wav

    shots = []
    for n in shot_ids:
        srow = script_shots.get(n, {})
        brow = board_shots.get(n, {})
        prompt = brow.get("prompt") or srow.get("prompt") or ""
        continuity = str(brow.get("continuity") or srow.get("continuity")
                         or "t2v")
        m = I2V_RE.match(continuity)
        prev_shot = int(m.group(1)) if m else None

        est_s = srow.get("est_s")
        vo = {"est_s": est_s, "measured_s": None, "file": None,
              "slot_s": slot_s, "overrun": False, "underrun": False}
        if n in vo_files:
            measured = _wav_seconds(vo_files[n])
            vo["file"] = vo_files[n].name
            vo["measured_s"] = round(measured, 3) if measured else None
        effective_slot = slot_s or (float(est_s) * 1.25
                                    if est_s else None)
        vo["effective_slot_s"] = effective_slot
        if vo["measured_s"] and effective_slot:
            if vo["measured_s"] > effective_slot * (1 + VO_TOLERANCE):
                vo["overrun"] = True
            elif vo["measured_s"] < MIN_SHOT_SLOT_S:
                vo["underrun"] = True

        obj = srow.get("object") or brow.get("object")
        chars = srow.get("characters") or brow.get("characters") or []
        if isinstance(chars, str):
            chars = [chars]
        shots.append({
            "asset_id": f"{doc_id}-s{n:02d}",
            "shot": n,
            "beat": srow.get("beat"),
            "prompt": prompt,
            "continuity": continuity,
            "prev_shot": prev_shot,
            "vo": vo,
            "assets": {
                "object": obj,
                "characters": chars,
                "location": srow.get("location") or brow.get("location"),
            },
            "controls": {
                # P1: pose/depth control inputs (DWPose skeleton + depth map)
                "pose": None,
                "depth": None,
                # P2: deterministic scene + camera control
                "scene": None,     # blender|stock|space|gaussian plate ref
                "camera": None,    # SCoPE trajectory / plate camera id
                # P3: scene-graph grounding for eval fixtures
                "scene_graph": None,
            },
            "qc": {
                "required": list((storyboard.get("qc") or {})
                                 .get("per_shot") or []),
                "video_qc": "scripts/ops/video-qc.py",
            },
            "takes": [],
        })

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "doc_id": doc_id,
        "built_at": _now(),
        "builder": "scripts/nest/doc_control.py build",
        "render": render,
        "style_suffix": storyboard.get("style_suffix"),
        "negative": storyboard.get("negative"),
        "script_meta": {
            k: script[k] for k in
            ("version", "status", "language_primary", "narrator",
             "estimated_runtime_s", "viewpoint", "scope", "data_rules")
            if k in script
        },
        "shots": shots,
    }
    _dump_json(Path(args.out), manifest)
    print(f"build: {len(shots)} shots -> {args.out}")
    overruns = [s["asset_id"] for s in shots if s["vo"]["overrun"]]
    if overruns:
        print("build: WARN vo overrun on " + ", ".join(overruns),
              file=sys.stderr)
    return 0


# ---------------------------------------------------------------- bibles

def validate_bibles(bibles: dict, doc_id: str | None = None) -> list[str]:
    errors = []
    if bibles.get("schema") != SCHEMA_BIBLES:
        errors.append(f"schema must be {SCHEMA_BIBLES}")
    if doc_id and bibles.get("doc_id") not in (None, doc_id):
        errors.append(f"doc_id {bibles.get('doc_id')!r} != {doc_id!r}")
    for section in ("characters", "objects", "locations"):
        rows = bibles.get(section) or []
        if not isinstance(rows, list):
            errors.append(f"{section}: must be a list")
            continue
        seen = set()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{section}[{i}]: not a mapping")
                continue
            rid = row.get("id")
            if not rid:
                errors.append(f"{section}[{i}]: missing id")
                continue
            if rid in seen:
                errors.append(f"{section}: duplicate id {rid!r}")
            seen.add(rid)
            if section == "characters" and not row.get("description"):
                errors.append(f"character {rid!r}: missing description")
            if section == "objects" and not row.get("kind"):
                errors.append(f"object {rid!r}: missing kind")
            if section == "locations" and not row.get("description"):
                errors.append(f"location {rid!r}: missing description")
    return errors


def cmd_bibles(args) -> int:
    bibles = _load_yaml(args.bibles)
    errors = validate_bibles(bibles, args.doc_id)
    for e in errors:
        print(f"bibles: FAIL {e}", file=sys.stderr)
    if errors:
        return 1
    total = sum(len(bibles.get(s) or [])
                for s in ("characters", "objects", "locations"))
    print(f"bibles: ok ({total} assets, doc={bibles.get('doc_id')})")
    return 0


def _bible_ids(bibles: dict) -> dict[str, set[str]]:
    return {s: {r.get("id") for r in (bibles.get(s) or [])
                if isinstance(r, dict) and r.get("id")}
            for s in ("characters", "objects", "locations")}


# ---------------------------------------------------------------- ledger

def _ledger_path(project: Path) -> Path:
    return project / "qc" / "continuity-ledger.jsonl"


def ledger_events(project: Path) -> list[dict]:
    path = _ledger_path(project)
    if not path.is_file():
        return []
    events = []
    for i, line in enumerate(path.read_text(encoding="utf-8")
                             .splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ledger line {i}: {exc}")
        if ev.get("schema") != SCHEMA_LEDGER:
            raise ValueError(f"ledger line {i}: bad schema")
        events.append(ev)
    return events


def cmd_ledger(args) -> int:
    project = Path(args.project)
    path = _ledger_path(project)
    if args.ledger_cmd == "append":
        missing = [k for k in ("shot", "asset_id", "take", "event")
                   if getattr(args, k) is None]
        if missing:
            print(f"ledger append: missing {', '.join(missing)}",
                  file=sys.stderr)
            return 2
        ev = {
            "schema": SCHEMA_LEDGER,
            "at": _now(),
            "shot": args.shot,
            "asset_id": args.asset_id,
            "take": int(args.take) if str(args.take).isdigit()
                    else args.take,
            "event": args.event,
            "artifact": args.artifact,
            "qc_ok": args.qc_ok,
            "note": args.note,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        print(f"ledger: appended {args.event} shot={args.shot} "
              f"take={args.take}")
        return 0
    # verify
    events = ledger_events(project)
    rendered = {}
    approved = {}
    for ev in events:
        if ev.get("event") == "rendered":
            rendered.setdefault(ev.get("shot"), set()).add(ev.get("take"))
        if ev.get("event") == "approved":
            approved[ev.get("shot")] = ev.get("take")
    print(json.dumps({
        "events": len(events),
        "shots_rendered": sorted(k for k in rendered if k is not None),
        "shots_approved": {str(k): v for k, v in sorted(
            approved.items(), key=lambda kv: str(kv[0]))},
    }, indent=2))
    return 0


# ---------------------------------------------------------------- takes

def cmd_takes(args) -> int:
    project = Path(args.project)
    manifest = json.loads((project / "shots" /
                           "shot-manifest-v2.json").read_text())
    events = ledger_events(project)
    by_shot: dict[int, list[dict]] = {}
    for ev in events:
        if ev.get("shot") is not None:
            by_shot.setdefault(int(ev["shot"]), []).append(ev)

    shots_out = []
    missing = []
    for shot in manifest["shots"]:
        n = int(shot["shot"])
        evs = by_shot.get(n, [])
        approved = [e for e in evs if e.get("event") == "approved"]
        rendered = [e for e in evs if e.get("event") == "rendered"]
        if not rendered:
            missing.append(shot["asset_id"])
            shots_out.append({
                "asset_id": shot["asset_id"], "shot": n, "take": None,
                "artifact": None, "sha256": None, "qc_ok": False,
                "approved": False, "events": len(evs),
                "note": "no rendered take",
            })
            continue
        take = (approved[-1] if approved else rendered[-1]).get("take")
        artifact = next((e.get("artifact") for e in reversed(evs)
                         if e.get("artifact")), None)
        art_path = None
        sha = None
        if artifact:
            cand = project / artifact
            if not cand.is_file():
                cand = Path(artifact)
            if cand.is_file():
                art_path = str(cand)
                sha = _sha256(cand)
        shots_out.append({
            "asset_id": shot["asset_id"],
            "shot": n,
            "take": take,
            "artifact": art_path,
            "sha256": sha,
            "qc_ok": all(e.get("qc_ok") is not False for e in evs),
            "approved": bool(approved),
            "events": len(evs),
        })

    doc = {"schema": SCHEMA_TAKES, "doc_id": manifest.get("doc_id"),
           "generated_at": _now(), "shots": shots_out}
    out = project / "qc" / "approved-takes.json"
    _dump_json(out, doc)
    print(f"takes: {len(shots_out)} shots -> {out}")
    if missing:
        print("takes: WARN no rendered take for " +
              ", ".join(missing), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- verify

def cmd_verify(args) -> int:
    project = Path(args.project)
    checks: list[tuple[str, str, list[str]]] = []  # name, status, errors

    def add(name, errors, warns=None):
        status = "fail" if errors else ("warn" if warns else "pass")
        checks.append((name, status, errors or warns or []))

    manifest_path = project / "shots" / "shot-manifest-v2.json"
    manifest = None
    if not manifest_path.is_file():
        add("manifest", ["shots/shot-manifest-v2.json missing — run `build`"])
    else:
        try:
            manifest = json.loads(manifest_path.read_text())
            errs = []
            if manifest.get("schema") != SCHEMA_MANIFEST:
                errs.append(f"schema must be {SCHEMA_MANIFEST}")
            shots = manifest.get("shots") or []
            if not shots:
                errs.append("manifest has no shots")
            nums = [int(s.get("shot", -1)) for s in shots]
            if sorted(nums) != list(range(1, len(nums) + 1)):
                errs.append(f"shot numbers not contiguous 1..{len(nums)}")
            ids = [s.get("asset_id") for s in shots]
            if len(set(ids)) != len(ids):
                errs.append("duplicate asset_id")
            for s in shots:
                if not s.get("prompt"):
                    errs.append(f"{s.get('asset_id')}: empty prompt")
                if s.get("vo", {}).get("overrun"):
                    errs.append(f"{s['asset_id']}: VO overrun "
                                f"{s['vo']['measured_s']}s > slot "
                                f"{s['vo']['effective_slot_s']}s")
                if s.get("vo", {}).get("underrun"):
                    errs.append(f"{s['asset_id']}: VO under-run "
                                "(<0.5s) — likely silent take")
            # continuity DAG: prev_shot must point at an existing shot
            known = set(nums)
            for s in shots:
                prev = s.get("prev_shot")
                if prev is not None and prev not in known:
                    errs.append(f"{s['asset_id']}: prev_shot {prev} "
                                "not in manifest")
                if prev is not None and prev >= int(s["shot"]):
                    errs.append(f"{s['asset_id']}: i2v link must point "
                                "to an earlier shot")
            add("manifest", errs)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            add("manifest", [f"unreadable: {exc}"])
            manifest = None

    # bibles + asset resolution
    bibles_path = project / "assets" / "bibles.yml"
    bible_errs = []
    bible_warns = []
    ids = None
    if bibles_path.is_file():
        try:
            bibles = _load_yaml(bibles_path)
            bible_errs = validate_bibles(bibles, manifest.get("doc_id")
                                         if manifest else None)
            ids = _bible_ids(bibles)
            if manifest:
                for s in manifest["shots"]:
                    a = s.get("assets") or {}
                    for cid in a.get("characters") or []:
                        if cid not in ids["characters"]:
                            bible_errs.append(
                                f"{s['asset_id']}: character {cid!r} "
                                "not in bibles")
                    if a.get("object") and a["object"] not in ids["objects"]:
                        bible_errs.append(
                            f"{s['asset_id']}: object {a['object']!r} "
                            "not in bibles")
                    if (a.get("location")
                            and a["location"] not in ids["locations"]):
                        bible_errs.append(
                            f"{s['asset_id']}: location "
                            f"{a['location']!r} not in bibles")
        except (OSError, ValueError) as exc:
            bible_errs.append(f"bibles.yml unreadable: {exc}")
    else:
        bible_warns.append("assets/bibles.yml absent — P1 asset identity "
                           "not yet declared")
    add("bibles", bible_errs, bible_warns)

    # continuity ledger + approved takes
    try:
        events = ledger_events(project)
    except ValueError as exc:
        add("ledger", [str(exc)])
        events = []
    else:
        add("ledger", [] if events else
            ["qc/continuity-ledger.jsonl absent — no take history"],
            None if events else
            ["ledger empty; approved-takes cannot be verified"])

    takes_path = project / "qc" / "approved-takes.json"
    take_errs = []
    if takes_path.is_file():
        try:
            takes = json.loads(takes_path.read_text())
            if takes.get("schema") != SCHEMA_TAKES:
                take_errs.append(f"schema must be {SCHEMA_TAKES}")
            approved_events = {(e.get("shot"), e.get("take"))
                               for e in events
                               if e.get("event") == "approved"}
            for row in takes.get("shots") or []:
                if row.get("approved") and (row.get("shot"),
                                            row.get("take")) \
                        not in approved_events:
                    take_errs.append(
                        f"{row.get('asset_id')}: approved take "
                        f"{row.get('take')} has no approved ledger event")
        except (OSError, json.JSONDecodeError) as exc:
            take_errs.append(f"unreadable: {exc}")
    else:
        take_errs.append("qc/approved-takes.json missing — run `takes`")
    add("approved-takes", take_errs)

    # P1-P3 coverage report (informational, never fails the gate)
    coverage = {"pose": 0, "depth": 0, "scene": 0, "camera": 0,
                "scene_graph": 0}
    if manifest:
        for s in manifest.get("shots") or []:
            c = s.get("controls") or {}
            for k in coverage:
                if c.get(k):
                    coverage[k] += 1
    n = len(manifest.get("shots") or []) if manifest else 0
    cov = {k: f"{v}/{n}" for k, v in coverage.items()}

    # optional artifact QC binding
    if args.require_artifacts and manifest:
        art_errs = []
        for s in manifest["shots"]:
            qc_json = project / "qc" / f"{s['asset_id']}.qc.json"
            if qc_json.is_file():
                try:
                    res = json.loads(qc_json.read_text())
                    if res.get("ok") is not True:
                        art_errs.append(f"{s['asset_id']}: video-qc not ok")
                except json.JSONDecodeError:
                    art_errs.append(f"{s['asset_id']}: qc json corrupt")
        add("artifact-qc", art_errs or
            ["no per-shot qc json found under qc/"])

    verdict = {"project": str(project), "at": _now(),
               "stage_coverage": cov, "checks": [
                   {"name": n_, "status": st, "detail": d}
                   for n_, st, d in checks]}
    n_fail = sum(1 for _, st, _ in checks if st == "fail")
    n_warn = sum(1 for _, st, _ in checks if st == "warn")
    verdict["verdict"] = "fail" if n_fail else ("warn" if n_warn else "pass")
    out = project / "qc" / "control-verify.json"
    _dump_json(out, verdict)
    for n_, st, d in checks:
        print(f"verify: {st:4} {n_}" +
              (f" — {'; '.join(d[:3])}" if d else ""))
    print(f"verify: coverage {cov} -> verdict={verdict['verdict']} ({out})")
    return 1 if n_fail else 0


# ---------------------------------------------------------------- fixture

def cmd_fixture(args) -> int:
    project = Path(args.project)
    manifest = json.loads((project / "shots" /
                           "shot-manifest-v2.json").read_text())
    bibles = {}
    bp = project / "assets" / "bibles.yml"
    if bp.is_file():
        bibles = _load_yaml(bp)
    fact_index = {}
    for row in (bibles.get("objects") or []):
        if isinstance(row, dict) and row.get("id"):
            fact_index[row["id"]] = row.get("facts") or {}

    cases = []
    for s in manifest.get("shots") or []:
        assets = s.get("assets") or {}
        objects = [o for o in [assets.get("object")] if o]
        relations = []
        if s.get("prev_shot") is not None:
            relations.append({"type": "continues_from",
                              "shot": s["prev_shot"]})
        if objects:
            relations.append({"type": "depicts", "object": objects[0]})
        cases.append({
            "id": s["asset_id"],
            "shot": s["shot"],
            "prompt": s.get("prompt"),
            "negative": manifest.get("negative"),
            "seed": (manifest.get("render") or {}).get("seed"),
            "est_duration_s": (s.get("vo") or {}).get("est_s"),
            "scene_graph": {
                "objects": objects,
                "characters": assets.get("characters") or [],
                "location": assets.get("location"),
                "relations": relations,
                "facts": {o: fact_index.get(o, {}) for o in objects},
            },
        })

    fixture = {
        "schema": SCHEMA_FIXTURE,
        "doc_id": manifest.get("doc_id"),
        "generated_at": _now(),
        "benchmarks": ["vbench", "t2v-compbench", "videoscore2"],
        "note": "small grounded fixture; prompts verbatim from the shot "
                "manifest so evals measure the real render inputs",
        "cases": cases,
    }
    out = project / "evals" / f"{manifest.get('doc_id')}-fixture-v1.json"
    _dump_json(out, fixture)
    print(f"fixture: {len(cases)} cases -> {out}")
    return 0


# ---------------------------------------------------------------- cli

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="script+storyboard -> shot manifest")
    p.add_argument("--script", type=Path, required=True)
    p.add_argument("--storyboard", type=Path)
    p.add_argument("--vo-dir", type=Path,
                   help="dir of vo-*.wav for measured scratch-VO timing")
    p.add_argument("--doc-id")
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("bibles", help="validate assets/bibles.yml")
    p.add_argument("bibles", type=Path)
    p.add_argument("--doc-id")
    p.set_defaults(fn=cmd_bibles)

    p = sub.add_parser("ledger", help="append|verify continuity ledger")
    p.add_argument("ledger_cmd", choices=["append", "verify"])
    p.add_argument("project", type=Path)
    p.add_argument("--shot", type=int)
    p.add_argument("--asset-id")
    p.add_argument("--take")
    p.add_argument("--event",
                   choices=["rendered", "qc", "approved", "rejected"])
    p.add_argument("--artifact")
    p.add_argument("--qc-ok", action="store_true", default=None)
    p.add_argument("--no-qc-ok", dest="qc_ok", action="store_false")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_ledger)

    p = sub.add_parser("takes", help="ledger -> approved-takes.json")
    p.add_argument("project", type=Path)
    p.set_defaults(fn=cmd_takes)

    p = sub.add_parser("verify", help="stage verifier over project dir")
    p.add_argument("project", type=Path)
    p.add_argument("--require-artifacts", action="store_true")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("fixture", help="P3 eval fixture from manifest")
    p.add_argument("project", type=Path)
    p.set_defaults(fn=cmd_fixture)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
