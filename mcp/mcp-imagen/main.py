from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from diffusers import AutoPipelineForText2Image
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

APP_NAME = "mcp-imagen"
APP_VERSION = "0.1.0"

PORT = int(os.getenv("PORT", "8001"))

_MODEL_ID = os.getenv("IMAGE_MODEL_ID", "runwayml/stable-diffusion-v1-5")
_TORCH_DEVICE = os.getenv("TORCH_DEVICE", "cpu").lower()
_IMAGE_DTYPE = os.getenv("IMAGE_DTYPE", "auto").lower()
_DEFAULT_STEPS = int(os.getenv("IMAGE_STEPS", "25"))
_MAX_STEPS = int(os.getenv("IMAGE_MAX_STEPS", "60"))
_MIN_STEPS = 5
_DEFAULT_WIDTH = int(os.getenv("IMAGE_WIDTH", "512"))
_DEFAULT_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "512"))

_pipeline: Optional[AutoPipelineForText2Image] = None

app = FastAPI(title=APP_NAME, version=APP_VERSION)


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Any
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None


class GenerateImageArgs(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = Field(default=None, alias="negativePrompt")
    guidance_scale: float = Field(default=7.0, alias="guidanceScale")
    num_inference_steps: int = Field(default=_DEFAULT_STEPS, alias="numInferenceSteps")
    width: Optional[int] = None
    height: Optional[int] = None
    seed: Optional[int] = None


def _validate_multiple_of_eight(value: Optional[int], fallback: int) -> int:
    try:
        parsed = int(value) if value is not None else int(fallback)
    except (TypeError, ValueError):
        parsed = fallback
    parsed = max(256, min(parsed, 1024))
    parsed -= parsed % 8
    return parsed or fallback


def _resolve_dtype() -> torch.dtype:
    if _TORCH_DEVICE.startswith("cuda"):
        if _IMAGE_DTYPE in ("fp32", "float32"):
            return torch.float32
        return torch.float16
    return torch.float32


def _get_pipeline() -> AutoPipelineForText2Image:
    global _pipeline
    if _pipeline is None:
        kwargs: Dict[str, Any] = {"torch_dtype": _resolve_dtype()}
        custom_cache = os.getenv("IMAGE_MODEL_CACHE")
        if custom_cache:
            kwargs["cache_dir"] = custom_cache
        pipeline = AutoPipelineForText2Image.from_pretrained(_MODEL_ID, **kwargs)
        pipeline = pipeline.to(_TORCH_DEVICE)
        pipeline.safety_checker = None
        _pipeline = pipeline
    return _pipeline


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def _tool_list() -> List[Dict[str, Any]]:
    return [
        {
            "name": "generate_image",
            "description": "Generate an image from a prompt using Stable Diffusion via diffusers.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": ["string", "null"]},
                    "guidance_scale": {"type": "number"},
                    "num_inference_steps": {"type": "integer"},
                    "width": {"type": ["integer", "null"]},
                    "height": {"type": ["integer", "null"]},
                    "seed": {"type": ["integer", "null"]},
                },
                "required": ["prompt"],
            },
        }
    ]


def _generate_image(args: GenerateImageArgs) -> Dict[str, Any]:
    prompt = (args.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt_required")

    steps = max(_MIN_STEPS, min(_MAX_STEPS, int(args.num_inference_steps or _DEFAULT_STEPS)))
    resolved_width = _validate_multiple_of_eight(args.width, _DEFAULT_WIDTH)
    resolved_height = _validate_multiple_of_eight(args.height, _DEFAULT_HEIGHT)

    pipeline = _get_pipeline()

    generator = None
    used_seed = args.seed
    if args.seed is not None:
        try:
            used_seed = int(args.seed)
            generator = torch.Generator(device=_TORCH_DEVICE).manual_seed(used_seed)
        except (TypeError, ValueError):
            used_seed = None

    started = time.time()
    dtype = _resolve_dtype()
    autocast_ctx = (
        torch.autocast(device_type="cuda")
        if _TORCH_DEVICE.startswith("cuda") and dtype == torch.float16
        else contextlib.nullcontext()
    )
    with torch.inference_mode(), autocast_ctx:
        result = pipeline(
            prompt=prompt,
            negative_prompt=args.negative_prompt.strip() if isinstance(args.negative_prompt, str) else None,
            guidance_scale=float(args.guidance_scale or 7.0),
            num_inference_steps=steps,
            width=resolved_width,
            height=resolved_height,
            generator=generator,
            output_type="np",
        )
    duration_ms = int((time.time() - started) * 1000)

    np_image = result.images[0]
    if not isinstance(np_image, np.ndarray):
        raise RuntimeError("unexpected_image_type")
    if np_image.ndim != 3 or np_image.shape[-1] != 3:
        raise RuntimeError(f"unexpected_image_shape:{getattr(np_image, 'shape', None)}")

    np_image_uint8 = (np.clip(np_image, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    image = Image.fromarray(np_image_uint8, mode="RGB")
    extrema = image.getextrema()
    pixel_min = int(np_image_uint8.min()) if np_image_uint8.size else 0
    pixel_max = int(np_image_uint8.max()) if np_image_uint8.size else 0
    pixel_mean = float(np_image_uint8.mean()) if np_image_uint8.size else 0.0

    return {
        "image_base64": _image_to_base64(image),
        "prompt": prompt,
        "negative_prompt": args.negative_prompt,
        "guidance_scale": float(args.guidance_scale or 7.0),
        "num_inference_steps": steps,
        "width": resolved_width,
        "height": resolved_height,
        "seed": used_seed,
        "duration_ms": duration_ms,
        "model": _MODEL_ID,
        "device": _TORCH_DEVICE,
        "dtype": str(dtype).replace("torch.", ""),
        "pixel_min": pixel_min,
        "pixel_max": pixel_max,
        "pixel_mean": pixel_mean,
        "extrema": extrema,
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "model": _MODEL_ID, "device": _TORCH_DEVICE}


@app.get("/.well-known/mcp.json")
def well_known() -> Dict[str, Any]:
    return {"name": APP_NAME, "version": APP_VERSION, "tools": _tool_list()}


@app.post("/generate")
async def generate_http(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    try:
        args = GenerateImageArgs.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_args: {exc}")

    return JSONResponse(_generate_image(args))


@app.post("/mcp")
async def mcp_rpc(request: Request) -> JSONResponse:
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                },
            },
            status_code=200,
        )

    if method == "notifications/initialized":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": None}, status_code=200)

    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}}, status_code=200)

    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list()}}, status_code=200)

    if method in ("tools/call", "tools/invoke"):
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        if name != "generate_image":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": "method not found"},
                },
                status_code=200,
            )

        if not isinstance(arguments, dict):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "invalid params"},
                },
                status_code=200,
            )

        try:
            args = GenerateImageArgs.model_validate(arguments)
            out = _generate_image(args)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "image",
                                "data": out["image_base64"].split(",", 1)[1],
                                "mimeType": "image/png",
                            }
                        ],
                        "meta": out,
                    },
                },
                status_code=200,
            )
        except HTTPException as exc:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(exc.detail)},
                },
                status_code=200,
            )
        except Exception as exc:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": f"tool_failed: {exc}"},
                },
                status_code=200,
            )

    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        },
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
