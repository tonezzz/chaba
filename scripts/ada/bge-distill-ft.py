#!/usr/bin/env python3
"""bge-distill-ft.py — fine-tune BGE-M3 to mimic gemini-embedding-2.

Card bge-m3-distillation-pilot-train-local-em-d85919 (option 1 of the
train-our-own discussion; Tony authorized "proceed" = rebuild teacher
vectors + full SBERT fine-tune, 2026-11-25).

Recipe (standard SBERT distillation):
  student  = BAAI/bge-m3 backbone (CLS pooling, 1024d)
             -> trainable linear head W: 1024 -> 768
             -> L2-normalize
  teacher  = gemini-embedding-2 vectors (768d, L2-normalized target)
  loss     = MSE(pred, teacher) on the unit sphere
             (= 2 - 2*cosine, so it IS cosine-similarity regression)

The closed-form linear map from the 2026-11-08 pilot already reached
mean cosine .9493 / judged r@5 .235 / MRR .871 — this run tests whether
fine-tuning the backbone on top of a learned head beats that.

Data (rebuilt by scripts/ada/embedeval-rebuild.py on idc03):
  <work>/docs.jsonl               id, bank, key, lang, status, text
  <work>/vec-gemini.jsonl         {"id","v": b64 f32[768]} teacher docs
  <work>/queries.jsonl            48 judged-eval queries
  <work>/vec-gemini-queries.jsonl {"id","v": b64 f32[768]} teacher queries
  <work>/qrels*.json              optional judged relevance (when present,
                                  offline recall/MRR is scored exactly like
                                  embed-space-eval stage_score)

Runs anywhere with torch+transformers (con01 CPU worker is the current
target; ~10h/epoch on 8 cores — launch detached, it checkpoints).

  python3 scripts/ada/bge-distill-ft.py train \
      --work /tmp/embedeval-distill --out /tmp/bge-m3-distill \
      --epochs 1 --batch-size 8 --grad-accum 2 --lr 2e-5 --max-len 512

  python3 scripts/ada/bge-distill-ft.py eval \
      --work /tmp/embedeval-distill --ckpt /tmp/bge-m3-distill/final
"""
import argparse
import base64
import hashlib
import json
import math
import os
import random
import struct
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


def jlines(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def b64d(s):
    raw = base64.b64decode(s)
    return np.frombuffer(raw, dtype="<f4").astype(np.float32)


def b64e(v):
    return base64.b64encode(
        struct.pack(f"<{len(v)}f", *map(float, v))).decode()


def l2n(x, dim=-1, eps=1e-12):
    return x / x.norm(dim=dim, keepdim=True).clamp_min(eps)


class DistillModel(nn.Module):
    """BGE-M3 backbone (CLS) + linear projection head to teacher dim."""

    def __init__(self, model_name, teacher_dim, freeze_layers=0):
        super().__init__()
        from transformers import AutoModel
        self.backbone = AutoModel.from_pretrained(model_name)
        hidden = self.backbone.config.hidden_size
        self.head = nn.Linear(hidden, teacher_dim)
        with torch.no_grad():
            self.head.weight.normal_(0, 0.02)
            if self.head.bias is not None:
                self.head.bias.zero_()
        if freeze_layers:
            for p in self.backbone.embeddings.parameters():
                p.requires_grad = False
            layers = self.backbone.encoder.layer
            for layer in layers[:freeze_layers]:
                for p in layer.parameters():
                    p.requires_grad = False

    def forward(self, input_ids, attention_mask):
        out = self.backbone(input_ids=input_ids,
                            attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        return l2n(self.head(cls))


class DocDataset(Dataset):
    def __init__(self, texts, targets, tokenizer, max_len):
        self.texts = texts
        self.targets = targets
        self.tok = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, i):
        enc = self.tok(self.texts[i], truncation=True,
                       max_length=self.max_len, return_tensors="pt")
        return {"input_ids": enc["input_ids"].squeeze(0),
                "attention_mask": enc["attention_mask"].squeeze(0),
                "target": torch.from_numpy(self.targets[i])}


def collate(batch, pad_id):
    maxlen = max(b["input_ids"].numel() for b in batch)
    ids = torch.full((len(batch), maxlen), pad_id, dtype=torch.long)
    mask = torch.zeros((len(batch), maxlen), dtype=torch.long)
    tgt = torch.stack([b["target"] for b in batch])
    for i, b in enumerate(batch):
        n = b["input_ids"].numel()
        ids[i, :n] = b["input_ids"]
        mask[i, :n] = b["attention_mask"]
    return {"input_ids": ids, "attention_mask": mask, "target": tgt}


def load_pairs(work, max_docs=0, seed=13):
    docs = {d["id"]: d for d in jlines(Path(work) / "docs.jsonl")}
    teachers = {}
    for r in jlines(Path(work) / "vec-gemini.jsonl"):
        teachers[r["id"]] = b64d(r["v"])
    rows = []
    for did, t in teachers.items():
        d = docs.get(did)
        if not d or d.get("status") == "retracted":
            continue
        text = (d.get("text") or "").strip()
        if len(text) < 20:
            continue
        rows.append((did, text, t / (np.linalg.norm(t) + 1e-12)))
    rng = random.Random(seed)
    rng.shuffle(rows)
    if max_docs:
        rows = rows[:max_docs]
    holdout = [r for r in rows
               if int(hashlib.md5(r[0].encode()).hexdigest(), 16) % 20 == 0]
    train = [r for r in rows if r not in holdout]
    return train, holdout


@torch.no_grad()
def embed_texts(model, tok, texts, device, batch_size, max_len,
                bf16=False):
    model.eval()
    vecs = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        enc = tok(chunk, truncation=True, max_length=max_len,
                  padding=True, return_tensors="pt").to(device)
        with torch.autocast("cpu", dtype=torch.bfloat16,
                            enabled=bf16 and device == "cpu"):
            v = model(enc["input_ids"], enc["attention_mask"])
        vecs.append(v.float().cpu())
    return torch.cat(vecs).numpy()


def cmd_train(a):
    from transformers import AutoTokenizer, get_cosine_schedule_with_warmup
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(a.seed)
    train, holdout = load_pairs(a.work, a.max_docs, a.seed)
    print(f"train pairs: {len(train)}  holdout: {len(holdout)}  "
          f"device: {device}", flush=True)

    tok = AutoTokenizer.from_pretrained(a.model)
    model = DistillModel(a.model, teacher_dim=768,
                         freeze_layers=a.freeze_layers).to(device)
    opt = torch.optim.AdamW(
        [{"params": model.backbone.parameters(), "lr": a.lr},
         {"params": model.head.parameters(), "lr": a.lr_head}],
        weight_decay=0.01)
    ds = DocDataset([t for _, t, _ in train],
                    np.stack([v for _, _, v in train]), tok, a.max_len)
    dl = DataLoader(ds, batch_size=a.batch_size, shuffle=True,
                    num_workers=a.workers, collate_fn=lambda b: collate(
                        b, tok.pad_token_id or 0), drop_last=True)
    steps = math.ceil(len(dl) / a.grad_accum) * a.epochs
    sched = get_cosine_schedule_with_warmup(
        opt, int(0.03 * steps), steps)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    step = 0
    t0 = time.time()
    for ep in range(a.epochs):
        model.train()
        acc = 0.0
        nb = 0
        for bi, batch in enumerate(dl):
            batch = {k: v.to(device) for k, v in batch.items()}
            ctx = torch.autocast("cpu", dtype=torch.bfloat16,
                                 enabled=a.bf16 and device == "cpu")
            with ctx:
                pred = model(batch["input_ids"], batch["attention_mask"])
                tgt = l2n(batch["target"].to(device))
                loss = F.mse_loss(pred.float(), tgt) / a.grad_accum
            loss.backward()
            acc += loss.item() * a.grad_accum
            nb += 1
            if (bi + 1) % a.grad_accum == 0 or bi + 1 == len(dl):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if step % a.log_every == 0:
                    print(f"ep{ep} step{step}/{steps} "
                          f"mse={acc / max(nb, 1):.4f} "
                          f"({time.time() - t0:.0f}s)", flush=True)
                    acc, nb = 0.0, 0
                if a.ckpt_every and step % a.ckpt_every == 0:
                    ck = out / f"step{step}"
                    model.backbone.save_pretrained(ck / "backbone")
                    tok.save_pretrained(ck / "backbone")
                    torch.save(model.head.state_dict(), ck / "head.pt")
                    (ck / "distill_config.json").write_text(json.dumps({
                        "model": a.model, "teacher_dim": 768,
                        "max_len": a.max_len,
                        "freeze_layers": a.freeze_layers,
                        "step": step,
                    }, indent=1))
                    print(f"saved {ck}", flush=True)
        # epoch checkpoint
        ck = out / f"epoch{ep + 1}"
        model.backbone.save_pretrained(ck / "backbone")
        tok.save_pretrained(ck / "backbone")
        torch.save(model.head.state_dict(), ck / "head.pt")
        (ck / "distill_config.json").write_text(json.dumps({
            "model": a.model, "teacher_dim": 768, "max_len": a.max_len,
            "freeze_layers": a.freeze_layers, "epoch": ep + 1,
        }, indent=1))
        print(f"saved {ck}", flush=True)

    # final + holdout cosine eval
    ck = out / "final"
    model.backbone.save_pretrained(ck / "backbone")
    tok.save_pretrained(ck / "backbone")
    torch.save(model.head.state_dict(), ck / "head.pt")
    (ck / "distill_config.json").write_text(json.dumps({
        "model": a.model, "teacher_dim": 768, "max_len": a.max_len,
        "freeze_layers": a.freeze_layers, "epoch": a.epochs,
    }, indent=1))

    if holdout:
        hv = embed_texts(model, tok, [t for _, t, _ in holdout],
                         device, a.batch_size, a.max_len)
        ht = np.stack([v for _, _, v in holdout])
        cos = (hv * ht).sum(1)
        print(f"holdout teacher-cosine: mean={cos.mean():.4f} "
              f"p10={np.percentile(cos, 10):.4f}", flush=True)
        np.save(out / "holdout_cos.npy", cos)
    print(f"train: done in {(time.time() - t0) / 3600:.2f}h -> {out}",
          flush=True)


def load_student(ckpt, device):
    from transformers import AutoTokenizer
    cfg = json.loads((Path(ckpt) / "distill_config.json").read_text())
    tok = AutoTokenizer.from_pretrained(Path(ckpt) / "backbone")
    model = DistillModel(str(Path(ckpt) / "backbone"),
                         teacher_dim=cfg["teacher_dim"],
                         freeze_layers=0)
    model.head.load_state_dict(
        torch.load(Path(ckpt) / "head.pt", map_location="cpu"))
    model.to(device).eval()
    return model, tok, cfg


def cmd_eval(a):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, tok, cfg = load_student(a.ckpt, device)
    max_len = cfg.get("max_len", a.max_len)

    docs = {d["id"]: d for d in jlines(Path(a.work) / "docs.jsonl")}
    tdocs = {}
    for r in jlines(Path(a.work) / "vec-gemini.jsonl"):
        tdocs[r["id"]] = b64d(r["v"])
    ids = [i for i in tdocs
           if i in docs and docs[i].get("status") != "retracted"]
    texts = [(docs[i].get("text") or "")[:1500] for i in ids]
    sv = embed_texts(model, tok, texts, device, a.batch_size, max_len)
    tv = np.stack([tdocs[i] / (np.linalg.norm(tdocs[i]) + 1e-12)
                   for i in ids])
    cos = (sv * tv).sum(1)
    print(f"docs: n={len(ids)} teacher-cosine mean={cos.mean():.4f} "
          f"p10={np.percentile(cos, 10):.4f} "
          f"p50={np.percentile(cos, 50):.4f}", flush=True)

    # query-side agreement: rank docs by student vs teacher cosine
    queries = jlines(Path(a.work) / "queries.jsonl")
    tq = {r["id"]: b64d(r["v"]) for r in
          jlines(Path(a.work) / "vec-gemini-queries.jsonl")}
    qrows = [q for q in queries if q["qid"] in tq]
    if qrows:
        qv = embed_texts(model, tok, [q["query"] for q in qrows],
                         device, a.batch_size, max_len)
        tvq = np.stack([tq[q["qid"]] /
                        (np.linalg.norm(tq[q["qid"]]) + 1e-12)
                        for q in qrows])
        s_cos = qv @ sv.T
        t_cos = tvq @ tv.T
        for k in (1, 5, 10):
            ov = []
            for i in range(len(qrows)):
                s_top = set(np.argsort(-s_cos[i])[:k].tolist())
                t_top = set(np.argsort(-t_cos[i])[:k].tolist())
                ov.append(len(s_top & t_top) / k)
            print(f"teacher-rank overlap@{k}: "
                  f"{np.mean(ov):.3f}", flush=True)

    # judged qrels if a rebuild produced them
    for qp in sorted(Path(a.work).glob("qrels*.json")):
        rel = json.loads(qp.read_text())
        pos = {i: k for k, i in enumerate(ids)}
        rec = {k: [] for k in (1, 3, 5)}
        rr = []
        for q in qrows:
            relset = set(rel.get(q["qid"]) or [])
            if not relset:
                continue
            rel_idx = [pos[i] for i in relset if i in pos]
            if not rel_idx:
                continue
            order = np.argsort(-s_cos[qrows.index(q)])[ :50]
            got = [ids[j] for j in order]
            for k in rec:
                rec[k].append(len(set(got[:k]) & relset) / len(relset))
            first = next((n + 1 for n, x in enumerate(got)
                          if x in relset), None)
            rr.append(1.0 / first if first else 0.0)
        if rr:
            print(f"qrels {qp.name}: n={len(rr)} "
                  + " ".join(f"r@{k}={np.mean(v):.3f}" for k, v in
                             rec.items())
                  + f" mrr={np.mean(rr):.3f}", flush=True)
    print("eval: done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("train", "eval"):
        p = sub.add_parser(name)
        p.add_argument("--work", default="/tmp/embedeval")
        p.add_argument("--model", default="BAAI/bge-m3")
        p.add_argument("--batch-size", type=int, default=8)
        p.add_argument("--max-len", type=int, default=512)
        p.add_argument("--seed", type=int, default=13)
        if name == "train":
            p.add_argument("--out", required=True)
            p.add_argument("--epochs", type=int, default=1)
            p.add_argument("--grad-accum", type=int, default=2)
            p.add_argument("--lr", type=float, default=2e-5)
            p.add_argument("--lr-head", type=float, default=1e-3)
            p.add_argument("--freeze-layers", type=int, default=0)
            p.add_argument("--max-docs", type=int, default=0)
            p.add_argument("--workers", type=int, default=2)
            p.add_argument("--log-every", type=int, default=20)
            p.add_argument("--ckpt-every", type=int, default=0,
                           help="save checkpoint every N optimizer steps "
                                "(0 = epoch-end only)")
            p.add_argument("--bf16", action="store_true",
                           help="CPU bf16 autocast (only helps on "
                                "AVX512-BF16 hosts)")
        else:
            p.add_argument("--ckpt", required=True)
    a = ap.parse_args()
    {"train": cmd_train, "eval": cmd_eval}[a.cmd](a)


if __name__ == "__main__":
    main()
