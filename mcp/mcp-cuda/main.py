from __future__ import annotations

import base64
import contextlib
import io
import json
import math
import os
import socket
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import traceback

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field
from sentence_transformers import CrossEncoder, SentenceTransformer
import torch
from diffusers import StableDiffusionImg2ImgPipeline, StableDiffusionPipeline, StableDiffusionXLPipeline
from concurrent.futures import ThreadPoolExecutor

APP_NAME = "mcp-cuda"
APP_VERSION = "0.1.0"
MCP_CUDA_INSTANCE_ID = os.getenv("MCP_CUDA_INSTANCE_ID", f"mcp-cuda-{uuid.uuid4().hex[:8]}")

CLIP_MODEL = (os.getenv("CLIP_MODEL") or "clip-ViT-B-32").strip()
MAX_IMAGE_ITEMS = int(os.getenv("MCP_CUDA_MAX_IMAGE_ITEMS", "32"))

TEXT_EMBED_MODEL = (os.getenv("TEXT_EMBED_MODEL") or "all-MiniLM-L6-v2").strip()
RERANK_MODEL = (os.getenv("RERANK_MODEL") or "cross-encoder/ms-marco-MiniLM-L-6-v2").strip()
MAX_TEXT_ITEMS = int(os.getenv("MCP_CUDA_MAX_TEXT_ITEMS", "128"))
MAX_RERANK_DOCS = int(os.getenv("MCP_CUDA_MAX_RERANK_DOCS", "64"))


SDXL_MODEL_DIR = (os.getenv("MCP_CUDA_SDXL_MODEL_DIR") or "/models/sdxl").strip()
SD15_MODEL_FILE = (os.getenv("MCP_CUDA_SD15_MODEL_FILE") or "").strip()
DISABLE_SAFETY_CHECKER = (os.getenv("MCP_CUDA_DISABLE_SAFETY_CHECKER") or "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
ENABLE_XFORMERS = (os.getenv("MCP_CUDA_ENABLE_XFORMERS") or "0").strip().lower() in ("1", "true", "yes")
MAX_DIMENSION = int(os.getenv("MCP_CUDA_MAX_DIMENSION", "2048"))
SDXL_MAX_PIXELS = int(os.getenv("MCP_CUDA_SDXL_MAX_PIXELS", str(1024 * 1024)))
SDXL_MAX_STEPS = int(os.getenv("MCP_CUDA_SDXL_MAX_STEPS", "60"))
SDXL_DEFAULT_STEPS = int(os.getenv("MCP_CUDA_SDXL_DEFAULT_STEPS", "30"))
SDXL_MAX_CONCURRENT_JOBS = int(os.getenv("MCP_CUDA_SDXL_MAX_CONCURRENT_JOBS", "1"))
SDXL_PREVIEW_EVERY_N_STEPS = int(os.getenv("MCP_CUDA_SDXL_PREVIEW_EVERY_N_STEPS", "0"))
SDXL_PREVIEW_MAX_SIZE = int(os.getenv("MCP_CUDA_SDXL_PREVIEW_MAX_SIZE", "512"))

# Backwards compatible preview cadence config.
# Prefer MCP_CUDA_PREVIEW_EVERY_N_STEPS if set; otherwise fall back to SDXL-specific env.
MCP_CUDA_PREVIEW_EVERY_N_STEPS = int(os.getenv("MCP_CUDA_PREVIEW_EVERY_N_STEPS", str(SDXL_PREVIEW_EVERY_N_STEPS or 0)))

# Configurable job retention settings
JOB_RETENTION_DAYS = float(os.getenv("MCP_CUDA_JOB_RETENTION_DAYS", "7"))  # Keep jobs for 7 days by default
MAX_JOBS_TO_RETAIN = int(os.getenv("MCP_CUDA_MAX_JOBS_TO_RETAIN", "100"))  # Max jobs to keep


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


class ToolCallArgs(BaseModel):
    pass


class ToolCallPayload(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ClipImageEmbedArgs(BaseModel):
    images_base64: List[str] = Field(..., alias="imagesBase64")
    normalize: bool = True
    model: Optional[str] = None


class TextEmbedArgs(BaseModel):
    texts: List[str]
    normalize: bool = True
    model: Optional[str] = None


class RerankArgs(BaseModel):
    query: str
    documents: List[str]
    model: Optional[str] = None


class ImagenJobCreateArgs(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = Field(default=None, alias="negativePrompt")
    width: Optional[int] = None
    height: Optional[int] = None
    num_inference_steps: Optional[int] = Field(default=None, alias="numInferenceSteps")
    guidance_scale: Optional[float] = Field(default=None, alias="guidanceScale")
    strength: Optional[float] = None
    seed: Optional[int] = None
    reference_image_base64: Optional[str] = Field(default=None, alias="referenceImageBase64")
    reference_image_dimensions: Optional[tuple[int, int]] = Field(default=None, alias="referenceImageDimensions")


class ImagenJobStatusArgs(BaseModel):
    job_id: str = Field(..., alias="jobId")


class ImagenJobResultArgs(BaseModel):
    job_id: str = Field(..., alias="jobId")


def _run(cmd: List[str], timeout_seconds: int = 10) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def _torch_info() -> Dict[str, Any]:
    cuda_available = bool(torch.cuda.is_available())
    out: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "torch": {
            "version": torch.__version__,
            "cuda_available": cuda_available,
            "cuda_version": getattr(torch.version, "cuda", None),
        },
    }
    if cuda_available:
        out["torch"]["cuda_device_count"] = int(torch.cuda.device_count())
        out["torch"]["cuda_current_device"] = int(torch.cuda.current_device())
        out["torch"]["cuda_device_name"] = torch.cuda.get_device_name(torch.cuda.current_device())
    return out


_clip_model: Optional[SentenceTransformer] = None

_text_model: Optional[SentenceTransformer] = None
_rerank_model: Optional[CrossEncoder] = None


_sdxl_pipeline: Optional[StableDiffusionXLPipeline] = None
_sd15_pipeline: Optional[StableDiffusionPipeline] = None
_sd15_img2img_pipeline: Optional[StableDiffusionImg2ImgPipeline] = None
_sdxl_pipeline_lock = threading.Lock()
_imagen_executor = ThreadPoolExecutor(max_workers=SDXL_MAX_CONCURRENT_JOBS)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp_int(value: Optional[int], *, default: int, min_value: int, max_value: int) -> int:
    v = default if value is None else int(value)
    if v < min_value:
        v = min_value
    if v > max_value:
        v = max_value
    return v


def _round_down_multiple(value: int, *, base: int) -> int:
    if base <= 1:
        return int(value)
    v = int(value)
    v -= v % int(base)
    return v


def _validate_imagen_args(args: ImagenJobCreateArgs) -> Dict[str, Any]:
    prompt = (args.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt_required")

    max_dim = max(256, int(MAX_DIMENSION or 2048))
    width = _clamp_int(args.width, default=1024, min_value=256, max_value=max_dim)
    height = _clamp_int(args.height, default=1024, min_value=256, max_value=max_dim)
    width = max(256, _round_down_multiple(width, base=8))
    height = max(256, _round_down_multiple(height, base=8))
    if width * height > SDXL_MAX_PIXELS:
        raise HTTPException(status_code=400, detail=f"too_many_pixels: max={SDXL_MAX_PIXELS}")

    # referenceImageDimensions is optional.
    # If it is provided, we validate it matches the decoded image dimensions.
    if args.reference_image_dimensions and not args.reference_image_base64:
        raise HTTPException(status_code=400, detail="reference_image_dimensions_without_image")
    if args.reference_image_base64 and args.reference_image_dimensions:
        img_data = base64.b64decode(args.reference_image_base64)
        img = Image.open(io.BytesIO(img_data))
        if (img.width, img.height) != args.reference_image_dimensions:
            raise HTTPException(status_code=400, detail="reference_image_dimensions_mismatch")

    steps = _clamp_int(
        args.num_inference_steps,
        default=SDXL_DEFAULT_STEPS,
        min_value=1,
        max_value=SDXL_MAX_STEPS,
    )
    guidance_scale = float(args.guidance_scale) if args.guidance_scale is not None else 7.0
    strength = float(args.strength) if args.strength is not None else 0.75
    if strength <= 0.0 or strength > 1.0:
        raise HTTPException(status_code=400, detail="strength_out_of_range")
    negative_prompt = (args.negative_prompt or "").strip() or None

    seed = int(args.seed) if args.seed is not None else None
    if seed is not None and seed < 0:
        raise HTTPException(status_code=400, detail="seed_must_be_nonnegative")

    out: Dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "guidance_scale": guidance_scale,
        "strength": strength,
        "seed": seed,
    }

    if args.reference_image_base64:
        out["reference_image_base64"] = str(args.reference_image_base64)
    if args.reference_image_dimensions:
        out["reference_image_dimensions"] = tuple(args.reference_image_dimensions)

    return out


def _get_sdxl_pipeline() -> StableDiffusionXLPipeline:
    global _sdxl_pipeline
    with _sdxl_pipeline_lock:
        if _sdxl_pipeline is not None:
            return _sdxl_pipeline

        if not os.path.exists(SDXL_MODEL_DIR):
            raise HTTPException(status_code=503, detail=f"sdxl_model_dir_missing: {SDXL_MODEL_DIR}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if device == "cuda" else torch.float32

        pipe = StableDiffusionXLPipeline.from_pretrained(
            SDXL_MODEL_DIR,
            torch_dtype=torch_dtype,
            local_files_only=True,
        )
        if DISABLE_SAFETY_CHECKER:
            try:
                pipe.safety_checker = None
                pipe.requires_safety_checker = False
            except Exception:
                pass
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass
        if ENABLE_XFORMERS:
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        if device == "cuda":
            pipe = pipe.to("cuda")
        _sdxl_pipeline = pipe
        return pipe


def _get_sd15_pipeline() -> StableDiffusionPipeline:
    global _sd15_pipeline
    with _sdxl_pipeline_lock:
        if _sd15_pipeline is not None:
            return _sd15_pipeline

        model_file = (SD15_MODEL_FILE or "").strip()
        if not model_file:
            raise HTTPException(status_code=503, detail="sd15_model_file_not_configured")
        if not os.path.exists(model_file):
            raise HTTPException(status_code=503, detail=f"sd15_model_file_missing: {model_file}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        # SD1.5 single-file checkpoints are more prone to NaN/black outputs in fp16 on some setups.
        # Prefer fp32 for stability.
        torch_dtype = torch.float32

        try:
            pipe = StableDiffusionPipeline.from_single_file(
                model_file,
                torch_dtype=torch_dtype,
                local_files_only=True,
            )
        except TypeError:
            pipe = StableDiffusionPipeline.from_single_file(
                model_file,
                torch_dtype=torch_dtype,
            )

        if DISABLE_SAFETY_CHECKER:
            try:
                pipe.safety_checker = None
                pipe.requires_safety_checker = False
            except Exception:
                pass

        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass
        if ENABLE_XFORMERS:
            try:
                pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass

        if device == "cuda":
            pipe = pipe.to("cuda")
        _sd15_pipeline = pipe
        return pipe


def _get_sd15_img2img_pipeline() -> StableDiffusionImg2ImgPipeline:
    global _sd15_img2img_pipeline
    with _sdxl_pipeline_lock:
        if _sd15_img2img_pipeline is not None:
            return _sd15_img2img_pipeline

        base = _get_sd15_pipeline()
        img2img = StableDiffusionImg2ImgPipeline(**base.components)

        if DISABLE_SAFETY_CHECKER:
            try:
                img2img.safety_checker = None
                img2img.requires_safety_checker = False
            except Exception:
                pass

        try:
            img2img.enable_attention_slicing()
        except Exception:
            pass
        try:
            img2img.enable_vae_slicing()
        except Exception:
            pass
        if ENABLE_XFORMERS:
            try:
                img2img.enable_xformers_memory_efficient_attention()
            except Exception:
                pass

        if torch.cuda.is_available():
            img2img = img2img.to("cuda")

        _sd15_img2img_pipeline = img2img
        return img2img


def _encode_image_png_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _truncate_prompt_77(pipe: Any, prompt: Any) -> (str, Dict[str, Any]):
    p = str(prompt or "")
    used_tokens = 77
    try:
        tok = getattr(pipe, "tokenizer", None)
        tok2 = getattr(pipe, "tokenizer_2", None)
        if tok is None and tok2 is None:
            return p, {"prompt_truncated": False, "original_tokens": None, "used_tokens": used_tokens}

        def _count_tokens(t):
            if t is None:
                return None
            ids_full = t(p, truncation=False, add_special_tokens=True).input_ids
            ids_trunc = t(p, truncation=True, max_length=used_tokens, add_special_tokens=True).input_ids
            full_len = len(ids_full[0]) if ids_full and len(ids_full) > 0 else 0
            trunc_len = len(ids_trunc[0]) if ids_trunc and len(ids_trunc) > 0 else 0
            return full_len, trunc_len, ids_trunc

        full1 = trunc1 = 0
        ids_trunc = None
        c1 = _count_tokens(tok)
        if c1 is not None:
            full1, trunc1, ids_trunc = c1

        full2 = trunc2 = 0
        c2 = _count_tokens(tok2)
        if c2 is not None:
            full2, trunc2, _ = c2

        original_tokens = max(int(full1 or 0), int(full2 or 0))
        prompt_truncated = bool(original_tokens > int(used_tokens))

        if prompt_truncated and ids_trunc is not None:
            try:
                t = tok or tok2
                p = t.decode(ids_trunc[0], skip_special_tokens=True)
            except Exception:
                pass

        return p, {"prompt_truncated": prompt_truncated, "original_tokens": original_tokens, "used_tokens": used_tokens}
    except Exception:
        return p, {"prompt_truncated": False, "original_tokens": None, "used_tokens": used_tokens}


def _latents_to_preview_png_base64(pipe: StableDiffusionXLPipeline, latents: Any) -> Optional[str]:
    if latents is None or not torch.is_tensor(latents):
        return None
    try:
        with torch.no_grad():
            lat_f32 = latents.detach().float()

            # Diagnostics: latents stats.
            try:
                if lat_f32.numel() > 0:
                    print(
                        f"[DEBUG] SDXL preview latents stats: min={float(lat_f32.min()):.4f} max={float(lat_f32.max()):.4f} mean={float(lat_f32.mean()):.4f} std={float(lat_f32.std()):.4f} has_nan={bool(torch.isnan(lat_f32).any())} has_inf={bool(torch.isinf(lat_f32).any())}",
                        flush=True,
                    )
            except Exception:
                pass

            # Prefer pipeline's own decode path when available.
            pil = None
            try:
                decode_latents = getattr(pipe, "decode_latents", None)
                if callable(decode_latents):
                    img_np = decode_latents(lat_f32)
                    # decode_latents usually returns NHWC float in [0,1]
                    pil = pipe.image_processor.numpy_to_pil(img_np)[0]
            except Exception:
                pil = None

            if pil is None:
                scaling_factor = float(getattr(pipe.vae.config, "scaling_factor", 1.0) or 1.0)
                scaled = lat_f32 / scaling_factor
                decoded = pipe.vae.decode(scaled.to(device=pipe.vae.device), return_dict=False)[0]
                image = (decoded / 2 + 0.5).clamp(0, 1)
                image = image.detach().float().cpu()
                image = image.permute(0, 2, 3, 1).numpy()
                pil = pipe.image_processor.numpy_to_pil(image)[0]

        # Suppress meaningless black previews (these cause useless cached preview images in imagen-light/LINE).
        try:
            extrema = pil.convert("L").getextrema()
            if isinstance(extrema, tuple) and len(extrema) == 2 and int(extrema[1]) == 0:
                print("[WARN] SDXL preview suppressed (decoded preview is constant black)", flush=True)
                return None
        except Exception:
            pass

        max_size = int(SDXL_PREVIEW_MAX_SIZE or 0)
        if max_size > 0:
            pil.thumbnail((max_size, max_size), Image.LANCZOS)
        return _encode_image_png_base64(pil)
    except Exception:
        return None


def _sd15_latents_to_preview_png_base64(pipe: StableDiffusionPipeline, latents: Any) -> Optional[str]:
    if latents is None or not torch.is_tensor(latents):
        return None
    try:
        with torch.no_grad():
            lat_f32 = latents.detach().float()

            try:
                if lat_f32.numel() > 0:
                    print(
                        f"[DEBUG] SD15 preview latents stats: min={float(lat_f32.min()):.4f} max={float(lat_f32.max()):.4f} mean={float(lat_f32.mean()):.4f} std={float(lat_f32.std()):.4f} has_nan={bool(torch.isnan(lat_f32).any())} has_inf={bool(torch.isinf(lat_f32).any())}",
                        flush=True,
                    )
            except Exception:
                pass

            pil = None
            try:
                decode_latents = getattr(pipe, "decode_latents", None)
                if callable(decode_latents):
                    img_np = decode_latents(lat_f32)
                    pil = pipe.image_processor.numpy_to_pil(img_np)[0]
            except Exception:
                pil = None

            if pil is None:
                scaling_factor = float(getattr(pipe.vae.config, "scaling_factor", 1.0) or 1.0)
                scaled = lat_f32 / scaling_factor
                decoded = pipe.vae.decode(scaled.to(device=pipe.vae.device), return_dict=False)[0]
                image = (decoded / 2 + 0.5).clamp(0, 1)
                image = image.detach().float().cpu()
                image = image.permute(0, 2, 3, 1).numpy()
                pil = pipe.image_processor.numpy_to_pil(image)[0]

        try:
            extrema = pil.convert("L").getextrema()
            if isinstance(extrema, tuple) and len(extrema) == 2 and int(extrema[1]) == 0:
                print("[WARN] SD15 preview suppressed (decoded preview is constant black)", flush=True)
                return None
        except Exception:
            pass

        max_size = int(SDXL_PREVIEW_MAX_SIZE or 0)
        if max_size > 0:
            pil.thumbnail((max_size, max_size), Image.LANCZOS)
        return _encode_image_png_base64(pil)
    except Exception:
        return None


class _ImagenJob:
    def __init__(self, *, job_id: str, spec: Dict[str, Any]):
        self.job_id = job_id
        self.spec = spec
        self.created_at_ms = _now_ms()
        self.started_at_ms: Optional[int] = None
        self.finished_at_ms: Optional[int] = None
        self.status = "queued"  # queued|running|succeeded|failed
        self.error: Optional[str] = None
        self.progress = {"step": 0, "steps": int(spec.get("steps") or 0)}
        self.result: Optional[Dict[str, Any]] = None
        self.preview: Optional[Dict[str, Any]] = None
        self._events: List[Dict[str, Any]] = []
        self._events_cond = threading.Condition()
        self._event_seq = 0

    def add_event(self, event: Dict[str, Any]) -> None:
        with self._events_cond:
            self._event_seq += 1
            payload = {
                "seq": self._event_seq,
                "ts": _now_ms(),
                **event,
            }
            self._events.append(payload)
            self._events_cond.notify_all()

    def wait_for_events(self, *, after_seq: int, timeout_s: float) -> List[Dict[str, Any]]:
        deadline = time.time() + timeout_s
        with self._events_cond:
            while True:
                out = [e for e in self._events if int(e.get("seq") or 0) > after_seq]
                if out:
                    return out
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._events_cond.wait(timeout=remaining)


_imagen_jobs: Dict[str, _ImagenJob] = {}
_imagen_jobs_lock = threading.Lock()


def _create_imagen_job(spec: Dict[str, Any]) -> _ImagenJob:
    job_id = str(uuid.uuid4())
    print(f"[DEBUG] Creating new job with ID: {job_id}", flush=True)
    job = _ImagenJob(job_id=job_id, spec=spec)
    with _imagen_jobs_lock:
        _imagen_jobs[job_id] = job
        print(f"[DEBUG] Added job to dictionary. Current jobs: {len(_imagen_jobs)}. All job IDs: {list(_imagen_jobs.keys())}", flush=True)
    job.add_event({"type": "queued", "jobId": job_id})
    return job


def _get_job(job_id: str) -> _ImagenJob:
    print(f"[DEBUG] Looking up job ID: {job_id}", flush=True)
    with _imagen_jobs_lock:
        job = _imagen_jobs.get(job_id)
        print(f"[DEBUG] Current jobs in dictionary: {len(_imagen_jobs)}. All job IDs: {list(_imagen_jobs.keys())}", flush=True)
    if job is None:
        print(f"[ERROR] Job not found: {job_id}", flush=True)
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


def _run_imagen_job(job: _ImagenJob) -> None:
    print(f"[DEBUG] Starting job execution for {job.job_id}", flush=True)
    try:
        job.started_at_ms = _now_ms()
        job.status = "running"
        print(f"[DEBUG] Job status set to running for {job.job_id}", flush=True)
        job.add_event({"type": "started", "jobId": job.job_id})
        
        using = "sd15_single" if (SD15_MODEL_FILE and os.path.exists(SD15_MODEL_FILE)) else "sdxl"
        pipe = _get_sd15_pipeline() if using == "sd15_single" else _get_sdxl_pipeline()
        
        seed = job.spec.get("seed")
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big")
        generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(int(seed))
        
        steps = int(job.spec.get("steps") or 0)
        job.progress = {"step": 0, "steps": steps}
        
        autocast_ctx = torch.autocast(device_type="cuda") if torch.cuda.is_available() else contextlib.nullcontext()
        trunc_info: Dict[str, Any] = {"prompt_truncated": False, "original_tokens": None, "used_tokens": 77}
        with autocast_ctx:
            if using == "sdxl":
                prompt_str, trunc_info = _truncate_prompt_77(pipe, job.spec.get("prompt"))
                def _cb(_pipe, step_idx: int, _timestep, _kwargs):
                    job.progress = {"step": int(step_idx) + 1, "steps": steps}
                    every = int(MCP_CUDA_PREVIEW_EVERY_N_STEPS or 0)
                    if every > 0 and (int(job.progress.get("step") or 0) % every == 0):
                        print(f"[DEBUG] Generating SDXL preview for step {step_idx}", flush=True)
                        try:
                            latents = (_kwargs or {}).get("latents")
                            if latents is None:
                                print("[WARNING] No latents available for preview generation", flush=True)
                                return {}
                                
                            b64 = _latents_to_preview_png_base64(pipe, latents)
                            if isinstance(b64, str) and b64:
                                payload = {
                                    "jobId": job.job_id,
                                    "status": job.status,
                                    "progress": job.progress,
                                    "mimeType": "image/png",
                                    "imageBase64": b64,
                                }
                                job.preview = payload
                                job.add_event({"type": "preview", "preview": payload})
                                print(f"[DEBUG] SDXL preview generated for step {step_idx}", flush=True)
                        except Exception as e:
                            print(f"[ERROR] Failed to generate SDXL preview: {str(e)}", flush=True)
                            print(traceback.format_exc(), flush=True)
                    
                    job.add_event({"type": "progress", "progress": job.progress})
                    return {}

                out = pipe(
                    prompt=prompt_str,
                    negative_prompt=job.spec.get("negative_prompt"),
                    width=int(job.spec.get("width") or 1024),
                    height=int(job.spec.get("height") or 1024),
                    num_inference_steps=steps,
                    guidance_scale=float(job.spec.get("guidance_scale") or 7.0),
                    generator=generator,
                    callback_on_step_end=_cb,
                    callback_on_step_end_tensor_inputs=["latents"],
                )
            else:
                # SD1.5 pipeline path
                print(f"[DEBUG] Starting SD1.5 generation with params: {job.spec}", flush=True)
                autocast_ctx = contextlib.nullcontext()
                
                def _cb_sd15(pipe, step, timestep, kwargs):
                    print(f"[DEBUG] SD1.5 callback - step: {step}", flush=True)
                    job.progress = {"step": min(int(step) + 1, steps), "steps": steps}
                    every = int(MCP_CUDA_PREVIEW_EVERY_N_STEPS or 0)
                    if every > 0 and (int(job.progress.get("step") or 0) % every == 0):
                        print(f"[DEBUG] Generating preview for step {step}", flush=True)
                        b64 = _sd15_latents_to_preview_png_base64(pipe, kwargs.get("latents"))
                        if isinstance(b64, str) and b64:
                            payload = {
                                "jobId": job.job_id,
                                "status": job.status,
                                "progress": job.progress,
                                "mimeType": "image/png",
                                "imageBase64": b64,
                            }
                            job.preview = payload
                            job.add_event({"type": "preview", "preview": payload})
                    job.add_event({"type": "progress", "progress": job.progress})
                    return {}
                
                print(f"[DEBUG] Before SD1.5 pipe() call", flush=True)
                with torch.inference_mode(), autocast_ctx:
                    print(f"[DEBUG] Inside torch inference context", flush=True)
                    prompt_str, trunc_info = _truncate_prompt_77(pipe, job.spec.get("prompt"))
                    neg_prompt_str, neg_trunc_info = _truncate_prompt_77(pipe, job.spec.get("negative_prompt"))
                    ref_b64 = job.spec.get("reference_image_base64")
                    if isinstance(ref_b64, str) and ref_b64.strip():
                        img2img = _get_sd15_img2img_pipeline()
                        ref_raw = base64.b64decode(ref_b64)
                        init_image = Image.open(io.BytesIO(ref_raw)).convert("RGB")
                        w = int(job.spec.get("width") or 1024)
                        h = int(job.spec.get("height") or 1024)
                        if init_image.size != (w, h):
                            init_image = init_image.resize((w, h), Image.LANCZOS)
                        out = img2img(
                            prompt=prompt_str,
                            negative_prompt=neg_prompt_str,
                            image=init_image,
                            width=w,
                            height=h,
                            num_inference_steps=steps,
                            guidance_scale=float(job.spec.get("guidance_scale") or 7.0),
                            generator=generator,
                            callback_on_step_end=_cb_sd15,
                            callback_on_step_end_tensor_inputs=["latents"],
                            output_type="np",
                        )
                    else:
                        out = pipe(
                            prompt=prompt_str,
                            negative_prompt=neg_prompt_str,
                            width=int(job.spec.get("width") or 1024),
                            height=int(job.spec.get("height") or 1024),
                            num_inference_steps=steps,
                            guidance_scale=float(job.spec.get("guidance_scale") or 7.0),
                            generator=generator,
                            callback_on_step_end=_cb_sd15,
                            callback_on_step_end_tensor_inputs=["latents"],
                            output_type="np",
                        )
                print(f"[DEBUG] After SD1.5 pipe() call", flush=True)
                print(f"[DEBUG] SD1.5 output: {out}", flush=True)

            img = out.images[0]
            if isinstance(img, np.ndarray):
                arr = img
                try:
                    if arr.size and bool(np.isnan(arr).any()):
                        nan_count = int(np.isnan(arr).sum())
                        print(f"[ERROR] SD output contains NaNs: nan_count={nan_count}", flush=True)
                        raise RuntimeError("nan_output")
                    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
                    # Diffusers typically returns float images in [0, 1]. Some pipelines may output [0, 255].
                    maxv = float(np.max(arr)) if arr.size else 0.0
                    if maxv > 1.5:
                        arr_u8 = np.clip(arr, 0.0, 255.0).round().astype(np.uint8)
                    else:
                        arr_u8 = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype(np.uint8)
                    if arr_u8.ndim == 3 and arr_u8.shape[-1] in (3, 4):
                        img = Image.fromarray(arr_u8)
                except Exception:
                    pass
            nsfw_content_detected = None
            try:
                nsfw_content_detected = getattr(out, "nsfw_content_detected", None)
            except Exception:
                nsfw_content_detected = None
            extrema = None
            pixel_min = None
            pixel_max = None
            pixel_mean = None
            try:
                extrema = img.getextrema()
                arr_u8 = np.asarray(img)
                if arr_u8.size:
                    pixel_min = int(arr_u8.min())
                    pixel_max = int(arr_u8.max())
                    pixel_mean = float(arr_u8.mean())
            except Exception:
                pass

            # Guard: avoid reporting succeeded when the output is clearly unusable.
            # Common cause: safety checker replaced output with black.
            if pixel_max == 0:
                raise RuntimeError("suspicious_black_image")
            img_b64 = _encode_image_png_base64(img)

            job.result = {
                "model": using,
                "mimeType": "image/png",
                "imageBase64": img_b64,
                "seed": int(seed),
                "width": int(img.width),
                "height": int(img.height),
                "steps": steps,
                **(trunc_info or {}),
                "pixel_min": pixel_min,
                "pixel_max": pixel_max,
                "pixel_mean": pixel_mean,
                "extrema": extrema,
                "nsfw_content_detected": nsfw_content_detected,
            }
            print(f"[DEBUG] Job {job.job_id} completed successfully", flush=True)
            job.status = "succeeded"
            job.finished_at_ms = _now_ms()
            job.add_event({"type": "done", "jobId": job.job_id})
    except HTTPException as exc:
        print(f"[ERROR] Job {job.job_id} failed with HTTPException: {exc}", flush=True)
        job.status = "failed"
        job.error = str(exc.detail)
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
    except RuntimeError as exc:
        msg = str(exc)
        if "out of memory" in msg.lower():
            msg = "cuda_oom"
        print(f"[ERROR] Job {job.job_id} failed with RuntimeError: {msg}", flush=True)
        job.status = "failed"
        job.error = msg
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Job {job.job_id} failed with unexpected error: {exc}", flush=True)
        job.status = "failed"
        job.error = f"unexpected_error: {exc}"
        job.finished_at_ms = _now_ms()
        job.add_event({"type": "error", "message": job.error})
    finally:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        print(f"[DEBUG] Final job state for {job.job_id}: status={job.status}, error={job.error}", flush=True)
        with _imagen_jobs_lock:
            print(f"[DEBUG] Current jobs in dictionary: {len(_imagen_jobs)}. All job IDs: {list(_imagen_jobs.keys())}", flush=True)
            # Ensure job remains in dictionary permanently
            if job.job_id not in _imagen_jobs:
                print(f"[PERSIST] Re-adding completed job {job.job_id} to dictionary", flush=True)
                _imagen_jobs[job.job_id] = job
            else:
                print(f"[PERSIST] Job {job.job_id} remains in dictionary", flush=True)
        
        # Cleanup old jobs if needed
        if len(_imagen_jobs) > MAX_JOBS_TO_RETAIN * 1.5:  # Clean when 50% over limit
            _cleanup_old_jobs()


def _get_clip_model(model_name: Optional[str]) -> SentenceTransformer:
    global _clip_model
    selected = (model_name or CLIP_MODEL).strip() or CLIP_MODEL
    if _clip_model is None or getattr(_clip_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = SentenceTransformer(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _clip_model = m
    return _clip_model


def _get_text_model(model_name: Optional[str]) -> SentenceTransformer:
    global _text_model
    selected = (model_name or TEXT_EMBED_MODEL).strip() or TEXT_EMBED_MODEL
    if _text_model is None or getattr(_text_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = SentenceTransformer(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _text_model = m
    return _text_model


def _get_rerank_model(model_name: Optional[str]) -> CrossEncoder:
    global _rerank_model
    selected = (model_name or RERANK_MODEL).strip() or RERANK_MODEL
    if _rerank_model is None or getattr(_rerank_model, "_chaba_model_name", None) != selected:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        m = CrossEncoder(selected, device=device)
        setattr(m, "_chaba_model_name", selected)
        _rerank_model = m
    return _rerank_model


def _decode_b64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_base64: {exc}")


def _clip_image_embed(images_base64: List[str], *, normalize: bool, model_name: Optional[str]) -> Dict[str, Any]:
    items = [str(x or "").strip() for x in (images_base64 or [])]
    if not items:
        raise HTTPException(status_code=400, detail="imagesBase64_required")
    if len(items) > MAX_IMAGE_ITEMS:
        raise HTTPException(status_code=400, detail=f"too_many_images: max={MAX_IMAGE_ITEMS}")

    model = _get_clip_model(model_name)

    images: List[Image.Image] = []
    for b64 in items:
        raw = _decode_b64(b64)
        try:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid_image: {exc}")
        if img.width < 8 or img.height < 8:
            img = img.resize((224, 224))
        images.append(img)

    vecs = model.encode(images, normalize_embeddings=bool(normalize))
    arr = np.asarray(vecs)
    return {
        "model": getattr(model, "_chaba_model_name", CLIP_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "count": int(arr.shape[0]) if arr.ndim >= 1 else 0,
        "dim": int(arr.shape[1]) if arr.ndim == 2 else 0,
        "vectors": arr.astype(float).tolist(),
    }


def _text_embed(texts: List[str], *, normalize: bool, model_name: Optional[str]) -> Dict[str, Any]:
    items = [str(t or "") for t in (texts or [])]
    if not items:
        raise HTTPException(status_code=400, detail="texts_required")
    if len(items) > MAX_TEXT_ITEMS:
        raise HTTPException(status_code=400, detail=f"too_many_texts: max={MAX_TEXT_ITEMS}")

    model = _get_text_model(model_name)
    vecs = model.encode(items, normalize_embeddings=bool(normalize))
    arr = np.asarray(vecs)
    return {
        "model": getattr(model, "_chaba_model_name", TEXT_EMBED_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "count": int(arr.shape[0]) if arr.ndim >= 1 else 0,
        "dim": int(arr.shape[1]) if arr.ndim == 2 else 0,
        "vectors": arr.astype(float).tolist(),
    }


def _rerank(query: str, documents: List[str], *, model_name: Optional[str]) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query_required")
    docs = [str(d or "") for d in (documents or [])]
    if not docs:
        raise HTTPException(status_code=400, detail="documents_required")
    if len(docs) > MAX_RERANK_DOCS:
        raise HTTPException(status_code=400, detail=f"too_many_documents: max={MAX_RERANK_DOCS}")

    model = _get_rerank_model(model_name)
    pairs = [(q, d) for d in docs]
    scores_raw = model.predict(pairs)
    scores = [float(x) for x in np.asarray(scores_raw).tolist()]
    ranked = sorted(
        [{"index": i, "score": s, "text": docs[i]} for i, s in enumerate(scores)],
        key=lambda x: x["score"],
        reverse=True,
    )
    return {
        "model": getattr(model, "_chaba_model_name", RERANK_MODEL),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "query": q,
        "results": ranked,
    }


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "cuda_info",
            "description": "Return basic GPU/CUDA availability info via nvidia-smi.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "nvidia_smi_query",
            "description": "Run a fixed nvidia-smi query (no arbitrary shell).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "nvidia-smi --query-gpu fields (e.g. name,driver_version,memory.total,memory.used)",
                    }
                },
                "required": ["fields"],
            },
        },
        {
            "name": "torch_info",
            "description": "Return torch/CUDA availability details for debugging.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "clip_image_embed",
            "description": "Compute CLIP image embeddings on GPU (batch). Input is base64-encoded image bytes.",
            "inputSchema": ClipImageEmbedArgs.model_json_schema(),
        },
        {
            "name": "text_embed",
            "description": "Compute text embeddings on GPU (batch) using sentence-transformers.",
            "inputSchema": TextEmbedArgs.model_json_schema(),
        },
        {
            "name": "rerank",
            "description": "Rerank candidate documents for a query using a cross-encoder (GPU if available).",
            "inputSchema": RerankArgs.model_json_schema(),
        },
        {
            "name": "imagen_models",
            "description": "Return available Imagen/SDXL model configuration.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "imagen_job_create",
            "description": "Create an image generation job. Model selection depends on server configuration: if MCP_CUDA_SD15_MODEL_FILE exists, SD1.5 is used; otherwise SDXL is used. If referenceImageBase64 is provided, SD1.5 runs img2img (uses strength in (0,1]); otherwise it runs txt2img. referenceImageDimensions is optional (used only for validation when provided). Use /imagen/jobs/{jobId}/events (SSE) for progress events.",
            "inputSchema": ImagenJobCreateArgs.model_json_schema(),
        },
        {
            "name": "imagen_job_status",
            "description": "Get status/progress for an image generation job (SDXL or SD1.5 depending on configuration).",
            "inputSchema": ImagenJobStatusArgs.model_json_schema(),
        },
        {
            "name": "imagen_job_result",
            "description": "Fetch the final result for a completed image generation job (base64 PNG).",
            "inputSchema": ImagenJobResultArgs.model_json_schema(),
        },
    ]


def _cuda_info() -> Dict[str, Any]:
    smi = _run(["nvidia-smi", "-L"], timeout_seconds=10)
    query = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout_seconds=10,
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "smi_list": smi,
        "smi_query": query,
        "notes": {
            "requires": "Docker GPU support + NVIDIA container runtime on host",
        },
    }


def _nvidia_smi_query(fields: List[str]) -> Dict[str, Any]:
    cleaned = [str(f).strip() for f in (fields or []) if str(f).strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="fields_required")

    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(cleaned)}",
        "--format=csv,noheader,nounits",
    ]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": cleaned,
        "result": _run(cmd, timeout_seconds=10),
    }


def _jsonrpc_error(id_value: Any, code: int, message: str, data: Optional[Any] = None) -> JsonRpcResponse:
    return JsonRpcResponse(id=id_value, error=JsonRpcError(code=code, message=message, data=data))


app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


@app.get("/health")
async def health() -> Dict[str, Any]:
    smi = _run(["nvidia-smi", "-L"], timeout_seconds=5)
    status = "ok" if smi.get("ok") else "degraded"
    return {
        "status": status,
        "service": APP_NAME,
        "version": APP_VERSION,
        "instanceId": MCP_CUDA_INSTANCE_ID,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "nvidiaSmi": bool(smi.get("ok")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/.well-known/mcp.json")
async def well_known_manifest() -> Dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "description": "CUDA/GPU utility MCP provider (centralized GPU access).",
        "capabilities": {
            "tools": tool_definitions(),
        },
    }


@app.get("/tools")
async def tools() -> Dict[str, Any]:
    return {"tools": tool_definitions()}


@app.post("/invoke")
async def invoke(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tool = (payload or {}).get("tool")
    args = (payload or {}).get("arguments") or {}

    if tool == "cuda_info":
        return {"tool": tool, "result": _cuda_info()}

    if tool == "nvidia_smi_query":
        fields = args.get("fields")
        if not isinstance(fields, list):
            raise HTTPException(status_code=400, detail="fields_must_be_array")
        return {"tool": tool, "result": _nvidia_smi_query(fields)}

    if tool == "torch_info":
        return {"tool": tool, "result": _torch_info()}

    if tool == "clip_image_embed":
        parsed = ClipImageEmbedArgs(**args)
        return {
            "tool": tool,
            "result": _clip_image_embed(
                parsed.images_base64,
                normalize=bool(parsed.normalize),
                model_name=parsed.model,
            ),
        }

    if tool == "text_embed":
        parsed = TextEmbedArgs(**args)
        return {
            "tool": tool,
            "result": _text_embed(parsed.texts, normalize=bool(parsed.normalize), model_name=parsed.model),
        }

    if tool == "rerank":
        parsed = RerankArgs(**args)
        return {
            "tool": tool,
            "result": _rerank(parsed.query, parsed.documents, model_name=parsed.model),
        }

    if tool == "imagen_models":
        return {
            "tool": tool,
            "result": {
                "default": "sd15_single" if (SD15_MODEL_FILE and os.path.exists(SD15_MODEL_FILE)) else "sdxl",
                "sdxl": {
                    "modelDir": SDXL_MODEL_DIR,
                    "localFilesOnly": True,
                    "maxPixels": SDXL_MAX_PIXELS,
                    "maxSteps": SDXL_MAX_STEPS,
                    "maxConcurrentJobs": SDXL_MAX_CONCURRENT_JOBS,
                },
                "sd15_single": {
                    "modelFile": SD15_MODEL_FILE,
                    "localFilesOnly": True,
                    "maxPixels": SDXL_MAX_PIXELS,
                    "maxSteps": SDXL_MAX_STEPS,
                    "maxConcurrentJobs": SDXL_MAX_CONCURRENT_JOBS,
                },
            },
        }

    if tool == "imagen_job_create":
        parsed = ImagenJobCreateArgs(**args)
        spec = _validate_imagen_args(parsed)
        job = _create_imagen_job(spec)
        _imagen_executor.submit(_run_imagen_job, job)
        return {
            "tool": tool,
            "result": {
                "jobId": job.job_id,
                "status": job.status,
                "eventsUrl": f"/imagen/jobs/{job.job_id}/events",
                "statusUrl": f"/imagen/jobs/{job.job_id}",
                "resultUrl": f"/imagen/jobs/{job.job_id}/result",
            },
        }

    if tool == "imagen_job_status":
        parsed = ImagenJobStatusArgs(**args)
        job = _get_job(parsed.job_id)
        return {
            "tool": tool,
            "result": {
                "jobId": job.job_id,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "createdAtMs": job.created_at_ms,
                "startedAtMs": job.started_at_ms,
                "finishedAtMs": job.finished_at_ms,
            },
        }

    if tool == "imagen_job_result":
        parsed = ImagenJobResultArgs(**args)
        job = _get_job(parsed.job_id)
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail=f"job_not_succeeded: {job.status}")
        if not isinstance(job.result, dict):
            raise HTTPException(status_code=502, detail="missing_result")
        return {
            "tool": tool,
            "result": {"jobId": job.job_id, **job.result},
        }

    raise HTTPException(status_code=404, detail=f"unknown tool '{tool}'")


@app.post("/mcp")
async def mcp_endpoint(payload: Dict[str, Any] = Body(...)):
    request = JsonRpcRequest(**(payload or {}))

    if request.id is None:
        return None

    method = (request.method or "").strip()
    params = request.params or {}

    if method == "initialize":
        return JsonRpcResponse(
            id=request.id,
            result={
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {}},
            },
        ).model_dump(exclude_none=True)

    if method in ("tools/list", "list_tools"):
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tool_definitions()},
        ).model_dump(exclude_none=True)

    if method in ("tools/call", "call_tool"):
        tool_name = (params.get("name") or params.get("tool") or "").strip()
        arguments_raw = params.get("arguments") or {}
        if not tool_name:
            return _jsonrpc_error(request.id, -32602, "Missing tool name").model_dump(exclude_none=True)

        if tool_name == "cuda_info":
            out = _cuda_info()
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "text_embed":
            try:
                parsed = TextEmbedArgs(**(arguments_raw or {}))
                out = _text_embed(parsed.texts, normalize=bool(parsed.normalize), model_name=parsed.model)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "rerank":
            try:
                parsed = RerankArgs(**(arguments_raw or {}))
                out = _rerank(parsed.query, parsed.documents, model_name=parsed.model)
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "nvidia_smi_query":
            fields = arguments_raw.get("fields")
            if not isinstance(fields, list):
                return _jsonrpc_error(request.id, -32602, "fields must be an array").model_dump(
                    exclude_none=True
                )
            out = _nvidia_smi_query(fields)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "torch_info":
            out = _torch_info()
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "clip_image_embed":
            try:
                parsed = ClipImageEmbedArgs(**(arguments_raw or {}))
                out = _clip_image_embed(
                    parsed.images_base64,
                    normalize=bool(parsed.normalize),
                    model_name=parsed.model,
                )
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "imagen_models":
            out = {
                "default": "sdxl",
                "sdxl": {
                    "modelDir": SDXL_MODEL_DIR,
                    "localFilesOnly": True,
                    "maxPixels": SDXL_MAX_PIXELS,
                    "maxSteps": SDXL_MAX_STEPS,
                    "maxConcurrentJobs": SDXL_MAX_CONCURRENT_JOBS,
                },
            }
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "imagen_job_create":
            try:
                parsed = ImagenJobCreateArgs(**(arguments_raw or {}))
                spec = _validate_imagen_args(parsed)
                job = _create_imagen_job(spec)
                _imagen_executor.submit(_run_imagen_job, job)
                out = {
                    "jobId": job.job_id,
                    "status": job.status,
                    "eventsUrl": f"/imagen/jobs/{job.job_id}/events",
                    "statusUrl": f"/imagen/jobs/{job.job_id}",
                    "resultUrl": f"/imagen/jobs/{job.job_id}/result",
                }
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "imagen_job_status":
            try:
                parsed = ImagenJobStatusArgs(**(arguments_raw or {}))
                job = _get_job(parsed.job_id)
                out = {
                    "jobId": job.job_id,
                    "status": job.status,
                    "progress": job.progress,
                    "error": job.error,
                    "createdAtMs": job.created_at_ms,
                    "startedAtMs": job.started_at_ms,
                    "finishedAtMs": job.finished_at_ms,
                }
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        if tool_name == "imagen_job_result":
            try:
                parsed = ImagenJobResultArgs(**(arguments_raw or {}))
                job = _get_job(parsed.job_id)
                if job.status != "succeeded":
                    raise HTTPException(status_code=409, detail=f"job_not_succeeded: {job.status}")
                if not isinstance(job.result, dict):
                    raise HTTPException(status_code=502, detail="missing_result")
                out = {"jobId": job.job_id, **job.result}
            except HTTPException as exc:
                return _jsonrpc_error(request.id, -32001, str(exc.detail)).model_dump(exclude_none=True)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": str(out)}]},
            ).model_dump(exclude_none=True)

        return _jsonrpc_error(request.id, -32601, f"Unknown tool '{tool_name}'").model_dump(exclude_none=True)

    return _jsonrpc_error(request.id, -32601, f"Unknown method '{method}'").model_dump(exclude_none=True)


@app.post("/imagen/jobs")
async def imagen_jobs_create(payload: Dict[str, Any] = Body(...)):
    if not payload.get("approved"):
        raise HTTPException(
            status_code=400,
            detail="approval_required_use_preview_first"
        )
    
    try:
        args = ImagenJobCreateArgs(**payload)
        spec = _validate_imagen_args(args)
        job = _create_imagen_job(spec)
        _imagen_executor.submit(_run_imagen_job, job)
        return {
            "jobId": job.job_id,
            "status": job.status,
            "eventsUrl": f"/imagen/jobs/{job.job_id}/events"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/imagen/jobs/{job_id}")
async def imagen_jobs_status(job_id: str) -> Dict[str, Any]:
    job = _get_job(job_id)
    return {
        "jobId": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "createdAtMs": job.created_at_ms,
        "startedAtMs": job.started_at_ms,
        "finishedAtMs": job.finished_at_ms,
        "eventsUrl": f"/imagen/jobs/{job.job_id}/events",
        "statusUrl": f"/imagen/jobs/{job.job_id}",
        "resultUrl": f"/imagen/jobs/{job.job_id}/result",
    }


@app.get("/imagen/jobs/{job_id}/preview")
async def imagen_jobs_preview_get(job_id: str) -> Dict[str, Any]:
    job = _get_job(job_id)
    if not isinstance(job.preview, dict):
        return {
            "jobId": job.job_id,
            "available": False,
            "status": job.status,
            "progress": job.progress,
        }
    # Important: job.preview may contain stale fields like status="running".
    # Always override with the authoritative job.status/job.progress.
    out = {
        "jobId": job.job_id,
        "available": True,
        **job.preview,
        "status": job.status,
        "progress": job.progress,
    }
    return out


@app.get("/imagen/jobs/{job_id}/result")
async def imagen_jobs_result(job_id: str) -> Dict[str, Any]:
    job = _get_job(job_id)
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"job_not_succeeded: {job.status}")
    if not isinstance(job.result, dict):
        raise HTTPException(status_code=502, detail="result_missing")
    return job.result


@app.get("/imagen/jobs/{job_id}/events")
async def imagen_jobs_events(job_id: str, after: int = 0, timeout: float = 20.0):
    job = _get_job(job_id)

    async def _iter():
        last_seq = int(after or 0)
        yield f"event: hello\ndata: {json.dumps({'jobId': job.job_id, 'after': last_seq})}\n\n"
        while True:
            events = job.wait_for_events(after_seq=last_seq, timeout_s=float(timeout or 20.0))
            if not events:
                yield "event: ping\ndata: {}\n\n"
                continue
            for e in events:
                try:
                    seq = int(e.get("seq") or last_seq)
                except Exception:
                    seq = last_seq
                if seq > last_seq:
                    last_seq = seq
                ev_type = str(e.get("type") or "message")
                yield f"event: {ev_type}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                if ev_type in ("done", "error"):
                    return

    return StreamingResponse(_iter(), media_type="text/event-stream")


@app.post("/imagen/preprocess")
async def preprocess_ref_image(
    image: str = Body(..., embed=True),
    width: int = Body(512),
    height: int = Body(512),
    format: str = Body("png")
):
    """Auto-resizes reference images to target dimensions"""
    try:
        img = Image.open(io.BytesIO(base64.b64decode(image)))
        if (img.width, img.height) != (width, height):
            img = img.resize((width, height), Image.LANCZOS)
        buffered = io.BytesIO()
        img.save(buffered, format=format)
        return {
            "processed": base64.b64encode(buffered.getvalue()).decode("utf-8"),
            "dimensions": [width, height]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"preprocessing_failed: {str(e)}")


@app.post("/imagen/jobs/preview")
async def imagen_jobs_preview(payload: Dict[str, Any] = Body(...)):
    """Preview job parameters before execution"""
    try:
        defaults = _get_imagen_light_defaults()
        
        # Merge user input with defaults
        params = {**defaults, **payload}
        
        # Validate merged parameters
        args = ImagenJobCreateArgs(**params)
        
        return {
            "preview": True,
            "parameters": params,
            "missing": [k for k in defaults if k not in payload],
            "defaults": defaults
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _cleanup_old_jobs() -> None:
    """Remove old jobs based on retention settings"""
    current_time = _now_ms() / 1000
    threshold = current_time - (JOB_RETENTION_DAYS * 86400)
    
    with _imagen_jobs_lock:
        # Remove jobs older than retention period
        to_remove = [
            job_id for job_id, job in _imagen_jobs.items()
            if job.finished_at_ms and (job.finished_at_ms / 1000) < threshold
        ]
        for job_id in to_remove:
            del _imagen_jobs[job_id]
        
        # If still over limit, remove oldest completed jobs
        if len(_imagen_jobs) > MAX_JOBS_TO_RETAIN:
            completed_jobs = [
                (job_id, job) for job_id, job in _imagen_jobs.items()
                if job.finished_at_ms
            ]
            completed_jobs.sort(key=lambda x: x[1].finished_at_ms)
            excess = len(_imagen_jobs) - MAX_JOBS_TO_RETAIN
            for job_id, _ in completed_jobs[:excess]:
                del _imagen_jobs[job_id]
        
        print(f"[CLEANUP] Removed {len(to_remove)} old jobs, current count: {len(_imagen_jobs)}", flush=True)
