import json
import os
import time
import uuid
import traceback
import threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import base64
import gc
import io
from PIL import Image
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import tqdm
import tqdm.auto

_CURRENT_JOB_ID = None


class _ProgressTqdm(tqdm.tqdm):
    def update(self, n=1):
        ret = super().update(n)
        if _CURRENT_JOB_ID and self.total:
            _set_progress(self.n, self.total)
        return ret


tqdm.tqdm = _ProgressTqdm
tqdm.auto.tqdm = _ProgressTqdm

from diffusers import LTXImageToVideoPipeline, LTXPipeline, LTXVideoTransformer3DModel
from diffusers.utils import export_to_video

app = FastAPI(title="CogVideo Inference")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", "/app/data/history"))
ITEMS_DIR = HISTORY_DIR / "items"
VIDEOS_DIR = HISTORY_DIR / "videos"
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))
MODEL_ID = os.environ.get("MODEL_ID", "THUDM/CogVideoX-2b")

for d in (HISTORY_DIR, ITEMS_DIR, VIDEOS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app.mount("/history/videos", StaticFiles(directory=VIDEOS_DIR, check_dir=False), name="history-videos")

JOBS = {}
JOBS_LOCK = threading.Lock()
executor = ThreadPoolExecutor(max_workers=1)
pipe = None
pipe_type = None


def _set_progress(current, total):
    if not _CURRENT_JOB_ID:
        return
    with JOBS_LOCK:
        if _CURRENT_JOB_ID in JOBS and total:
            JOBS[_CURRENT_JOB_ID]["progress"] = min(current / total, 1.0)


def _atomic_write(path: Path, data: bytes):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data):
    _atomic_write(path, json.dumps(data, ensure_ascii=False).encode("utf-8"))


def _ensure_text_to_video():
    global pipe, pipe_type
    if pipe_type == "t2v":
        return
    if pipe is not None:
        del pipe
        pipe = None
        gc.collect()
        torch.cuda.empty_cache()
    transformer = LTXVideoTransformer3DModel.from_pretrained(
        MODEL_ID,
        subfolder="transformer",
        torch_dtype=torch.float16,
    )
    pipe = LTXPipeline.from_pretrained(
        MODEL_ID,
        transformer=transformer,
        torch_dtype=torch.float16,
    )
    pipe.enable_sequential_cpu_offload()
    pipe_type = "t2v"


def _ensure_image_to_video():
    global pipe, pipe_type
    if pipe_type == "i2v":
        return
    if pipe is not None:
        del pipe
        pipe = None
        gc.collect()
        torch.cuda.empty_cache()
    pipe = LTXImageToVideoPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
    )
    pipe.enable_sequential_cpu_offload()
    pipe_type = "i2v"


def _new_item_id() -> str:
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _item_path(item_id: str) -> Path:
    return ITEMS_DIR / f"{item_id}.json"


def _video_path(item_id: str) -> Path:
    return VIDEOS_DIR / f"{item_id}.mp4"


def _prune_history():
    try:
        items = sorted(ITEMS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(items) > MAX_HISTORY:
            old = items.pop(0).stem
            for p in (_item_path(old), _video_path(old)):
                try:
                    if p.exists():
                        p.unlink()
                except OSError:
                    pass
    except Exception:
        traceback.print_exc()


def _list_history():
    history = {}
    for p in ITEMS_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            history[data["id"]] = data
        except Exception:
            continue
    with JOBS_LOCK:
        for job_id, data in JOBS.items():
            if job_id not in history:
                history[job_id] = data
    return sorted(history.values(), key=lambda x: x.get("created_at", ""), reverse=True)


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = Field(256, ge=128, le=1280, multiple_of=32)
    height: int = Field(256, ge=128, le=1280, multiple_of=32)
    num_frames: int = Field(16, ge=9, le=129)
    num_inference_steps: int = Field(25, ge=1, le=100)
    guidance_scale: float = Field(9.0, ge=1.0, le=20.0)
    seed: int = Field(-1, ge=-1)
    fps: int = Field(8, ge=1, le=60)


class GenerateImageRequest(GenerateRequest):
    image: str
    match_source: bool = False


@app.on_event("startup")
def startup():
    print(f"[startup] Loading video model {MODEL_ID}...", flush=True)
    _ensure_text_to_video()
    print("[startup] Model loaded.", flush=True)


@app.get("/health")
def health():
    return {"status": "ok" if pipe else "loading", "model": MODEL_ID, "pipe_type": pipe_type}


@app.post("/generate")
def start_generate(req: GenerateRequest):
    job_id = _new_item_id()
    with JOBS_LOCK:
        JOBS[job_id] = req.dict()
        JOBS[job_id]["id"] = job_id
        JOBS[job_id]["status"] = "queued"
        JOBS[job_id]["progress"] = 0.0
        JOBS[job_id]["created_at"] = datetime.now(timezone.utc).isoformat()
    executor.submit(_run_generate, job_id, req)
    return {"job_id": job_id}


@app.post("/generate_image")
def start_generate_image(req: GenerateImageRequest):
    job_id = _new_item_id()
    with JOBS_LOCK:
        JOBS[job_id] = req.dict()
        JOBS[job_id]["id"] = job_id
        JOBS[job_id]["status"] = "queued"
        JOBS[job_id]["progress"] = 0.0
        JOBS[job_id]["created_at"] = datetime.now(timezone.utc).isoformat()
    executor.submit(_run_generate_image, job_id, req)
    return {"job_id": job_id}


def _run_generate_image(job_id: str, req: GenerateImageRequest):
    global _CURRENT_JOB_ID
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"
    try:
        _ensure_image_to_video()
        img_bytes = base64.b64decode(req.image)
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        if req.match_source:
            img_w, img_h = image.size
            scale = min(req.width / img_w, req.height / img_h, 1.0)
            out_w = int(img_w * scale)
            out_h = int(img_h * scale)
            out_w = max(32, out_w - (out_w % 32))
            out_h = max(32, out_h - (out_h % 32))
            image = image.resize((out_w, out_h), Image.Resampling.LANCZOS)
            req.width = out_w
            req.height = out_h
        else:
            image = image.resize((req.width, req.height), Image.Resampling.LANCZOS)
        generator = None
        if req.seed != -1:
            generator = torch.Generator(device="cuda").manual_seed(req.seed)

        _CURRENT_JOB_ID = job_id
        try:
            frames = pipe(
                image=image,
                prompt=req.prompt,
                negative_prompt=req.negative_prompt or "",
                width=req.width,
                height=req.height,
                num_frames=req.num_frames,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
                generator=generator,
                output_type="pil",
            ).frames
        finally:
            _CURRENT_JOB_ID = None

        video = frames[0] if frames and isinstance(frames[0], (list, tuple)) else frames
        video_path = _video_path(job_id)
        export_to_video(video, str(video_path), fps=req.fps)
        item = {
            "id": job_id,
            "status": "completed",
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "width": req.width,
            "height": req.height,
            "num_frames": req.num_frames,
            "num_inference_steps": req.num_inference_steps,
            "guidance_scale": req.guidance_scale,
            "seed": req.seed,
            "fps": req.fps,
            "created_at": JOBS[job_id].get("created_at", datetime.now(timezone.utc).isoformat()),
            "video_url": f"api/history/videos/{job_id}.mp4",
        }
        _atomic_write_json(_item_path(job_id), item)
        with JOBS_LOCK:
            JOBS[job_id].update({
                "status": "completed",
                "progress": 1.0,
                "video_url": item["video_url"],
                "created_at": item["created_at"],
            })
        _prune_history()
    except Exception as e:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(e)


def _run_generate(job_id: str, req: GenerateRequest):
    global _CURRENT_JOB_ID
    with JOBS_LOCK:
        JOBS[job_id]["status"] = "running"

    try:
        _ensure_text_to_video()
        generator = None
        if req.seed != -1:
            generator = torch.Generator(device="cuda").manual_seed(req.seed)

        _CURRENT_JOB_ID = job_id
        try:
            frames = pipe(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt or "",
                width=req.width,
                height=req.height,
                num_frames=req.num_frames,
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
                generator=generator,
                output_type="pil",
            ).frames
        finally:
            _CURRENT_JOB_ID = None

        # Different pipelines return either [PIL] or [[PIL]]; normalize to a single video.
        video = frames[0] if frames and isinstance(frames[0], (list, tuple)) else frames

        video_path = _video_path(job_id)
        export_to_video(video, str(video_path), fps=req.fps)

        item = {
            "id": job_id,
            "status": "completed",
            "prompt": req.prompt,
            "negative_prompt": req.negative_prompt,
            "width": req.width,
            "height": req.height,
            "num_frames": req.num_frames,
            "num_inference_steps": req.num_inference_steps,
            "guidance_scale": req.guidance_scale,
            "seed": req.seed,
            "fps": req.fps,
            "created_at": JOBS[job_id].get("created_at", datetime.now(timezone.utc).isoformat()),
            "video_url": f"api/history/videos/{job_id}.mp4",
        }
        _atomic_write_json(_item_path(job_id), item)

        with JOBS_LOCK:
            JOBS[job_id].update({
                "status": "completed",
                "progress": 1.0,
                "video_url": item["video_url"],
                "created_at": item["created_at"],
            })
        _prune_history()
    except Exception as e:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(e)


@app.get("/progress/{job_id}")
def get_progress(job_id: str):
    with JOBS_LOCK:
        if job_id not in JOBS:
            raise HTTPException(status_code=404, detail="job not found")
        return JOBS[job_id]


@app.get("/history")
def get_history():
    return {"history": _list_history()}


@app.get("/history/{item_id}")
def get_history_item(item_id: str):
    p = _item_path(item_id)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    with JOBS_LOCK:
        if item_id in JOBS:
            return JOBS[item_id]
    raise HTTPException(status_code=404, detail="item not found")


@app.delete("/history/{item_id}")
def delete_history_item(item_id: str):
    p = _item_path(item_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="item not found")
    p.unlink()
    vp = _video_path(item_id)
    if vp.exists():
        vp.unlink()
    with JOBS_LOCK:
        JOBS.pop(item_id, None)
    return {"ok": True}
