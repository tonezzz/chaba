#!/usr/bin/env python3
"""CPU-only NASA still + starfield + parallax proof for Earth and Saturn."""
from pathlib import Path
import math
import os
import random
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(os.environ.get('NASA_2P5D_ROOT', Path(__file__).resolve().parent))
ASSETS = ROOT / 'assets'
FRAMES = ROOT / 'frames'
FRAMES.mkdir(parents=True, exist_ok=True)
W, H, FPS = 640, 384, 24
SCENE_FRAMES, GAP_FRAMES = 73, 7
FONT_TH = '/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf'
FONT_EN = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

SCENES = [
    {
        'file': 'earth-blue-marble.jpg',
        'slug': 'earth',
        'title': 'โลก',
        'caption': 'นี่คือบ้านของเรา โลกสีฟ้าใบเล็ก',
        'credit': 'Image: NASA Goddard',
        'glow': (35, 110, 255),
        'seed': 1101,
    },
    {
        'file': 'saturn-cassini-pia06193.jpg',
        'slug': 'saturn',
        'title': 'ดาวเสาร์',
        'caption': 'ดาวเสาร์ เจ้าแห่งวงแหวนอันงดงาม',
        'credit': 'Image: NASA/JPL/Space Science Institute',
        'glow': (255, 182, 78),
        'seed': 1111,
    },
]


def starfield(seed, glow_color):
    yy, xx = np.mgrid[0:H, 0:W]
    x = (xx - W * 0.51) / (W * 0.72)
    y = (yy - H * 0.48) / (H * 0.78)
    radial = np.exp(-(x * x + y * y) * 2.1)
    base = np.zeros((H, W, 3), dtype=np.float32)
    base[:, :, 0] = 2 + radial * glow_color[0] * 0.045
    base[:, :, 1] = 4 + radial * glow_color[1] * 0.06
    base[:, :, 2] = 13 + radial * glow_color[2] * 0.075
    img = Image.fromarray(np.uint8(np.clip(base, 0, 255)), 'RGB').convert('RGBA')
    draw = ImageDraw.Draw(img, 'RGBA')
    rng = random.Random(seed)
    for _ in range(155):
        x, y = rng.randrange(W), rng.randrange(H - 75)
        a = rng.randrange(70, 190)
        r = 1 if rng.random() < 0.94 else 2
        draw.ellipse((x-r, y-r, x+r, y+r), fill=(190, 213, 255, a))
    return img


def source_layer(path):
    src = Image.open(path).convert('RGB')
    # Reserve a clean lower-third band instead of covering the planet/rings.
    plate_h = H - 84
    src.thumbnail((W - 40, plate_h - 6), Image.Resampling.LANCZOS)
    rgb = np.asarray(src, dtype=np.uint8)
    peak = rgb.max(axis=2).astype(np.float32)
    # The downloaded plates use near-black space; preserve dark planetary
    # detail while making only the black surround transparent.
    alpha = np.clip((peak - 3.0) * 24.0, 0, 255).astype(np.uint8)
    rgba = np.dstack((rgb, alpha))
    plate = Image.new('RGBA', (W, plate_h), (0, 0, 0, 0))
    plate.paste(Image.fromarray(rgba, 'RGBA'),
                ((W - src.width) // 2, (plate_h - src.height) // 2))
    return plate


def centered_zoom(layer, zoom, dx, center_y):
    sw = int(layer.width * zoom)
    sh = int(layer.height * zoom)
    large = layer.resize((sw, sh), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    out.alpha_composite(
        large, ((W - sw) // 2 + dx, round(center_y - sh / 2)))
    return out


def compose(scene, plate, frame_idx):
    t = frame_idx / max(1, SCENE_FRAMES - 1)
    zoom = 1.005 + 0.035 * t
    dx = round(-4 + 8 * t)
    bg = starfield(scene['seed'], scene['glow'])

    mask = plate.getchannel('A').filter(ImageFilter.GaussianBlur(22))
    mask = mask.point(lambda a: int(a * 0.18))
    glow = Image.new('RGBA', plate.size, scene['glow'] + (0,))
    glow.putalpha(mask)
    bg = Image.alpha_composite(bg, centered_zoom(glow, zoom, dx, 150))
    bg = Image.alpha_composite(bg, centered_zoom(plate, zoom, dx, 150))

    # A quiet lower third carries Thai narration and an exact source credit.
    panel = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel, 'RGBA')
    draw.rectangle((0, H - 73, W, H), fill=(1, 4, 12, 205))
    title_font = ImageFont.truetype(FONT_TH, 23)
    credit_font = ImageFont.truetype(FONT_EN, 12)
    draw.text((24, H - 69), scene['title'], font=title_font,
              fill=(117, 190, 255, 255), stroke_width=1,
              stroke_fill=(0, 0, 0, 180))
    draw.text((24, H - 39), scene['caption'], font=title_font,
              fill=(247, 249, 255, 255), stroke_width=1,
              stroke_fill=(0, 0, 0, 200))
    draw.text((24, H - 14), scene['credit'], font=credit_font,
              fill=(195, 204, 220, 255))
    return Image.alpha_composite(bg, panel).convert('RGB')


out_idx = 0
for scene in SCENES:
    plate = source_layer(ASSETS / scene['file'])
    last = None
    for i in range(SCENE_FRAMES):
        frame = compose(scene, plate, i)
        frame.save(FRAMES / f'frame-{out_idx:04d}.png', compress_level=1)
        out_idx += 1
        last = frame
    if scene['slug'] == 'earth':
        for _ in range(GAP_FRAMES):
            last.save(FRAMES / f'frame-{out_idx:04d}.png', compress_level=1)
            out_idx += 1

# Contact sheet: first and last frame from each scene for review.
thumbs = []
for i in (0, SCENE_FRAMES - 1, SCENE_FRAMES + GAP_FRAMES,
          SCENE_FRAMES + GAP_FRAMES + SCENE_FRAMES - 1):
    im = Image.open(FRAMES / f'frame-{i:04d}.png').resize((320, 192))
    thumbs.append(im)
sheet = Image.new('RGB', (640, 384), (0, 0, 0))
for i, im in enumerate(thumbs):
    sheet.paste(im, ((i % 2) * 320, (i // 2) * 192))
sheet.save(ROOT / 'contact-sheet.jpg', quality=90)

video = ROOT / 'visuals-silent.mp4'
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
    '-framerate', str(FPS), '-i', str(FRAMES / 'frame-%04d.png'),
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19',
    '-pix_fmt', 'yuv420p', '-r', str(FPS), str(video)
], check=True)
print(f'frames={out_idx} duration={out_idx/FPS:.3f}s '
      f'video={video.stat().st_size} bytes', flush=True)
