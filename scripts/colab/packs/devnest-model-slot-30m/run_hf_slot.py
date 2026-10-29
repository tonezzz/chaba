#!/usr/bin/env python3
"""Run the bounded, local-only Qwen3 HF structured-output smoke on a T4."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

SYSTEM = (
    "You are a read-only structured-output model. Use only the synthetic "
    "text in the task. Do not use tools, access files, or perform actions. "
    "Return only the requested JSON object with no extra keys."
)


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


def verify_model_snapshot(model_dir: Path, manifest: dict) -> None:
    for name, record in (manifest.get("files") or {}).items():
        path = model_dir / name
        print(f"verify model file: {name}", flush=True)
        if not path.is_file() or path.stat().st_size != int(record["bytes"]):
            raise RuntimeError(f"pre-staged model file missing or wrong size: {name}")
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"pre-staged model file hash mismatch: {name}")


def run(model_dir: Path, fixtures_path: Path, manifest_path: Path,
        out_dir: Path) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("this pack requires a CUDA T4 runtime")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    if manifest.get("repo_id") != "Qwen/Qwen3-8B":
        raise RuntimeError("pre-staged model repo does not match Qwen3-8B")
    if manifest.get("revision") != "b968826d9c46dd6066d109eabc6255188de91218":
        raise RuntimeError("pre-staged model revision is not the pinned revision")
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
    rows = []
    torch.cuda.reset_peak_memory_stats()
    for fixture in fixtures:
        print(f"run fixture: {fixture['id']}", flush=True)
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
        encoded = {key: value.to(device) for key, value in encoded.items()}
        prompt_tokens = int(encoded["input_ids"].shape[-1])
        torch.cuda.synchronize()
        started = time.monotonic()
        with torch.inference_mode():
            output = model.generate(
                **encoded, do_sample=False, max_new_tokens=128)
        torch.cuda.synchronize()
        elapsed = round(time.monotonic() - started, 3)
        completion = output[0][prompt_tokens:]
        response = tokenizer.decode(completion, skip_special_tokens=True)
        try:
            actual = parse_json_response(response)
            passed, verifier = verify_response(actual, fixture["expected"])
        except (ValueError, json.JSONDecodeError) as exc:
            actual, passed, verifier = None, False, f"invalid_json:{exc}"
        completion_tokens = int(completion.numel())
        rows.append({
            "fixture": fixture["id"],
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

    pass_count = sum(row["pass"] for row in rows)
    device_name = torch.cuda.get_device_name(0)
    record = {
        "schema": 1,
        "kind": "devnest-model-only-structured-output-smoke",
        "scope": "synthetic prompts only; not an agent replay or production-route pass",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": manifest["repo_id"],
        "revision": manifest["revision"],
        "license": manifest.get("license"),
        "fixtures_sha256": sha256_file(fixtures_path),
        "manifest_sha256": sha256_file(manifest_path),
        "device": device_name,
        "torch": torch.__version__,
        "model_load_s": model_load_s,
        "device_map": device_map,
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 3),
        "fixture_count": len(fixtures),
        "pass_count": pass_count,
        "pass_rate": round(pass_count / len(fixtures), 3) if fixtures else 0,
        "execution_status": "complete",
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    verdict = {
        "status": "pass" if pass_count == len(fixtures) else "partial",
        "scope": record["scope"],
        "pass_count": pass_count,
        "fixture_count": len(fixtures),
        "model": record["model"],
        "revision": record["revision"],
    }
    (out_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = [
        "# DevNest Colab model-only smoke",
        "",
        f"- Scope: {record['scope']}",
        f"- Model: `{record['model']}` at `{record['revision']}`",
        f"- Device: {device_name}; peak allocation {record['peak_gpu_gb']} GB",
        f"- Exact structured outputs: {pass_count}/{len(fixtures)}",
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
    print(json.dumps(record, sort_keys=True), flush=True)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.model_dir, args.fixtures, args.manifest, args.out)
    except Exception as exc:
        print(f"Colab model-slot failed: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
