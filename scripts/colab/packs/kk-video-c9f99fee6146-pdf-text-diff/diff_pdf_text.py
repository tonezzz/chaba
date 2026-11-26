#!/usr/bin/env python3
"""Create a private, deterministic text diff between two project PDFs."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path


FILES = ("OST_-.pdf", "OST_-_v1_01.pdf")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    return [re.sub(r"[ \t]+", " ", line).strip()
            for line in text.splitlines()]


def run_text(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} failed rc={result.returncode}: "
            f"{result.stderr[-300:]}")
    return result.stdout


def page_count(pdf: Path) -> int:
    info = run_text(["pdfinfo", str(pdf)])
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", info)
    if not match:
        raise ValueError(f"pdfinfo did not report pages for {pdf.name}")
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.project.read_text(encoding="utf-8"))
    if manifest.get("project_id") != "kk-video-c9f99fee6146":
        raise ValueError("unexpected project_id")
    if (manifest.get("source") or {}).get("filename") != FILES[1]:
        raise ValueError("project primary source is not v1_01")
    sources = {s.get("filename"): s for s in manifest.get("sources", [])}
    if any(name not in sources for name in FILES):
        raise ValueError("manifest must preserve both PDF revisions")

    texts = []
    metadata = []
    for filename in FILES:
        pdf = args.source_dir / filename
        if not pdf.is_file():
            raise FileNotFoundError(filename)
        actual_hash = file_sha256(pdf)
        source = sources[filename]
        if actual_hash != source.get("sha256"):
            raise ValueError(f"{filename} hash mismatch")
        raw = run_text(["pdftotext", "-layout", "-nopgbrk", str(pdf), "-"])
        lines = normalize_text(raw)
        metadata.append({
            "filename": filename,
            "sha256": actual_hash,
            "bytes": pdf.stat().st_size,
            "pdf_pages": page_count(pdf),
            "extracted_lines": len(lines),
            "normalized_characters": sum(len(line) for line in lines),
        })
        texts.append(lines)

    original, revised = texts
    diff_lines = list(difflib.unified_diff(
        original,
        revised,
        fromfile=FILES[0],
        tofile=FILES[1],
        n=3,
        lineterm="",
    ))
    additions = sum(line.startswith("+") and not line.startswith("+++")
                    for line in diff_lines)
    deletions = sum(line.startswith("-") and not line.startswith("---")
                    for line in diff_lines)
    summary = {
        "schema": 1,
        "project_id": manifest["project_id"],
        "primary_source": FILES[1],
        "method": "pdftotext -layout -nopgbrk; whitespace-normalized line diff",
        "raw_text_location": "not retained; only the private diff is stored",
        "added_lines": additions,
        "removed_lines": deletions,
        "diff_lines": len(diff_lines),
        "sources": metadata,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "text-diff.patch").write_text(
        "\n".join(diff_lines) + ("\n" if diff_lines else ""),
        encoding="utf-8")
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    (args.out / "summary.md").write_text(
        "\n".join([
            "# Sacred Father PDF text comparison",
            "",
            "Private deterministic diff; no model was used and source text "
            "was not retained separately.",
            "",
            f"- Original: {metadata[0]['pdf_pages']} pages, "
            f"{metadata[0]['normalized_characters']} normalized characters.",
            f"- v1_01 primary: {metadata[1]['pdf_pages']} pages, "
            f"{metadata[1]['normalized_characters']} normalized characters.",
            f"- Changed lines: +{additions} / -{deletions}.",
            "- Full line diff: `text-diff.patch` (private Drive artifact).",
            "",
        ]),
        encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "added_lines": additions,
        "removed_lines": deletions,
        "diff_lines": len(diff_lines),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
