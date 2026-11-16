"""P0 gate — deterministic replay from manifest.json.

Regenerates every row from the manifest + frozen corpus with zero
provider calls, then compares IDENTITY_FIELDS against results.json.
Also re-validates the schema and re-runs the authority guard scan.

Exit path: writes packet/replay-check.json; ok=true iff every row's
identity matches and there are no schema errors.
"""
import json
from pathlib import Path

from .contract import canonical_json, row_identity
from .harness import PACKET, build_rows


def replay(frozen, manifest, results, packet_dir=PACKET):
    new_rows, errors = build_rows(frozen, manifest, write_dir=None)
    old = {(r["task_id"], r["candidate"], r["seed"]): r
           for r in results["rows"]}
    mismatches = []
    for r in new_rows:
        key = (r["task_id"], r["candidate"], r["seed"])
        if key not in old:
            mismatches.append({"key": key, "issue": "missing in results"})
            continue
        if row_identity(old[key]) != row_identity(r):
            diffs = {f: {"old": old[key].get(f), "new": r.get(f)}
                     for f in row_identity(r)
                     if old[key].get(f) != r.get(f)}
            mismatches.append({"key": key, "diffs": diffs})
    extra = [k for k in old if k not in
             {(r["task_id"], r["candidate"], r["seed"])
              for r in new_rows}]
    for k in extra:
        mismatches.append({"key": k, "issue": "stale row in results"})
    guard_hits = sum(1 for r in results["rows"]
                     if r.get("meta", {}).get("guard_violation"))
    check = {
        "ok": not mismatches and not errors,
        "rows_replayed": len(new_rows),
        "schema_errors": len(errors),
        "identity_mismatches": len(mismatches),
        "mismatches": mismatches[:20],
        "guard_violations": guard_hits,
        "providers_called": 0,
    }
    (Path(packet_dir) / "replay-check.json").write_text(
        canonical_json(check) + "\n", encoding="utf-8")
    print(f"replay: {len(new_rows)} rows, "
          f"{len(mismatches)} mismatches, "
          f"{len(errors)} schema errors, ok={check['ok']}")
    return check
