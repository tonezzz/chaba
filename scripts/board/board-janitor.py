#!/usr/bin/env python3
"""board-janitor.py — single tick for all kanban sweeps.

OPS-1244d: merge board sweep scripts into one janitor tick.
Runs the sweeps as sub-checks in order, sharing a single /cards fetch,
per-check state file, per-check timeout, and isolates failures.

Sweeps run in this order:
  1. merge-sweep
  2. answer-sweep
  3. request-sweep
  4. lab-review-sweep
  5. backlog-audit
  6. review-digest
  7. kanban-stats
"""

import sys
import os
import time
import json
import yaml
import importlib.util
import multiprocessing
from pathlib import Path

# Adjust repo path
CHABA_REPO = Path(os.environ.get("CHABA_REPO", Path(__file__).resolve().parents[2]))
CARD_DIR = CHABA_REPO / "docs/ssot/kanban/cards"
STATE_DIR = Path.home() / ".local/state/chaba/board-janitor"

SWEEPS = [
    ("merge-sweep", "scripts/board/merge-sweep.py"),
    ("answer-sweep", "scripts/board/answer-sweep.py"),
    ("request-sweep", "scripts/board/request-sweep.py"),
    ("lab-review-sweep", "scripts/board/lab-review-sweep.py"),
    ("backlog-audit", "scripts/ops/backlog-audit.py"),
    ("review-digest", "scripts/board/review-digest.py"),
    ("kanban-stats", "scripts/board/kanban-stats.py"),
]


def load_module(name: str, rel_path: str):
    path = CHABA_REPO / rel_path
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), str(path))
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load {rel_path}")
    mod = importlib.util.module_from_spec(spec)
    # inject sys.argv so they don't crash reading the janitor's args
    old_argv = sys.argv
    sys.argv = [str(path)]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = old_argv
    return mod


def load_all_cards() -> list[dict]:
    cards = []
    for p in sorted(CARD_DIR.glob("*.yml")):
        try:
            c = yaml.safe_load(p.read_text())
            if isinstance(c, dict):
                # some sweeps expect 'id' injected if missing, like backlog-audit does
                if not c.get("id"):
                    c["id"] = p.stem
                cards.append(c)
        except Exception:
            pass
    return cards


def run_sweep(mod, cards: list[dict], result_queue: multiprocessing.Queue):
    try:
        # pass the cards dictionary
        rc = mod.main(cards=cards)
        result_queue.put(("ok", rc))
    except Exception as e:
        result_queue.put(("error", str(e)))


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cards = load_all_cards()

    overall_success = True
    summary = []

    for name, rel_path in SWEEPS:
        start_t = time.monotonic()
        state_file = STATE_DIR / f"{name}.json"

        try:
            mod = load_module(name, rel_path)
            q = multiprocessing.Queue()

            p = multiprocessing.Process(target=run_sweep, args=(mod, cards, q))
            p.start()
            p.join(timeout=180)  # 3 minutes timeout per check

            if p.is_alive():
                p.terminate()
                p.join()
                err = "timeout"
                overall_success = False
                print(f"board-janitor: {name} timed out after 180s", file=sys.stderr)
                summary.append(f"{name}=timeout")
            else:
                if not q.empty():
                    status, val = q.get()
                    if status == "error":
                        err = val
                        overall_success = False
                        print(f"board-janitor: {name} failed: {val}", file=sys.stderr)
                        summary.append(f"{name}=err")
                    else:
                        err = None
                        summary.append(f"{name}=ok")
                else:
                    err = "no result"
                    overall_success = False
                    print(f"board-janitor: {name} died without result", file=sys.stderr)
                    summary.append(f"{name}=died")

        except Exception as e:
            err = str(e)
            overall_success = False
            print(f"board-janitor: {name} failed to load: {e}", file=sys.stderr)
            summary.append(f"{name}=load_err")

        dur = time.monotonic() - start_t
        state = {
            "last_run": time.time(),
            "duration": dur,
            "error": err
        }
        if not err:
            state["last_success"] = state["last_run"]
        elif state_file.exists():
            try:
                old = json.loads(state_file.read_text())
                state["last_success"] = old.get("last_success")
            except Exception:
                pass

        state_file.write_text(json.dumps(state))

    print(f"board-janitor tick complete: {', '.join(summary)}")
    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
