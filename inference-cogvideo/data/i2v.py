import os
import json
import time
import uuid
import traceback

import torch
from PIL import Image
from diffusers import LTXImageToVideoPipeline
from diffusers.utils import export_to_video


def log(msg):
    print(msg, flush=True)
    with open("/app/data/i2v.log", "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


def _new_item_id() -> str:
    return f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _atomic_write_json(path: str, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    config_path = "/app/data/i2v_config.json"
    if not os.path.exists(config_path):
        log(f"[v2] config not found: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    image_path = cfg.get("image_path", "/app/data/history/images/anchor.png")
    if not os.path.exists(image_path):
        log(f"[v2] anchor image not found: {image_path}")
        return

    image = Image.open(image_path).convert("RGB")
    w = cfg["width"]
    h = cfg["height"]
    resample = getattr(Image, "Resampling", Image).LANCZOS
    image = image.resize((w, h), resample)
    log(f"[v2] anchor image loaded and resized to {w}x{h}")

    prompt = cfg["prompt"]
    negative_prompt = cfg.get("negative_prompt", "")
    num_frames = cfg.get("num_frames", 9)
    frame_rate = cfg.get("frame_rate", 25)
    num_inference_steps = cfg.get("num_inference_steps", 80)
    guidance_scale = cfg.get("guidance_scale", 3.0)
    guidance_rescale = cfg.get("guidance_rescale", 0.0)
    decode_timestep = cfg.get("decode_timestep", 0.0)
    decode_noise_scale = cfg.get("decode_noise_scale", None)
    seed = cfg.get("seed", -1)
    fps = cfg.get("fps", 8)

    model_id = os.environ.get("MODEL_ID", "a-r-r-o-w/LTX-Video-diffusers")
    log(f"[v2] loading image-to-video model {model_id}")
    try:
        pipe = LTXImageToVideoPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
        )
        pipe.enable_sequential_cpu_offload()
        log("[v2] model loaded")
    except Exception:
        log("[v2] load failed:\n" + traceback.format_exc())
        return

    generator = None
    if seed >= 0:
        generator = torch.Generator(device="cuda").manual_seed(seed)

    log(
        f"[v2] generating {w}x{h}, {num_frames} frames, "
        f"frame_rate={frame_rate}, {num_inference_steps} steps, "
        f"cfg={guidance_scale}, rescale={guidance_rescale}, "
        f"decode_timestep={decode_timestep}, decode_noise_scale={decode_noise_scale}, seed={seed}"
    )
    call_kwargs = {
        "image": image,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": w,
        "height": h,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
        "guidance_rescale": guidance_rescale,
        "decode_timestep": decode_timestep,
        "generator": generator,
        "output_type": "pil",
    }
    if decode_noise_scale is not None:
        call_kwargs["decode_noise_scale"] = decode_noise_scale

    try:
        result = pipe(**call_kwargs)
        frames = result.frames
    except Exception:
        log("[v2] inference failed:\n" + traceback.format_exc())
        return

    video = frames[0] if frames and isinstance(frames[0], (list, tuple)) else frames
    job_id = _new_item_id()
    video_path = f"/app/data/history/videos/{job_id}.mp4"
    export_to_video(video, video_path, fps=fps)
    log(f"[v2] saved video {video_path}")

    item = {
        "id": job_id,
        "status": "completed",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": w,
        "height": h,
        "num_frames": num_frames,
        "frame_rate": frame_rate,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
        "guidance_rescale": guidance_rescale,
        "decode_timestep": decode_timestep,
        "decode_noise_scale": decode_noise_scale,
        "seed": seed,
        "fps": fps,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_url": f"api/history/videos/{job_id}.mp4",
    }
    _atomic_write_json(f"/app/data/history/items/{job_id}.json", item)
    log(f"[v2] saved item {job_id}")


if __name__ == "__main__":
    main()
