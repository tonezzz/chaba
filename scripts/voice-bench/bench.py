#!/usr/bin/env python3
"""Run the voice-fallback benchmark for one combo.

Usage:
  bench.py --combo <id> [--dry-run] [--fixtures a,b,c] [--timeout N]

Brings the combo's stack up per its combos.yml runtime (podman/local/none),
streams every fixture wav through the orchestrator endpoint, and measures
per fixture:
  - ttfa_ms        time from audio send to first audio byte back
  - total_ms       full round-trip
  - transcript     STT/orchestrator transcript (WER vs expected)
  - tool_call      structured call emitted (scored exact/partial/none)

Writes results/<combo>-<UTCts>.json (schema: voice-bench-result, v1).

--dry-run exercises the whole pipeline against the manifest without any
services: every fixture gets status=dry_run and a results file is still
written, so CI/cards can verify the schema end-to-end.
"""
import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import lib

STARTUP_TIMEOUT = 120


class Stack:
    """Bring the combo runtime up/down. Orchestrator protocol plumbing
    (audio stream in, transcript/audio/tool-calls out) is owned by each
    combo implementation; the harness only manages lifecycle + timing."""

    def __init__(self, combo):
        self.combo = combo
        self.proc = None

    def __enter__(self):
        rt = self.combo.get("runtime") or {}
        kind = rt.get("kind", "none")
        if kind == "none":
            return self
        if kind == "local":
            cmd = rt.get("cmd")
            if not cmd:
                raise lib.HarnessError(f"{self.combo['id']}: runtime.local needs cmd")
            self.proc = subprocess.Popen(
                cmd, shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif kind == "podman":
            args = ["podman", "run", "--rm", "-d"]
            for p in rt.get("ports") or []:
                args += ["-p", p]
            for k, v in (rt.get("env") or {}).items():
                args += ["-e", f"{k}={v}"]
            args.append(rt["image"])
            if rt.get("cmd"):
                args += rt["cmd"] if isinstance(rt["cmd"], list) else [rt["cmd"]]
            out = subprocess.run(args, capture_output=True, text=True)
            if out.returncode != 0:
                raise lib.HarnessError(
                    f"podman run failed for {self.combo['id']}: {out.stderr.strip()}")
            self.container = out.stdout.strip()
        self._wait_ready()
        return self

    def _wait_ready(self):
        ep = self.combo.get("endpoint", "")
        if not ep.startswith("http"):
            time.sleep(2)  # ws endpoints: combo impl owns readiness probing
            return
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            try:
                urllib.request.urlopen(ep, timeout=2)
                return
            except Exception:
                time.sleep(1)
        raise lib.HarnessError(f"{self.combo['id']}: endpoint {ep} never came up")

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
        if getattr(self, "container", None):
            subprocess.run(["podman", "stop", self.container],
                           capture_output=True)
        return False


def run_fixture(combo, fx, timeout):
    """Stream one wav through the live stack. Returns a fixture result.

    Transport: POST the wav to <endpoint>/bench with a 2 s chunk-delay to
    simulate streaming; the orchestrator is expected to reply with JSON
    {transcript, tool_call, first_audio_ms}. Combos implementing a custom
    protocol (e.g. OpenAI Realtime events) provide their own adapter —
    this fallback is the harness's lingua franca.
    """
    wav = Path(fx["wav"])
    if not wav.exists():
        return lib.fixture_result(fx, status="missing_wav",
                                  error=f"{wav.name} not found")
    ep = combo.get("endpoint", "").rstrip("/")
    if not ep:
        return lib.fixture_result(fx, status="skipped",
                                  error="combo has no endpoint")
    url = ep.replace("ws://", "http://").replace("wss://", "https://") + "/bench"
    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url, data=wav.read_bytes(),
            headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        total_ms = round((time.monotonic() - start) * 1000)
        return lib.fixture_result(
            fx,
            transcript=body.get("transcript"),
            tool_call=body.get("tool_call"),
            ttfa_ms=body.get("first_audio_ms"),
            total_ms=total_ms)
    except Exception as e:
        return lib.fixture_result(fx, status="error", error=str(e),
                                  total_ms=round((time.monotonic() - start) * 1000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="emit the full result schema without touching services")
    ap.add_argument("--fixtures", help="comma-separated fixture ids to run")
    ap.add_argument("--timeout", type=int, default=60, help="per-fixture secs")
    ap.add_argument("--out", help="override results output path")
    args = ap.parse_args()

    combo = lib.get_combo(args.combo)
    fixtures = lib.load_fixtures()
    if args.fixtures:
        keep = set(args.fixtures.split(","))
        fixtures = [f for f in fixtures if f["id"] in keep]
    if not fixtures:
        sys.exit("no fixtures selected")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"at": ts, "host": subprocess.run(["hostname"], capture_output=True,
                                            text=True).stdout.strip()}

    if args.dry_run:
        results = [lib.fixture_result(f, status="dry_run") for f in fixtures]
    else:
        results = []
        with Stack(combo):
            for fx in fixtures:
                print(f"[{fx['id']}] ...", flush=True)
                r = run_fixture(combo, fx, args.timeout)
                results.append(r)
                print(f"  status={r['status']} wer={r['wer']} "
                      f"tool={r['tool_call_match']} total_ms={r['total_ms']}")

    doc = lib.result_doc(combo, results, dry_run=args.dry_run, meta=meta)
    out = Path(args.out) if args.out else lib.results_path(args.combo, ts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {out}")
    print(json.dumps(doc["summary"], indent=2))


if __name__ == "__main__":
    try:
        main()
    except lib.HarnessError as e:
        sys.exit(f"bench: {e}")
