from pathlib import Path
R = Path("/home/tony/CascadeProjects/ada-pi")

# ---- tg_relay.py: send_voice + /send audio_b64 ------------------------------
p = R / "backend/tg_relay.py"
s = p.read_text()

# send_voice next to send_photo
s = s.replace(
    '''        """Fetch image bytes (tailnet-reachable) and sendPhoto them."""''',
    '''    async def send_voice(self, chat_id: int, ogg: bytes,
                         caption: str = "", duration_ms: int = 0) -> None:
        """Push an OGG/Opus voice bubble via sendVoice — TG takes a direct
        multipart upload (no public URL needed, unlike LINE)."""
        assert self.http is not None
        resp = await self.http.post(
            f"{TG_API}/bot{BOT_TOKEN}/sendVoice",
            data={"chat_id": str(chat_id),
                  "caption": caption[:1000],
                  "duration": str(max(0, int(duration_ms) // 1000))},
            files={"voice": ("voice.ogg", ogg, "audio/ogg")})
        if not resp.json().get("ok"):
            raise RuntimeError(str(resp.json()))

    def _wav_to_ogg(self, wav: bytes) -> bytes:
        """WAV (any rate) -> OGG/Opus 24kHz mono via PyAV — the format
        sendVoice needs for a native voice bubble."""
        import io
        import av
        inp = av.open(io.BytesIO(wav))
        ist = inp.streams.audio[0]
        buf = io.BytesIO()
        out = av.open(buf, mode="w", format="ogg")
        ost = out.add_stream("libopus", rate=24000)
        ost.layout = "mono"
        resampler = av.audio.resampler.AudioResampler(
            format="fltp", layout="mono", rate=24000)
        for frame in inp.decode(ist):
            for rf in resampler.resample(frame):
                for pkt in ost.encode(rf):
                    out.mux(pkt)
        for rf in resampler.resample(None):
            for pkt in ost.encode(rf):
                out.mux(pkt)
        for pkt in ost.encode(None):
            out.mux(pkt)
        out.close()
        inp.close()
        return buf.getvalue()

    """Fetch image bytes (tailnet-reachable) and sendPhoto them."""''',
    1)

# /send handler: audio_b64
s = s.replace(
    '''            photo = body.get("photo_url") or body.get("image_url")
            if not (body.get("text") or photo):''',
    '''            photo = body.get("photo_url") or body.get("image_url")
            audio_b64 = str(body.get("audio_b64") or "")
            if not (body.get("text") or photo or audio_b64):''',
    1)

s = s.replace(
    '''                if photo:
                    await self.send_photo(cid, str(photo),
                                          str(body.get("caption") or ""))
                return JSONResponse({"ok": True, "chat_id": cid})''',
    '''                if photo:
                    await self.send_photo(cid, str(photo),
                                          str(body.get("caption") or ""))
                if audio_b64:
                    import base64
                    ogg = await asyncio.to_thread(
                        self._wav_to_ogg, base64.b64decode(audio_b64))
                    await self.send_voice(
                        cid, ogg, str(body.get("caption") or ""),
                        int(body.get("duration_ms") or 0))
                return JSONResponse({"ok": True, "chat_id": cid})''',
    1)
p.write_text(s)
print("tg_relay.py patched")

# ---- chat.py: voice on telegram too -----------------------------------------
p = R / "backend/tool_runner/chat.py"
s = p.read_text()
s = s.replace(
    '''        say_text = str(say or "").strip()
        if say_text and "line" in relays:''',
    '''        say_text = str(say or "").strip()
        want_voice = ("line" in relays or "telegram" in relays
                      or "tg" in relays)
        if say_text and want_voice:''',
    1)
s = s.replace(
    '''        elif say_text:
            summary_bits.append("voice: LINE only — skipped")''',
    '''        elif say_text:
            summary_bits.append("voice: line/telegram only — skipped")''',
    1)
s = s.replace(
    '''            if svc == "line" and audio_b64:
                payload.update({"audio_b64": audio_b64,
                                "audio_mime": "audio/wav",
                                "duration_ms": duration_ms})''',
    '''            if audio_b64 and svc in ("line", "telegram", "tg"):
                payload.update({"audio_b64": audio_b64,
                                "audio_mime": "audio/wav",
                                "duration_ms": duration_ms})''',
    1)
p.write_text(s)
print("chat.py patched")

# ---- schema description tweak ------------------------------------------------
p = R / "backend/realtime_provider.py"
s = p.read_text()
s = s.replace(
    '"a voice message (LINE only)."',
    '"a voice message (LINE and Telegram)."',
    1)
s = s.replace(
    '"description": "Voice-note text — synthesized to speech (your voice) and pushed as a LINE voice message. LINE only; keep it short and speakable.",',
    '"description": "Voice-note text — synthesized to speech (your voice) and pushed as a voice message. LINE and Telegram; keep it short and speakable.",',
    1)
p.write_text(s)
print("schema patched")
