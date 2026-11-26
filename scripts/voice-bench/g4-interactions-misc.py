#!/usr/bin/env python3
"""Probe thought summaries, token counting, file input and OpenAI compat on free tier.

Read-only, synthetic media only. Env: GEMINI_API_KEY, MODEL, OUT.
"""
import base64
import json
import os
import signal
import struct
import time
import urllib.request
import zlib
from datetime import datetime, timezone

from google import genai
from openai import OpenAI

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
OUT = os.environ.get("OUT", "/tmp/opencode/g4-interactions-misc.json")
KEY = os.environ["GEMINI_API_KEY"]
client = genai.Client()
results = {}


class CallTimeout(Exception):
    pass


def _alarm(_signum, _frame):
    raise CallTimeout("per-surface timeout (240s)")


signal.signal(signal.SIGALRM, _alarm)


def save_partial():
    with open(OUT, "w") as f:
        json.dump({
            "schema": "g4-interactions-misc",
            "schema_version": 1,
            "date": datetime.now(timezone.utc).isoformat(),
            "host": "idc03",
            "model": MODEL,
            "key_printed": False,
            "results": results,
            "complete": False,
        }, f, indent=2)


def dump(obj):
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    return str(obj)


def record(name, fn):
    t0 = time.monotonic()
    signal.alarm(240)
    try:
        out = fn() or {}
        results[name] = {"ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **out}
    except Exception as e:
        results[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:500]}",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    finally:
        signal.alarm(0)
        save_partial()
    r = results[name]
    print(name, "OK" if r["ok"] else "FAIL", str(r.get("error", ""))[:200], flush=True)


PUZZLE = (
    "Alice, Bob, and Carol each live in a different house on the same street: "
    "red, green, and blue. Alice does not live in the red house. "
    "Bob does not live in the green house. Carol does not live in the red or green house. "
    "Which house does each person live in?"
)


def thought_steps(r):
    thoughts = []
    for s in getattr(r, "steps", None) or []:
        if getattr(s, "type", None) == "thought":
            summary = getattr(s, "summary", None) or []
            text = "".join(
                getattr(b, "text", "") or ""
                for b in summary
                if getattr(b, "type", None) == "text"
            )
            sig = getattr(s, "signature", None)
            thoughts.append({
                "summary_chars": len(text),
                "summary": text[:400],
                "has_signature": bool(sig),
            })
    u = dump(getattr(r, "usage", None)) or {}
    return {
        "text": str(getattr(r, "output_text", None))[:300],
        "step_types": [getattr(s, "type", None) for s in (getattr(r, "steps", None) or [])],
        "thoughts": thoughts,
        "thought_tokens": u.get("total_thought_tokens"),
        "output_tokens": u.get("total_output_tokens"),
        "usage": u,
    }


def thought_default():
    r = client.interactions.create(
        model=MODEL, input=PUZZLE,
        generation_config={"thinking_summaries": "auto"})
    return thought_steps(r)


def thought_high():
    r = client.interactions.create(
        model=MODEL, input=PUZZLE,
        generation_config={"thinking_summaries": "auto", "thinking_level": "high"})
    return thought_steps(r)


def thought_stream():
    stream = client.interactions.create(
        model=MODEL, input=PUZZLE,
        generation_config={"thinking_summaries": "auto", "thinking_level": "high"},
        stream=True)
    deltas, summary, text, usage = {}, "", "", None
    for ev in stream:
        et = getattr(ev, "event_type", None)
        if et == "interaction.completed":
            usage = dump(getattr(getattr(ev, "interaction", None), "usage", None))
            continue
        if et != "step.delta":
            continue
        d = getattr(ev, "delta", None)
        dt = str(getattr(d, "type", None))
        deltas[dt] = deltas.get(dt, 0) + 1
        if dt == "thought_summary":
            content = getattr(d, "content", None)
            summary += getattr(content, "text", "") or ""
        elif dt == "text":
            text += getattr(d, "text", "") or ""
    return {
        "delta_types": deltas,
        "summary_chars": len(summary),
        "summary": summary[:400],
        "text": text[:300],
        "usage": usage,
    }


PROMPT = "The quick brown fox jumps over the lazy dog. Reply with exactly: OK"


def token_count():
    counted = client.models.count_tokens(model=MODEL, contents=PROMPT)
    r = client.interactions.create(model=MODEL, input=PROMPT)
    u = dump(getattr(r, "usage", None)) or {}
    info = client.models.get(model=MODEL)
    return {
        "prompt_chars": len(PROMPT),
        "count_tokens_result": dump(counted),
        "interaction_input_tokens": u.get("total_input_tokens"),
        "interaction_usage": u,
        "model_limits": {
            "input_token_limit": getattr(info, "input_token_limit", None),
            "output_token_limit": getattr(info, "output_token_limit", None),
        },
    }


def png_bytes(width, height, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


IMG = png_bytes(64, 64, (220, 30, 30))
IMG_B64 = base64.b64encode(IMG).decode("ascii")
IMG_PATH = "/tmp/opencode/g4-test-red.png"
with open(IMG_PATH, "wb") as f:
    f.write(IMG)


def inline_image():
    counted = client.models.count_tokens(
        model=MODEL,
        contents=["What color is this image? Reply one word.", IMG_B64],
    )
    r = client.interactions.create(
        model=MODEL,
        input=[
            {"type": "text", "text": "What color is this image? Reply one word."},
            {"type": "image", "data": IMG_B64, "mime_type": "image/png"},
        ],
    )
    u = dump(getattr(r, "usage", None)) or {}
    return {
        "png_bytes": len(IMG),
        "count_tokens_text_plus_image": dump(counted),
        "text": str(getattr(r, "output_text", None))[:200],
        "usage": u,
    }


def files_api():
    up = client.files.upload(file=IMG_PATH)
    name, uri, mime = getattr(up, "name", None), getattr(up, "uri", None), getattr(up, "mime_type", None)
    got = client.files.get(name=name)
    r = client.interactions.create(
        model=MODEL,
        input=[
            {"type": "text", "text": "What color is this image? Reply one word."},
            {"type": "image", "uri": uri, "mime_type": mime},
        ],
    )
    names = []
    try:
        for f in client.files.list():
            names.append(getattr(f, "name", None))
            if len(names) >= 3:
                break
    except Exception as e:
        names = [f"list_failed: {type(e).__name__}: {str(e)[:120]}"]
    deleted = "not attempted"
    try:
        client.files.delete(name=name)
        deleted = "ok"
    except Exception as e:
        deleted = f"{type(e).__name__}: {str(e)[:160]}"
    return {
        "uploaded_name": name,
        "uploaded_uri": uri,
        "uploaded_mime": mime,
        "get_name": getattr(got, "name", None),
        "get_state": dump(getattr(got, "state", None)),
        "list_names": names,
        "interaction_text": str(getattr(r, "output_text", None))[:200],
        "interaction_usage": dump(getattr(r, "usage", None)),
        "delete": deleted,
    }


def openai_sdk():
    oa = OpenAI(api_key=KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    r = oa.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": "Reply concisely."},
                  {"role": "user", "content": "Say exactly: OPENAIOK"}],
    )
    msg = r.choices[0].message
    chunks, stream_text = 0, ""
    for c in oa.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Count from 1 to 5, comma separated. Nothing else."}],
        stream=True,
    ):
        chunks += 1
        delta = c.choices[0].delta
        stream_text += delta.content or ""
    return {
        "model_echo": getattr(r, "model", None),
        "text": msg.content,
        "finish_reason": r.choices[0].finish_reason,
        "usage": dump(getattr(r, "usage", None)),
        "stream_chunks": chunks,
        "stream_text": stream_text[:200],
    }


def openai_rest():
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say exactly: RESTOK"}],
    }).encode()
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        payload = json.loads(resp.read().decode())
    choice = payload.get("choices", [{}])[0]
    return {
        "text": (choice.get("message") or {}).get("content"),
        "model_echo": payload.get("model"),
        "usage": payload.get("usage"),
        "finish_reason": choice.get("finish_reason"),
    }


def main():
    print("start", MODEL, flush=True)
    record("thought_summary_default", thought_default)
    record("thought_summary_high", thought_high)
    record("thought_summary_stream", thought_stream)
    record("token_count", token_count)
    record("inline_image", inline_image)
    record("files_api", files_api)
    record("openai_sdk", openai_sdk)
    record("openai_rest", openai_rest)
    out = {
        "schema": "g4-interactions-misc",
        "schema_version": 1,
        "date": datetime.now(timezone.utc).isoformat(),
        "host": "idc03",
        "model": MODEL,
        "key_printed": False,
        "complete": True,
        "results": results,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
