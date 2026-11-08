#!/usr/bin/env python3
"""picker-server.py — serve the mask-picker UI and accept repair requests.

GET  /*            static files from --dir (the picker folder)
POST /submit      JSON body from the picker page:
                    {image, region{x,y,w,h}, comment, gemini_prompt,
                     mask_png_b64, submitted_at}
                  -> saves inbox/<ts>-<slug>.json + .mask.png
                  -> posts a board comment on --card via board-cli
                  -> returns {"ok": true, "id": "..."}

Run:  python3 picker-server.py --dir ~/adobe-work/picker --port 8777
The agent polls ~/adobe-work/inbox/ (or reads board comms) for requests.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BOARD_CLI_CANDIDATES = [
    Path.home() / "CascadeProjects/chaba/scripts/board/board-cli.py",
    Path.home() / "CascadeProjects/chaba-tony-dell/scripts/board/board-cli.py",
]
CARD = "adobe-stock-inpaint-defect-repair"
INBOX = Path.home() / "adobe-work/inbox"


def board_comment(text: str) -> str:
    cli = next((p for p in BOARD_CLI_CANDIDATES if p.exists()), None)
    if not cli:
        return "board_cli_missing"
    try:
        r = subprocess.run(
            [sys.executable, str(cli), "--ssh", "idc03", "comment", CARD,
             text[:1500], "--from", "devin"],
            capture_output=True, text=True, timeout=60)
        return "ok" if r.returncode == 0 else f"rc{r.returncode}"
    except Exception as exc:
        return f"err:{type(exc).__name__}"


CAMPAIGN = "AS-2026-11-05-REMOTE-WORK-001"
REMOTE = "gdrive:ada-nest-adobe-stock"
CAMPAIGN_STATUS_CANDIDATES = [
    Path(__file__).resolve().parent / "campaign-status.py",
    Path.home() / "CascadeProjects/chaba/scripts/adobe-stock/campaign-status.py",
]


def campaign_status() -> dict:
    tool = next((p for p in CAMPAIGN_STATUS_CANDIDATES if p.exists()), None)
    if not tool:
        return {"error": "campaign-status.py missing"}
    r = subprocess.run(
        [sys.executable, str(tool), "--campaign", CAMPAIGN],
        capture_output=True, text=True, timeout=120)
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return {"error": (r.stderr or r.stdout)[-300:]}


def ensure_candidate_image(asset: str, serve_dir: Path) -> Path | None:
    """Pull <asset> image from Drive 30-candidates into img-cache/ so the
    static handler can serve it at /img-cache/<asset>.<ext>."""
    cache = serve_dir / "img-cache"
    cache.mkdir(exist_ok=True)
    for ext in ("png", "jpg", "jpeg"):
        dst = cache / f"{asset}.{ext}"
        if dst.exists() and dst.stat().st_size > 1000:
            return dst
    for ext in ("png", "jpg", "jpeg"):
        src = (f"{REMOTE}/campaigns/{CAMPAIGN}/30-candidates/{asset}/"
               f"{asset}.{ext}")
        r = subprocess.run(["rclone", "copy", src, str(cache)],
                           capture_output=True, timeout=180)
        dst = cache / f"{asset}.{ext}"
        if dst.exists() and dst.stat().st_size > 1000:
            return dst
    return None


def qc_decision(asset: str, decision: str, note: str) -> str:
    """Record a Tony QC decision into SESSION.json + 40-qc-review.md on
    Drive. Returns 'ok' or an error string."""
    root = f"{REMOTE}/campaigns/{CAMPAIGN}"
    td = Path.home() / "adobe-work" / ".qc-tmp"
    td.mkdir(parents=True, exist_ok=True)
    sp = td / "SESSION.json"
    r = subprocess.run(["rclone", "copy", f"{root}/SESSION.json", str(td)],
                       capture_output=True, timeout=120)
    if r.returncode or not sp.exists():
        return "session_fetch_failed"
    try:
        s = json.loads(sp.read_text())
    except Exception:
        return "session_parse_failed"
    comp = s.setdefault("comparison", {})
    key = asset.replace("-", "_")
    comp[f"{key}_qc_decision"] = decision
    comp[f"{key}_qc_note"] = (note or "")[:400]
    sp.write_text(json.dumps(s, indent=1, ensure_ascii=False))
    subprocess.run(["rclone", "copyto", str(sp), f"{root}/SESSION.json"],
                   capture_output=True, timeout=120)
    qp = td / "40-qc-review.md"
    subprocess.run(["rclone", "copy", f"{root}/40-qc-review.md", str(td)],
                   capture_output=True, timeout=120)
    if qp.exists():
        with open(qp, "a") as f:
            f.write(f"\n## {asset} — QC decision via picker/ada "
                    f"({datetime.now(timezone.utc).isoformat()})\n\n"
                    f"**Decision: {decision}.** {note}\n")
        subprocess.run(["rclone", "copyto", str(qp),
                        f"{root}/40-qc-review.md"],
                       capture_output=True, timeout=120)
    return "ok"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.inbox = server.inbox
        super().__init__(request, client_address, server,
                         directory=str(server.serve_dir))

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/session":
            td = Path.home() / "adobe-work" / ".qc-tmp"
            td.mkdir(parents=True, exist_ok=True)
            sp = td / "SESSION.json"
            r = subprocess.run(
                ["rclone", "copy",
                 f"{REMOTE}/campaigns/{CAMPAIGN}/SESSION.json", str(td)],
                capture_output=True, timeout=120)
            if r.returncode or not sp.exists():
                out = json.dumps({"error": "session_fetch_failed"}).encode()
            else:
                out = sp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if path == "/api/campaign":
            out = json.dumps(campaign_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if path.startswith("/img/"):
            asset = path[5:].strip("/")
            if not asset or "/" in asset or ".." in asset:
                self.send_error(400)
                return
            p = ensure_candidate_image(asset, self.server.serve_dir)
            if not p:
                self.send_error(404, "asset not found")
                return
            # rewrite to the cached file under serve_dir
            self.path = f"/img-cache/{p.name}"
        super().do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/qc-decision":
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self.send_error(400, "bad json")
                return
            asset = str(body.get("asset", ""))[:120]
            decision = str(body.get("decision", ""))[:40]
            note = str(body.get("note", ""))[:400]
            if not asset or decision not in ("keep", "reject", "revise"):
                self.send_error(400, "asset + decision(keep|reject|revise) required")
                return
            res = qc_decision(asset, decision, note)
            out = json.dumps({"ok": res == "ok", "result": res}).encode()
            self.send_response(200 if res == "ok" else 500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        if path != "/submit":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self.send_error(400, "bad json")
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = "".join(ch if ch.isalnum() or ch in "-_" else "-"
                       for ch in str(body.get("image", "img")))[:40]
        rid = f"{ts}-{slug}"
        self.inbox.mkdir(parents=True, exist_ok=True)
        (self.inbox / f"{rid}.json").write_text(
            json.dumps(body, indent=1, ensure_ascii=False) + "\n")
        mask_b64 = body.get("mask_png_b64")
        if mask_b64:
            try:
                (self.inbox / f"{rid}.mask.png").write_bytes(
                    base64.b64decode(mask_b64.split(",", 1)[-1]))
            except Exception:
                pass
        region = body.get("region") or {}
        comment = (body.get("comment") or "").strip()
        note = (f"Picker repair request {rid}: image={body.get('image')} "
                f"region=x{region.get('x')},y{region.get('y')},"
                f"w{region.get('w')},h{region.get('h')} "
                f"comment='{comment[:200]}'")
        bstat = board_comment(note)
        out = json.dumps({"ok": True, "id": rid, "board": bstat}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--inbox", default=str(INBOX))
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.serve_dir = Path(args.dir).resolve()
    srv.inbox = Path(args.inbox)
    print(f"picker-server on :{args.port} dir={srv.serve_dir} "
          f"inbox={srv.inbox}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
