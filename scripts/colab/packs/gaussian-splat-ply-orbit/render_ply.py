#!/usr/bin/env python3
"""Render a 3DGS PLY to an orbit MP4 + still + timing/VRAM report.

Runs inside the nest-pack contract (queue-runner execs run_sh with
PACK_DIR/NEST_ROOT in env). Reads a standard Inria/gsplat PLY, renders a
turntable orbit with gsplat.rasterization, and writes artifacts under
$PACK_DIR/out plus $PACK_DIR/report.md.

Env knobs (all optional):
  GS_PLY       path to PLY (default: kk-mac-hibiscus-7k pack on the store)
  GS_UP        world up axis for the orbit: x|y|z (default z)
  GS_SH        1 = full SH degree-3 color, 0 = DC-only (default 1)
  GS_SH_ORDER  'channel' (gsplat export order) or 'band' (Inria order)
  GS_FRAMES    orbit frame count (default 48)
  GS_W/GS_H    output resolution (default 640x384)
"""
import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
import imageio.v2 as imageio
from plyfile import PlyData
from gsplat import rasterization

NEST = os.environ.get("NEST_ROOT", "/content/drive/MyDrive/ada-nest")
PACK_DIR = os.environ.get("PACK_DIR", ".")
PLY = os.environ.get(
    "GS_PLY", f"{NEST}/packs/kk-mac-hibiscus-7k/point_cloud_6999.ply"
)
OUT = os.path.join(PACK_DIR, "out")
os.makedirs(OUT, exist_ok=True)

W = int(os.environ.get("GS_W", "640"))
H = int(os.environ.get("GS_H", "384"))
FRAMES = int(os.environ.get("GS_FRAMES", "48"))
UP_NAME = os.environ.get("GS_UP", "z").lower()
SH_MODE = os.environ.get("GS_SH", "1") == "1"
SH_ORDER = os.environ.get("GS_SH_ORDER", "channel").lower()
FOV_DEG = float(os.environ.get("GS_FOV_DEG", "42"))
ELEV_DEG = float(os.environ.get("GS_ELEV_DEG", "12"))


def load_ply(path):
    ply = PlyData.read(path)
    if "vertex" not in ply:
        raise RuntimeError(f"{path}: no vertex element")
    v = ply["vertex"]

    def col(name):
        return np.asarray(v[name], dtype=np.float32)

    n = len(v)
    names = set(v.data.dtype.names)
    has_rest = all(f"f_rest_{i}" in names for i in range(45))
    return {
        "n": n,
        "means": np.stack([col("x"), col("y"), col("z")], 1),
        "f_dc": np.stack([col("f_dc_0"), col("f_dc_1"), col("f_dc_2")], 1),
        "f_rest": (
            np.stack([col(f"f_rest_{i}") for i in range(45)], 1)
            if has_rest
            else None
        ),
        "opacity": col("opacity"),
        "scale": np.stack([col("scale_0"), col("scale_1"), col("scale_2")], 1),
        "rot": np.stack([col(f"rot_{i}") for i in range(4)], 1),
    }


def build_colors(d, device):
    """Return (colors, sh_degree). colors is (N,3) RGB or (N,16,3) SH."""
    sh0 = torch.tensor(d["f_dc"], device=device).unsqueeze(1)  # (N,1,3)
    if not SH_MODE or d["f_rest"] is None:
        c0 = 0.28209479177387814
        return (sh0.squeeze(1) * c0 + 0.5).clamp(0.0, 1.0), None
    rest = torch.tensor(d["f_rest"], device=device)  # (N,45)
    n = rest.shape[0]
    if SH_ORDER == "channel":
        # gsplat export_splats order: shN (N,K,3) -> (N,3,K) flat
        shn = rest.reshape(n, 3, 15).permute(0, 2, 1)  # (N,15,3)
    else:
        # band-major order: (band,channel) pairs -> (N,15,3)
        shn = rest.reshape(n, 15, 3)
    colors = torch.cat([sh0, shn], dim=1)  # (N,16,3)
    return colors, 3


def look_at(eye, target, up):
    """world-to-camera 4x4 for gsplat's OpenCV camera model
    (x=right, y=down, z=forward; +z is depth)."""
    f = F.normalize(target - eye, dim=0)
    r = F.normalize(torch.cross(f, up), dim=0)
    d = torch.cross(f, r)
    R = torch.stack([r, d, f])
    V = torch.eye(4, device=eye.device, dtype=eye.dtype)
    V[:3, :3] = R
    V[:3, 3] = -R @ eye
    return V


def basis_perp(up):
    """Two orthonormal axes spanning the plane perpendicular to `up`."""
    up = F.normalize(up, dim=0)
    a = torch.tensor([1.0, 0.0, 0.0], device=up.device)
    if abs(float(up @ a)) > 0.9:
        a = torch.tensor([0.0, 1.0, 0.0], device=up.device)
    e1 = F.normalize(torch.cross(up, a), dim=0)
    e2 = torch.cross(up, e1)
    return e1, e2


def render_frame(means, quats, scales, opacities, colors, sh_degree,
                 viewmats, Ks, width, height):
    renders, _, _ = rasterization(
        means, quats, scales, opacities, colors,
        viewmats=viewmats, Ks=Ks, width=width, height=height,
        sh_degree=sh_degree, packed=True,
    )
    return torch.clamp(renders[0], 0.0, 1.0)


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("gaussian-splat-ply-orbit requires a CUDA GPU")
    device = "cuda"
    t_all = time.time()

    d = load_ply(PLY)
    n = d["n"]
    print(f"loaded {PLY}: {n} gaussians", flush=True)

    means = torch.tensor(d["means"], device=device)
    quats = F.normalize(torch.tensor(d["rot"], device=device), dim=-1)
    scales = torch.exp(torch.tensor(d["scale"], device=device))
    opacities = torch.sigmoid(torch.tensor(d["opacity"], device=device))
    colors, sh_degree = build_colors(d, device)

    up = torch.zeros(3, device=device)
    up["xyz".index(UP_NAME)] = 1.0
    e1, e2 = basis_perp(up)

    center = means.median(dim=0).values
    dist = (means - center).norm(dim=1)
    r90 = float(torch.quantile(dist, 0.9).item())

    fy = H / (2.0 * np.tan(np.deg2rad(FOV_DEG) / 2.0))
    fx = fy
    Ks = torch.tensor(
        [[[fx, 0.0, W / 2.0], [0.0, fy, H / 2.0], [0.0, 0.0, 1.0]]],
        device=device, dtype=torch.float32,
    )

    el = np.deg2rad(ELEV_DEG)
    cel, sel = np.cos(el), np.sin(el)

    def eye_at(theta, mult):
        return center + r90 * mult * (
            cel * (np.cos(theta) * e1 + np.sin(theta) * e2) + sel * up
        )

    # Auto-fit: shrink/grow orbit radius until alpha coverage lands in
    # [0.25, 0.8] on a probe frame.
    radius_mult = 1.9
    best_cov = -1.0
    for _ in range(4):
        eye = eye_at(0.6, radius_mult)
        view = look_at(eye, center, up)[None]
        frame = render_frame(
            means, quats, scales, opacities, colors, sh_degree, view, Ks, W, H
        )
        cov = float((frame.mean(dim=-1) > 0.04).float().mean().item())
        best_cov = cov
        if 0.25 <= cov <= 0.8:
            break
        radius_mult *= 0.72 if cov < 0.25 else 1.35

    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()
    writer = imageio.get_writer(
        f"{OUT}/gaussian-splat-ply-orbit.mp4", fps=24,
        codec="libx264", quality=8,
    )
    first = None
    alphas = []
    for i in range(FRAMES):
        theta = i / FRAMES * 2.0 * np.pi
        view = look_at(eye_at(theta, radius_mult), center, up)[None]
        frame = render_frame(
            means, quats, scales, opacities, colors, sh_degree,
            view, Ks, W, H,
        )
        alphas.append(float(frame.mean().item()))
        arr = (frame.detach().cpu().numpy() * 255).astype("uint8")
        if first is None:
            first = arr.copy()
            imageio.imwrite(f"{OUT}/gaussian-splat-ply-orbit.png", arr)
        writer.append_data(arr)
    writer.close()
    render_s = time.time() - t0
    vram_gb = torch.cuda.max_memory_allocated() / 1e9

    report = {
        "pack": "gaussian-splat-ply-orbit",
        "source_ply": PLY,
        "num_gaussians": int(n),
        "frames": FRAMES,
        "resolution": f"{W}x{H}",
        "sh_mode": "sh3" if sh_degree else "dc",
        "sh_order": SH_ORDER if sh_degree else None,
        "up_axis": UP_NAME,
        "elevation_deg": ELEV_DEG,
        "fov_deg": FOV_DEG,
        "scene_radius_p90": round(r90, 4),
        "orbit_radius_mult": round(radius_mult, 3),
        "frame_alpha_coverage_probe": round(best_cov, 4),
        "render_seconds": round(render_s, 2),
        "sec_per_frame": round(render_s / FRAMES, 3),
        "peak_cuda_gb": round(vram_gb, 3),
        "mean_frame_luma": round(float(np.mean(alphas)), 4),
        "wall_seconds_total": round(time.time() - t_all, 1),
        "device": torch.cuda.get_device_name(0),
    }
    with open(f"{PACK_DIR}/report.json", "w") as f:
        json.dump(report, f, indent=2)
    md = [
        "# gaussian-splat-ply-orbit — PLY to orbit MP4",
        "",
        f"- source PLY: `{PLY}`",
        f"- Gaussians: {n:,}",
        f"- output: {W}x{H}, {FRAMES} frames @24fps",
        f"- color mode: {'SH degree 3' if sh_degree else 'DC only'}"
        + (f" ({SH_ORDER} order)" if sh_degree else ""),
        f"- up axis: {UP_NAME}, elevation {ELEV_DEG}deg, fov {FOV_DEG}deg",
        f"- render time: {render_s:.2f}s ({render_s / FRAMES * 1000:.0f} ms/frame)",
        f"- peak CUDA memory: {vram_gb:.2f} GB",
        f"- device: {torch.cuda.get_device_name(0)}",
        "",
        "Artifacts: `out/gaussian-splat-ply-orbit.mp4`, "
        "`out/gaussian-splat-ply-orbit.png`, `report.json`.",
        "",
        "This renders the existing kk-mac-hibiscus-7k reconstruction with "
        "gsplat (CUDA). It validates the render lane only — the PLY was "
        "trained by mpsplat on KK-Mac, not by this pack.",
    ]
    with open(f"{PACK_DIR}/report.md", "w") as f:
        f.write("\n".join(md) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
