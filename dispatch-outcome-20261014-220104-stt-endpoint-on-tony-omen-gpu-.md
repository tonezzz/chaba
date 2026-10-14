# dispatch-outcome — stt-omen-large-v3

**Result: deployed and verified.** ada-whisper HTTP STT endpoint is live
on tony-omen serving whisper large-v3 int8_float16 on the GTX 1650, and
all three msg-lane relays on idc03 now prefer it with a working local
fallback. Committed as c9483403 on the dispatch branch.

## What changed (live)

**tony-omen** — `ada-whisper.service` (systemd --user, linger on,
Restart=on-failure):
- `~/apps/ada-whisper/whisper_server.py` — FastAPI + faster-whisper
  1.2.1; `POST /transcribe` (multipart `file` or raw body), `GET
  /health` on `0.0.0.0:8790`.
- Dedicated `~/.venvs/ada-whisper` (py3.12): ctranslate2 4.8.2 +
  `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` + `LD_LIBRARY_PATH` into
  their `lib/` dirs — the thai-tts venv's cu13 libs fail at
  `libcublas.so.12`, so reuse was not an option.
- Decode is ffmpeg→16kHz f32 numpy, no PyAV.
- **GPU citizenship**: model lazy-loads (~10s cold incl. HF etag) and
  unloads after `WHISPER_IDLE_S=300` — verified twice in journal,
  frees ~1.9GB. On CUDA load failure it evicts ollama models via
  `keep_alive=0` and retries, then falls back to CPU int8.

**idc03** — ada-pi `backend/tg_relay.py` + `backend/line_relay.py`:
- `_transcribe()` → `TG_WHISPER_URL`/`LINE_WHISPER_URL` remote first
  (httpx multipart, 120s); exception → local faster-whisper
  (TG_WHISPER_MODEL=medium, CPU int8). Empty transcript from a healthy
  endpoint does NOT re-transcribe locally (silence is silence).
- `_decode_audio()` → system ffmpeg or `imageio-ffmpeg` bundled binary
  (idc03 has no ffmpeg!), PyAV decode only as last resort — closes the
  av-drift hole from card `tg-relay-whisper-pin`.
- ada-pi venv: `faster-whisper==1.2.1` + `imageio-ffmpeg` installed,
  `av` kept at 15.1; requirements.txt gained the pins. Committed
  locally on ada-pi main as **daa0e0a (not pushed)**.
- Env: `TG_WHISPER_URL=http://tony-omen:8790/transcribe` appended to
  `telegram-bot.env` + `telegram-kk-bot.env`; `LINE_WHISPER_URL` in
  `line-bot.env` — **inert**: LINE_VOICE_TRANSCRIBE was never armed
  (LINE clips are corpus+speaker-id only). Board request raised.
- `ada-tg-relay`, `ada-tg-relay-kk`, `ada-line-relay` restarted; all
  active, journals clean, `/proc/*/environ` confirms the vars.

## Verified

- idc03 → `http://tony-omen:8790/transcribe` TH fixture:
  `สวัสดีครับ วันนี้เป็นไงบ้าง` (th p=1.00) — 4.0s warm, ~8s cold.
- EN fixture: `Good morning, how are you today?` (p=0.97) — 3.6s.
- Real `_transcribe()` in the ada-pi venv: remote path correct TH;
  dead-URL → local medium → identical TH text.
- Idle unload fired at 22:16:17 and 22:34:47 (+1.9GB VRAM released);
  reload-on-request works.
- Repo YAML all parses; `whisper_server.py` compiles.

## Tradeoff to know

phi3 (ollama, ~2.7GB) can't fully coexist with warm whisper (~1.9GB)
on the 4GB card — while whisper is warm (~5min after a clip) phi3
reloads into partial CPU offload. This is the ssot.gpu one-workload
policy made practical: brief contention, no failures.

## Repo artifacts

- `scripts/ada/whisper_server.py`
- `stacks/tony-omen/ada-whisper/{ada-whisper.service,stack.yml}`
- `integrations/ada-pi/backend/{tg_relay,line_relay}.whisper-url.patch`
  + README drop 9 (install/contract/verified/residual)
- `docs/ssot/jobs/ada/2026-10-14-stt-omen-whisper-endpoint.yml`
- `ssot.services.yml` + `ssot.health.home.gpu.yml` entries,
  `docs/kb/msg-lane-standard.md` new-lane checklist line

## How to verify

1. `curl -s http://tony-omen:8790/health` → `{"ok":true,...}`
2. Send a Telegram voice note → relay replies `🎙 "<transcript>"`;
   journal shows no "local fallback" warning when omen is up.
3. `systemctl --user stop ada-whisper` on omen, send another clip →
   relay journal shows `remote whisper ... failed — local fallback`,
   transcript still arrives (slower, medium quality).
4. `nvidia-smi` on omen ~6min after a clip → whisper VRAM released.

## Open

- Board request `arm-line-voice-transcribe-...`: arm
  `LINE_VOICE_TRANSCRIBE=1` so LINE voice notes transcribe too.
- ada-pi `daa0e0a` is local-only — needs a push when someone syncs
  ada-pi (rails said don't push).
