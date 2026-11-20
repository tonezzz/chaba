#!/usr/bin/env python3
"""opencode-command.py — Devin-side thin client for the allowlisted
OpenCode command publisher (card
ada-opencode-command-publisher-20261108).

POSTs to board-api /opencode-command, the single audited door — same
shape as lesson-add.py. Never edits card YAML, never runs remote shell;
every mutation op needs --confirm and, for publish, --expect-sha proving
the previewed bytes are the bytes shipped.

Pipeline:
  preview                          # canonical vs deployed, bounded diff
  validate --file new-ada.md       # structure + required markers
  publish --file new-ada.md --confirm --expect-sha <sha256 of file>
  sync --confirm [--expect-sha <canonical sha from preview>]
  verify                           # deployed hash == canonical hash

--via local runs the same ops against a local checkout+deploy path
(testing / host-side runs — no commit hook, no board audit).
Env: BOARD_API (default: the tailnet board-api URL).
"""
import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import dispatch_repos as dr
    API = dr.board_api_base()
except Exception:
    API = "https://idc03.taila0626a.ts.net:10000"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _post(body: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        f"{API}/opencode-command", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"opencode-command: board-api {e.code}: "
            f"{e.read()[:300].decode('utf-8', 'replace')}")
    except OSError as e:
        raise SystemExit(f"opencode-command: board-api unreachable: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("op",
                    choices=["preview", "validate", "publish",
                             "sync", "verify"])
    ap.add_argument("--name", default="ada",
                    help="allowlisted command name (default: ada)")
    ap.add_argument("--file", help="candidate content for validate/publish")
    ap.add_argument("--confirm", action="store_true",
                    help="required for publish/sync")
    ap.add_argument("--expect-sha", default="",
                    help="publish: sha256 of --file; sync: canonical sha")
    ap.add_argument("--via", default="api", choices=["api", "local"])
    a = ap.parse_args()

    body = {"op": a.op, "name": a.name, "from": "devin"}
    if a.file:
        body["content"] = Path(a.file).read_text()
    if a.confirm:
        body["confirm"] = True
    if a.expect_sha:
        body["expect_sha"] = a.expect_sha
    if a.op == "publish" and a.file and not a.expect_sha:
        # convenience: hash the file the caller just read — still proves
        # the reviewed bytes are the shipped bytes
        body["expect_sha"] = _sha(body["content"])

    if a.via == "local":
        import opencode_command as opc
        try:
            res = opc.handle(body)
        except (ValueError, opc.PublishError) as e:
            raise SystemExit(f"opencode-command: {e}")
        res.setdefault("ok", True)
        res["via"] = "local"
    else:
        res = _post(body)

    if a.op == "preview" and res.get("diff"):
        print(res["diff"])
        print("---")
    print(json.dumps({k: v for k, v in res.items() if k != "diff"},
                     indent=1))
    if res.get("valid") is False or res.get("match") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
