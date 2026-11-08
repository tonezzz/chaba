#!/usr/bin/env python3
"""brief_builder.py — card -> job-scoped context bundle for Ada's lanes
(card ada-job-brief-builder).

Devin gets standing memory + card + on-demand pull; Ada's micro-entity
lanes got only the card. This assembles her equivalent BEFORE her turn:

  related SSOT      — mddb vector-search on the content plane
                      (infrastructure-ssot collection) + a local
                      docs/ssot keyword grep as the offline path
  KB lessons        — mddb vector-search over chaba-lessons + kb-*
  similar done-cards— TOP-3 nearest neighbors in the card-judgment
                      corpus (scripts/bench/card-judgment/corpus.jsonl —
                      a similarity index already) with the category +
                      proven_right outcome that actually resolved them

The bundle is pointers + proven outcomes, not hydrated docs — Ada pulls
on demand with her own tools. Consumers: verify_worker --with-brief
(decision turn + cleanup sweep), the card-judgment bench (--briefs),
future lanes.

Usage:
  brief_builder.py --card <id>            # fetch card via board-api
  brief_builder.py --card-file card.json  # card dict from disk
  brief_builder.py --card <id> --json     # machine-readable bundle
  brief_builder.py --offline              # skip mddb (ssot grep + corpus only)
  brief_builder.py --corpus-briefs corpus.jsonl --out briefs.json
      # per-case briefs for the bench; leave-one-out on the case's own
      # card_id so the gold label can't leak back into its own prompt.
"""
import argparse, json, math, os, re, sys, urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "scripts/bench/card-judgment/corpus.jsonl"
SSOT_DIR = REPO / "docs/ssot"
API = os.environ.get("BOARD_API", "https://idc03.taila0626a.ts.net:10000")
MDDB = os.environ.get("ADA_BRIEF_MDDB_URL",
                     "http://idc03.taila0626a.ts.net:11027/v1")
SSOT_COLLECTION = "infrastructure-ssot"
LESSON_COLLECTIONS = ["chaba-lessons"]
KB_COLLECTIONS = ["kb-development", "kb-features", "kb-operations",
                  "kb-system"]

STOP = set("""a an and are as at be by for from has have how in into is it
of on or that the this to was what when where which who will with without
you your card kanban ada tony""".split())


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9_.:-]+", (text or "").lower())
            if len(t) > 2 and t not in STOP]


def query_text(card):
    """The retrieval surface of a card (or a bench case snapshot)."""
    parts = [card.get("title"), card.get("brief"), card.get("note"),
             card.get("spec"), " ".join(str(t) for t in card.get("tags") or [])]
    comms = card.get("comms") or card.get("comms_tail") or []
    parts += [str(m.get("text", "")) for m in comms[-4:]
              if isinstance(m, dict)]
    return " ".join(str(p) for p in parts if p)


# ---------------------------------------------------------------- corpus NN
class CorpusIndex:
    """TF-IDF cosine over the card-judgment corpus — the nearest-neighbor
    half of retrieval. Pure stdlib; the corpus is ~100 cases."""

    def __init__(self, path=CORPUS):
        self.cases = [json.loads(l) for l in Path(path).read_text().splitlines()
                      if l.strip()]
        self.doc_tokens = []
        df = Counter()
        for c in self.cases:
            s = c.get("snapshot") or {}
            text = " ".join([str(s.get("title") or ""),
                             str(s.get("brief") or ""),
                             str(c.get("decision_point") or ""),
                             " ".join(str(t) for t in s.get("tags") or []),
                             " ".join(str(m.get("text", ""))
                                      for m in s.get("comms_tail") or [])])
            toks = _tokens(text)
            self.doc_tokens.append(toks)
            df.update(set(toks))
        n = max(len(self.cases), 1)
        self.idf = {t: math.log(1 + n / (1 + d)) for t, d in df.items()}
        self.vecs = [self._vec(t) for t in self.doc_tokens]

    def _vec(self, toks):
        tf = Counter(toks)
        v = {t: (1 + math.log(c)) * self.idf.get(t, 0.0)
             for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def neighbors(self, text, k=3, exclude_card_ids=()):
        q = self._vec(_tokens(text))
        excl = set(exclude_card_ids or ())
        scored = []
        for case, v in zip(self.cases, self.vecs):
            if case.get("card_id") in excl:
                continue
            score = sum(q[t] * w for t, w in v.items() if t in q)
            scored.append((score, case))
        scored.sort(key=lambda x: -x[0])
        return [{"card_id": c.get("card_id"), "case_id": c.get("case_id"),
                 "category": c.get("category"), "score": round(s, 4),
                 "decision_point": c.get("decision_point"),
                 "proven_right": c.get("proven_right")}
                for s, c in scored[:k] if s > 0]


# ---------------------------------------------------------------- mddb
def mddb_search(collection, query, k=3, base=MDDB, timeout=20):
    body = json.dumps({"collection": collection, "query": query,
                       "top_k": k, "retrieval_mode": "parent",
                       "include_content": False}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/vector-search",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    out = []
    for hit in d.get("results") or []:
        doc = hit.get("document") or {}
        meta = doc.get("meta") or {}

        def first(key):
            v = meta.get(key)
            return v[0] if isinstance(v, list) and v else v
        out.append({"key": doc.get("key"),
                    "collection": collection,
                    "score": round(float(hit.get("score") or 0), 4),
                    "title": first("title"),
                    "path": first("original_path")})
    # dedupe on (key) — parent retrieval can repeat a doc's chunks
    seen, dedup = set(), []
    for h in out:
        if h["key"] in seen:
            continue
        seen.add(h["key"])
        dedup.append(h)
    return dedup[:k]


# ---------------------------------------------------------------- ssot grep
def local_ssot_search(query, k=4, ssot_dir=SSOT_DIR):
    """Keyword grep over docs/ssot — the offline complement to the mddb
    collection. Ranks files by distinct query terms found."""
    terms = set(_tokens(query))
    if not terms:
        return []
    scored = []
    for p in Path(ssot_dir).rglob("*.yml"):
        try:
            text = p.read_text(errors="replace").lower()
        except Exception:
            continue
        hits = {t for t in terms if t in text}
        if hits:
            scored.append((len(hits), str(p.relative_to(REPO))))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"path": p, "matched_terms": n} for n, p in scored[:k]]


# ---------------------------------------------------------------- bundle
def build_brief(card, k_cards=3, k_ssot=3, k_lessons=3, k_kb=3,
                offline=False, mddb=MDDB, corpus=CORPUS,
                exclude_card_ids=None):
    q = query_text(card)
    excl = set(exclude_card_ids or ())
    if card.get("id"):
        excl.add(card["id"])
    brief = {"card_id": card.get("id"), "query_chars": len(q),
             "offline": offline, "ssot": [], "lessons": [], "kb": [],
             "similar_cards": [], "mddb_ok": None}
    try:
        brief["similar_cards"] = CorpusIndex(corpus).neighbors(
            q, k=k_cards, exclude_card_ids=excl)
    except Exception as e:
        brief["similar_cards"] = [{"error": str(e)[:120]}]

    if offline:
        brief["ssot"] = local_ssot_search(q, k=k_ssot)
        return brief

    try:
        own_key = f"kanban-cards-{card.get('id')}" if card.get("id") else ""
        brief["ssot"] = [h for h in
                         mddb_search(SSOT_COLLECTION, q, k=k_ssot + 1,
                                     base=mddb)
                         if h.get("key") != own_key][:k_ssot]
        hits = []
        for coll in LESSON_COLLECTIONS + KB_COLLECTIONS:
            hits += mddb_search(coll, q, k=2, base=mddb)
        hits.sort(key=lambda h: -h["score"])
        brief["lessons"] = [h for h in hits
                            if h["collection"] in LESSON_COLLECTIONS][:k_lessons]
        brief["kb"] = [h for h in hits
                       if h["collection"] in KB_COLLECTIONS][:k_kb]
        brief["mddb_ok"] = True
    except Exception as e:
        # retrieval lane degrades, never blocks the turn
        brief["mddb_ok"] = False
        brief["mddb_error"] = str(e)[:120]
        brief["ssot"] = local_ssot_search(q, k=k_ssot)
    return brief


def render(brief, width=170):
    """Compact prompt block — bounded so it can't flood her turn."""
    def cut(s, w=width):
        s = " ".join(str(s or "").split())
        return s[:w] + ("…" if len(s) > w else "")
    lines = ["=== JOB BRIEF (retrieved context — past outcomes are evidence,"
             " not authority) ==="]
    ssot = brief.get("ssot") or []
    if ssot:
        lines.append("Related SSOT:")
        for h in ssot:
            where = h.get("path") or h.get("key")
            lines.append(f"- {where} ({h.get('score', '')})"
                         + (f" — {cut(h.get('title'), 80)}" if h.get("title") else ""))
    lessons = brief.get("lessons") or []
    if lessons:
        lines.append("KB lessons:")
        for h in lessons:
            lines.append(f"- {cut(h.get('title') or h.get('key'), 100)}"
                         f" ({h.get('score', '')})")
    kb = brief.get("kb") or []
    if kb:
        lines.append("KB docs:")
        for h in kb:
            lines.append(f"- {h.get('key')} ({h.get('score', '')})"
                         + (f" — {cut(h.get('title'), 80)}" if h.get("title") else ""))
    sims = brief.get("similar_cards") or []
    if sims:
        lines.append("Similar past cards — what proved right:")
        for h in sims:
            if h.get("error"):
                continue
            lines.append(f"- [{h.get('category')}] {h.get('card_id')} "
                         f"(sim {h.get('score')}): "
                         f"{cut(h.get('decision_point'), 90)} -> "
                         f"{cut(h.get('proven_right'), 140)}")
    if brief.get("mddb_ok") is False:
        lines.append(f"(mddb offline: {brief.get('mddb_error', '?')} — "
                     "ssot via local grep)")
    return "\n".join(lines)


def fetch_card(card_id):
    req = urllib.request.Request(API + "/cards")
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    cards = d if isinstance(d, list) else d.get("cards", [])
    for c in cards:
        if c.get("id") == card_id:
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="")
    ap.add_argument("--card-file", default="")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--corpus-briefs", default="",
                    help="corpus.jsonl -> per-case briefs json (--out)")
    ap.add_argument("--out", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--no-ssot", action="store_true",
                    help="similar-cards only (bench boundary ablation)")
    args = ap.parse_args()

    if args.corpus_briefs:
        cases = [json.loads(l) for l in
                 Path(args.corpus_briefs).read_text().splitlines() if l.strip()]
        idx = CorpusIndex(args.corpus)
        out = {}
        for c in cases:
            snap = c.get("snapshot") or {}
            pseudo = {"title": snap.get("title"), "brief": snap.get("brief"),
                      "tags": snap.get("tags"),
                      "comms_tail": snap.get("comms_tail")}
            brief = {"similar_cards": idx.neighbors(
                query_text(pseudo), k=args.k,
                exclude_card_ids={c.get("card_id")})}
            if not args.no_ssot:
                q = query_text(pseudo)
                own_key = f"kanban-cards-{c.get('card_id')}"
                try:
                    brief["ssot"] = [h for h in
                                     mddb_search(SSOT_COLLECTION, q, k=4)
                                     if h.get("key") != own_key][:3]
                    hits = []
                    for coll in LESSON_COLLECTIONS + KB_COLLECTIONS:
                        hits += mddb_search(coll, q, k=2)
                    hits.sort(key=lambda h: -h["score"])
                    brief["lessons"] = [h for h in hits if h["collection"]
                                        in LESSON_COLLECTIONS][:3]
                    brief["kb"] = [h for h in hits if h["collection"]
                                   in KB_COLLECTIONS][:3]
                except Exception:
                    brief["ssot"] = local_ssot_search(q)
            out[c["case_id"]] = {"card_id": c.get("card_id"),
                                 "category": c.get("category"),
                                 "brief": render(brief)}
            print(f"[{c['case_id']}] brief built", file=sys.stderr)
        Path(args.out or "briefs.json").write_text(json.dumps(out, indent=1))
        print(f"{len(out)} briefs -> {args.out or 'briefs.json'}",
              file=sys.stderr)
        return

    card = None
    if args.card_file:
        card = json.loads(Path(args.card_file).read_text())
    elif args.card:
        card = fetch_card(args.card)
    if not card:
        print("no card found", file=sys.stderr)
        sys.exit(2)
    brief = build_brief(card, k_cards=args.k, offline=args.offline)
    print(json.dumps(brief, indent=1, ensure_ascii=False)
          if args.json else render(brief))


if __name__ == "__main__":
    main()
