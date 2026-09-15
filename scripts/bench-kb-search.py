#!/usr/bin/env python3
"""Run NotebookLM vs MDDB KB search benchmark."""
import json
import subprocess
import time
import yaml
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

NOTEBOOK_ID = "fdfd3483-6b7e-4cb0-85f3-7f060698769c"
MDDB_URL = "http://127.0.0.1:11023/v1/search"
MDDB_COLLECTION = "infrastructure-ssot"
OUT = Path("/home/tony/CascadeProjects/chaba/docs/kb/experiments/notebooklm-kb-search-benchmark-2026-09-15.yml")
QUESTIONS = [
    "What is the Tailscale IP of tony-dell?",
    "How do I restart the NotebookLM REST auth refresh?",
    "Where does Caddy serve the public apps from on tony-dell?",
    "What is the nlm-add workflow for adding SSOT sources to NotebookLM?",
    "How do I fix devin-desktop after a crash on tony-dell?",
    "Which Home Assistant token file should I use for michael-ha?",
    "How do I deploy a new card bundle to michael-dev?",
    "How do I add a new app to the public apps page on tony-dell?",
]


def run_mddb(question):
    start = time.time()
    try:
        payload = json.dumps({
            "collection": MDDB_COLLECTION,
            "query": question,
            "limit": 3,
        })
        out = subprocess.run(
            ["curl", "-sS", "-X", "POST", MDDB_URL, "-H", "Content-Type: application/json", "-d", payload],
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(out.stdout)
        hits = [
            {
                "key": item.get("key"),
                "title": item.get("meta", {}).get("title", [None])[0],
                "original_path": item.get("meta", {}).get("original_path", [None])[0],
            }
            for item in data
        ]
        return {
            "question": question,
            "tool": "mddb",
            "elapsed": round(time.time() - start, 2),
            "top_hits": hits,
            "error": None,
        }
    except Exception as e:
        return {"question": question, "tool": "mddb", "elapsed": round(time.time() - start, 2), "error": str(e)}


def run_nlm(question):
    start = time.time()
    try:
        out = subprocess.run(
            ["nlm", "query", "notebook", NOTEBOOK_ID, question, "--timeout", "120"],
            capture_output=True,
            text=True,
            timeout=150,
        )
        return {
            "question": question,
            "tool": "notebooklm",
            "elapsed": round(time.time() - start, 2),
            "answer": out.stdout,
            "error": out.stderr if out.returncode != 0 else None,
        }
    except Exception as e:
        return {"question": question, "tool": "notebooklm", "elapsed": round(time.time() - start, 2), "error": str(e)}


def main():
    print("Running MDDB baseline...")
    mddb_results = list(map(run_mddb, QUESTIONS))

    print("Running NotebookLM queries (4 in parallel)...")
    nlm_results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        nlm_results = list(ex.map(run_nlm, QUESTIONS))

    report = {
        "title": "NotebookLM vs MDDB KB search benchmark",
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "notebook_id": NOTEBOOK_ID,
        "mddb_collection": MDDB_COLLECTION,
        "questions": QUESTIONS,
        "mddb_results": mddb_results,
        "notebooklm_results": nlm_results,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        yaml.safe_dump(report, f, sort_keys=False, allow_unicode=True)
    print(f"Report written to {OUT}")


if __name__ == "__main__":
    main()
