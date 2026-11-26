#!/usr/bin/env python3
"""Inventory embedded PDF images without using them in generated media."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


IMAGE_TYPES = {"image", "mask", "smask", "stencil"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pdf_pages(pdfinfo: str) -> int:
    match = re.search(r"(?m)^Pages:\s*(\d+)\s*$", pdfinfo)
    if not match:
        raise ValueError("pdfinfo output did not include a page count")
    return int(match.group(1))


def parse_image_rows(listing: str) -> list[dict]:
    rows = []
    for line in listing.splitlines():
        columns = line.split()
        if len(columns) < 5 or not columns[0].isdigit():
            continue
        if columns[2] not in IMAGE_TYPES:
            continue
        try:
            row = {
                "page": int(columns[0]),
                "index": int(columns[1]),
                "type": columns[2],
                "width": int(columns[3]),
                "height": int(columns[4]),
            }
        except ValueError:
            continue
        if len(columns) > 5:
            row["color"] = columns[5]
        if len(columns) > 6:
            row["components"] = columns[6]
        if len(columns) > 7:
            row["bits_per_component"] = columns[7]
        if len(columns) > 8:
            row["encoding"] = columns[8]
        if len(columns) > 9:
            row["interpolate"] = columns[9]
        rows.append(row)
    return rows


def text_page_fingerprints(text: str, page_count: int) -> list[dict]:
    pages = text.split("\f")
    while len(pages) > page_count and not pages[-1].strip():
        pages.pop()
    pages = (pages + [""] * page_count)[:page_count]
    result = []
    for number, page in enumerate(pages, 1):
        normalized = re.sub(r"\s+", " ", page).strip()
        result.append({
            "page": number,
            "chars": len(normalized),
            "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        })
    return result


def run_text(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} failed rc={result.returncode}: "
            f"{result.stderr[-300:]}")
    return result.stdout


def audit_one(label: str, source: dict, source_dir: Path,
              out_dir: Path) -> dict:
    filename = str(source["filename"])
    pdf = source_dir / filename
    if not pdf.is_file():
        raise FileNotFoundError(f"missing source file: {filename}")

    actual_hash = sha256(pdf)
    expected_hash = str(source.get("sha256", ""))
    if actual_hash != expected_hash:
        raise ValueError(f"{filename} hash mismatch")
    expected_size = source.get("bytes")
    if expected_size is not None and pdf.stat().st_size != int(expected_size):
        raise ValueError(f"{filename} size mismatch")

    info = run_text(["pdfinfo", str(pdf)])
    pages = parse_pdf_pages(info)
    text_pages = text_page_fingerprints(
        run_text(["pdftotext", "-layout", str(pdf), "-"]), pages)
    page_size = re.search(r"(?m)^Page size:\s*(.+)$", info)
    listing = run_text(["pdfimages", "-list", str(pdf)])

    target = out_dir / label
    images_dir = target / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    # Keep document metadata (author/title/producer) out of the audit artifact.
    (target / "pdfinfo-summary.txt").write_text(
        f"pages: {pages}\n"
        f"page_size: {page_size.group(1) if page_size else 'unknown'}\n",
        encoding="utf-8")
    (target / "pdfimages-list.txt").write_text(listing, encoding="utf-8")
    rows = parse_image_rows(listing)
    extracted_prefix = images_dir / "image"
    run_text(["pdfimages", "-all", str(pdf), str(extracted_prefix)])
    extracted = sorted(p for p in images_dir.iterdir() if p.is_file())
    image_files = extracted
    if not extracted:
        marker = images_dir / "NO_EMBEDDED_IMAGES.txt"
        marker.write_text("No embedded image objects were extracted.\n",
                          encoding="utf-8")
        extracted = [marker]

    per_page = {}
    for row in rows:
        per_page[row["page"]] = per_page.get(row["page"], 0) + 1
    return {
        "label": label,
        "filename": filename,
        "sha256": actual_hash,
        "bytes": pdf.stat().st_size,
        "pages": pages,
        "text_pages": text_pages,
        "embedded_image_objects": len(rows),
        "extracted_image_files": len(image_files),
        "image_objects_by_page": per_page,
        "image_rows": rows,
        "extracted_files": [
            {
                "path": str(p.relative_to(out_dir)),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
            for p in extracted
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.project.read_text(encoding="utf-8"))
    if manifest.get("project_id") != "kk-video-c9f99fee6146":
        raise ValueError("unexpected project_id")
    revisions = manifest.get("sources") or [manifest.get("source") or {}]
    labels = {
        "OST_-.pdf": "original",
        "OST_-_v1_01.pdf": "v1_01",
    }
    selected = [s for s in revisions if s.get("filename") in labels]
    if set(s.get("filename") for s in selected) != set(labels):
        raise ValueError("manifest must retain both original and v1_01 sources")
    if (manifest.get("source") or {}).get("filename") != "OST_-_v1_01.pdf":
        raise ValueError("project primary source is not v1_01")

    args.out.mkdir(parents=True, exist_ok=True)
    reports = [
        audit_one(labels[str(source["filename"])], source,
                  args.source_dir, args.out)
        for source in selected
    ]
    by_label = {report["label"]: report for report in reports}
    original_text = {
        p["page"]: p["sha256"]
        for p in by_label["original"]["text_pages"]
    }
    revised_text = {
        p["page"]: p["sha256"]
        for p in by_label["v1_01"]["text_pages"]
    }
    shared_pages = sorted(set(original_text) & set(revised_text))
    changed_text_pages = [
        page for page in shared_pages
        if original_text[page] != revised_text[page]
    ]
    text_delta = {
        "changed_pages": changed_text_pages,
        "added_pages": sorted(set(revised_text) - set(original_text)),
        "removed_pages": sorted(set(original_text) - set(revised_text)),
    }
    summary = {
        "schema": 1,
        "project_id": manifest["project_id"],
        "primary_source": manifest["source"]["filename"],
        "image_use": "inventory only; no image was passed to a renderer",
        "sources": reports,
        "text_delta": text_delta,
    }
    (args.out / "audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    lines = [
        "# Sacred Father PDF image audit",
        "",
        "Private source inventory only; extracted images were not fed into LTX.",
        "",
        "| Revision | PDF | Pages | Embedded image objects | Extracted files | SHA-256 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for report in reports:
        lines.append(
            f"| {report['label']} | {report['filename']} | {report['pages']} "
            f"| {report['embedded_image_objects']} | "
            f"{report['extracted_image_files']} | `{report['sha256']}` |")
    lines += ["", "## Per-page image-object counts", ""]
    for report in reports:
        counts = report["image_objects_by_page"]
        lines.append(f"### {report['label']}")
        lines.append(
            ", ".join(f"p{page}:{count}" for page, count in sorted(counts.items()))
            or "No embedded image objects found.")
        lines.append("")
    lines += [
        "## Text-change fingerprint",
        "",
        "Only normalized per-page character counts and SHA-256 fingerprints "
        "are stored; extracted source text is not retained.",
        "",
        f"- Changed page fingerprints: {text_delta['changed_pages'] or 'none'}",
        f"- Added pages: {text_delta['added_pages'] or 'none'}",
        f"- Removed pages: {text_delta['removed_pages'] or 'none'}",
        "",
    ]
    (args.out / "report.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "sources": [
            {
                "label": r["label"],
                "pages": r["pages"],
                "images": r["embedded_image_objects"],
                "files": len(r["extracted_files"]),
            }
            for r in reports
        ],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
