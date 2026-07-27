import json
import os
import time
import io
import base64
import uuid
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor
import threading
import traceback
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo
from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline, AutoencoderKL, EulerDiscreteScheduler

app = FastAPI(title="Imagen Inference")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_ID = os.environ.get("MODEL_ID", "runwayml/stable-diffusion-v1-5")
VAE_ID = os.environ.get("VAE_ID", "")
pipe = None
i2i = None

HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", "/app/data"))
HISTORY_FILE = HISTORY_DIR / "history.json"
MAX_HISTORY = 12

JOBS = {}
JOBS_LOCK = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1)


def _load_history_file():
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history_file(history):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[:MAX_HISTORY], f)


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = Field(1024, ge=512, le=1024, multiple_of=64)
    height: int = Field(1024, ge=512, le=1024, multiple_of=64)
    steps: int = Field(25, ge=1, le=50)
    seed: int = Field(-1, ge=-1)
    image: str = ""
    strength: float = Field(0.5, ge=0.0, le=1.0)
    guidance_scale: float = Field(8.5, ge=0.0, le=20.0)
    guidance_rescale: float = Field(0.7, ge=0.0, le=1.0)


class UpscaleRequest(BaseModel):
    image: str
    scale: int = Field(2, ge=1, le=10)
    fmt: str = "png"


class HistoryPayload(BaseModel):
    history: List[dict]


@app.on_event("startup")
def load_model():
    global pipe, i2i
    extra_kwargs = {}
    if VAE_ID:
        vae = AutoencoderKL.from_pretrained(VAE_ID, torch_dtype=torch.float32)
        extra_kwargs["vae"] = vae
    pipe = StableDiffusionXLPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float32,
        use_safetensors=True,
        **extra_kwargs,
    )
    # Apply SDXL-Lightning 4-step LoRA for distilled fast inference.
    pipe.load_lora_weights(
        "ByteDance/SDXL-Lightning",
        weight_name="sdxl_lightning_4step_lora.safetensors",
    )
    pipe.fuse_lora()
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    pipe.safety_checker = None
    pipe.feature_extractor = None
    pipe.enable_sequential_cpu_offload()
    pipe.enable_vae_slicing()
    i2i = StableDiffusionXLImg2ImgPipeline(**pipe.components)
    i2i.safety_checker = None
    i2i.feature_extractor = None


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID}


@app.get("/history")
def get_history():
    return {"history": _load_history_file()}


@app.post("/history")
def post_history(payload: HistoryPayload):
    try:
        _save_history_file(payload.history)
        return {"ok": True, "count": len(payload.history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _pil_to_base64(image):
    buf = io.BytesIO()
    image.thumbnail((512, 512))
    image.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _decode_latents(latents):
    try:
        # align latents with the VAE's current parameter device
        device = next(pipe.vae.parameters()).device
        if device.type == "meta":
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        latents = latents.to(device)
        with torch.inference_mode():
            decoded = pipe.vae.decode(latents).sample
        decoded = (decoded / 2 + 0.5).clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        decoded = (decoded * 255).astype("uint8")
        return Image.fromarray(decoded)
    except Exception:
        traceback.print_exc()
        return None


def _run_generate(job_id, req: GenerateRequest):
    start = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {"done": False, "progress": None, "result": None, "error": None}

    try:
        seed = req.seed if req.seed >= 0 else int(time.time()) + uuid.uuid4().int % 100000
        generator = torch.Generator(device="cuda").manual_seed(seed)

        def callback_on_step_end(pipeline, step, timestep, callback_kwargs):
            if step % 5 == 0:
                latents = callback_kwargs.get("latents")
                if latents is not None:
                    pil = _decode_latents(latents)
                    if pil:
                        with JOBS_LOCK:
                            JOBS[job_id]["progress"] = {"step": step, "image": _pil_to_base64(pil)}
            return callback_kwargs

        kwargs = {
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "num_inference_steps": req.steps,
            "guidance_scale": req.guidance_scale,
            "guidance_rescale": req.guidance_rescale,
            "generator": generator,
            "callback_on_step_end": callback_on_step_end,
            "callback_on_step_end_tensor_inputs": ["latents"],
        }

        with torch.inference_mode():
            if req.image:
                b64 = req.image.split(",")[-1]
                init_bytes = base64.b64decode(b64)
                init_image = Image.open(io.BytesIO(init_bytes)).convert("RGB")
                init_image = ImageOps.fit(init_image, (req.width, req.height), method=Image.Resampling.LANCZOS)
                image = i2i(
                    image=init_image,
                    strength=req.strength,
                    **kwargs,
                ).images[0]
            else:
                image = pipe(
                    width=req.width,
                    height=req.height,
                    **kwargs,
                ).images[0]

        pnginfo = PngInfo()
        pnginfo.add_text("prompt", req.prompt or "")
        pnginfo.add_text("negative_prompt", req.negative_prompt or "")
        pnginfo.add_text("seed", str(seed))
        pnginfo.add_text("width", str(req.width))
        pnginfo.add_text("height", str(req.height))
        pnginfo.add_text("steps", str(req.steps))
        pnginfo.add_text("guidance_scale", str(req.guidance_scale))
        pnginfo.add_text("strength", str(req.strength))

        buf = io.BytesIO()
        image.save(buf, format="PNG", pnginfo=pnginfo)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        result = {
            "image_base64": image_b64,
            "seed": seed,
            "width": req.width,
            "height": req.height,
            "inference_time": round(time.time() - start, 2),
        }
        with JOBS_LOCK:
            JOBS[job_id] = {"done": True, "progress": None, "result": result, "error": None}
    except Exception as e:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id] = {"done": True, "progress": None, "result": None, "error": str(e)}


@app.post("/generate")
def start_generate(req: GenerateRequest):
    job_id = uuid.uuid4().hex
    if req.image and req.steps * req.strength < 1:
        raise HTTPException(
            status_code=422,
            detail=f"steps * strength must be >= 1 for img2img (got {req.steps * req.strength})",
        )
    executor.submit(_run_generate, job_id, req)
    return {"job_id": job_id}


@app.get("/progress/{job_id}")
def get_progress(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/upscale")
def upscale(req: UpscaleRequest):
    try:
        b64 = req.image.split(",")[-1]
        img_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = img.size
        new_w = w * req.scale
        new_h = h * req.scale
        if new_w > 16384 or new_h > 16384:
            raise HTTPException(status_code=400, detail="scaled dimensions exceed 16384")
        upscaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        out_format = req.fmt.upper() if req.fmt.upper() in ("PNG", "JPEG", "WEBP") else "PNG"
        buf = io.BytesIO()
        if out_format == "PNG":
            upscaled.save(buf, format="PNG")
        else:
            upscaled.save(buf, format=out_format, quality=90)
        out_b64 = base64.b64encode(buf.getvalue()).decode()
        return {
            "image_base64": out_b64,
            "width": new_w,
            "height": new_h,
            "scale": req.scale,
            "format": out_format,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
