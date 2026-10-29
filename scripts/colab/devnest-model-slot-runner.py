#!/usr/bin/env python3
"""Local Ollama model-only smoke for the frozen synthetic DevNest fixtures.

This measures structured-output behavior and latency only. It does not run
tools or claim to be the held-out shadow/agent replay benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).with_name("devnest-model-slot-fixtures.json")
SYSTEM = (
    "You are a read-only structured-output model. Use only the synthetic "
    "text in the task. Do not use tools, access files, or perform actions. "
    "Return only the requested JSON object with no extra keys."
)


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


def request_json(url: str, payload: dict | None = None, timeout_s: int = 20) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"local Ollama request failed: {exc}") from exc


def inventory(base_url: str) -> list[dict]:
    payload = request_json(base_url.rstrip("/") + "/api/tags")
    return payload.get("models", [])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_fixture(base_url: str, model: str, fixture: dict) -> dict:
    prompt = (
        f"{SYSTEM}\n\nTask: {fixture['prompt']}\n"
        f"Return JSON with exactly these keys: "
        f"{', '.join(fixture['expected'].keys())}."
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "keep_alive": "5m",
        "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 128},
    }
    started = time.monotonic()
    result = request_json(
        base_url.rstrip("/") + "/api/generate", payload, timeout_s=240)
    wall_s = round(time.monotonic() - started, 3)
    response = str(result.get("response") or "")
    try:
        actual = parse_json_response(response)
        passed, reason = verify_response(actual, fixture["expected"])
    except (ValueError, json.JSONDecodeError) as exc:
        actual, passed, reason = None, False, f"invalid_response:{exc}"
    eval_count = int(result.get("eval_count") or 0)
    eval_duration_ns = int(result.get("eval_duration") or 0)
    return {
        "fixture": fixture["id"],
        "pass": passed,
        "verifier": reason,
        "actual": actual,
        "response": response,
        "wall_s": wall_s,
        "prompt_tokens": int(result.get("prompt_eval_count") or 0),
        "completion_tokens": eval_count,
        "tokens_per_second": round(eval_count / (eval_duration_ns / 1e9), 2)
        if eval_duration_ns else None,
        "load_s": round(int(result.get("load_duration") or 0) / 1e9, 3),
    }


def device_facts(base_url: str, model: str) -> dict:
    facts = {
        "host": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "nvidia_smi": None,
        "unified_memory_bytes": None,
        "ollama_model_memory": None,
    }
    if shutil.which("nvidia-smi"):
        probe = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        if probe.returncode == 0:
            facts["nvidia_smi"] = probe.stdout.strip()
    if platform.system() == "Darwin" and shutil.which("sysctl"):
        probe = subprocess.run(["sysctl", "-n", "hw.memsize"],
                               capture_output=True, text=True, timeout=10)
        if probe.returncode == 0:
            try:
                facts["unified_memory_bytes"] = int(probe.stdout.strip())
            except ValueError:
                pass
    try:
        running = request_json(base_url.rstrip("/") + "/api/ps").get("models", [])
        process = next((item for item in running
                        if item.get("name") == model), None)
        if process:
            facts["ollama_model_memory"] = {
                key: process.get(key)
                for key in ("name", "size", "size_vram", "context_length")
                if key in process
            }
    except Exception:
        pass
    return facts


def maybe_save_ollama_cache(path: str, source_dir: str) -> bool:
    """Best-effort cache save for later T4 boots; never blocks the verdict."""
    archive = Path(path)
    if archive.is_file() and archive.stat().st_size:
        check = subprocess.run(
            ["tar", "-I", "zstd", "-tf", str(archive)],
            capture_output=True, text=True, timeout=120)
        if check.returncode == 0:
            return True
    model_root = Path(source_dir)
    if not model_root.is_dir() or not shutil.which("zstd"):
        return False
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_suffix(archive.suffix + ".incomplete")
    try:
        result = subprocess.run(
            ["tar", "-I", "zstd", "-cf", str(temporary), "-C",
             str(model_root), "."],
            capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        temporary.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not temporary.is_file() \
            or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        return False
    try:
        temporary.replace(archive)
        return True
    except OSError:
        temporary.unlink(missing_ok=True)
        return False


def run(model: str, base_url: str, out_dir: Path,
        cache_archive: str | None = None, cache_source: str | None = None,
        fixtures_path: Path = FIXTURES) -> dict:
    models = inventory(base_url)
    installed = {item.get("name") for item in models}
    if model not in installed:
        raise RuntimeError(f"required model {model!r} is not installed")
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    rows = [run_fixture(base_url, model, fixture) for fixture in fixtures]
    passed = sum(row["pass"] for row in rows)
    cache_saved = (maybe_save_ollama_cache(cache_archive, cache_source)
                   if cache_archive and cache_source else None)
    record = {
        "schema": 1,
        "kind": "devnest-model-only-structured-output-smoke",
        "scope": "synthetic prompts only; not an agent replay or production-route pass",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "model_digest": next((item.get("digest") for item in models
                              if item.get("name") == model), None),
        "fixtures_sha256": sha256_file(fixtures_path),
        "fixture_count": len(fixtures),
        "pass_count": passed,
        "pass_rate": round(passed / len(fixtures), 3) if fixtures else 0,
        "execution_status": "complete",
        "cache_archive_saved": cache_saved,
        "device": device_facts(base_url, model),
        "rows": rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (out_dir / "verdict.json").write_text(
        json.dumps({
            "status": "pass" if passed == len(fixtures) else "partial",
            "scope": record["scope"],
            "pass_count": passed,
            "fixture_count": len(fixtures),
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    lines = [
        "# DevNest model-only smoke",
        "",
        f"- Scope: {record['scope']}",
        f"- Model: `{model}`",
        f"- Exact structured outputs: {passed}/{len(fixtures)}",
        f"- Device: {facts_text(record['device'])}",
        f"- Ollama cache archive saved: {cache_saved}",
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


def facts_text(facts: dict) -> str:
    return f"{facts['host']} / {facts['platform']} / {facts['machine']}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cache-archive")
    parser.add_argument("--cache-source")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args()
    try:
        run(args.model, args.base_url, Path(args.out), args.cache_archive,
            args.cache_source, args.fixtures)
    except Exception as exc:
        print(f"model-slot failed: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
