#!/usr/bin/env python3
"""nlm_batch — one-shot NotebookLM batch task for the DevNest nlm_batch lane.

OPS-1048 spike verdict 3: Google AI Pro raises NotebookLM to 500 notebooks /
300 sources-per-notebook / 500 chats-day / 20 audio-overviews-day — a real
free batch lane for edu dossiers, report research, transcript digestion.

Runs `nlm` (installed + authed at ~/.local/bin/nlm, profile ~/.notebooklm).
Creates or reuses a notebook, optionally adds one source (text/file/url),
runs one query, writes the answer to --out. Exit 0 = artifact produced.

Usage:
  nlm_batch.py --prompt-file F --out result.md [--notebook ID]
               [--title T] [--query Q]
               [--source-file F | --source-text T | --source-url U]
               [--keep-notebook]
"""
import argparse, json, os, re, shlex, subprocess, sys, uuid
from pathlib import Path

NLM = os.environ.get("NLM_BIN", str(Path.home() / ".local/bin/nlm"))


def nlm(*args, timeout=600):
    r = subprocess.run([NLM, *args], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"nlm {' '.join(args[:2])} failed rc={r.returncode}: "
                 f"{(r.stderr or r.stdout)[:400]}")
    return r.stdout.strip()


def find_nb_id(out: str) -> str:
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                  r"-[0-9a-f]{12}", out)
    if not m:
        sys.exit(f"no notebook id in output: {out[:200]}")
    return m.group(0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt-file")
    p.add_argument("--out", required=True)
    p.add_argument("--notebook")
    p.add_argument("--title", default="")
    p.add_argument("--query")
    p.add_argument("--source-file")
    p.add_argument("--source-text")
    p.add_argument("--source-url")
    p.add_argument("--keep-notebook", action="store_true")
    a = p.parse_args()

    if not Path(NLM).is_file():
        sys.exit(f"nlm not installed at {NLM}")

    prompt = (Path(a.prompt_file).read_text() if a.prompt_file
              else "").strip()
    query = (a.query or "").strip() or prompt
    if not query:
        sys.exit("no query (need --query or --prompt-file)")

    nb = a.notebook
    if not nb:
        title = (a.title or f"devnest-{uuid.uuid4().hex[:8]}")[:80]
        nb = find_nb_id(nlm("notebook", "create", title))
        print(f"notebook: {nb} ({title})")

    if a.source_file:
        print(nlm("source", "add", nb, "--file", a.source_file, "--wait"))
    elif a.source_url:
        print(nlm("source", "add", nb, "--url", a.source_url, "--wait"))
    elif a.source_text or (prompt and not a.notebook):
        st = a.source_text or prompt
        if Path(st).is_file() and len(st) < 200:
            st = Path(st).read_text()[:50000]
        print(nlm("source", "add", nb, "--text", st[:50000],
                  "--title", (a.title or "input")[:80], "--wait"))

    answer = nlm("notebook", "query", nb, query, timeout=900)
    Path(a.out).write_text(
        f"# {a.title or 'nlm batch'}\n\n"
        f"notebook: {nb}\n\n{answer}\n")
    print(f"artifact: {a.out}")

    if not a.keep_notebook and not a.notebook:
        try:
            nlm("notebook", "delete", nb, "--confirm", "--json", timeout=60)
            print(f"notebook {nb} deleted")
        except SystemExit:
            print(f"notebook {nb} delete failed — left behind")


if __name__ == "__main__":
    main()
