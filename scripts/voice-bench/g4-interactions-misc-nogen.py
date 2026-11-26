#!/usr/bin/env python3
"""No-generation-quota checks: countTokens, Files API, model info, raw statuses.

Env: GEMINI_API_KEY, MODEL, OUT. No key value is written to output.
"""
import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone

from google import genai

MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")
KEY = os.environ["GEMINI_API_KEY"]
OUT = os.environ.get("OUT", "/tmp/opencode/g4-interactions-misc-nogen.json")
results = {}


def record(name, fn):
    t0 = time.monotonic()
    try:
        out = fn() or {}
        results[name] = {"ok": True, "elapsed_s": round(time.monotonic() - t0, 2), **out}
    except Exception as e:
        results[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "elapsed_s": round(time.monotonic() - t0, 2),
        }
    r = results[name]
    print(name, "OK" if r["ok"] else "FAIL", str(r.get("error", ""))[:180], flush=True)


def rest_post(path, body):
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/{path}",
        data=json.dumps(body).encode(),
        headers={"x-goog-api-key": KEY, "Content-Type": "application/json",
                 "Api-Revision": "2026-05-20"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


PROMPT = "The quick brown fox jumps over the lazy dog. Reply with exactly: OK"


def token_count_text():
    code, payload = rest_post(f"models/{MODEL}:countTokens", {
        "contents": [{"parts": [{"text": PROMPT}]}]
    })
    return {"http": code, "prompt_chars": len(PROMPT), "payload": payload}


def png_bytes(width, height, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


IMG = png_bytes(64, 64, (220, 30, 30))
IMG_PATH = "/tmp/opencode/g4-test-red.png"
with open(IMG_PATH, "wb") as f:
    f.write(IMG)
IMG_B64 = base64.b64encode(IMG).decode("ascii")


def token_count_image():
    attempts = {}
    for label, part in (
        ("camel_inlineData", {"inlineData": {"mimeType": "image/png", "data": IMG_B64}}),
        ("snake_inline_data", {"inline_data": {"mime_type": "image/png", "data": IMG_B64}}),
    ):
        code, payload = rest_post(f"models/{MODEL}:countTokens", {
            "contents": [{"parts": [{"text": "What color is this image?"}, part]}]
        })
        attempts[label] = {"http": code, "payload": payload}
    return {"png_bytes": len(IMG), "attempts": attempts}


def model_info():
    client = genai.Client(api_key=KEY)
    info = client.models.get(model=MODEL)
    return {
        "input_token_limit": getattr(info, "input_token_limit", None),
        "output_token_limit": getattr(info, "output_token_limit", None),
        "name": getattr(info, "name", None),
    }


def files_api():
    client = genai.Client(api_key=KEY)
    up = client.files.upload(file=IMG_PATH)
    name, uri, mime = getattr(up, "name", None), getattr(up, "uri", None), getattr(up, "mime_type", None)
    got = client.files.get(name=name)
    names = []
    for f in client.files.list():
        names.append(getattr(f, "name", None))
        if len(names) >= 3:
            break
    deleted = "not attempted"
    try:
        client.files.delete(name=name)
        deleted = "ok"
    except Exception as e:
        deleted = f"{type(e).__name__}: {str(e)[:120]}"
    return {
        "uploaded_name": name, "uploaded_uri": uri, "uploaded_mime": mime,
        "get_name": getattr(got, "name", None),
        "list_names": names, "delete": deleted,
    }


def raw_statuses():
    out = {}
    code, payload = rest_post("interactions", {
        "model": MODEL, "input": "Reply with exactly: OK"
    })
    out["interactions"] = {"http": code, "message": (payload.get("error") or {}).get("message", "")[:300]}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        data=json.dumps({"model": MODEL, "messages": [{"role": "user", "content": "Say OK"}]}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            out["openai_compat"] = {"http": resp.status, "model_echo": json.loads(resp.read().decode()).get("model")}
    except urllib.error.HTTPError as e:
        out["openai_compat"] = {"http": e.code, "message": e.read().decode()[:300]}
    return out


def main():
    print("start", MODEL, flush=True)
    record("token_count_text", token_count_text)
    record("token_count_image", token_count_image)
    record("model_info", model_info)
    record("files_api", files_api)
    record("raw_statuses", raw_statuses)
    out = {"schema": "g4-interactions-misc-nogen", "schema_version": 1,
           "date": datetime.now(timezone.utc).isoformat(), "host": "idc03",
           "model": MODEL, "key_printed": False, "complete": True, "results": results}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
