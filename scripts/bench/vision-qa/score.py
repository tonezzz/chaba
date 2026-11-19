#!/usr/bin/env python3
"""score.py — vision-qa bench scorer (card kk-mac-vision-lane-eval).

Runs the generated corpus (images/ + corpus.jsonl from build_corpus.py)
against a VLM and scores whether it can do the two jobs the adobe-stock
visual-QA lane needs: description matching + defect detection on stock
assets, plus UI screenshot triage.

Same harness pattern as scripts/bench/card-judgment/score.py:
corpus jsonl -> entity -> per-case verdicts -> metrics + md/json report.

Entities:
  ollama      native /api/chat with images=[b64] (kk-mac direct — default)
  openai      OpenAI-compatible /v1/chat/completions w/ image_url (LiteLLM)
  mock-oracle returns the gold answer — harness smoke test, no model

Usage:
  score.py --entity ollama --model qwen2.5vl:7b --base-url http://kk-mac:11434
  score.py --entity mock-oracle          # validates harness end-to-end
"""
import argparse, base64, json, re, subprocess, sys, time, urllib.request
from pathlib import Path

UI_LABELS = {"ok", "error_state", "layout_bug", "empty_state"}
BIN_LABELS = {"yes", "no"}
_ANSWER_NORM = {"true": "yes", "false": "no", "y": "yes", "n": "no",
                "error": "error_state", "error-state": "error_state",
                "layout": "layout_bug", "layout-bug": "layout_bug",
                "layoutbug": "layout_bug", "empty": "empty_state",
                "empty-state": "empty_state", "emptystate": "empty_state",
                "normal": "ok", "fine": "ok"}

SYSTEM = ("You are a precise visual QA judge. Look at the image and answer "
          "ONLY the JSON object requested — no prose, no markdown fences.")


def load_corpus(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()
            if l.strip()]


def _b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


# ---------------------------------------------------------------- entities
def _post(url, body, api_key="", timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ollama_entity_factory(base_url, model, temperature=0, retries=1):
    def ent(case, img_b64):
        body = {"model": model, "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": case["prompt"],
                     "images": [img_b64]}],
                "options": {"temperature": temperature, "num_predict": 200}}
        for attempt in range(retries + 1):
            try:
                d = _post(base_url.rstrip("/") + "/api/chat", body)
                return d["message"]["content"]
            except Exception as e:
                if attempt == retries:
                    return f"ERROR {e}"
                time.sleep(2)
    return ent


def openai_entity_factory(base_url, model, api_key="", temperature=0,
                          retries=1):
    def ent(case, img_b64):
        body = {"model": model, "temperature": temperature, "max_tokens": 200,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": [
                        {"type": "text", "text": case["prompt"]},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{img_b64}"}}]}]}
        for attempt in range(retries + 1):
            try:
                d = _post(base_url.rstrip("/") + "/chat/completions", body,
                          api_key)
                return d["choices"][0]["message"]["content"]
            except Exception as e:
                if attempt == retries:
                    return f"ERROR {e}"
                time.sleep(2)
    return ent


def mock_oracle_entity(case, img_b64):
    """Harness smoke test — always emits the gold answer in model shape."""
    return json.dumps({"answer": case["gold"], "reason": "mock oracle"})


def entity_from_args(a):
    import os
    if a.entity == "mock-oracle":
        return mock_oracle_entity
    key = os.environ.get(a.api_key_env, "") if a.api_key_env else ""
    if a.entity == "ollama":
        base = a.base_url or "http://127.0.0.1:11434"
        return ollama_entity_factory(base, a.model, temperature=a.temperature)
    base = a.base_url or "http://100.102.134.91:4000/v1"
    return openai_entity_factory(base, a.model, key,
                                 temperature=a.temperature)


# ------------------------------------------------------------------ parsing
def parse_answer(text, valid):
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            a = json.loads(m.group(0)).get("answer", "")
            a = _ANSWER_NORM.get(str(a).strip().lower(),
                                 str(a).strip().lower())
            if a in valid:
                return a
        except Exception:
            pass
    hits = [w for w in re.findall(r"[a-z_]+", (text or "").lower())
            if _ANSWER_NORM.get(w, w) in valid]
    return _ANSWER_NORM.get(hits[-1], hits[-1]) if hits else ""


# ------------------------------------------------------------------ metrics
def score(cases, preds, lat):
    n = len(cases)
    def acc(f):
        sub = [(c, p) for c, p in zip(cases, preds) if f(c)]
        return round(sum(p == c["gold"] for c, p in sub) / len(sub), 4) \
            if sub else None
    lanes = sorted({c["lane"] for c in cases})
    kinds = sorted({(c["lane"], c["kind"]) for c in cases})
    defect_pos = [(c, p) for c, p in zip(cases, preds)
                  if c["kind"] == "defect" and c["gold"] == "yes"]
    recall = (sum(p == "yes" for _, p in defect_pos) / len(defect_pos)
              if defect_pos else 0.0)
    defect_neg = [(c, p) for c, p in zip(cases, preds)
                  if c["kind"] == "defect" and c["gold"] == "no"]
    spec = (sum(p == "no" for _, p in defect_neg) / len(defect_neg)
            if defect_neg else 0.0)
    conf = {}
    for c, p in zip(cases, preds):
        conf.setdefault(c["gold"], {}).setdefault(p, 0)
        conf[c["gold"]][p] += 1
    return {
        "n_cases": n,
        "overall_accuracy": round(sum(p == c["gold"]
                                      for c, p in zip(cases, preds)) / n, 4),
        "per_lane": {l: acc(lambda c, l=l: c["lane"] == l) for l in lanes},
        "per_kind": {f"{l}/{k}": acc(lambda c, l=l, k=k:
                                     c["lane"] == l and c["kind"] == k)
                     for l, k in kinds},
        "defect_recall": round(recall, 4),
        "defect_specificity": round(spec, 4),
        "parse_failures": sum(1 for p in preds
                              if p.startswith("parse-fail")),
        "latency_s": {"mean": round(sum(lat) / len(lat), 1) if lat else 0,
                      "max": round(max(lat), 1) if lat else 0,
                      "total": round(sum(lat), 1)},
        "confusion": {g: v for g, v in sorted(conf.items())},
    }


THRESHOLD = {  # provisional "usable for the lane" bar — see report note
    "overall_accuracy": 0.80, "stock_lane": 0.80, "defect_recall": 0.75,
    "ui_lane": 0.70, "parse_failures": 0}


def report_md(metrics, entity_name, model, per_case):
    th = THRESHOLD
    lane = metrics["per_lane"]
    rows = [
        ("overall_accuracy", metrics["overall_accuracy"], th["overall_accuracy"]),
        ("stock_lane_accuracy", lane.get("stock"), th["stock_lane"]),
        ("ui_lane_accuracy", lane.get("ui"), th["ui_lane"]),
        ("defect_recall", metrics["defect_recall"], th["defect_recall"]),
        ("defect_specificity", metrics["defect_specificity"], None),
        ("parse_failures", metrics["parse_failures"], th["parse_failures"]),
    ]
    lines = [
        "# vision-qa bench — kk-mac VLM run", "",
        f"entity: `{entity_name}` model: `{model or '-'}` "
        f"cases: {metrics['n_cases']} "
        f"latency mean {metrics['latency_s']['mean']}s "
        f"total {metrics['latency_s']['total']}s", "",
        "| metric | score | threshold | verdict |", "|---|---|---|---|",
    ]
    for name, val, t in rows:
        if t is None or val is None:
            verdict = "-"
        elif name == "parse_failures":
            verdict = "PASS" if val <= t else "miss"
        else:
            verdict = "PASS" if val >= t else "miss"
        ttxt = "-" if t is None else (f"<= {t}" if name == "parse_failures"
                                     else f">= {t}")
        vtxt = "-" if val is None else val
        lines.append(f"| {name} | {vtxt} | {ttxt} | {verdict} |")
    lines += ["", "per-kind:", "```json",
              json.dumps(metrics["per_kind"], indent=2), "```", "",
              "## confusion (gold -> predicted counts)", "```json",
              json.dumps(metrics["confusion"], indent=2), "```", "",
              "NOTE: thresholds are the provisional 'usable lane' bar for "
              "stock visual QA — not the nest-bench T3 gate.", "",
              "## per-case", "", "| case | lane | gold | predicted | s | ok |",
              "|---|---|---|---|---|---|"]
    for cid, l, gold, pred, s in per_case:
        lines.append(f"| {cid} | {l} | {gold} | {pred} | {s:.1f} | "
                     f"{'y' if gold == pred else 'n'} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus",
                    default=str(Path(__file__).parent / "corpus.jsonl"))
    ap.add_argument("--entity", default="ollama",
                    choices=["ollama", "openai", "mock-oracle"])
    ap.add_argument("--model", default="qwen2.5vl:7b")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--api-key-env", default="")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--out-md", default="")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--temp-host", default="")
    ap.add_argument("--temp-ssh-user", default="")
    ap.add_argument("--max-temp-c", type=float, default=0.0)
    args = ap.parse_args()

    corpus_path = Path(args.corpus)
    cases = load_corpus(corpus_path)
    if args.limit:
        cases = cases[:args.limit]
    ent = entity_from_args(args)

    def temp_c():
        if not args.temp_host:
            return None
        target = (f"{args.temp_ssh_user}@" if args.temp_ssh_user else "") \
            + args.temp_host
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 target,
                 "~/.local/bin/smctemp -c 2>/dev/null || smctemp -c 2>/dev/null"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None

    def thermal_pause(case_id):
        while args.max_temp_c > 0:
            t = temp_c()
            if t is None or t <= args.max_temp_c:
                return
            print(f"[{case_id}] thermal gate: {t:.1f}C > "
                  f"{args.max_temp_c:.0f}C — pausing 30s", file=sys.stderr)
            time.sleep(30)

    preds, lat, per_case = [], [], []
    for i, c in enumerate(cases, 1):
        thermal_pause(c["case_id"])
        valid = UI_LABELS if c["lane"] == "ui" else BIN_LABELS
        t0 = time.time()
        raw = ent(c, _b64(corpus_path.parent / c["image"]))
        s = round(time.time() - t0, 1)
        p = parse_answer(raw, valid)
        if p not in valid:
            p = f"parse-fail:{(raw or '')[:60]}"
        preds.append(p)
        lat.append(s)
        per_case.append((c["case_id"], c["lane"], c["gold"], p, s))
        print(f"[{i}/{len(cases)}] {c['case_id']}: gold={c['gold']} "
              f"pred={p} {s}s", file=sys.stderr)
        if args.delay:
            time.sleep(args.delay)

    metrics = score(cases, preds, lat)
    metrics["entity"] = args.entity
    metrics["model"] = args.model or args.entity
    md = report_md(metrics, args.entity, args.model or args.entity, per_case)
    print(md)
    if args.out_md:
        Path(args.out_md).write_text(md)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(
            {"metrics": metrics, "cases": per_case}, indent=2))


if __name__ == "__main__":
    main()
