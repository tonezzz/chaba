#!/usr/bin/env python3
"""kk_mac_video_compare — old-vs-new comparison for KK-Mac MLX rerenders.

Compares an old (CUDA/ViMax/MPS) clip against a new MLX clip shot-by-shot:
stream specs (codec/size/fps/frames/duration), frame-aligned SSIM+PSNR
when geometry matches (ffmpeg filters), black/freeze detection on the new
clip, per-shot contact strips, and a JSON report. Read-only on inputs;
writes only into --out-dir.

Usage:
  kk_mac_video_compare.py --pair old.mp4=new.mp4 [--pair ...] \
      --out-dir comparisons/scene0-control-20261124 [--strip-frames 3]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries",
             "stream=codec_name,width,height,r_frame_rate,nb_frames,duration",
             "-of", "json", str(path)])
    if p.returncode != 0:
        return {"error": p.stderr.strip()[:200]}
    st = (json.loads(p.stdout).get("streams") or [{}])[0]
    num, _, den = str(st.get("r_frame_rate", "0/1")).partition("/")
    fps = round(float(num) / float(den), 4) if den and float(den) else 0.0
    return {
        "codec": st.get("codec_name"),
        "width": st.get("width"), "height": st.get("height"),
        "fps": fps, "frames": int(st.get("nb_frames") or 0),
        "duration_s": round(float(st.get("duration") or 0), 4),
    }


def ffmpeg_metrics(old: Path, new: Path) -> dict:
    """SSIM+PSNR via ffmpeg filters; scales new to old if needed."""
    po = probe(old)
    scale = f"scale={po['width']}:{po['height']},setsar=1"
    out = {}
    # ssim: overall score is on the 'All:' line of the stream summary
    fc_ssim = (f"[0:v]{scale}[a];[1:v]{scale}[b];"
               f"[a][b]ssim")
    p = run(["ffmpeg", "-i", str(old), "-i", str(new), "-filter_complex",
             fc_ssim, "-an", "-f", "null", "-"])
    for line in (p.stdout + p.stderr).splitlines():
        if "All:" in line:
            out["ssim_all"] = line.split("All:")[-1].strip()
    fc_psnr = (f"[0:v]{scale}[a];[1:v]{scale}[b];"
               f"[a][b]psnr")
    p = run(["ffmpeg", "-i", str(old), "-i", str(new), "-filter_complex",
             fc_psnr, "-an", "-f", "null", "-"])
    for line in (p.stdout + p.stderr).splitlines():
        if "average:" in line:
            out["psnr_avg"] = line.split("average:")[-1].strip()
    return out


def detect_defects(path: Path) -> dict:
    """blackdetect + freezedetect on the new clip."""
    p = run(["ffmpeg", "-i", str(path), "-vf",
             "blackdetect=d=0.1:pix_th=0.10,freezedetect=n=-60dB:d=0.5",
             "-an", "-f", "null", "-"])
    black = [l for l in p.stderr.splitlines() if "blackdetect" in l]
    freeze = [l for l in p.stderr.splitlines() if "freezedetect" in l]
    return {"black_events": len(black), "freeze_events": len(freeze),
            "black_log": black[:5], "freeze_log": freeze[:5]}


def contact_strip(old: Path, new: Path, out_png: Path, n: int = 3) -> bool:
    """Tile n frames from each video side-by-side (old top, new bottom)."""
    # pick evenly spaced timestamps from the new clip duration
    dur = probe(new)["duration_s"] or 1.0
    ts = [dur * i / max(n - 1, 1) for i in range(n)]
    frames = []
    for src, tag in ((old, "o"), (new, "n")):
        for i, t in enumerate(ts):
            dst = out_png.parent / f"._{tag}{i}.png"
            r = run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(src),
                     "-frames:v", "1", "-q:v", "3", str(dst)])
            if r.returncode == 0 and dst.exists():
                frames.append(dst)
    if not frames:
        return False
    inputs = []
    for f in frames:
        inputs += ["-i", str(f)]
    # single row: all old frames then all new frames
    fc = "".join(f"[{i}:v]" for i in range(len(frames)))
    fc += f"hstack=inputs={len(frames)}"
    p = run(["ffmpeg", "-y", *inputs, "-filter_complex", fc,
             "-frames:v", "1", str(out_png)])
    for f in frames:
        f.unlink(missing_ok=True)
    return p.returncode == 0 and out_png.exists()


def compare_pair(old: Path, new: Path, out_dir: Path) -> dict:
    name = f"{old.stem}__vs__{new.stem}"
    row = {"old": str(old), "new": str(new),
           "old_probe": probe(old), "new_probe": probe(new)}
    po, pn = row["old_probe"], row["new_probe"]
    same_geom = all(po.get(k) == pn.get(k)
                    for k in ("width", "height", "fps"))
    row["same_geometry"] = same_geom
    if same_geom and po.get("frames") and pn.get("frames"):
        row["stream_metrics"] = ffmpeg_metrics(old, new)
    row["new_defects"] = detect_defects(new)
    strip = out_dir / f"{name}-strip.png"
    row["contact_strip"] = str(strip) if contact_strip(old, new, strip) else None
    row["duration_delta_s"] = round(
        (pn.get("duration_s") or 0) - (po.get("duration_s") or 0), 4)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="append", required=True,
                    help="old.mp4=new.mp4 (repeatable)")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--strip-frames", type=int, default=3)
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in args.pair:
        old_s, _, new_s = spec.partition("=")
        rows.append(compare_pair(Path(old_s), Path(new_s), args.out_dir))
    report = {"generated_by": "kk_mac_video_compare.py",
              "pairs": rows}
    out = args.report or args.out_dir / "comparison-report.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
