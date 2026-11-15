"""Arm registry — the pinned candidate set for the P0 replay.

Every arm pins model_id, model_revision, tokenizer, quantization and
hardware per the procedure. LLM revisions = Ollama content digests
captured at freeze time; sim-arm revisions = sha256 of the worker source.
"""
import subprocess
from pathlib import Path

from .contract import sha256_text

ROOT = Path(__file__).resolve().parent.parent

NUM_PREDICT = {"sudoku": 200, "thai_continue": 120, "short_prompt": 80}
# qwen3:4b emits reasoning prose before the answer even with think=false;
# give it a larger pinned budget or every cell truncates mid-answer.
NUM_PREDICT_ARM = {
    "llm_qwen3_4b": {"sudoku": 900, "thai_continue": 600,
                     "short_prompt": 500},
}

LLM_ARMS = [
    {"id": "llm_qwen3_0p6b", "model": "qwen3:0.6b"},
    {"id": "llm_llama32_1b", "model": "llama3.2:1b"},
    {"id": "llm_qwen3_4b", "model": "qwen3:4b"},
]


def num_predict(arm_id, kind):
    return NUM_PREDICT_ARM.get(arm_id, NUM_PREDICT)[kind]

PARALLEL_POOL = ["ar_char_ngram", "ncm_2level",
                 "llm_qwen3_0p6b", "llm_llama32_1b"]


def _src_rev():
    h = ""
    for f in ("workers.py", "fixtures.py", "verifier.py"):
        h += sha256_text((ROOT / "p0harness" / f).read_text())
    return "src-" + sha256_text(h)[:16]


def code_revision():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:
        return "unknown"


def gen_arm_specs(models):
    """Generative arm pins. `models` = frozen {arm_id: {digest, quant,
    processor}} captured by freeze from /api/tags + /api/ps."""
    src = _src_rev()
    arms = [
        {"id": "ar_char_ngram", "class": "generative", "worker": "ar",
         "model_id": "ar-charngram3-local", "model_revision": src,
         "tokenizer": "char-utf8-order3", "quantization": "none",
         "hardware": "cpu-python3-stdlib",
         "decode": {"temperature": 1.0, "sampling": "seeded-categorical"},
         "simulated": False},
        {"id": "ncm_2level", "class": "generative", "worker": "ncm",
         "model_id": "ncm-2level-standin", "model_revision": src,
         "tokenizer": "class6+char", "quantization": "none",
         "hardware": "cpu-python3-stdlib",
         "decode": {"levels": 2, "sampling": "seeded-categorical"},
         "simulated": True,
         "note": "Contract stand-in for the trained NCM generator; real "
                 "checkpoint is blocked until the P1 GPU stage has "
                 "authorized compute."},
    ]
    for spec in LLM_ARMS:
        info = models.get(spec["id"], {})
        arms.append({
            "id": spec["id"], "class": "generative", "worker": "llm",
            "model_id": spec["model"],
            "model_revision": info.get("digest", "unrecorded"),
            "tokenizer": spec["model"].split(":")[0] + "-bpe-ollama",
            "quantization": info.get("quantization", "unknown"),
            "hardware": info.get("processor",
                                 "tony-omen ollama gguf (local)"),
            "decode": {"temperature": 0, "think": False,
                       "num_predict_per_kind":
                           NUM_PREDICT_ARM.get(spec["id"], NUM_PREDICT)},
            "simulated": False,
            "note": "Real local inference recorded at freeze; run/replay "
                    "reads the frozen record — zero provider calls."})
    return arms


def decision_arm_specs():
    return [
        {"id": "jev_route", "class": "decision", "worker": "jev_route",
         "model_id": "jev-rules-v1", "model_revision": _src_rev(),
         "tokenizer": "n/a-json-decision", "quantization": "none",
         "hardware": "cpu-python3-stdlib",
         "decode": {"policy": "deterministic-rules"},
         "simulated": False},
    ]


def composite_arm_specs():
    return [
        {"id": "jev_routed", "class": "composite", "worker": "jev_routed",
         "model_id": "jev-rules-v1+pool", "model_revision": _src_rev(),
         "tokenizer": "inherits-selected", "quantization": "none",
         "hardware": "cpu+recorded", "decode": {},
         "simulated": False},
        {"id": "parallel_verified", "class": "composite",
         "worker": "parallel", "model_id": "bounded-pool+det-verifier",
         "model_revision": _src_rev(), "tokenizer": "inherits-selected",
         "quantization": "none", "hardware": "cpu+recorded",
         "decode": {"pool": PARALLEL_POOL},
         "simulated": False},
    ]
