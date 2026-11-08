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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.inbox = server.inbox
        super().__init__(request, client_address, server,
                         directory=str(server.serve_dir))

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/submit":
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
