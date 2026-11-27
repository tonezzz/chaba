#!/usr/bin/env python3
"""One batched gemini-decision-1 call for the diverse 60-brief third gate set.

Reads GEMINI_API_KEY_MICHAEL from the environment (never printed or stored),
POSTs the prebuilt payload, and writes the raw response (or error body) to
results/g4-decision-gate-diverse60-response.json. No other services touched.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
payload = json.load(open(RESULTS / "g4-decision-gate-diverse60-payload.json"))
key = (os.environ.get("GEMINI_API_KEY_FRESH") or
       os.environ["GEMINI_API_KEY_MICHAEL"]).strip()
data = json.dumps(payload).encode()
url = "https://generativelanguage.googleapis.com/v1beta/decisions"


def post(use_query):
    target = url + "?key=" + key if use_query else url
    headers = {"Content-Type": "application/json"}
    if not use_query:
        headers["X-Goog-Api-Key"] = key
    req = urllib.request.Request(target, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return 0, json.dumps({"error": {"message": str(e.reason)}}).encode()


status, body = post(False)
if status == 400 and b"API_KEY_INVALID" in body:
    status, body = post(True)  # some projects only accept the query parameter

try:
    parsed = json.loads(body)
except ValueError:
    parsed = {"raw_text": body.decode(errors="replace")}
json.dump(parsed, open(RESULTS / "g4-decision-gate-diverse60-response.json", "w"), indent=2)
if status == 200 and "answers" in parsed:
    print("status", status, "answers", len(parsed["answers"]), "usage", parsed.get("usage"))
else:
    print("status", status, "error", json.dumps(parsed)[:400])
    sys.exit(1)
