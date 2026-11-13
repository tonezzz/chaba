"""P0 arm workers.

Generative workers share the shape:
    generate(task, seed, ctx) -> {output, tokens_in, tokens_out,
                                  latency_ms, meta}

Arms:
  ar_char_ngram   small Thai AR baseline — char trigram w/ backoff trained
                  on the frozen corpus. Real AR model, CPU, deterministic.
  ncm_2level      NCM contract stand-in — two-level coarse->fine generator
                  (class-level chain, then class-conditioned char chain).
                  NOT the trained NCM: no checkpoint exists until the P1
                  GPU stage is authorized. Marked simulated in manifest.
  llm_*           pinned local Ollama models. Outputs recorded into the
                  frozen corpus at freeze time (one authorized call per
                  task/arm/seed); run/replay read the frozen record and
                  never call a provider.
"""
import json
import random
import time
import urllib.request

from .contract import sha256_text

# ---------------------------------------------------------------- utils


def _seeded(seed, task_id, salt=""):
    h = int.from_bytes(
        bytes.fromhex(sha256_text(task_id + "|" + salt))[:8], "big")
    return random.Random((seed * 1000003 + h) % (2 ** 32))


def _pick(rng, counts):
    """Deterministic categorical draw from {key: count}."""
    total = sum(counts.values())
    r = rng.random() * total
    acc = 0.0
    last = None
    for k in sorted(counts):
        acc += counts[k]
        last = k
        if r < acc:
            return k
    return last


MAX_LEN = {"sudoku": 120, "thai_continue": 90, "short_prompt": 70}


# --------------------------------------------------- ar_char_ngram arm
class CharNGram:
    """Order-3 char model with 2/1/0 backoff over the frozen corpus."""

    ORDER = 3
    NAME = "ar_char_ngram"

    def __init__(self, texts):
        self.counts = {n: {} for n in range(1, self.ORDER + 1)}
        for t in texts:
            s = "\n" + t
            for i in range(len(s)):
                for n in range(1, self.ORDER + 1):
                    if i - n + 1 < 0:
                        continue
                    ctx = s[i - n + 1:i] if n > 1 else ""
                    self.counts[n].setdefault(ctx, {})
                    ch = s[i]
                    self.counts[n][ctx][ch] = \
                        self.counts[n][ctx].get(ch, 0) + 1

    def _next(self, rng, ctx):
        for n in range(self.ORDER, 0, -1):
            key = ctx[-(n - 1):] if n > 1 else ""
            c = self.counts[n].get(key)
            if c:
                return _pick(rng, c)
        return " "

    def generate(self, task, seed, ctx):
        t0 = time.perf_counter()
        rng = _seeded(seed, task["task_id"], self.NAME)
        out = task["input"][-(self.ORDER - 1):]
        buf = []
        for _ in range(MAX_LEN[task["kind"]]):
            ch = self._next(rng, out)
            if ch == "\n" and len(buf) >= 8:
                break
            buf.append(ch)
            out = (out + ch)[-(self.ORDER - 1):]
        text = "".join(buf).strip()
        return {"output": text,
                "tokens_in": len(task["input"]),
                "tokens_out": len(text),
                "latency_ms": (time.perf_counter() - t0) * 1e3,
                "meta": {"tokenizer": "char-utf8", "order": self.ORDER}}


# ------------------------------------------------------ ncm_2level arm
_CLASSES = [
    ("digit", lambda c: c.isdigit()),
    ("sep", lambda c: c == "|"),
    ("thai", lambda c: "ก" <= c <= "๙"),
    ("latin", lambda c: c.isascii() and c.isalpha()),
    ("space", lambda c: c.isspace()),
    ("punct", lambda c: True),
]


def _cls(ch):
    for name, test in _CLASSES:
        if test(ch):
            return name
    return "punct"


class TwoLevel:
    """Coarse-to-fine stand-in shaped like NCM: level-0 emits a class per
    position (bigram over class sequences), level-1 fills each position
    with a class-conditioned char (class unigram + char bigram mix).
    level-parallel in spirit: levels modelled, not positions."""

    NAME = "ncm_2level"

    def __init__(self, texts):
        self.cls_bi = {}        # prev class -> {class: n}
        self.cls_uni = {}       # class -> {char: n}
        self.char_bi = {}       # (class, prev char) -> {char: n}
        for t in texts:
            s = "\n" + t
            prev_cls, prev_ch = _cls("\n"), "\n"
            for ch in s[1:]:
                c = _cls(ch)
                self.cls_bi.setdefault(prev_cls, {})
                self.cls_bi[prev_cls][c] = self.cls_bi[prev_cls].get(c, 0) + 1
                self.cls_uni.setdefault(c, {})
                self.cls_uni[c][ch] = self.cls_uni[c].get(ch, 0) + 1
                k = (c, prev_ch)
                self.char_bi.setdefault(k, {})
                self.char_bi[k][ch] = self.char_bi[k].get(ch, 0) + 1
                prev_cls, prev_ch = c, ch
        self.cls_uni["\n"] = {"\n": 1}  # EOL sentinel level

    def _fill(self, rng, c, prev_ch):
        uni = self.cls_uni.get(c, {" ": 1})
        bi = self.char_bi.get((c, prev_ch), {})
        mix = dict(uni)
        for k, v in bi.items():
            mix[k] = mix.get(k, 0) + 2 * v
        return _pick(rng, mix)

    def generate(self, task, seed, ctx):
        t0 = time.perf_counter()
        rng = _seeded(seed, task["task_id"], self.NAME)
        prev_cls = _cls(task["input"][-1]) if task["input"] else "space"
        prev_ch = task["input"][-1] if task["input"] else "\n"
        # level 0: class plan
        plan = []
        for _ in range(MAX_LEN[task["kind"]]):
            c = _pick(rng, self.cls_bi.get(prev_cls, {"space": 1}))
            plan.append(c)
            prev_cls = c
        # level 1: fill plan positions level-parallel
        buf = []
        for c in plan:
            ch = self._fill(rng, c, prev_ch)
            if ch == "\n" and len(buf) >= 8:
                break
            buf.append(ch)
            prev_ch = ch
        text = "".join(buf).strip()
        return {"output": text,
                "tokens_in": len(task["input"]),
                "tokens_out": len(text),
                "latency_ms": (time.perf_counter() - t0) * 1e3,
                "meta": {"tokenizer": "class+char", "levels": 2,
                         "simulated": True}}


# ------------------------------------------------------------ llm arms
def ollama_generate(base_url, model, prompt, seed, num_predict,
                    timeout=300):
    """One authorized local call at freeze time. Returns frozen record."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": seed,
                    "num_predict": num_predict},
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    lat = (time.perf_counter() - t0) * 1e3
    return {"status": "ok",
            "output": r.get("message", {}).get("content", ""),
            "latency_ms": round(lat, 1),
            "tokens_in": r.get("prompt_eval_count", 0),
            "tokens_out": r.get("eval_count", 0)}


def replay_frozen(rec):
    """Run/replay path for llm arms — no provider call."""
    if rec.get("status") != "ok":
        return {"output": "", "tokens_in": 0, "tokens_out": 0,
                "latency_ms": 0,
                "meta": {"blocked": rec.get("detail", "unavailable")}}
    return {"output": rec["output"],
            "tokens_in": rec["tokens_in"],
            "tokens_out": rec["tokens_out"],
            "latency_ms": rec["latency_ms"],
            "meta": {"replayed": True}}


# --------------------------------------------------------------- router
# JEV route-only: deterministic rules policy. A decision, not text.
ROUTE_TABLE = {
    "sudoku": {"ncm_2level": 0.90, "llm_qwen3_4b": 0.50,
               "llm_qwen3_0p6b": 0.35, "llm_llama32_1b": 0.30,
               "ar_char_ngram": 0.20},
    "thai_continue": {"ar_char_ngram": 0.85, "llm_qwen3_4b": 0.60,
                      "llm_qwen3_0p6b": 0.50, "llm_llama32_1b": 0.45,
                      "ncm_2level": 0.40},
    "short_prompt": {"llm_qwen3_4b": 0.90, "llm_qwen3_0p6b": 0.60,
                     "llm_llama32_1b": 0.55, "ar_char_ngram": 0.10,
                     "ncm_2level": 0.10},
}


def route(task, gen_arms):
    scores = dict(ROUTE_TABLE[task["kind"]])
    thai = sum(1 for c in task["input"] if "ก" <= c <= "๙")
    if thai > 10:  # feature tweak: strong Thai signal favours local AR
        scores["ar_char_ngram"] = min(1.0,
                                      scores["ar_char_ngram"] + 0.05)
    scores = {a: s for a, s in scores.items() if a in gen_arms}
    best = max(sorted(scores), key=lambda a: scores[a])
    return {"policy": "jev-rules-v1",
            "kind": task["kind"],
            "features": {"input_len": len(task["input"]),
                         "thai_chars": thai},
            "scores": {a: scores[a] for a in sorted(scores)},
            "route": best}
