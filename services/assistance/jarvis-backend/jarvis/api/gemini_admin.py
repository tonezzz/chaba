"""
Gemini Admin API Router
Admin-only endpoints for Gemini Live model management, caching, and sidecar STT.
"""
import os
import struct
import time
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Body

from jarvis.websocket.session import (
    gemini_list_models,
    gemini_live_probe_and_cache,
    gemini_live_cache_status,
    sidecar_stt_cache_status,
    sidecar_stt_set_working_model,
)

router = APIRouter()


def _require_admin(auth: str | None = Header(default=None, alias="Authorization")) -> None:
    """Require admin token for sensitive endpoints."""
    token = str(os.getenv("JARVIS_ADMIN_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="admin_token_not_configured")
    if not auth:
        raise HTTPException(status_code=401, detail="missing_authorization")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="invalid_authorization")
    presented = auth.split(" ", 1)[1].strip()
    if presented != token:
        raise HTTPException(status_code=403, detail="forbidden")


@router.get("/jarvis/api/gemini/models")
async def gemini_models() -> dict[str, Any]:
    models = gemini_list_models()
    return {"ok": True, "count": len(models), "models": models}


@router.get("/gemini/models")
async def gemini_models_unprefixed() -> dict[str, Any]:
    models = gemini_list_models()
    return {"ok": True, "count": len(models), "models": models}


@router.get("/jarvis/api/gemini/live/cache")
async def gemini_live_cache(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@router.get("/gemini/live/cache")
async def gemini_live_cache_unprefixed(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@router.post("/jarvis/api/gemini/live/probe")
async def gemini_live_probe(_: None = Depends(_require_admin)) -> dict[str, Any]:
    result = await gemini_live_probe_and_cache()
    return result


@router.post("/gemini/live/probe")
async def gemini_live_probe_unprefixed(_: None = Depends(_require_admin)) -> dict[str, Any]:
    result = await gemini_live_probe_and_cache()
    return result


@router.get("/jarvis/api/live/cache_status")
async def live_cache_status(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@router.get("/live/cache_status")
async def live_cache_status_unprefixed(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **gemini_live_cache_status()}


@router.post("/jarvis/api/live/probe")
async def live_probe(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return await gemini_live_probe_and_cache()


@router.post("/live/probe")
async def live_probe_unprefixed(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return await gemini_live_probe_and_cache()


@router.get("/jarvis/api/gemini/live/recommend")
async def gemini_live_recommend() -> dict[str, Any]:
    models = gemini_list_models()
    # Recommend models based on list output (keep deterministic ordering)
    ranked = [
        m for m in models
        if any(k in m.lower() for k in ["live", "realtime", "native-audio"]) or "bidi" in m.lower()
    ]
    return {"ok": True, "count": len(ranked), "models": ranked}


@router.get("/gemini/live/recommend")
async def gemini_live_recommend_unprefixed() -> dict[str, Any]:
    models = gemini_list_models()
    ranked = [
        m for m in models
        if any(k in m.lower() for k in ["live", "realtime", "native-audio"]) or "bidi" in m.lower()
    ]
    return {"ok": True, "count": len(ranked), "models": ranked}


async def _gemini_sidecar_stt_probe(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Internal: Probe Gemini sidecar STT capabilities."""
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"missing_google_genai: {str(e)}")

    api_key = str(os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="missing_gemini_api_key")

    p = payload or {}
    raw_models = p.get("models")
    models: list[str]
    if isinstance(raw_models, list) and raw_models:
        models = [str(m).strip() for m in raw_models if str(m).strip()]
    else:
        # Heuristic defaults: common text models for STT via generateContent.
        models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-2.5-pro",
            "gemini-pro-latest",
        ]

    max_models = int(p.get("max_models") or 12)
    if max_models > 0:
        models = models[:max_models]

    sample_rate = int(p.get("sample_rate") or 16000)
    seconds = float(p.get("seconds") or 0.25)
    seconds = max(0.05, min(seconds, 2.0))
    pcm16 = b"\x00\x00" * int(sample_rate * seconds)

    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = len(pcm16)
    riff_size = 36 + data_size
    wav_bytes = b"".join(
        [
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", 1),
            struct.pack("<H", num_channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", bits_per_sample),
            b"data",
            struct.pack("<I", data_size),
            pcm16,
        ]
    )

    prompt = str(p.get("prompt") or "Transcribe the audio. Return only the spoken words.").strip()
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    attempts: list[dict[str, Any]] = []
    started = time.time()
    for model in models:
        clean_model = model[7:] if model.startswith("models/") else model
        try:
            resp = await client.aio.models.generate_content(
                model=clean_model,
                contents=[
                    prompt,
                    types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
                ],
                config={
                    "system_instruction": "You are a speech-to-text transcription engine.",
                },
            )
            text = str(getattr(resp, "text", "") or "")
            attempts.append(
                {
                    "model": clean_model,
                    "ok": True,
                    "text_len": len(text.strip()),
                }
            )
        except Exception as e:
            attempts.append({"model": clean_model, "ok": False, "error": str(e)})

    chosen: str | None = None
    preferred = [
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
    ]
    ok_models: list[str] = []
    for a in attempts:
        try:
            if a.get("ok") is True and a.get("model"):
                ok_models.append(str(a.get("model")).strip())
        except Exception:
            continue

    for p0 in preferred:
        if p0 in ok_models:
            chosen = p0
            break
    if not chosen and ok_models:
        chosen = ok_models[0]

    if chosen:
        try:
            sidecar_stt_set_working_model(chosen)
        except Exception as e:
            logger.warning(f"Failed to set sidecar STT working model: {e}")

    return {
        "ok": any(a.get("ok") for a in attempts),
        "model": chosen,
        **sidecar_stt_cache_status(),
        "attempts": attempts,
        "elapsed_ms": int((time.time() - started) * 1000),
    }


@router.post("/jarvis/api/gemini/sidecar_stt/probe")
async def gemini_sidecar_stt_probe(
    payload: dict[str, Any] | None = Body(default=None),
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    return await _gemini_sidecar_stt_probe(payload)


@router.post("/gemini/sidecar_stt/probe")
async def gemini_sidecar_stt_probe_unprefixed(
    payload: dict[str, Any] | None = Body(default=None),
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    return await _gemini_sidecar_stt_probe(payload)


@router.get("/jarvis/api/gemini/sidecar_stt/cache")
async def gemini_sidecar_stt_cache(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **sidecar_stt_cache_status()}


@router.get("/gemini/sidecar_stt/cache")
async def gemini_sidecar_stt_cache_unprefixed(_: None = Depends(_require_admin)) -> dict[str, Any]:
    return {"ok": True, **sidecar_stt_cache_status()}
