#!/usr/bin/env python3
"""yt-vtt-translate.py — translate a WebVTT file via Gemini and emit a merged
dual-language VTT (original line(s) + translated line(s) per cue).

Usage: yt-vtt-translate.py IN.vtt OUT.vtt [--target th] [--batch 40]
       yt-vtt-translate.py GROUPS.json OUT.json --groups [--target th]
Env:    GEMINI_API_KEY (required), GEMINI_MODEL (optional override)

--groups mode consumes the sentence-group table emitted by
yt-vtt-dub.py --dump-groups ([{i,s,e,voice,en,th}]) and writes a plain
JSON array of translated strings — the format --th-file takes — so
dubbing no longer needs a hand-written Thai file. Translation happens
per sentence group (natural spoken register, sized to the group's time
window), one LLM call per --batch groups, disk-cached under
~/.cache/yt-live-subs/groups/ keyed on lang+model+inputs. Fallback when
no API is reachable: the group's cue-level machine translation (the "th"
field), i.e. the pre-existing dub behaviour.
"""
import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

LANGS = {
    "th": "Thai", "en": "English", "ja": "Japanese", "ko": "Korean",
    "zh": "Simplified Chinese", "vi": "Vietnamese", "id": "Indonesian",
    "ms": "Malay", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "hi": "Hindi",
    "nl": "Dutch", "de-orig": "German",
}
TIME_RE = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})")
TAG_RE = re.compile(r"<[^>]*>")


def parse_vtt(path):
    cues = []  # (start, end, text)
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f]
    i = 0
    while i < len(lines):
        m = TIME_RE.search(lines[i])
        if not m:
            i += 1
            continue
        start, end = m.group(1), m.group(2)
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i])
            i += 1
        text = html.unescape(TAG_RE.sub("", " ".join(text_lines))).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            cues.append([start, end, text])
    # drop consecutive duplicates (YouTube auto-sub rolling captions)
    deduped = []
    for c in cues:
        if deduped and deduped[-1][2] == c[2]:
            deduped[-1][1] = c[1]  # extend end time
            continue
        deduped.append(c)
    return deduped


def api_request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def pick_models(key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        models = api_request(url).get("models", [])
    except Exception:
        return ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
    names = [m["name"].split("/")[-1] for m in models
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    pref = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite",
            "gemini-flash-latest", "gemini-3.5-flash",
            "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash",
            "gemini-2.5-flash"]
    ordered = [m for m in pref if m in names]
    ordered += [n for n in names if "flash" in n and n not in ordered]
    return ordered or ["gemini-2.5-flash"]


def translate_batch(texts, lang_name, models, key):
    prompt = (
        f"Translate each subtitle line into {lang_name}. Keep meaning natural for "
        f"spoken dialogue; never leave words in the source language or English "
        f"(only proper names may stay). Do not add commentary. Return ONLY a "
        f"JSON array of strings with the same length and order as the input.\n\n"
        + json.dumps(texts, ensure_ascii=False))
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.2},
    }
    for model in models:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        for wait in (0, 20, 40):
            if wait:
                time.sleep(wait)
            try:
                out = api_request(url, payload)
                text = out["candidates"][0]["content"]["parts"][0]["text"]
                arr = json.loads(text)
                if isinstance(arr, list) and len(arr) == len(texts):
                    return [str(x).strip() for x in arr]
                if isinstance(arr, list) and len(arr) > len(texts):
                    return [str(x).strip() for x in arr[:len(texts)]]
            except Exception:
                continue
    print("warn: batch translate failed on all models; keeping original",
          file=sys.stderr)
    return list(texts)


def translate_group_batch(items, lang_name, models, key):
    """items = [{en, secs, mt?}] -> spoken-register translations sized to
    each group's window. One API call per batch, model-chain retry."""
    prompt = (
        f"These are consecutive subtitle groups from one video, to be dubbed "
        f"into {lang_name} voice-over. Each item has the source line (\"en\") "
        f"and the seconds it must fit (\"secs\"). Rewrite each as natural, "
        f"conversational spoken {lang_name} — the way a native speaker would "
        f"say it aloud, not a literal translation — short enough to speak "
        f"comfortably inside its window at normal pace (~12-14 characters "
        f"per second; aim under, never over). Keep proper names. If \"mt\" is "
        f"present it is a rough cue-level machine translation — use it for "
        f"meaning reference only, do not copy its phrasing. Do not add "
        f"commentary. Return ONLY a JSON array of strings with the same "
        f"length and order as the input.\n\n"
        + json.dumps(items, ensure_ascii=False))
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0.3},
    }
    for model in models:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        for wait in (0, 20, 40):
            if wait:
                time.sleep(wait)
            try:
                out = api_request(url, payload)
                arr = json.loads(out["candidates"][0]["content"]
                                 ["parts"][0]["text"])
                if isinstance(arr, list) and len(arr) == len(items):
                    return [str(x).strip() for x in arr]
                if isinstance(arr, list) and len(arr) > len(items):
                    return [str(x).strip() for x in arr[:len(items)]]
            except Exception:
                continue
    return None


GROUP_CACHE = Path.home() / ".cache/yt-live-subs/groups"
GROUP_PROMPT_V = "v1"  # bump to invalidate the disk cache


def groups_mode(a):
    groups = json.loads(open(a.src, encoding="utf-8").read())
    if not isinstance(groups, list) or not groups:
        sys.exit(f"no groups parsed from {a.src}")
    lang_name = LANGS.get(a.target.lower(), a.target)
    items = [{"en": g.get("en", ""),
              "secs": round(max(g.get("e", g["s"]) - g["s"], 0.5), 1)}
             for g in groups]
    for it, g in zip(items, groups):
        if g.get("th"):
            it["mt"] = g["th"]

    key = os.environ.get("GEMINI_API_KEY")
    models = ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL")
              else (pick_models(key) if key else []))
    ck = hashlib.sha256(
        (GROUP_PROMPT_V + "|" + a.target + "|" + (models[0] if models else "none")
         + "|" + json.dumps(items, ensure_ascii=False)).encode()).hexdigest()
    cache = GROUP_CACHE / f"{ck[:20]}.{a.target}.json"
    if cache.exists():
        try:
            arr = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(arr, list) and len(arr) == len(groups):
                print(f"group translation cache hit -> {a.dst}",
                      file=sys.stderr)
                Path(a.dst).write_text(
                    json.dumps(arr, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                return
        except Exception:
            pass

    out = [g.get("th", "") for g in groups]  # fallback: cue-level MT text
    if key:
        batches = [(off, items[off:off + a.batch])
                   for off in range(0, len(items), a.batch)]

        def work(bt):
            off, chunk = bt
            return off, translate_group_batch(chunk, lang_name, models, key)

        if a.jobs > 1 and len(batches) > 1:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=a.jobs) as ex:
                results = list(ex.map(work, batches))
        else:
            results = [work(b) for b in batches]
        failed = 0
        for off, arr in results:
            if arr is None:
                failed += 1
                continue
            for j, t in enumerate(arr):
                out[off + j] = t
            print(f"  [groups] {min(off + a.batch, len(items))}/{len(items)}",
                  file=sys.stderr)
        if failed:
            print(f"warn: {failed}/{len(batches)} group batches failed on "
                  f"all models — those groups keep cue-level MT text",
                  file=sys.stderr)
    else:
        print("warn: GEMINI_API_KEY not set — emitting cue-level MT text",
              file=sys.stderr)
    Path(a.dst).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    if key and not cache.exists():
        try:
            GROUP_CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        except Exception as e:
            print(f"warn: group cache write failed ({e})", file=sys.stderr)
    print(f"wrote {a.dst} ({len(out)} groups, lang={a.target})",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--target", default="th",
                    help="single target lang (legacy; --langs overrides)")
    ap.add_argument("--langs", default=None,
                    help="comma list, e.g. 'en,th' -> orig+EN+TH lines")
    ap.add_argument("--batch", type=int, default=100,
                    help="cues per call (or groups per call with --groups)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="concurrent translation batches across all langs")
    ap.add_argument("--groups", action="store_true",
                    help="src is a yt-vtt-dub.py --dump-groups table; dst "
                         "is a JSON array of per-group translations "
                         "(the --th-file format)")
    a = ap.parse_args()

    if a.groups:
        if a.batch == 100:
            a.batch = 20  # group texts are longer than cue lines
        groups_mode(a)
        return

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set")
    langs = ([l.strip() for l in a.langs.split(",") if l.strip()]
             if a.langs else [a.target])
    models = ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL")
              else pick_models(key))

    cues = parse_vtt(a.src)
    if not cues:
        sys.exit(f"no cues parsed from {a.src}")
    print(f"{len(cues)} cues, models[:3]={models[:3]}, langs={langs}",
          file=sys.stderr)

    tasks = []  # (lang_idx, off, chunk, lang_name)
    for li, lang in enumerate(langs):
        lang_name = LANGS.get(lang.lower(), lang)
        for off in range(0, len(cues), a.batch):
            tasks.append((li, off,
                          [c[2] for c in cues[off:off + a.batch]], lang_name))

    def work(t):
        li, off, chunk, lang_name = t
        return li, off, translate_batch(chunk, lang_name, models, key)

    if a.jobs > 1 and len(tasks) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as ex:
            results = list(ex.map(work, tasks))
    else:
        results = [work(t) for t in tasks]

    for li, off, trans in results:
        idx = 3 + li
        for c, t in zip(cues[off:off + a.batch], trans):
            while len(c) <= idx:
                c.append(None)
            c[idx] = t
        print(f"  [{langs[li]}] {min(off + a.batch, len(cues))}/{len(cues)}",
              file=sys.stderr)

    with open(a.dst, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for c in cues:
            lines = [c[2]] + [t for t in c[3:] if t]
            f.write(f"{c[0]} --> {c[1]}\n" + "\n".join(lines) + "\n\n")
    print(f"wrote {a.dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
