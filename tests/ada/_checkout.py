"""Shared scratch ada-voice trees for tests/ada/*.

`git clone --depth 1` of the ada-voice checkout cost ~65-86MB per test
(.git objects + pwa wasm vendor + tests/voice-corpus audio) and the
suite runs ~8 of them — ~680MB of tmpfs churn per run (ADA-0171,
found during the OPS-0128 /tmp quota investigation). `git archive HEAD`
materializes the same tracked tree a clone would check out, minus .git,
pwa/, tests/voice-corpus and __pycache__ — identical content for
check_patch/apply_patch and module loads at ~18MB per tree. No .git is
needed: git apply works on plain working files (verified 2026-11-17).
"""
from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

# tracked paths excluded from the scratch tree — none are referenced by
# integrations/ada-voice patches or imported by the modules under test.
_EXCLUDES = (
    ":(exclude)pwa",
    ":(exclude)tests/voice-corpus",
    ":(exclude)**/__pycache__",
)


def materialize_head(dst: Path, ada_pi: Path) -> Path:
    """Extract ada_pi's HEAD tree into dst (no .git). Content-equivalent
    to `git clone --depth 1` checkout of the same commit."""
    dst.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "-C", str(ada_pi), "archive", "--format=tar", "HEAD",
         "--", ".", *_EXCLUDES],
        check=True, capture_output=True, timeout=120)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tf:
        tf.extractall(dst, filter="data")
    return dst
