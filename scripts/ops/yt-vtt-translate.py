#!/usr/bin/env python3
"""yt-vtt-translate.py — translate a WebVTT file via Gemini and emit a merged
dual-language VTT (original line(s) + translated line(s) per cue).

Usage: yt-vtt-translate.py IN.vtt OUT.vtt [--target th] [--batch 40]
Env:    GEMINI_API_KEY (required), GEMINI_MODEL (optional override)
"""
import argparse
import concurrent.futures
import html
import json
import os
import re
import sys
import time
import urllib.request

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--target", default="th",
                    help="single target lang (legacy; --langs overrides)")
    ap.add_argument("--langs", default=None,
                    help="comma list, e.g. 'en,th' -> orig+EN+TH lines")
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=1,
                    help="concurrent translation batches across all langs")
    a = ap.parse_args()

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
