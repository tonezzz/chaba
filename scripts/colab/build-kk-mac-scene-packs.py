#!/usr/bin/env python3
"""Build versioned, one-shot KK-Mac storyboard packs from audited assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import yaml

PROJECT = "kk-video-c9f99fee6146"
SOURCE_SHA256 = "5a6ef65431865b1b4957b70023d3e83cbdcaf19a5ebaa4896c6f2cd31ad06d34"
ROOT_DATE = "20261030"
REQUIRES = [
    "kk-mac-storyboard-i2v-probe-20261029",
    "kk-mac-storyboard-i2v-fullshot01-20261030",
    "kk-mac-storyboard-i2v-shot02-20261030",
    "kk-mac-storyboard-i2v-visual-review-approved-20261030",
]
MODEL_REVISION = "8984fa25007f376c1a299016d0957a37a2f797bb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_spec(name: str, shot: int) -> str:
    return f"""name: {name}
requires:
{''.join(f'  - {item}\n' for item in REQUIRES)}needs:
  ram_gb: 30
  disk_gb: 10
  egress_only_ok: false
timeout_s: 3600
artifacts:
  - packs/{name}/out/shot{shot:02d}-i2v-mps.mp4
  - packs/{name}/out/probe.json
  - packs/{name}/out/report.md
prep: |
  set -eu
  pmset -g batt | grep -q "AC Power" || {{ echo "KK-Mac is not on AC"; exit 1; }}
  FREE_PCT=$(memory_pressure | awk -F'[:%]' '/System-wide memory free percentage:/ {{gsub(/[[:space:]]/, "", $2); print $2}}')
  if [ -n "$FREE_PCT" ] && [ "$FREE_PCT" -lt 20 ]; then echo "memory gate failed: $FREE_PCT% free"; exit 1; fi
  if [ -x /opt/homebrew/bin/ollama ]; then
    MODELS=$(/opt/homebrew/bin/ollama ps 2>/dev/null | tail -n +2 | sed '/^[[:space:]]*$/d')
    [ -z "$MODELS" ] || {{ echo "Ollama model resident"; exit 1; }}
  fi
  BUSY=$(ps -axo comm | awk '{{s=tolower($0); sub(/^.*\\\\//, "", s); if(s ~ /^(ffmpeg|mlx|resolve|davinci resolve|premiere pro|adobe premiere pro|final cut pro|after effects|photoshop)$/) n++}} END {{print n+0}}')
  [ "$BUSY" -eq 0 ] || {{ echo "owner video/compute workload detected"; exit 1; }}
  PY="$HOME/kk-video/.venv/bin/python"
  MODEL="$HOME/.cache/huggingface/hub/models--Lightricks--LTX-Video/snapshots/{MODEL_REVISION}"
  test -x "$PY"
  for f in model_index.json scheduler/scheduler_config.json transformer/config.json transformer/diffusion_pytorch_model.safetensors.index.json transformer/diffusion_pytorch_model-00001-of-00002.safetensors transformer/diffusion_pytorch_model-00002-of-00002.safetensors vae/config.json vae/diffusion_pytorch_model.safetensors; do
    test -s "$MODEL/$f" || {{ echo "cached LTX component missing: $f"; exit 2; }}
  done
  "$PY" -c "import torch; from diffusers import LTXImageToVideoPipeline; assert torch.backends.mps.is_available(); assert LTXImageToVideoPipeline; print('MPS I2V ready')"
run_sh: |
  export HF_HUB_OFFLINE=1
  "$HOME/kk-video/.venv/bin/python" "$PACK_DIR/run_scene.py" \
    --pack-dir "$PACK_DIR" \
    --model-dir "$HOME/.cache/huggingface/hub/models--Lightricks--LTX-Video/snapshots/{MODEL_REVISION}"
"""


def build(args: argparse.Namespace) -> list[Path]:
    source_map = yaml.safe_load(args.scene_map.read_text(encoding="utf-8"))
    if (source_map.get("project_id") != PROJECT
            or source_map.get("source", {}).get("sha256") != SOURCE_SHA256
            or source_map.get("visibility") != "private"):
        raise ValueError("scene map is not the approved private source map")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    source = next(
        (entry for entry in audit.get("sources", [])
         if entry.get("label") == "v1_01"),
        None)
    if not source or source.get("sha256") != SOURCE_SHA256:
        raise ValueError("image audit does not match approved v1_01 source")
    image_records = sorted(
        (record for record in source.get("extracted_files", [])
         if "/images/image-" in record.get("path", "")),
        key=lambda record: record["path"])
    image_rows = source.get("image_rows") or []
    if len(image_records) != len(image_rows):
        raise ValueError("audit image rows and files do not align")
    by_id = {
        Path(record["path"]).stem: (record, image_rows[index])
        for index, record in enumerate(image_records)
    }

    entries = [
        item for item in source_map["shots"]
        if args.first_shot <= int(item["shot"]) <= args.last_shot
    ]
    expected = list(range(args.first_shot, args.last_shot + 1))
    if [int(item["shot"]) for item in entries] != expected:
        raise ValueError("scene map does not contain a contiguous requested shot range")

    plans = []
    for item in entries:
        shot = int(item["shot"])
        page = int(item["storyboard_page"])
        image_id = str(item["storyboard_image"])
        if image_id not in by_id:
            raise ValueError(f"missing audited image {image_id}")
        record, row = by_id[image_id]
        if int(row["page"]) != page:
            raise ValueError(f"{image_id} audit page differs from map")
        image_source = args.images_dir / Path(record["path"]).name
        embed_source = args.embeds_dir / f"shot{shot:02d}.pt"
        if (not image_source.is_file()
                or image_source.stat().st_size != int(record["bytes"])
                or sha256(image_source) != record["sha256"]):
            raise ValueError(f"{image_id} local asset does not match the audit")
        if not embed_source.is_file() or embed_source.stat().st_size == 0:
            raise FileNotFoundError(f"missing embedding for shot {shot}")
        name = f"kk-mac-storyboard-i2v-shot{shot:02d}-{ROOT_DATE}"
        target = args.output_root / name
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing pack {target}")
        plans.append({
            "shot": shot,
            "page": page,
            "image_id": image_id,
            "image_record": record,
            "image_source": image_source,
            "embed_source": embed_source,
            "embed_sha256": sha256(embed_source),
            "name": name,
            "target": target,
        })

    built = []
    for plan in plans:
        inputs = plan["target"] / "inputs"
        inputs.mkdir(parents=True)
        shutil.copyfile(args.audit, inputs / "audit.json")
        image_name = Path(plan["image_record"]["path"]).name
        embedding_name = f"shot{plan['shot']:02d}.pt"
        shutil.copyfile(plan["image_source"], inputs / image_name)
        shutil.copyfile(plan["embed_source"], inputs / embedding_name)
        scene = {
            "schema": 1,
            "project_id": PROJECT,
            "visibility": "private",
            "source": {
                "filename": "OST_-_v1_01.pdf",
                "sha256": SOURCE_SHA256,
            },
            "shot": {
                "number": plan["shot"],
                "storyboard_page": plan["page"],
                "storyboard_image": plan["image_id"],
                "image_file": image_name,
                "image_sha256": plan["image_record"]["sha256"],
                "embedding": embedding_name,
                "embedding_sha256": plan["embed_sha256"],
            },
        }
        (inputs / "scene-map.yml").write_text(
            yaml.safe_dump(scene, sort_keys=False, allow_unicode=True),
            encoding="utf-8")
        shutil.copyfile(args.runner, plan["target"] / "run_scene.py")
        (plan["target"] / "pack.yml").write_text(
            pack_spec(plan["name"], plan["shot"]), encoding="utf-8")
        built.append(plan["target"])
    return built


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-map", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--embeds-dir", required=True, type=Path)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--first-shot", type=int, default=3)
    parser.add_argument("--last-shot", type=int, default=10)
    args = parser.parse_args()
    for path in (args.scene_map, args.audit, args.images_dir,
                 args.embeds_dir, args.runner, args.output_root):
        if not path.exists():
            raise FileNotFoundError(path)
    for pack in build(args):
        print(pack)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
