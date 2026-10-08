"""Generic HF seq-cls checkpoint served as /v1/systemone (noul only).

  serve-seqcls.py --ckpt g270m-clf --port 8781
"""
import argparse, json, re, sys, time
from pathlib import Path

import torch
from fastapi import FastAPI
from transformers import AutoModelForSequenceClassification, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lane_metrics  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ckpt", required=True)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, required=True)
args = ap.parse_args()

tok = AutoTokenizer.from_pretrained(args.ckpt)
model = AutoModelForSequenceClassification.from_pretrained(args.ckpt).eval()
THR = float((getattr(model.config, "custom_params", None) or {})
            .get("noul_threshold", 0.5))
NAME = f"seqcls:{args.ckpt}"
app = FastAPI()
lane_metrics.attach(app)


def turn_from_state(state) -> str:
    if isinstance(state, dict):
        state = json.dumps(state, ensure_ascii=False)
    if isinstance(state, list):
        state = " ".join(map(str, state))
    s = str(state)
    m = re.search(r'The user turn was:\s*"([^"]+)"', s)
    if m:
        return m.group(1)
    m = re.search(r'User said:\s*"([^"]+)"', s)
    if m:
        return m.group(1)
    return s[-300:]


@app.get("/health")
def health():
    return {"ok": True, "model": NAME, "thr": THR}


@app.post("/v1/systemone")
def systemone(body: dict):
    t0 = time.time()
    questions = body.get("questions") or {}
    turn = turn_from_state(body.get("state", ""))
    enc = tok(turn, truncation=True, max_length=96, return_tensors="pt")
    with torch.no_grad():
        p = torch.softmax(model(**enc).logits, -1)[0, 1].item()
    answers = {}
    escalations = 0
    for qid, q in questions.items():
        qtype = (q or {}).get("type")
        if qtype == "noul":
            answers[qid] = {"type": "noul", "noul": p}
        else:
            answers[qid] = {"type": qtype or "unknown", "score": p}
            escalations += 1  # not a noul lane — caller escalates heavier
    lane_metrics.METRICS.observe(
        time.time() - t0, questions=len(questions),
        escalations=escalations)
    return {"model": NAME, "answers": answers,
            "usage": {"input_tokens": int(enc["input_ids"].shape[1]),
                      "output_tokens": 0,
                      "elapsed_s": round(time.time() - t0, 3)}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
