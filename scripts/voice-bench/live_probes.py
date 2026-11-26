#!/usr/bin/env python3
"""Gemini Live session probes — barge-in and session soak.

Re-implementation of the probes used in the 2026-11-24 gemini-3.8-live
promotion gate (docs/ssot/jobs/voice/2026-11-24-gemini-38-live-eval.yml)
as a committed script, so future Live-model evals don't re-derive them.

  barge-in — stream fixture A; when the model starts speaking its reply,
             stream fixture B over it. Pass = serverContent.interrupted
             observed AND the post-interrupt input transcription matches B.
  soak     — one session, N text turns; per-turn latency plus
             error/disconnect count. Stability signal, not a full-duplex
             audio soak (same caveat as the 2026-11-24 gate).

Usage:
  live_probes.py --model gemini-3.8-live [--thinking-level LOW] \
      [--key-file PATH] [--fixture-a ID --fixture-b ID] \
      [--soak-turns 9] [--turn-timeout 60] [--out results/x.json]

Key: GEMINI_API_KEY env wins; else --key-file / GEMINI_KEY_FILE /
~/.config/secrets/gemini-api-key.env (see adapters.load_gemini_key).
"""
import argparse
import asyncio
import base64
import datetime as dt
import json
import os
import subprocess
import time
import wave
from pathlib import Path

import adapters
import lib

WS_URL = ("wss://generativelanguage.googleapis.com/ws/"
          "google.ai.generativelanguage.v1beta.GenerativeService."
          "BidiGenerateContent")

CHUNK_MS = 100
TRAIL_SILENCE_S = 1.0


def _wav_pcm(path):
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        return w.readframes(w.getnframes()), w.getframerate()


def _payload(path):
    pcm, rate = _wav_pcm(path)
    if rate != 16000:
        raise RuntimeError(f"{path}: expected 16kHz, got {rate}")
    return pcm + b"\x00" * int(rate * TRAIL_SILENCE_S) * 2, rate


class LiveSession:
    """One BidiGenerateContent session: receiver task + shared turn state.

    Turn completion rule mirrors adapters.gemini_live: extended-thinking
    models gate on interactionStatus IDLE (turnComplete only ends an
    utterance); other models complete on turnComplete with the one early
    skip after a toolCall.
    """

    def __init__(self, model, thinking_level):
        self.model = model
        self.thinking_mode, self.level = adapters.thinking_mode_for(
            model, thinking_level)
        self.ws = None
        self.closed = False
        self.error = None
        # turn state
        self.turn_done = asyncio.Event()
        self.last_status = None
        self.status_seen = False
        self.awaiting_final = False
        self.early_skipped = False
        # observations
        self.events = []            # (mono_ts, kind, detail)
        self.transcripts = []       # (mono_ts, text)  input transcription
        self.assistant_parts = []   # (mono_ts, text)  output transcription
        self.audio_ts = []          # mono_ts of each modelTurn audio chunk
        self.tool_calls = []        # {name, args}
        self.interrupted_count = 0
        self.interrupt_ts = None    # first serverContent.interrupted
        self.barge_ts = None        # set by barge-in probe
        self.audio_after_barge = False
        self.first_audio_ts = None
        self.idle_since = None
        self.last_event_ts = None
        self.last_tc_ts = None      # last turnComplete (any flavor)

    def note(self, kind, detail=None):
        self.last_event_ts = time.monotonic()
        self.events.append((self.last_event_ts, kind, detail))

    async def connect(self, api_key):
        import websockets
        self.ws = await websockets.connect(
            f"{WS_URL}?key={api_key}", max_size=None)
        await self.ws.send(json.dumps(
            adapters.live_setup(self.model, self.level)))
        self._recv_task = asyncio.create_task(self._receiver())

    async def close(self):
        self._recv_task.cancel()
        try:
            await self.ws.close()
        except Exception:
            pass

    def arm_turn(self):
        self.turn_done.clear()

    async def wait_turn(self, timeout):
        """Wait for a qualifying turn completion. 1 s slices let the
        IDLE-without-turnComplete safety fire on thinking models."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                await asyncio.wait_for(self.turn_done.wait(), timeout=1.0)
                return True
            except asyncio.TimeoutError:
                pass
            if (self.thinking_mode and self.idle_since
                    and time.monotonic() - self.idle_since > 4):
                self.note("idle_no_tc_done")
                return True
            if self.closed:
                return False
        return False

    async def _receiver(self):
        debug = os.environ.get("VB_DEBUG")
        try:
            while True:
                raw = await self.ws.recv()
                if debug:
                    print(f"[rx {time.monotonic():.1f}] {raw[:400]}",
                          flush=True)
                try:
                    m = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle(m)
        except Exception as e:  # close, protocol error, cancel
            self.closed = True
            self.error = self.error or str(e)
            self.turn_done.set()

    async def _handle(self, m):
        now = time.monotonic()
        sc = m.get("serverContent") or {}
        st = m.get("interactionStatus") or sc.get("interactionStatus")
        if st:
            self.status_seen = True
            self.last_status = st
            self.idle_since = time.monotonic() if st == "IDLE" else None
            self.note(f"interaction_{str(st).lower()}")
        it = sc.get("inputTranscription") or {}
        if it.get("text"):
            self.transcripts.append((now, it["text"]))
            self.note("input_transcription", it["text"][:80])
        ot = sc.get("outputTranscription") or {}
        if ot.get("text"):
            self.assistant_parts.append((now, ot["text"]))
            self.note("output_transcription")
            self.awaiting_final = False
        for part in ((sc.get("modelTurn") or {}).get("parts") or []):
            if part.get("inlineData", {}).get("data"):
                self.audio_ts.append(now)
                if self.first_audio_ts is None:
                    self.first_audio_ts = now
                if (self.barge_ts is not None and now > self.barge_ts):
                    self.audio_after_barge = True
                self.awaiting_final = False
                self.note("audio")
        if sc.get("interrupted"):
            self.interrupted_count += 1
            if self.interrupt_ts is None:
                self.interrupt_ts = now
            self.note("interrupted")
        if sc.get("turnComplete"):
            self.last_tc_ts = now
            if self.thinking_mode and self.status_seen:
                # turnComplete ends an utterance; IDLE ends the request.
                if self.last_status == "IDLE":
                    self.note("turn_complete")
                    self.turn_done.set()
                else:
                    self.note("utterance_turn_complete")
            elif self.awaiting_final and not self.early_skipped:
                self.note("early_turn_complete")
                self.early_skipped = True
            else:
                self.note("turn_complete")
                self.turn_done.set()
        if "toolCall" in m:
            self.note("tool_call")
            responses = []
            for call in (m["toolCall"].get("functionCalls") or []):
                self.tool_calls.append(
                    {"name": call.get("name"),
                     "args": call.get("args") or {}})
                responses.append({
                    "id": call.get("id", ""),
                    "name": call.get("name", ""),
                    "response": {"ok": True,
                                 "result": "done (bench stub)"}})
            if responses:
                try:
                    await self.ws.send(json.dumps({"toolResponse": {
                        "functionResponses": responses}}))
                except Exception as e:
                    self.error = self.error or f"toolResponse send: {e}"
                self.awaiting_final = True
                self.early_skipped = False
        if m.get("error"):
            self.error = self.error or json.dumps(m["error"])
            self.note("server_error", str(m["error"])[:200])
            self.turn_done.set()

    # -- senders ---------------------------------------------------------

    async def stream_audio(self, payload, start_at=None):
        """Stream PCM16@16k at real-time pace; returns monotonic send_done."""
        if start_at is not None:
            await asyncio.sleep(max(0.0, start_at - time.monotonic()))
        chunk_bytes = int(16000 * CHUNK_MS / 1000) * 2
        for i in range(0, len(payload), chunk_bytes):
            await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                "data": base64.b64encode(
                    payload[i:i + chunk_bytes]).decode(),
                "mimeType": "audio/pcm;rate=16000"}}}))
            await asyncio.sleep(CHUNK_MS / 1000)
        await self.ws.send(json.dumps(
            {"realtimeInput": {"audioStreamEnd": True}}))
        return time.monotonic()

    async def send_text(self, text):
        await self.ws.send(json.dumps(
            {"realtimeInput": {"text": text}}))


async def probe_barge_in(sess, fx_a, fx_b, timeout):
    """Stream A, barge with B when the model starts speaking, wait for the
    post-interrupt turn to complete. Returns the probe record."""
    payload_a, _ = _payload(fx_a["wav"])
    payload_b, _ = _payload(fx_b["wav"])
    t0 = time.monotonic()
    rec = {"fixture_a": fx_a["id"], "fixture_b": fx_b["id"],
           "expected_b": fx_b["expected_transcript"],
           "lang_b": fx_b["lang"]}

    send_a = asyncio.create_task(sess.stream_audio(payload_a))
    # wait for the model to start speaking fixture A's reply
    deadline = t0 + timeout
    while sess.first_audio_ts is None and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    if sess.first_audio_ts is None:
        rec.update(status="error",
                   error="model never started speaking fixture A")
        send_a.cancel()
        return rec
    rec["first_audio_a_ms"] = round((sess.first_audio_ts - t0) * 1000)

    # barge in: cancel A's silence tail, stream B at real-time pace
    send_a.cancel()
    sess.barge_ts = time.monotonic()
    sess.arm_turn()
    send_b = asyncio.create_task(sess.stream_audio(payload_b))
    rec["barge_ts"] = round((sess.barge_ts - t0) * 1000)

    # done = quiescence, not a single turnDone edge: the ABORTED turn can
    # close with turnComplete+IDLE after the barge (thinking Live does
    # exactly that), which would false-trigger a naive done check while the
    # real post-barge turn is still working. Require 2 s of no events plus
    # a post-barge turnComplete, IDLE status (thinking), post-barge audio,
    # and a post-barge transcript.
    QUIET_S = 2.0

    def post_barge_tx():
        # transcripts counted as "post-barge" start at the interruption
        # itself — fixture A's own input transcription can land after
        # barge_ts and would otherwise pollute the WER vs fixture B.
        cutoff = (sess.interrupt_ts if sess.interrupt_ts is not None
                  else sess.barge_ts)
        return "".join(
            t for ts, t in sess.transcripts if ts > cutoff).strip()
    while time.monotonic() < deadline:
        quiet = (sess.last_event_ts is not None
                 and time.monotonic() - sess.last_event_ts > QUIET_S)
        tc_after = (sess.last_tc_ts is not None
                    and sess.last_tc_ts > sess.barge_ts)
        status_idle = (not sess.thinking_mode
                       or sess.last_status == "IDLE")
        if (quiet and tc_after and status_idle
                and sess.audio_after_barge and post_barge_tx()):
            break
        await asyncio.sleep(0.1)
    # drain: thinking models can emit a toolCall + final spoken turn a beat
    # after the IDLE that satisfied turn_done — keep reading briefly so the
    # record captures the whole post-barge exchange.
    drain_end = time.monotonic() + 4
    while time.monotonic() < drain_end and not sess.closed:
        await asyncio.sleep(0.2)
    try:
        await asyncio.wait_for(send_b, timeout=10)
    except asyncio.TimeoutError:
        pass
    rec["total_ms"] = round((time.monotonic() - t0) * 1000)
    rec["interrupted"] = sess.interrupted_count
    tx = post_barge_tx()
    rec["post_barge_transcript"] = tx or None
    rec["post_barge_wer"] = (lib.wer(fx_b["expected_transcript"], tx,
                                     fx_b["lang"])
                             if tx else None)
    rec["transcript_ok"] = bool(tx) and rec["post_barge_wer"] <= 0.34
    rec["assistant_text"] = "".join(
        t for _, t in sess.assistant_parts).strip() or None
    rec["tool_calls"] = sess.tool_calls
    rec["events_seen"] = sorted({k for _, k, _ in sess.events})
    if sess.error:
        rec["status"] = "error"
        rec["error"] = sess.error
    elif rec["transcript_ok"] and sess.interrupted_count:
        rec["status"] = "ok"
    elif rec["transcript_ok"]:
        rec["status"] = "degraded"  # answered B but no interrupt event
    else:
        rec["status"] = "error"
        rec["error"] = rec.get("error") or "post-barge turn did not complete"
    return rec


SOAK_PROMPTS = [
    "Soak check {i}: reply with exactly 'soak turn {i} ok' and nothing else.",
    "Soak check {i}: what is {a} plus {b}? Reply with just the number.",
    "Soak check {i}: say the word 'pineapple' once, nothing else.",
    "Soak check {i}: reply with exactly 'still here {i}'.",
    "Soak check {i}: what day comes after Monday? One word answer.",
    "Soak check {i}: count from {a} to {b}. Just the numbers.",
    "Soak check {i}: reply with exactly 'soak turn {i} ok' and nothing else.",
    "Soak check {i}: what is the capital of France? One word.",
    "Soak check {i}: say 'session stable' and nothing else.",
]


async def probe_soak(sess, turns, turn_timeout, gap_s):
    """N text turns on one session; per-turn latency + session health."""
    t0 = time.monotonic()
    rec = {"turns": [], "prompts_sent": []}
    disconnects = 0
    for i in range(turns):
        if sess.closed:
            disconnects += 1
            break
        prompt = SOAK_PROMPTS[i % len(SOAK_PROMPTS)].format(
            i=i + 1, a=(i * 7) % 90 + 2, b=(i * 13) % 40 + 1)
        rec["prompts_sent"].append(prompt)
        turn = {"i": i + 1, "prompt": prompt}
        sess.arm_turn()
        t_send = time.monotonic()
        tx_start = len(sess.transcripts)
        audio_start = len(sess.audio_ts)
        await sess.send_text(prompt)
        ok = await sess.wait_turn(turn_timeout)
        turn["elapsed_ms"] = round((time.monotonic() - t_send) * 1000)
        turn["ok"] = ok and not sess.closed
        if sess.first_audio_ts is not None:
            after = [t for t in sess.audio_ts[audio_start:]]
            turn["first_audio_ms"] = (
                round((after[0] - t_send) * 1000) if after else None)
        tx = "".join(t for _, t in sess.transcripts[tx_start:]).strip()
        turn["transcript"] = tx or None
        turn["assistant_text"] = "".join(
            t for _, t in sess.assistant_parts).strip()[-160:] or None
        rec["turns"].append(turn)
        if sess.closed:
            disconnects += 1
            break
        await asyncio.sleep(gap_s)
    rec["total_ms"] = round((time.monotonic() - t0) * 1000)
    rec["n_turns"] = len(rec["turns"])
    rec["n_ok"] = sum(1 for t in rec["turns"] if t["ok"])
    rec["disconnects"] = disconnects
    rec["errors"] = [e for e in (sess.error,) if e]
    rec["events_seen"] = sorted({k for _, k, _ in sess.events})
    return rec


async def run(args):
    if args.key_file:
        # --key-file feeds the GEMINI_KEY_FILE fallback in
        # adapters.load_gemini_key; a real GEMINI_API_KEY env still wins.
        os.environ["GEMINI_KEY_FILE"] = args.key_file
    api_key = adapters.load_gemini_key()

    fixtures = {f["id"]: f for f in lib.load_fixtures()}
    fx_a = fixtures[args.fixture_a]
    fx_b = fixtures[args.fixture_b]

    out = {"schema": "voice-live-probes", "schema_version": 1,
           "model": args.model, "thinking_level": args.thinking_level,
           "at": dt.datetime.now(dt.timezone.utc).strftime(
               "%Y%m%dT%H%M%SZ"),
           "host": subprocess.run(["hostname"], capture_output=True,
                                  text=True).stdout.strip()}

    # --- barge-in -------------------------------------------------------
    if args.only in (None, "barge-in"):
        sess = LiveSession(args.model, args.thinking_level)
        try:
            await sess.connect(api_key)
            out["barge_in"] = await probe_barge_in(
                sess, fx_a, fx_b, args.timeout)
        except Exception as e:
            out["barge_in"] = {"status": "error", "error": str(e)}
        finally:
            await sess.close()

    # --- soak -----------------------------------------------------------
    if args.only in (None, "soak"):
        sess = LiveSession(args.model, args.thinking_level)
        try:
            await sess.connect(api_key)
            out["soak"] = await probe_soak(
                sess, args.soak_turns, args.turn_timeout, args.gap)
        except Exception as e:
            out["soak"] = {"status": "error", "error": str(e)}
        finally:
            await sess.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--key-file", default=None)
    ap.add_argument("--fixture-a", default="en-chat-joke",
                    help="fixture the model answers before the barge")
    ap.add_argument("--fixture-b", default="en-cmd-light-kitchen",
                    help="fixture streamed over the model's reply")
    ap.add_argument("--timeout", type=int, default=90,
                    help="per-probe seconds (barge-in)")
    ap.add_argument("--soak-turns", type=int, default=9)
    ap.add_argument("--turn-timeout", type=int, default=60)
    ap.add_argument("--gap", type=float, default=2.0,
                    help="seconds between soak turns")
    ap.add_argument("--only", choices=["barge-in", "soak"], default=None,
                    help="run a single probe")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    doc = asyncio.run(run(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out}")
    summary = {}
    if "barge_in" in doc:
        summary["barge_in"] = {k: doc["barge_in"].get(k) for k in
                               ("status", "interrupted", "post_barge_wer",
                                "transcript_ok", "total_ms")}
    if "soak" in doc:
        summary["soak"] = {k: doc["soak"].get(k) for k in
                           ("n_turns", "n_ok", "disconnects", "total_ms")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
