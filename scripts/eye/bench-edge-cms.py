#!/usr/bin/env python3
"""bench-edge-cms.py — 'bench-edge' page in ada-cms-pages.

The /apps/eye/ page posts a bench/edge-<ts> doc to ada-ha-scenario-
reports after every ?bench=N run (fps, inference p50/p95, model, UA).
This script trends those rows into one CMS page — the answer to "can my
iPhone carry it", per device, per model.

Runs on tony-dell (systemd timer, hourly) or on demand. Writes:
  - ada-cms-pages/bench-edge           the trend page
  - apps/reports/bench-edge-trend.png  fps-over-time chart (PIL)
  - ada-cms-pages/reports-index        regenerated via scripts/lib/cms_index

Page contract: docs/ssot/infrastructure/ssot.cms.yml — bench-* keys are
domain=bench, which lands in the 'Bench' nav section; the page carries
kind/domain/status/summary/fresh_for and this script's generated_by.

Env:
  MDDB_BASE_URL   default http://100.102.134.91:11023/v1
  EYE_PUBLIC      reports dir root — default the live checkout's
                  stacks/web/public (overridable for tests)
Flags:
  --dry-run       render + print, no MDDB writes, no chart file
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))
import cms_index  # noqa: E402

MDDB = os.environ.get(
    "MDDB_BASE_URL", "http://100.102.134.91:11023/v1").rstrip("/")
PUBLIC = Path(os.environ.get(
    "EYE_PUBLIC",
    str(Path.home()
        / "CascadeProjects/chaba-tony-dell/stacks/web/public")))
SRC_COLLECTION = "ada-ha-scenario-reports"
PAGE_COLLECTION = "ada-cms-pages"
SLUG = "bench-edge"
GENERATOR = "bench-edge-cms"
FRESH_FOR = "7d"          # bench rows are sporadic — not a liveness signal
DRY = "--dry-run" in sys.argv
CHART_NAME = "bench-edge-trend.png"

_JSON_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


# ---------- mddb ----------

def mddb_post(path: str, payload: dict, timeout: float = 30):
    req = urllib.request.Request(
        f"{MDDB}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def mddb_get(key: str) -> dict | None:
    try:
        return mddb_post("get", {"collection": PAGE_COLLECTION,
                                 "key": key, "lang": "en"})
    except urllib.error.HTTPError as exc:
        if exc.code != 400:   # 400 {"error":"not found"} = absent doc
            print(f"mddb get {key}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"mddb get {key}: {exc}", file=sys.stderr)
        return None


def mddb_write(key: str, md: str, meta: dict) -> bool:
    body = json.dumps({"collection": PAGE_COLLECTION, "key": key,
                       "lang": "en", "contentMd": md,
                       "meta": meta}).encode()
    if DRY:
        print(f"[dry] would write {key} ({len(body)}B)")
        return True
    try:
        mddb_post("add", json.loads(body))
        return True
    except Exception as exc:
        print(f"mddb add {key}: {exc}", file=sys.stderr)
        return False


# ---------- bench rows ----------

def bench_rows() -> list[dict]:
    """Parse every bench/edge-* doc. The payload is a ```json fence in
    contentMd (eye-page writer); tolerate meta-only docs."""
    docs = cms_index.list_docs(MDDB, SRC_COLLECTION)
    rows = []
    for d in docs:
        key = d.get("key") or ""
        if not key.startswith("bench/edge-"):
            continue
        row = {}
        m = _JSON_FENCE.search(d.get("contentMd") or "")
        if m:
            try:
                row = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        if not row:
            # meta fallback — enough for a degraded row
            meta = d.get("meta") or {}
            row = {"model": (meta.get("model") or ["?"])[0],
                   "ua": (meta.get("ua") or [""])[0],
                   "ts": (meta.get("updated") or [""])[0]}
        row["_key"] = key
        rows.append(row)
    rows.sort(key=lambda r: r.get("ts") or "")
    return rows


def lane_rows() -> list[dict]:
    """Parse every bench/lane-* doc — nest-train-loop.py lane-bench
    output. Payload is a ```json fence; meta fallback carries
    lane/model/score/p50_ms/p95_ms."""
    docs = cms_index.list_docs(MDDB, SRC_COLLECTION)
    rows = []
    for d in docs:
        key = d.get("key") or ""
        if not key.startswith("bench/lane-"):
            continue
        row = {}
        m = _JSON_FENCE.search(d.get("contentMd") or "")
        if m:
            try:
                row = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        meta = d.get("meta") or {}
        if not row:
            row = {"lane": (meta.get("lane") or ["?"])[0],
                   "host": (meta.get("host") or ["?"])[0],
                   "runtime": (meta.get("runtime") or ["?"])[0],
                   "model": (meta.get("model") or ["?"])[0],
                   "score": (meta.get("score") or ["?"])[0],
                   "probe": {"p50_ms": (meta.get("p50_ms") or ["?"])[0],
                             "p95_ms": (meta.get("p95_ms") or ["?"])[0],
                             "n": "?"},
                   "ts": (meta.get("ts") or meta.get("updated")
                          or [""])[0]}
        row["_key"] = key
        rows.append(row)
    rows.sort(key=lambda r: r.get("ts") or "")
    return rows


def ua_label(ua: str) -> str:
    """Compact device label from a user-agent string."""
    if not ua:
        return "unknown"
    dev = "Linux"
    low = ua.lower()
    if "iphone" in low:
        dev = "iPhone"
    elif "ipad" in low:
        dev = "iPad"
    elif "android" in low:
        dev = "Android"
    elif "mac os x" in low or "macintosh" in low:
        dev = "Mac"
    elif "windows" in low:
        dev = "Windows"
    if "headless" in low:
        br = "headless-chrome"
    elif "edg/" in low:
        br = "Edge"
    elif "chrome/" in low:
        br = "Chrome"
    elif "safari/" in low and "chrome" not in low:
        br = "Safari"
    elif "firefox/" in low:
        br = "Firefox"
    else:
        br = "browser"
    return f"{dev}/{br}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso() -> str:
    return _now().isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------- chart ----------

PALETTE = ["#4cd2ff", "#ffb454", "#7ee08c", "#ff7b72", "#d2a8ff",
           "#f2cc60", "#56d4dd", "#ff9bce"]

def draw_chart(rows: list[dict], out: Path) -> bool:
    """fps (1000/p50) over time, one series per device label."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    series: dict[str, list[tuple[float, float]]] = {}
    t0 = None
    for r in rows:
        p50 = r.get("infer_ms_p50")
        ts = r.get("ts")
        if not p50 or not ts:
            continue
        try:
            t = datetime.datetime.fromisoformat(
                ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        t0 = t if t0 is None else min(t0, t)
        series.setdefault(ua_label(r.get("ua", "")),
                          []).append((t, 1000.0 / p50))
    if not series or t0 is None:
        return False
    W, H, pad_l, pad_b, pad_t = 960, 360, 56, 34, 34
    img = Image.new("RGB", (W, H), "#0b0d10")
    dr = ImageDraw.Draw(img)
    span = max(3600.0, max(t for pts in series.values() for t, _ in pts) - t0)
    ymax = max(10.0, max(f for pts in series.values() for _, f in pts)) * 1.15
    # axes + horizontal gridlines at 25/50/75/100%
    dr.line([(pad_l, pad_t), (pad_l, H - pad_b), (W - 8, H - pad_b)],
            fill="#3a3f45")
    for f in (0.25, 0.5, 0.75, 1.0):
        y = pad_t + (H - pad_b - pad_t) * (1 - f)
        dr.line([(pad_l, y), (W - 8, y)], fill="#20242a")
        dr.text((8, y - 6), f"{ymax * f:.0f}", fill="#8b949e")
    dr.text((8, 8), "fps", fill="#8b949e")
    for i, (label, pts) in enumerate(sorted(series.items())):
        col = PALETTE[i % len(PALETTE)]
        xy = [(pad_l + (t - t0) / span * (W - pad_l - 16),
               pad_t + (H - pad_b - pad_t) * (1 - f / ymax))
              for t, f in sorted(pts)]
        if len(xy) > 1:
            dr.line(xy, fill=col, width=2)
        for x, y in xy:
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
        dr.text((pad_l + 8 + i * 130, H - pad_b + 8), label, fill=col)
    if not DRY:
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
    return True


# ---------- page ----------

def lanes_md(lane_rs: list[dict]) -> list[str]:
    """## Nest serve lanes — accuracy + p50 per lane, latest run each
    plus run history."""
    if not lane_rs:
        return []
    by_lane: dict[str, list[dict]] = {}
    for r in lane_rs:
        by_lane.setdefault(r.get("lane") or "?", []).append(r)
    lines = ["## Nest serve lanes\n",
             "| lane | host | runtime | model | acc | p50 | p95 | runs | "
             "last |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, rs in sorted(by_lane.items()):
        r = rs[-1]
        pr = r.get("probe") or {}
        acc = (f"{r['acc']:.3f}" if isinstance(r.get("acc"), (int, float))
               else r.get("score") or "?")
        lines.append(
            f"| {name} | {r.get('host', '?')} | {r.get('runtime', '?')} | "
            f"{r.get('model', '?')} | {acc} | {pr.get('p50_ms', '?')}ms | "
            f"{pr.get('p95_ms', '?')}ms | {len(rs)} | "
            f"{(r.get('ts') or '?')[:16]} |")
    lines.append(
        "\n*Lane bench: `nest-train-loop.py lane-bench --lane <name> "
        "--model <onnx-dir>` — registry: ada-pi "
        "tests/bench/topologies.yml `lanes:`.*\n")
    return lines


def render(rows: list[dict], lane_rs: list[dict], chart_ok: bool) -> str:
    now = _now()
    if not rows:
        head = ("# bench-edge — in-browser detection benchmarks\n\n"
                "**Status: no device bench rows yet.** Rows land here the "
                "first time someone runs a bench on the eye page.\n\n"
                "## How to add a row\n\n"
                "- Open `https://tony-dell.taila0626a.ts.net/apps/eye/"
                "?src=test&bench=60` on the device you want to measure "
                "(tailnet, any browser).\n"
                "- `src=test` needs no camera; use `src=me` / `cam:<name>` "
                "to bench on a real feed.\n"
                "- After N frames the page POSTs fps, inference p50/p95 "
                "and the UA to MDDB (`ada-ha-scenario-reports`, "
                "`bench/edge-*`) — this page trends them.\n\n"
                "## Model under test\n\n"
                "- `efficientdet_lite0_int8` — MediaPipe tasks-vision, "
                "~4.4MB, WASM (vendored at `/apps/vendor/mediapipe/`).\n\n")
        return head + "\n".join(lanes_md(lane_rs)) + (
            "\n*Generated by bench-edge-cms · sources: "
            "ada-ha-scenario-reports bench/edge-* + bench/lane-* docs.*\n")
    by_dev: dict[str, list[dict]] = {}
    for r in rows:
        by_dev.setdefault(ua_label(r.get("ua", "")), []).append(r)
    latest_per_dev = {d: rs[-1] for d, rs in by_dev.items()}
    best = max(latest_per_dev.values(),
               key=lambda r: r.get("fps") or 0)

    lines = [
        "# bench-edge — in-browser detection benchmarks\n",
        f"**Status: {len(by_dev)} device(s), {len(rows)} run(s); "
        f"fastest {best.get('fps', 0):.1f} fps on "
        f"{ua_label(best.get('ua', ''))} "
        f"({best.get('model', '?')}).**\n",
        "## Latest\n",
    ]
    for r in rows[-5:][::-1]:
        lines.append(
            f"- **{(r.get('ts') or '?')[:16]}** — "
            f"{ua_label(r.get('ua', ''))}: {r.get('fps', '?')} fps, "
            f"p50 {r.get('infer_ms_p50', '?')}ms "
            f"({r.get('model', '?')}, n={r.get('n', '?')})")
    lines.append("")
    lines.append("Sections: [Per device](#per-device) · "
                 "[Per model](#per-model) · [Runs](#runs)\n")
    if chart_ok:
        lines.append(f"![fps trend](/apps/reports/{CHART_NAME})\n")

    lines.append("## Per device\n")
    lines.append("| device | runs | latest fps | p50 ms | p95 ms | "
                 "load ms | last seen |")
    lines.append("|---|---|---|---|---|---|---|")
    for dev, rs in sorted(by_dev.items(),
                          key=lambda kv: -(kv[1][-1].get("fps") or 0)):
        r = rs[-1]
        lines.append(
            f"| {dev} | {len(rs)} | {r.get('fps', '?')} | "
            f"{r.get('infer_ms_p50', '?')} | {r.get('infer_ms_p95', '?')} | "
            f"{r.get('load_ms', '?')} | {(r.get('ts') or '?')[:16]} |")
    lines.append("")

    by_model: dict[str, list[dict]] = {}
    for r in rows:
        by_model.setdefault(r.get("model") or "?", []).append(r)
    lines.append("## Per model\n")
    lines.append("| model | devices | runs | best fps |")
    lines.append("|---|---|---|---|")
    for mdl, rs in sorted(by_model.items()):
        devs = {ua_label(r.get("ua", "")) for r in rs}
        lines.append(f"| {mdl} | {len(devs)} | {len(rs)} | "
                     f"{max(r.get('fps') or 0 for r in rs)} |")
    lines.append("")

    lines.append("## Runs\n")
    lines.append("| ts | device | model | n | fps | p50 | p95 | src w×h |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows[-25:][::-1]:
        lines.append(
            f"| {(r.get('ts') or '?')[:19]} | {ua_label(r.get('ua', ''))} | "
            f"{r.get('model', '?')} | {r.get('n', '?')} | {r.get('fps', '?')} | "
            f"{r.get('infer_ms_p50', '?')} | {r.get('infer_ms_p95', '?')} | "
            f"{r.get('w', '?')}×{r.get('h', '?')} |")
    lines += lanes_md(lane_rs)
    lines.append(
        "\n---\n*Generated by bench-edge-cms from ada-ha-scenario-reports "
        "bench/edge-* + bench/lane-* docs · run: "
        "`/apps/eye/?src=test&bench=60` on any device to add an edge "
        "row.*\n")
    return "\n".join(lines)


def main() -> int:
    rows = bench_rows()
    lrs = lane_rows()
    chart = PUBLIC / "apps" / "reports" / CHART_NAME
    chart_ok = draw_chart(rows, chart)
    md = render(rows, lrs, chart_ok)

    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    old = mddb_get(SLUG) or {}
    old_meta = {k: (v if isinstance(v, list) else [str(v)])
                for k, v in (old.get("meta") or {}).items()}
    if (old_meta.get("pub_hash") or [""])[0] == h:
        print("unchanged — skip")
        return 0
    today = _now().strftime("%Y-%m-%d")
    meta = dict(old_meta)
    meta.update({
        "kind": ["page"], "attribute": ["page"], "bank": ["cms"],
        "slug": [SLUG], "subject": [SLUG],
        "title": ["bench-edge — in-browser detection benchmarks"],
        "format": ["markdown"], "lang": ["en"],
        "domain": ["bench"], "scope": ["tony"], "status": ["active"],
        "source": ["api"], "generated_by": [GENERATOR],
        "written_by": [GENERATOR],
        "sources": [f"{SRC_COLLECTION}:bench/edge-*",
                    f"{SRC_COLLECTION}:bench/lane-*"],
        "fresh_for": [FRESH_FOR], "updated": [_iso()],
        "last_verified": [today], "pub_hash": [h],
        "summary": [f"{len(rows)} edge-bench runs across "
                    f"{len({ua_label(r.get('ua', '')) for r in rows})} "
                    f"devices + {len(lrs)} lane-bench runs — "
                    "/apps/eye/?bench=N"],
    })
    meta.setdefault("valid_from", [today])
    for f in ("superseded_by", "superseded_at", "archived_at"):
        meta.pop(f, None)
    if not mddb_write(SLUG, md, meta):
        return 1
    if not DRY:
        try:
            cms_index.regen_reports_index(MDDB, written_by=GENERATOR)
        except Exception as exc:
            print(f"reports-index regen failed (non-fatal): {exc}",
                  file=sys.stderr)
    print(f"bench-edge: {len(rows)} rows, "
          f"{len({ua_label(r.get('ua', '')) for r in rows})} devices, "
          f"{len(lrs)} lane rows, chart={'yes' if chart_ok else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
