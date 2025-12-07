from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import threading
import time
import logging
from typing import Any, Dict, Optional

import torch
from diffusers import AutoPipelineForText2Image
from mcp.server.fastmcp import FastMCP
from PIL import Image
import numpy as np
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.status import HTTP_400_BAD_REQUEST
import uvicorn

logging.basicConfig(level=os.getenv("IMAGE_LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger(__name__)

mcp = FastMCP("StableDiffusionImageGenerator")

_MODEL_ID = os.getenv("IMAGE_MODEL_ID", "runwayml/stable-diffusion-v1-5")
_TORCH_DEVICE = os.getenv("TORCH_DEVICE", "cpu").lower()
_DEFAULT_STEPS = int(os.getenv("IMAGE_STEPS", "25"))
_MAX_STEPS = int(os.getenv("IMAGE_MAX_STEPS", "50"))
_MIN_STEPS = 5
_DEFAULT_WIDTH = int(os.getenv("IMAGE_WIDTH", "512"))
_DEFAULT_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "512"))
_DTYPE_OVERRIDE = (os.getenv("IMAGE_TORCH_DTYPE") or "").strip().lower()
_ADMIN_TOKEN = (os.getenv("IMAGE_ADMIN_TOKEN") or "").strip()

_pipeline: Optional[AutoPipelineForText2Image] = None
_ACCELERATOR_LABEL = "gpu" if _TORCH_DEVICE.startswith("cuda") else "cpu"
_PIPELINE_LOCK = threading.Lock()


def _validate_multiple_of_eight(value: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    parsed = max(256, min(parsed, 1024))
    parsed -= parsed % 8
    return parsed or fallback


def _resolve_dtype() -> torch.dtype:
    if _DTYPE_OVERRIDE:
        mapping = {
            "float16": torch.float16,
            "fp16": torch.float16,
            "half": torch.float16,
            "float32": torch.float32,
            "fp32": torch.float32,
            "full": torch.float32,
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
        }
        dtype = mapping.get(_DTYPE_OVERRIDE)
        if dtype is None:
            LOGGER.warning("Unsupported IMAGE_TORCH_DTYPE=%s, falling back to float32", _DTYPE_OVERRIDE)
        else:
            LOGGER.info("Using IMAGE_TORCH_DTYPE override: %s", _DTYPE_OVERRIDE)
            return dtype
    if _TORCH_DEVICE.startswith("cuda"):
        LOGGER.info("Running on CUDA; defaulting to torch.float32 for stability")
        return torch.float32
    return torch.float32


def _get_pipeline() -> AutoPipelineForText2Image:
    global _pipeline
    if _pipeline is None:
        with _PIPELINE_LOCK:
            if _pipeline is None:
                LOGGER.info("Loading pipeline for model_id=%s", _MODEL_ID)
                kwargs: Dict[str, Any] = {"torch_dtype": _resolve_dtype()}
                custom_cache = os.getenv("IMAGE_MODEL_CACHE")
                if custom_cache:
                    kwargs["cache_dir"] = custom_cache
                pipeline = AutoPipelineForText2Image.from_pretrained(_MODEL_ID, **kwargs)
                pipeline = pipeline.to(_TORCH_DEVICE)
                pipeline.safety_checker = None
                _pipeline = pipeline
    return _pipeline


def _set_model_id(model_id: str, *, warm_start: bool = False) -> str:
    """Update the active model ID and optionally preload the pipeline."""

    global _MODEL_ID, _pipeline
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("model_id is required")
    normalized = model_id.strip()
    with _PIPELINE_LOCK:
        if normalized == _MODEL_ID and _pipeline is not None:
            LOGGER.info("Model %s already active; skipping reload", normalized)
            return _MODEL_ID
        LOGGER.info("Switching model from %s to %s", _MODEL_ID, normalized)
        _MODEL_ID = normalized
        _pipeline = None

    if warm_start:
        try:
            _get_pipeline()
        except Exception:
            # revert to prevent broken state
            LOGGER.exception("Failed to warm-start model %s; reverting", normalized)
            with _PIPELINE_LOCK:
                _MODEL_ID = normalized
                _pipeline = None
            raise
    return _MODEL_ID


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def _latents_to_base64(pipeline: AutoPipelineForText2Image, latents: torch.Tensor) -> Optional[str]:
    try:
        with torch.no_grad():
            device = pipeline.device
            scaled = (latents.to(device) / pipeline.vae.config.scaling_factor)
            decoded = pipeline.vae.decode(scaled).sample
        decoded = (decoded / 2 + 0.5).clamp(0, 1)
        decoded = decoded.cpu().permute(0, 2, 3, 1).float().numpy()
        decoded = np.nan_to_num(decoded, nan=0.5, posinf=1.0, neginf=0.0)
        sample = decoded[0]
        vmin = np.min(sample)
        vmax = np.max(sample)
        if np.isfinite(vmin) and np.isfinite(vmax) and vmax - vmin > 1e-4:
            sample = (sample - vmin) / (vmax - vmin)
        sample = np.clip(sample, 0.0, 1.0)
        array = (sample * 255).round().astype("uint8")
        preview = Image.fromarray(array)
        return _image_to_base64(preview)
    except Exception:
        return None


@mcp.tool()
def generate_image(
    prompt: str,
    negative_prompt: Optional[str] = None,
    guidance_scale: float = 7.0,
    num_inference_steps: int = _DEFAULT_STEPS,
    width: Optional[int] = None,
    height: Optional[int] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt is required")

    steps = max(_MIN_STEPS, min(_MAX_STEPS, int(num_inference_steps or _DEFAULT_STEPS)))
    resolved_width = _validate_multiple_of_eight(width, _DEFAULT_WIDTH)
    resolved_height = _validate_multiple_of_eight(height, _DEFAULT_HEIGHT)

    pipeline = _get_pipeline()
    generator = None
    used_seed = seed
    if seed is not None:
        try:
            used_seed = int(seed)
            generator = torch.Generator(device=_TORCH_DEVICE).manual_seed(used_seed)
        except (TypeError, ValueError):
            used_seed = None

    started = time.time()
    result = pipeline(
        prompt=prompt.strip(),
        negative_prompt=negative_prompt.strip() if isinstance(negative_prompt, str) else None,
        guidance_scale=float(guidance_scale or 7.0),
        num_inference_steps=steps,
        width=resolved_width,
        height=resolved_height,
        generator=generator,
    )
    duration_ms = int((time.time() - started) * 1000)
    image = result.images[0]

    return {
        "image_base64": _image_to_base64(image),
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "guidance_scale": guidance_scale,
        "num_inference_steps": steps,
        "width": resolved_width,
        "height": resolved_height,
        "seed": used_seed,
        "duration_ms": duration_ms,
    }


@mcp.custom_route("/generate", methods=["POST"])
async def generate_http(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=HTTP_400_BAD_REQUEST)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "invalid_payload"}, status_code=HTTP_400_BAD_REQUEST)

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse({"error": "prompt_required"}, status_code=HTTP_400_BAD_REQUEST)

    try:
        data = generate_image(
            prompt=prompt,
            negative_prompt=payload.get("negative_prompt"),
            guidance_scale=float(payload.get("guidance_scale", 7.0)),
            num_inference_steps=int(payload.get("num_inference_steps", _DEFAULT_STEPS)),
            width=payload.get("width"),
            height=payload.get("height"),
            seed=payload.get("seed"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=HTTP_400_BAD_REQUEST)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": "generation_failed", "detail": str(exc)}, status_code=500)

    return JSONResponse(data)


@mcp.custom_route("/generate-stream", methods=["POST"])
async def generate_stream_http(request: Request) -> StreamingResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=HTTP_400_BAD_REQUEST)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "invalid_payload"}, status_code=HTTP_400_BAD_REQUEST)

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse({"error": "prompt_required"}, status_code=HTTP_400_BAD_REQUEST)

    steps = max(_MIN_STEPS, min(_MAX_STEPS, int(payload.get("num_inference_steps", _DEFAULT_STEPS) or _DEFAULT_STEPS)))
    resolved_width = _validate_multiple_of_eight(payload.get("width"), _DEFAULT_WIDTH)
    resolved_height = _validate_multiple_of_eight(payload.get("height"), _DEFAULT_HEIGHT)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
    started = time.time()

    def emit(event: Dict[str, Any]) -> None:
        event.setdefault("accelerator", _ACCELERATOR_LABEL)
        serialized = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
        asyncio.run_coroutine_threadsafe(queue.put(serialized), loop)

    def finalize_queue() -> None:
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    def run_generation() -> None:
        try:
            pipeline = _get_pipeline()
            generator = None
            seed = payload.get("seed")
            used_seed = None
            if seed is not None:
                try:
                    used_seed = int(seed)
                    generator = torch.Generator(device=_TORCH_DEVICE).manual_seed(used_seed)
                except (TypeError, ValueError):
                    used_seed = None

            negative_prompt = payload.get("negative_prompt")
            effective_negative = negative_prompt.strip() if isinstance(negative_prompt, str) else None
            guidance_scale = float(payload.get("guidance_scale", 7.0) or 7.0)

            emit({
                "type": "status",
                "status": "starting",
                "prompt": prompt.strip(),
                "total_steps": steps,
            })

            callback_interval = max(1, steps // 6)

            def progress_callback(step: int, _timestep: int, latents: torch.Tensor) -> None:
                if step <= 0:
                    return
                if step % callback_interval != 0 and step + 1 < steps:
                    return
                preview_base64 = _latents_to_base64(pipeline, latents)
                if not preview_base64:
                    return
                emit(
                    {
                        "type": "progress",
                        "step": step,
                        "total_steps": steps,
                        "image_base64": preview_base64,
                    }
                )

            result = pipeline(
                prompt=prompt.strip(),
                negative_prompt=effective_negative,
                guidance_scale=guidance_scale,
                num_inference_steps=steps,
                width=resolved_width,
                height=resolved_height,
                generator=generator,
                callback=progress_callback,
                callback_steps=1,
            )
            duration_ms = int((time.time() - started) * 1000)
            image = result.images[0]
            emit(
                {
                    "type": "complete",
                    "prompt": prompt,
                    "negative_prompt": effective_negative,
                    "guidance_scale": guidance_scale,
                    "num_inference_steps": steps,
                    "width": resolved_width,
                    "height": resolved_height,
                    "seed": used_seed,
                    "duration_ms": duration_ms,
                    "image_base64": _image_to_base64(image),
                }
            )
        except Exception as exc:  # noqa: BLE001
            emit({"type": "error", "error": str(exc)})
        finally:
            finalize_queue()

    threading.Thread(target=run_generation, daemon=True).start()

    async def event_stream() -> Any:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


async def reload_model(request: Request) -> JSONResponse:
    if not _ADMIN_TOKEN:
        return JSONResponse({"error": "admin_disabled"}, status_code=HTTP_400_BAD_REQUEST)

    provided = request.headers.get("x-image-admin", "") or request.headers.get("x-image-admin-token", "")
    if provided != _ADMIN_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    model_id = payload.get("model_id") if isinstance(payload, dict) else None
    warm_start = bool(payload.get("warm_start")) if isinstance(payload, dict) else False

    try:
        new_id = _set_model_id(model_id or _MODEL_ID, warm_start=warm_start)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=HTTP_400_BAD_REQUEST)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("Model reload failed")
        return JSONResponse({"error": "reload_failed", "detail": str(exc)}, status_code=500)

    response = {"model": new_id, "warm_start": warm_start}
    if warm_start:
        response["status"] = "loaded"
    else:
        response["status"] = "pending"
    return JSONResponse(response)


async def root(_: Request) -> JSONResponse:
    """Return the basic readiness payload for default route checks."""
    return JSONResponse({"status": "ok", "model": _MODEL_ID, "device": _TORCH_DEVICE})


async def health(_: Request) -> JSONResponse:
    """Expose an explicit /health endpoint for Docker healthchecks."""
    return JSONResponse({"status": "ok", "model": _MODEL_ID, "device": _TORCH_DEVICE})


def main() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))

    app = Starlette(
        routes=[
            Route("/", root, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
            Route("/generate", generate_http, methods=["POST"]),
            Route("/generate-stream", generate_stream_http, methods=["POST"]),
            Route("/admin/reload", reload_model, methods=["POST"]),
        ]
    )

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
