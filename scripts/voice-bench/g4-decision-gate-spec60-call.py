#!/usr/bin/env python3
"""One batched gemini-decision-1 noul call over the fresh brief+spec set.

Reads a free-tier key from GEMINI_API_KEY_FRESH (fallback GEMINI_API_KEY_MICHAEL)
from the environment; never prints or stores the value. Writes the parsed
response or error body to results/g4-decision-gate-spec60-response.json.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
payload = json.load(open(RESULTS / "g4-decision-gate-spec60-payload.json"))
key = (os.environ.get("GEMINI_API_KEY_FRESH") or
       os.environ.get("GEMINI_API_KEY_MICHAEL") or "").strip()
if not key:
    raise SystemExit("no free-tier Decisions key in environment")
data = json.dumps(payload).encode()
url = "https://generativelanguage.googleapis.com/v1beta/decisions"


def post(header):
    headers = {"Content-Type": "application/json"}
    target = url
    if header:
        headers["X-Goog-Api-Key"] = key
    else:
        target += "?key=" + key
    req = urllib.request.Request(target, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 0, json.dumps({"error": {"message": str(e.reason)}}).encode()


status, body = post(True)
if status == 400 and b"API_KEY_INVALID" in body:
    status, body = post(False)
try:
    parsed = json.loads(body)
except ValueError:
    parsed = {"raw_text": body.decode(errors="replace")}
json.dump(parsed, open(RESULTS / "g4-decision-gate-spec60-response.json", "w"), indent=2)
if status == 200 and "answers" in parsed:
    print("status", status, "answers", len(parsed["answers"]), "usage", parsed.get("usage"))
else:
    print("status", status, "error", json.dumps(parsed)[:400])
    sys.exit(1)
