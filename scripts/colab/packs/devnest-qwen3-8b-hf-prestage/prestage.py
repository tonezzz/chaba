#!/usr/bin/env python3
"""Fetch a pinned public Qwen3 snapshot for later offline Colab inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

import zstandard
from huggingface_hub import snapshot_download

REPO_ID = "Qwen/Qwen3-8B"
REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
ALLOW_PATTERNS = [
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "model-*.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "merges.txt",
    "vocab.json",
    "LICENSE",
]
REQUIRED = [
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
    "model-00001-of-00005.safetensors",
    "model-00002-of-00005.safetensors",
    "model-00003-of-00005.safetensors",
    "model-00004-of-00005.safetensors",
    "model-00005-of-00005.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "merges.txt",
    "vocab.json",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    model_dir = out_dir / "model"
    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=str(model_dir),
        allow_patterns=ALLOW_PATTERNS,
    )
    files = {}
    for name in REQUIRED:
        path = model_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"required model file missing: {name}")
        files[name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    manifest = {
        "schema": 1,
        "repo_id": REPO_ID,
        "revision": REVISION,
        "license": "apache-2.0",
        "quantization": "runtime bitsandbytes NF4 4-bit on Colab",
        "files": files,
        "total_bytes": sum(item["bytes"] for item in files.values()),
    }
    archive = out_dir / "qwen3-8b-hf-cache.tar.zst"
    temporary = archive.with_suffix(archive.suffix + ".incomplete")
    compressor = zstandard.ZstdCompressor(level=3)
    with temporary.open("wb") as raw:
        with compressor.stream_writer(raw, closefd=False) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for name in REQUIRED:
                    tar.add(str((model_dir / name).resolve()),
                            arcname=name, recursive=False)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("model archive is empty")
    temporary.replace(archive)
    (out_dir / "model-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    manifest = stage(args.out)
    print(json.dumps({
        "status": "staged",
        "repo_id": REPO_ID,
        "revision": REVISION,
        "files": len(manifest["files"]),
        "bytes": manifest["total_bytes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
