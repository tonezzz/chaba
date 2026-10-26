"""Drop gate for chat-send-page-images (card chat-send-page-images,
ADA-0511) staged under integrations/ada-voice/.

The card: Kaewta's photo-ask path was nondeterministic — cms_read +
image_url + deliver sometimes invented URLs (surf-thailand.com/kk/…,
unsplash → all 404) or produced text-only phantom sends. The drop adds
page=<slug> to chat_send: the background job cms_get_page's the doc,
extracts every embedded image (markdown ![..](..) + <img src>,
site-relative resolved vs LINE_URL_BASE), and posts one
image_urls=[...] batch to the relay /send — which sends each asset as
its own bubble, chunks past the 5-bubble LINE push cap, and reports
per-URL status so the summary note stays honest.

Chaba-side coverage (the ada-voice-side suite is
tests/test_chat_send_page.py in the drop — extraction, the page job,
the relay batch, the tg batch):

- every patch in the drop resolves against a live ada-voice checkout
  (ADA_PI env or ~/CascadeProjects/ada-voice): applies while pending,
  or merged/diverged -> the live file is tested
  (tests/ada/_drops.py);
- patched files compile;
- the shipped ada-voice test file exists and compiles;
- the patch surface really introduces the contract (page= param,
  image_urls payload field, per-URL images report).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects/ada-voice")))

PATCHES = [
    DROP / "backend/tool_runner.page-images.patch",
    DROP / "backend/line_relay.page-images.patch",
    DROP / "backend/tg_relay.page-images.patch",
    DROP / "backend/realtime_provider.page-images.patch",
    DROP / "backend/tool_guide.page-images.patch",
]
NEW_FILES = [DROP / "tests/test_chat_send_page.py"]

NEEDS_ADA_PI = pytest.mark.skipif(
    not (ADA_PI / "backend/line_relay.py").is_file(),
    reason="no ada-voice checkout to apply the patch against")


def _clean_checkout(tmp_path: Path) -> Path:
    """Copy ada-voice into tmp so patches apply without touching the
    real checkout."""
    src = tmp_path / "ada-voice"
    for rel in ("backend", "tests"):
        shutil.copytree(ADA_PI / rel, src / rel,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for f in ADA_PI.iterdir():
        if f.is_file():
            shutil.copy2(f, src / f.name)
    return src


@NEEDS_ADA_PI
class TestPatchApplies:
    def test_patches_apply_or_landed(self, tmp_path):
        """Tri-state per patch: applies (drop pending), merged (already
        upstream), diverged. Divergence fails only when NOTHING in the
        drop merged — a pending drop whose base rotted."""
        src = _clean_checkout(tmp_path)
        states = {p.name: check_patch(p, src) for p in PATCHES}
        assert drop_guard_ok(states.values()), (
            f"drop rotted on its base — re-dispatch: {states}")

    def test_applied_files_compile(self, tmp_path):
        src = _clean_checkout(tmp_path)
        for p in PATCHES:
            apply_patch(p, src)
        for f in NEW_FILES:  # install step copies new files verbatim
            (src / "tests" / f.name).write_bytes(f.read_bytes())
        for rel in ("backend/tool_runner/chat.py",
                    "backend/line_relay.py",
                    "backend/tg_relay.py",
                    "backend/realtime_provider.py",
                    "tests/test_chat_send_page.py"):
            f = src / rel
            compile(f.read_text(), str(f), "exec")
        # the guide is yaml — a broken hunk would corrupt the tool
        # surface the personas read.
        import yaml
        yaml.safe_load((src / "backend/tool_guide.yml").read_text())


class TestDropSurface:
    """The staged files carry the contract the card asked for —
    guardable without an ada-voice checkout."""

    def test_patch_files_exist(self):
        for p in PATCHES + NEW_FILES:
            assert p.is_file(), p

    def test_runner_patch_adds_page_param_and_batch(self):
        body = (PATCHES[0]).read_text()
        assert 'page: str = ""' in body
        assert "_chat_send_page_run" in body
        assert '"image_urls": urls' in body
        assert "_page_image_urls" in body
        assert "LINE_URL_BASE" in body

    def test_relay_patch_adds_batch_and_per_url_report(self):
        body = (PATCHES[1]).read_text()
        assert "image_urls" in body
        assert "images" in body           # response report
        assert "msgs[i:i + 5]" in body    # chunked pushes, no trunc
        assert "fetch-failed" in body

    def test_provider_declares_page_param(self):
        body = (PATCHES[3]).read_text()
        assert '"page": {' in body

    def test_guide_documents_page(self):
        body = (PATCHES[4]).read_text()
        assert "page='<cms slug>'" in body

    def test_new_test_file_compiles(self):
        for f in NEW_FILES:
            compile(f.read_text(), str(f), "exec")
