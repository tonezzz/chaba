"""Unit tests for the kk-ha degraded-mode drop staged under
integrations/ada-voice/ (card
kk-ha-degraded-mode-explain-capabilities-000d8b, 2026-11-24).

KK's lane burned its OpenRouter credit on 2026-10-14: every reply
transport failed and the lane answered with silence — the turn died as
response_interrupted with no words, and voice connects died on a bare
provider_cap error. The drop gives member lanes a defined degraded-mode
notice: backend/degraded_mode.py owns the sustained-outage classifier
(credits/quota/billing/gone-model — transient rate limits keep the old
interrupted path) plus the bilingual canned reply;
openrouter_provider emits the notice as a normal assistant reply when
EVERY text transport fails; pwa_server sends a 'degraded' frame on
billing-class connect holds; the ada-voice-card (patched in this repo —
all three www/ copies stay byte-identical) shows and speaks it.

Chaba-side coverage:

- degraded_mode.py is extracted from its new-file patch and exercised
  standalone — it is stdlib-only at import time (backend.* imports are
  lazy), so the classifier and both language templates run without an
  ada-voice checkout;
- every patch resolves against a live ada-voice checkout (ADA_PI env or
  ~/CascadeProjects/ada-voice): applies while pending, merged/diverged
  per tests/ada/_drops.py;
- the patched OpenRouterTextProvider._complete is driven end-to-end on
  a patched scratch tree: a credit-shaped total failure yields
  transcript deltas + response_completed carrying the notice, while a
  transient 429 still yields response_interrupted.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from tests.ada._checkout import materialize_head
from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
PATCH_NEW = DROP / "backend/degraded_mode.degraded-mode.patch"
PATCHES = [
    PATCH_NEW,
    DROP / "backend/openrouter_provider.degraded-mode.patch",
    DROP / "pwa_server.degraded-mode.patch",
]
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects" / "ada-voice")))

NEEDS_ADA_PI = pytest.mark.skipif(
    not (ADA_PI / "backend" / "openrouter_provider.py").is_file(),
    reason="no ada-voice checkout to apply the drop against")


# ------------------------------------------------------------- module under test

def _load_standalone(tmp_path: Path):
    """Extract backend/degraded_mode.py from its new-file patch and load
    it as a top-level module — stdlib-only at import time, so the
    classifier and notices run without the ada-voice tree."""
    body = "\n".join(
        line[1:] for line in PATCH_NEW.read_text().splitlines()
        if line.startswith("+") and not line.startswith("+++"))
    assert "def is_credit_failure" in body
    f = tmp_path / "degraded_mode.py"
    f.write_text(body + "\n")
    spec = importlib.util.spec_from_file_location("degraded_mode", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestClassifier:
    """is_credit_failure — sustained outage vs transient blip."""

    @pytest.fixture()
    def dm(self, tmp_path):
        return _load_standalone(tmp_path)

    @pytest.mark.parametrize("text", [
        "HTTP 402 Payment Required: Insufficient credits",
        "403 Key limit exceeded (monthly)",
        "spending cap reached for this key",
        "prepayment credits depleted",
        "429 RESOURCE_EXHAUSTED quota exceeded for metric: "
        "generate_requests_per_model_per_day",
        "quota has been exhausted, resets at midnight",
        "403 key_model_access_denied: model not found",
        "404 model does not exist",
    ])
    def test_sustained_shapes(self, dm, text):
        assert dm.is_credit_failure(Exception(text)) is True

    @pytest.mark.parametrize("text", [
        "429 Too Many Requests: rate limit exceeded, per minute",
        "429 RESOURCE_EXHAUSTED: quota exceeded, retry in 30s",
        "ReadTimeout: timed out",
        "connection reset by peer",
        "500 Internal Server Error",
        "some ordinary failure",
    ])
    def test_transient_and_ordinary(self, dm, text):
        assert dm.is_credit_failure(Exception(text)) is False

    def test_lane_budget_hold_by_code(self, dm):
        class Hold(Exception):
            code = "lane_budget"
        assert dm.is_credit_failure(Hold("held")) is True

    def test_status_code_402_attr(self, dm):
        class E(Exception):
            status_code = 402
        assert dm.is_credit_failure(E("payment")) is True

    def test_none_and_mixed(self, dm):
        assert dm.is_credit_failure(None) is False
        assert dm.is_credit_failure(None, Exception("402 insufficient "
                                                    "credits")) is True

    def test_response_body_scanned(self, dm):
        class Resp:
            status_code = 429
            text = '{"error":{"message":"Insufficient credits"}}'

        class E(Exception):
            response = Resp()
        assert dm.is_credit_failure(E("Client error")) is True


class TestNotices:
    @pytest.fixture()
    def dm(self, tmp_path):
        return _load_standalone(tmp_path)

    def test_english_default(self, dm, monkeypatch):
        monkeypatch.delenv("ADA_DEGRADED_LANG", raising=False)
        monkeypatch.delenv("ADA_DEGRADED_CONTACT", raising=False)
        monkeypatch.delenv("ADA_DEGRADED_PARTICLE", raising=False)
        n = dm.notice("turn", user_text="hello")
        assert "credits" in n and "Tony" in n
        assert "timers" in n  # what still works

    def test_thai_forced_and_auto(self, dm, monkeypatch):
        monkeypatch.setenv("ADA_DEGRADED_LANG", "th")
        n = dm.notice("turn")
        assert "เครดิต" in n and "ค่ะ" in n
        monkeypatch.delenv("ADA_DEGRADED_LANG")
        n2 = dm.notice("turn", user_text="สวัสดีค่ะ")
        assert "เครดิต" in n2
        n3 = dm.notice("turn", user_text="hello there")
        assert "credits" in n3

    def test_contact_and_particle_env(self, dm, monkeypatch):
        monkeypatch.setenv("ADA_DEGRADED_CONTACT", "Boss")
        monkeypatch.setenv("ADA_DEGRADED_PARTICLE", "ครับ")
        monkeypatch.setenv("ADA_DEGRADED_LANG", "th")
        n = dm.notice("connect")
        assert "Boss" in n and "ครับ" in n

    def test_template_override(self, dm, monkeypatch):
        monkeypatch.setenv("ADA_DEGRADED_NOTICE_EN", "CUSTOM {contact}")
        assert dm.notice("turn", user_text="hi") == "CUSTOM Tony"

    def test_turn_failure_notice_gating(self, dm, monkeypatch):
        monkeypatch.delenv("ADA_DEGRADED_LANG", raising=False)
        assert dm.turn_failure_notice(
            Exception("402 insufficient credits"),
            Exception("boom"), user_text="hi") is not None
        assert dm.turn_failure_notice(
            Exception("429 rate limit per minute"),
            Exception("timeout"), user_text="hi") is None

        class Hold(Exception):
            code = "lane_budget"
        assert dm.connect_notice(Hold("held until rollover")) is not None
        assert dm.connect_notice(Exception("timeout")) is None


# ------------------------------------------------------------- drop registry

@NEEDS_ADA_PI
def test_patches_apply_or_landed(tmp_path):
    """Tri-state per patch: applies (drop pending), merged (already
    upstream), diverged — divergence fails only when NOTHING in the drop
    merged (rotted base on a pending drop)."""
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    states = {p.name: check_patch(p, dst) for p in PATCHES}
    assert drop_guard_ok(states.values()), (
        f"drop rotted on its base — re-dispatch: {states}")


@NEEDS_ADA_PI
def test_patched_files_compile(tmp_path):
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    for p in PATCHES:
        apply_patch(p, dst)
    for rel in ("backend/degraded_mode.py",
                "backend/openrouter_provider.py",
                "pwa_server.py"):
        f = dst / rel
        compile(f.read_text(), str(f), "exec")


# ------------------------------------------------- patched provider behaviour

def _import_patched_provider(src: Path):
    """Import backend.openrouter_provider from the patched scratch tree
    via real package imports (sys.path) — hand-wiring submodules is
    order-fragile because realtime_provider pulls the whole backend
    package at import time. dep_stubs fabricates google-genai/fastapi.
    Returns (module, restore callable)."""
    pytest.importorskip("httpx")
    pre_modules = set(sys.modules)
    spec = importlib.util.spec_from_file_location(
        "ada_pi_dep_stubs", src / "tests" / "dep_stubs.py")
    stubs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stubs)
    stubs.install()
    # evict stale backend.* (other drop tests / dep_stubs leftovers) so
    # the scratch tree's package wins the import
    evicted = {n: sys.modules.pop(n) for n in list(sys.modules)
               if n == "backend" or n.startswith("backend.")}
    sys.path.insert(0, str(src))
    try:
        import backend.openrouter_provider as orp
    finally:
        sys.path.remove(str(src))

    def _restore() -> None:
        for name in set(sys.modules) - pre_modules:
            sys.modules.pop(name, None)
        sys.modules.update(evicted)

    return orp, _restore


async def _drive_complete(provider, user_text: str, err: Exception):
    provider._turns.append(
        {"role": "user", "parts": [{"text": user_text}]})

    async def _or_turn(last_err=None):
        raise err

    provider._or_turn = _or_turn
    await provider._complete()
    evs = []
    while not provider._queue.empty():
        evs.append(provider._queue.get_nowait())
    return evs


@NEEDS_ADA_PI
def test_credit_failure_emits_notice_not_silence(tmp_path):
    """The KK failure mode: every transport dead on a credit error must
    produce a spoken/shown notice, not response_interrupted silence."""
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    for p in PATCHES:
        apply_patch(p, dst)
    orp, restore = _import_patched_provider(dst)
    try:
        provider = orp.OpenRouterTextProvider(tools=False,
                                              session_id="t-degraded")
        evs = asyncio.run(_drive_complete(
            provider, "hello",
            Exception("HTTP 402 Payment Required: Insufficient credits")))
        types_seen = [e.type for e in evs]
        assert "response_interrupted" not in types_seen
        assert types_seen[0] == "response_started"
        assert types_seen[-1] == "response_completed"
        text = "".join(e.data.get("text", "")
                       for e in evs if e.type == "assistant_transcript_delta")
        assert "credits" in text and "Tony" in text
    finally:
        restore()


@NEEDS_ADA_PI
def test_credit_failure_thai_user_gets_thai_notice(tmp_path,
                                                 monkeypatch):
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    for p in PATCHES:
        apply_patch(p, dst)
    orp, restore = _import_patched_provider(dst)
    try:
        monkeypatch.delenv("ADA_DEGRADED_LANG", raising=False)
        provider = orp.OpenRouterTextProvider(tools=False,
                                              session_id="t-th")
        evs = asyncio.run(_drive_complete(
            provider, "สวัสดีค่ะ",
            Exception("HTTP 402 Insufficient credits")))
        text = "".join(e.data.get("text", "")
                       for e in evs if e.type == "assistant_transcript_delta")
        assert "เครดิต" in text
    finally:
        restore()


@NEEDS_ADA_PI
def test_transient_failure_keeps_interrupted_path(tmp_path):
    """A per-minute 429 is not a credit outage — the old
    response_interrupted behaviour must not regress into a false
    'credits died' alarm."""
    dst = tmp_path / "ada-voice"
    materialize_head(dst, ADA_PI)
    for p in PATCHES:
        apply_patch(p, dst)
    orp, restore = _import_patched_provider(dst)
    try:
        provider = orp.OpenRouterTextProvider(tools=False,
                                              session_id="t-transient")
        evs = asyncio.run(_drive_complete(
            provider, "hello",
            Exception("429 Too Many Requests: rate limit per minute")))
        types_seen = [e.type for e in evs]
        assert types_seen == ["response_interrupted"]
    finally:
        restore()
