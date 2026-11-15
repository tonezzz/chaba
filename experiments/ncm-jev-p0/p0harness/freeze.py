"""Freeze the P0 corpus — runs ONCE, before the benchmark.

Writes corpus/frozen.json: tasks (sudoku + thai + prompts), the authored
Thai training corpus, pinned model metadata captured from the local
Ollama (/api/tags digest + /api/ps processor), and the recorded LLM
outputs for every task/arm/seed cell.

Freeze is the ONLY stage allowed to call a provider (local Ollama —
already-authorized compute, no paid inference). run/replay never do.
"""
import json
import urllib.request
from pathlib import Path

from .contract import canonical_json
from .fixtures import (FREEZE_SEED, SEED_SET, THAI_CORPUS, build_tasks,
                       render_prompt)
from .registry import LLM_ARMS, ROOT, code_revision, num_predict
from .workers import ollama_generate

CORPUS_PATH = ROOT / "corpus" / "frozen.json"
OLLAMA_DEFAULT = "http://127.0.0.1:11434"


def _tags(base_url):
    r = json.load(urllib.request.urlopen(
        base_url.rstrip("/") + "/api/tags", timeout=15))
    return {m["name"]: m for m in r.get("models", [])}


def _processor_map(base_url):
    try:
        r = json.load(urllib.request.urlopen(
            base_url.rstrip("/") + "/api/ps", timeout=10))
        return {m["name"]: m.get("processor", "") for m in r.get("models", [])}
    except Exception:
        return {}


def freeze(base_url=OLLAMA_DEFAULT, skip_llm=False, only_arm=None):
    tasks = build_tasks()
    if only_arm and CORPUS_PATH.exists():
        frozen = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        if frozen["tasks"] != tasks or \
                frozen["thai_corpus"] != THAI_CORPUS:
            raise SystemExit("corpus drift vs frozen.json — full refreeze "
                             "required")
    else:
        frozen = {
            "corpus_id": "ncm-jev-p0-corpus",
            "freeze_seed": FREEZE_SEED,
            "seed_set": SEED_SET,
            "code_revision": code_revision(),
            "thai_corpus": THAI_CORPUS,
            "tasks": tasks,
            "models": {},
            "frozen_outputs": {},
        }
    arms = [a for a in LLM_ARMS if not only_arm or a["id"] == only_arm]
    if skip_llm:
        for arm in arms:
            frozen["models"][arm["id"]] = {
                "model_id": arm["model"], "digest": "unrecorded",
                "quantization": "unknown",
                "processor": "tony-omen ollama gguf (local)"}
            for t in tasks:
                for s in SEED_SET:
                    frozen["frozen_outputs"][
                        f"{t['task_id']}|{arm['id']}|{s}"] = {
                        "status": "blocked", "detail": "llm-freeze-skipped"}
    else:
        tags = _tags(base_url)
        for arm in arms:  # model-outer order: fewer reloads
            spec = tags.get(arm["model"], {})
            proc = ""
            frozen["models"][arm["id"]] = {
                "model_id": arm["model"],
                "digest": spec.get("digest", "unrecorded"),
                "quantization": spec.get("details", {})
                .get("quantization_level", "unknown"),
                "processor": "tony-omen ollama gguf (local)",
            }
            n_done = 0
            n_cells = len(tasks) * len(SEED_SET)
            for t in tasks:
                for s in SEED_SET:
                    key = f"{t['task_id']}|{arm['id']}|{s}"
                    try:
                        rec = ollama_generate(
                            base_url, arm["model"], render_prompt(t), s,
                            num_predict(arm["id"], t["kind"]))
                    except Exception as e:  # provider hiccup -> blocked
                        rec = {"status": "blocked", "detail": str(e)[:200]}
                    frozen["frozen_outputs"][key] = rec
                    n_done += 1
                    print(f"  freeze {key} -> {rec['status']} "
                          f"({n_done}/{n_cells})", flush=True)
            proc = _processor_map(base_url).get(arm["model"])
            if proc:
                frozen["models"][arm["id"]]["processor"] = \
                    f"tony-omen ollama {proc}"
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(canonical_json(frozen) + "\n", encoding="utf-8")
    n_ok = sum(1 for r in frozen["frozen_outputs"].values()
               if r.get("status") == "ok")
    print(f"froze {len(tasks)} tasks, {n_ok}/"
          f"{len(frozen['frozen_outputs'])} llm cells ok -> {CORPUS_PATH}")
    return frozen


def load_frozen():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
