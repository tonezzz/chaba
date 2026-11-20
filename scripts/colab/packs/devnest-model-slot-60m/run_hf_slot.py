#!/usr/bin/env python3
"""Run the bounded, local-only Qwen3 HF structured-output smoke on a T4.

Model-only inference arm of the DevNest shadow evaluation (card
devnest-colab-t4-model-slot-adapter). This is NOT a fixture replay and
NOT a production-route pass: it drives a pinned, pre-staged local
snapshot with synthetic prompts and reports throughput + structured
format results only.

Hard rules baked in:
  * weights come only from a pre-staged local dir verified file-by-file
    (size + sha256) against the pre-stage pack's manifest — no download,
    no Hub call (callers also export HF_HUB_OFFLINE=1);
  * the model repo + revision must match the pin below or it refuses;
  * --max-seconds is a soft wall-clock cap so the pack finishes writing
    artifacts before the runner's timeout_s SIGALRM;
  * --gate-file writes a {verdict: pass|fail} JSON the queue-runner reads
    when another pack declares `requires:` on this one — this is what
    enforces "60-minute slot only after a passing 30-minute slot".

--self-check runs a CPU-only lint of the arm (fixtures schema, JSON
parse/verify logic, pin constants) with no torch/GPU — used by
shadow_eval.py's `t4slot --check` gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

PIN_REPO_ID = "Qwen/Qwen3-8B"
PIN_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"

SYSTEM = (
    "You are a read-only structured-output model. Use only the synthetic "
    "text in the task. Do not use tools, access files, or perform actions. "
    "Return only the requested JSON object with no extra keys."
)

SCOPE = ("synthetic structured-output smoke only; not an agent replay, "
         "not a held-out fixture verdict, not a production-route pass")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_json_response(text: str) -> dict:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("response did not contain a JSON object")
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("response JSON was not an object")
    return value


def verify_response(actual: dict, expected: dict) -> tuple[bool, str]:
    if set(actual) != set(expected):
        return False, "keys_mismatch"
    for key, value in expected.items():
        if type(actual[key]) is not type(value) or actual[key] != value:
            return False, f"value_mismatch:{key}"
    return True, "exact_match"


def load_fixtures(fixtures_path: Path) -> list:
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    if not isinstance(fixtures, list) or not fixtures:
        raise RuntimeError("fixtures file must be a non-empty list")
    for i, f in enumerate(fixtures):
        if not isinstance(f.get("id"), str) or not f["id"]:
            raise RuntimeError(f"fixtures[{i}] missing string id")
        if not isinstance(f.get("prompt"), str) or not f["prompt"]:
            raise RuntimeError(f"fixtures[{i}] ({f.get('id')}) missing prompt")
        if not isinstance(f.get("expected"), dict) or not f["expected"]:
            raise RuntimeError(
                f"fixtures[{i}] ({f.get('id')}) missing expected object")
    return fixtures


def verify_model_snapshot(model_dir: Path, manifest: dict) -> None:
    for name, record in (manifest.get("files") or {}).items():
        path = model_dir / name
        print(f"verify model file: {name}", flush=True)
        if not path.is_file() or path.stat().st_size != int(record["bytes"]):
            raise RuntimeError(
                f"pre-staged model file missing or wrong size: {name}")
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(
                f"pre-staged model file hash mismatch: {name}")


def check_manifest_pin(manifest: dict) -> None:
    if manifest.get("repo_id") != PIN_REPO_ID:
        raise RuntimeError(
            f"pre-staged model repo {manifest.get('repo_id')!r} "
            f"!= pinned {PIN_REPO_ID!r}")
    if manifest.get("revision") != PIN_REVISION:
        raise RuntimeError(
            f"pre-staged model revision {manifest.get('revision')!r} "
            f"!= pinned {PIN_REVISION!r}")


def write_gate(gate_path: Path, verdict: str, detail: dict) -> None:
    """Queue-runner gate contract: packs/<req>/preflight.json with a
    'verdict' field; verdict 'fail' blocks dependents at claim time."""
    gate_path = Path(gate_path)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "model-slot-gate",
        "verdict": verdict,
        "scope": SCOPE,
        "model": PIN_REPO_ID,
        "revision": PIN_REVISION,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }
    tmp = gate_path.with_suffix(gate_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, gate_path)


def write_outputs(out_dir: Path, record: dict, rows: list,
                  status: str, gate_path: Path | None,
                  note: str = "") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pass_count = sum(1 for r in rows if r.get("pass"))
    record.update({
        "pass_count": pass_count,
        "pass_rate": round(pass_count / len(rows), 3) if rows else 0,
        "execution_status": status,
        "rows": rows,
    })
    if note:
        record["note"] = note
    (out_dir / "metrics.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    verdict_status = "pass" if (status == "complete"
                                and pass_count == len(rows)
                                and rows) else (
                                    "partial" if rows else "fail")
    verdict = {
        "status": verdict_status,
        "scope": record["scope"],
        "pass_count": pass_count,
        "fixture_count": record.get("fixture_count", 0),
        "model": record["model"],
        "revision": record["revision"],
        "note": note,
    }
    (out_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = [
        "# DevNest Colab model-only smoke",
        "",
        f"- Scope: {record['scope']}",
        f"- Model: `{record['model']}` at `{record['revision']}`",
        f"- Device: {record.get('device', 'n/a')}; "
        f"peak allocation {record.get('peak_gpu_gb', 'n/a')} GB",
        f"- Status: **{status}** — exact structured outputs: "
        f"{pass_count}/{len(rows)}",
    ]
    if note:
        lines.append(f"- Note: {note}")
    lines += [
        "",
        "| Fixture | Pass | Wall seconds | Tokens/s | Verifier |",
        "|---|---:|---:|---:|---|",
    ]
    lines.extend(
        f"| {row['fixture']} | {row['pass']} | {row['wall_s']} | "
        f"{row['tokens_per_second']} | {row['verifier']} |"
        for row in rows)
    (out_dir / "report.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    if gate_path:
        # 'pass' only on a fully clean slot; anything else blocks the
        # 60-minute pack at the queue-runner's requires gate.
        write_gate(gate_path,
                   "pass" if verdict_status == "pass" else "fail",
                   {"status": verdict_status,
                    "pass_count": pass_count,
                    "fixture_count": record.get("fixture_count", 0)})


def run(model_dir: Path, fixtures_path: Path, manifest_path: Path,
        out_dir: Path, max_seconds: float, repeat: int,
        gate_path: Path | None) -> dict:
    import torch
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig)

    if not torch.cuda.is_available():
        raise RuntimeError("this pack requires a CUDA T4 runtime")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check_manifest_pin(manifest)
    fixtures = load_fixtures(fixtures_path)
    verify_model_snapshot(model_dir, manifest)

    load_started = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False)
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir),
        local_files_only=True,
        trust_remote_code=False,
        torch_dtype=torch.float16,
        quantization_config=quantization,
        device_map="auto",
        low_cpu_mem_usage=True,
    )
    model.eval()
    device = model.get_input_embeddings().weight.device
    if device.type != "cuda":
        raise RuntimeError(f"model was not placed on CUDA: {device}")
    model_load_s = round(time.monotonic() - load_started, 2)
    device_map = {
        str(name): str(target)
        for name, target in getattr(model, "hf_device_map", {}).items()
    }
    record = {
        "schema": 1,
        "kind": "devnest-model-only-structured-output-smoke",
        "scope": SCOPE,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": manifest["repo_id"],
        "revision": manifest["revision"],
        "license": manifest.get("license"),
        "fixtures_sha256": sha256_file(fixtures_path),
        "manifest_sha256": sha256_file(manifest_path),
        "device": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "model_load_s": model_load_s,
        "device_map": device_map,
        "max_seconds": max_seconds,
        "repeat": repeat,
        "fixture_count": len(fixtures) * repeat,
        "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE", ""),
    }
    rows = []
    deadline = time.monotonic() + max_seconds
    status = "complete"
    torch.cuda.reset_peak_memory_stats()
    for rep in range(repeat):
        for fixture in fixtures:
            if time.monotonic() > deadline:
                status = "deadline"
                print("soft deadline reached — stopping fixture loop",
                      flush=True)
                break
            row_id = (fixture["id"] if repeat == 1
                      else f"{fixture['id']}#{rep + 1}")
            print(f"run fixture: {row_id}", flush=True)
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": fixture["prompt"]},
            ]
            encoded = tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                return_tensors="pt",
                return_dict=True,
            )
            encoded = {key: value.to(device)
                       for key, value in encoded.items()}
            prompt_tokens = int(encoded["input_ids"].shape[-1])
            torch.cuda.synchronize()
            started = time.monotonic()
            with torch.inference_mode():
                output = model.generate(
                    **encoded, do_sample=False, max_new_tokens=128)
            torch.cuda.synchronize()
            elapsed = round(time.monotonic() - started, 3)
            completion = output[0][prompt_tokens:]
            response = tokenizer.decode(completion,
                                        skip_special_tokens=True)
            try:
                actual = parse_json_response(response)
                passed, verifier = verify_response(
                    actual, fixture["expected"])
            except (ValueError, json.JSONDecodeError) as exc:
                actual, passed, verifier = None, False, f"invalid_json:{exc}"
            completion_tokens = int(completion.numel())
            rows.append({
                "fixture": row_id,
                "pass": passed,
                "verifier": verifier,
                "actual": actual,
                "response": response,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "wall_s": elapsed,
                "tokens_per_second": round(completion_tokens / elapsed, 2)
                if elapsed else None,
            })
            del encoded, output, completion
            torch.cuda.empty_cache()
        if status == "deadline":
            break

    record["peak_gpu_gb"] = round(
        torch.cuda.max_memory_allocated() / 1e9, 3)
    record["wall_s"] = round(
        time.monotonic() - load_started + model_load_s, 1)
    write_outputs(out_dir, record, rows, status, gate_path)
    print(json.dumps({k: record[k] for k in
                      ("execution_status", "pass_count", "fixture_count",
                       "peak_gpu_gb", "model_load_s")}, sort_keys=True),
          flush=True)
    return record


def self_check(fixtures_path: Path) -> int:
    """CPU-only arm lint — no torch, no weights. Validates the fixture
    contract and exercises the parse/verify logic the GPU run relies on."""
    checks = []
    fixtures = load_fixtures(fixtures_path)
    checks.append(("fixtures_schema", True, f"{len(fixtures)} checks"))
    ok, how = verify_response(
        parse_json_response('{"a": 1, "b": "x"}'), {"a": 1, "b": "x"})
    checks.append(("parse_exact", ok and how == "exact_match", how))
    ok, how = verify_response(
        parse_json_response('pre {"a": 1} post'), {"a": 1})
    checks.append(("parse_embedded", ok, how))
    ok, how = verify_response(
        parse_json_response('{"a": 1, "b": 2}'), {"a": 1})
    checks.append(("keys_mismatch_detected", not ok
                   and how == "keys_mismatch", how))
    ok, how = verify_response(
        parse_json_response('{"a": "1"}'), {"a": 1})
    checks.append(("type_mismatch_detected", not ok
                   and how.startswith("value_mismatch"), how))
    try:
        parse_json_response("not json at all")
        checks.append(("invalid_json_detected", False, "no error"))
    except ValueError:
        checks.append(("invalid_json_detected", True, "raised"))
    passed = all(c[1] for c in checks)
    print(json.dumps({
        "kind": "devnest-model-slot-self-check",
        "pin": {"repo_id": PIN_REPO_ID, "revision": PIN_REVISION},
        "fixtures_sha256": sha256_file(fixtures_path),
        "checks": [{"id": c[0], "ok": c[1], "detail": c[2]}
                   for c in checks],
        "verdict": "pass" if passed else "fail",
    }, indent=1, sort_keys=True))
    return 0 if passed else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path,
                        help="pre-staged snapshot dir (required to run)")
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--manifest", type=Path,
                        help="pre-stage model-manifest.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-seconds", type=float, default=1500,
                        help="soft cap inside the pack timeout_s")
    parser.add_argument("--repeat", type=int, default=1,
                        help="fixture loop count (throughput stats)")
    parser.add_argument("--gate-file", type=Path,
                        help="write a runner-gate {verdict} JSON here")
    parser.add_argument("--self-check", action="store_true",
                        help="CPU-only arm lint; no GPU/weights needed")
    args = parser.parse_args()
    if args.self_check:
        return self_check(args.fixtures)
    for name in ("model_dir", "manifest", "out"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} required to run")
    try:
        run(args.model_dir, args.fixtures, args.manifest, args.out,
            args.max_seconds, max(1, args.repeat), args.gate_file)
    except Exception as exc:
        print(f"Colab model-slot failed: {exc}", flush=True)
        if args.gate_file:
            try:
                write_gate(args.gate_file, "fail",
                           {"error": str(exc)[:300]})
            except OSError:
                pass
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
