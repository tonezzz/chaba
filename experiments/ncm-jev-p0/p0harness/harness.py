"""Run stage — build manifest + replay every task through every arm.

Pure replay: reads corpus/frozen.json, runs the deterministic CPU
workers and replays recorded LLM outputs. Zero provider calls. Writes
packet/manifest.json, packet/results.json and packet/artifacts/.
"""
from .contract import (IDENTITY_FIELDS, canonical_json, guard_scan,
                       make_row, sha256_text, validate_row)
from .fixtures import render_prompt, training_texts
from .registry import (PARALLEL_POOL, ROOT, code_revision,
                       composite_arm_specs, decision_arm_specs,
                       gen_arm_specs)
from .verifier import check_decision, score, verdict_for
from .workers import CharNGram, TwoLevel, replay_frozen, route

PACKET = ROOT / "packet"


def build_manifest(frozen):
    return {
        "experiment": "ncm-jev-p0-replay-contract",
        "procedure": "docs/kb/ncm-jev-nest-exploration-procedure.md#p0",
        "code_revision": frozen.get("code_revision") or code_revision(),
        "corpus_id": frozen["corpus_id"],
        "corpus_sha256": sha256_text(canonical_json(frozen)),
        "freeze_seed": frozen["freeze_seed"],
        "seed_set": frozen["seed_set"],
        "arms": (gen_arm_specs(frozen.get("models", {}))
                 + decision_arm_specs() + composite_arm_specs()),
        "parallel_pool": PARALLEL_POOL,
        "gate": {
            "schema": "worker-contract-v1",
            "identity_fields": IDENTITY_FIELDS,
            "latency_exempt": "wall-clock timing is recorded but not part "
                              "of replay identity",
            "replay_requires_providers": False,
        },
        "guard": {
            "forbidden_output_keys": [
                "allowed_paths", "tools", "credentials", "human_gate",
                "permissions", "authorize", "grant_access"],
            "rule": "model/jev outputs never mint authority; Nest owns "
                    "queueing, isolation and permissioning",
        },
    }


def _artifact_ref(task_id, candidate, seed):
    return f"artifacts/{task_id}/{candidate}__s{seed}.txt"


def _emit(rows, pool, task, candidate, model_id, model_revision, prompt,
          seed, res, verdict, meta_extra, score_val=None, detail=None,
          write_dir=None):
    ref = _artifact_ref(task["task_id"], candidate, seed)
    if write_dir is not None:
        p = write_dir / ref
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(res["output"], encoding="utf-8")
    meta = dict(res.get("meta") or {})
    if score_val is not None:
        meta["score"] = round(score_val, 3)
    if detail:
        meta["detail"] = detail
    meta.update(meta_extra)
    row = make_row(task["task_id"], task["input"], candidate, model_id,
                   model_revision, prompt, seed, res["output"],
                   res["latency_ms"], res["tokens_in"], res["tokens_out"],
                   verdict, ref, meta)
    hits = guard_scan(row)
    if hits:
        row["meta"]["guard_violation"] = hits
        if row["verdict"] == "pass":
            row["verdict"] = "escalate"
    rows.append(row)
    return row


def build_rows(frozen, manifest, write_dir=None):
    """Generate every contract row. Deterministic; no provider calls.
    `write_dir=None` (replay) still computes artifact_refs identically."""
    tasks = frozen["tasks"]
    seeds = frozen["seed_set"]
    arm_map = {a["id"]: a for a in manifest["arms"]}
    texts = training_texts(tasks)
    workers = {"ar": CharNGram(texts), "ncm": TwoLevel(texts)}
    rows, pool, errors = [], {}, []

    gen_ids = [a["id"] for a in manifest["arms"]
               if a["class"] == "generative"]

    # 1-3) generative arms: AR baseline, NCM stand-in, each pinned LLM
    for arm in manifest["arms"]:
        if arm["class"] != "generative":
            continue
        for t in tasks:
            prompt = render_prompt(t)
            for s in seeds:
                if arm["worker"] == "llm":
                    rec = frozen["frozen_outputs"].get(
                        f"{t['task_id']}|{arm['id']}|{s}", {})
                    res = replay_frozen(rec)
                else:
                    res = workers[arm["worker"]].generate(t, s, None)
                if res["meta"].get("blocked"):
                    sc, detail, verdict = None, None, "escalate"
                else:
                    sc, detail = score(t, res["output"])
                    verdict = verdict_for(t, sc)
                row = _emit(rows, pool, t, arm["id"], arm["model_id"],
                            arm["model_revision"], prompt, s, res,
                            verdict, {"arm_class": "generative"}, sc,
                            detail, write_dir)
                pool[(t["task_id"], arm["id"], s)] = (row, sc)

    # 4) JEV route-only — scored as a decision, not generated text
    for t in tasks:
        dec = route(t, gen_ids)
        res = {"output": canonical_json(dec), "tokens_in": 0,
               "tokens_out": len(dec["scores"]), "latency_ms": 0.05,
               "meta": {"decision": True}}
        errs = check_decision(dec, gen_ids)
        _emit(rows, pool, t, "jev_route",
              arm_map["jev_route"]["model_id"],
              arm_map["jev_route"]["model_revision"],
              render_prompt(t), 0, res,
              "pass" if not errs else "fail",
              {"arm_class": "decision"}, None,
              {"decision_errors": errs} if errs else None, write_dir)

    # 5) JEV route + selected candidate
    for t in tasks:
        dec = route(t, gen_ids)
        for s in seeds:
            inner, _sc = pool[(t["task_id"], dec["route"], s)]
            out = canonical_json({
                "policy": dec["policy"], "route": dec["route"],
                "scores": dec["scores"], "candidate": dec["route"],
                "output": inner["output"]})
            res = {"output": out, "tokens_in": inner["tokens_in"],
                   "tokens_out": inner["tokens_out"],
                   "latency_ms": inner["latency_ms"] + 0.05, "meta": {}}
            _emit(rows, pool, t, "jev_routed",
                  arm_map["jev_routed"]["model_id"],
                  arm_map["jev_routed"]["model_revision"],
                  render_prompt(t), s, res, inner["verdict"],
                  {"arm_class": "composite",
                   "inner_ref": inner["artifact_ref"]},
                  detail=None, write_dir=write_dir)

    # 6) bounded parallel candidates + deterministic verifier/ranker
    for t in tasks:
        for s in seeds:
            cand = {a: pool[(t["task_id"], a, s)] for a in PARALLEL_POOL}
            scores = {a: (c[1] if c[1] is not None else -1.0)
                      for a, c in cand.items()}
            order = {a: i for i, a in enumerate(PARALLEL_POOL)}
            best = min(scores, key=lambda a: (-scores[a], order[a]))
            winner, wscore = cand[best][0], scores[best]
            out = canonical_json({
                "pool": PARALLEL_POOL, "scores": scores,
                "selected": best, "output": winner["output"]})
            res = {"output": out,
                   "tokens_in": sum(c[0]["tokens_in"]
                                    for c in cand.values()),
                   "tokens_out": sum(c[0]["tokens_out"]
                                     for c in cand.values()),
                   "latency_ms": sum(c[0]["latency_ms"]
                                     for c in cand.values()),
                   "meta": {}}
            verdict = "pass" if winner["verdict"] == "pass" else \
                ("escalate" if wscore < 0 else "fail")
            _emit(rows, pool, t, "parallel_verified",
                  arm_map["parallel_verified"]["model_id"],
                  arm_map["parallel_verified"]["model_revision"],
                  render_prompt(t), s, res, verdict,
                  {"arm_class": "composite",
                   "inner_ref": winner["artifact_ref"]},
                  detail={"selected": best, "scores": scores},
                  write_dir=write_dir)

    for r in rows:
        errors.extend(validate_row(r))
    return rows, errors


def summarize(rows):
    agg = {}
    for r in rows:
        a = agg.setdefault(r["candidate"], {
            "n": 0, "pass": 0, "fail": 0, "escalate": 0,
            "score_sum": 0.0, "scored": 0, "guard_violations": 0,
            "tokens_out": 0, "latency_ms_sum": 0})
        a["n"] += 1
        a[r["verdict"]] += 1
        a["tokens_out"] += r["tokens_out"]
        a["latency_ms_sum"] += r["latency_ms"]
        if isinstance(r.get("meta"), dict):
            if "score" in r["meta"]:
                a["score_sum"] += r["meta"]["score"]
                a["scored"] += 1
            if r["meta"].get("guard_violation"):
                a["guard_violations"] += 1
    for a in agg.values():
        a["mean_score"] = round(a["score_sum"] / a["scored"], 3) \
            if a["scored"] else None
        a["mean_latency_ms"] = round(a["latency_ms_sum"] / a["n"], 1)
        del a["score_sum"], a["scored"], a["latency_ms_sum"]
    return agg


def run(frozen):
    manifest = build_manifest(frozen)
    rows, errors = build_rows(frozen, manifest, write_dir=PACKET)
    PACKET.mkdir(parents=True, exist_ok=True)
    (PACKET / "manifest.json").write_text(
        canonical_json(manifest) + "\n", encoding="utf-8")
    results = {"rows": rows, "summary": summarize(rows),
               "schema_errors": errors}
    (PACKET / "results.json").write_text(
        canonical_json(results) + "\n", encoding="utf-8")
    print(f"run: {len(rows)} rows, {len(errors)} schema errors -> "
          f"{PACKET}")
    return manifest, results
