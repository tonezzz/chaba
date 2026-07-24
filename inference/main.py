import os
import time
import io
import base64
import uuid
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from diffusers import StableDiffusionPipeline

app = FastAPI(title="Imagen Inference")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_ID = os.environ.get("MODEL_ID", "runwayml/stable-diffusion-v1-5")
pipe = None


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    width: int = Field(512, ge=512, le=1024, multiple_of=64)
    height: int = Field(512, ge=512, le=1024, multiple_of=64)
    steps: int = Field(25, ge=1, le=50)
    seed: int = Field(-1, ge=-1)


@app.on_event("startup")
def load_model():
    global pipe
    pipe = StableDiffusionPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float32,
        use_safetensors=True,
    )
    pipe.safety_checker = None
    pipe.feature_extractor = None
    pipe.enable_sequential_cpu_offload()


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID}


@app.post("/generate")
def generate(req: GenerateRequest):
    start = time.time()
    try:
        seed = req.seed if req.seed >= 0 else int(time.time()) + uuid.uuid4().int % 100000
        generator = torch.Generator(device="cuda").manual_seed(seed)
        image = pipe(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            num_inference_steps=req.steps,
            generator=generator,
        ).images[0]

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        return {
            "image_base64": image_b64,
            "seed": seed,
            "width": req.width,
            "height": req.height,
            "inference_time": round(time.time() - start, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
