#!/usr/bin/env python3
"""Photo -> 3DGS PLY reconstruction on the nest-pack contract.

Pipeline (card gaussian-splatting-nest-video-poc):
  1. Stage the hibiscus-v1 image set from the Drive store.
  2. COLMAP via pycolmap: SIFT features -> exhaustive matching ->
     incremental mapping (poses + sparse points + intrinsics).
  3. Build a gsplat-style parser: camtoworlds, undistorted intrinsics,
     world normalization (ported from gsplat examples/datasets).
  4. Train 3DGS with gsplat.rasterization (L1 + SSIM, DefaultStrategy
     densification, SH-degree schedule).
  5. Eval PSNR/SSIM on a held-out image split.
  6. Export PLY (gsplat export_splats), render an orbit MP4, and write
     report.md + metrics.json under $PACK_DIR.

Scratch (COLMAP db, sparse model, undistorted images) stays on local
disk under a tempdir; only the declared artifacts land in $PACK_DIR.

Env knobs (all optional, used for local reduced-scale prototypes):
  GS_IMAGES       image dir override (default: $NEST_ROOT/datasets/...)
  GS_STEPS        training steps            (default 5000)
  GS_FACTOR       image downscale divisor   (default 4)
  GS_TEST_EVERY   every Nth image is val    (default 5)
  GS_SH_DEGREE    max SH degree             (default 3)
  GS_ORBIT_FRAMES orbit mp4 length         (default 32)
  GS_ORBIT_W/H    orbit resolution          (default 640x384)
"""
import glob
import json
import math
import os
import shutil
import tempfile
import time

import cv2
import imageio.v2 as imageio
import numpy as np
import torch
import torch.nn.functional as F

NEST = os.environ.get("NEST_ROOT", "/content/drive/MyDrive/ada-nest")
PACK_DIR = os.environ.get("PACK_DIR", ".")
OUT = os.path.join(PACK_DIR, "out")
os.makedirs(OUT, exist_ok=True)

IMG_SRC = os.environ.get(
    "GS_IMAGES",
    f"{NEST}/datasets/gaussian/hibiscus-v1/source/original",
)
STEPS = int(os.environ.get("GS_STEPS", "5000"))
FACTOR = int(os.environ.get("GS_FACTOR", "4"))
TEST_EVERY = int(os.environ.get("GS_TEST_EVERY", "5"))
SH_DEGREE = int(os.environ.get("GS_SH_DEGREE", "3"))
ORBIT_FRAMES = int(os.environ.get("GS_ORBIT_FRAMES", "32"))
ORBIT_W = int(os.environ.get("GS_ORBIT_W", "640"))
ORBIT_H = int(os.environ.get("GS_ORBIT_H", "384"))
INIT_SCALE = float(os.environ.get("GS_INIT_SCALE", "1.0"))
INIT_OPA = float(os.environ.get("GS_INIT_OPA", "0.1"))
PACK_NAME = "gaussian-splat-hibiscus-recon"


# ---------------------------------------------------------------- COLMAP --
def run_colmap(img_dir, work):
    """SIFT -> exhaustive match -> incremental mapping. Returns the
    largest pycolmap.Reconstruction (registered-image count)."""
    import pycolmap

    db = os.path.join(work, "database.db")
    sparse = os.path.join(work, "sparse")
    t0 = time.time()
    pycolmap.extract_features(db, img_dir, camera_mode=pycolmap.CameraMode.AUTO)
    print(f"[colmap] features done {time.time() - t0:.0f}s", flush=True)
    t0 = time.time()
    pycolmap.match_exhaustive(db)
    print(f"[colmap] matching done {time.time() - t0:.0f}s", flush=True)
    t0 = time.time()
    recons = pycolmap.incremental_mapping(db, img_dir, sparse)
    print(f"[colmap] mapping done {time.time() - t0:.0f}s "
          f"({len(recons)} model(s))", flush=True)
    if not recons:
        raise RuntimeError("COLMAP incremental_mapping produced no model")
    recon = max(recons.values(), key=lambda r: r.num_reg_images())
    print(f"[colmap] using model: {recon.num_reg_images()} reg images, "
          f"{recon.num_points3D()} points3D", flush=True)
    return recon, time.time()


# ------------------------------------------------------- world normalize --
def similarity_from_cameras(c2w):
    """Ported from gsplat examples/datasets/normalize.py."""
    t = c2w[:, :3, 3]
    R = c2w[:, :3, :3]
    ups = np.sum(R * np.array([0, -1.0, 0]), axis=-1)
    world_up = np.mean(ups, axis=0)
    world_up /= np.linalg.norm(world_up)
    up_camspace = np.array([0.0, -1.0, 0.0])
    c = (up_camspace * world_up).sum()
    cross = np.cross(world_up, up_camspace)
    skew = np.array(
        [[0.0, -cross[2], cross[1]],
         [cross[2], 0.0, -cross[0]],
         [-cross[1], cross[0], 0.0]]
    )
    if c > -1:
        R_align = np.eye(3) + skew + (skew @ skew) * 1 / (1 + c)
    else:
        R_align = np.array([[-1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [0.0, 0.0, 1.0]])
    R = R_align @ R
    fwds = np.sum(R * np.array([0, 0.0, 1.0]), axis=-1)
    t = (R_align @ t[..., None])[..., 0]
    nearest = t + (fwds * -t).sum(-1)[:, None] * fwds
    translate = -np.median(nearest, axis=0)
    transform = np.eye(4)
    transform[:3, 3] = translate
    transform[:3, :3] = R_align
    scale = 1.0 / np.median(np.linalg.norm(t + translate, axis=-1))
    transform[:3, :] *= scale
    return transform


def align_principal_axes(point_cloud):
    centroid = np.median(point_cloud, axis=0)
    translated = point_cloud - centroid
    cov = np.cov(translated, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    sort_indices = eigenvalues.argsort()[::-1]
    eigenvectors = eigenvectors[:, sort_indices]
    if np.linalg.det(eigenvectors) < 0:
        eigenvectors[:, 0] *= -1
    rotation_matrix = eigenvectors.T
    transform = np.eye(4)
    transform[:3, :3] = rotation_matrix
    transform[:3, 3] = -rotation_matrix @ centroid
    return transform


def transform_points(matrix, points):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def transform_cameras(matrix, camtoworlds):
    camtoworlds = np.einsum("nij, ki -> nkj", camtoworlds, matrix)
    scaling = np.linalg.norm(camtoworlds[:, 0, :3], axis=1)
    camtoworlds[:, :3, :3] = camtoworlds[:, :3, :3] / scaling[:, None, None]
    return camtoworlds


# ----------------------------------------------------------------- parse --
CAMERA_DIST_PARAMS = {
    # model_name -> (dist coeff indices into cam.params, kind)
    "SIMPLE_PINHOLE": ((), "perspective"),
    "PINHOLE": ((), "perspective"),
    "SIMPLE_RADIAL": ((3,), "perspective"),      # [f,cx,cy,k]
    "RADIAL": ((3, 4), "perspective"),           # [f,cx,cy,k1,k2]
    "OPENCV": ((4, 5, 6, 7), "perspective"),     # fx,fy,cx,cy,k1,k2,p1,p2
    "FULL_OPENCV": ((4, 5, 6, 7, 8, 9, 10, 11), "perspective"),
    "OPENCV_FISHEYE": ((4, 5, 6, 7), "fisheye"),  # fx,fy,cx,cy,k1..k4
    "FOV": ((), "perspective"),
    "SIMPLE_RADIAL_FISHEYE": ((3,), "fisheye"),
    "RADIAL_FISHEYE": ((3, 4), "fisheye"),
}


def parse_reconstruction(recon):
    """Extract camtoworlds, intrinsics, points from a pycolmap 4.x
    Reconstruction (registered images only)."""
    reg_ids = set(recon.reg_image_ids())
    cams = {}
    for cam_id, cam in recon.cameras.items():
        model = cam.model_name
        if model not in CAMERA_DIST_PARAMS:
            raise RuntimeError(f"unsupported camera model {model}")
        didx, kind = CAMERA_DIST_PARAMS[model]
        params = np.asarray(cam.params, dtype=np.float64)
        dist = np.array([params[i] for i in didx], dtype=np.float64) \
            if didx else np.zeros(0)
        # normalize dist to what cv2/the fisheye remap expects
        if model == "SIMPLE_RADIAL":
            dist = np.array([dist[0], 0, 0, 0])
        elif model == "RADIAL":
            dist = np.array([dist[0], dist[1], 0, 0])
        elif model in ("SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE"):
            pass  # custom remap below uses what it gets
        cams[cam_id] = {
            "K": np.asarray(cam.calibration_matrix(), dtype=np.float64),
            "dist": dist,
            "kind": kind,
            "model": model,
            "w": int(cam.width),
            "h": int(cam.height),
        }

    entries = []
    for img_id, img in recon.images.items():
        if img_id not in reg_ids:
            continue
        w2c34 = np.asarray(img.cam_from_world().matrix(), dtype=np.float64)
        w2c = np.eye(4)
        w2c[:3] = w2c34
        c2w = np.linalg.inv(w2c)
        cam_id = img.camera_id
        entries.append({
            "name": img.name,
            "cam_id": cam_id,
            "c2w": c2w,
        })
    entries.sort(key=lambda e: e["name"])
    if not entries:
        raise RuntimeError("no registered images in reconstruction")

    camtoworlds = np.stack([e["c2w"] for e in entries])
    points = np.stack(
        [np.asarray(p.xyz, dtype=np.float32)
         for p in recon.points3D.values()]
    ) if recon.num_points3D() else np.zeros((0, 3), np.float32)
    points_rgb = np.stack(
        [np.asarray(p.color, dtype=np.uint8)
         for p in recon.points3D.values()]
    ) if recon.num_points3D() else np.zeros((0, 3), np.uint8)

    # world normalization (same recipe as gsplat examples)
    T1 = similarity_from_cameras(camtoworlds)
    camtoworlds = transform_cameras(T1, camtoworlds)
    points = transform_points(T1, points) if len(points) else points
    if len(points):
        T2 = align_principal_axes(points)
        camtoworlds = transform_cameras(T2, camtoworlds)
        points = transform_points(T2, points)
        transform = T2 @ T1
        if np.median(points[:, 2]) > np.mean(points[:, 2]):
            T3 = np.array([[1., 0, 0, 0], [0, -1., 0, 0],
                           [0, 0, -1., 0], [0, 0, 0, 1.]])
            camtoworlds = transform_cameras(T3, camtoworlds)
            points = transform_points(T3, points)
            transform = T3 @ transform
    else:
        transform = T1

    camera_locations = camtoworlds[:, :3, 3]
    scene_center = np.mean(camera_locations, axis=0)
    dists = np.linalg.norm(camera_locations - scene_center, axis=1)
    scene_scale = float(np.max(dists))

    return {
        "entries": entries,
        "camtoworlds": camtoworlds,
        "cameras": cams,
        "points": points.astype(np.float32),
        "points_rgb": points_rgb,
        "transform": transform,
        "scene_scale": scene_scale,
    }


# ------------------------------------------------- undistort + downscale --
def _dist_params_4(dist):
    """Pad/truncate distortion coeffs to the 4 cv2 expects."""
    d = np.zeros(4, dtype=np.float64)
    d[: min(4, len(dist))] = dist[:4]
    return d


def build_undistorted_images(parsed, img_dir, out_dir):
    """Undistort each image at native res, crop to valid ROI, downscale by
    FACTOR, save PNGs. Returns per-image record list with adjusted K."""
    os.makedirs(out_dir, exist_ok=True)
    records = []
    remap_cache = {}
    for i, e in enumerate(parsed["entries"]):
        cam = parsed["cameras"][e["cam_id"]]
        src = os.path.join(img_dir, e["name"])
        img = imageio.imread(src)[..., :3]
        K, dist, kind = cam["K"], cam["dist"], cam["kind"]
        w, h = cam["w"], cam["h"]
        if img.shape[1] != w or img.shape[0] != h:
            # COLMAP intrinsics describe the file as read; trust the file.
            h, w = img.shape[:2]
            scale_x, scale_y = w / cam["w"], h / cam["h"]
            K = K.copy()
            K[0] *= scale_x
            K[1] *= scale_y
        K_undist = K.copy()
        roi = (0, 0, w, h)
        if kind == "perspective" and len(dist) and np.any(dist):
            d4 = _dist_params_4(dist)
            K_undist, roi_arr = cv2.getOptimalNewCameraMatrix(
                K, d4, (w, h), 0)
            roi = tuple(int(v) for v in roi_arr)
            mapx, mapy = cv2.initUndistortRectifyMap(
                K, d4, None, K_undist, (w, h), cv2.CV_32FC1)
            key = e["cam_id"]
            if key not in remap_cache:
                remap_cache[key] = (mapx, mapy)
            mx, my = remap_cache[key]
            img = cv2.remap(img, mx, my, cv2.INTER_LINEAR)
            x, y, rw, rh = roi
            img = img[y:y + rh, x:x + rw]
            K_undist = K_undist.copy()
            K_undist[0, 2] -= x
            K_undist[1, 2] -= y
        elif kind == "fisheye" and len(dist) and np.any(dist):
            fx, fy = K[0, 0], K[1, 1]
            cx, cy = K[0, 2], K[1, 2]
            gx, gy = np.meshgrid(
                np.arange(w, dtype=np.float32),
                np.arange(h, dtype=np.float32), indexing="xy")
            x1 = (gx - cx) / fx
            y1 = (gy - cy) / fy
            theta = np.sqrt(x1 ** 2 + y1 ** 2)
            d = dist
            r = (1.0 + d[0] * theta ** 2 + d[1] * theta ** 4
                 + (d[2] * theta ** 6 if len(d) > 2 else 0)
                 + (d[3] * theta ** 8 if len(d) > 3 else 0))
            mapx = (fx * x1 * r + w // 2).astype(np.float32)
            mapy = (fy * y1 * r + h // 2).astype(np.float32)
            img = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR)
        # downscale
        if FACTOR > 1:
            nh = int(round(img.shape[0] / FACTOR))
            nw = int(round(img.shape[1] / FACTOR))
            img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            K_undist = K_undist.copy()
            K_undist[0] /= FACTOR
            K_undist[1] /= FACTOR
        out_name = f"{i:04d}.png"
        imageio.imwrite(os.path.join(out_dir, out_name), img)
        records.append({
            "file": out_name,
            "src_name": e["name"],
            "K": K_undist.astype(np.float32),
            "camtoworld": parsed["camtoworlds"][i],
            "orig_hw": (img.shape[0], img.shape[1]),
        })
        print(f"[prep] {e['name']} -> {out_name} {img.shape[1]}x{img.shape[0]}",
              flush=True)
    return records


# ----------------------------------------------------------------- train --
def knn(points, k):
    with torch.no_grad():
        dist = torch.cdist(points, points)
        dist.fill_diagonal_(float("inf"))
        return dist.topk(k, largest=False).values


def rgb_to_sh(rgb):
    return (rgb - 0.5) / 0.28209479177387814


def gaussian_kernel(win=11, sigma=1.5):
    x = torch.arange(win, dtype=torch.float32) - win // 2
    g = torch.exp(-x ** 2 / (2 * sigma ** 2))
    g = g / g.sum()
    k2 = torch.outer(g, g)
    return k2[None, None].repeat(3, 1, 1, 1)


def ssim_torch(x, y):
    """x,y: (1,3,H,W) in [0,1]; standard 11x11 gaussian SSIM, valid crop."""
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    k = gaussian_kernel().to(x.device)
    mu_x = F.conv2d(x, k, padding=5, groups=3)
    mu_y = F.conv2d(y, k, padding=5, groups=3)
    sx = F.conv2d(x * x, k, padding=5, groups=3) - mu_x ** 2
    sy = F.conv2d(y * y, k, padding=5, groups=3) - mu_y ** 2
    sxy = F.conv2d(x * y, k, padding=5, groups=3) - mu_x * mu_y
    ssim = ((2 * mu_x * mu_y + C1) * (2 * sxy + C2)) / (
        (mu_x ** 2 + mu_y ** 2 + C1) * (sx + sy + C2))
    return ssim.mean()


def init_splats(points, rgbs, device):
    points = torch.from_numpy(points).float().to(device)
    rgbs = torch.from_numpy(rgbs).float().to(device)
    dist2_avg = (knn(points, 4)[:, 1:] ** 2).mean(dim=-1)
    dist_avg = torch.sqrt(dist2_avg)
    scales = torch.log(dist_avg * INIT_SCALE).unsqueeze(-1).repeat(1, 3)
    N = points.shape[0]
    quats = F.normalize(torch.rand((N, 4), device=device), dim=-1)
    opacities = torch.logit(torch.full((N,), INIT_OPA, device=device))
    colors = torch.zeros((N, (SH_DEGREE + 1) ** 2, 3), device=device)
    colors[:, 0, :] = rgb_to_sh(rgbs)
    params = [
        ("means", torch.nn.Parameter(points), 1.6e-4),
        ("scales", torch.nn.Parameter(scales), 5e-3),
        ("quats", torch.nn.Parameter(quats), 1e-3),
        ("opacities", torch.nn.Parameter(opacities), 5e-2),
        ("sh0", torch.nn.Parameter(colors[:, :1, :]), 2.5e-3),
        ("shN", torch.nn.Parameter(colors[:, 1:, :]), 2.5e-3 / 20),
    ]
    splats = torch.nn.ParameterDict(
        {n: v for n, v, _ in params}).to(device)
    eps = 1e-15
    optimizers = {
        n: torch.optim.Adam(
            [{"params": splats[n], "lr": lr, "name": n}], eps=eps)
        for n, _, lr in params
    }
    return splats, optimizers


def rasterize(splats, camtoworld, K, w, h, sh_degree, near=0.01, far=1e10):
    from gsplat import rasterization
    means = splats["means"]
    quats = F.normalize(splats["quats"], dim=-1)
    scales = torch.exp(splats["scales"])
    opacities = torch.sigmoid(splats["opacities"])
    colors = torch.cat([splats["sh0"], splats["shN"]], 1)
    viewmat = torch.linalg.inv(
        torch.from_numpy(camtoworld).float().to(means.device))[None]
    Ks = torch.from_numpy(K).float().to(means.device)[None]
    renders, alphas, info = rasterization(
        means, quats, scales, opacities, colors,
        viewmats=viewmat, Ks=Ks, width=w, height=h,
        sh_degree=sh_degree, near_plane=near, far_plane=far,
        packed=False,
    )
    return renders[0], alphas[0], info


def train(splats, optimizers, records, device, scene_scale):
    from gsplat.strategy import DefaultStrategy

    scene_scale_t = torch.tensor(scene_scale, device=device)
    strategy = DefaultStrategy(
        refine_start_iter=max(100, STEPS // 10),
        refine_stop_iter=int(STEPS * 0.7),
        reset_every=max(500, STEPS // 2),
        refine_every=100,
    )
    strategy_state = strategy.initialize_state(scene_scale=scene_scale)
    scheduler = torch.optim.lr_scheduler.ExponentialLR(
        optimizers["means"], gamma=0.01 ** (1.0 / STEPS))

    train_idx = [i for i in range(len(records))
                 if i % TEST_EVERY != 0]
    val_idx = [i for i in range(len(records)) if i % TEST_EVERY == 0]
    print(f"[train] {len(train_idx)} train / {len(val_idx)} val images, "
          f"{STEPS} steps", flush=True)

    sh_interval = max(100, STEPS // 6)
    t0 = time.time()
    torch.cuda.reset_peak_memory_stats()
    for step in range(STEPS):
        i = train_idx[np.random.randint(len(train_idx))]
        rec = records[i]
        img = imageio.imread(
            os.path.join(UNDIR, rec["file"]))[..., :3]
        h, w = img.shape[:2]
        pixels = torch.from_numpy(img).float().to(device) / 255.0
        sh_deg = min(step // sh_interval, SH_DEGREE)
        renders, _, info = rasterize(
            splats, rec["camtoworld"], rec["K"], w, h, sh_deg)
        colors = torch.clamp(renders, 0.0, 1.0)

        strategy.step_pre_backward(
            params=splats, optimizers=optimizers,
            state=strategy_state, step=step, info=info)

        l1 = F.l1_loss(colors, pixels)
        ssim = ssim_torch(
            colors.permute(2, 0, 1)[None],
            pixels.permute(2, 0, 1)[None])
        loss = l1 * 0.8 + (1.0 - ssim) * 0.2
        loss.backward()
        for opt in optimizers.values():
            opt.step()
            opt.zero_grad(set_to_none=True)
        scheduler.step()
        strategy.step_post_backward(
            params=splats, optimizers=optimizers,
            state=strategy_state, step=step, info=info)

        if step % 250 == 0 or step == STEPS - 1:
            n = len(splats["means"])
            mem = torch.cuda.max_memory_allocated() / 1e9
            print(f"[train] step {step}/{STEPS} loss={loss.item():.4f} "
                  f"l1={l1.item():.4f} ssim={ssim.item():.4f} "
                  f"GS={n} vram={mem:.1f}GB "
                  f"({(time.time() - t0) / (step + 1):.2f}s/it)",
                  flush=True)
    return val_idx, time.time() - t0


def evaluate(splats, records, val_idx, device):
    psnrs, ssims = [], []
    for i in val_idx:
        rec = records[i]
        img = imageio.imread(
            os.path.join(UNDIR, rec["file"]))[..., :3]
        h, w = img.shape[:2]
        pixels = torch.from_numpy(img).float().to(device) / 255.0
        with torch.no_grad():
            renders, _, _ = rasterize(
                splats, rec["camtoworld"], rec["K"], w, h, SH_DEGREE)
            colors = torch.clamp(renders, 0.0, 1.0)
            mse = F.mse_loss(colors, pixels).item()
            psnr = 10 * math.log10(1.0 / max(mse, 1e-10))
            ssim = ssim_torch(
                colors.permute(2, 0, 1)[None],
                pixels.permute(2, 0, 1)[None]).item()
        psnrs.append(psnr)
        ssims.append(ssim)
        print(f"[eval] val {rec['src_name']}: PSNR={psnr:.2f} "
              f"SSIM={ssim:.4f}", flush=True)
    return {
        "psnr_mean": float(np.mean(psnrs)) if psnrs else None,
        "psnr_per_image": psnrs,
        "ssim_mean": float(np.mean(ssims)) if ssims else None,
        "ssim_per_image": ssims,
        "val_indices": val_idx,
    }


# ---------------------------------------------------------------- orbit --
def render_orbit(splats, scene_scale, device):
    """Turntable orbit around the normalized (z-up) scene."""
    from gsplat import rasterization

    means = splats["means"].detach()
    quats = F.normalize(splats["quats"].detach(), dim=-1)
    scales = torch.exp(splats["scales"].detach())
    opacities = torch.sigmoid(splats["opacities"].detach())
    colors = torch.cat(
        [splats["sh0"].detach(), splats["shN"].detach()], 1)

    center = means.median(dim=0).values
    dist = (means - center).norm(dim=1)
    r90 = float(torch.quantile(dist, 0.9).item())
    radius = max(r90 * 1.9, scene_scale * 0.9)

    fy = ORBIT_H / (2.0 * math.tan(math.radians(42) / 2.0))
    Ks = torch.tensor(
        [[[fy, 0.0, ORBIT_W / 2.0], [0.0, fy, ORBIT_H / 2.0],
          [0.0, 0.0, 1.0]]], device=device, dtype=torch.float32)

    up = torch.tensor([0.0, 0.0, 1.0], device=device)
    a = torch.tensor([1.0, 0.0, 0.0], device=device)
    e1 = F.normalize(torch.cross(up, a), dim=0)
    e2 = torch.cross(up, e1)
    el = math.radians(15.0)
    cel, sel = math.cos(el), math.sin(el)

    def look_at(eye, target):
        f = F.normalize(target - eye, dim=0)
        r = F.normalize(torch.cross(f, up), dim=0)
        d = torch.cross(f, r)
        R = torch.stack([r, d, f])
        V = torch.eye(4, device=device)
        V[:3, :3] = R
        V[:3, 3] = -R @ eye
        return V[None]

    def eye_at(theta):
        return center + radius * (
            cel * (math.cos(theta) * e1 + math.sin(theta) * e2)
            + sel * up)

    writer = imageio.get_writer(
        f"{OUT}/{PACK_NAME}.mp4", fps=24,
        codec="libx264", quality=8)
    first = None
    for i in range(ORBIT_FRAMES):
        theta = i / ORBIT_FRAMES * 2.0 * math.pi
        view = look_at(eye_at(theta), center)
        renders, _, _ = rasterization(
            means, quats, scales, opacities, colors,
            viewmats=view, Ks=Ks, width=ORBIT_W, height=ORBIT_H,
            sh_degree=SH_DEGREE, packed=False)
        frame = torch.clamp(renders[0], 0.0, 1.0)
        arr = (frame.detach().cpu().numpy() * 255).astype("uint8")
        if first is None:
            first = arr.copy()
            imageio.imwrite(f"{OUT}/{PACK_NAME}.png", arr)
        writer.append_data(arr)
    writer.close()
    return first is not None


# ------------------------------------------------------------------ main --
UNDIR = None  # set in main; used by train/evaluate


def main():
    global UNDIR
    t_all = time.time()
    device = "cuda"
    if not torch.cuda.is_available():
        raise RuntimeError(f"{PACK_NAME} requires a CUDA GPU")

    work = tempfile.mkdtemp(prefix="gsrecon-")
    img_dir = os.path.join(work, "images")
    os.makedirs(img_dir, exist_ok=True)
    srcs = sorted(glob.glob(os.path.join(IMG_SRC, "*.jpg"))
                  + glob.glob(os.path.join(IMG_SRC, "*.png"))
                  + glob.glob(os.path.join(IMG_SRC, "*.jpeg")))
    if not srcs:
        raise RuntimeError(f"no images found under {IMG_SRC}")
    for i, s in enumerate(srcs):
        ext = os.path.splitext(s)[1].lower()
        shutil.copy(s, os.path.join(
            img_dir, f"frame_{i:03d}{ext}"))
    print(f"[stage] {len(srcs)} images -> {img_dir}", flush=True)

    t_colmap = time.time()
    recon, _ = run_colmap(img_dir, work)
    colmap_s = time.time() - t_colmap

    parsed = parse_reconstruction(recon)
    print(f"[parse] {len(parsed['entries'])} images, "
          f"{len(parsed['points'])} points, "
          f"scene_scale={parsed['scene_scale']:.3f}", flush=True)

    UNDIR = os.path.join(work, "undistorted")
    records = build_undistorted_images(parsed, img_dir, UNDIR)

    if not len(parsed["points"]):
        raise RuntimeError("COLMAP produced no 3D points — cannot init GS")

    splats, optimizers = init_splats(
        parsed["points"], parsed["points_rgb"] / 255.0, device)
    # scale means lr by scene scale like the example does
    for opt in optimizers.values():
        for g in opt.param_groups:
            if g.get("name") == "means":
                g["lr"] = 1.6e-4 * parsed["scene_scale"]
    print(f"[init] {len(splats['means'])} gaussians", flush=True)

    val_idx, train_s = train(
        splats, optimizers, records, device, parsed["scene_scale"])
    metrics = evaluate(splats, records, val_idx, device)

    # export PLY — export_splats wants the raw parameterization:
    # log-space scales, logit opacities, (w,x,y,z) quats, sh0 (N,1,3),
    # shN (N,K,3); it flattens shN channel-major = f_rest order that
    # gaussian-splat-ply-orbit's render_ply.py reads back.
    from gsplat import export_splats
    ply_path = f"{OUT}/{PACK_NAME}.ply"
    export_splats(
        splats["means"].detach(),
        splats["scales"].detach(),
        F.normalize(splats["quats"].detach(), dim=-1),
        splats["opacities"].detach(),
        splats["sh0"].detach(),
        splats["shN"].detach(),
        format="ply", save_to=ply_path)
    ply_mb = os.path.getsize(ply_path) / 1e6

    orbit_ok = render_orbit(splats, parsed["scene_scale"], device)

    vram_gb = torch.cuda.max_memory_allocated() / 1e9
    wall_s = time.time() - t_all
    num_gs = int(len(splats["means"]))

    metrics.update({
        "pack": PACK_NAME,
        "dataset": IMG_SRC,
        "num_images": len(records),
        "num_train": len(records) - len(val_idx),
        "num_val": len(val_idx),
        "factor": FACTOR,
        "steps": STEPS,
        "sh_degree": SH_DEGREE,
        "colmap": {
            "reg_images": int(recon.num_reg_images()),
            "points3D": int(recon.num_points3D()),
            "num_cameras": int(recon.num_cameras()),
            "seconds": round(colmap_s, 1),
        },
        "final_num_gaussians": num_gs,
        "train_seconds": round(train_s, 1),
        "sec_per_step": round(train_s / STEPS, 3),
        "peak_cuda_gb": round(vram_gb, 3),
        "device": torch.cuda.get_device_name(0),
        "ply_mb": round(ply_mb, 1),
        "orbit_rendered": orbit_ok,
        "wall_seconds_total": round(wall_s, 1),
    })
    with open(f"{PACK_DIR}/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    md = [
        "# gaussian-splat-hibiscus-recon — photo to 3DGS PLY",
        "",
        f"- dataset: `{IMG_SRC}` ({len(records)} images, factor {FACTOR})",
        f"- COLMAP: {recon.num_reg_images()} registered images, "
        f"{recon.num_points3D():,} sparse points "
        f"({colmap_s:.0f}s)",
        f"- training: {STEPS} steps, final {num_gs:,} Gaussians "
        f"({train_s:.0f}s, {train_s / STEPS * 1000:.0f} ms/step)",
        f"- eval (held-out): PSNR {metrics['psnr_mean']:.2f} dB, "
        f"SSIM {metrics['ssim_mean']:.4f}"
        if metrics["psnr_mean"] is not None else "- eval: n/a",
        f"- peak CUDA: {vram_gb:.2f} GB on {torch.cuda.get_device_name(0)}",
        f"- wall time: {wall_s:.0f}s",
        "",
        "Artifacts: `out/gaussian-splat-hibiscus-recon.ply`, "
        "`.mp4` (orbit), `.png` (still), `metrics.json`.",
        "",
        "Pipeline: pycolmap SIFT+exhaustive+incremental mapping -> "
        "gsplat rasterization training (L1+SSIM, DefaultStrategy) -> "
        "export_splats PLY. World normalized z-up; orbit rendered "
        "directly from trained splats.",
    ]
    with open(f"{PACK_DIR}/report.md", "w") as f:
        f.write("\n".join(md) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)
    print(f"[done] {PACK_NAME} in {wall_s:.0f}s", flush=True)


if __name__ == "__main__":
    main()
