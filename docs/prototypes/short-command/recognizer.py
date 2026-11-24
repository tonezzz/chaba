#!/usr/bin/env python3
"""Tiered short-command recognizer — stdlib-only prototype.

Pipeline (see docs/kb/short-command-recognition-research.md):

  T0  deterministic: exact phrase table + anchored, operand-gated regex.
      $0, microseconds, zero wrong-fires by construction on covered forms.
  T1  char n-gram TF-IDF cosine similarity against per-intent prototype
      phrases, gated by absolute threshold AND top-1/top-2 margin.
      Pure Python — no numpy/sklearn — so it runs anywhere.
  T2  declared rung, NOT implemented here: the local small-LLM
      route+entity call (ada-voice command_lane -> /v1/systemone).
      The prototype treats "below T1" as escalate-to-T2/T3.
  T3  pass-through to the full pipeline (provider turn / Ada turn).

Design rule (the wrong-fire gate): a tier may only CLAIM an item when
confidence clears its gate; everything else escalates. A wrong local
action costs far more than a slow provider turn, so thresholds are
set for precision, not recall.
"""

import json
import math
import re
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- T0 data

# Exact normalized phrases -> intent. Longest phrase wins, so specific
# forms ("หยุดเพลง" = stop-the-music -> media) beat generic ones
# ("หยุด" -> stop).
T0_PHRASES = {
    # status
    "status": "status", "status?": "status", "board status": "status",
    "สถานะ": "status", "สถานะบอร์ด": "status",
    # help
    "help": "help", "help me": "help", "ช่วยหน่อย": "help",
    "ใช้ยังไง": "help", "วิธีใช้": "help",
    # stop / cancel
    "stop": "stop", "cancel": "stop", "cancel that": "stop",
    "never mind": "stop", "nevermind": "stop",
    "หยุด": "stop", "ยกเลิก": "stop", "ไม่เอาแล้ว": "stop",
    # media
    "play": "media", "pause": "media", "next": "media",
    "previous": "media", "resume": "media",
    "volume up": "media", "volume down": "media", "mute": "media",
    "เล่น": "media", "เล่นเพลง": "media", "หยุดเพลง": "media",
    "เพลงต่อไป": "media", "เพลงก่อนหน้า": "media", "เสียงดังขึ้น": "media",
    "เสียงเบาลง": "media", "ปิดเสียง": "media", "เปิดเสียง": "media",
    "ปิดเพลง": "media",
    # device (HA)
    "open the tv": "device", "turn on the tv": "device",
    "เปิดทีวี": "device", "ปิดทีวี": "device",
    # time
    "what time is it": "time", "what's the time": "time",
    "what time": "time", "กี่โมงแล้ว": "time", "กี่โมง": "time",
    "ตอนนี้กี่โมง": "time",
    # explain — whole-message forms only; operand-gated patterns below
    # carry the ref requirement
    # board_action — same
}

# Anchored patterns -> intent. `^...` forms only: the devnest router's
# whole-message discipline — "please explain X" is not a command.
# Patterns may carry operand gates (a card ref, a device noun) so a
# bare keyword can't fire on an open question.
# Patterns run on NORMALIZED text (casefolded, punctuation -> space),
# so "OPS-0912" arrives as "ops 0912" — the ref pattern allows the
# space/hyphen separator. "card <slug>" covers slug-form references.
CARD_REF = (r"(?:[a-z]{2,4}[ -]?\d{3,5}|ops[ -]?\d+|"
            r"card\s+[a-z0-9][a-z0-9 ]*)")
T0_PATTERNS = {
    "status": [
        re.compile(r"^what'?s the status\b"),
        re.compile(r"^status (please|pls)\b"),
        re.compile(r"^บอร์ดเป็นไง\b"),
        re.compile(r"^สถานะเป็นไง\b"),
    ],
    "help": [
        re.compile(r"^what can you do\b"),
        re.compile(r"^show me the commands\b"),
        re.compile(r"^help (me|please)?\s*$"),
        re.compile(r"^วิธีใช้|^ใช้งานยังไง"),
    ],
    "stop": [
        re.compile(r"^cancel (that|it|this)\b"),
        re.compile(r"^never ?mind\b"),
    ],
    "media": [
        re.compile(r"^(play|pause|resume|next|previous)\b"),
        re.compile(r"^volume (up|down|mute)\b"),
        # Thai: no \b — Thai script has no word boundaries; exact
        # phrases above carry the precision, these catch extensions.
        # Bare หยุด is NOT a media prefix: หยุดก่อน = "stop for now"
        # (stop intent), only หยุดเพลง/เสียง is media.
        re.compile(r"^(เล่น|ต่อไป|ก่อนหน้า)"),
        re.compile(r"^หยุด(เพลง|เสียง|การเล่น)"),
        re.compile(r"^เพลง(ต่อไป|ก่อนหน้า)"),
        re.compile(r"^เสียง(ดัง|เบา)"),
        re.compile(r"^ปิดเสียง|^เปิดเสียง|^ปิดเพลง"),
    ],
    "device": [
        re.compile(r"^(turn|switch) (on|off)\b"),
        re.compile(r"^(open|close) the\b"),
        # Thai device control is OPERAND-GATED like explain: bare
        # เปิด/ปิด also forms media commands (ปิดเสียง = mute,
        # ปิดเพลง = stop music). Require a device noun.
        re.compile(r"^(เปิด|ปิด)(ไฟ|แอร์|ทีวี|พัดลม|ไฟฉาย|ประตู|หม้อหุงข้าว|ทีวี)"),
    ],
    "time": [
        re.compile(r"^what'?s the (date|time)\b"),
        re.compile(r"^what day is (it|today)\b"),
        re.compile(r"^what is the (date|time)\b"),
        re.compile(r"^(กี่โมง|วันนี้วันอะไร|วันอะไร)"),
    ],
    # explain requires a card-ref / card-slug operand — "explain how
    # DNS works" must NOT fire (wrong-fire gate).
    "explain": [
        re.compile(r"^(explain|describe|show)\s+" + CARD_REF),
        re.compile(r"^status of\s+" + CARD_REF),
        re.compile(r"^(อธิบาย|บอก)\s+" + CARD_REF),
    ],
    # board_action: anchored form + operand. Approver gating happens
    # downstream (devnest router TELEGRAM_APPROVER_IDS), not here.
    "board_action": [
        re.compile(r"^(approve|reject|accept|deny)\s+" + CARD_REF),
        re.compile(r"^(approve|reject)\s+(that|this|the)\s+(request|card|ask)"),
        re.compile(r"^(อนุมัติ|ปฏิเสธ)\s+" + CARD_REF),
    ],
}

# ------------------------------------------------------------- T1 data
# Prototype phrases per intent — the T1 "class centroids". Deliberately
# mixed EN/TH, imperative + interrogative shapes, with and without
# operands. Char n-grams (not tokens) because Thai has no spaces.

T1_PROTOTYPES = {
    "status": [
        "status", "board status", "what's the status", "system status",
        "how are things", "how's everything", "status check",
        "สถานะ", "สถานะบอร์ด", "เป็นไงบ้าง", "เป็นยังไง", "ตอนนี้เป็นไง",
    ],
    "help": [
        "help", "help me", "what can you do", "show commands",
        "list commands", "usage", "how do i use this",
        "ช่วยหน่อย", "ใช้ยังไง", "วิธีใช้", "ทำอะไรได้บ้าง", "สั่งงานยังไง",
    ],
    "stop": [
        "stop", "cancel", "cancel that", "never mind", "forget it",
        "stop that", "halt",
        "หยุด", "ยกเลิก", "ไม่เอาแล้ว", "เลิก", "หยุดก่อน",
    ],
    "media": [
        "play", "pause", "next track", "previous track", "volume up",
        "volume down", "mute", "resume", "skip", "play music",
        "เล่นเพลง", "หยุดเพลง", "เพลงต่อไป", "เพลงก่อนหน้า", "เสียงดังขึ้น",
        "เสียงเบาลง", "เล่นต่อ", "ข้ามเพลง",
    ],
    "device": [
        "turn on the light", "turn off the light", "turn on the ac",
        "open the tv", "close the tv", "switch on the fan",
        "ปิดไฟ", "เปิดไฟ", "เปิดแอร์", "ปิดแอร์", "เปิดทีวี", "ปิดทีวี",
        "เปิดพัดลม",
    ],
    "time": [
        "what time is it", "what's the time", "what's the date",
        "what day is today", "current time", "tell me the time",
        "กี่โมงแล้ว", "กี่โมง", "วันนี้วันอะไร", "วันที่เท่าไหร่", "ตอนนี้กี่โมง",
    ],
    "explain": [
        "explain OPS-0912", "explain this card", "what is OPS-0912",
        "tell me about this card", "card status",
        "status of OPS-0912", "status of this card",
        "describe the card",
        "อธิบายการ์ด", "บอกสถานะการ์ด", "การ์ดนี้คืออะไร",
    ],
    "board_action": [
        "approve OPS-0912", "reject OPS-0912", "approve this",
        "reject this request", "approve the card", "deny the request",
        "อนุมัติ", "ปฏิเสธ", "อนุมัติการ์ด", "ตกลงการ์ดนี้",
    ],
}

# Phrases allowed to prefix-match ("play some jazz" -> media). Bare
# status words are NOT here: "status of the new router" must escalate,
# not claim the status intent.
T0_PREFIX_PHRASES = {
    "play", "pause", "next", "previous", "resume", "mute",
    "volume up", "volume down",
}

# T1 operand gate: these intents are DEFINED by their operand — an
# "explain"/"approve" with no card-ref (or request pronoun) is an open
# question, not a command. T1 may only claim them when the operand is
# actually present. This is the same discipline as the T0 patterns.
T1_OPERAND_RES = {
    "explain": re.compile(CARD_REF),
    "board_action": re.compile(
        CARD_REF + r"|(that|this|the)\s+(request|card|ask)"),
}

# T1 vetoes: shapes that LOOK command-adjacent to n-grams but are task
# requests or entity questions. Checked before scoring — a veto beats
# any similarity score.
T1_VETOES = [
    # "ช่วย<verb>..." = "help me <do task>" — a task request, not the
    # help intent. Only bare "ช่วยหน่อย" is help (T0 exact phrase).
    re.compile(r"^ช่วย(?!\s*หน่อย)"),
    # "help me <two+ words>" = task request ("help me fix my car");
    # "help me"/"help me please"/"help me out" stay help-eligible.
    re.compile(r"^help me\s+\S+\s+\S+"),
    # "status of <non-card-entity>" is a question about that entity;
    # card-scoped status routes to explain (operand present -> no veto).
    re.compile(r"^status of\s+(?!" + CARD_REF + r")"),
]

# T1 gates — three zones, tuned on corpus.jsonl for ZERO wrong-fires
# first, then max deflection:
#   sim >= T1_ACCEPT          -> claim (zone "accept")
#   T1_GRAY <= sim < ACCEPT   -> escalate, candidate logged (zone "gray")
#   sim < T1_GRAY             -> escalate, no candidate (zone "reject")
# The margin gate rejects cases where two intents score nearly equal
# (ambiguous -> escalate regardless of zone).
T1_ACCEPT = 0.42
T1_GRAY = 0.28
T1_MARGIN = 0.06
NGRAM_MIN, NGRAM_MAX = 3, 5

# Short acks/greetings are the trivial-gate's job upstream; the command
# recognizer explicitly refuses texts under this length unless T0
# matched, so "ok"/"lol" can never become commands.
T1_MIN_CHARS = 4

# ---------------------------------------------------------------- utils

_PUNCT_RE = re.compile(r"[^\w\s\u0e00-\u0e7f]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Casefold, NFKC, strip punctuation, collapse whitespace.

    Keeps Thai block (\u0e00-\u0e7f) and word chars; Thai has no spaces
    so token-level matching is useless — n-grams downstream handle it.
    """
    t = unicodedata.normalize("NFKC", text).casefold()
    t = _PUNCT_RE.sub(" ", t)
    return _SPACE_RE.sub(" ", t).strip()


def ngrams(text: str) -> list[str]:
    padded = f" {text} "
    return [
        padded[i:i + n]
        for n in range(NGRAM_MIN, NGRAM_MAX + 1)
        for i in range(len(padded) - n + 1)
    ]


def _tfidf_vector(grams: list[str], idf: dict[str, float]) -> dict[str, float]:
    """Sublinear tf, idf-weighted, L2-normalized sparse vector."""
    tf: dict[str, int] = {}
    for g in grams:
        tf[g] = tf.get(g, 0) + 1
    vec = {g: (1 + math.log(c)) * idf.get(g, 0.0) for g, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {g: v / norm for g, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(g, 0.0) for g, v in a.items())


class Recognizer:
    """T0 -> T1 cascade. Returns (tier, intent|None, confidence, note)."""

    def __init__(self, accept: float = T1_ACCEPT, gray: float = T1_GRAY,
                 margin: float = T1_MARGIN):
        self.accept = accept
        self.gray = gray
        self.margin = margin
        # longest phrase first so "หยุดเพลง" beats "หยุด"
        self._phrases = sorted(T0_PHRASES.items(),
                               key=lambda kv: -len(kv[0]))
        # Pre-build T1 index: per-intent prototype vectors + idf over
        # the whole prototype corpus (small — build once).
        all_grams = [
            g for phrases in T1_PROTOTYPES.values()
            for p in phrases for g in set(ngrams(normalize(p)))
        ]
        df: dict[str, int] = {}
        for g in all_grams:
            df[g] = df.get(g, 0) + 1
        n_docs = len(all_grams) or 1
        self._idf = {
            g: math.log((n_docs + 1) / (c + 1)) + 1.0 for g, c in df.items()
        }
        self._intent_vecs: dict[str, list[dict[str, float]]] = {}
        for intent, phrases in T1_PROTOTYPES.items():
            self._intent_vecs[intent] = [
                _tfidf_vector(ngrams(normalize(p)), self._idf)
                for p in phrases
            ]

    # -- T0 ---------------------------------------------------------
    def _t0(self, norm: str) -> tuple[str, float] | None:
        for phrase, intent in self._phrases:
            if norm == phrase or (phrase in T0_PREFIX_PHRASES
                                  and norm.startswith(phrase + " ")):
                return intent, 1.0
        for intent, pats in T0_PATTERNS.items():
            for pat in pats:
                if pat.search(norm):
                    return intent, 1.0
        return None

    # -- T1 ---------------------------------------------------------
    def _t1(self, norm: str) -> dict | None:
        """Score all intents; return best candidate + zone.

        zone "accept" is the only claimable outcome; "gray"/"reject"
        both escalate but gray keeps the candidate for the T2 rung.
        """
        if len(norm) < T1_MIN_CHARS:
            return None
        if any(v.search(norm) for v in T1_VETOES):
            return {"zone": "veto", "intent": None, "confidence": 0.0}
        vec = _tfidf_vector(ngrams(norm), self._idf)
        scores: dict[str, float] = {}
        for intent, pvecs in self._intent_vecs.items():
            scores[intent] = max(_cosine(vec, pv) for pv in pvecs)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        (best_i, best_s), (_, second_s) = ranked[0], ranked[1]
        margin = best_s - second_s
        ambiguous = margin < self.margin
        operand_res = T1_OPERAND_RES.get(best_i)
        operand_ok = operand_res is None or operand_res.search(norm)
        if ambiguous or not operand_ok:
            zone = "reject"
        elif best_s >= self.accept:
            zone = "accept"
        elif best_s >= self.gray:
            zone = "gray"
        else:
            zone = "reject"
        return {"zone": zone, "intent": best_i, "confidence": best_s,
                "margin": margin}

    # -- public -----------------------------------------------------
    def recognize(self, text: str) -> dict:
        norm = normalize(text)
        hit = self._t0(norm)
        if hit:
            intent, conf = hit
            return {"tier": "T0", "intent": intent, "confidence": conf,
                    "zone": "accept", "normalized": norm}
        hit = self._t1(norm)
        if hit:
            if hit["zone"] == "accept":
                return {"tier": "T1", "intent": hit["intent"],
                        "confidence": hit["confidence"],
                        "margin": hit["margin"], "zone": "accept",
                        "normalized": norm}
            # gray/reject/veto -> escalate; keep the candidate for T2
            return {"tier": "T3", "intent": None, "confidence": 0.0,
                    "zone": hit["zone"],
                    "candidate": hit.get("intent"),
                    "candidate_confidence": hit.get("confidence"),
                    "normalized": norm}
        # T2 rung (local LLM route+entity) is declared but not
        # implemented in this stdlib prototype — escalate straight to
        # the T3 pass-through outcome.
        return {"tier": "T3", "intent": None, "confidence": 0.0,
                "zone": "reject", "normalized": norm}


def load_corpus(path: Path) -> list[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    import sys
    rec = Recognizer()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        r = rec.recognize(line)
        print(json.dumps({"text": line, **r}, ensure_ascii=False))
