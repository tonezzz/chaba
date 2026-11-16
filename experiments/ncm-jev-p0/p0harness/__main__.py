"""CLI: python3 -m p0harness <freeze|run|replay|packet|all> [--ollama URL]
[--skip-llm] [--packet DIR]

`replay` reads the packet under --packet (default ./packet) and exits
non-zero if the gate fails — the provider-free reproducibility check.
"""
import argparse
import json
import sys
from pathlib import Path

from .freeze import OLLAMA_DEFAULT, CORPUS_PATH, freeze, load_frozen
from .harness import PACKET, build_manifest, run
from .packet import publish
from .registry import ROOT


def _load_packet(packet_dir):
    d = Path(packet_dir)
    manifest = json.loads((d / "manifest.json").read_text())
    results = json.loads((d / "results.json").read_text())
    return manifest, results


def main():
    ap = argparse.ArgumentParser(prog="p0harness")
    ap.add_argument("stage",
                    choices=["freeze", "run", "replay", "packet", "all"])
    ap.add_argument("--ollama", default=OLLAMA_DEFAULT)
    ap.add_argument("--skip-llm", action="store_true",
                    help="freeze without calling Ollama (llm rows -> "
                         "blocked escalations)")
    ap.add_argument("--only-arm", default=None,
                    help="re-record only this llm arm's cells (keeps "
                         "other frozen cells)")
    ap.add_argument("--packet", default=str(PACKET))
    a = ap.parse_args()

    if a.stage == "freeze":
        freeze(a.ollama, skip_llm=a.skip_llm, only_arm=a.only_arm)
        return 0

    if not CORPUS_PATH.exists():
        print(f"frozen corpus missing: {CORPUS_PATH} — run `freeze` first",
              file=sys.stderr)
        return 2
    frozen = load_frozen()

    if a.stage in ("run", "all"):
        manifest, results = run(frozen)
        if a.stage == "run":
            return 0
    else:
        manifest, results = _load_packet(a.packet)

    if a.stage in ("replay", "all", "packet"):
        from .replay import replay
        check = replay(frozen, manifest, results, Path(a.packet))
    else:
        check = json.loads(
            (Path(a.packet) / "replay-check.json").read_text())

    if a.stage in ("packet", "all"):
        publish(manifest, results, check)

    if a.stage == "replay":
        return 0 if check["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
