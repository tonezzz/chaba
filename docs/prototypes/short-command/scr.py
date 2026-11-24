"""Short command recognizer (SCR) — tiered, host-agnostic, stdlib-only.

T0: template/grammar match  (hassil-style syntax, zero inference)
T1: exemplar similarity     (char-3gram + token Jaccard; optional embedding
                             scorer via SCR_EMBED_URL)
T2: local router LLM        (optional, via SCR_ROUTER_URL — POST
                             {"text": ...} expecting {"intent","slots"})

Usage:
    from scr import Recognizer
    r = Recognizer("commands.json")
    print(r.recognize("turn on the kitchen light"))
"""

import json
import os
import re
import time
import urllib.request

# Calibrated 2026-11-24 on the real TG voice corpus (card
# scr-calibrate-t1-…-8ca63e): max non-command score 0.216, min true
# T1 command 0.615 — see docs/kb/short-command-recognition-research.md
_GRAY_LO = 0.25      # below: pass through
_ACCEPT_HI = 0.40    # at/above: accept T1


def _norm(text):
    """Lowercase, strip punctuation, collapse whitespace. Thai-safe
    (no word splitting — Thai has no spaces)."""
    t = text.lower().strip()
    t = re.sub(r"[?!.,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _ngrams(t, n=3):
    return {t[i:i + n] for i in range(max(len(t) - n + 1, 1))}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def lexical_score(a, b):
    """Char-3gram Jaccard (0.6) + token Jaccard (0.4). Char n-grams carry
    unspaced Thai; tokens help spaced EN."""
    a, b = _norm(a), _norm(b)
    return 0.6 * _jaccard(_ngrams(a), _ngrams(b)) + \
        0.4 * _jaccard(set(a.split()), set(b.split()))


class _Slot:
    def __init__(self, spec):
        self.kind = spec["kind"]
        if self.kind == "list":
            self.canonical = {}          # alias -> canonical value
            for value, aliases in spec["values"].items():
                for alias in aliases:
                    self.canonical[alias] = value
            self.pattern = "|".join(
                re.escape(a) for a in
                sorted(self.canonical, key=len, reverse=True))
        else:                            # regex | rest
            self.canonical = None
            self.pattern = "|".join("(?:%s)" % p for p in spec["patterns"])

    def resolve(self, text):
        if self.canonical is None:
            return text.strip()
        return self.canonical.get(text.strip(), text.strip())


def _compile(template, slots):
    """hassil-lite: (a|b) alternation, [x] optional, {slot} placeholder.
    Whitespace -> \\s* so unspaced Thai segments match."""
    out, i = ["^"], 0
    while i < len(template):
        c = template[i]
        if c == "(":
            out.append("(?:"); i += 1
        elif c == ")":
            out.append(")"); i += 1
        elif c == "[":
            out.append("(?:"); i += 1
        elif c == "]":
            out.append(")?"); i += 1
        elif c == "|":
            out.append("|"); i += 1
        elif c == "{":
            j = template.index("}", i)
            name = template[i + 1:j]
            out.append("(?P<%s>%s)" % (name, slots[name].pattern))
            i = j + 1
        elif c.isspace():
            while i < len(template) and template[i].isspace():
                i += 1
            out.append(r"\s*")
        else:
            out.append(re.escape(c)); i += 1
    out.append("$")
    return re.compile("".join(out), re.IGNORECASE)


class Recognizer:
    def __init__(self, commands_path,
                 accept=_ACCEPT_HI, gray_lo=_GRAY_LO):
        spec = json.load(open(commands_path, encoding="utf-8"))
        self.slots = {k: _Slot(v) for k, v in spec["slot_lists"].items()}
        self.accept, self.gray_lo = accept, gray_lo
        self.intents = []                # [(intent, regex)]
        self.exemplars = {}              # intent -> [phrases]
        self.known = set()
        for item in spec["intents"]:
            name = item["intent"]
            self.known.add(name)
            for tmpl in item.get("templates", []):
                self.intents.append((name, _compile(tmpl, self.slots)))
            self.exemplars[name] = item.get("exemplars", [])
        self.embed_url = os.environ.get("SCR_EMBED_URL")
        self.router_url = os.environ.get("SCR_ROUTER_URL")
        self._embed_cache = {}

    # -- tiers ---------------------------------------------------------

    def _t0(self, text):
        t = _norm(text)
        for intent, rx in self.intents:
            m = rx.match(t)
            if m:
                slots = {k: self.slots[k].resolve(v)
                         for k, v in m.groupdict().items() if v}
                return {"status": "match", "intent": intent,
                        "slots": slots, "tier": "T0", "score": 1.0}
        return None

    def _embed(self, text):
        if text in self._embed_cache:
            return self._embed_cache[text]
        body = json.dumps({"text": text}).encode()
        req = urllib.request.Request(
            self.embed_url, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            vec = json.loads(r.read())["embedding"]
        self._embed_cache[text] = vec
        return vec

    @staticmethod
    def _cosine(a, b):
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def _sim(self, a, b):
        if not self.embed_url:
            return lexical_score(a, b)
        try:
            return self._cosine(self._embed(_norm(a)),
                                self._embed(_norm(b)))
        except Exception:
            return lexical_score(a, b)   # scorer downgraded, still works

    def _t1(self, text):
        best = (0.0, None)
        for intent, phrases in self.exemplars.items():
            for p in phrases:
                s = self._sim(text, p)
                if s > best[0]:
                    best = (s, intent)
        score, intent = best
        if score >= self.accept:
            return {"status": "match", "intent": intent, "slots": {},
                    "tier": "T1", "score": round(score, 3)}
        if score >= self.gray_lo:
            return {"status": "gray", "intent": intent, "slots": {},
                    "tier": "T1", "score": round(score, 3)}
        return None

    def _t2(self, text):
        if not self.router_url:
            return None
        try:
            body = json.dumps({"text": text}).encode()
            req = urllib.request.Request(
                self.router_url, data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                out = json.loads(r.read())
            if out.get("intent") in self.known:
                return {"status": "match", "intent": out["intent"],
                        "slots": out.get("slots", {}),
                        "tier": "T2", "score": out.get("score", 1.0)}
        except Exception:
            pass                         # breaker: escalate silently
        return None

    # -- public --------------------------------------------------------

    def recognize(self, text):
        t0 = time.monotonic()
        for tier in (self._t0, self._t1, self._t2):
            hit = tier(text)
            if hit:
                hit["elapsed_ms"] = round((time.monotonic() - t0) * 1e3, 2)
                return hit
        return {"status": "no_match", "intent": None, "slots": {},
                "tier": None, "score": 0.0,
                "elapsed_ms": round((time.monotonic() - t0) * 1e3, 2)}
