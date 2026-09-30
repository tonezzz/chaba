#!/usr/bin/env python3
"""Run one image-generation experiment on an ephemeral Colab GPU VM.

Usage (on the host, via the colab-test venv):
    uvx --from google-colab-cli==0.7.4 colab run --gpu T4 \
        scripts/colab/img_gen.py -- \
        --model prompthero/openjourney --prompt "..." \
        --width 512 --height 512 --steps 25 --seed 42

The script writes report.json + generated image(s) to --out-dir on the VM.
Download them afterwards with `colab download` (or use --keep + colab exec).
"""
import argparse
import json
import os
import subprocess
import sys
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="prompthero/openjourney")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="")
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--height", type=int, default=512)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--guidance", type=float, default=7.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--out-dir", default="/content/output")
    args = ap.parse_args()

    print("Installing diffusers / transformers / accelerate ...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q",
         "diffusers", "transformers", "accelerate"])

    import torch
    from diffusers import StableDiffusionPipeline

    os.makedirs(args.out_dir, exist_ok=True)

    print(f"Loading pipeline: {args.model}", flush=True)
    t0 = time.time()
    pipe = StableDiffusionPipeline.from_pretrained(args.model, torch_dtype=torch.float16)
    pipe = pipe.to("cuda")
    load_s = time.time() - t0
    print(f"Pipeline loaded in {load_s:.1f}s", flush=True)

    runs = []
    for i in range(args.count):
        seed = args.seed + i
        gen = torch.Generator("cuda").manual_seed(seed)
        torch.cuda.reset_peak_memory_stats()
        t1 = time.time()
        image = pipe(
            args.prompt,
            negative_prompt=args.negative or None,
            height=args.height,
            width=args.width,
            num_inference_steps=args.steps,
            guidance_scale=args.guidance,
            generator=gen,
        ).images[0]
        gen_s = time.time() - t1
        vram_mb = torch.cuda.max_memory_allocated() / 1024**2

        png_path = os.path.join(args.out_dir, f"img_{i:02d}_s{seed}.png")
        image.save(png_path)
        runs.append({
            "seed": seed,
            "gen_time_s": round(gen_s, 1),
            "vram_peak_mb": round(vram_mb, 1),
            "png_path": png_path,
        })

    report = {
        "model": args.model,
        "prompt": args.prompt,
        "negative": args.negative,
        "width": args.width,
        "height": args.height,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance,
        "device": torch.cuda.get_device_name(0),
        "load_time_s": round(load_s, 1),
        "runs": runs,
    }
    json_path = os.path.join(args.out_dir, "report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
