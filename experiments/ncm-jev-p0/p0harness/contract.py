"""Worker contract v1 — the common row every P0 arm emits.

Fields (per docs/kb/ncm-jev-nest-exploration-procedure.md):
  task_id, input, candidate, model_id, model_revision, prompt_hash,
  seed, output, latency_ms, tokens_in, tokens_out, verdict, artifact_ref

Plus optional `meta` for harness bookkeeping (scores, provenance, guard
flags). `meta` never carries permissions — the authority guard scans it.
"""
import hashlib
import json

CONTRACT_VERSION = "worker-contract-v1"

REQUIRED_FIELDS = [
    "task_id", "input", "candidate", "model_id", "model_revision",
    "prompt_hash", "seed", "output", "latency_ms", "tokens_in",
    "tokens_out", "verdict", "artifact_ref",
]

VERDICTS = ("pass", "fail", "escalate")

# Model outputs must never mint authority. If any of these tokens appear
# inside an emitted output the row is escalated + counted as a guard
# violation — NCM/JEV produce candidates and decisions, never permissions.
FORBIDDEN_OUTPUT_KEYS = (
    "allowed_paths", "tools", "credentials", "human_gate",
    "permissions", "authorize", "grant_access",
)

# Fields the P0 replay gate compares. latency_ms is excluded: it is
# wall-clock timing, not content. Everything content-bearing is compared.
IDENTITY_FIELDS = [
    "task_id", "input", "candidate", "model_id", "model_revision",
    "prompt_hash", "seed", "output", "tokens_in", "tokens_out",
    "verdict", "artifact_ref",
]


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj):
    return sha256_text(canonical_json(obj))


def make_row(task_id, input_text, candidate, model_id, model_revision,
             prompt, seed, output, latency_ms, tokens_in, tokens_out,
             verdict, artifact_ref, meta=None):
    row = {
        "task_id": task_id,
        "input": input_text,
        "candidate": candidate,
        "model_id": model_id,
        "model_revision": model_revision,
        "prompt_hash": sha256_text(prompt),
        "seed": seed,
        "output": output,
        "latency_ms": int(round(latency_ms)),
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "verdict": verdict,
        "artifact_ref": artifact_ref,
    }
    if meta:
        row["meta"] = meta
    return row


def validate_row(row):
    """Return list of schema violations (empty = valid)."""
    errs = []
    for f in REQUIRED_FIELDS:
        if f not in row:
            errs.append(f"missing field {f}")
    if errs:
        return errs
    if row["verdict"] not in VERDICTS:
        errs.append(f"bad verdict {row['verdict']!r}")
    if not isinstance(row["seed"], int):
        errs.append("seed must be int")
    for f in ("latency_ms", "tokens_in", "tokens_out"):
        if not isinstance(row[f], int) or row[f] < 0:
            errs.append(f"{f} must be non-negative int")
    for f in ("task_id", "input", "candidate", "model_id",
              "model_revision", "prompt_hash", "artifact_ref"):
        if not isinstance(row[f], str):
            errs.append(f"{f} must be str")
    if len(row["prompt_hash"]) != 64:
        errs.append("prompt_hash must be sha256 hex")
    return errs


def guard_scan(row):
    """Authority guard: find forbidden tokens inside output or meta."""
    hay = row.get("output", "")
    if isinstance(row.get("meta"), dict):
        hay += "\n" + canonical_json(row["meta"])
    hits = [k for k in FORBIDDEN_OUTPUT_KEYS if k in hay]
    return hits


def row_identity(row):
    return {f: row[f] for f in IDENTITY_FIELDS}
