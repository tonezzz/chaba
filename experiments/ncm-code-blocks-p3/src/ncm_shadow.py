#!/usr/bin/env python3
"""NCM Variant B P3 shadow — frozen, self-contained lane (stdlib only).

Replicates the scaled Variant B lane (experiments lived at
/home/tony/tony-projects/ncm-code-blocks, card OPS-1325 / ncm-variant-b-p3-shadow)
with zero external repo/runtime dependencies:

  * corpus   : pack.yml -> structure/content token records (logic copied
               verbatim from structure_content.build_records)
  * detail   : role-conditioned MLP, weights exported to JSON
               (model/rolecond-weights.json); inference in pure Python
  * compat   : deterministic verifier identical to scale_variantb.score
  * glue     : qwen2.5:7b-instruct on tony-dell via ssh (Arm A baseline)
  * choice   : JevOS /v1/systemone on idc03:8017 (Jev/nest decision plane)

Subcommands: freeze | record | score | replay | report
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # experiments/ncm-code-blocks-p3
PACKET = ROOT / "packet"
CORPUS_PACKS = PACKET / "corpus" / "packs"              # 73 frozen pack.yml dirs
FRESH_PACKS = PACKET / "corpus" / "fresh"               # 3 fresh pack.yml dirs
RECORDINGS = PACKET / "recordings.json"

SEEDS = [42, 7, 13]
N_TASKS = 30
KINDS = ("embeds", "shots", "vo", "out", "final", "candidates", "bench",
         "report")
NEEDS = ("disk_gb", "gpu_gb", "ram_gb", "egress_only_ok")
RULES = ("embeds", "vo", "assemble", "render", "bench", "score", "scout",
         "probe", "smoke", "recon", "extract", "preview", "tts", "i2v",
         "frames", "subs", "final", "music", "qc", "preflight", "shadow",
         "model-slot", "shortlist", "bridge", "delivery")
FORBIDDEN = ("allowed_paths", "tools", "credentials", "human_gate",
             "permissions", "authorize", "grant_access")
SHORTLIST_EXTRA = ("embeds", "bench", "render", "scout")

OLLAMA_MODEL = "qwen2.5:7b-instruct"
OLLAMA_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
OLLAMA_HOST = "tony-dell"
JEV_URL = "http://127.0.0.1:8017/v1/systemone"
JEV_HOST = "idc03"

GLUE_PROMPT = """Fill in the detail contract for a nest pack block.

Task: produce a pack skeleton for the {block} block
Chosen block: {block}
Artifact-kind tokens: embeds, shots, vo, out, final, candidates, bench, report
Need keys: disk_gb, gpu_gb, ram_gb, egress_only_ok

Return ONLY valid JSON with exactly these keys:
{{"needs":[...],"consumes":[...],"produces":[...],"venv":bool,"prep":bool,"run":bool,"timeout":"short"|"medium"|"long"}}"""


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


# ---------------------------------------------------------------- pack.yml --
def read_pack(path: Path) -> dict:
    """Verbatim port of structure_content.read_pack (YAML subset parser)."""
    top, section, block, block_lines = {}, None, None, []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if block is not None:
            if line.startswith((" ", "\t")):
                block_lines.append(line)
                continue
            top[block] = "\n".join(block_lines)
            block, block_lines = None, []
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if indent == 0:
            section = None
            if ":" not in s:
                continue
            k, _, v = s.partition(":")
            v = re.split(r"\s+#", v.strip(), maxsplit=1)[0].strip()
            if v in ("|", ">"):
                block, block_lines = k.strip(), []
            elif v:
                top[k.strip()] = v
            else:
                top[k.strip()] = None
                section = k.strip()
        elif section:
            if s.startswith("- "):
                if not isinstance(top.get(section), list):
                    top[section] = []
                top[section].append(s[2:].strip())
            elif ":" in s:
                k, _, v = s.partition(":")
                if not isinstance(top.get(section), dict):
                    top[section] = {}
                top[section][k.strip()] = v.strip()
    if block is not None:
        top[block] = "\n".join(block_lines)
    return top


def as_list(v):
    return v if isinstance(v, list) else ([v] if v else [])


def num(v):
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def record_from_top(top: dict, dir_name: str) -> dict:
    """Per-pack record extraction — same fields as structure_content.build_records."""
    name = str(top.get("name") or dir_name)
    role = next((r for r in RULES if r in name.lower()), "misc")
    needs = top.get("needs") or {}
    if not isinstance(needs, dict):
        needs = {}
    fetch, arts = as_list(top.get("fetch")), as_list(top.get("artifacts"))
    kinds = {k for x in fetch + arts for k in KINDS if k in x.lower()}
    t = num(top.get("timeout_s"))
    bucket = "short" if t is None or t <= 600 else \
             "medium" if t <= 1800 else "long"

    structure = {f"role:{role}"}
    structure |= {f"need:{k}" for k in needs if k.lower() in
                  [n.lower() for n in NEEDS]}
    structure |= {f"consume:{k}" for k in kinds} | \
                 {f"produce:{k}" for k in kinds}
    structure |= {"schema:venv" if top.get("venv") else "schema:novenv"}
    structure |= {"schema:prep" if top.get("prep") else "schema:noprep"}
    structure |= {"schema:run" if top.get("run") else "schema:norun"}
    structure.add(f"timeout:{bucket}")

    content = set()
    for k in NEEDS:
        v = num(needs.get(k))
        if v is None:
            continue
        if k == "gpu_gb":
            b = "0" if v == 0 else "1-8" if v <= 8 else "9+"
        elif k == "ram_gb":
            b = "0-16" if v <= 16 else "17-32" if v <= 32 else "33+"
        else:
            b = "0-10" if v <= 10 else "11-30" if v <= 30 else "31+"
        content.add(f"value:{k}={b}")
    content.add(f"timeout_exact:{int(t) if t is not None else 0}")
    content.add(f"count:fetch={min(len(fetch), 3)}")
    content.add(f"count:artifacts={min(len(arts), 3)}")
    return {"pack": name, "role": role, "dir": dir_name,
            "structure": sorted(structure), "content": sorted(content)}


def build_records(packs_dir: Path) -> list[dict]:
    out = []
    for p in sorted(packs_dir.glob("*/pack.yml")):
        out.append(record_from_top(read_pack(p), p.parent.name))
    return out


# ------------------------------------------------------------- rolecond MLP --
_WEIGHTS = None


def _weights():
    global _WEIGHTS
    if _WEIGHTS is None:
        _WEIGHTS = json.loads(
            (ROOT / "model" / "rolecond-weights.json").read_text(
                encoding="utf-8"))["state_dict"]
    return _WEIGHTS


def _linear(x, w, b):
    # w: [out][in] row-major; x: [in]
    return [sum(wi * xi for wi, xi in zip(wrow, x)) + bi
            for wrow, bi in zip(w, b)]


def lane_logits(role_idx: int, vocab_size: int = 81, nrole: int = 24):
    """Pure-python forward pass: input = [role one-hot | zeros]."""
    w = _weights()
    x = [0.0] * (nrole + vocab_size)
    x[role_idx] = 1.0
    h1 = [max(0.0, v) for v in _linear(x, w["0.weight"], w["0.bias"])]
    h2 = [max(0.0, v) for v in _linear(h1, w["2.weight"], w["2.bias"])]
    return _linear(h2, w["4.weight"], w["4.bias"])


_LANE_CACHE = {}


def lane_tokens(block: str) -> list[str]:
    """Predicted detail-token set for a block role (cached; deterministic)."""
    if block in _LANE_CACHE:
        return _LANE_CACHE[block]
    roles = json.loads((ROOT / "model" / "roles.json").read_text(
        encoding="utf-8"))
    vocab = json.loads((ROOT / "model" / "vocab.json").read_text(
        encoding="utf-8"))
    if block not in roles:
        _LANE_CACHE[block] = []
        return []
    logits = lane_logits(roles.index(block))
    toks = [vocab[i] for i, z in enumerate(logits) if z > 0]
    _LANE_CACHE[block] = toks
    return toks


# ------------------------------------------------------------------ scoring --
def f1(gold: set, pred: set) -> float:
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    tp = len(gold & pred)
    p, r = tp / len(pred), tp / len(gold)
    return round(2 * p * r / (p + r), 4) if p + r else 0.0


def f1_raw(gold: set, pred: set) -> float:
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    tp = len(gold & pred)
    p, r = tp / len(pred), tp / len(gold)
    return 2 * p * r / (p + r) if p + r else 0.0


def score(tokens, gold):
    """Deterministic compat verifier — identical to scale_variantb.score
    (pass decided on the UNROUNDED f1, fidelity reported rounded)."""
    g, p = set(gold), set(tokens)
    raw = f1_raw(g, p)
    produce = any(t.startswith("produce:") for t in p)
    need = any(t.startswith("need:") for t in p)
    guard = [k for k in FORBIDDEN if any(k in t for t in p)]
    compat = produce and need
    return {"fidelity": round(raw, 4),
            "produce": produce, "need": need, "compat": compat,
            "guard": guard,
            "pass": bool(raw >= 0.5 and compat and not guard)}


def parse_glue(text: str):
    """Verbatim port of bestofk.parse_glue."""
    t = (text or "").strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        d = json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    return {
        "L1": sorted(f"need:{x}" for x in (d.get("needs") or [])
                     if x in NEEDS),
        "L2": sorted([f"consume:{x}" for x in (d.get("consumes") or [])
                      if x in KINDS] +
                     [f"produce:{x}" for x in (d.get("produces") or [])
                      if x in KINDS]),
        "L3": sorted((["schema:venv"] if d.get("venv") else []) +
                     (["schema:prep"] if d.get("prep") else []) +
                     (["schema:run"] if d.get("run") else []) +
                     [f"timeout:{d.get('timeout') if d.get('timeout') in ('short','medium','long') else 'short'}"])}


def glue_tokens(parsed) -> list:
    if not parsed:
        return []
    return parsed["L1"] + parsed["L2"] + parsed["L3"]


# ---------------------------------------------------------------- providers --
def jev_choice(shortlist, task, timeout=70):
    """JevOS /v1/systemone via ssh idc03 — same payload as scale_variantb.jev."""
    payload = {"model": "jev-latest",
               "state": {"task": task, "shortlist": shortlist},
               "questions": {"block": {"type": "choice",
                   "instructions": "Which block fits? Pick one key.",
                   "criteria": {r: r for r in shortlist}}}}
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", JEV_HOST,
           "curl -s --max-time 45 -X POST " + JEV_URL +
           " -H 'Content-Type: application/json' --data-binary @-"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=canon(payload), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "fail", "winner": None, "error": "ssh timeout",
                "latency_ms": round((time.time() - t0) * 1000, 1)}
    lat = round((time.time() - t0) * 1000, 1)
    if r.returncode:
        return {"status": "fail", "winner": None,
                "error": f"ssh rc={r.returncode}", "latency_ms": lat}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": "fail", "winner": None, "error": "non-json",
                "latency_ms": lat}
    a = (d.get("answers") or {}).get("block") or {}
    c = a.get("choice")
    if c not in shortlist:
        return {"status": "fail", "winner": None,
                "error": f"choice {c!r} outside shortlist",
                "model": d.get("model"), "latency_ms": lat}
    return {"status": "ok", "winner": c, "model": d.get("model"),
            "confidence": a.get("confidence"), "latency_ms": lat}


def ollama_glue(block, seed, timeout=210):
    """qwen2.5:7b-instruct on tony-dell — same payload as alt_hosts_probe.ollama."""
    payload = {"model": OLLAMA_MODEL,
               "messages": [{"role": "user",
                             "content": GLUE_PROMPT.format(block=block)}],
               "stream": False, "think": False, "keep_alive": "10m",
               "format": "json",
               "options": {"temperature": 0, "seed": seed,
                           "num_predict": 160}}
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           OLLAMA_HOST,
           "curl -s --max-time 180 http://127.0.0.1:11434/api/chat "
           "-H 'Content-Type: application/json' --data-binary @-"]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=canon(payload), capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "fail", "error": "ssh timeout",
                "latency_ms": round((time.time() - t0) * 1000, 1)}
    lat = round((time.time() - t0) * 1000, 1)
    if r.returncode:
        return {"status": "fail", "error": "ssh/curl failed",
                "latency_ms": lat}
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": "fail", "error": "non-json reply",
                "latency_ms": lat}
    return {"status": "ok",
            "output": d.get("message", {}).get("content", ""),
            "latency_ms": lat, "tokens_out": d.get("eval_count", 0)}


# ------------------------------------------------------------ freeze/record --
def cmd_freeze():
    corpus = build_records(CORPUS_PACKS)
    fresh = build_records(FRESH_PACKS)
    tasks = [r["pack"] for r in corpus[::2]][:N_TASKS]
    roles = json.loads((ROOT / "model" / "roles.json").read_text(
        encoding="utf-8"))
    vocab = json.loads((ROOT / "model" / "vocab.json").read_text(
        encoding="utf-8"))
    # every corpus/fresh token must be representable; out-of-vocab tokens are
    # simply never predicted (same as training make_vec/id_of behaviour)
    all_toks = sorted({t for r in corpus + fresh
                       for t in r["structure"] + r["content"]})
    oov = [t for t in all_toks if t not in vocab]
    reps = {r["role"]: r for r in corpus}          # last-wins, as scaled run
    missing_roles = sorted({r["role"] for r in corpus + fresh}
                           - set(roles))
    out = {
        "corpus_id": "ncm-variant-b-p3-shadow-v1",
        "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "source": "chaba@79ae156fded9 scripts/colab/packs (73) + "
                  "scripts/devnest/video-packs (3 fresh)",
        "n_corpus_records": len(corpus),
        "n_fresh_records": len(fresh),
        "tasks": tasks,
        "fresh_tasks": [r["pack"] for r in fresh],
        "n_roles_corpus": len({r["role"] for r in corpus}),
        "roles_in_model": len(roles),
        "roles_missing_from_model": missing_roles,
        "vocab_size": len(vocab),
        "out_of_vocab_gold_tokens": oov,
        "seeds": SEEDS,
        "corpus_records": corpus,
        "fresh_records": fresh,
        "role_reps": {role: rep["pack"] for role, rep in reps.items()},
    }
    (PACKET / "records-corpus.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"freeze: {len(corpus)} corpus records, {len(fresh)} fresh, "
          f"{len(tasks)} tasks, roles_missing={missing_roles} "
          f"oov={len(oov)} -> {PACKET/'records-corpus.json'}")


def _load_recordings():
    if RECORDINGS.exists():
        return json.loads(RECORDINGS.read_text(encoding="utf-8"))
    return {"jev": {}, "glue": {}, "cells": []}


def _save_recordings(rec):
    RECORDINGS.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")


def cmd_record():
    frozen = json.loads((PACKET / "records-corpus.json").read_text(
        encoding="utf-8"))
    tasks = frozen["tasks"] + frozen["fresh_tasks"]
    by_pack = {r["pack"]: r for r in
               frozen["corpus_records"] + frozen["fresh_records"]}
    rec = _load_recordings()
    done = {(c["task"], c["rep"]) for c in rec["cells"]}
    t0 = time.time()
    for i, seed in enumerate(SEEDS):
        for tid in tasks:
            if (tid, i) in done:
                continue
            base = by_pack[tid]["role"]
            shortlist = list(dict.fromkeys([base] + list(SHORTLIST_EXTRA)))
            random.Random(seed + i).shuffle(shortlist)
            ch = jev_choice(shortlist, f"produce a pack skeleton for {base}")
            jkey = f"{tid}|{i}"
            rec["jev"][jkey] = {**ch, "shortlist": shortlist, "seed": seed}
            block = ch.get("winner") or base
            gkey = f"{block}|{seed}"
            if gkey not in rec["glue"]:
                rec["glue"][gkey] = ollama_glue(block, seed)
                rec["glue"][gkey]["block"] = block
                rec["glue"][gkey]["seed"] = seed
            rec["cells"].append({"task": tid, "rep": i, "seed": seed,
                                 "base_role": base, "shortlist": shortlist,
                                 "block": block,
                                 "jev_status": ch.get("status"),
                                 "glue_key": gkey})
            _save_recordings(rec)
            print(f"[{time.time()-t0:7.1f}s] rep{i} {tid}: "
                  f"block={block} jev={ch.get('status')} "
                  f"glue={rec['glue'][gkey].get('status')}", flush=True)
    print(f"record done: {len(rec['cells'])} cells, "
          f"{len(rec['glue'])} unique glue calls -> {RECORDINGS}")


def _cell_scores(frozen, rec):
    """Deterministic scoring of every recorded cell — no provider calls."""
    reps = {r["role"]: r for r in frozen["corpus_records"]}
    by_pack = {r["pack"]: r for r in
               frozen["corpus_records"] + frozen["fresh_records"]}
    fresh_set = set(frozen["fresh_tasks"])
    rows = []
    for c in rec["cells"]:
        block = c["block"]
        rep = reps.get(block)
        if rep is None:
            gold = set()
        else:
            gold = set(rep["structure"]) | set(rep["content"])
        lt = lane_tokens(block)
        lane = score(lt, gold)
        grec = rec["glue"].get(c["glue_key"], {})
        gtok = parse_glue(grec.get("output", "")) \
            if grec.get("status") == "ok" else None
        if gtok is None:
            gl = {"fidelity": 0.0, "pass": False, "guard": [],
                  "produce": False, "need": False, "compat": False}
        else:
            gl = score(glue_tokens(gtok), gold)
        glue_guard = [k for k in FORBIDDEN
                      if k in (grec.get("output") or "")]
        cell = {"task": c["task"], "rep": c["rep"], "seed": c["seed"],
                "base_role": c["base_role"], "block": block,
                "fresh": c["task"] in fresh_set,
                "lane": lane, "glue": gl,
                "lane_tokens": lt,
                "glue_tokens": glue_tokens(gtok) if gtok else [],
                "glue_status": grec.get("status"),
                "glue_guard_raw": glue_guard,
                "lane_guard_hit": bool(lane["guard"]),
                "glue_guard_hit": bool(glue_guard) or bool(gl["guard"])}
        # secondary: fresh pack scored against its OWN tokens
        if cell["fresh"]:
            own = set(by_pack[c["task"]]["structure"]) | \
                  set(by_pack[c["task"]]["content"])
            cell["lane_self_f1"] = f1(set(lt), own)
            cell["glue_self_f1"] = f1(set(cell["glue_tokens"]), own) \
                if gtok else 0.0
        rows.append(cell)
    return rows


def cmd_score():
    frozen = json.loads((PACKET / "records-corpus.json").read_text(
        encoding="utf-8"))
    rec = _load_recordings()
    rows = _cell_scores(frozen, rec)
    per_rep = {}
    for r in rows:
        d = per_rep.setdefault(r["rep"], {"n": 0, "lane": 0, "glue": 0,
                                          "guard": 0})
        d["n"] += 1
        d["lane"] += int(r["lane"]["pass"])
        d["glue"] += int(r["glue"]["pass"])
        d["guard"] += int(r["lane_guard_hit"] or r["glue_guard_hit"])
    reps_out = []
    for i in sorted(per_rep):
        d = per_rep[i]
        lr, gr = d["lane"] / d["n"], d["glue"] / d["n"]
        reps_out.append({"rep": i, "seed": SEEDS[i], "n": d["n"],
                         "lane_pass_rate": round(lr, 4),
                         "glue_pass_rate": round(gr, 4),
                         "advantage": round(lr - gr, 4),
                         "guard": d["guard"]})
    advs = sorted(r["advantage"] for r in reps_out)
    median = advs[len(advs) // 2] if advs else 0.0
    total_guard = sum(r["guard"] for r in reps_out)
    # breakdown by chosen block role
    by_block = {}
    for r in rows:
        d = by_block.setdefault(r["block"], {"n": 0, "lane": 0,
                                             "glue": 0})
        d["n"] += 1
        d["lane"] += int(r["lane"]["pass"])
        d["glue"] += int(r["glue"]["pass"])
    block_out = {b: {"n": v["n"],
                     "lane_pass_rate": round(v["lane"] / v["n"], 4),
                     "glue_pass_rate": round(v["glue"] / v["n"], 4)}
                 for b, v in sorted(by_block.items())}
    fresh_rows = [r for r in rows if r["fresh"]]
    fresh_out = {
        "n_cells": len(fresh_rows),
        "tasks": sorted({r["task"] for r in fresh_rows}),
        "lane_pass": sum(int(r["lane"]["pass"]) for r in fresh_rows),
        "glue_pass": sum(int(r["glue"]["pass"]) for r in fresh_rows),
        "lane_self_f1_mean": round(
            sum(r.get("lane_self_f1", 0.0) for r in fresh_rows)
            / max(1, len(fresh_rows)), 4),
        "glue_self_f1_mean": round(
            sum(r.get("glue_self_f1", 0.0) for r in fresh_rows)
            / max(1, len(fresh_rows)), 4),
    }
    result = {"experiment": "ncm-variant-b-p3-shadow",
              "card": "ncm-variant-b-p3-shadow",
              "parent_card": "OPS-1325",
              "corpus_id": frozen["corpus_id"],
              "n_tasks": len(frozen["tasks"]),
              "n_fresh_tasks": len(frozen["fresh_tasks"]),
              "n_cells": len(rows),
              "seeds": SEEDS,
              "providers": {"choice": f"{JEV_HOST}:{JEV_URL} (jevos-v5)",
                            "glue": f"{OLLAMA_HOST} {OLLAMA_MODEL} "
                                    f"digest {OLLAMA_DIGEST[:12]}"},
              "reps": reps_out,
              "median_advantage": round(median, 4),
              "total_guard_violations": total_guard,
              "by_block": block_out,
              "fresh": fresh_out,
              "rows": rows}
    (PACKET / "results.json").write_text(
        json.dumps(result, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"score: {len(rows)} cells, median_adv={median}, "
          f"guard={total_guard} -> {PACKET/'results.json'}")
    return result


def cmd_replay():
    """Deterministic replay: recompute scores from recordings + frozen
    artifacts only. Zero provider calls. Fails loudly on any mismatch."""
    frozen = json.loads((PACKET / "records-corpus.json").read_text(
        encoding="utf-8"))
    rec = _load_recordings()
    rows = _cell_scores(frozen, rec)
    prior = json.loads((PACKET / "results.json").read_text(
        encoding="utf-8")) if (PACKET / "results.json").exists() else None
    # canonical fingerprint of every scored cell
    fp = [{"task": r["task"], "rep": r["rep"], "block": r["block"],
           "lane_pass": r["lane"]["pass"], "lane_f1": r["lane"]["fidelity"],
           "glue_pass": r["glue"]["pass"], "glue_f1": r["glue"]["fidelity"],
           "lane_guard": r["lane_guard_hit"],
           "glue_guard": r["glue_guard_hit"]} for r in rows]
    canon_fp = canon(fp)
    import hashlib
    digest = hashlib.sha256(canon_fp.encode()).hexdigest()
    # recompute per-rep aggregates from replayed rows
    per_rep = {}
    for r in rows:
        d = per_rep.setdefault(r["rep"], {"n": 0, "lane": 0, "glue": 0,
                                          "guard": 0})
        d["n"] += 1
        d["lane"] += int(r["lane"]["pass"])
        d["glue"] += int(r["glue"]["pass"])
        d["guard"] += int(r["lane_guard_hit"] or r["glue_guard_hit"])
    advs = sorted(round(d["lane"] / d["n"] - d["glue"] / d["n"], 4)
                  for d in per_rep.values())
    median = advs[len(advs) // 2] if advs else 0.0
    out = {"replay": "ncm-variant-b-p3-shadow",
           "provider_calls": 0,
           "cells": len(rows),
           "fingerprint_sha256": digest,
           "reps": [{"rep": i, "seed": SEEDS[i],
                     "lane_pass_rate": round(per_rep[i]["lane"] /
                                             per_rep[i]["n"], 4),
                     "glue_pass_rate": round(per_rep[i]["glue"] /
                                             per_rep[i]["n"], 4),
                     "guard": per_rep[i]["guard"]}
                    for i in sorted(per_rep)],
           "median_advantage": round(median, 4),
           "total_guard_violations": sum(d["guard"]
                                         for d in per_rep.values()),
           "matches_results": None}
    if prior is not None:
        prior_fp = [{"task": r["task"], "rep": r["rep"], "block": r["block"],
                     "lane_pass": r["lane"]["pass"],
                     "lane_f1": r["lane"]["fidelity"],
                     "glue_pass": r["glue"]["pass"],
                     "glue_f1": r["glue"]["fidelity"],
                     "lane_guard": r["lane_guard_hit"],
                     "glue_guard": r["glue_guard_hit"]}
                    for r in prior["rows"]]
        out["matches_results"] = canon(prior_fp) == canon_fp
    (PACKET / "replay-proof.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"replay: cells={len(rows)} sha256={digest[:16]} "
          f"median_adv={out['median_advantage']} "
          f"matches={out['matches_results']} -> "
          f"{PACKET/'replay-proof.json'}")
    return 0 if out["matches_results"] is not False else 1


def cmd_report():
    res = json.loads((PACKET / "results.json").read_text(encoding="utf-8"))
    pre = json.loads((PACKET / "pre-registration.json").read_text(
        encoding="utf-8"))
    gate = pre["promotion_gate"]
    med = res["median_advantage"]
    guard = res["total_guard_violations"]
    promote = (med >= gate["median_advantage_min"]
               and guard <= gate["guard_violations_max"]
               and res["fresh"]["n_cells"] >=
               gate["fresh_tasks_min"] * len(SEEDS))
    verdict = "PROMOTE" if promote else "HOLD"
    lines = [
        "# NCM Variant B — P3 shadow report", "",
        f"- card: `{res['card']}` (parent OPS-1325)",
        f"- corpus: `{res['corpus_id']}` — {res['n_tasks']} corpus tasks "
        f"+ {res['n_fresh_tasks']} fresh packs x {len(SEEDS)} paired reps "
        f"= {res['n_cells']} cells/arm",
        f"- providers: choice `{res['providers']['choice']}`; "
        f"glue `{res['providers']['glue']}`",
        f"- pre-registered gate: median advantage >= "
        f"{gate['median_advantage_min']}, guard <= "
        f"{gate['guard_violations_max']}, "
        f">= {gate['fresh_tasks_min']} fresh pack(s)", "",
        "| rep | seed | lane pass | glue pass | advantage | guard |",
        "|---|---|---|---|---|---|"]
    for r in res["reps"]:
        lines.append(f"| {r['rep']} | {r['seed']} | {r['lane_pass_rate']} | "
                     f"{r['glue_pass_rate']} | +{r['advantage']} | "
                     f"{r['guard']} |")
    lines += [
        "",
        f"- **median advantage: +{med}** (gate {gate['median_advantage_min']})",
        f"- **total guard violations: {guard}**",
        f"- fresh packs: {res['fresh']['tasks']} — lane pass "
        f"{res['fresh']['lane_pass']}/{res['fresh']['n_cells']}, glue pass "
        f"{res['fresh']['glue_pass']}/{res['fresh']['n_cells']}; "
        f"self-token F1 lane {res['fresh']['lane_self_f1_mean']} vs glue "
        f"{res['fresh']['glue_self_f1_mean']}",
        "",
        "## Pass rate by chosen block role", "",
        "| block | n | lane pass | glue pass |", "|---|---|---|---|"]
    for b, v in res["by_block"].items():
        lines.append(f"| {b} | {v['n']} | {v['lane_pass_rate']} | "
                     f"{v['glue_pass_rate']} |")
    lines += [
        "",
        f"## Verdict: **{verdict}**", "",
        "Shadow only — no production lane switch, no user-facing promotion. "
        "Replay proof: `packet/replay-proof.json` (0 provider calls).",
        ""]
    (PACKET / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"report -> {PACKET/'report.md'} verdict={verdict}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"freeze": cmd_freeze, "record": cmd_record,
          "score": cmd_score, "replay": cmd_replay,
          "report": cmd_report}.get(cmd)
    if fn is None:
        sys.exit(f"usage: {sys.argv[0]} freeze|record|score|replay|report")
    sys.exit(fn() or 0)
