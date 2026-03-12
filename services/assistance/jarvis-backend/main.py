import asyncio
import base64
import os
import logging
import json
import sqlite3
import time
import uuid
import re
import hashlib
from io import BytesIO
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from dotenv import load_dotenv

from google import genai
from google.genai import types
from pydantic import BaseModel, Field


def _require_env(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


load_dotenv()

GEMINI_LIVE_MODEL_OVERRIDE = str(os.getenv("GEMINI_LIVE_MODEL") or "").strip()
GEMINI_LIVE_MODEL_DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"

_REMINDER_TITLE_MODEL_SINGLE = (
    str(os.getenv("JARVIS_REMINDER_TITLE_MODEL") or os.getenv("GEMINI_TEXT_MODEL") or "gemini-2.0-flash").strip()
    or "gemini-2.0-flash"
)


def _parse_model_list(value: str) -> list[str]:
    parts = [p.strip() for p in str(value or "").split(",")]
    return [p for p in parts if p]


def _normalize_model_name(name: str) -> str:
    s = str(name or "").strip()
    if s.startswith("models/"):
        s = s[len("models/") :]
    return s


def _normalize_models_prefix(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    return s if s.startswith("models/") else f"models/{s}"


REMINDER_TITLE_MODELS: list[str] = [
    _normalize_model_name(m) for m in _parse_model_list(str(os.getenv("JARVIS_REMINDER_TITLE_MODELS") or "").strip())
]
if not REMINDER_TITLE_MODELS:
    REMINDER_TITLE_MODELS = [
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-pro-latest",
        _normalize_model_name(_REMINDER_TITLE_MODEL_SINGLE),
    ]

INSTANCE_ID = str(os.getenv("JARVIS_INSTANCE_ID") or "").strip() or f"jarvis_{uuid.uuid4().hex[:10]}"

logger = logging.getLogger("jarvis-backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="jarvis-backend", version="0.1.0")


WEB_FETCHER_BASE_URL = str(os.getenv("WEB_FETCHER_BASE_URL") or "http://web-fetcher:8028").strip().rstrip("/")

MCP_BASE_URL = str(os.getenv("MCP_BASE_URL") or "http://mcp-bundle:3050").strip().rstrip("/")

DEEP_RESEARCH_WORKER_BASE_URL = str(os.getenv("DEEP_RESEARCH_WORKER_BASE_URL") or "").strip().rstrip("/")

AIM_MCP_BASE_URL = str(os.getenv("AIM_MCP_BASE_URL") or "").strip().rstrip("/")

WEAVIATE_URL = str(os.getenv("WEAVIATE_URL") or "").strip().rstrip("/")
GEMINI_EMBEDDING_MODEL = str(os.getenv("GEMINI_EMBEDDING_MODEL") or "text-embedding-004").strip() or "text-embedding-004"

JARVIS_TOOL_ALLOWLIST = [
    t.strip()
    for t in str(os.getenv("JARVIS_TOOL_ALLOWLIST") or "").split(",")
    if t.strip()
]
JARVIS_EMBED_CACHE_MAX = max(0, int(os.getenv("JARVIS_EMBED_CACHE_MAX") or "512"))

IMAGEN_MODEL_DEFAULT = str(os.getenv("JARVIS_IMAGEN_MODEL") or "imagen-4.0-generate-001").strip() or "imagen-4.0-generate-001"
IMAGEN_ALLOWED_MODELS = [
    m.strip()
    for m in str(
        os.getenv("JARVIS_IMAGEN_ALLOWED_MODELS")
        or "imagen-4.0-generate-001,imagen-4.0-ultra-generate-001,imagen-4.0-fast-generate-001"
    ).split(",")
    if m.strip()
]
IMAGEN_ASSETS_DIR = str(os.getenv("JARVIS_IMAGEN_ASSETS_DIR") or "/app/imagen_assets").strip() or "/app/imagen_assets"

IMAGE_MODEL_DEFAULT = str(os.getenv("JARVIS_IMAGE_MODEL") or "gemini-3.1-flash-image-preview").strip() or "gemini-3.1-flash-image-preview"
IMAGE_ALLOWED_MODELS = [
    m.strip()
    for m in str(os.getenv("JARVIS_IMAGE_ALLOWED_MODELS") or "gemini-3.1-flash-image-preview").split(",")
    if m.strip()
]


SESSION_DB_PATH = os.getenv("JARVIS_SESSION_DB", "/app/jarvis_sessions.sqlite")

CARS_DATA_DIR = str(os.getenv("JARVIS_CARS_DATA_DIR") or "/app/assistance_data/cars").strip() or "/app/assistance_data/cars"
CARS_ORIGINALS_DIR = os.path.join(CARS_DATA_DIR, "originals")
CARS_PLATES_DIR = os.path.join(CARS_DATA_DIR, "plates")
CARS_CROPS_DIR = os.path.join(CARS_DATA_DIR, "cars")

AGENTS_DIR = str(os.getenv("JARVIS_AGENTS_DIR") or "/app/agents").strip() or "/app/agents"

DEFAULT_USER_ID = str(os.getenv("JARVIS_DEFAULT_USER_ID") or "default").strip() or "default"
DEFAULT_TIMEZONE = str(os.getenv("JARVIS_DEFAULT_TIMEZONE") or "Asia/Bangkok").strip() or "Asia/Bangkok"
MORNING_BRIEF_HOUR = int(str(os.getenv("JARVIS_MORNING_BRIEF_HOUR") or "8").strip() or "8")
MORNING_BRIEF_MINUTE = int(str(os.getenv("JARVIS_MORNING_BRIEF_MINUTE") or "0").strip() or "0")

AGENT_CONTINUE_WINDOW_SECONDS = int(str(os.getenv("JARVIS_AGENT_CONTINUE_WINDOW_SECONDS") or "120").strip() or "120")

_ws_by_user: dict[str, set[WebSocket]] = {}
_reminder_task: Optional[asyncio.Task[None]] = None

_agent_defs: dict[str, dict[str, Any]] = {}

_agent_triggers: dict[str, list[str]] = {}

_weaviate_schema_ready: bool = False


class ImagenGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    model: Optional[str] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    number_of_images: int = 1
    person_generation: Optional[str] = None
    return_data_url: bool = True


class ImagenGenerateResponse(BaseModel):
    asset_id: str
    model: str
    mime_type: str
    sha256: str
    data_url: Optional[str] = None


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    model: Optional[str] = None
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    return_data_url: bool = True


class ImageGenerateResponse(BaseModel):
    asset_id: str
    model: str
    mime_type: str
    sha256: str
    data_url: Optional[str] = None


def _classify_image_generation_error(message: str) -> Optional[dict[str, Any]]:
    msg = str(message or "").strip()
    low = msg.lower()
    if not low:
        return None

    if "only available on paid plans" in low or "upgrade your account" in low:
        return {
            "image_generation_unavailable": True,
            "reason": "paid_plan_required",
            "message": msg,
        }

    if "resource_exhausted" in low or "quota exceeded" in low or "exceeded your current quota" in low:
        return {
            "image_generation_unavailable": True,
            "reason": "quota_exhausted",
            "message": msg,
        }

    return None


def _imagen_allowed_model(model: Optional[str]) -> str:
    m = (str(model or "").strip() or IMAGEN_MODEL_DEFAULT).strip()
    if m not in IMAGEN_ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail={"imagen_model_not_allowed": m, "allowed": IMAGEN_ALLOWED_MODELS})
    return m


def _image_allowed_model(model: Optional[str]) -> str:
    m = (str(model or "").strip() or IMAGE_MODEL_DEFAULT).strip()
    if m not in IMAGE_ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail={"image_model_not_allowed": m, "allowed": IMAGE_ALLOWED_MODELS})
    return m


def _extract_inline_image(res: Any) -> tuple[bytes, str]:
    candidates = getattr(res, "candidates", None) or []
    cand0 = candidates[0] if isinstance(candidates, list) and candidates else None
    content = getattr(cand0, "content", None) if cand0 is not None else None
    parts = getattr(content, "parts", None) if content is not None else None
    for part in parts or []:
        inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
        if not inline_data:
            continue
        mime_type = getattr(inline_data, "mime_type", None) or getattr(inline_data, "mimeType", None) or "image/png"
        data = getattr(inline_data, "data", None)
        if isinstance(data, (bytes, bytearray)):
            return (bytes(data), str(mime_type))
        if isinstance(data, str) and data:
            try:
                return (base64.b64decode(data), str(mime_type))
            except Exception:
                return (data.encode("utf-8"), str(mime_type))
        try:
            as_bytes = bytes(data)
            if as_bytes:
                return (as_bytes, str(mime_type))
        except Exception:
            pass
    raise HTTPException(status_code=502, detail="imagen_no_inline_image")


def _extract_generated_image(res: Any) -> tuple[bytes, str]:
    generated = getattr(res, "generated_images", None) or getattr(res, "generatedImages", None) or []
    if isinstance(generated, list) and generated:
        gi0 = generated[0]
        img = getattr(gi0, "image", None) or gi0
        mime_type = getattr(img, "mime_type", None) or getattr(img, "mimeType", None) or "image/png"
        data = (
            getattr(img, "image_bytes", None)
            or getattr(img, "imageBytes", None)
            or getattr(img, "bytes", None)
            or getattr(img, "data", None)
        )
        if isinstance(data, (bytes, bytearray)):
            return (bytes(data), str(mime_type))
        if isinstance(data, str) and data:
            try:
                return (base64.b64decode(data), str(mime_type))
            except Exception:
                return (data.encode("utf-8"), str(mime_type))
        try:
            as_bytes = bytes(data)
            if as_bytes:
                return (as_bytes, str(mime_type))
        except Exception:
            pass
    raise HTTPException(status_code=502, detail="imagen_no_generated_images")


def _ensure_imagen_assets_dir() -> None:
    os.makedirs(IMAGEN_ASSETS_DIR, exist_ok=True)


def _ensure_cars_data_dirs() -> None:
    os.makedirs(CARS_DATA_DIR, exist_ok=True)
    os.makedirs(CARS_ORIGINALS_DIR, exist_ok=True)
    os.makedirs(CARS_PLATES_DIR, exist_ok=True)
    os.makedirs(CARS_CROPS_DIR, exist_ok=True)


def _normalize_th_plate(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    s = s.replace(" ", "").replace("-", "").replace(".", "")
    s = re.sub(r"[\\/]+", "_", s)
    s = s.strip("_")
    return s


def _guess_image_ext(mime_type: str) -> str:
    mt = str(mime_type or "").lower().strip()
    if "png" in mt:
        return ".png"
    if "webp" in mt:
        return ".webp"
    return ".jpg"


def _write_json_atomic(path: str, obj: Any) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_json_if_exists(path: str) -> Optional[dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _clip_box(box: dict[str, Any], w: int, h: int) -> Optional[tuple[int, int, int, int]]:
    try:
        x1 = int(float(box.get("x1")))
        y1 = int(float(box.get("y1")))
        x2 = int(float(box.get("x2")))
        y2 = int(float(box.get("y2")))
    except Exception:
        return None
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(0, min(w, x2))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _expand_box(x1: int, y1: int, x2: int, y2: int, w: int, h: int, pad: float) -> tuple[int, int, int, int]:
    dx = int((x2 - x1) * pad)
    dy = int((y2 - y1) * pad)
    nx1 = max(0, x1 - dx)
    ny1 = max(0, y1 - dy)
    nx2 = min(w, x2 + dx)
    ny2 = min(h, y2 + dy)
    return (nx1, ny1, nx2, ny2)


async def _detect_th_plates_via_gemini(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return {"ok": False, "error": "missing_api_key"}

    model = _image_allowed_model(os.getenv("JARVIS_IMAGE_MODEL") or IMAGE_MODEL_DEFAULT)
    client = genai.Client(api_key=api_key)

    prompt = (
        "You are given a single exterior photo that may contain multiple cars. "
        "Detect Thailand license plates that are clearly readable. Ignore cars without a visible plate. "
        "Return ONLY valid JSON in this exact schema:\n"
        "{\n"
        "  \"plates\": [\n"
        "    {\n"
        "      \"plate\": \"<string>\",\n"
        "      \"confidence\": <number 0..1>,\n"
        "      \"bbox_plate\": {\"x1\":<int>,\"y1\":<int>,\"x2\":<int>,\"y2\":<int>}\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Coordinates must be pixel coordinates in the original image, with (0,0) at top-left."
    )

    try:
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": str(mime_type or "image/jpeg"), "data": image_bytes}},
                ],
            }
        ]
        res = await client.aio.models.generate_content(model=model, contents=contents)
        txt = getattr(res, "text", None)
        if not txt:
            try:
                txt = str(res)
            except Exception:
                txt = ""
        txt = str(txt or "").strip()
        data = json.loads(txt)
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid_response"}
        plates = data.get("plates")
        if not isinstance(plates, list):
            plates = []
        return {"ok": True, "plates": plates}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _handle_cars_ingest_image(ws: WebSocket, msg: dict[str, Any]) -> None:
    _ensure_cars_data_dirs()

    data_b64 = str(msg.get("data") or "")
    mime_type = str(msg.get("mimeType") or msg.get("mime_type") or "image/jpeg")
    request_id = str(msg.get("request_id") or uuid.uuid4().hex)
    if not data_b64:
        await ws.send_json({"type": "cars_ingest_result", "request_id": request_id, "ok": False, "error": "missing_data"})
        return

    try:
        image_bytes = base64.b64decode(data_b64)
    except Exception:
        await ws.send_json({"type": "cars_ingest_result", "request_id": request_id, "ok": False, "error": "invalid_base64"})
        return

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    ext = _guess_image_ext(mime_type)
    upload_id = uuid.uuid4().hex[:8]
    original_name = f"{ts}_upload_{upload_id}{ext}"
    original_path = os.path.join(CARS_ORIGINALS_DIR, original_name)
    with open(original_path, "wb") as f:
        f.write(image_bytes)

    detected = await _detect_th_plates_via_gemini(image_bytes=image_bytes, mime_type=mime_type)
    plates_in: list[dict[str, Any]] = []
    if bool(detected.get("ok")):
        raw_plates = detected.get("plates")
        if isinstance(raw_plates, list):
            plates_in = [p for p in raw_plates if isinstance(p, dict)]

    results: list[dict[str, Any]] = []
    crops_written = 0
    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception:
        img = None

    for idx, p in enumerate(plates_in, start=1):
        raw_plate = str(p.get("plate") or "")
        plate = _normalize_th_plate(raw_plate)
        if not plate:
            continue

        conf = p.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except Exception:
            conf_f = None

        bbox = p.get("bbox_plate")
        plate_crop_path: Optional[str] = None
        car_crop_path: Optional[str] = None

        if img is not None and isinstance(bbox, dict):
            w, h = img.size
            clipped = _clip_box(bbox, w=w, h=h)
            if clipped is not None:
                x1, y1, x2, y2 = clipped
                plate_crop = img.crop((x1, y1, x2, y2))
                plate_crop_name = f"{plate}_{ts}_{idx:02d}{ext}"
                plate_crop_path = os.path.join(CARS_PLATES_DIR, plate_crop_name)
                try:
                    plate_crop.save(plate_crop_path)
                    crops_written += 1
                except Exception:
                    plate_crop_path = None

                cx1, cy1, cx2, cy2 = _expand_box(x1, y1, x2, y2, w=w, h=h, pad=2.5)
                car_crop = img.crop((cx1, cy1, cx2, cy2))
                car_crop_name = f"{plate}_{ts}_{idx:02d}{ext}"
                car_crop_path = os.path.join(CARS_CROPS_DIR, car_crop_name)
                try:
                    car_crop.save(car_crop_path)
                    crops_written += 1
                except Exception:
                    car_crop_path = None

        json_path = os.path.join(CARS_DATA_DIR, f"{plate}.json")
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        existing = _load_json_if_exists(json_path)
        if existing is None:
            record: dict[str, Any] = {
                "plate": plate,
                "plate_normalized": plate,
                "country": "TH",
                "created_at": now_iso,
                "updated_at": now_iso,
                "attributes": {"make": None, "model": None, "color": None, "body_type": None},
                "observations": [],
            }
        else:
            record = existing
            record["updated_at"] = now_iso

        obs: dict[str, Any] = {
            "timestamp": now_iso,
            "source_image": str(original_path),
            "plate_crop": str(plate_crop_path) if plate_crop_path else None,
            "car_crop": str(car_crop_path) if car_crop_path else None,
            "confidence": {"plate": conf_f},
        }
        observations = record.get("observations")
        if not isinstance(observations, list):
            observations = []
        observations.append(obs)
        record["observations"] = observations

        _write_json_atomic(json_path, record)
        results.append(
            {
                "plate": plate,
                "json_path": json_path,
                "plate_crop": plate_crop_path,
                "car_crop": car_crop_path,
                "confidence": conf_f,
            }
        )

    await ws.send_json(
        {
            "type": "cars_ingest_result",
            "request_id": request_id,
            "ok": True,
            "original_path": original_path,
            "detector": detected,
            "items": results,
            "crops_written": crops_written,
            "instance_id": INSTANCE_ID,
        }
    )


def _asset_paths(asset_id: str) -> tuple[str, str]:
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(asset_id))
    blob_path = os.path.join(IMAGEN_ASSETS_DIR, f"{safe_id}.bin")
    meta_path = os.path.join(IMAGEN_ASSETS_DIR, f"{safe_id}.json")
    return blob_path, meta_path


@app.post("/imagen/generate", response_model=ImagenGenerateResponse)
async def imagen_generate(req: ImagenGenerateRequest) -> ImagenGenerateResponse:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")
    model = _imagen_allowed_model(req.model)

    _ensure_imagen_assets_dir()
    client = genai.Client(api_key=api_key)
    is_imagen = model.startswith("imagen-")
    try:
        if is_imagen:
            cfg = types.GenerateImagesConfig(
                number_of_images=max(1, min(int(req.number_of_images or 1), 4)),
                aspect_ratio=str(req.aspect_ratio) if req.aspect_ratio else None,
                image_size=str(req.image_size) if req.image_size else None,
                person_generation=str(req.person_generation) if req.person_generation else None,
            )
            res = await client.aio.models.generate_images(model=model, prompt=req.prompt, config=cfg)
            img_bytes, mime_type = _extract_generated_image(res)
        else:
            cfg2: dict[str, Any] = {"imageConfig": {}}
            if req.aspect_ratio:
                cfg2["imageConfig"]["aspectRatio"] = str(req.aspect_ratio)
            if req.image_size:
                cfg2["imageConfig"]["imageSize"] = str(req.image_size)
            if not cfg2["imageConfig"]:
                cfg2.pop("imageConfig", None)
            res = await client.aio.models.generate_content(model=model, contents=req.prompt, config=cfg2 or None)
            img_bytes, mime_type = _extract_inline_image(res)
    except Exception as e:
        classified = _classify_image_generation_error(str(e))
        if classified is not None:
            raise HTTPException(status_code=503, detail=classified)
        raise HTTPException(status_code=502, detail={"imagen_generate_failed": str(e)})
    import hashlib

    digest = hashlib.sha256(img_bytes).hexdigest()
    asset_id = f"img_{uuid.uuid4().hex[:24]}"
    blob_path, meta_path = _asset_paths(asset_id)
    with open(blob_path, "wb") as f:
        f.write(img_bytes)
    meta = {
        "asset_id": asset_id,
        "model": model,
        "mime_type": mime_type,
        "sha256": digest,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
        "image_size": req.image_size,
        "number_of_images": int(req.number_of_images or 1),
        "person_generation": req.person_generation,
        "created_at": int(time.time()),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    data_url = None
    if req.return_data_url:
        data_url = f"data:{mime_type};base64,{base64.b64encode(img_bytes).decode('ascii')}"
    return ImagenGenerateResponse(asset_id=asset_id, model=model, mime_type=mime_type, sha256=digest, data_url=data_url)


@app.post("/image/generate", response_model=ImageGenerateResponse)
async def image_generate(req: ImageGenerateRequest) -> ImageGenerateResponse:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="missing_api_key")
    model = _image_allowed_model(req.model)

    _ensure_imagen_assets_dir()
    client = genai.Client(api_key=api_key)
    try:
        cfg2: dict[str, Any] = {"imageConfig": {}}
        if req.aspect_ratio:
            cfg2["imageConfig"]["aspectRatio"] = str(req.aspect_ratio)
        if req.image_size:
            cfg2["imageConfig"]["imageSize"] = str(req.image_size)
        if not cfg2["imageConfig"]:
            cfg2.pop("imageConfig", None)
        res = await client.aio.models.generate_content(model=model, contents=req.prompt, config=cfg2 or None)
        img_bytes, mime_type = _extract_inline_image(res)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"image_generate_failed": str(e)})
    import hashlib

    digest = hashlib.sha256(img_bytes).hexdigest()
    asset_id = f"gimg_{uuid.uuid4().hex[:24]}"
    blob_path, meta_path = _asset_paths(asset_id)
    with open(blob_path, "wb") as f:
        f.write(img_bytes)
    meta = {
        "asset_id": asset_id,
        "model": model,
        "mime_type": mime_type,
        "sha256": digest,
        "prompt": req.prompt,
        "aspect_ratio": req.aspect_ratio,
        "image_size": req.image_size,
        "created_at": int(time.time()),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    data_url = None
    if req.return_data_url:
        data_url = f"data:{mime_type};base64,{base64.b64encode(img_bytes).decode('ascii')}"
    return ImageGenerateResponse(asset_id=asset_id, model=model, mime_type=mime_type, sha256=digest, data_url=data_url)


@app.get("/imagen/assets/{asset_id}/blob")
async def imagen_asset_blob(asset_id: str) -> Response:
    blob_path, _ = _asset_paths(asset_id)
    if not os.path.exists(blob_path):
        raise HTTPException(status_code=404, detail="asset_not_found")
    data = Path(blob_path).read_bytes()
    _, meta_path = _asset_paths(asset_id)
    mime_type = "application/octet-stream"
    try:
        if os.path.exists(meta_path):
            meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("mime_type"):
                mime_type = str(meta.get("mime_type"))
    except Exception:
        pass
    return Response(content=data, media_type=mime_type)


@app.get("/image/assets/{asset_id}/blob")
async def image_asset_blob(asset_id: str) -> Response:
    return await imagen_asset_blob(asset_id)


@app.get("/imagen/assets/{asset_id}")
async def imagen_asset_meta(asset_id: str) -> dict[str, Any]:
    _, meta_path = _asset_paths(asset_id)
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="asset_not_found")
    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"asset_meta_read_failed": str(e)})
    if not isinstance(meta, dict):
        raise HTTPException(status_code=500, detail="asset_meta_invalid")
    return meta


@app.get("/image/assets/{asset_id}")
async def image_asset_meta(asset_id: str) -> dict[str, Any]:
    return await imagen_asset_meta(asset_id)


def _init_session_db() -> None:
    os.makedirs(os.path.dirname(SESSION_DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              active_trip_id TEXT,
              active_trip_name TEXT,
              updated_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_writes (
              confirmation_id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              action TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at INTEGER NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
              reminder_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              dedupe_key TEXT,
              due_at INTEGER,
              timezone TEXT NOT NULL,
              schedule_type TEXT NOT NULL,
              notify_at INTEGER,
              hide_until INTEGER,
              status TEXT NOT NULL,
              source_text TEXT,
              aim_entity_name TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        # Index creation must tolerate older DBs missing newly added columns.
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_notify ON reminders(user_id, notify_at)")
        except Exception:
            pass
        # Backwards-compatible migration: ensure dedupe_key exists for older DBs.
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()]
            if "dedupe_key" not in cols:
                conn.execute("ALTER TABLE reminders ADD COLUMN dedupe_key TEXT")
        except Exception:
            pass

        # Backwards-compatible migration: allow notify_at to be nullable and add hide_until.
        # SQLite can't drop NOT NULL constraints, so we rebuild the table if needed.
        try:
            info = conn.execute("PRAGMA table_info(reminders)").fetchall() or []
            by_name = {str(r[1]): r for r in info if isinstance(r, (list, tuple)) and len(r) >= 4}
            notify_at_notnull = False
            if "notify_at" in by_name:
                try:
                    notify_at_notnull = bool(int(by_name["notify_at"][3]))
                except Exception:
                    notify_at_notnull = False

            if "hide_until" not in by_name or notify_at_notnull:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reminders_new (
                      reminder_id TEXT PRIMARY KEY,
                      user_id TEXT NOT NULL,
                      title TEXT NOT NULL,
                      dedupe_key TEXT,
                      due_at INTEGER,
                      timezone TEXT NOT NULL,
                      schedule_type TEXT NOT NULL,
                      notify_at INTEGER,
                      hide_until INTEGER,
                      status TEXT NOT NULL,
                      source_text TEXT,
                      aim_entity_name TEXT,
                      created_at INTEGER NOT NULL,
                      updated_at INTEGER NOT NULL
                    )
                    """
                )

                # Copy best-effort from old reminders table.
                cols_existing = [r[1] for r in info]
                has_hide_until = "hide_until" in cols_existing
                notify_at_expr = "notify_at"
                hide_until_expr = "hide_until" if has_hide_until else "NULL"

                conn.execute(
                    f"""
                    INSERT OR REPLACE INTO reminders_new(
                      reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, hide_until,
                      status, source_text, aim_entity_name, created_at, updated_at
                    )
                    SELECT reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, {notify_at_expr}, {hide_until_expr},
                           status, source_text, aim_entity_name, created_at, updated_at
                    FROM reminders
                    """
                )

                conn.execute("DROP TABLE reminders")
                conn.execute("ALTER TABLE reminders_new RENAME TO reminders")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_notify ON reminders(user_id, notify_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_hide_until ON reminders(user_id, hide_until)")
        except Exception as e:
            logger.warning("reminders_schema_migration_failed error=%s", str(e))

        # Ensure hide_until index exists (after migration) when the column is present.
        try:
            cols2 = [r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()]
            if "hide_until" in cols2:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_hide_until ON reminders(user_id, hide_until)")
        except Exception:
            pass
        # Prevent duplicates among pending reminders.
        # SQLite supports partial indexes (>= 3.8.0), which is the norm on modern distros.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_pending_dedupe ON reminders(user_id, dedupe_key) WHERE status = 'pending'"
            )
        except Exception:
            pass

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_status (
              user_id TEXT NOT NULL,
              agent_id TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(user_id, agent_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_status_user_updated ON agent_status(user_id, updated_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_cache (
              cache_key TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_cache_updated ON news_cache(updated_at)")
        conn.commit()


def _get_news_cache(cache_key: str) -> Optional[dict[str, Any]]:
    _init_session_db()
    k = str(cache_key or "").strip()
    if not k:
        return None
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT payload_json, updated_at FROM news_cache WHERE cache_key = ? LIMIT 1",
            (k,),
        )
        row = cur.fetchone()
    if not row:
        return None
    payload_json, updated_at = row
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    if isinstance(payload, dict):
        payload.setdefault("updated_at", updated_at)
    return {"cache_key": k, "payload": payload, "updated_at": updated_at}


def _set_news_cache(cache_key: str, payload: Any) -> dict[str, Any]:
    _init_session_db()
    k = str(cache_key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="missing_cache_key")
    now_ts = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO news_cache(cache_key, payload_json, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (k, payload_json, now_ts),
        )
        conn.commit()
    return {"ok": True, "cache_key": k, "updated_at": now_ts}


def _weaviate_enabled() -> bool:
    return bool(WEAVIATE_URL)


def _weaviate_object_uuid(external_key: str) -> str:
    # Deterministic UUID for idempotent upserts.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis::{external_key}"))


async def _gemini_embed_text(text: str) -> list[float]:
    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing required env var: API_KEY (or GEMINI_API_KEY)")
    client = genai.Client(api_key=api_key)
    # Embedding API surface and model availability can vary by google-genai version and API key.
    # Keep the calling convention stable (contents=...) and try a few model candidates.
    model_candidates = [
        str(GEMINI_EMBEDDING_MODEL or "").strip(),
        "text-embedding-004",
        "embedding-001",
    ]
    seen: set[str] = set()
    model_candidates = [m for m in model_candidates if m and not (m in seen or seen.add(m))]

    last_err: Exception | None = None
    for m in model_candidates:
        try:
            res = await client.aio.models.embed_content(model=m, contents=text)
            emb = getattr(res, "embedding", None)
            values = getattr(emb, "values", None)
            if isinstance(values, list) and values:
                return [float(x) for x in values]
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"gemini_embedding_failed: {last_err}" if last_err is not None else "gemini_embedding_failed")


def _pseudo_embed_vector(text: str, dim: int = 64) -> list[float]:
    # Deterministic, local-only fallback to keep Weaviate writes working when embedding providers are unavailable.
    # Not semantically meaningful like real embeddings, but stable for storage and basic similarity behavior.
    d = max(8, int(dim or 64))
    digest = hashlib.sha256(str(text or "").encode("utf-8")).digest()
    out: list[float] = []
    for i in range(d):
        b = digest[i % len(digest)]
        out.append((float(int(b)) / 255.0) * 2.0 - 1.0)
    return out


_embed_cache: dict[str, list[float]] = {}
_embed_cache_order: list[str] = []
_embed_cache_lock: asyncio.Lock = asyncio.Lock()


async def _gemini_embed_text_cached(text: str) -> list[float]:
    t = str(text or "").strip()
    if not t:
        return []

    max_items = int(JARVIS_EMBED_CACHE_MAX or 0)
    if max_items <= 0:
        return await _gemini_embed_text(t)

    async with _embed_cache_lock:
        cached = _embed_cache.get(t)
        if isinstance(cached, list) and cached:
            try:
                _embed_cache_order.remove(t)
            except Exception:
                pass
            _embed_cache_order.append(t)
            return cached

    vec = await _gemini_embed_text(t)

    async with _embed_cache_lock:
        _embed_cache[t] = vec
        try:
            _embed_cache_order.remove(t)
        except Exception:
            pass
        _embed_cache_order.append(t)

        # Simple LRU eviction.
        while len(_embed_cache_order) > max_items:
            oldest = _embed_cache_order.pop(0)
            try:
                _embed_cache.pop(oldest, None)
            except Exception:
                pass

    return vec


async def _weaviate_request(method: str, path: str, payload: Any = None) -> Any:
    if not _weaviate_enabled():
        raise HTTPException(status_code=500, detail="weaviate_not_configured")
    url = f"{WEAVIATE_URL}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.request(method, url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            # Preserve original status code so callers can handle 404 vs 500 etc.
            raise HTTPException(status_code=int(res.status_code), detail={"weaviate_error": detail})
        if not res.text:
            return None
        try:
            return res.json()
        except Exception:
            return res.text


async def _deep_research_worker_post(path: str, payload: Any) -> Any:
    if not DEEP_RESEARCH_WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="deep_research_worker_not_configured")
    url = f"{DEEP_RESEARCH_WORKER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


async def _deep_research_worker_get(path: str) -> Any:
    if not DEEP_RESEARCH_WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="deep_research_worker_not_configured")
    url = f"{DEEP_RESEARCH_WORKER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get(url)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


async def _weaviate_ensure_schema() -> None:
    global _weaviate_schema_ready
    if _weaviate_schema_ready:
        return
    if not _weaviate_enabled():
        return

    schema = {
        "class": "JarvisMemoryItem",
        "description": "Jarvis authoritative memory items (reminders, todos, notes, agent status).",
        "vectorizer": "none",
        "properties": [
            {"name": "external_key", "dataType": ["text"]},
            {"name": "kind", "dataType": ["text"]},
            {"name": "title", "dataType": ["text"]},
            {"name": "body", "dataType": ["text"]},
            {"name": "status", "dataType": ["text"]},
            {"name": "due_at", "dataType": ["number"]},
            {"name": "notify_at", "dataType": ["number"]},
            {"name": "timezone", "dataType": ["text"]},
            {"name": "source", "dataType": ["text"]},
            {"name": "created_at", "dataType": ["number"]},
            {"name": "updated_at", "dataType": ["number"]},
        ],
    }

    try:
        existing_schema = await _weaviate_request("GET", "/v1/schema/JarvisMemoryItem")
        try:
            props = existing_schema.get("properties") if isinstance(existing_schema, dict) else None
            prop_names = {str(p.get("name")) for p in props} if isinstance(props, list) else set()
            if "hide_until" not in prop_names:
                await _weaviate_request(
                    "POST",
                    "/v1/schema/JarvisMemoryItem/properties",
                    {"name": "hide_until", "dataType": ["number"]},
                )
        except Exception:
            pass
        _weaviate_schema_ready = True
        return
    except Exception:
        pass

    await _weaviate_request("POST", "/v1/schema", schema)
    _weaviate_schema_ready = True


async def _weaviate_upsert_memory_item(
    *,
    external_key: str,
    kind: str,
    title: str,
    body: str,
    status: str,
    due_at: Optional[int],
    notify_at: Optional[int],
    hide_until: Optional[int] = None,
    timezone_name: str,
    source: str,
) -> dict[str, Any]:
    await _weaviate_ensure_schema()
    now_ts = int(time.time())
    obj_id = _weaviate_object_uuid(external_key)

    vector_text = "\n".join([str(kind), str(title), str(body)]).strip()
    try:
        vector = await _gemini_embed_text_cached(vector_text)
    except Exception as e:
        logger.warning("weaviate_embed_failed_fallback error=%s", str(e))
        vector = _pseudo_embed_vector(vector_text)

    exists = False
    existing_created_at: Optional[float] = None
    try:
        existing = await _weaviate_request("GET", f"/v1/objects/JarvisMemoryItem/{obj_id}")
        if isinstance(existing, dict):
            exists = True
            props0 = existing.get("properties")
            if isinstance(props0, dict) and props0.get("created_at") is not None:
                try:
                    existing_created_at = float(props0.get("created_at"))
                except Exception:
                    existing_created_at = None
    except HTTPException as e:
        # 404 means this is a new object; we must create via POST /v1/objects.
        if int(getattr(e, "status_code", 0) or 0) != 404:
            raise
        exists = False
        existing_created_at = None
    except Exception:
        # Non-HTTP failures (e.g., network) should bubble up to the caller.
        raise

    props: dict[str, Any] = {
        "external_key": external_key,
        "kind": kind,
        "title": title,
        "body": body,
        "status": status,
        "timezone": timezone_name,
        "source": source,
        "updated_at": now_ts,
    }
    if due_at is not None:
        props["due_at"] = float(due_at)
    if notify_at is not None:
        props["notify_at"] = float(notify_at)
    if hide_until is not None:
        props["hide_until"] = float(hide_until)

    # First write uses created_at; subsequent writes keep the original created_at.
    if existing_created_at is not None:
        props["created_at"] = float(existing_created_at)
    else:
        props["created_at"] = float(now_ts)

    payload = {
        "class": "JarvisMemoryItem",
        "id": obj_id,
        "properties": props,
        "vector": vector,
    }

    if exists:
        await _weaviate_request("PUT", f"/v1/objects/JarvisMemoryItem/{obj_id}", payload)
    else:
        # Weaviate creates objects via POST /v1/objects. PUT /v1/objects/{id} only updates.
        await _weaviate_request("POST", "/v1/objects", payload)
    return {"id": obj_id, "external_key": external_key}


async def _weaviate_query_upcoming_reminders(*, start_ts: int, end_ts: int, limit: int) -> list[dict[str, Any]]:
    await _weaviate_ensure_schema()
    lim = max(1, min(int(limit or 50), 500))
    query = {
        "query": """
        {
          Get {
            JarvisMemoryItem(
              where: {
                operator: And
                operands: [
                  { path: [\"kind\"], operator: Equal, valueText: \"reminder\" }
                  { path: [\"status\"], operator: Equal, valueText: \"pending\" }
                  { path: [\"notify_at\"], operator: GreaterThanEqual, valueNumber: %START% }
                  { path: [\"notify_at\"], operator: LessThanEqual, valueNumber: %END% }
                ]
              }
              limit: %LIMIT%
            ) {
              external_key
              title
              body
              status
              due_at
              notify_at
              hide_until
              timezone
              updated_at
            }
          }
        }
        """
        .replace("%START%", str(float(int(start_ts))))
        .replace("%END%", str(float(int(end_ts))))
        .replace("%LIMIT%", str(int(lim)))
    }
    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoryItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


async def _weaviate_query_reminders(*, status: str, limit: int) -> list[dict[str, Any]]:
    await _weaviate_ensure_schema()
    lim = max(1, min(int(limit or 50), 500))
    status_norm = str(status or "all").strip().lower() or "all"
    if status_norm not in ("all", "pending", "fired", "done"):
        raise HTTPException(status_code=400, detail="invalid_status")

    where_status = "" if status_norm == "all" else f'{{ path: ["status"], operator: Equal, valueText: "{status_norm}" }}'
    operands = "\n".join(
        [
            '{ path: ["kind"], operator: Equal, valueText: "reminder" }',
            where_status,
        ]
    ).strip()
    # Remove any empty lines if status is all.
    operands = "\n".join([l for l in operands.splitlines() if l.strip()])

    query = {
        "query": f"""
        {{
          Get {{
            JarvisMemoryItem(
              where: {{
                operator: And
                operands: [
{operands}
                ]
              }}
              limit: {int(lim)}
              sort: [{{ path: [\"updated_at\"], order: desc }}]
            ) {{
              external_key
              title
              body
              status
              due_at
              notify_at
              hide_until
              timezone
              created_at
              updated_at
              source
            }}
          }}
        }}
        """
    }

    res = await _weaviate_request("POST", "/v1/graphql", query)
    items = (
        res.get("data", {})
        .get("Get", {})
        .get("JarvisMemoryItem", [])
        if isinstance(res, dict)
        else []
    )
    out: list[dict[str, Any]] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


def _local_reminder_id_from_external_key(external_key: str) -> str:
    s = str(external_key or "").strip()
    # Prefer decoding when possible to avoid generating new local ids for existing reminders.
    if s.startswith("reminder::"):
        tail = s[len("reminder::") :].strip()
        if tail:
            return tail
    # Stable local PK so restart sync can still upsert deterministically.
    u = uuid.uuid5(uuid.NAMESPACE_URL, f"jarvis_local::{s}")
    return f"r_{u.hex[:18]}"


def _upsert_local_reminder_from_memory_item(user_id: str, item: dict[str, Any]) -> Optional[str]:
    external_key = str(item.get("external_key") or "").strip()
    if not external_key:
        return None
    reminder_id = _local_reminder_id_from_external_key(external_key)
    title = str(item.get("title") or "Reminder").strip() or "Reminder"
    tz_name = str(item.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    schedule_type = "memory"
    source_text = str(item.get("body") or "").strip()

    due_at = item.get("due_at")
    notify_at = item.get("notify_at")
    try:
        due_at_ts = int(float(due_at)) if due_at is not None else None
    except Exception:
        due_at_ts = None
    try:
        notify_at_ts = int(float(notify_at)) if notify_at is not None else None
    except Exception:
        notify_at_ts = None

    if notify_at_ts is None:
        return None

    dedupe_key = _reminder_dedupe_key(title, due_at_ts, schedule_type)

    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reminders(
              reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, status,
              source_text, aim_entity_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(reminder_id) DO UPDATE SET
              title=excluded.title,
              dedupe_key=excluded.dedupe_key,
              due_at=excluded.due_at,
              timezone=excluded.timezone,
              schedule_type=excluded.schedule_type,
              notify_at=excluded.notify_at,
              status=excluded.status,
              source_text=excluded.source_text,
              updated_at=excluded.updated_at
            """,
            (
                reminder_id,
                user_id,
                title,
                dedupe_key,
                due_at_ts,
                tz_name,
                schedule_type,
                notify_at_ts,
                "pending",
                source_text,
                external_key,
                now_ts,
                now_ts,
            ),
        )
        conn.commit()
    return reminder_id


def _parse_agent_md(md_text: str) -> Optional[dict[str, Any]]:
    text = str(md_text or "")
    if not text.strip().startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    meta: dict[str, Any] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            key = str(k).strip()
            val = str(v).strip()
            if key:
                meta[key] = val
        i += 1

    if i >= len(lines) or lines[i].strip() != "---":
        return None

    body = "\n".join(lines[i + 1 :]).strip()
    if body:
        meta["body"] = body
    return meta


def _load_agent_defs() -> dict[str, dict[str, Any]]:
    defs: dict[str, dict[str, Any]] = {}
    root = Path(AGENTS_DIR)
    if not root.exists() or not root.is_dir():
        return defs

    for p in sorted(root.rglob("*.md")):
        try:
            md = p.read_text(encoding="utf-8")
        except Exception:
            continue
        parsed = _parse_agent_md(md)
        if not isinstance(parsed, dict):
            continue
        agent_id = str(parsed.get("id") or "").strip()
        if not agent_id:
            continue
        parsed["path"] = str(p)
        defs[agent_id] = parsed
    return defs


def _agents_snapshot() -> dict[str, dict[str, Any]]:
    global _agent_defs
    if not _agent_defs:
        _agent_defs = _load_agent_defs()
    return dict(_agent_defs)


def _agent_triggers_snapshot() -> dict[str, list[str]]:
    global _agent_triggers
    if _agent_triggers:
        return dict(_agent_triggers)

    agents = _agents_snapshot()
    out: dict[str, list[str]] = {}
    for agent_id, meta in agents.items():
        raw = meta.get("trigger_phrases")
        if raw is None:
            continue
        phrases: list[str] = []
        if isinstance(raw, str):
            # Support simple comma-separated values (frontmatter is parsed as strings).
            for part in raw.split(","):
                p = part.strip()
                if p:
                    phrases.append(p)
        if phrases:
            out[agent_id] = phrases
    _agent_triggers = out
    return dict(_agent_triggers)


def _upsert_agent_status(user_id: str, agent_id: str, payload: Any) -> None:
    _init_session_db()
    now_ts = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO agent_status(user_id, agent_id, payload_json, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id, agent_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (user_id, agent_id, payload_json, now_ts),
        )
        conn.commit()


def _get_agent_statuses(user_id: str) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT agent_id, payload_json, updated_at FROM agent_status WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for agent_id, payload_json, updated_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append({"agent_id": agent_id, "payload": payload, "updated_at": updated_at})
    return out


def _list_upcoming_pending_reminders(
    *,
    user_id: str,
    start_ts: int,
    end_ts: int,
    time_field: str,
    limit: int,
) -> list[dict[str, Any]]:
    _init_session_db()
    field = str(time_field or "notify_at").strip().lower() or "notify_at"
    if field not in ("notify_at", "due_at"):
        raise HTTPException(status_code=400, detail="invalid_time_field")

    start_v = int(start_ts)
    end_v = int(end_ts)
    if end_v < start_v:
        raise HTTPException(status_code=400, detail="invalid_time_window")

    lim = max(1, min(int(limit or 50), 500))

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        now_ts = int(time.time())
        cur = conn.execute(
            f"""
            SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, source_text, aim_entity_name
            FROM reminders
            WHERE user_id = ?
              AND status = 'pending'
              AND {field} IS NOT NULL
              AND (hide_until IS NULL OR hide_until <= ?)
              AND {field} >= ?
              AND {field} <= ?
            ORDER BY {field} ASC
            LIMIT ?
            """,
            (user_id, now_ts, start_v, end_v, lim),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for reminder_id, title, due_at, tz_name, schedule_type, notify_at, source_text, aim_entity_name in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
            }
        )
    return out


def _list_reminders(
    *,
    user_id: str,
    status: str,
    limit: int,
    offset: int,
    order: str,
    include_hidden: bool,
) -> list[dict[str, Any]]:
    _init_session_db()
    status_norm = str(status or "all").strip().lower() or "all"
    order_norm = str(order or "desc").strip().lower() or "desc"
    lim = max(1, min(int(limit or 50), 500))
    off = max(0, int(offset or 0))

    if status_norm not in ("all", "pending", "fired", "done"):
        raise HTTPException(status_code=400, detail="invalid_status")
    if order_norm not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="invalid_order")

    status_clause = ""
    params: list[Any] = [user_id]
    if status_norm != "all":
        status_clause = " AND status = ?"
        params.append(status_norm)

    hidden_clause = ""
    if not bool(include_hidden):
        now_ts = int(time.time())
        hidden_clause = " AND (hide_until IS NULL OR hide_until <= ?)"
        params.append(now_ts)

    sql = (
        "SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, hide_until, status, source_text, aim_entity_name, created_at, updated_at "
        "FROM reminders "
        "WHERE user_id = ?" + status_clause + hidden_clause + " "
        f"ORDER BY updated_at {order_norm.upper()} "
        "LIMIT ? OFFSET ?"
    )
    params.extend([lim, off])

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for (
        reminder_id,
        title,
        due_at,
        tz_name,
        schedule_type,
        notify_at,
        hide_until,
        status_value,
        source_text,
        aim_entity_name,
        created_at,
        updated_at,
    ) in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "hide_until": hide_until,
                "status": status_value,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    return out


async def _render_daily_brief(user_id: str) -> dict[str, Any]:
    agents = _agents_snapshot()
    statuses = _get_agent_statuses(user_id)
    status_by_agent: dict[str, dict[str, Any]] = {}
    for s in statuses:
        aid = str(s.get("agent_id") or "").strip()
        if aid and aid not in status_by_agent:
            status_by_agent[aid] = s

    now_ts = int(time.time())
    upcoming_reminders: list[dict[str, Any]] = []
    if _weaviate_enabled():
        try:
            upcoming_reminders = await _weaviate_query_upcoming_reminders(
                start_ts=now_ts,
                end_ts=now_ts + 24 * 3600,
                limit=50,
            )
        except Exception:
            upcoming_reminders = []
    if not upcoming_reminders:
        upcoming_reminders = _list_upcoming_pending_reminders(
            user_id=user_id,
            start_ts=now_ts,
            end_ts=now_ts + 24 * 3600,
            time_field="notify_at",
            limit=50,
        )

    lines: list[str] = []
    lines.append(f"Daily Brief ({datetime.now(tz=_get_user_timezone(user_id)).isoformat()})")

    lines.append("\nAgents")
    for agent_id in sorted(agents.keys()):
        name = str(agents[agent_id].get("name") or agent_id)
        s = status_by_agent.get(agent_id)
        if not s:
            lines.append(f"- {name}: no recent status")
            continue
        payload = s.get("payload")
        summary = ""
        if isinstance(payload, dict):
            summary = str(payload.get("summary") or payload.get("status") or "").strip()
        updated_at = int(s.get("updated_at") or 0)
        when = datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat() if updated_at else ""
        if summary:
            lines.append(f"- {name}: {summary} ({when})")
        else:
            lines.append(f"- {name}: updated ({when})")

    if upcoming_reminders:
        lines.append("\nReminders (next 24h)")
        for r in upcoming_reminders[:20]:
            title = str(r.get("title") or "").strip() or "Reminder"
            notify_at = r.get("notify_at")
            due_at = r.get("due_at")
            lines.append(f"- {title} (notify_at={notify_at}, due_at={due_at})")

    return {
        "user_id": user_id,
        "generated_at": int(time.time()),
        "agent_count": len(agents),
        "status_count": len(statuses),
        "brief_text": "\n".join(lines).strip(),
    }


def _extract_reminder_setup_title(text: str) -> str:
    s = str(text or "").strip()
    m = re.search(r"\breminder\s+setup\b\s*[:\-]?\s*(.*)$", s, flags=re.IGNORECASE)
    tail = ""
    if m:
        tail = str(m.group(1) or "").strip()
    else:
        # Also support the shorter colon form.
        m2 = re.search(r"\breminder\b\s*[:\-]\s*(.*)$", s, flags=re.IGNORECASE)
        if m2:
            tail = str(m2.group(1) or "").strip()

    if not tail:
        # Thai variants (keep loose spacing). Examples:
        # - สร้างแจ้งเตือนใหม่ พรุ่งนี้ 9 โมง ...
        # - แจ้งเตือน: พรุ่งนี้ ...
        # - ตั้งเตือน: ...
        m_th = re.search(r"^(?:สร้าง\s*)?แจ้งเตือน(?:\s*ใหม่)?\s*[:\-]?\s*(.*)$", s)
        if m_th:
            tail = str(m_th.group(1) or "").strip()
        else:
            m_th2 = re.search(r"^ตั้ง\s*เตือน\s*[:\-]?\s*(.*)$", s)
            if m_th2:
                tail = str(m_th2.group(1) or "").strip()

    if not tail:
        return "Reminder"

    # Keep titles short and stable.
    return tail[:120]


def _parse_reminder_helper_command(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "args": {}}

    def after(prefix: str) -> str:
        if s.startswith(prefix + ":"):
            return raw.split(":", 1)[1].strip()
        if s.startswith(prefix + " "):
            return raw[len(prefix) :].strip()
        return ""

    # English
    if s.startswith("reminder add"):
        return {"action": "add", "args": {"text": after("reminder add")}}
    if s.startswith("reminder done"):
        return {"action": "done", "args": {"reminder_id": after("reminder done")}}
    if s.startswith("reminder later"):
        tail = after("reminder later")
        parts = tail.split()
        rid = parts[0].strip() if parts else ""
        days = None
        if len(parts) >= 2:
            try:
                days = int(parts[1])
            except Exception:
                days = None
        return {"action": "later", "args": {"reminder_id": rid, "days": days}}
    if s.startswith("reminder reschedule"):
        tail = after("reminder reschedule")
        parts = tail.split(" ", 1)
        rid = parts[0].strip() if parts else ""
        when = parts[1].strip() if len(parts) > 1 else ""
        return {"action": "reschedule", "args": {"reminder_id": rid, "when": when}}
    if s.startswith("reminder delete"):
        return {"action": "delete", "args": {"reminder_id": after("reminder delete")}}
    if s.startswith("reminder list"):
        tail = after("reminder list")
        tail_s = " ".join(tail.lower().split())
        status = "pending" if "pending" in tail_s else "all" if tail_s else "pending"
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden}}

    # Thai aliases
    if s.startswith("เตือน เพิ่ม"):
        return {"action": "add", "args": {"text": after("เตือน เพิ่ม")}}
    if s.startswith("เตือน เสร็จ"):
        return {"action": "done", "args": {"reminder_id": after("เตือน เสร็จ")}}
    if s.startswith("เตือน ลบ"):
        return {"action": "delete", "args": {"reminder_id": after("เตือน ลบ")}}
    if s.startswith("เตือน เลื่อน"):
        tail = after("เตือน เลื่อน")
        parts = tail.split(" ", 1)
        rid = parts[0].strip() if parts else ""
        when = parts[1].strip() if len(parts) > 1 else ""
        return {"action": "reschedule", "args": {"reminder_id": rid, "when": when}}
    if s.startswith("เตือน รายการ"):
        tail = after("เตือน รายการ")
        tail_s = " ".join(tail.lower().split())
        status = "pending" if "pending" in tail_s else "all" if tail_s else "pending"
        include_hidden = "include_hidden" in tail_s or "hidden" in tail_s
        return {"action": "list", "args": {"status": status, "include_hidden": include_hidden}}

    return {"action": "", "args": {}}


async def _handle_reminder_helper_trigger(ws: WebSocket, text: str) -> bool:
    cmd = _parse_reminder_helper_command(text)
    action = str(cmd.get("action") or "")
    args = cmd.get("args") if isinstance(cmd.get("args"), dict) else {}
    if not action:
        return False

    if action == "add":
        payload = str(args.get("text") or "").strip()
        if not payload:
            await ws.send_json({"type": "reminder_helper_error", "message": "missing_text"})
            return True
        handled = await _handle_reminder_setup_trigger(ws, f"reminder setup: {payload}")
        if not handled:
            await ws.send_json({"type": "reminder_helper_error", "message": "add_failed"})
        return True

    if action == "list":
        status = str(args.get("status") or "pending")
        include_hidden = bool(args.get("include_hidden"))
        items: list[dict[str, Any]] = []
        if _weaviate_enabled():
            try:
                now_ts = int(time.time())
                wv_items = await _weaviate_query_reminders(status=status, limit=50)
                for it in wv_items:
                    title = str(it.get("title") or "Reminder").strip() or "Reminder"
                    tz_name = str(it.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
                    hide_until = int(float(it["hide_until"])) if it.get("hide_until") is not None else None
                    if (not include_hidden) and hide_until is not None and hide_until > now_ts:
                        continue
                    items.append(
                        {
                            "reminder_id": _local_reminder_id_from_external_key(str(it.get("external_key") or "")),
                            "title": title,
                            "due_at": int(float(it["due_at"])) if it.get("due_at") is not None else None,
                            "timezone": tz_name,
                            "schedule_type": "memory",
                            "notify_at": int(float(it["notify_at"])) if it.get("notify_at") is not None else None,
                            "hide_until": hide_until,
                            "status": str(it.get("status") or "").strip() or "pending",
                            "source_text": str(it.get("body") or ""),
                            "aim_entity_name": str(it.get("external_key") or ""),
                            "created_at": int(float(it["created_at"])) if it.get("created_at") is not None else None,
                            "updated_at": int(float(it["updated_at"])) if it.get("updated_at") is not None else None,
                        }
                    )
            except Exception:
                items = []

        if not items:
            items = _list_reminders(
                user_id=DEFAULT_USER_ID,
                status=status,
                limit=50,
                offset=0,
                order="desc",
                include_hidden=include_hidden,
            )
        await ws.send_json(
            {
                "type": "reminder_helper_list",
                "status": status,
                "include_hidden": include_hidden,
                "reminders": items,
                "instance_id": INSTANCE_ID,
            }
        )
        return True

    rid = str(args.get("reminder_id") or "").strip()
    if not rid:
        await ws.send_json({"type": "reminder_helper_error", "message": "missing_reminder_id"})
        return True

    if action == "done":
        changed = _mark_reminder_done(rid)
        wv: Optional[dict[str, Any]] = None
        if _weaviate_enabled():
            try:
                wv = await _mark_reminder_done_weaviate(rid)
            except Exception as e:
                wv = {"ok": False, "error": str(e)}
        await ws.send_json({"type": "reminder_helper_done", "reminder_id": rid, "changed": changed, "weaviate": wv})
        return True

    if action == "later":
        days_v = args.get("days")
        days = 1
        if days_v is not None:
            try:
                days = max(1, int(days_v))
            except Exception:
                days = 1
        tz = _get_user_timezone(DEFAULT_USER_ID)
        now = datetime.now(tz=timezone.utc)
        hide_until_local = _default_hide_until(now, tz, days_ahead=days)
        hide_until_ts = int(hide_until_local.astimezone(timezone.utc).timestamp())
        changed = _set_reminder_hide_until(rid, hide_until_ts)
        wv: Optional[dict[str, Any]] = None
        if _weaviate_enabled():
            try:
                local = _get_local_reminder_by_id(rid) or {}
                if not local:
                    raise HTTPException(status_code=404, detail="reminder_not_found")
                external_key = str(local.get("aim_entity_name") or "").strip() or f"reminder::{rid}"
                tz_name = str(local.get("timezone") or tz.key)
                wv = await _weaviate_upsert_memory_item(
                    external_key=external_key,
                    kind="reminder",
                    title=str(local.get("title") or "Reminder"),
                    body=str(local.get("source_text") or ""),
                    status=str(local.get("status") or "pending"),
                    due_at=int(local.get("due_at")) if local.get("due_at") is not None else None,
                    notify_at=int(local.get("notify_at")) if local.get("notify_at") is not None else None,
                    hide_until=hide_until_ts,
                    timezone_name=tz_name,
                    source="jarvis",
                )
            except Exception as e:
                wv = {"ok": False, "error": str(e)}
        await ws.send_json({"type": "reminder_helper_later", "reminder_id": rid, "hide_until": hide_until_ts, "changed": changed, "weaviate": wv})
        return True

    if action == "reschedule":
        when = str(args.get("when") or "").strip()
        if not when:
            await ws.send_json({"type": "reminder_helper_error", "message": "missing_time_text"})
            return True
        tz = _get_user_timezone(DEFAULT_USER_ID)
        now = datetime.now(tz=timezone.utc)
        due_at_utc, local_iso = _parse_time_from_text(when, now, tz)
        if due_at_utc is None:
            await ws.send_json({"type": "reminder_helper_error", "message": "time_parse_failed", "hint": "Try: today 17:00 | tomorrow 09:00"})
            return True
        notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
        notify_at_ts = int(notify_at_local.astimezone(timezone.utc).timestamp())
        changed = _set_reminder_notify_at(rid, notify_at_ts)
        _set_reminder_hide_until(rid, None)
        wv: Optional[dict[str, Any]] = None
        if _weaviate_enabled():
            try:
                local = _get_local_reminder_by_id(rid) or {}
                if not local:
                    raise HTTPException(status_code=404, detail="reminder_not_found")
                tz_name = str(local.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
                external_key = str(local.get("aim_entity_name") or "").strip() or f"reminder::{rid}"
                wv = await _weaviate_upsert_memory_item(
                    external_key=external_key,
                    kind="reminder",
                    title=str(local.get("title") or "Reminder"),
                    body=str(local.get("source_text") or ""),
                    status=str(local.get("status") or "pending"),
                    due_at=int(local.get("due_at")) if local.get("due_at") is not None else None,
                    notify_at=notify_at_ts,
                    hide_until=None,
                    timezone_name=tz_name,
                    source="jarvis",
                )
            except Exception as e:
                wv = {"ok": False, "error": str(e)}
        await ws.send_json(
            {
                "type": "reminder_helper_reschedule",
                "reminder_id": rid,
                "notify_at": notify_at_ts,
                "local_time": local_iso,
                "changed": changed,
                "weaviate": wv,
            }
        )
        return True

    if action == "delete":
        changed = _delete_reminder_local(rid)
        wv: Optional[dict[str, Any]] = None
        if _weaviate_enabled():
            try:
                wv = await _mark_reminder_done_weaviate(rid)
            except Exception as e:
                wv = {"ok": False, "error": str(e)}
        await ws.send_json({"type": "reminder_helper_delete", "reminder_id": rid, "changed": changed, "weaviate": wv})
        return True

    await ws.send_json({"type": "reminder_helper_error", "message": "unknown_action", "action": action})
    return True


async def _improve_reminder_title(*, raw_title: str, source_text: str) -> str:
    title = str(raw_title or "").strip() or "Reminder"
    src = str(source_text or "").strip()
    if not src or not title:
        return title[:120]

    api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return title[:120]

    prompt = (
        "Rewrite the reminder title to be clear, concise, and actionable. "
        "Preserve the user's language (Thai stays Thai). "
        "Keep it under 80 characters. Output ONLY the title.\n\n"
        f"User text: {src}\n"
        f"Current title: {title}\n"
    )

    try:
        client = genai.Client(api_key=api_key)

        async def _run(model_name: str) -> str:
            res = await client.aio.models.generate_content(model=model_name, contents=prompt)
            txt = getattr(res, "text", None)
            if txt is None:
                try:
                    txt = str(res)
                except Exception:
                    txt = ""
            cleaned = " ".join(str(txt or "").strip().split())
            if not cleaned:
                return title
            if len(cleaned) > 120:
                cleaned = cleaned[:120].rstrip()
            return cleaned

        last_err: Exception | None = None
        for model_name in REMINDER_TITLE_MODELS:
            try:
                improved = await asyncio.wait_for(_run(model_name), timeout=2.5)
                return str(improved or title).strip()[:120] or "Reminder"
            except Exception as e:
                last_err = e
                msg = str(e)
                lower = msg.lower()
                retryable = any(
                    k in lower
                    for k in [
                        "resource_exhausted",
                        "quota",
                        "rate",
                        "429",
                        "not found",
                        "model",
                        "permission",
                        "403",
                        "404",
                        "unavailable",
                        "503",
                        "500",
                        "timeout",
                    ]
                )
                if retryable:
                    continue
                raise

        if last_err is not None:
            logger.warning("reminder_title_rewrite_failed: %s", last_err)
        return title[:120]
    except Exception:
        return title[:120]


async def _handle_reminder_setup_trigger(ws: WebSocket, text: str) -> bool:
    title = _extract_reminder_setup_title(text)
    title = await _improve_reminder_title(raw_title=title, source_text=text)
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(text, now, tz)
    if due_at_utc is None:
        ws.state.pending_reminder_setup = {
            "title": title,
            "source_text": text,
            "timezone": tz.key,
            "created_at": int(time.time()),
        }
        logger.info("reminder_setup_draft_emit title=%s", title)
        await ws.send_json(
            {
                "type": "reminder_setup_draft",
                "title": title,
                "result": {
                    "ok": True,
                    "needs_time": True,
                    "hint": "Confirm before creating. Reply: reminder confirm: <when>  (or: reminder confirm  / reminder cancel)",
                },
                "instance_id": INSTANCE_ID,
            }
        )
        try:
            await _live_say(
                ws,
                f"I drafted a reminder: {title}. Say 'reminder confirm' with a time, or say 'reminder cancel'.",
            )
        except Exception:
            pass
        return True

    # Weaviate-authoritative: write local first for reliability, then write-through to Weaviate.
    schedule_type = "morning_brief"
    notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
    notify_at_utc = notify_at_local.astimezone(timezone.utc)
    external_key: Optional[str] = None

    reminder_id = _create_reminder(
        user_id=DEFAULT_USER_ID,
        title=title,
        due_at_utc=due_at_utc,
        tz=tz,
        schedule_type=schedule_type,
        notify_at_utc=notify_at_utc,
        source_text=text,
        aim_entity_name=None,
    )

    external_key = f"reminder::{reminder_id}"

    result: Any = {
        "ok": True,
        "reminder": {
            "reminder_id": reminder_id,
            "schedule_type": schedule_type,
            "due_at_utc": due_at_utc.replace(tzinfo=timezone.utc).isoformat(),
            "local_time": local_iso,
            "timezone": tz.key,
        },
    }

    if _weaviate_enabled():
        try:
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=title,
                body=text,
                status="pending",
                due_at=int(due_at_utc.timestamp()),
                notify_at=int(notify_at_utc.timestamp()),
                hide_until=None,
                timezone_name=tz.key,
                source="jarvis",
            )
            # Store a stable mapping for later debug/sync.
            try:
                _init_session_db()
                with sqlite3.connect(SESSION_DB_PATH) as conn:
                    conn.execute(
                        "UPDATE reminders SET aim_entity_name = ?, updated_at = ? WHERE reminder_id = ?",
                        (external_key, int(time.time()), reminder_id),
                    )
                    conn.commit()
            except Exception:
                pass
            result = {**result, "weaviate": wv}
        except Exception as e:
            result = {**result, "weaviate": {"ok": False, "error": str(e)}}

    _upsert_agent_status(
        DEFAULT_USER_ID,
        "reminder-setup",
        {
            "summary": f"created reminder: {title}",
            "reminder_id": reminder_id,
            "result": result,
            "updated_at": int(time.time()),
        },
    )

    await ws.send_json(
        {
            "type": "reminder_setup",
            "title": title,
            "reminder_id": reminder_id,
            "result": result,
        }
    )
    return True


async def _handle_pending_reminder_confirm_or_cancel(ws: WebSocket, text: str) -> bool:
    pending = getattr(ws.state, "pending_reminder_setup", None)
    if not isinstance(pending, dict):
        return False

    s = " ".join(str(text or "").strip().split())
    lower = s.lower()
    if not (lower.startswith("reminder confirm") or lower.startswith("reminder cancel")):
        return False

    if lower.startswith("reminder cancel"):
        ws.state.pending_reminder_setup = None
        await ws.send_json({"type": "reminder_setup_cancelled", "instance_id": INSTANCE_ID})
        try:
            await _live_say(ws, "Okay. I cancelled that reminder draft.")
        except Exception:
            pass
        return True

    when = ""
    m = re.search(r"^reminder\s+confirm\s*[:\-]?\s*(.*)$", s, flags=re.IGNORECASE)
    if m:
        when = str(m.group(1) or "").strip()

    title = str(pending.get("title") or "Reminder").strip() or "Reminder"
    source_text = str(pending.get("source_text") or "").strip()
    tz_name = str(pending.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz=timezone.utc)

    due_at_utc: Optional[datetime] = None
    local_iso: Optional[str] = None
    if when:
        due_at_utc, local_iso = _parse_time_from_text(when, now, tz)

    if due_at_utc is None:
        reminder_id = _create_reminder(
            user_id=DEFAULT_USER_ID,
            title=title,
            due_at_utc=None,
            tz=tz,
            schedule_type="unscheduled",
            notify_at_utc=None,
            source_text=source_text or s,
            aim_entity_name=None,
        )
        external_key = f"reminder::{reminder_id}"
        if _weaviate_enabled():
            try:
                await _weaviate_upsert_memory_item(
                    external_key=external_key,
                    kind="reminder",
                    title=title,
                    body=source_text or s,
                    status="pending",
                    due_at=None,
                    notify_at=None,
                    hide_until=None,
                    timezone_name=tz.key,
                    source="jarvis",
                )
            except Exception:
                pass
        ws.state.pending_reminder_setup = None
        await ws.send_json(
            {
                "type": "reminder_setup",
                "title": title,
                "reminder_id": reminder_id,
                "result": {
                    "ok": True,
                    "reminder": {"reminder_id": reminder_id, "schedule_type": "unscheduled", "timezone": tz.key},
                    "needs_time": True,
                    "hint": "Set a time (e.g. today 17:00 or tomorrow 09:00).",
                },
                "instance_id": INSTANCE_ID,
            }
        )
        try:
            await _live_say(ws, f"Confirmed. I created the reminder: {title}. Please tell me what time.")
        except Exception:
            pass
        return True

    schedule_type = "morning_brief"
    notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
    notify_at_utc = notify_at_local.astimezone(timezone.utc)
    reminder_id = _create_reminder(
        user_id=DEFAULT_USER_ID,
        title=title,
        due_at_utc=due_at_utc,
        tz=tz,
        schedule_type=schedule_type,
        notify_at_utc=notify_at_utc,
        source_text=source_text or s,
        aim_entity_name=None,
    )

    external_key = f"reminder::{reminder_id}"
    result: Any = {
        "ok": True,
        "reminder": {
            "reminder_id": reminder_id,
            "schedule_type": schedule_type,
            "due_at_utc": due_at_utc.replace(tzinfo=timezone.utc).isoformat(),
            "local_time": local_iso,
            "timezone": tz.key,
        },
    }
    if _weaviate_enabled():
        try:
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=title,
                body=source_text or s,
                status="pending",
                due_at=int(due_at_utc.timestamp()),
                notify_at=int(notify_at_utc.timestamp()),
                hide_until=None,
                timezone_name=tz.key,
                source="jarvis",
            )
            result = {**result, "weaviate": wv}
        except Exception as e:
            result = {**result, "weaviate": {"ok": False, "error": str(e)}}

    ws.state.pending_reminder_setup = None
    await ws.send_json(
        {
            "type": "reminder_setup",
            "title": title,
            "reminder_id": reminder_id,
            "result": result,
            "instance_id": INSTANCE_ID,
        }
    )
    try:
        await _live_say(ws, f"Confirmed. I created the reminder: {title}.")
    except Exception:
        pass
    return True


async def _startup_resync_from_weaviate() -> None:
    if not _weaviate_enabled():
        return
    try:
        now_ts = int(time.time())
        # Keep local scheduler warm for the next 7 days.
        items = await _weaviate_query_upcoming_reminders(
            start_ts=now_ts,
            end_ts=now_ts + 7 * 24 * 3600,
            limit=500,
        )
        for it in items:
            _upsert_local_reminder_from_memory_item(DEFAULT_USER_ID, it)
    except Exception as e:
        logger.warning("weaviate_startup_resync_failed error=%s", e)


def _parse_news_follow_command(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "arg": ""}

    # English focus commands
    if s == "focus list" or s == "list focus":
        return {"action": "focus_list", "arg": ""}
    if s.startswith("focus add:") or s.startswith("focus add "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_add", "arg": arg}
    if s.startswith("focus remove:") or s.startswith("focus remove "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_remove", "arg": arg}

    if s.startswith("โฟกัสข่าว เพิ่ม:") or s.startswith("โฟกัสข่าว เพิ่ม "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_add", "arg": arg}
    if s.startswith("เพิ่มโฟกัสข่าว:") or s.startswith("เพิ่มโฟกัสข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "focus_add", "arg": arg}

    if s.startswith("โฟกัสข่าว ลบ:") or s.startswith("โฟกัสข่าว ลบ "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "focus_remove", "arg": arg}
    if s.startswith("ลบโฟกัสข่าว:") or s.startswith("ลบโฟกัสข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "focus_remove", "arg": arg}

    if s == "โฟกัสข่าว" or s == "รายการโฟกัสข่าว":
        return {"action": "focus_list", "arg": ""}

    if s.startswith("รายงานข่าว:") or s.startswith("รายงานข่าว "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "report", "arg": arg}

    if s.startswith("report:") or s.startswith("report "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip() if len(raw.split()) >= 2 else ""
        return {"action": "report", "arg": arg}

    if "รีเฟรช" in s or "refresh" in s:
        if "ติดตามข่าว" in s or "follow_news" in s or "follow news" in s or "track news" in s:
            return {"action": "refresh", "arg": ""}

    if "ติดตามข่าว" in s or "สรุปข่าวติดตาม" in s or "follow_news" in s or "follow news" in s or "news follow" in s or "track news" in s:
        return {"action": "list", "arg": ""}

    return {"action": "", "arg": ""}


def _news_follow_cache_key_focus(user_id: str) -> str:
    return f"news-follow::{user_id}::focus"


def _news_follow_cache_key_summaries(user_id: str) -> str:
    return f"news-follow::{user_id}::summaries"


def _get_news_follow_focus(user_id: str) -> list[str]:
    cached = _get_news_cache(_news_follow_cache_key_focus(user_id))
    payload = cached.get("payload") if isinstance(cached, dict) else None
    focus = payload.get("focus") if isinstance(payload, dict) else None
    if isinstance(focus, list):
        out: list[str] = []
        seen: set[str] = set()
        for f in focus:
            t = str(f or "").strip()
            k = t.lower()
            if t and k not in seen:
                seen.add(k)
                out.append(t)
        return out
    return ["Thai Baht", "USD/THB", "gold", "oil", "Iran"]


def _set_news_follow_focus(user_id: str, focus: list[str]) -> None:
    _set_news_cache(_news_follow_cache_key_focus(user_id), {"focus": focus, "updated_at": int(time.time())})


def _get_news_follow_summaries(user_id: str) -> list[dict[str, Any]]:
    cached = _get_news_cache(_news_follow_cache_key_summaries(user_id))
    payload = cached.get("payload") if isinstance(cached, dict) else None
    items = payload.get("summaries") if isinstance(payload, dict) else None
    if isinstance(items, list):
        out: list[dict[str, Any]] = []
        for it in items:
            if isinstance(it, dict):
                out.append(it)
        return out
    return []


def _set_news_follow_summaries(user_id: str, summaries: list[dict[str, Any]]) -> None:
    _set_news_cache(_news_follow_cache_key_summaries(user_id), {"summaries": summaries, "updated_at": int(time.time())})


async def _refresh_news_follow_summaries(user_id: str, focus: list[str]) -> dict[str, Any]:
    feeds = [
        "https://rss.cnn.com/rss/edition.rss",
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://rss.cnn.com/rss/money_latest.rss",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
    ]
    all_items: list[dict[str, Any]] = []
    for url in feeds:
        xml_text = await _mcp_web_fetch_text(url, max_length=250000)
        all_items.extend(_parse_rss_items(xml_text))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in all_items:
        key = str(it.get("link") or "") or str(it.get("title") or "")
        key = key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    focus_norm = [str(f or "").strip() for f in focus if str(f or "").strip()]
    matched: list[dict[str, Any]] = []
    for it in deduped:
        blob = f"{it.get('title','')} {it.get('description','')}"
        if _topic_match(blob, focus_norm):
            matched.append(it)

    sources: list[str] = []
    lines: list[str] = []
    for it in matched[:20]:
        title = str(it.get("title") or "").strip()
        link = str(it.get("link") or "").strip()
        if link and link not in sources:
            sources.append(link)
        if title:
            if link:
                lines.append(f"- {title} ({link})")
            else:
                lines.append(f"- {title}")

    summary_text = "\n".join(lines).strip()
    now_ts = int(time.time())
    summary_id = f"nf_{uuid.uuid4().hex[:12]}"
    summary_obj = {
        "summary_id": summary_id,
        "title": "ติดตามข่าว: สรุปล่าสุด",
        "focus": focus_norm,
        "text": summary_text,
        "sources": sources,
        "created_at": now_ts,
    }

    summaries = _get_news_follow_summaries(user_id)
    summaries = [summary_obj] + [s for s in summaries if isinstance(s, dict) and str(s.get("summary_id") or "") != summary_id]
    summaries = summaries[:20]
    _set_news_follow_summaries(user_id, summaries)
    payload = {"summary": "news-follow refreshed", "focus": focus_norm, "summaries": summaries, "updated_at": now_ts}
    _upsert_agent_status(user_id, "follow_news", payload)
    return payload


async def _handle_news_follow_trigger(ws: WebSocket, text: str) -> bool:
    cmd = _parse_news_follow_command(text)
    action = cmd.get("action") or ""
    arg = cmd.get("arg") or ""

    s = " ".join(str(text or "").lower().split())
    is_trigger = action != "" or ("ติดตามข่าว" in s) or ("โฟกัสข่าว" in s) or ("follow_news" in s) or ("follow news" in s) or ("news follow" in s) or ("track news" in s)
    if not is_trigger:
        return False

    user_id = DEFAULT_USER_ID
    focus = _get_news_follow_focus(user_id)
    summaries = _get_news_follow_summaries(user_id)

    if action == "focus_list":
        await ws.send_json({"type": "news_follow_focus", "focus": focus})
        return True

    if action == "focus_add":
        item = str(arg or "").strip()
        if not item:
            await ws.send_json({"type": "news_follow_error", "message": "missing_focus_item"})
            return True
        new_focus = focus + [item]
        _set_news_follow_focus(user_id, new_focus)
        await ws.send_json({"type": "news_follow_focus_updated", "focus": _get_news_follow_focus(user_id)})
        return True

    if action == "focus_remove":
        item = str(arg or "").strip().lower()
        if not item:
            await ws.send_json({"type": "news_follow_error", "message": "missing_focus_item"})
            return True
        new_focus = [f for f in focus if str(f or "").strip().lower() != item]
        _set_news_follow_focus(user_id, new_focus)
        await ws.send_json({"type": "news_follow_focus_updated", "focus": _get_news_follow_focus(user_id)})
        return True

    if action == "refresh":
        payload = await _refresh_news_follow_summaries(user_id, focus)
        await ws.send_json({"type": "news_follow_refreshed", "status": payload})
        return True

    if action == "report":
        target = str(arg or "").strip()
        if not target:
            await ws.send_json({"type": "news_follow_error", "message": "missing_summary_id"})
            return True
        chosen: Optional[dict[str, Any]] = None
        for it in summaries:
            if isinstance(it, dict) and str(it.get("summary_id") or "").strip() == target:
                chosen = it
                break
        if not chosen:
            await ws.send_json({"type": "news_follow_error", "message": "summary_not_found", "summary_id": target})
            return True
        await ws.send_json({"type": "news_follow_report", "summary": chosen})
        return True

    if not summaries:
        await ws.send_json(
            {
                "type": "news_follow",
                "message": "ยังไม่มีสรุปที่เก็บไว้ พิมพ์: ติดตามข่าว รีเฟรช",
                "focus": focus,
            }
        )
        return True

    available = [
        {
            "summary_id": str(it.get("summary_id") or ""),
            "title": str(it.get("title") or ""),
            "created_at": it.get("created_at"),
            "focus": it.get("focus"),
        }
        for it in summaries
        if isinstance(it, dict)
    ]
    await ws.send_json(
        {
            "type": "news_follow_available",
            "focus": focus,
            "summaries": available,
            "message": "ต้องการให้รายงานอันไหน? พิมพ์: รายงานข่าว: <summary_id> หรือ ติดตามข่าว รีเฟรช",
        }
    )
    return True


async def _dispatch_sub_agents(ws: WebSocket, text: str) -> bool:
    # Draft confirmation has priority over all other routing.
    # This allows follow-up messages like `reminder confirm: tomorrow 09:00` to finalize a pending draft.
    try:
        handled_confirm = await _handle_pending_reminder_confirm_or_cancel(ws, text)
        if handled_confirm:
            return True
    except Exception:
        pass

    # Continuation handling: if a sub-agent is active for this websocket, let it handle followups.
    now_ts = int(time.time())
    active_agent_id = str(getattr(ws.state, "active_agent_id", "") or "").strip() or None
    active_until = getattr(ws.state, "active_agent_until_ts", None)
    try:
        active_until_ts = int(active_until) if active_until is not None else 0
    except Exception:
        active_until_ts = 0

    async def _run_agent(agent_id: str) -> bool:
        agent_id_norm = str(agent_id or "").strip()
        if agent_id_norm == "reminder-setup":
            # New reminder setup overrides any previous pending draft.
            ws.state.pending_reminder_setup = None
            handled = await _handle_reminder_setup_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "reminder-helper":
            handled = await _handle_reminder_helper_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "current-news":
            handled = await _handle_current_news_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "deep-research":
            handled = await _handle_deep_research_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        if agent_id_norm == "follow_news":
            handled = await _handle_news_follow_trigger(ws, text)
            if handled:
                ws.state.active_agent_id = agent_id_norm
                ws.state.active_agent_until_ts = int(time.time()) + AGENT_CONTINUE_WINDOW_SECONDS
            return handled
        return False

    if active_agent_id and active_until_ts >= now_ts:
        handled = await _run_agent(active_agent_id)
        if handled:
            return True

    # Trigger matching.
    triggers = _agent_triggers_snapshot()
    s = str(text or "")
    for agent_id, phrases in triggers.items():
        for phrase in phrases:
            if phrase and phrase.lower() in s.lower():
                handled = await _run_agent(agent_id)
                if handled:
                    return True

    # Clear expired continuation state.
    if active_agent_id and active_until_ts < now_ts:
        ws.state.active_agent_id = None
        ws.state.active_agent_until_ts = None
    return False


def _extract_mcp_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts).strip()
    t2 = result.get("text")
    if isinstance(t2, str):
        return t2.strip()
    return ""


async def _mcp_web_fetch_text(url: str, max_length: int = 200000) -> str:
    meta = MCP_TOOL_MAP.get("web_fetch") or {}
    mcp_name = str(meta.get("mcp_name") or "").strip()
    if not mcp_name:
        raise HTTPException(status_code=500, detail="mcp_web_fetch_missing")
    result = await _mcp_tools_call(mcp_name, {"url": url, "max_length": int(max_length)})
    return _extract_mcp_text(result)


def _parse_rss_items(xml_text: str) -> list[dict[str, Any]]:
    s = str(xml_text or "")
    if not s.strip():
        return []
    try:
        root = ET.fromstring(s)
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        desc = (it.findtext("description") or "").strip()
        if not title and not link:
            continue
        items.append({"title": title, "link": link, "pubDate": pub, "description": desc})
    return items


def _topic_match(text: str, keywords: list[str]) -> bool:
    s = " ".join(str(text or "").lower().split())
    if not s:
        return False
    for k in keywords:
        if k and k.lower() in s:
            return True
    return False


def _build_current_news_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    def pick(keywords: list[str], limit: int = 6) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in items:
            blob = f"{it.get('title','')} {it.get('description','')}"
            if _topic_match(blob, keywords):
                out.append(it)
            if len(out) >= limit:
                break
        return out

    iran = pick(
        [
            "iran",
            "israel",
            "tehran",
            "gaza",
            "hezbollah",
            "missile",
            "drone",
            "strike",
            "ceasefire",
            "u.s.",
            "us ",
            "pentagon",
        ]
    )
    gold = pick(["gold", "bullion", "xau"], limit=4)
    usd = pick(["dollar", "usd", "treasury", "yield", "fed"], limit=4)
    oil = pick(["oil", "crude", "brent", "wti", "opec"], limit=4)
    thb = pick(["thai baht", "baht", "thb", "usd/thb", "thb/usd", "bank of thailand", "bot"], limit=4)

    sources: list[str] = []
    for it in (iran + gold + usd + oil + thb):
        link = str(it.get("link") or "").strip()
        if link and link not in sources:
            sources.append(link)

    def brief_lines(section_items: list[dict[str, Any]], max_lines: int) -> list[str]:
        lines: list[str] = []
        for it in section_items[:max_lines]:
            t = str(it.get("title") or "").strip()
            if t:
                lines.append(t)
        return lines

    now_ts = int(time.time())
    return {
        "summary": "CNN current-news context refreshed",
        "updated_at": now_ts,
        "sources": sources,
        "topics": {
            "iran_war": {"headlines": brief_lines(iran, 5), "items": iran},
            "gold": {"headlines": brief_lines(gold, 3), "items": gold},
            "usd": {"headlines": brief_lines(usd, 3), "items": usd},
            "oil": {"headlines": brief_lines(oil, 3), "items": oil},
            "thb": {"headlines": brief_lines(thb, 3), "items": thb},
        },
    }


def _render_current_news_brief(ctx: dict[str, Any]) -> str:
    topics = ctx.get("topics") if isinstance(ctx, dict) else None
    if not isinstance(topics, dict):
        return "Current news: no cached context available. Say 'current news refresh' to fetch from CNN."

    def block(title: str, key: str, max_lines: int) -> str:
        sec = topics.get(key)
        headlines = sec.get("headlines") if isinstance(sec, dict) else None
        if not isinstance(headlines, list) or not headlines:
            return f"{title}: (no recent CNN headlines found)"
        lines = [f"{title}:"]
        for h in headlines[:max_lines]:
            hh = str(h or "").strip()
            if hh:
                lines.append(f"- {hh}")
        return "\n".join(lines)

    parts = [
        block("Iran war", "iran_war", 5),
        block("Gold", "gold", 3),
        block("Dollar/US rates", "usd", 3),
        block("Oil", "oil", 3),
        block("Thai Baht", "thb", 3),
        "\nYou can ask: 'details iran', 'details oil', 'details baht', 'list sources', or 'refresh current news'.",
    ]
    return "\n\n".join([p for p in parts if p.strip()])


async def _refresh_current_news_cache() -> dict[str, Any]:
    feeds = [
        "https://rss.cnn.com/rss/edition.rss",
        "https://rss.cnn.com/rss/edition_world.rss",
        "https://rss.cnn.com/rss/money_latest.rss",
    ]
    all_items: list[dict[str, Any]] = []
    for url in feeds:
        xml_text = await _mcp_web_fetch_text(url, max_length=250000)
        all_items.extend(_parse_rss_items(xml_text))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in all_items:
        key = str(it.get("link") or "") or str(it.get("title") or "")
        key = key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    ctx = _build_current_news_context(deduped)
    _set_news_cache("current-news", ctx)
    _upsert_agent_status(DEFAULT_USER_ID, "current-news", ctx)
    return ctx


async def _handle_current_news_trigger(ws: WebSocket, text: str) -> bool:
    s = " ".join(str(text or "").strip().lower().split())
    if not s:
        return False

    wants_refresh = any(
        p in s
        for p in (
            "refresh current news",
            "current news refresh",
            "refresh news",
            "update current news",
            "current news update",
        )
    )
    wants_sources = "list sources" in s or s == "sources"
    wants_details = s.startswith("details ") or s.startswith("detail ")
    is_trigger = (
        ("current news" in s)
        or ("cnn news" in s)
        or ("thai baht" in s)
        or (" baht" in f" {s}")
        or ("thb" in s)
        or wants_refresh
        or wants_details
        or wants_sources
    )
    if not is_trigger:
        return False

    cached = _get_news_cache("current-news")
    ctx: Optional[dict[str, Any]] = None
    if cached and isinstance(cached.get("payload"), dict):
        ctx = cached["payload"]

    if wants_refresh or ctx is None:
        ctx = await _refresh_current_news_cache()

    if not isinstance(ctx, dict):
        return False

    if wants_sources:
        await ws.send_json(
            {"type": "current_news_sources", "sources": ctx.get("sources") or [], "updated_at": ctx.get("updated_at")}
        )
        return True

    if wants_details:
        topic = str(s.split(" ", 1)[1] if " " in s else "").strip()
        topics = ctx.get("topics") if isinstance(ctx.get("topics"), dict) else {}
        key_map = {
            "iran": "iran_war",
            "iran war": "iran_war",
            "war": "iran_war",
            "gold": "gold",
            "dollar": "usd",
            "usd": "usd",
            "oil": "oil",
            "baht": "thb",
            "thai baht": "thb",
            "thb": "thb",
            "usd/thb": "thb",
        }
        chosen = key_map.get(topic, "")
        if chosen and isinstance(topics, dict) and isinstance(topics.get(chosen), dict):
            await ws.send_json(
                {"type": "current_news_details", "topic": chosen, "data": topics.get(chosen), "updated_at": ctx.get("updated_at")}
            )
        else:
            await ws.send_json(
                {
                    "type": "current_news_details",
                    "topic": topic,
                    "error": "unknown_topic",
                    "hint": "Try: details iran | details gold | details usd | details oil",
                }
            )
        return True

    brief = _render_current_news_brief(ctx)
    await ws.send_json({"type": "current_news", "brief": brief, "context": ctx, "updated_at": ctx.get("updated_at")})
    return True


@app.get("/current-news/brief")
async def current_news_brief() -> dict[str, Any]:
    cached = _get_news_cache("current-news")
    if cached and isinstance(cached.get("payload"), dict):
        ctx = cached["payload"]
        return {"ok": True, "cached": True, "brief": _render_current_news_brief(ctx), "context": ctx}
    ctx2 = await _refresh_current_news_cache()
    return {"ok": True, "cached": False, "brief": _render_current_news_brief(ctx2), "context": ctx2}


@app.post("/current-news/refresh")
async def current_news_refresh() -> dict[str, Any]:
    ctx = await _refresh_current_news_cache()
    return {"ok": True, "context": ctx}


def _parse_deep_research_command(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    s = " ".join(raw.lower().split())
    if not s:
        return {"action": "", "arg": ""}

    # Start commands
    if s.startswith("deep research:") or s.startswith("deep research "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "start", "arg": arg}
    if s.startswith("research:") or s.startswith("research "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
        return {"action": "start", "arg": arg}

    # Status/result commands
    if s.startswith("research status"):
        return {"action": "status", "arg": raw[len("research status") :].strip()}
    if s.startswith("research result"):
        return {"action": "result", "arg": raw[len("research result") :].strip()}
    if s.startswith("research poll"):
        return {"action": "poll", "arg": raw[len("research poll") :].strip()}

    # Follow-up command
    if s.startswith("research followup:") or s.startswith("research followup "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 2)[2].strip() if len(raw.split()) >= 3 else ""
        return {"action": "followup", "arg": arg}
    if s.startswith("followup:") or s.startswith("followup "):
        arg = raw.split(":", 1)[1].strip() if ":" in raw else raw.split(" ", 1)[1].strip()
        return {"action": "followup", "arg": arg}

    # If the user just says "deep research" with no query, treat as help.
    if s == "deep research" or s == "research" or s == "deep-research":
        return {"action": "help", "arg": ""}

    return {"action": "", "arg": ""}


async def _handle_deep_research_trigger(ws: WebSocket, text: str) -> bool:
    cmd = _parse_deep_research_command(text)
    action = cmd.get("action") or ""
    arg = cmd.get("arg") or ""

    # Trigger matching should also route generic mentions.
    s = " ".join(str(text or "").lower().split())
    is_trigger = (
        action != ""
        or ("deep research" in s)
        or ("research" in s)
        or ("investigate" in s)
        or ("research report" in s)
    )
    if not is_trigger:
        return False

    async def _send_help() -> None:
        await ws.send_json(
            {
                "type": "deep_research_help",
                "message": "Use: 'deep research: <question>' then 'research status' or 'research result'. For followups: 'research followup: <question>'.",
            }
        )

    if action == "help" or (action == "start" and not arg.strip()):
        await _send_help()
        return True

    # Session state: remember last job and interaction for convenience.
    last_job_id = str(getattr(ws.state, "deep_research_job_id", "") or "").strip()
    last_interaction_id = str(getattr(ws.state, "deep_research_interaction_id", "") or "").strip()

    if action == "start":
        res = await _deep_research_worker_post("/deep-research/start", {"query": arg})
        job_id = str(res.get("job_id") or "").strip()
        interaction_id = str(res.get("interaction_id") or "").strip()
        status = res.get("status")
        ws.state.deep_research_job_id = job_id
        ws.state.deep_research_interaction_id = interaction_id
        _upsert_agent_status(
            DEFAULT_USER_ID,
            "deep-research",
            {
                "summary": f"deep research started (status={status})",
                "job_id": job_id,
                "interaction_id": interaction_id,
                "status": status,
                "updated_at": int(time.time()),
            },
        )
        await ws.send_json({"type": "deep_research_started", "worker": res})
        return True

    # Determine target job id.
    target = arg.strip() or last_job_id
    if action in ("status", "poll", "result") and not target:
        await ws.send_json({"type": "deep_research_error", "message": "missing_job_id", "hint": "Start with: deep research: <question>"})
        return True

    if action in ("status", "result"):
        data = await _deep_research_worker_get(f"/deep-research/jobs/{target}")
        job = data.get("job") if isinstance(data, dict) else None
        await ws.send_json({"type": f"deep_research_{action}", "job": job})
        return True

    if action == "poll":
        data = await _deep_research_worker_post(f"/deep-research/poll/{target}", {})
        job = data.get("job") if isinstance(data, dict) else None
        if isinstance(job, dict):
            st = job.get("status")
            if st in ("completed", "failed", "cancelled"):
                # Prefer continuing followups from the completed interaction id.
                ws.state.deep_research_interaction_id = str(job.get("interaction_id") or "")
            _upsert_agent_status(
                DEFAULT_USER_ID,
                "deep-research",
                {
                    "summary": f"deep research poll (status={st})",
                    "job_id": str(job.get("job_id") or target),
                    "interaction_id": str(job.get("interaction_id") or ""),
                    "status": st,
                    "updated_at": int(time.time()),
                },
            )
        await ws.send_json({"type": "deep_research_poll", "job": job})
        return True

    if action == "followup":
        prev = last_interaction_id
        if not prev:
            await ws.send_json(
                {
                    "type": "deep_research_error",
                    "message": "missing_previous_interaction_id",
                    "hint": "Run a deep research first and poll until completed.",
                }
            )
            return True
        res = await _deep_research_worker_post("/deep-research/followup", {"previous_interaction_id": prev, "question": arg})
        job_id = str(res.get("job_id") or "").strip()
        interaction_id = str(res.get("interaction_id") or "").strip()
        status = res.get("status")
        ws.state.deep_research_job_id = job_id
        ws.state.deep_research_interaction_id = interaction_id
        _upsert_agent_status(
            DEFAULT_USER_ID,
            "deep-research",
            {
                "summary": f"deep research followup started (status={status})",
                "job_id": job_id,
                "interaction_id": interaction_id,
                "status": status,
                "updated_at": int(time.time()),
            },
        )
        await ws.send_json({"type": "deep_research_followup_started", "worker": res})
        return True

    await _send_help()
    return True


def _get_user_timezone(user_id: str) -> ZoneInfo:
    # Placeholder for future user-profile timezone retrieval.
    # For now, use a default timezone.
    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _next_morning_brief_at(now: datetime, tz: ZoneInfo, due_at: Optional[datetime]) -> datetime:
    base = due_at.astimezone(tz) if due_at is not None else now.astimezone(tz)
    candidate = datetime(
        year=base.year,
        month=base.month,
        day=base.day,
        hour=MORNING_BRIEF_HOUR,
        minute=MORNING_BRIEF_MINUTE,
        tzinfo=tz,
    )
    if candidate <= now.astimezone(tz):
        candidate = candidate + timedelta(days=1)
    return candidate


def _next_local_morning_at(now: datetime, tz: ZoneInfo, *, hour: int, minute: int, days_ahead: int) -> datetime:
    local = now.astimezone(tz)
    base = datetime(year=local.year, month=local.month, day=local.day, tzinfo=tz)
    base = base + timedelta(days=max(0, int(days_ahead)))
    return base.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def _default_hide_until(now: datetime, tz: ZoneInfo, days_ahead: int) -> datetime:
    # User preference: 08:30 local time.
    return _next_local_morning_at(now, tz, hour=8, minute=30, days_ahead=max(1, int(days_ahead)))


def _suggest_reschedule_notify_at(now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    if local.hour < 16:
        cand = local + timedelta(hours=2)
        minute = int(cand.minute)
        rounded = ((minute + 14) // 15) * 15
        if rounded >= 60:
            cand = cand.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            cand = cand.replace(minute=rounded, second=0, microsecond=0)
        return cand
    return _default_hide_until(now, tz, days_ahead=1)


def _set_reminder_hide_until(reminder_id: str, hide_until_ts: Optional[int]) -> bool:
    _init_session_db()
    rid = str(reminder_id or "").strip()
    if not rid:
        return False
    now_ts = int(time.time())
    try:
        with sqlite3.connect(SESSION_DB_PATH) as conn:
            cur = conn.execute(
                "UPDATE reminders SET hide_until = ?, updated_at = ? WHERE reminder_id = ?",
                (hide_until_ts, now_ts, rid),
            )
            conn.commit()
            return bool(cur.rowcount and int(cur.rowcount) > 0)
    except sqlite3.OperationalError as e:
        if "no such column" in str(e).lower() and "hide_until" in str(e).lower():
            _init_session_db()
            with sqlite3.connect(SESSION_DB_PATH) as conn:
                cur = conn.execute(
                    "UPDATE reminders SET hide_until = ?, updated_at = ? WHERE reminder_id = ?",
                    (hide_until_ts, now_ts, rid),
                )
                conn.commit()
                return bool(cur.rowcount and int(cur.rowcount) > 0)
        raise


def _set_reminder_notify_at(reminder_id: str, notify_at_ts: Optional[int]) -> bool:
    _init_session_db()
    rid = str(reminder_id or "").strip()
    if not rid:
        return False
    now_ts = int(time.time())
    try:
        with sqlite3.connect(SESSION_DB_PATH) as conn:
            cur = conn.execute(
                "UPDATE reminders SET notify_at = ?, updated_at = ? WHERE reminder_id = ?",
                (notify_at_ts, now_ts, rid),
            )
            conn.commit()
            return bool(cur.rowcount and int(cur.rowcount) > 0)
    except sqlite3.OperationalError as e:
        if "no such column" in str(e).lower() and "notify_at" in str(e).lower():
            _init_session_db()
            with sqlite3.connect(SESSION_DB_PATH) as conn:
                cur = conn.execute(
                    "UPDATE reminders SET notify_at = ?, updated_at = ? WHERE reminder_id = ?",
                    (notify_at_ts, now_ts, rid),
                )
                conn.commit()
                return bool(cur.rowcount and int(cur.rowcount) > 0)
        raise


def _parse_time_from_text(text: str, now: datetime, tz: ZoneInfo) -> tuple[Optional[datetime], Optional[str]]:
    s = str(text or "").strip().lower()
    if not s:
        return None, None

    day: Optional[datetime] = None
    if re.search(r"\btomorrow\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz) + timedelta(days=1)
    elif re.search(r"\btoday\b", s):
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)

    time_match = re.search(r"\b(at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s)
    if not time_match and day is None:
        return None, None

    hour = 9
    minute = 0
    meridiem = None
    if time_match:
        hour = int(time_match.group(2))
        minute = int(time_match.group(3) or "0")
        meridiem = time_match.group(4)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0

    if day is None:
        local = now.astimezone(tz)
        day = datetime(local.year, local.month, local.day, tzinfo=tz)
        # If time already passed today, treat it as tomorrow.
        candidate = day.replace(hour=hour, minute=minute)
        if candidate <= local:
            candidate = candidate + timedelta(days=1)
        return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"

    candidate = day.replace(hour=hour, minute=minute)
    return candidate.astimezone(timezone.utc), f"{candidate.isoformat()}"


def _reminder_dedupe_key(title: str, due_at_ts: Optional[int], schedule_type: str) -> str:
    t = " ".join(str(title or "").strip().lower().split())
    d = str(int(due_at_ts)) if due_at_ts is not None else "none"
    s = " ".join(str(schedule_type or "").strip().lower().split())
    return f"{t}|{d}|{s}"[:512]


def _create_reminder(
    *,
    user_id: str,
    title: str,
    due_at_utc: Optional[datetime],
    tz: ZoneInfo,
    schedule_type: str,
    notify_at_utc: Optional[datetime],
    source_text: str,
    aim_entity_name: Optional[str],
) -> str:
    _init_session_db()
    now_ts = int(time.time())
    due_at_ts = int(due_at_utc.timestamp()) if due_at_utc is not None else None
    notify_at_ts = int(notify_at_utc.timestamp()) if notify_at_utc is not None else None
    dedupe_key = _reminder_dedupe_key(title, due_at_ts, schedule_type)

    with sqlite3.connect(SESSION_DB_PATH) as conn:
        # If an equivalent pending reminder already exists, reuse it and update notify_at to the earliest.
        cur = conn.execute(
            """
            SELECT reminder_id, notify_at
            FROM reminders
            WHERE user_id = ? AND dedupe_key = ? AND status = 'pending'
            LIMIT 1
            """,
            (user_id, dedupe_key),
        )
        row = cur.fetchone()
        if row:
            existing_id, existing_notify_at = row
            try:
                existing_notify_at_int = int(existing_notify_at)
            except Exception:
                existing_notify_at_int = notify_at_ts
            if notify_at_ts is not None:
                new_notify_at = min(existing_notify_at_int, notify_at_ts)
                conn.execute(
                    "UPDATE reminders SET notify_at = ?, updated_at = ? WHERE reminder_id = ?",
                    (new_notify_at, now_ts, existing_id),
                )
            else:
                conn.execute(
                    "UPDATE reminders SET updated_at = ? WHERE reminder_id = ?",
                    (now_ts, existing_id),
                )
            conn.commit()
            return str(existing_id)

        reminder_id = f"r_{int(time.time())}_{os.urandom(6).hex()}"
        conn.execute(
            """
            INSERT INTO reminders(
              reminder_id, user_id, title, dedupe_key, due_at, timezone, schedule_type, notify_at, status,
              hide_until, source_text, aim_entity_name, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """ ,
            (
                reminder_id,
                user_id,
                title,
                dedupe_key,
                due_at_ts,
                str(tz.key),
                schedule_type,
                notify_at_ts,
                "pending",
                None,
                source_text,
                aim_entity_name,
                now_ts,
                now_ts,
            ),
        )
        conn.commit()
    return reminder_id


def _mark_reminder_fired(reminder_id: str) -> None:
    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            "UPDATE reminders SET status = ?, updated_at = ? WHERE reminder_id = ?",
            ("fired", now_ts, reminder_id),
        )
        conn.commit()


def _mark_reminder_done(reminder_id: str) -> bool:
    _init_session_db()
    now_ts = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE reminders SET status = ?, updated_at = ? WHERE reminder_id = ? AND status != ?",
            ("done", now_ts, reminder_id, "done"),
        )
        conn.commit()
        return bool(cur.rowcount and int(cur.rowcount) > 0)


def _delete_reminder_local(reminder_id: str) -> bool:
    _init_session_db()
    rid = str(reminder_id or "").strip()
    if not rid:
        return False
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute("DELETE FROM reminders WHERE reminder_id = ?", (rid,))
        conn.commit()
        return bool(cur.rowcount and int(cur.rowcount) > 0)


def _get_local_reminder_by_id(reminder_id: str) -> Optional[dict[str, Any]]:
    _init_session_db()
    rid = str(reminder_id or "").strip()
    if not rid:
        return None
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, hide_until, status, source_text, aim_entity_name, created_at, updated_at "
            "FROM reminders WHERE reminder_id = ? LIMIT 1",
            (rid,),
        )
        row = cur.fetchone()
    if not row:
        return None
    (
        reminder_id_v,
        title,
        due_at,
        tz_name,
        schedule_type,
        notify_at,
        hide_until,
        status_value,
        source_text,
        aim_entity_name,
        created_at,
        updated_at,
    ) = row
    return {
        "reminder_id": reminder_id_v,
        "title": title,
        "due_at": due_at,
        "timezone": tz_name,
        "schedule_type": schedule_type,
        "notify_at": notify_at,
        "hide_until": hide_until,
        "status": status_value,
        "source_text": source_text,
        "aim_entity_name": aim_entity_name,
        "created_at": created_at,
        "updated_at": updated_at,
    }


async def _weaviate_get_memory_item_by_external_key(external_key: str) -> Optional[dict[str, Any]]:
    await _weaviate_ensure_schema()
    ek = str(external_key or "").strip()
    if not ek:
        return None
    obj_id = _weaviate_object_uuid(ek)
    try:
        existing = await _weaviate_request("GET", f"/v1/objects/{obj_id}")
    except Exception:
        return None
    if not isinstance(existing, dict):
        return None
    props = existing.get("properties")
    if not isinstance(props, dict):
        return None
    return props


async def _mark_reminder_done_weaviate(reminder_id: str) -> dict[str, Any]:
    if not _weaviate_enabled():
        return {"ok": False, "skipped": True}

    rid = str(reminder_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing_reminder_id")

    local = _get_local_reminder_by_id(rid)
    external_key = None
    if isinstance(local, dict):
        external_key = str(local.get("aim_entity_name") or "").strip()
    if not external_key:
        external_key = f"reminder::{rid}"

    props = await _weaviate_get_memory_item_by_external_key(external_key)
    title = str((props or {}).get("title") or (local or {}).get("title") or "Reminder").strip() or "Reminder"
    body = str((props or {}).get("body") or (local or {}).get("source_text") or "").strip()
    tz_name = str((props or {}).get("timezone") or (local or {}).get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE

    def _num(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(float(v))
        except Exception:
            return None

    due_at = _num((props or {}).get("due_at"))
    notify_at = _num((props or {}).get("notify_at"))
    if due_at is None and isinstance(local, dict):
        due_at = _num(local.get("due_at"))
    if notify_at is None and isinstance(local, dict):
        notify_at = _num(local.get("notify_at"))

    wv = await _weaviate_upsert_memory_item(
        external_key=external_key,
        kind="reminder",
        title=title,
        body=body,
        status="done",
        due_at=due_at,
        notify_at=notify_at,
        hide_until=None,
        timezone_name=tz_name,
        source="jarvis",
    )
    return {"ok": True, "weaviate": wv, "external_key": external_key}


def _list_due_reminders(user_id: str, now_ts: int) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT reminder_id, title, due_at, timezone, schedule_type, notify_at, source_text, aim_entity_name
            FROM reminders
            WHERE user_id = ?
              AND status = 'pending'
              AND notify_at IS NOT NULL
              AND notify_at <= ?
              AND (hide_until IS NULL OR hide_until <= ?)
            ORDER BY notify_at ASC
            """,
            (user_id, now_ts, now_ts),
        )
        rows = cur.fetchall() or []

    out: list[dict[str, Any]] = []
    for reminder_id, title, due_at, tz_name, schedule_type, notify_at, source_text, aim_entity_name in rows:
        out.append(
            {
                "reminder_id": reminder_id,
                "title": title,
                "due_at": due_at,
                "timezone": tz_name,
                "schedule_type": schedule_type,
                "notify_at": notify_at,
                "source_text": source_text,
                "aim_entity_name": aim_entity_name,
            }
        )
    return out


async def _broadcast_to_user(user_id: str, payload: dict[str, Any]) -> None:
    conns = list(_ws_by_user.get(user_id, set()))
    if not conns:
        return
    dead: list[WebSocket] = []
    for ws in conns:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    if dead:
        s = _ws_by_user.get(user_id)
        if s is not None:
            for ws in dead:
                s.discard(ws)


async def _reminder_scheduler_loop() -> None:
    while True:
        try:
            now_ts = int(time.time())
            reminders = _list_due_reminders(DEFAULT_USER_ID, now_ts)
            for r in reminders:
                reminder_id = str(r.get("reminder_id") or "")
                if reminder_id:
                    _mark_reminder_fired(reminder_id)
                await _broadcast_to_user(
                    DEFAULT_USER_ID,
                    {
                        "type": "reminder",
                        "reminder": r,
                    },
                )
        except Exception as e:
            logger.warning("reminder_scheduler_error error=%s", e)
        await asyncio.sleep(15)


@app.on_event("startup")
async def _startup() -> None:
    global _reminder_task
    try:
        _init_session_db()
    except Exception as e:
        logger.warning("session_db_init_failed error=%s", e)
    try:
        _ensure_cars_data_dirs()
    except Exception as e:
        logger.warning("cars_data_dir_init_failed error=%s", e)
    try:
        await _startup_resync_from_weaviate()
    except Exception as e:
        logger.warning("startup_resync_failed error=%s", e)
    if _reminder_task is None or _reminder_task.done():
        _reminder_task = asyncio.create_task(_reminder_scheduler_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _reminder_task
    if _reminder_task is not None:
        _reminder_task.cancel()
        _reminder_task = None


def _get_session_state(session_id: str) -> dict[str, Optional[str]]:
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT active_trip_id, active_trip_name FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"active_trip_id": None, "active_trip_name": None}
        return {"active_trip_id": row[0], "active_trip_name": row[1]}


def _set_session_state(session_id: str, active_trip_id: Optional[str], active_trip_name: Optional[str]) -> None:
    now = int(time.time())
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO sessions(session_id, active_trip_id, active_trip_name, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
              active_trip_id=excluded.active_trip_id,
              active_trip_name=excluded.active_trip_name,
              updated_at=excluded.updated_at
            """,
            (session_id, active_trip_id, active_trip_name, now),
        )
        conn.commit()


def _create_pending_write(session_id: str, action: str, payload: Any) -> str:
    _init_session_db()
    confirmation_id = f"pw_{int(time.time())}_{os.urandom(6).hex()}"
    created_at = int(time.time())
    payload_json = json.dumps(payload, ensure_ascii=False)
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO pending_writes(confirmation_id, session_id, action, payload_json, created_at) VALUES(?, ?, ?, ?, ?)",
            (confirmation_id, session_id, action, payload_json, created_at),
        )
        conn.commit()
    return confirmation_id


def _list_pending_writes(session_id: str) -> list[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT confirmation_id, action, payload_json, created_at FROM pending_writes WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for confirmation_id, action, payload_json, created_at in rows:
        try:
            payload = json.loads(payload_json)
        except Exception:
            payload = payload_json
        out.append(
            {
                "confirmation_id": confirmation_id,
                "action": action,
                "payload": payload,
                "created_at": created_at,
            }
        )
    return out


def _pop_pending_write(session_id: str, confirmation_id: str) -> Optional[dict[str, Any]]:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "SELECT action, payload_json, created_at FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        action, payload_json, created_at = row
        conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        conn.commit()
    try:
        payload = json.loads(payload_json)
    except Exception:
        payload = payload_json
    return {"action": action, "payload": payload, "created_at": created_at}


def _cancel_pending_write(session_id: str, confirmation_id: str) -> bool:
    _init_session_db()
    with sqlite3.connect(SESSION_DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM pending_writes WHERE session_id = ? AND confirmation_id = ?",
            (session_id, confirmation_id),
        )
        conn.commit()
        return (cur.rowcount or 0) > 0

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"] ,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "jarvis-backend", "instance_id": INSTANCE_ID, "weaviate_enabled": _weaviate_enabled()}


@app.get("/agents")
def list_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    out: list[dict[str, Any]] = []
    for agent_id, meta in agents.items():
        out.append(
            {
                "id": agent_id,
                "name": meta.get("name") or agent_id,
                "kind": meta.get("kind") or "",
                "version": meta.get("version") or "",
                "path": meta.get("path") or "",
            }
        )
    return {"ok": True, "agents": out}


@app.post("/agents/{agent_id}/status")
def post_agent_status(agent_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    agents = _agents_snapshot()
    agent_id = str(agent_id or "").strip()
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="agent_not_found")
    _upsert_agent_status(DEFAULT_USER_ID, agent_id, payload)
    return {"ok": True}


@app.get("/daily-brief")
async def daily_brief() -> dict[str, Any]:
    agents = _agents_snapshot()
    if "daily-brief" not in agents:
        raise HTTPException(status_code=500, detail="daily_brief_agent_missing")
    return {"ok": True, "brief": await _render_daily_brief(DEFAULT_USER_ID)}


@app.get("/reminders")
async def list_reminders(
    status: str = "all",
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
    include_hidden: bool = False,
) -> dict[str, Any]:
    # Cross-device consistency: when Weaviate is enabled, prefer it as the authoritative read path.
    if _weaviate_enabled():
        try:
            now_ts = int(time.time())
            items = await _weaviate_query_reminders(status=status, limit=limit)
            # Map Weaviate items into the same shape as SQLite reminders.
            out: list[dict[str, Any]] = []
            for it in items:
                title = str(it.get("title") or "Reminder").strip() or "Reminder"
                tz_name = str(it.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
                hide_until = int(float(it["hide_until"])) if it.get("hide_until") is not None else None
                if (not include_hidden) and hide_until is not None and hide_until > now_ts:
                    continue
                out.append(
                    {
                        "reminder_id": _local_reminder_id_from_external_key(str(it.get("external_key") or "")),
                        "title": title,
                        "due_at": int(float(it["due_at"])) if it.get("due_at") is not None else None,
                        "timezone": tz_name,
                        "schedule_type": "memory",
                        "notify_at": int(float(it["notify_at"])) if it.get("notify_at") is not None else None,
                        "hide_until": hide_until,
                        "status": str(it.get("status") or "").strip() or "pending",
                        "source_text": str(it.get("body") or ""),
                        "aim_entity_name": str(it.get("external_key") or ""),
                        "created_at": int(float(it["created_at"])) if it.get("created_at") is not None else None,
                        "updated_at": int(float(it["updated_at"])) if it.get("updated_at") is not None else None,
                    }
                )
            return {"ok": True, "source": "weaviate", "instance_id": INSTANCE_ID, "reminders": out}
        except Exception as e:
            return {
                "ok": True,
                "source": "sqlite_fallback",
                "instance_id": INSTANCE_ID,
                "error": str(e),
                "reminders": _list_reminders(
                    user_id=DEFAULT_USER_ID,
                    status=status,
                    limit=limit,
                    offset=offset,
                    order=order,
                    include_hidden=include_hidden,
                ),
            }

    reminders = _list_reminders(
        user_id=DEFAULT_USER_ID,
        status=status,
        limit=limit,
        offset=offset,
        order=order,
        include_hidden=include_hidden,
    )
    return {"ok": True, "source": "sqlite", "instance_id": INSTANCE_ID, "reminders": reminders}


class ReminderCreateRequest(BaseModel):
    title: str = Field(default="Reminder")
    due_at_utc: Optional[str] = Field(default=None)
    timezone: str = Field(default=DEFAULT_TIMEZONE)
    schedule_type: str = Field(default="unscheduled")
    source_text: str = Field(default="")


@app.post("/reminders")
async def create_reminder(req: ReminderCreateRequest) -> dict[str, Any]:
    tz_name = str(req.timezone or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_timezone")

    title = str(req.title or "Reminder").strip() or "Reminder"
    schedule_type = str(req.schedule_type or "unscheduled").strip() or "unscheduled"
    source_text = str(req.source_text or "").strip()

    due_at_utc: Optional[datetime] = None
    if req.due_at_utc is not None:
        try:
            parsed = datetime.fromisoformat(str(req.due_at_utc).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            due_at_utc = parsed.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_due_at_utc")

    reminder_id = _create_reminder(
        user_id=DEFAULT_USER_ID,
        title=title,
        due_at_utc=due_at_utc,
        tz=tz,
        schedule_type=schedule_type,
        notify_at_utc=None,
        source_text=source_text,
        aim_entity_name=None,
    )

    # Attempt Weaviate write-through, but do not fail the create if Weaviate is unavailable.
    wv: Optional[dict[str, Any]] = None
    external_key = f"reminder::{reminder_id}"
    if _weaviate_enabled():
        try:
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=title,
                body=source_text,
                status="pending",
                due_at=int(due_at_utc.timestamp()) if due_at_utc is not None else None,
                notify_at=None,
                hide_until=None,
                timezone_name=tz.key,
                source="jarvis",
            )
            try:
                _init_session_db()
                with sqlite3.connect(SESSION_DB_PATH) as conn:
                    conn.execute(
                        "UPDATE reminders SET aim_entity_name = ?, updated_at = ? WHERE reminder_id = ?",
                        (external_key, int(time.time()), reminder_id),
                    )
                    conn.commit()
            except Exception:
                pass
        except Exception as e:
            wv = {"ok": False, "error": str(e)}

    local = _get_local_reminder_by_id(reminder_id)
    return {
        "ok": True,
        "instance_id": INSTANCE_ID,
        "reminder_id": reminder_id,
        "external_key": external_key,
        "reminder": local,
        "weaviate": wv,
    }


@app.post("/reminders/{reminder_id}/done")
async def reminders_done(reminder_id: str) -> dict[str, Any]:
    rid = str(reminder_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing_reminder_id")

    changed = _mark_reminder_done(rid)
    wv: Optional[dict[str, Any]] = None
    if _weaviate_enabled():
        try:
            wv = await _mark_reminder_done_weaviate(rid)
        except Exception as e:
            wv = {"ok": False, "error": str(e)}

    await _broadcast_to_user(
        DEFAULT_USER_ID,
        {"type": "reminder_done", "reminder_id": rid, "changed": changed, "weaviate": wv, "instance_id": INSTANCE_ID},
    )
    return {"ok": True, "reminder_id": rid, "changed": changed, "weaviate": wv, "instance_id": INSTANCE_ID}


@app.get("/reminders/upcoming")
async def upcoming_reminders(window_hours: int = 48, time_field: str = "notify_at", limit: int = 50) -> dict[str, Any]:
    now_ts = int(time.time())
    end_ts = now_ts + max(1, int(window_hours or 48)) * 3600
    if _weaviate_enabled() and str(time_field or "").strip().lower() == "notify_at":
        try:
            items = await _weaviate_query_upcoming_reminders(start_ts=now_ts, end_ts=end_ts, limit=limit)
            out: list[dict[str, Any]] = []
            for it in items:
                title = str(it.get("title") or "Reminder").strip() or "Reminder"
                tz_name = str(it.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
                hide_until = int(float(it["hide_until"])) if it.get("hide_until") is not None else None
                if hide_until is not None and hide_until > now_ts:
                    continue
                out.append(
                    {
                        "reminder_id": _local_reminder_id_from_external_key(str(it.get("external_key") or "")),
                        "title": title,
                        "due_at": int(float(it["due_at"])) if it.get("due_at") is not None else None,
                        "timezone": tz_name,
                        "schedule_type": "memory",
                        "notify_at": int(float(it["notify_at"])) if it.get("notify_at") is not None else None,
                        "hide_until": hide_until,
                        "source_text": str(it.get("body") or ""),
                        "aim_entity_name": str(it.get("external_key") or ""),
                    }
                )
            return {"ok": True, "source": "weaviate", "instance_id": INSTANCE_ID, "now": now_ts, "end": end_ts, "time_field": time_field, "reminders": out}
        except Exception as e:
            pass

    reminders = _list_upcoming_pending_reminders(
        user_id=DEFAULT_USER_ID,
        start_ts=now_ts,
        end_ts=end_ts,
        time_field=time_field,
        limit=limit,
    )
    return {"ok": True, "source": "sqlite", "instance_id": INSTANCE_ID, "now": now_ts, "end": end_ts, "time_field": time_field, "reminders": reminders}


@app.post("/reminders/{reminder_id}/later")
async def reminder_later(reminder_id: str, days: int = 1) -> dict[str, Any]:
    rid = str(reminder_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing_reminder_id")
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    hide_until_local = _default_hide_until(now, tz, days_ahead=int(days or 1))
    hide_until_utc = hide_until_local.astimezone(timezone.utc)
    hide_until_ts = int(hide_until_utc.timestamp())
    changed = False
    local_error: Optional[str] = None
    try:
        changed = _set_reminder_hide_until(rid, hide_until_ts)
    except Exception as e:
        local_error = str(e)
        if not _weaviate_enabled():
            raise HTTPException(status_code=500, detail={"reminder_later_failed": local_error})

    if not changed and not _weaviate_enabled():
        raise HTTPException(status_code=404, detail="reminder_not_found")

    wv: Optional[dict[str, Any]] = None
    if _weaviate_enabled():
        try:
            local = _get_local_reminder_by_id(rid) or {}
            if not local:
                raise HTTPException(status_code=404, detail="reminder_not_found")
            external_key = str(local.get("aim_entity_name") or "").strip() or f"reminder::{rid}"
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=str(local.get("title") or "Reminder"),
                body=str(local.get("source_text") or ""),
                status=str(local.get("status") or "pending"),
                due_at=int(local.get("due_at")) if local.get("due_at") is not None else None,
                notify_at=int(local.get("notify_at")) if local.get("notify_at") is not None else None,
                hide_until=hide_until_ts,
                timezone_name=str(local.get("timezone") or tz.key),
                source="jarvis",
            )
        except Exception as e:
            wv = {"ok": False, "error": str(e)}

    await _broadcast_to_user(
        DEFAULT_USER_ID,
        {
            "type": "reminder_later",
            "reminder_id": rid,
            "hide_until": hide_until_ts,
            "changed": changed,
            "local_error": local_error,
            "weaviate": wv,
            "instance_id": INSTANCE_ID,
        },
    )
    return {
        "ok": True,
        "reminder_id": rid,
        "hide_until": hide_until_ts,
        "changed": changed,
        "local_error": local_error,
        "weaviate": wv,
    }


@app.get("/reminders/{reminder_id}/reschedule/suggest")
async def reminder_reschedule_suggest(reminder_id: str) -> dict[str, Any]:
    rid = str(reminder_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing_reminder_id")
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    suggested_local = _suggest_reschedule_notify_at(now, tz)
    suggested_utc = suggested_local.astimezone(timezone.utc)
    return {
        "ok": True,
        "reminder_id": rid,
        "timezone": tz.key,
        "suggested_notify_at": int(suggested_utc.timestamp()),
        "suggested_local_iso": suggested_local.isoformat(),
    }


@app.post("/reminders/{reminder_id}/reschedule")
async def reminder_reschedule(reminder_id: str, notify_at: int) -> dict[str, Any]:
    rid = str(reminder_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="missing_reminder_id")
    try:
        notify_at_ts = int(notify_at)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_notify_at")

    changed = False
    local_error: Optional[str] = None
    try:
        changed = _set_reminder_notify_at(rid, notify_at_ts)
        _set_reminder_hide_until(rid, None)
    except Exception as e:
        local_error = str(e)
        if not _weaviate_enabled():
            raise HTTPException(status_code=500, detail={"reminder_reschedule_failed": local_error})

    if not changed and not _weaviate_enabled():
        raise HTTPException(status_code=404, detail="reminder_not_found")

    wv: Optional[dict[str, Any]] = None
    if _weaviate_enabled():
        try:
            local = _get_local_reminder_by_id(rid) or {}
            if not local:
                raise HTTPException(status_code=404, detail="reminder_not_found")
            tz_name = str(local.get("timezone") or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
            external_key = str(local.get("aim_entity_name") or "").strip() or f"reminder::{rid}"
            wv = await _weaviate_upsert_memory_item(
                external_key=external_key,
                kind="reminder",
                title=str(local.get("title") or "Reminder"),
                body=str(local.get("source_text") or ""),
                status=str(local.get("status") or "pending"),
                due_at=int(local.get("due_at")) if local.get("due_at") is not None else None,
                notify_at=notify_at_ts,
                hide_until=None,
                timezone_name=tz_name,
                source="jarvis",
            )
        except Exception as e:
            wv = {"ok": False, "error": str(e)}

    await _broadcast_to_user(
        DEFAULT_USER_ID,
        {
            "type": "reminder_reschedule",
            "reminder_id": rid,
            "notify_at": notify_at_ts,
            "changed": changed,
            "local_error": local_error,
            "weaviate": wv,
            "instance_id": INSTANCE_ID,
        },
    )
    return {
        "ok": True,
        "reminder_id": rid,
        "notify_at": notify_at_ts,
        "changed": changed,
        "local_error": local_error,
        "weaviate": wv,
    }


@app.get("/debug/agents")
def debug_agents() -> dict[str, Any]:
    agents = _agents_snapshot()
    triggers = _agent_triggers_snapshot()
    return {
        "ok": True,
        "agents_dir": AGENTS_DIR,
        "agent_count": len(agents),
        "agents": agents,
        "triggers": triggers,
        "continuation_window_seconds": AGENT_CONTINUE_WINDOW_SECONDS,
    }


def _parse_sse_first_message_data(text: str) -> dict[str, Any]:
    # 1MCP returns text/event-stream where each JSON-RPC response is on a `data: {...}` line.
    for line in (text or "").splitlines():
        if line.startswith("data: "):
            try:
                parsed = json.loads(line[len("data: ") :].strip())
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


async def _mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    return await _mcp_rpc_base(MCP_BASE_URL, method, params)


async def _aim_mcp_rpc(method: str, params: dict[str, Any]) -> Any:
    if not AIM_MCP_BASE_URL:
        raise HTTPException(status_code=500, detail="aim_mcp_base_url_not_configured")
    return await _mcp_rpc_base(AIM_MCP_BASE_URL, method, params)


async def _mcp_rpc_base(base_url: str, method: str, params: dict[str, Any]) -> Any:
    session_id = str(uuid.uuid4())
    url = f"{base_url}/mcp?sessionId={session_id}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-backend", "version": "0.1"},
            },
        }
        init_res = await client.post(
            url,
            json=init_req,
            headers={"Accept": "application/json, text/event-stream"},
        )
        if init_res.status_code >= 400:
            raise HTTPException(status_code=502, detail={"mcp_initialize_failed": init_res.text})

        mcp_session_id = init_res.headers.get("mcp-session-id") or ""
        if not mcp_session_id:
            raise HTTPException(status_code=502, detail="mcp_missing_session_header")

        req = {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}
        res = await client.post(
            url,
            json=req,
            headers={
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": mcp_session_id,
            },
        )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail={"mcp_rpc_failed": res.text})

        msg = _parse_sse_first_message_data(res.text)
        if msg.get("error") is not None:
            raise HTTPException(status_code=502, detail={"mcp_error": msg.get("error")})
        return msg.get("result")


async def _mcp_tools_list() -> list[dict[str, Any]]:
    result = await _mcp_rpc("tools/list", {})
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for t in tools:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            out.append(t)
    return out


async def _mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    return await _mcp_rpc("tools/call", {"name": name, "arguments": arguments})


async def _aim_mcp_tools_call(name: str, arguments: dict[str, Any]) -> Any:
    return await _aim_mcp_rpc("tools/call", {"name": name, "arguments": arguments})


async def _web_fetcher_post(path: str, payload: Any) -> Any:
    url = f"{WEB_FETCHER_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(url, json=payload)
        if res.status_code >= 400:
            detail: Any
            try:
                detail = res.json()
            except Exception:
                detail = res.text
            raise HTTPException(status_code=res.status_code, detail=detail)
        return res.json()


def _require_confirmation(confirm: bool, action: str, payload: Any) -> None:
    if confirm:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "requires_confirmation": True,
            "action": action,
            "payload": payload,
        },
    )


def _adapt_aim_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name != "aim_memory_store":
        return args

    if isinstance(args.get("entities"), list):
        return args

    name = str(args.get("name") or "").strip() or "Memory"
    description = str(args.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="missing_description")

    entity_type = str(args.get("entityType") or args.get("entity_type") or "note").strip() or "note"
    tz = _get_user_timezone(DEFAULT_USER_ID)
    now = datetime.now(tz=timezone.utc)
    due_at_utc, local_iso = _parse_time_from_text(description, now, tz)
    if due_at_utc is not None:
        entity_type = "reminder"
    observations = args.get("observations")
    if not isinstance(observations, list):
        observations = [description]
    else:
        # Normalize observations to strings
        observations = [str(o) for o in observations if str(o).strip()]
        if not observations:
            observations = [description]

    if due_at_utc is not None and local_iso is not None:
        observations = list(observations)
        observations.append(f"TIMEZONE: {tz.key}")
        observations.append(f"ISO_TIME: {due_at_utc.replace(tzinfo=timezone.utc).isoformat()}")
        observations.append(f"LOCAL_TIME: {local_iso}")

    out: dict[str, Any] = {}
    context = args.get("context")
    if context is not None:
        out["context"] = str(context)
    location = args.get("location")
    if location is not None:
        out["location"] = str(location)

    out["entities"] = [
        {
            "name": name,
            "entityType": entity_type,
            "observations": observations,
        }
    ]
    return out


MCP_TOOL_MAP: dict[str, dict[str, Any]] = {
    "web_fetch": {
        "mcp_name": "fetch_1mcp_fetch",
        "description": "Fetch and extract readable text from a URL via the 1MCP fetch server.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP(S) URL to fetch."},
                "max_length": {"type": "integer", "description": "Maximum number of characters to return."},
                "start_index": {"type": "integer", "description": "Start content from this character index."},
                "raw": {"type": "boolean", "description": "Return raw content without markdown conversion."},
            },
            "required": ["url"],
        },
        "requires_confirmation": False,
    },
    "sequential_thinking": {
        "mcp_name": "server-sequential-thinking_1mcp_sequentialthinking",
        "description": "Run a step of Sequential Thinking (via 1MCP).",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "nextThoughtNeeded": {"type": "boolean"},
                "thoughtNumber": {"type": "integer"},
                "totalThoughts": {"type": "integer"},
                "isRevision": {"type": "boolean"},
                "revisesThought": {"type": "integer"},
                "branchFromThought": {"type": "integer"},
                "branchId": {"type": "string"},
                "needsMoreThoughts": {"type": "boolean"},
            },
            "required": ["thought", "nextThoughtNeeded", "thoughtNumber", "totalThoughts"],
        },
        "requires_confirmation": False,
    },
    "browser_navigate": {
        "mcp_name": "playwright_1mcp_browser_navigate",
        "description": "Navigate the browser to a URL (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
        "requires_confirmation": True,
    },
    "browser_snapshot": {
        "mcp_name": "playwright_1mcp_browser_snapshot",
        "description": "Capture an accessibility snapshot of the page (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },
    "browser_click": {
        "mcp_name": "playwright_1mcp_browser_click",
        "description": "Click an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
            },
            "required": ["ref"],
        },
        "requires_confirmation": True,
    },
    "browser_type": {
        "mcp_name": "playwright_1mcp_browser_type",
        "description": "Type into an element (via 1MCP Playwright). Requires confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "element": {"type": "string"},
                "ref": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["ref", "text"],
        },
        "requires_confirmation": True,
    },
    "browser_wait_for": {
        "mcp_name": "playwright_1mcp_browser_wait_for",
        "description": "Wait for text or time (via 1MCP Playwright).",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {"type": "number"},
                "text": {"type": "string"},
                "textGone": {"type": "string"},
            },
        },
        "requires_confirmation": False,
    },

    "aim_memory_store": {
        "mcp_name": "aim-kg_1mcp_aim_memory_store",
        "description": "Store entities/observations in the AIM knowledge graph memory store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Optional memory context. Defaults to master database if not specified.",
                },
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The name of the entity"},
                            "entityType": {"type": "string", "description": "The type of the entity"},
                            "observations": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Observations associated with the entity",
                            },
                        },
                        "required": ["name", "entityType", "observations"],
                    },
                },
            },
            "required": ["entities"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_add_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_add_facts",
        "description": "Add facts/observations to an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "contents": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "contents"],
                    },
                },
            },
            "required": ["observations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_link": {
        "mcp_name": "aim-kg_1mcp_aim_memory_link",
        "description": "Link two memory entities together.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Optional memory context."},
                "location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Optional storage location override.",
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_search": {
        "mcp_name": "aim-kg_1mcp_aim_memory_search",
        "description": "Search memory entities by keyword.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "query": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["query"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_get": {
        "mcp_name": "aim-kg_1mcp_aim_memory_get",
        "description": "Get memory entities by exact name.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "names": {"type": "array", "items": {"type": "string"}},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
            "required": ["names"],
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_read_all": {
        "mcp_name": "aim-kg_1mcp_aim_memory_read_all",
        "description": "Read all memories from a store.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "format": {"type": "string", "enum": ["json", "pretty"]},
            },
        },
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_list_stores": {
        "mcp_name": "aim-kg_1mcp_aim_memory_list_stores",
        "description": "List available memory stores/databases.",
        "parameters": {"type": "object", "properties": {}},
        "requires_confirmation": False,
        "mcp_base": "aim",
    },
    "aim_memory_forget": {
        "mcp_name": "aim-kg_1mcp_aim_memory_forget",
        "description": "Forget/delete memories.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "entityNames": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["entityNames"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_remove_facts": {
        "mcp_name": "aim-kg_1mcp_aim_memory_remove_facts",
        "description": "Remove facts from an existing memory entity.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "deletions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entityName": {"type": "string"},
                            "observations": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["entityName", "observations"],
                    },
                },
            },
            "required": ["deletions"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
    "aim_memory_unlink": {
        "mcp_name": "aim-kg_1mcp_aim_memory_unlink",
        "description": "Remove links between memory entities.",
        "parameters": {
            "type": "object",
            "properties": {
                "context": {"type": "string"},
                "location": {"type": "string", "enum": ["project", "global"]},
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                            "relationType": {"type": "string"},
                        },
                        "required": ["from", "to", "relationType"],
                    },
                },
            },
            "required": ["relations"],
        },
        "requires_confirmation": True,
        "mcp_base": "aim",
    },
}


def _mcp_tool_declarations() -> list[dict[str, Any]]:
    decls: list[dict[str, Any]] = []
    for name, meta in MCP_TOOL_MAP.items():
        if str(meta.get("mcp_base") or "").strip().lower() == "aim" and not AIM_MCP_BASE_URL:
            continue
        if JARVIS_TOOL_ALLOWLIST and name not in JARVIS_TOOL_ALLOWLIST:
            continue
        decl: dict[str, Any] = {
            "name": name,
            "description": str(meta.get("description") or ""),
        }
        params = meta.get("parameters")
        if isinstance(params, dict):
            decl["parameters"] = params
        decls.append(decl)

    decls.append(
        {
            "name": "time_now",
            "description": "Return the authoritative current server time (UTC + local timezone).",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "IANA timezone name (e.g. Asia/Bangkok)."},
                },
            },
        }
    )

    decls.append({"name": "pending_list", "description": "List queued pending actions waiting for confirmation."})
    decls.append(
        {
            "name": "pending_confirm",
            "description": "Confirm and execute a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )
    decls.append(
        {
            "name": "pending_cancel",
            "description": "Cancel a queued pending action.",
            "parameters": {
                "type": "object",
                "properties": {"confirmation_id": {"type": "string"}},
                "required": ["confirmation_id"],
            },
        }
    )

    decls.append(
        {
            "name": "reminders_list",
            "description": "List reminders from the local Jarvis session DB (including fired/old reminders).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: all|pending|fired|done"},
                    "limit": {"type": "integer", "description": "Max rows (default 50, max 500)"},
                    "offset": {"type": "integer", "description": "Offset for pagination"},
                    "order": {"type": "string", "description": "Sort by updated_at: asc|desc"},
                },
            },
        }
    )

    decls.append(
        {
            "name": "reminders_upcoming",
            "description": "List upcoming pending reminders in the next N hours (defaults to 48).",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_hours": {"type": "integer", "description": "How far ahead to look (hours)."},
                    "time_field": {
                        "type": "string",
                        "description": "Which timestamp to use: notify_at|due_at (default notify_at).",
                    },
                    "limit": {"type": "integer", "description": "Max rows (default 50, max 500)."},
                },
            },
        }
    )

    decls.append(
        {
            "name": "reminders_done",
            "description": "Mark a reminder as done/completed so it disappears from upcoming/today views.",
            "parameters": {
                "type": "object",
                "properties": {"reminder_id": {"type": "string"}},
                "required": ["reminder_id"],
            },
        }
    )
    return decls


async def _handle_mcp_tool_call(session_id: Optional[str], tool_name: str, args: dict[str, Any]) -> Any:
    if tool_name == "time_now":
        tz_raw = str(args.get("timezone") or "").strip()
        if tz_raw:
            try:
                tz = ZoneInfo(tz_raw)
            except Exception:
                tz = _get_user_timezone(DEFAULT_USER_ID)
        else:
            tz = _get_user_timezone(DEFAULT_USER_ID)
        now_utc = datetime.now(tz=timezone.utc)
        now_local = now_utc.astimezone(tz)
        return {
            "unix_ts": int(now_utc.timestamp()),
            "utc_iso": now_utc.replace(tzinfo=timezone.utc).isoformat(),
            "local_iso": now_local.isoformat(),
            "timezone": tz.key,
        }

    if tool_name == "pending_list":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        return _list_pending_writes(session_id)

    if tool_name == "pending_confirm":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        pending = _pop_pending_write(session_id, confirmation_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        action = str(pending.get("action") or "")
        payload = pending.get("payload")
        if action == "mcp_tools_call":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            mcp_name = str(payload.get("mcp_name") or "")
            mcp_args = payload.get("arguments")
            mcp_base = str(payload.get("mcp_base") or "").strip().lower()
            original_tool_name = str(payload.get("tool_name") or "").strip()
            if not mcp_name or not isinstance(mcp_args, dict):
                raise HTTPException(status_code=400, detail="invalid_pending_payload")
            if mcp_base == "aim":
                adapted = _adapt_aim_tool_args(original_tool_name or "", dict(mcp_args))
                return await _aim_mcp_tools_call(mcp_name, adapted)
            return await _mcp_tools_call(mcp_name, mcp_args)
        raise HTTPException(status_code=400, detail={"unknown_pending_action": action})

    if tool_name == "pending_cancel":
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            raise HTTPException(status_code=400, detail="missing_confirmation_id")
        ok = _cancel_pending_write(session_id, confirmation_id)
        if not ok:
            raise HTTPException(status_code=404, detail="pending_write_not_found")
        return {"ok": True}

    if tool_name == "reminders_list":
        status = str(args.get("status") or "all")
        limit = int(args.get("limit") or 50)
        offset = int(args.get("offset") or 0)
        order = str(args.get("order") or "desc")
        include_hidden = bool(args.get("include_hidden") or False)
        return _list_reminders(
            user_id=DEFAULT_USER_ID,
            status=status,
            limit=limit,
            offset=offset,
            order=order,
            include_hidden=include_hidden,
        )

    if tool_name == "reminders_upcoming":
        window_hours = int(args.get("window_hours") or 48)
        time_field = str(args.get("time_field") or "notify_at")
        limit = int(args.get("limit") or 50)
        now_ts = int(time.time())
        end_ts = now_ts + max(1, window_hours) * 3600
        return _list_upcoming_pending_reminders(
            user_id=DEFAULT_USER_ID,
            start_ts=now_ts,
            end_ts=end_ts,
            time_field=time_field,
            limit=limit,
        )

    if tool_name == "reminders_done":
        reminder_id = str(args.get("reminder_id") or "").strip()
        if not reminder_id:
            raise HTTPException(status_code=400, detail="missing_reminder_id")
        changed = _mark_reminder_done(reminder_id)
        wv: Optional[dict[str, Any]] = None
        if _weaviate_enabled():
            try:
                wv = await _mark_reminder_done_weaviate(reminder_id)
            except Exception as e:
                wv = {"ok": False, "error": str(e)}
        await _broadcast_to_user(
            DEFAULT_USER_ID,
            {"type": "reminder_done", "reminder_id": reminder_id, "changed": changed, "weaviate": wv, "instance_id": INSTANCE_ID},
        )
        return {"ok": True, "reminder_id": reminder_id, "changed": changed, "weaviate": wv}

    meta = MCP_TOOL_MAP.get(tool_name)
    if not meta:
        raise HTTPException(status_code=400, detail={"unknown_tool": tool_name})

    mcp_name = str(meta.get("mcp_name") or "")
    if not mcp_name:
        raise HTTPException(status_code=500, detail="mcp_tool_missing_mapping")

    requires_confirmation = bool(meta.get("requires_confirmation"))
    mcp_base = str(meta.get("mcp_base") or "").strip().lower()
    if requires_confirmation:
        if not session_id:
            raise HTTPException(status_code=400, detail="missing_session_id")
        confirmation_id = _create_pending_write(
            session_id,
            action="mcp_tools_call",
            payload={"mcp_name": mcp_name, "arguments": dict(args), "mcp_base": mcp_base, "tool_name": tool_name},
        )
        return {
            "requires_confirmation": True,
            "confirmation_id": confirmation_id,
            "action": tool_name,
            "payload": args,
        }

    if mcp_base == "aim":
        adapted = _adapt_aim_tool_args(tool_name, dict(args))
        result = await _aim_mcp_tools_call(mcp_name, adapted)

        if tool_name == "aim_memory_store":
            try:
                entities = adapted.get("entities")
                if isinstance(entities, list) and entities:
                    ent0 = entities[0] if isinstance(entities[0], dict) else {}
                    title = str(ent0.get("name") or "Reminder").strip() or "Reminder"
                    obs = ent0.get("observations")
                    source_text = ""
                    if isinstance(obs, list) and obs:
                        source_text = str(obs[0])

                    tz = _get_user_timezone(DEFAULT_USER_ID)
                    now = datetime.now(tz=timezone.utc)
                    due_at_utc, _ = _parse_time_from_text(source_text, now, tz)
                    if due_at_utc is not None:
                        schedule_type = "morning_brief"
                        notify_at_local = _next_morning_brief_at(now, tz, due_at_utc)
                        notify_at_utc = notify_at_local.astimezone(timezone.utc)
                        reminder_id = _create_reminder(
                            user_id=DEFAULT_USER_ID,
                            title=title,
                            due_at_utc=due_at_utc,
                            tz=tz,
                            schedule_type=schedule_type,
                            notify_at_utc=notify_at_utc,
                            source_text=source_text,
                            aim_entity_name=title,
                        )
                        return {"aim": result, "reminder": {"reminder_id": reminder_id, "schedule_type": schedule_type}}
            except Exception as e:
                logger.warning("reminder_create_failed error=%s", e)
        return result
    return await _mcp_tools_call(mcp_name, dict(args))


def _fc_args(fc: Any) -> dict[str, Any]:
    args = getattr(fc, "args", None)
    if isinstance(args, dict):
        return args
    args = getattr(fc, "arguments", None)
    if isinstance(args, dict):
        return args
    # Fallback: try model_dump if present
    try:
        dumped = fc.model_dump()  # type: ignore[attr-defined]
        for k in ("args", "arguments"):
            if isinstance(dumped.get(k), dict):
                return dumped[k]
    except Exception:
        pass
    return {}


async def _ws_to_gemini_loop(ws: WebSocket, session: Any) -> None:
    audio_frames = 0
    gemini_available = True
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        # Session control messages (handled locally, never forwarded to Gemini)
        if msg_type == "get_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            if not session_id:
                await ws.send_json({"type": "active_trip", "active_trip_id": None, "active_trip_name": None})
                continue
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "set_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            active_trip_id = msg.get("active_trip_id")
            active_trip_name = msg.get("active_trip_name")
            if not session_id:
                await ws.send_json({"type": "error", "message": "missing_session_id"})
                continue
            _set_session_state(
                str(session_id),
                str(active_trip_id) if active_trip_id is not None else None,
                str(active_trip_name) if active_trip_name is not None else None,
            )
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "cars_ingest_image":
            await _handle_cars_ingest_image(ws, msg if isinstance(msg, dict) else {})
            continue

        if msg_type == "audio":
            if not gemini_available:
                continue
            data_b64 = str(msg.get("data") or "")
            mime_type = str(msg.get("mimeType") or "audio/pcm;rate=16000")
            if not data_b64:
                continue
            try:
                audio_bytes = base64.b64decode(data_b64)
                await session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_audio_failed error=%s", str(e))
                try:
                    await ws.send_json({"type": "error", "message": "gemini_unavailable", "detail": str(e)})
                except Exception:
                    pass
                continue
            audio_frames += 1
            if audio_frames % 50 == 0:
                logger.info("forwarded_audio_frames=%s", audio_frames)
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            logger.info("ws_in_text len=%s head=%s", len(text), text[:120])
            handled = await _dispatch_sub_agents(ws, text)
            logger.info("ws_in_text_dispatched handled=%s active_agent_id=%s", handled, getattr(ws.state, "active_agent_id", None))
            if handled:
                continue
            if not gemini_available:
                try:
                    await ws.send_json({"type": "error", "message": "gemini_unavailable"})
                except Exception:
                    pass
                continue
            try:
                await session.send_client_content(turns={"parts": [{"text": text}]}, turn_complete=True)
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_text_failed error=%s", str(e))
                try:
                    await ws.send_json({"type": "error", "message": "gemini_unavailable", "detail": str(e)})
                except Exception:
                    pass
            continue

        if msg_type == "audio_stream_end":
            if not gemini_available:
                continue
            try:
                await session.send_realtime_input(audio_stream_end=True)
            except Exception as e:
                gemini_available = False
                logger.warning("gemini_send_audio_end_failed error=%s", str(e))
                try:
                    await ws.send_json({"type": "error", "message": "gemini_unavailable", "detail": str(e)})
                except Exception:
                    pass
            continue

        if msg_type == "close":
            return


async def _live_say(ws: WebSocket, text: str) -> None:
    s = str(text or "").strip()
    if not s:
        return
    session = getattr(ws.state, "gemini_live_session", None)
    if session is None:
        return
    try:
        await session.send_client_content(turns={"parts": [{"text": s}]}, turn_complete=True)
    except Exception:
        return


async def _ws_local_only_loop(ws: WebSocket) -> None:
    while True:
        msg = await ws.receive_json()
        msg_type = msg.get("type")

        if msg_type == "get_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            if not session_id:
                await ws.send_json({"type": "active_trip", "active_trip_id": None, "active_trip_name": None})
                continue
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "set_active_trip":
            session_id = getattr(ws.state, "session_id", None)
            active_trip_id = msg.get("active_trip_id")
            active_trip_name = msg.get("active_trip_name")
            if not session_id:
                await ws.send_json({"type": "error", "message": "missing_session_id"})
                continue
            _set_session_state(
                str(session_id),
                str(active_trip_id) if active_trip_id is not None else None,
                str(active_trip_name) if active_trip_name is not None else None,
            )
            state = _get_session_state(str(session_id))
            await ws.send_json({"type": "active_trip", **state})
            continue

        if msg_type == "cars_ingest_image":
            await _handle_cars_ingest_image(ws, msg if isinstance(msg, dict) else {})
            continue

        if msg_type == "audio":
            # Local-only mode: ignore audio frames (no Gemini Live session).
            continue

        if msg_type == "audio_stream_end":
            continue

        if msg_type == "text":
            text = str(msg.get("text") or "")
            if not text:
                continue
            logger.info("ws_in_text_local_only len=%s head=%s", len(text), text[:120])
            handled = await _dispatch_sub_agents(ws, text)
            logger.info(
                "ws_in_text_local_only_dispatched handled=%s active_agent_id=%s",
                handled,
                getattr(ws.state, "active_agent_id", None),
            )
            if handled:
                continue
            await ws.send_json({"type": "error", "message": "gemini_unavailable"})
            continue

        if msg_type == "close":
            return


def _extract_audio_b64(server_msg: Any) -> Optional[str]:
    try:
        server_content = getattr(server_msg, "server_content", None)
        if not server_content:
            return None
        model_turn = getattr(server_content, "model_turn", None)
        if not model_turn:
            return None
        parts = getattr(model_turn, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if not data:
                continue
            if isinstance(data, (bytes, bytearray)):
                return base64.b64encode(bytes(data)).decode("ascii")
            if isinstance(data, str):
                return data
            try:
                as_bytes = bytes(data)
                return base64.b64encode(as_bytes).decode("ascii")
            except Exception:
                return str(data)
    except Exception:
        return None
    return None


async def _gemini_to_ws_loop(ws: WebSocket, session: Any) -> None:
    audio_out_frames = 0
    logged_shape = False
    logged_server_content_shape = False
    while True:
        async for server_msg in session.receive():
            tool_call = getattr(server_msg, "tool_call", None)
            if tool_call is not None:
                function_calls = getattr(tool_call, "function_calls", None) or []
                logger.info("gemini_tool_call count=%s", len(function_calls))
                function_responses: list[Any] = []
                for fc in function_calls:
                    fc_id = getattr(fc, "id", None)
                    fc_name = str(getattr(fc, "name", "") or "")
                    fc_args = _fc_args(fc)
                    logger.info("gemini_tool_call_item name=%s args_keys=%s", fc_name, list(fc_args.keys()))
                    try:
                        session_id = getattr(ws.state, "session_id", None)
                        if fc_name in MCP_TOOL_MAP or fc_name in (
                            "time_now",
                            "pending_list",
                            "pending_confirm",
                            "pending_cancel",
                            "reminders_list",
                            "reminders_upcoming",
                            "reminders_done",
                        ):
                            result = await _handle_mcp_tool_call(session_id, fc_name, fc_args)
                        else:
                            raise HTTPException(status_code=400, detail={"unknown_tool": fc_name})
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": True, "result": result},
                            )
                        )
                    except HTTPException as e:
                        logger.info("gemini_tool_call_error name=%s status_code=%s", fc_name, e.status_code)
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": e.detail, "status_code": e.status_code},
                            )
                        )
                    except Exception as e:
                        logger.info("gemini_tool_call_exception name=%s error=%s", fc_name, str(e))
                        function_responses.append(
                            types.FunctionResponse(
                                id=fc_id,
                                name=fc_name,
                                response={"ok": False, "error": str(e)},
                            )
                        )

                if function_responses:
                    await session.send_tool_response(function_responses=function_responses)
                continue

            transcription = getattr(server_msg, "transcription", None)
            if transcription is not None:
                text = getattr(transcription, "text", None)
                if text:
                    await ws.send_json({"type": "transcript", "text": str(text)})
                    continue
            elif not logged_shape:
                # One-time debug to understand server message fields.
                try:
                    keys = list(getattr(server_msg, "__dict__", {}).keys())
                    logger.info("live_msg_fields=%s", keys)
                except Exception:
                    logger.info("live_msg_type=%s", type(server_msg))
                logged_shape = True

            server_content = getattr(server_msg, "server_content", None)
            if server_content is not None:
                if not logged_server_content_shape:
                    try:
                        keys = list(getattr(server_content, "__dict__", {}).keys())
                        logger.info("live_server_content_fields=%s", keys)
                    except Exception:
                        logger.info("live_server_content_type=%s", type(server_content))
                    logged_server_content_shape = True

                input_tr = getattr(server_content, "input_transcription", None)
                if input_tr is not None:
                    text = getattr(input_tr, "text", None)
                    if text:
                        logger.info("live_input_transcript text=%s", str(text)[:300])
                        # Voice UX: allow local sub-agents (e.g., reminders) to trigger from
                        # input transcription even if Gemini doesn't emit a tool_call.
                        try:
                            handled = await _dispatch_sub_agents(ws, str(text))
                            if handled:
                                logger.info("live_input_transcript_dispatched handled=true")
                                continue
                        except Exception as e:
                            logger.info("input_transcript_dispatch_failed error=%s", str(e))
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "input"})
                        continue

                output_tr = getattr(server_content, "output_transcription", None)
                if output_tr is not None:
                    text = getattr(output_tr, "text", None)
                    if text:
                        await ws.send_json({"type": "transcript", "text": str(text), "source": "output"})
                        continue

                model_turn = getattr(server_content, "model_turn", None)
                if model_turn is not None:
                    parts = getattr(model_turn, "parts", None) or []
                    for part in parts:
                        part_text = getattr(part, "text", None)
                        if part_text:
                            await ws.send_json({"type": "text", "text": str(part_text)})
                            break

            audio_b64 = _extract_audio_b64(server_msg)
            if audio_b64:
                await ws.send_json({"type": "audio", "data": audio_b64, "sampleRate": 24000})
                audio_out_frames += 1
                if audio_out_frames % 10 == 0:
                    logger.info("sent_audio_frames=%s", audio_out_frames)
                continue

            # Send text if present (useful for debugging / future UI)
            text = getattr(server_msg, "text", None)
            if text:
                await ws.send_json({"type": "text", "text": str(text)})


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()

    user_id = DEFAULT_USER_ID
    _ws_by_user.setdefault(user_id, set()).add(ws)

    # Sticky session support: the frontend provides ?session_id=... so we can persist
    # per-session state (e.g., active trip) across reconnects.
    session_id = str(ws.query_params.get("session_id") or "").strip() or None
    ws.state.session_id = session_id
    if session_id:
        try:
            _init_session_db()
            state = _get_session_state(session_id)
            await ws.send_json({"type": "active_trip", **state})
        except Exception as e:
            logger.warning("session_db_init_failed error=%s", e)

    connected_sent = False
    try:
        api_key = str(os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        if not api_key:
            await ws.send_json(
                {
                    "type": "error",
                    "kind": "missing_api_key",
                    "message": "missing_api_key",
                    "detail": "Missing required env var: API_KEY (or GEMINI_API_KEY)",
                }
            )
            await _ws_local_only_loop(ws)
            return
        client = genai.Client(api_key=api_key)

        class _GeminiLiveModelNotFound(Exception):
            def __init__(self, detail: str) -> None:
                super().__init__(detail)
                self.detail = detail

        class _GeminiLiveSessionFailed(Exception):
            def __init__(self, detail: str) -> None:
                super().__init__(detail)
                self.detail = detail

        def _classify_gemini_live_error(err: Exception, model: str) -> dict[str, Any]:
            msg = str(err)
            status_code = getattr(err, "status_code", None)
            if status_code == 1008 or "requested entity was not found" in msg.lower():
                return {
                    "kind": "gemini_model_not_found",
                    "message": "gemini_live_model_not_found",
                    "model": model,
                    "hint": "Set GEMINI_LIVE_MODEL to a model your API key can access.",
                    "detail": msg,
                }
            return {
                "kind": "gemini_session_failed",
                "message": "gemini_session_failed",
                "model": model,
                "detail": msg,
            }

        base_config = {
            "response_modalities": ["AUDIO", "TEXT"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "tools": [
                {"function_declarations": _mcp_tool_declarations()},
            ],
        }

        base_candidates = [
            "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini-2.5-flash-native-audio-preview-09-2025",
            "gemini-2.5-flash-native-audio-latest",
        ]

        raw_candidates = [
            GEMINI_LIVE_MODEL_OVERRIDE,
            *(base_candidates if GEMINI_LIVE_MODEL_OVERRIDE else [GEMINI_LIVE_MODEL_DEFAULT, *base_candidates]),
        ]

        # Gemini Live model naming can vary by endpoint/version. Be permissive:
        # - accept both with and without the `models/` prefix
        # - try `models/<id>` first to match `models.list()` output
        expanded: list[str] = []
        for m in raw_candidates:
            m = str(m or "").strip()
            if not m:
                continue
            expanded.append(_normalize_models_prefix(m))
            expanded.append(_normalize_model_name(m))

        seen: set[str] = set()
        model_candidates = [m for m in expanded if m and not (m in seen or seen.add(m))]

        logger.info(
            "gemini_live_connect model=%s",
            model_candidates[0] if model_candidates else (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT),
        )

        # Resilient supervision: keep the client WS open even if Gemini fails.
        gemini_failed_event: asyncio.Event = asyncio.Event()
        gemini_failed_error: dict[str, Any] | None = None

        async def _safe_gemini_to_ws_loop(ws2: WebSocket, session2: Any) -> None:
            try:
                await _gemini_to_ws_loop(ws2, session2)
            except Exception as e:
                model_used = getattr(ws2.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
                classified = _classify_gemini_live_error(e, str(model_used))
                if classified.get("kind") == "gemini_model_not_found":
                    logger.warning(
                        "gemini_to_ws_failed_model_not_found model=%s error=%s",
                        model_used,
                        classified.get("detail"),
                    )
                else:
                    logger.exception("gemini_to_ws_failed error=%s", str(e))

                logger.info(
                    "gemini_to_ws_failed_meta model=%s exc_type=%s status_code=%s",
                    model_used,
                    type(e).__name__,
                    getattr(e, "status_code", None),
                )
                try:
                    await ws2.send_json({"type": "error", **classified})
                except Exception:
                    pass

                # Signal the session runner so it can tear down and retry with the
                # next candidate model.
                nonlocal gemini_failed_error
                gemini_failed_error = classified
                gemini_failed_event.set()

        async def _run_with_config(model: str, cfg: dict[str, Any]) -> None:
            nonlocal gemini_failed_error
            gemini_failed_error = None
            try:
                gemini_failed_event.clear()
            except Exception:
                pass
            ws.state.gemini_live_model = model
            session_cm = client.aio.live.connect(model=model, config=cfg)
            try:
                async with session_cm as session:
                    logger.info("gemini_live_connected model=%s", model)
                    ws.state.gemini_live_session = session
                    await ws.send_json({"type": "state", "state": "connected", "instance_id": INSTANCE_ID})
                    connected_sent = True

                    try:
                        tz = _get_user_timezone(DEFAULT_USER_ID)
                        now_utc = datetime.now(tz=timezone.utc)
                        now_local = now_utc.astimezone(tz)
                        time_ctx = (
                            "TIME_CONTEXT (authoritative server time)\n"
                            f"TIMEZONE: {tz.key}\n"
                            f"NOW_UTC: {now_utc.replace(tzinfo=timezone.utc).isoformat()}\n"
                            f"NOW_LOCAL: {now_local.isoformat()}\n"
                            "Use this as the reference for all relative time calculations."
                        )
                        await session.send_client_content(turns={"parts": [{"text": time_ctx}]}, turn_complete=True)
                    except Exception as e:
                        logger.info("time_context_inject_failed error=%s", str(e))

                    to_gemini = asyncio.create_task(_ws_to_gemini_loop(ws, session), name="ws_to_gemini")
                    to_ws = asyncio.create_task(_safe_gemini_to_ws_loop(ws, session), name="gemini_to_ws")
                    wait_failed: asyncio.Task[bool] | None = None

                    try:
                        # Either the client disconnects (ws_to_gemini finishes) or Gemini fails.
                        wait_failed = asyncio.create_task(gemini_failed_event.wait(), name="gemini_failed_wait")
                        done, pending = await asyncio.wait(
                            {to_gemini, wait_failed},
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        if wait_failed in done and gemini_failed_event.is_set():
                            # Gemini failed; tear down this session to allow outer retry.
                            if not to_gemini.done():
                                to_gemini.cancel()
                                try:
                                    await to_gemini
                                except asyncio.CancelledError:
                                    pass
                                except Exception:
                                    pass
                            if not to_ws.done():
                                to_ws.cancel()
                                try:
                                    await to_ws
                                except asyncio.CancelledError:
                                    pass
                                except Exception:
                                    pass

                            detail = (gemini_failed_error or {}).get("detail") or "gemini_failed"
                            kind = (gemini_failed_error or {}).get("kind")
                            if kind == "gemini_model_not_found":
                                raise _GeminiLiveModelNotFound(str(detail))
                            raise _GeminiLiveSessionFailed(str(detail))

                        # Client disconnected or finished.
                        await to_gemini
                    except WebSocketDisconnect:
                        return
                    finally:
                        try:
                            if wait_failed is not None and not wait_failed.done():
                                wait_failed.cancel()
                        except Exception:
                            pass

                        if not to_ws.done():
                            to_ws.cancel()
                            try:
                                await to_ws
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                pass
            finally:
                try:
                    ws.state.gemini_live_session = None
                except Exception:
                    pass

        if last_error is not None:
            msg = str(last_error)
            if "invalid argument" not in msg.lower():
                model_used = getattr(ws.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
                classified = _classify_gemini_live_error(last_error, str(model_used))
                if classified.get("kind") == "gemini_model_not_found":
                    logger.warning(
                        "gemini_live_session_model_not_found model=%s error=%s",
                        model_used,
                        classified.get("detail"),
                    )
                    try:
                        await ws.send_json({"type": "error", **classified})
                    except Exception:
                        pass
                    await _ws_local_only_loop(ws)
                    return
                else:
                    logger.exception("gemini_live_session_failed model=%s error=%s", model_used, msg)
                    try:
                        await ws.send_json({"type": "error", **classified})
                    except Exception:
                        pass
                    await _ws_local_only_loop(ws)
                    return
            else:
                cfg = dict(base_config)
                cfg["response_modalities"] = ["AUDIO"]
                model_used = getattr(ws.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
                logger.warning(
                    "gemini_live_connect_retry_invalid_argument model=%s before=%s after=%s error=%s",
                    model_used,
                    base_config.get("response_modalities"),
                    cfg.get("response_modalities"),
                    msg,
                )
                await _run_with_config(str(model_used), cfg)

    except WebSocketDisconnect:
        return
    except Exception as e:
        classified: Optional[dict[str, Any]] = None
        try:
            if "_classify_gemini_live_error" in locals():
                model_used = getattr(ws.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
                classified = _classify_gemini_live_error(e, str(model_used))
        except Exception:
            classified = None
        try:
            if classified is not None:
                await ws.send_json({"type": "error", **classified})
        except Exception:
            pass
        if classified and classified.get("kind") == "gemini_model_not_found":
            model_used = getattr(ws.state, "gemini_live_model", None) or (GEMINI_LIVE_MODEL_OVERRIDE or GEMINI_LIVE_MODEL_DEFAULT)
            logger.warning("ws_live_model_not_found model=%s error=%s", model_used, classified.get("detail"))
            try:
                await ws.send_json({"type": "error", **classified})
            except Exception:
                pass
            if not connected_sent:
                try:
                    await ws.send_json({"type": "state", "state": "connected", "instance_id": INSTANCE_ID})
                except Exception:
                    pass
            try:
                await _ws_local_only_loop(ws)
            except WebSocketDisconnect:
                return
            return

        logger.exception("ws_live_exception")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        return
    finally:
        s = _ws_by_user.get(user_id)
        if s is not None:
            s.discard(ws)
