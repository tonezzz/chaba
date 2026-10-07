#!/usr/bin/env python3
"""yt-vtt-dub.py — minimal cue-level TTS dub over a yt-live cached video.

Reads a merged bilingual VTT (en line + th line per cue), synthesizes the
target-language line per cue with edge-tts, fits each segment to its cue
window (edge-tts --rate resynth first, atempo as fallback), lays segments
on a silent timeline, mixes over the ducked original, and muxes to mp4.

--qc gates synthesis on a caption-QC pass: every post-dedup cue/group is
scored (chars/sec bounds, thin-text-vs-window, rolling-caption residue,
untranslated EN in a TH line, speaker markers/stage directions); flagged
cues are skipped for TTS but stay in the display burn, and a JSON report +
printed table lands at <out>.qc.json (--qc-only scores without rendering).

Usage:
  yt-vtt-dub.py <media.m3u8> <subs.vtt> <out.mp4> [--lang th] [--secs 180] [--duck 0.22] [--qc]

Speaker casting (needs --sentences --en-vtt): --cast-detect for the
heuristic path, or --diarize-file for real diarization turns (RTTM or
'start end SPEAKER_NN' from yt-diarize.py) — >2 speakers map into
pitch-offset voice families via --cast-voices, and --anchors names
SPEAKER_NN labels from known transcript phrases (--names-map records
the resolution for reproducible renders).
"""
import argparse
import html
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EDGE = str(Path.home() / ".venvs/edge-tts/bin/edge-tts")
VOICES = {"th": "th-TH-PremwadeeNeural", "th-f": "th-TH-PremwadeeNeural",
          "th-m": "th-TH-NiwatNeural", "en": "en-US-ChristopherNeural"}
CUE_RE = re.compile(r"(\d+):(\d+):(\d+\.\d+)\s*-->\s*(\d+):(\d+):(\d+\.\d+)")
THAI = re.compile(r"[฀-๿]")
TAGS = re.compile(r"<[^>]+>")
SKIP = re.compile(r"^[\s♪()\-–—.]*$")


def ts(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_vtt(path, lang, limit):
    cues = []
    for b in Path(path).read_text(encoding="utf-8").split("\n\n"):
        m = CUE_RE.search(b)
        if not m:
            continue
        start, end = ts(*m.group(1, 2, 3)), ts(*m.group(4, 5, 6))
        lines = [
            TAGS.sub("", l).strip()
            for l in html.unescape(b[m.end():]).splitlines()
            if l.strip() and "-->" not in l
            and not re.match(
                r"(align|position|line|vertical|size|region):", l.strip())
        ]
        if lang.startswith("th"):
            text = " ".join(l for l in lines if THAI.search(l))
        else:
            text = " ".join(
                l
                for l in lines
                if not THAI.search(l) and not SKIP.match(l) and not l.startswith("(")
            )
        text = text.strip()
        if not text or start >= limit:
            continue
        end = min(end, limit)
        if end - start < 0.4:
            continue
        cues.append([start, end, text])
    cues.sort(key=lambda c: c[0])
    # clamp overlapping caption timestamps: a cue may not run into the next
    for i in range(len(cues) - 1):
        if cues[i][1] > cues[i + 1][0]:
            cues[i][1] = cues[i + 1][0]
    cues = [c for c in cues if c[1] - c[0] >= 0.4]

    # YouTube rolling captions: each cue repeats the previous cue's tail.
    # Strip the longest cue-prefix that already appears as the running
    # text's suffix — ~40% of auto-caption text is duplicated this way
    # (speaking it verbatim doubles words and explains "overlap").
    deduped = []
    spoken = ""
    for s, e, text in cues:
        t = " ".join(text.split())
        # longest prefix of t that is a suffix of spoken (char-level —
        # works for Thai, which has no word separators)
        k = 0
        for n in range(min(len(t), len(spoken)), 0, -1):
            if spoken.endswith(t[:n]):
                k = n
                break
        new = t[k:].strip()
        if len(new) >= 3:
            deduped.append([s, e, new])
            spoken = (spoken + " " + new).strip()
    return deduped


WORD_TAG = re.compile(r"<(\d+:\d+:\d+\.\d+)><c>")


def parse_words(path, limit, offset=0.0):
    """Karaoke word stream -> deduped [(start, end, word)].
    Splits every text piece into words — rolled-context blobs (untagged
    repeats of the previous cue) get dropped by the sequence dedup."""
    words = []
    for b in Path(path).read_text(encoding="utf-8").split("\n\n"):
        m = CUE_RE.search(b)
        if not m:
            continue
        cs, ce = ts(*m.group(1, 2, 3)) - offset, ts(*m.group(4, 5, 6)) - offset
        if cs >= limit or ce < 0:
            if cs >= limit:
                break
            continue
        wlist = []
        for ln in b[m.end():].splitlines():
            ln = re.sub(
                r"^\s*(align|position|line|vertical|size|region):.*", "", ln)
            if not ln.strip() or "-->" in ln:
                continue
            ln = html.unescape(ln)
            parts = WORD_TAG.split(ln)
            # lead text precedes the first tag -> starts at cue start;
            # text after a tag starts at that tag's time
            for w in TAGS.sub("", parts[0]).split():
                wlist.append([cs, 0, w])
            for i in range(1, len(parts), 2):
                wt = ts(*parts[i].split(":")) - offset
                for w in TAGS.sub("", parts[i + 1]).split():
                    wlist.append([wt, 0, w])
        # drop caption decorations — speaker markers and stage directions;
        # strip any >> fused onto word heads (">>But" -> "But")
        for w in wlist:
            w[2] = w[2].lstrip(">")
        wlist = [w for w in wlist
                 if w[2] and not
                 (w[2].startswith("[") and w[2].endswith("]"))]
        if not wlist:
            continue
        for j in range(len(wlist)):
            wlist[j][1] = (wlist[j + 1][0] if j + 1 < len(wlist) else ce)
        # rolling-caption dedup at word level: drop the longest prefix of
        # this cue's words that equals the emitted stream's suffix
        emit = [w[2].lower() for w in words]
        cur = [w[2].lower() for w in wlist]
        k = 0
        for n in range(min(len(cur), len(emit)), 0, -1):
            if emit[-n:] == cur[:n]:
                k = n
                break
        words.extend(w for w in wlist[k:] if w[0] < limit)
    for i in range(1, len(words)):
        if words[i - 1][1] > words[i][0]:
            words[i - 1][1] = words[i][0]
    return words


def sentence_groups(words, gap=1.0, voice_at=None):
    """Split the deduped word stream at phrase breaks / turn changes.
    Auto-captions carry no punctuation — the signal is the inter-word
    START delta (word duration + silence): ~0.36s/word median within a
    phrase, ~1s+ at chunk/sentence boundaries. voice_at(t) -> voice name
    or None; a change forces a boundary. Returns [(start,end,[w],voice)]."""
    groups = []
    prev_start = None
    for w in words:
        v = voice_at(w[0]) if voice_at else None
        if groups and ((prev_start is not None and w[0] - prev_start > gap)
                       or (voice_at and v != groups[-1][3])):
            groups.append([w[0], w[0], [], v])
            groups[-2][1] = w[0]
        if not groups:
            groups.append([w[0], w[0], [], v])
        groups[-1][1] = w[1]
        groups[-1][2].append((w[0], w[2]))
        prev_start = w[0]
    return [(s, e, ws, v) for s, e, ws, v in groups if ws]


def _fix(text, fm):
    for k, v in fm.items():
        text = text.replace(k, v)
    return text


# --- caption QC gate -------------------------------------------------------
# Scores every post-dedup cue/group before synthesis; flagged cues are
# skipped for TTS but stay in the display burn (the burn VTT is written from
# the group table before the gate runs). Report lands at <out>.qc.json —
# see docs/ssot/jobs/yt-dub/2026-10-07-yt-voice-dub-qc.yml.
QC_CPS = {            # chars/sec bounds vs the cue's OWN caption span —
    "th": (2.0, 30.0),   # ~2x natural = unspeakable; below lo the text can't
    "en": (3.0, 36.0),   # account for the caption duration (truncated/garbage)
}
QC_NAT_CPS = {"th": 14.0, "en": 16.0}   # natural-rate chars/sec (fill estimate)
QC_FILL_MIN = 0.12    # short text covering <12% of a >=5s span = fragment
QC_PREFIX_MIN = 0.6   # shared prefix with previous cue >= this share = residue
QC_PREFIX_CHARS = 8   # ... and at least this many chars
QC_LATIN = re.compile(r"[A-Za-z]{2,}")
QC_STAGE = re.compile(  # bracketed stage directions + speaker markers that
    r"\[[^\]]{1,40}\]|>>|^\s*>|\b(applause|laughter|cheering)\b", re.I)


def qc_score(cues, lang, spans=None):
    """Score post-dedup cues [(start,end,text)]; return flag dicts.
    spans[i] = the cue's own caption span (real VTT duration / group word
    span) — density is judged against the caption's claim, not the fit
    window (turn splits leave ~0.2s fit windows under real speech)."""
    lo, hi = QC_CPS.get(lang[:2], QC_CPS["en"])
    nat = QC_NAT_CPS.get(lang[:2], 16.0)
    flags = []
    prev = ""
    for i, (s, e, text) in enumerate(cues):
        win = max((spans[i] if spans else e - s), 0.01)
        t = " ".join(str(text).split())
        reasons = []
        cps = len(t) / win
        if cps > hi:
            reasons.append(f"cps-high {cps:.0f}>{hi:.0f}")
        elif cps < lo and len(t) >= 4:
            reasons.append(f"cps-low {cps:.1f}<{lo:.0f}")
        if win >= 5.0 and len(t) <= 12 and len(t) / nat / win < QC_FILL_MIN:
            reasons.append(f"thin fill={len(t) / nat / win:.0%}")
        if prev:
            k = 0
            for a_ch, b_ch in zip(t, prev):
                if a_ch != b_ch:
                    break
                k += 1
            if k >= QC_PREFIX_CHARS and k / max(len(t), 1) >= QC_PREFIX_MIN:
                reasons.append(f"residue prefix={k}ch")
        if lang.startswith("th"):
            # missed translation: a "Thai" line that is really English.
            # pure-EN lines never reach here (parse_vtt drops them), so this
            # catches latin-dominant fragments + --th-file leftovers while
            # sparing proper names (>=3 latin words AND latin-dominant)
            lat = QC_LATIN.findall(t)
            n_th = len(THAI.findall(t))
            n_lat = sum(len(w) for w in lat)
            if (not n_th and len(lat) >= 2) \
                    or (len(lat) >= 3 and n_lat > n_th):
                reasons.append("untranslated")
        if QC_STAGE.search(t):
            reasons.append("markers")
        if reasons:
            flags.append({"i": i, "start": round(s, 2), "end": round(e, 2),
                          "cps": round(cps, 1), "reasons": reasons,
                          "text": t[:140]})
        prev = t
    return flags


def qc_gate(cues, voice_of, lang, out_path, spans=None):
    """Print the QC table, write <out>.qc.json, drop flagged cues (remapping
    voice indices). Returns (cues, voice_of, report)."""
    import json
    flags = qc_score(cues, lang, spans)
    print(f"qc: {len(flags)}/{len(cues)} cues flagged "
          f"(skipped for TTS, kept in burn)")
    for f in flags:
        print(f"  [{f['i']:>3}] {f['start']:>7.2f}s "
              f"{', '.join(f['reasons']):<26} {f['text'][:60]}")
    report = {"lang": lang, "cues": len(cues), "flagged": len(flags),
              "gate": "flagged cues skipped for TTS, kept in display burn",
              "flags": flags}
    rep_path = out_path
    with open(rep_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(f"qc report -> {rep_path}")
    bad = {f["i"] for f in flags}
    keep = [i for i in range(len(cues)) if i not in bad]
    cues = [cues[i] for i in keep]
    voice_of = {ni: v for ni, oi in enumerate(keep)
                if (v := voice_of.get(oi))}
    return cues, voice_of, report


# --- heuristic speaker-turn detection ---------------------------------------
# YouTube auto-captions carry no speaker labels. Under a 2-speaker assumption
# (interview/talk) every detected turn boundary flips the voice. Signals:
# cue-gap clustering (Otsu split of inter-group gaps -> long-gap class is
# likely turn air) + question cues (prev group ends '?', next opens with an
# interrogative). Heuristic, not diarization — verify on the dump before
# trusting a full render.
Q_LEAD = {  # question openers: wh-words + aux-inversion + "tell me"
    "what", "why", "how", "when", "where", "who", "whose", "which",
    "do", "does", "did", "is", "are", "was", "were", "can", "could",
    "would", "will", "shall", "should", "have", "has", "tell",
}
ANS_LEAD = {  # response openers — a new phrase starting with one is often
    "yeah", "yes", "no", "nah", "well", "oh", "right", "exactly",  # a reply
    "absolutely", "sure", "really", "definitely", "obviously",
    "honestly", "actually", "totally", "indeed", "wow", "ah",
}
TAG_Q = re.compile(  # whole-phrase tag/discourse questions — rhetorical,
    r"^(right|yeah|yes|ok|okay|innit|isn't it|you know|"
    r"you know what i mean|know what i mean|you see|see)[\s.,!?]*$",
    re.I)


def _grp_text(g):
    return " ".join(w for _, w in g[2])


def _q_end(g):
    t = _grp_text(g).rstrip(" .,!…")
    if not t.endswith("?"):
        return False
    # tag-question phrases ("You know what I mean?", "Right?") are
    # discourse markers, not turn elicitors — suppress whole-phrase tags
    return not TAG_Q.match(t)


def _q_start(g):
    for _, w in g[2]:
        w = w.lower().strip(".,!?\"'")
        if w:
            return w in Q_LEAD
    return False


def _ans_start(g):
    for _, w in g[2]:
        w = w.lower().strip(".,!?\"'")
        if w:
            return w in ANS_LEAD
    return False


def _otsu_split(vals):
    """Sorted 1-D 2-class split (Otsu between-class variance).
    Returns the smallest value of the upper class — the boundary between
    'normal pause' and 'turn pause' gaps — or None when there is no
    meaningful second cluster (gaps uniform -> rely on question cues)."""
    s = sorted(vals)
    n = len(s)
    if n < 6 or s[-1] - s[0] < 0.8:
        return None
    total = sum(s)
    best_i, best_v, s0 = None, -1.0, 0.0
    for i in range(1, n):
        s0 += s[i - 1]
        w0 = i / n
        m0, m1 = s0 / i, (total - s0) / (n - i)
        v = w0 * (1 - w0) * (m0 - m1) ** 2
        if s[i] != s[i - 1] and v > best_v:
            best_v, best_i = v, i
    return s[best_i] if best_i else None


def detect_turns(words, speakers=2, detect_gap=0.6, min_pause=0.35):
    """Heuristic speaker-turn detection on the karaoke word stream.

    Phrases = words split at start-deltas > detect_gap (mirrors
    sentence_groups, but phrase end = last word END so inter-phrase gap
    is true silence — sentence_groups clamps ends to the next start and
    would show zero air). Each boundary scores question cues and cue-gap
    clustering; every boundary flips speaker under N-speaker round-robin
    (default 2 -> alternation). Returns (turns, debug): turns =
    [(start, end, spk_idx, [phrases])], phrases shaped like groups."""
    # phrase index boundaries in the word stream
    cuts = [i for i in range(1, len(words))
            if words[i][0] - words[i - 1][0] > detect_gap]
    phrases = []
    for a, b in zip([0] + cuts, cuts + [len(words)]):
        ws = words[a:b]
        phrases.append((ws[0][0], ws[-1][1],
                        [(w[0], w[2]) for w in ws], None))
    gaps = [phrases[i + 1][0] - phrases[i][1]
            for i in range(len(phrases) - 1)]
    t_long = _otsu_split(gaps)
    med = max(0.25, (t_long or 1.4) * 0.4)
    turns, dbg = [], []
    spk = 0
    for i, g in enumerate(phrases):
        if i:
            # NB: word-end times are derived (end = next word start), so
            # caption air is ~0 except caption-off beats — question cues
            # carry most of the turn signal, real air the rest.
            gap = max(gaps[i - 1], 0.0)
            qe, qs = _q_end(phrases[i - 1]), _q_start(g)
            ans = _ans_start(g)
            short_answer = len(g[2]) <= 4
            turn_air = g[0] - (turns[-1][0] if turns else g[0])
            score = 0.0
            if t_long is not None and gap >= t_long:
                score += 1.5          # real air — likely turn pause
            elif gap >= med:
                score += 0.5
            if qe:
                score += 1.7          # question just ended -> answer turn
                if short_answer:
                    score += 0.5      # "Yeah."/"No." — classic reply
            if qs:
                score += 0.6          # question opens -> likely host turn
                if turn_air >= 12:
                    score += 1.0      # host interjecting a long answer
            if ans:
                score += 0.8 if gap >= 0.15 else 0.3
            # a real question flips unconditionally — in interviews the
            # answer usually jumps in with ~0 captioned air anyway
            boundary = qe or score >= 1.5
            dbg.append({"t": round(g[0], 2), "gap": round(gap, 2),
                        "q_end": qe, "q_start": qs, "ans": ans,
                        "score": round(score, 2), "boundary": boundary})
            if boundary:
                spk = (spk + 1) % speakers
        if turns and turns[-1][2] == spk:
            turns[-1][1] = g[1]
            turns[-1][3].append(g)
        else:
            turns.append([g[0], g[1], spk, [g]])
    return turns, {"t_long": t_long, "boundaries": dbg}


def turns_to_cast_times(turns, voices):
    """[(s,e,spk,..)] -> 'voice:t0-t1,t2-t3;voice2:u0-u1' cast-times map.
    A turn's range runs to the NEXT turn's start so voice_at() covers
    inter-turn air too (words landing mid-gap keep the last speaker)."""
    ranges = {}
    for i, t in enumerate(turns):
        s, e, spk = t[0], t[1], t[2]
        e = turns[i + 1][0] if i + 1 < len(turns) else e
        ranges.setdefault(spk % len(voices), []).append((s, e))
    parts = []
    for spk in sorted(ranges):
        parts.append(voices[spk] + ":" + ",".join(
            f"{s:.2f}-{e:.2f}" for s, e in ranges[spk]))
    return ";".join(parts)


def turn_summary(turns):
    """Per-speaker stats for the detection report: airtime, turn count,
    question marks (question-asker ~ the host in an interview)."""
    stats = {}
    for s, e, spk, gs in turns:
        st = stats.setdefault(spk, {"turns": 0, "air": 0.0, "q": 0})
        st["turns"] += 1
        st["air"] += e - s
        st["q"] += sum(1 for g in gs if _q_end(g))
    return stats


# --- diarization-driven casting ---------------------------------------------
# Real turn tables come from pyannote (yt-diarize.py on tony-omen GPU) as
# either RTTM ('SPEAKER f 1 t0 dur <NA> <NA> LABEL <NA> <NA>') or the plain
# 'start end SPEAKER_NN' text format. SPEAKER_NN labels are cluster ids, not
# identities — name speakers via transcript anchors (--anchors), not
# voiceprints.


def parse_diarize(path, min_turn=0.3):
    """Diarization turn file -> (turns, labels).

    turns = [(start, end, spk_idx)] with labels mapped to indices in order
    of first appearance (sorted time axis). Turns shorter than min_turn are
    dropped — pyannote micro-turn noise (~0.3s floor, same filter v17 used)
    — then adjacent same-speaker spans merge. Returns labels in index
    order so callers can print 'SPEAKER_00 -> voice' mappings."""
    raw = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", ";")):
            continue
        f = ln.split()
        try:
            if f[0].upper() == "SPEAKER" and len(f) >= 8:
                s, dur, lab = float(f[3]), float(f[4]), f[7]
                raw.append((s, s + dur, lab))
            elif len(f) >= 3:
                raw.append((float(f[0]), float(f[1]), f[2]))
        except ValueError:
            continue  # header / malformed line
    labels = {}
    for _, _, lab in sorted(raw):
        labels.setdefault(lab, len(labels))
    turns = []
    for s, e, lab in sorted(raw):
        if e - s < min_turn:
            continue
        idx = labels[lab]
        if turns and turns[-1][2] == idx:
            turns[-1][1] = e
        else:
            turns.append([s, e, idx])
    inv = [None] * len(labels)
    for lab, i in labels.items():
        inv[i] = lab
    return turns, inv


# Pitch-offset families: edge-tts ships exactly 2 TH voices, so speakers
# beyond the base-voice count re-enter a family at a shifted pitch.
# Ladder alternates up/down so members spread away from base timbre; the
# separability ceiling is ~3-4 members per family (past ~±20Hz the voice
# reads as a different speaker but sounds processed). Entries in
# --cast-voices may already carry @pitch — member 0 keeps it verbatim.
PITCH_LADDER = [0, 8, -10, -18, 16, -26, 24, -34]


def speaker_voices(base_voices, n_speakers):
    """One voice spec per speaker index via pitch-offset families.

    speaker i -> base_voices[i % len(base)] family; member index
    i // len(base) picks its PITCH_LADDER offset (member 0 = unshifted
    base spec, @pitch preserved). Round-robins speakers beyond the base
    count into the same voice at shifted pitch."""
    out = []
    for i in range(n_speakers):
        spec = base_voices[i % len(base_voices)]
        m = i // len(base_voices)
        if m:
            voice, _, _ = spec.partition("@")
            off = (PITCH_LADDER[m] if m < len(PITCH_LADDER)
                   else PITCH_LADDER[-1] - 8 * (m - len(PITCH_LADDER) + 1))
            spec = f"{voice}@{off:+d}Hz"
        out.append(spec)
    return out


def _norm_tok(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def anchor_speakers(anchor_map, words, turns):
    """Transcript-anchor naming: {'Name': 'known phrase'} -> spk_idx.

    Finds the phrase as a consecutive token run in the karaoke word
    stream, then resolves the diarization turn covering that time under
    extended coverage (each turn runs to the next turn's start — same
    rule voice_at uses). Returns {spk_idx: (name, t)} — first Name to
    claim a speaker wins."""
    wn = [_norm_tok(w[2]) for w in words]
    claimed = {}
    for name, phrase in anchor_map.items():
        toks = [t for t in (_norm_tok(x) for x in phrase.split()) if t]
        hit = None
        for i in range(len(wn) - len(toks) + 1):
            if wn[i:i + len(toks)] == toks:
                hit = words[i][0]
                break
        if hit is None:
            print(f"anchor '{name}': phrase not found in word stream",
                  file=sys.stderr)
            continue
        spk = 0
        for ti, (s, e, idx) in enumerate(turns):
            if s <= hit:
                spk = idx
            else:
                break
        if spk not in claimed:
            claimed[spk] = (name, hit)
        else:
            print(f"anchor '{name}': lands on already-claimed speaker "
                  f"{spk} — ignored", file=sys.stderr)
    return claimed


def probe(p):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def tts(text, out, voice=None, rate=None):
    spec = (voice or VOICE)
    voice, _, pitch = spec.partition("@")  # "name@-8Hz" -> voice + pitch
    cmd = [EDGE, "--voice", voice, "--text", text, "--write-media", str(out)]
    if pitch:
        cmd += ["--pitch", pitch]
    if rate:
        cmd += ["--rate", rate]
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and Path(out).exists() and Path(out).stat().st_size > 0:
            return
    raise subprocess.CalledProcessError(r.returncode, cmd, stderr=r.stderr)


def compress_lines(texts, key=None, model=None):
    """Tighten each line for spoken dub (~70% length). Gemini first,
    local ollama fallback (quota-free)."""
    import json
    import urllib.request
    prompt = (
        "Rewrite each Thai subtitle line to be SHORTER for voice dubbing — "
        "terse natural spoken Thai, keep the meaning, target ~60-70% of the "
        "original length. Do not add commentary. Return ONLY a JSON array of "
        "strings with the same length and order as the input.\n\n"
        + json.dumps(texts, ensure_ascii=False))
    if key:
        try:
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json",
                                     "temperature": 0.2},
            }
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model or 'gemini-2.5-flash'}:generateContent?key={key}")
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"})
            out = json.loads(urllib.request.urlopen(req, timeout=90).read())
            arr = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
            if isinstance(arr, list) and len(arr) == len(texts):
                return [str(x).strip() or t for x, t in zip(arr, texts)]
        except Exception as e:
            print(f"gemini compress failed ({e}); trying ollama",
                  file=sys.stderr)
    def ollama(chunk):
        p = (
            "Rewrite each Thai subtitle line to be SHORTER for voice dubbing — "
            "terse natural spoken Thai, keep the meaning, target ~60-70% of "
            "the original length. Return ONLY a JSON array of strings with "
            "the same length and order as the input.\n\n"
            + json.dumps(chunk, ensure_ascii=False))
        payload = {"model": "llama3.2:3b", "prompt": p, "stream": False}
        out = json.loads(urllib.request.urlopen(urllib.request.Request(
            "http://idc03.taila0626a.ts.net:11434/api/generate",
            data=json.dumps(payload).encode()), timeout=240).read())
        m = re.search(r"\[.*\]", out.get("response", ""), re.S)
        arr = json.loads(m.group(0)) if m else []
        return arr if isinstance(arr, list) and len(arr) == len(chunk) else chunk

    chunks = [texts[i:i + 12] for i in range(0, len(texts), 12)]
    with ThreadPoolExecutor(3) as ex:
        done = list(ex.map(ollama, chunks))
    return [t for chunk in done for t in chunk]


def synth_one(i, text, work, voice=None, rate=None):
    mp3 = work / f"c{i:04d}{'_r' if rate else ''}.mp3"
    try:
        tts(text, mp3, voice=voice, rate=rate)
    except subprocess.CalledProcessError as e:
        print(f"  cue {i} tts failed: {e.stderr.decode()[:100]}", file=sys.stderr)
        return i, mp3, 0.0
    return i, mp3, probe(mp3)


def fit_wav(i, mp3, window, work):
    """mp3 -> wav; strip TTS onset/lead silence; atempo residual over
    window (cap 1.4x), atrim the tail."""
    wav = work / f"c{i:04d}.wav"
    dur = probe(mp3)
    # edge-tts emits ~200ms leading silence + ~150ms tail — both steal
    # sync accuracy and window budget; strip them before timing math
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
           "-af", "silenceremove=start_periods=1:start_threshold=-45dB:"
           "start_silence=0.04,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB:"
           "start_silence=0.04,areverse"]
    dur = None
    if dur := probe(mp3):
        if dur > window * 1.05:
            r = min(dur / window, 1.4)
            chain = cmd[-1] + f",atempo={r:.3f}"
            if dur / r > window:
                chain += f",atrim=duration={window:.3f}"
            cmd[-1] = chain
    cmd += ["-ar", "44100", "-ac", "1", str(wav)]
    subprocess.run(cmd, check=True, capture_output=True)
    return wav


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("m3u8")
    ap.add_argument("vtt")
    ap.add_argument("out")
    ap.add_argument("--lang", default="th")
    ap.add_argument("--secs", type=int, default=180)
    ap.add_argument("--duck", default="0.22")
    ap.add_argument("--max-rate", type=float, default=1.25,
                    help="cap global speed-up factor (default 1.25x)")
    ap.add_argument("--no-compress", action="store_true",
                    help="skip the Gemini tighten pass on the text")
    ap.add_argument("--lag-budget", type=float, default=5.0,
                    help="total seconds of drift allowed across the whole "
                         "render — per-segment --lag draws from this pool; "
                         "once spent, segments atempo onto their cue times")
    ap.add_argument("--lag", type=float, default=3.0,
                    help="max seconds a segment may trail its cue (queue mode)")
    ap.add_argument("--cast-map", default="",
                    help="per-cue voice: 'voice:0-6,9-12;voice2:7-8' — "
                         "cue indices after dedup; unmatched cues use --lang default")
    ap.add_argument("--sentences", action="store_true",
                    help="merge deduped text into sentence groups (pause "
                         "gaps / turn changes) — one utterance per sentence")
    ap.add_argument("--sent-gap", type=float, default=1.4,
                    help="min word-start gap (s) that opens a new sentence "
                         "group — raise so voice carries over scene cuts")
    ap.add_argument("--cast-times", default="",
                    help="time-based cast map: 'voice:t0-t1,t2-;voice2:t3-t4' "
                         "in seconds — overrides --cast-map for turn borders")
    ap.add_argument("--cast-detect", action="store_true",
                    help="auto-detect speaker turns from the karaoke word "
                         "stream (cue-gap clustering + question cues, "
                         "--speakers alternating) -> cast-times. Needs "
                         "--sentences --en-vtt; explicit --cast-times/"
                         "--cast-map wins")
    ap.add_argument("--cast-voices", default="",
                    help="comma voices for --cast-detect/--diarize-file in "
                         "speaker order (default: Niwat,Premwadee — "
                         "host-then-guest). Entries may carry @pitch "
                         "('voice@+8Hz'); speakers beyond the list length "
                         "round-robin into pitch-offset families")
    ap.add_argument("--speakers", type=int, default=2,
                    help="speaker count assumption for --cast-detect")
    ap.add_argument("--diarize-file", default="",
                    help="diarization turn file (RTTM or 'start end "
                         "SPEAKER_NN' text) — converts real speaker turns "
                         "to cast-times; needs --sentences --en-vtt; "
                         "explicit --cast-times/--cast-map wins")
    ap.add_argument("--min-turn", type=float, default=0.3,
                    help="drop diarization turns shorter than this (s) — "
                         "pyannote micro-turn noise floor")
    ap.add_argument("--anchors", default="",
                    help="transcript-anchor speaker naming: "
                         "'Name=phrase they say;Name2=other phrase' — "
                         "matched against the EN word stream to name "
                         "SPEAKER_NN labels for burn-vtt + --names-map")
    ap.add_argument("--names-map", default="",
                    help="write speaker->voice->name resolution as JSON "
                         "(with anchor match times) so renders are "
                         "reproducible")
    ap.add_argument("--detect-gap", type=float, default=0.6,
                    help="word-gap (s) for the detection pass — finer than "
                         "--sent-gap so turn candidates are not pre-merged")
    ap.add_argument("--dump-turns", default="",
                    help="write detected turn table "
                         "(spk/start/end/q/text) as JSON")
    ap.add_argument("--names", default="",
                    help="speaker name tags for subs: "
                         "'voice@pitch=ชื่อ;voice2=ชื่อ2' — shown on voice change")
    ap.add_argument("--en-vtt", default="",
                    help="karaoke source VTT with <c> word timestamps "
                         "(required by --sentences)")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="seconds to subtract from caption times — use when "
                         "the media input is a pre-cut slice")
    ap.add_argument("--burn-vtt", default="",
                    help="also write a display VTT of the merged sentences")
    ap.add_argument("--th-file", default="",
                    help="JSON array of polished TH text per sentence group "
                         "(overrides translated text for speech + burn)")
    ap.add_argument("--fix-map", default="",
                    help="JSON object(s) of TH pronunciation fixups applied "
                         "to spoken text — comma paths merge in order, e.g. "
                         "'seed.th.json,VID.th.json'; ZWSP \\u200b forces the "
                         "syllable break ('{\"โล่งอก\": \"โล่ง\\u200bอก\"}')")
    ap.add_argument("--qc", action="store_true",
                    help="caption QC gate: score every post-dedup cue/group "
                         "before TTS (cps bounds, thin-vs-window, rolling "
                         "residue, untranslated EN, speaker markers/stage "
                         "directions); flagged cues are skipped for TTS but "
                         "stay in the burn; report -> <out>.qc.json")
    ap.add_argument("--qc-report", default="",
                    help="QC report path (default <out>.qc.json)")
    ap.add_argument("--qc-only", action="store_true",
                    help="run the QC pass then exit — no TTS, no render")
    ap.add_argument("--dump-groups", default="",
                    help="write sentence-group table (idx/voice/en/th) as JSON")
    ap.add_argument("--dub-wav", default="",
                    help="also write the bare dub track (pre-mix, no "
                         "original bed) — for voice/pitch verification")
    ap.add_argument("--dump-only", action="store_true",
                    help="exit after --dump-groups (tune maps without TTS)")
    a = ap.parse_args()
    if a.cast_detect and not a.sentences:
        print("--cast-detect needs --sentences --en-vtt; ignoring",
              file=sys.stderr)
    if a.diarize_file and not a.sentences:
        print("--diarize-file needs --sentences --en-vtt; ignoring",
              file=sys.stderr)
    global VOICE
    VOICE = VOICES[a.lang]

    cues = parse_vtt(a.vtt, a.lang, a.secs)
    print(f"{len(cues)} {a.lang} cues within {a.secs}s")
    if not cues and not a.sentences:
        sys.exit("no usable cues")
    orig_cue_starts = [c[0] for c in cues]  # snapshot before clamp shifts
    qc_spans = [c[1] - c[0] for c in cues]  # real caption spans for --qc
    # clamp overlapping VTT timestamps — auto-captions often overlap;
    # each cue's fit window extends into the gap before the next cue
    # (dead air is free space — absorb overflow before compressing)
    for i in range(len(cues)):
        s, e, t = cues[i]
        if i and s < cues[i - 1][1]:
            s = cues[i - 1][1]
        nxt = cues[i + 1][0] if i + 1 < len(cues) else a.secs
        # fit window runs to the NEXT cue's start — gap air is free space
        cues[i] = (s, max(min(nxt, a.secs), s + 0.4), t)  # (start, fit_end, text)

    # per-cue voice assignment (speaker casting): 'voice:lo-hi,lo-hi;voice:lo-'
    voice_of = {}
    if a.cast_map:
        for part in a.cast_map.split(";"):
            voice, _, ranges = part.partition(":")
            for rng in ranges.split(","):
                lo, _, hi = rng.partition("-")
                hi = hi or str(len(cues))
                for n in range(int(lo), int(hi) + 1):
                    voice_of[n] = voice.strip()
        print(f"cast-map: {len(voice_of)} cues -> "
              + ", ".join(f"{v.split('-')[-2]} x{sum(1 for x in voice_of.values() if x == v)}"
                          for v in set(voice_of.values())))

    # sentence-merge: karaoke word times -> pause/turn boundaries ->
    # one utterance per sentence group (natural TTS prosody + clean subs)
    if a.sentences:
        if not a.en_vtt:
            sys.exit("--sentences needs --en-vtt (karaoke <c> word times)")
        words = parse_words(a.en_vtt, a.secs, offset=a.offset)
        cue_starts = orig_cue_starts  # clamped starts drift voice lookup

        if a.diarize_file and not (a.cast_times or a.cast_map):
            # real diarization turn file -> speaker-indexed turns ->
            # cast-times; beats --cast-detect heuristics when both given
            base = ([v.strip() for v in a.cast_voices.split(",")]
                    if a.cast_voices else
                    ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"])
            dturns, dlabels = parse_diarize(
                a.diarize_file, min_turn=a.min_turn)
            spk_voices = speaker_voices(base, len(dlabels))
            a.cast_times = turns_to_cast_times(dturns, spk_voices)
            air = {}
            for s, e, idx in dturns:
                air[idx] = air.get(idx, 0.0) + e - s
            print(f"diarize: {len(dturns)} turns, {len(dlabels)} speakers "
                  f"from {Path(a.diarize_file).name}")
            for idx, lab in enumerate(dlabels):
                print(f"  {lab} -> {spk_voices[idx]}: "
                      f"{sum(1 for t in dturns if t[2] == idx)} turns, "
                      f"{air.get(idx, 0):.0f}s air")
            # transcript-anchor naming: known phrase -> SPEAKER_NN -> name
            named = {}
            if a.anchors:
                amap = dict(p.split("=", 1) for p in a.anchors.split(";")
                            if "=" in p)
                named = anchor_speakers(amap, words, dturns)
                extra = []
                for idx, (name, hit) in sorted(named.items()):
                    extra.append(f"{spk_voices[idx]}={name}")
                    print(f"  anchor: {dlabels[idx]} = {name} "
                          f"(matched @ {hit:.1f}s)")
                if extra:
                    a.names = ";".join(
                        ([a.names] if a.names else []) + extra)
            if a.names_map:
                import json as _jn
                _jn.dump(
                    {"source": str(a.diarize_file),
                     "speakers": [
                         {"speaker": dlabels[i], "voice": spk_voices[i],
                          "name": named[i][0] if i in named else "",
                          "anchor_t": round(named[i][1], 2) if i in named
                          else None,
                          "turns": sum(1 for t in dturns if t[2] == i),
                          "air_s": round(air.get(i, 0), 1)}
                         for i in range(len(dlabels))]},
                    open(a.names_map, "w", encoding="utf-8"),
                    ensure_ascii=False, indent=1)
                print(f"names map -> {a.names_map}")
            if a.dump_turns:
                import json as _jd
                _jd.dump(
                    {"labels": dlabels, "voices": spk_voices,
                     "min_turn": a.min_turn,
                     "turns": [
                         {"spk": idx, "label": dlabels[idx],
                          "voice": spk_voices[idx],
                          "s": round(s, 2), "e": round(e, 2),
                          "text": " ".join(
                              w[2] for w in words
                              if s <= w[0] < e)[:160]}
                         for s, e, idx in dturns]},
                    open(a.dump_turns, "w", encoding="utf-8"),
                    ensure_ascii=False, indent=1)
                print(f"dumped turns -> {a.dump_turns}")
            if a.dump_only:
                sys.exit(0)
        elif a.diarize_file:
            print("diarize: explicit --cast-times/--cast-map wins",
                  file=sys.stderr)

        if a.cast_detect:
            if a.cast_times or a.cast_map:
                print("cast-detect: explicit --cast-times/--cast-map wins",
                      file=sys.stderr)
            else:
                det_voices = speaker_voices(
                    [v.strip() for v in a.cast_voices.split(",")]
                    if a.cast_voices else
                    ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"],
                    a.speakers)
                turns, dbg = detect_turns(
                    words, speakers=a.speakers, detect_gap=a.detect_gap)
                a.cast_times = turns_to_cast_times(turns, det_voices)
                stats = turn_summary(turns)
                host = max(stats, key=lambda s: stats[s]["q"],
                           default=None)
                n_bounds = sum(1 for b in dbg["boundaries"] if b["boundary"])
                print(f"cast-detect: {len(turns)} turns over {a.speakers} "
                      f"speakers ({n_bounds} boundaries, "
                      f"t_long={dbg['t_long']})")
                for spk in sorted(stats):
                    st = stats[spk]
                    tag = " <- host?" if spk == host and st["q"] else ""
                    print(f"  S{spk} {det_voices[spk % len(det_voices)]}: "
                          f"{st['turns']} turns, {st['air']:.0f}s air, "
                          f"{st['q']} questions{tag}")
                if a.dump_turns:
                    import json as _jt
                    _jt.dump(
                        {"t_long": dbg["t_long"],
                         "voices": det_voices,
                         "turns": [
                             {"spk": spk, "s": round(s, 2), "e": round(e, 2),
                              "text": " ".join(_grp_text(g) for g in gs)[:160]}
                             for s, e, spk, gs in turns],
                         "boundaries": dbg["boundaries"]},
                        open(a.dump_turns, "w", encoding="utf-8"),
                        ensure_ascii=False, indent=1)
                    print(f"dumped turns -> {a.dump_turns}")
                if a.dump_only:
                    sys.exit(0)

        if a.cast_times:
            # turn borders in seconds — bisect a sorted boundary list
            import bisect as _bb
            tb = []  # (from_time, voice)
            for part in a.cast_times.split(";"):
                voice, _, ranges = part.partition(":")
                for rng in ranges.split(","):
                    lo, _, hi = rng.rpartition("-")
                    tb.append((float(lo), voice.strip(),
                               float(hi) if hi else a.secs))
            tb.sort()

            def voice_at(t):
                v = None
                for lo, vo, hi in tb:
                    if lo <= t < hi:
                        v = vo
                        break
                return v
        else:
            def voice_at(t):
                import bisect
                idx = bisect.bisect_right(cue_starts, t) - 1
                return voice_of.get(idx) if idx >= 0 else None

        groups = sentence_groups(
            words, gap=a.sent_gap,
            voice_at=voice_at if (a.cast_map or a.cast_times) else None)
        # TH deduped cue text lands in the group containing its start;
        # keep (cue_time, text) pieces so display slices can re-split,
        # and re-dedup each piece against the group's running text —
        # TH re-translation isn't verbatim so use a tolerant tail match
        import bisect as _b
        g_starts = [g[0] for g in groups]
        g_pieces = [[] for _ in groups]
        for ci, c in enumerate(cues):
            gi = max(_b.bisect_right(g_starts, orig_cue_starts[ci]) - 1, 0)
            acc = " ".join(p[1] for p in g_pieces[gi])
            tail = acc[-160:]
            t = " ".join(c[2].split())
            k = 0
            for n in range(min(len(t), 120), 2, -1):
                pos = tail.rfind(t[:n])
                if pos >= 0 and len(tail) - (pos + n) <= 20:
                    k = n
                    break
            new = t[k:].strip()
            if new:
                g_pieces[gi].append((c[0], new))
        groups = [(s, e, ws, v, " ".join(p[1] for p in g_pieces[i]), g_pieces[i])
                  for i, (s, e, ws, v) in enumerate(groups)]
        dump = getattr(a, "dump_groups", "")
        if dump:
            import json as _j
            _j.dump([{"i": i, "s": round(g[0], 2), "voice": g[3] or "",
                      "en": " ".join(w for _, w in g[2]),
                      "th": g[4]} for i, g in enumerate(groups)],
                    open(dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"dumped {len(groups)} groups -> {dump}")
            if a.dump_only:
                sys.exit(0)
        if a.th_file:
            import json as _json
            over = _json.loads(open(a.th_file, encoding="utf-8").read())
            groups = [(*g[:4], over[i] if i < len(over) and over[i] else g[4],
                       g[5]) for i, g in enumerate(groups)]
            print(f"th-file overrides: {min(len(over), len(groups))} groups")
        fm = {}
        if a.fix_map:
            import json as _j2
            # comma-separated paths merge in order (seed dict first, then a
            # per-video dict overriding) — see the fix-map watch-list doc
            for p in a.fix_map.split(","):
                p = p.strip()
                if p:
                    fm.update(_j2.loads(open(p, encoding="utf-8").read()))
            print(f"fix-map: {len(fm)} rules (spoken text only)")
        # build cues + voice_of in the same index space — dropping a
        # too-short group must not shift the voice map onto the wrong cue
        voice_of, cues, qc_spans = {}, [], []
        for gi, g in enumerate(groups):
            t = _fix(g[4], fm)
            if len(t) < 3:
                continue
            if g[3]:
                voice_of[len(cues)] = g[3]
            qc_spans.append(g[1] - g[0])   # group word-span for --qc
            cues.append([g[0],
                         groups[gi + 1][0] if gi + 1 < len(groups) else a.secs,
                         t])
        print(f"{len(groups)} sentence groups -> {len(cues)} spoken")
        if a.burn_vtt:
            def _ts(x):
                h = int(x // 3600); m = int((x % 3600) // 60)
                return f"{h:02d}:{m:02d}:{x % 60:06.3f}"
            name_of = dict(p.split("=", 1) for p in a.names.split(";")
                           if "=" in p) if a.names else {}
            burn_prev = [None]
            with open(a.burn_vtt, "w", encoding="utf-8") as f:
                f.write("WEBVTT\n\n")
                for i, g in enumerate(groups):
                    gend = groups[i + 1][0] if i + 1 < len(groups) else g[1]
                    # split display blocks >9s at TH-piece cue starts — each
                    # slice shows its own EN word span + TH piece span
                    bounds = [g[0]]
                    for p in g[5]:
                        if p[0] - bounds[-1] > 9:
                            bounds.append(p[0])
                    # th-file groups have no pieces — slice on time at word
                    # boundaries so a 20s group isn't one mega-block
                    if len(bounds) == 1:
                        b = g[0]
                        for wt, _ in g[2]:
                            if wt - b > 9:
                                bounds.append(wt)
                                b = wt
                    bounds.append(gend)
                    ns = len(bounds) - 1
                    if a.th_file and g[4]:
                        # distribute the TH line across slices ~proportionally
                        # to each slice's EN word count, splitting on
                        # Thai-friendly clause punctuation
                        chunks = re.split(r"(?<=[,—…!?๏])\s*|\s+(?=—)", g[4])
                        chunks = [c for c in chunks if c.strip()]
                        wcnt = [sum(1 for wt, _ in g[2]
                                    if bounds[j] <= wt < bounds[j + 1])
                                for j in range(ns)]
                        tot = max(sum(wcnt), 1)
                        th_slices, ci = [], 0
                        for j in range(ns):
                            take = round(len(chunks) * wcnt[j] / tot)
                            if j == ns - 1:
                                take = len(chunks) - ci
                            take = min(max(take, 0), len(chunks) - ci)
                            th_slices.append("".join(chunks[ci:ci + take]))
                            ci += take
                    else:
                        th_slices = [" ".join(p[1] for p in g[5]
                                              if bounds[j] <= p[0] < bounds[j + 1])
                                     for j in range(ns)]
                    for j in range(ns):
                        bs, be = bounds[j], bounds[j + 1]
                        en = " ".join(w for wt, w in g[2] if bs <= wt < be)
                        th = th_slices[j]
                        if j == 0:
                            nm = name_of.get(g[3], "")
                            if nm and g[3] != burn_prev[0]:
                                th = f"{nm}: {th}" if th else nm
                        f.write(f"{_ts(max(bs, 0))} --> "
                                f"{_ts(max(be, bs + 0.8, 0))}\n"
                                f"{en}\n{th}\n\n")
                    burn_prev[0] = g[3]

    # caption QC gate — last text transform before TTS; flagged cues leave
    # the synth list here (display burn was already written from `groups`)
    if a.qc or a.qc_only:
        rep = a.qc_report or str(Path(a.out).with_suffix("")) + ".qc.json"
        cues, voice_of, _ = qc_gate(cues, voice_of, a.lang, rep, qc_spans)
        if a.qc_only:
            sys.exit(0)
        if not cues:
            sys.exit("qc: nothing left to synthesize")

    # tighten the text for spoken dub — TH translations run ~1.4x too long
    # for the EN timing window; shorter text is the honest speed fix
    if not a.no_compress:
        import os
        try:
            before = [c[2] for c in cues]
            texts = compress_lines(
                before, os.environ.get("GEMINI_API_KEY"),
                os.environ.get("GEMINI_MODEL"))
            cues = [(s, e, t2) for (s, e, _), t2 in zip(cues, texts)]
            shrink = (1 - sum(map(len, texts)) /
                      max(sum(map(len, before)), 1)) * 100
            print(f"compressed {len(texts)} cue texts ({shrink:.0f}% shorter)")
        except Exception as e:
            print(f"compress failed ({e}); using source text",
                  file=sys.stderr)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        # pass 1: natural-rate synth — measure total speech vs total window
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda t: synth_one(t[0], t[1], work, t[2]),
                              [(i, c[2], voice_of.get(i)) for i, c in enumerate(cues)]))
        ok = [(i, p, d) for i, p, d in res if d > 0]
        total_speech = sum(d for _, _, d in ok)
        total_window = sum(cues[i][1] - cues[i][0] for i, _, _ in ok)
        g_rate = min(max(total_speech / max(total_window, 0.1), 0.95), a.max_rate)
        rate_pct = int(round((g_rate - 1.0) * 100 / 5) * 5)
        print(f"speech {total_speech:.0f}s vs window {total_window:.0f}s -> "
              f"global rate {g_rate:.2f} ({rate_pct:+d}%)")

        # pass 2: resynth every cue at the SAME rate — uniform voice speed
        if rate_pct > 0:
            with ThreadPoolExecutor(4) as ex:
                res2 = list(ex.map(lambda t: synth_one(t[0], t[1], work, t[2],
                                                       rate=f"+{rate_pct}%"),
                                   [(i, cues[i][2], voice_of.get(i))
                                    for i, _, _ in ok]))
            mp3_of = {i: p for i, p, d in res2}
        else:
            mp3_of = {i: p for i, p, d in ok}

        segs = []
        lag_pool = a.lag_budget
        for i, _, _ in ok:
            try:
                # bound = cue window + lag drawn from a shared budget —
                # when the pool runs dry, atempo pins speech to cue time
                win = cues[i][1] - cues[i][0]
                bound = win + min(a.lag, lag_pool)
                w = fit_wav(i, mp3_of[i], bound, work)
                lag_pool = max(0.0, lag_pool - max(0.0, probe(w) - win))
                segs.append((w, i))
            except subprocess.CalledProcessError:
                print(f"  cue {i} failed", file=sys.stderr)
        print(f"{len(segs)} segments rendered")

        # queue layout: each segment starts at its cue start OR right when
        # the previous segment ends — the caption pause IS the breath gap;
        # only add a beat when a speaker turn happens with no natural air
        prev_end = 0.0
        prev_i = None
        placed = []
        total_lag = 0.0
        for w, i in segs:
            cue_start = cues[i][0]
            air = cue_start - prev_end
            pos = max(cue_start, prev_end, 0.0)
            if (a.sentences and prev_i is not None
                    and voice_of.get(i) != voice_of.get(prev_i)
                    and air < 0.25):
                pos += 0.3  # zero-air turn — beat so the voice switch reads
            total_lag += pos - cue_start
            placed.append((w, int(pos * 1000)))
            prev_end = pos + probe(w)
            prev_i = i
        print(f"total queued lag: {total_lag:.1f}s; "
              f"last speech ends at {prev_end:.1f}s")

        # assemble dub track: silence base + each segment at queue offset
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={a.secs}"]
        for w, _ in placed:
            cmd += ["-i", str(w)]
        fc = ";".join(
            f"[{i + 1}:a]adelay={ms}|{ms}[d{i}]" for i, (_, ms) in enumerate(placed)
        )
        fc += (";[0:a]" + "".join(f"[d{i}]" for i in range(len(placed)))
               + f"amix=inputs={len(placed) + 1}:normalize=0[dub]")
        dub = work / "dub.wav"
        subprocess.run(cmd + ["-filter_complex", fc, "-map", "[dub]", str(dub)],
                       check=True)
        if a.dub_wav:
            import shutil
            shutil.copy(dub, a.dub_wav)
            print(f"bare dub track -> {a.dub_wav}")

        # mux: dub loudnorm + original sidechain-ducked — English drops to
        # --duck volume only while Thai speaks, ambience (laughter etc)
        # returns in the gaps instead of bleeding under every utterance
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-i", a.m3u8, "-i", str(dub),
            "-filter_complex",
            "[1:a]loudnorm=I=-16:TP=-1.5:LRA=8,asplit=2[dubm][sc];"
            f"[0:a]volume=0.55[orig];"
            f"[orig][sc]sidechaincompress=threshold=0.015:ratio=12:"
            "attack=15:release=500:makeup=1[bg];"
            "[dubm][bg]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-t", str(a.secs), "-c:v", "copy", "-c:a", "aac", a.out,
        ], check=True)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
