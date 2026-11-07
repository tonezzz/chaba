#!/usr/bin/env python3
"""doc-static-final-v3 — CPU 2.5D assembler for the v3 tourist-ship cut.

Card: doc-pilot-v3-tourist-cut (OPS-0904). Rebuilds the 18-shot private
review cut entirely on CPU: NASA stills keyed/full-bleed with a subtle
zoom (2.5D), recurring unbranded ship silhouette, cockpit-window edge on
POV shots, Thai fact callouts, burned Thai subtitles + mov_text + SRT.

Shots 8-9 use rights-checked NASA stills (PIA04866, PIA21772) as the
approved static fallback while the LTX dynamic renders wait for a safe
GPU lane; per-shot assets remain replaceable later.

Inputs expected under work dir (see pack.yml):
  vo/v3-vo-01..18.wav      measured VO clips (24 kHz s16)
  vo/vo-manifest-v3.json   per-shot durations/text
  assets/...               NASA plates + ship PNG + window PNG
Outputs:
  out/v3-static-final-v1.mp4  (H.264/AAC + mov_text, 640x384@24)
  out/subtitles-th-v3-static-final-v1.srt
  out/v3-static-final-v1-report.md
"""
import json, math, os, subprocess, sys, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 640, 384
BG_W, BG_H = 1280, 768          # 2x supersample plate for zoom headroom
FPS = 24
SLATE_S = 2.0
FONT = "/usr/share/fonts/opentype/tlwg/Loma.otf"
FONT_B = "/usr/share/fonts/opentype/tlwg/Loma-Bold.otf"

# ---------------------------------------------------------------- shots
# fact lines come verbatim from the approved script callouts; title/credit
# lines document the plate used.  method: disk (keyed planet on black),
# full (full-bleed plate), scene (procedural), none (stars only)
SHOTS = [
 dict(n=1, method="stars", ship=(0.58, 0.66, 1.30), window=True,
      zoom="in",
      callout=None),
 dict(n=2, method="full", img="earth-blue-marble.jpg",
      ship=(0.80, 0.72, 0.34), zoom="out",
      callout=dict(title="โลก",
        lines=["จากดวงอาทิตย์เฉลี่ย 1.00 AU (149.6 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 12,756 กม."],
        credit="NASA Goddard")),
 dict(n=3, method="disk", img="PIA00405-Moon-Galileo-Natural.jpg",
      scale=0.62, pos=(0.68, 0.52), glow=(200, 200, 210),
      ship=(0.16, 0.70, 0.30), zoom="in",
      callout=dict(title="ดวงจันทร์",
        lines=["ห่างจากโลกเฉลี่ย 384,400 กม.",
               "เส้นผ่านศูนย์กลาง 3,475 กม."],
        credit="NASA/JPL/USGS (Galileo)")),
 dict(n=4, method="disk", img="PIA26681-Sun-SDO.jpg",
      scale=0.80, pos=(0.66, 0.52), glow=(255, 150, 40), glow_big=1.9,
      ship=(0.10, 0.74, 0.26), zoom="in",
      callout=dict(title="ดวงอาทิตย์",
        lines=["ดาวฤกษ์ศูนย์กลาง",
               "เส้นผ่านศูนย์กลางประมาณ 1.39 ล้าน กม.",
               "(ภาพจากระยะปลอดภัย)"],
        credit="NASA/GSFC/SDO")),
 dict(n=5, method="full", img="PIA18108-Mercury-Three-Color-Mosaic.jpg",
      ship=(0.78, 0.70, 0.34), zoom="in",
      callout=dict(title="ดาวพุธ",
        lines=["0.387 AU (57.9 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 4,879 กม.",
               "ภาพโมเสกสีปรับแต่ง"],
        credit="NASA/JHUAPL/CIW")),
 dict(n=6, method="disk", img="PIA23791-Venus-Mariner10.jpg",
      crop="right_disk", scale=0.60, pos=(0.68, 0.50),
      glow=(235, 205, 160),
      ship=(0.14, 0.68, 0.30), zoom="in",
      callout=dict(title="ดาวศุกร์",
        lines=["0.723 AU (108.2 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 12,104 กม.",
               "ร้อนที่สุดในระบบสุริยะ"],
        credit="NASA/JPL-Caltech (Mariner 10)")),
 dict(n=7, method="disk", img="GSFC-e000332-Mars-Hubble.jpg",
      scale=0.58, pos=(0.66, 0.52), glow=(230, 120, 80),
      ship=(0.15, 0.71, 0.32), zoom="in",
      callout=dict(title="ดาวอังคาร",
        lines=["1.524 AU (228.0 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 6,792 กม."],
        credit="NASA, ESA/Hubble")),
 dict(n=8, method="disk", img="PIA04866-Jupiter-Cassini.jpg",
      scale=0.76, pos=(0.66, 0.56), glow=(210, 180, 150),
      ship=(0.13, 0.72, 0.34), zoom="in",
      callout=dict(title="ดาวพฤหัสบดี",
        lines=["5.203 AU (778.5 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 142,984 กม."],
        credit="NASA/JPL/SSI (Cassini)")),
 dict(n=9, method="full", img="PIA21772-GRS-JunoCam-Closeup.jpg",
      ship=(0.80, 0.74, 0.32), zoom="in",
      callout=dict(title="จุดแดงใหญ่",
        lines=["พายุกว้างกว่าโลก",
               "ยังคงเปลี่ยนรูปและขนาด",
               "ภาพปรับสี JunoCam"],
        credit="NASA/JPL-Caltech/SwRI/MSSS/J. Major")),
 dict(n=10, method="disk", img="saturn-cassini-pia06193.jpg",
      scale=0.88, pos=(0.60, 0.54), glow=(220, 200, 170),
      ship=(0.78, 0.72, 0.34), zoom="in",
      callout=dict(title="ดาวเสาร์",
        lines=["9.58 AU (1,432 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 120,536 กม."],
        credit="NASA/JPL/SSI")),
 dict(n=11, method="full", img="saturn-cassini-pia06193.jpg",
      crop="rings", ship=(0.80, 0.75, 0.30), zoom="in",
      callout=dict(title="วงแหวนดาวเสาร์",
        lines=["องค์ประกอบ",
               "อนุภาคน้ำแข็งและหิน"],
        credit="NASA/JPL/SSI")),
 dict(n=12, method="disk", img="PIA18182-Uranus-Voyager2.jpg",
      scale=0.72, pos=(0.64, 0.54), glow=(150, 210, 210),
      ship=(0.15, 0.70, 0.30), zoom="in",
      callout=dict(title="ดาวยูเรนัส",
        lines=["19.2 AU (2,867 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 51,118 กม."],
        credit="NASA/JPL-Caltech (Voyager 2)")),
 dict(n=13, method="disk", img="PIA00046-Neptune-Full-Disk.jpg",
      scale=0.72, pos=(0.64, 0.54), glow=(80, 130, 220),
      ship=(0.15, 0.70, 0.30), zoom="in",
      callout=dict(title="ดาวเนปจูน",
        lines=["30.2 AU (4,515 ล้าน กม.)",
               "เส้นผ่านศูนย์กลาง 49,528 กม."],
        credit="NASA/JPL (Voyager 2)")),
 dict(n=14, method="disk", img="PIA20291-Pluto-Color.jpg",
      scale=0.66, pos=(0.64, 0.54), glow=(215, 190, 160),
      ship=(0.15, 0.71, 0.30), zoom="in",
      callout=dict(title="พลูโต",
        lines=["ดาวเคราะห์แคระ",
               "39.5 AU (5,906 ล้าน กม.)",
               "เส้นผ่านศูนย์กลางประมาณ 2,377 กม."],
        credit="NASA/JHUAPL/SwRI (New Horizons)")),
 dict(n=15, method="scene", scene="kuiper",
      ship=(0.80, 0.74, 0.30), zoom="in",
      callout=dict(title="แถบไคเปอร์",
        lines=["แถบหลักราว 30-50 AU",
               "คาดว่ามีวัตถุน้ำแข็งนับล้าน",
               "(แผนผัง ไม่ใช่ภาพถ่าย)"])),
 dict(n=16, method="scene", scene="scalemap",
      ship=(0.82, 0.76, 0.30), zoom="none",
      callout=dict(title="แผนที่สเกล",
        lines=["ระยะเฉลี่ยบอกสเกล",
               "ภาพแผนที่ไม่ได้วาดตามสเกล"])),
 dict(n=17, method="pbd", img="PIA00452-Pale-Blue-Dot.jpg",
      ship=(0.16, 0.72, 0.30), window=True, zoom="in",
      callout=dict(title="จุดสีฟ้าอ่อน",
        lines=["มุมมองจากไกลแสนไกล",
               "โลกเป็นจุดเล็กในอวกาศ",
               "(วงกลมชี้ตำแหน่งโดยประมาณ)"],
        credit="NASA/JPL (Voyager 1)")),
 dict(n=18, method="full", img="earth-blue-marble.jpg",
      warm=True, ship=(0.76, 0.68, 0.42), zoom="in",
      callout=None),
]

NASA = None        # set in main
SUB_TEXT = {}      # filled from manifest

# ------------------------------------------------------------ draw utils
def font(sz, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, sz,
                              layout_engine=ImageFont.Layout.RAQM)

def starfield(seed=7, w=BG_W, h=BG_H, n=240):
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (w, h), (4, 6, 16))
    d = ImageDraw.Draw(im)
    for _ in range(n):
        x, y = rng.integers(0, w), rng.integers(0, h)
        b = int(rng.integers(60, 220))
        r = 1 if rng.random() < 0.85 else 2
        d.ellipse([x-r, y-r, x+r, y+r], fill=(b, b, min(255, b+20)))
    return im.filter(ImageFilter.GaussianBlur(0.4))

def glow_blob(size, color, strength=170):
    """Radial alpha gradient (no square edges)."""
    r = np.linspace(-1, 1, size)
    yy, xx = np.meshgrid(r, r, indexing="ij")
    a = np.clip(1 - np.sqrt(xx*xx + yy*yy), 0, 1) ** 1.6
    return Image.fromarray((a*strength).astype(np.uint8), "L")

def key_disk(img, thresh=16):
    """Return RGBA crop of planet disk keyed off its black background."""
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    lum = a.max(2)
    mask = (lum > thresh).astype(np.uint8)*255
    m = Image.fromarray(mask, "L").filter(ImageFilter.GaussianBlur(1.2))
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return img.convert("RGBA")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pad = 6
    x0, y0 = max(0, x0-pad), max(0, y0-pad)
    x1, y1 = min(img.width, x1+pad), min(img.height, y1+pad)
    out = img.convert("RGBA").crop((x0, y0, x1, y1))
    out.putalpha(m.crop((x0, y0, x1, y1)))
    return out

def cover(img, w=BG_W, h=BG_H):
    s = max(w/img.width, h/img.height)
    im = img.resize((int(img.width*s+0.5), int(img.height*s+0.5)),
                    Image.LANCZOS)
    x = (im.width-w)//2
    y = (im.height-h)//2
    return im.crop((x, y, x+w, y+h))

def rounded(draw, box, rad, **kw):
    draw.rounded_rectangle(box, radius=rad, **kw)

def th(draw, xy, text, size, fill, bold=False, anchor="la"):
    draw.text(xy, text, font=font(size, bold), fill=fill, anchor=anchor)

# ------------------------------------------------------------- bg scenes
def scene_kuiper():
    im = starfield(seed=15)
    d = ImageDraw.Draw(im, "RGBA")
    cx, cy = int(BG_W*0.30), int(BG_H*0.55)
    # sun dot
    d.ellipse([cx-16, cy-16, cx+16, cy+16], fill=(255, 210, 120, 255))
    # neptune orbit
    for rx, ry, col in [(210, 90, (90, 130, 190, 160)),
                        (430, 185, (120, 190, 230, 200))]:
        d.ellipse([cx-rx, cy-ry, cx+rx, cy+ry], outline=col, width=3)
    # icy bodies beyond neptune orbit (schematic, sparse)
    rng = np.random.default_rng(3)
    for _ in range(70):
        t = rng.uniform(0, 2*math.pi)
        rad = rng.uniform(1.0, 1.45)
        x = cx + math.cos(t)*430*rad*0.9
        y = cy + math.sin(t)*185*rad
        b = int(rng.integers(160, 255))
        r = 2 if rng.random() < 0.75 else 3
        d.ellipse([x-r, y-r, x+r, y+r],
                  fill=(b//2+90, b//2+95, b+25, 255))
    # belt band highlight
    d.ellipse([cx-430*1.06, cy-185*1.06, cx+430*1.06, cy+185*1.06],
              outline=(150, 220, 255, 90), width=10)
    return im

def scene_scalemap():
    im = starfield(seed=16)
    d = ImageDraw.Draw(im, "RGBA")
    y = int(BG_H*0.52)
    names = ["ดวงอาทิตย์", "พุธ", "ศุกร์", "โลก", "อังคาร",
             "พฤหัส", "เสาร์", "ยูเรนัส", "เนปจูน", "พลูโต"]
    xs = [90, 195, 305, 420, 540, 660, 780, 900, 1020, 1150]
    d.line([70, y, 1210, y], fill=(120, 170, 220, 200), width=4)
    for i, (x, nm) in enumerate(zip(xs, names)):
        if i == 0:
            d.ellipse([x-34, y-34, x+34, y+34],
                      fill=(255, 200, 90, 255))
        else:
            d.line([x, y-14, x, y+14], fill=(255, 210, 110, 255), width=5)
            d.ellipse([x-11, y-11, x+11, y+11],
                      fill=(255, 215, 130, 255))
        f = font(24 if i == 0 else 22)
        tw = d.textlength(nm, font=f)
        d.text((x-tw/2, y+38), nm, font=f, fill=(230, 235, 245, 255))
    return im

def build_bg(spec):
    n = spec["n"]
    m = spec["method"]
    if m == "stars":
        im = starfield()
    elif m == "full":
        p = NASA / spec["img"]
        img = Image.open(p).convert("RGB")
        if spec.get("crop") == "rings":
            # zoom into the ring plane region of the Cassini portrait
            w0, h0 = img.size
            img = img.crop((int(w0*0.15), int(h0*0.30),
                            int(w0*0.85), int(h0*0.58)))
        img = cover(img)
        if spec.get("warm"):
            ov = Image.new("RGB", img.size, (0, 0, 0))
            ov.paste((255, 140, 60),
                     (0, int(BG_H*0.72), BG_W, BG_H))
            ov = ov.filter(ImageFilter.GaussianBlur(90))
            img = Image.blend(img, Image.composite(
                ov, img, ov.convert("L").point(lambda v: v//3)), 0.5)
        im = img
    elif m == "disk":
        img = Image.open(NASA / spec["img"]).convert("RGB")
        if spec.get("crop") == "right_disk":
            img = img.crop((img.width//2+12, 0, img.width, img.height))
        disk = key_disk(img)
        s = spec["scale"] * BG_H / disk.height
        disk = disk.resize((int(disk.width*s), int(disk.height*s)),
                           Image.LANCZOS)
        im = starfield(seed=40+n)
        gb = glow_blob(int(disk.width*spec.get("glow_big", 1.35)),
                       spec["glow"])
        im.paste(spec["glow"], (int(spec["pos"][0]*BG_W-gb.width/2),
                                int(spec["pos"][1]*BG_H-gb.height/2)),
                 gb)
        im.paste(disk, (int(spec["pos"][0]*BG_W-disk.width/2),
                        int(spec["pos"][1]*BG_H-disk.height/2)), disk)
    elif m == "scene":
        im = scene_kuiper() if spec["scene"] == "kuiper" else \
             scene_scalemap()
    elif m == "pbd":
        img = Image.open(NASA / spec["img"]).convert("RGB")
        # lift shadows so the scattered-light bands read at 640x384
        a = np.asarray(img, dtype=np.float32) / 255.0
        img = Image.fromarray(
            (np.power(a, 0.55)*255).astype(np.uint8))
        s = BG_H / img.height
        img = img.resize((int(img.width*s), BG_H), Image.LANCZOS)
        im = starfield(seed=17)
        ox = int(BG_W*0.60)
        im.paste(img, (ox, 0))
        d = ImageDraw.Draw(im, "RGBA")
        # dot marker: source (344,344) * scale
        ds = BG_H / 614.0
        mx, my = ox + int(344*ds), int(344*ds)
        r = 30
        for k in range(3):
            d.ellipse([mx-r-k*6, my-r-k*6, mx+r+k*6, my+r+k*6],
                      outline=(150, 220, 255, 200-k*60), width=4)
        d.line([mx-r-90, my-80, mx-r-14, my-14],
               fill=(150, 220, 255, 220), width=4)
        th(d, (mx-r-96, my-118), "โลก", 34, (200, 235, 255, 255), True)
    else:
        raise ValueError(m)
    return im.convert("RGB")

# ------------------------------------------------------------- fg layer
def build_fg(spec, idx, total):
    fg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    co = spec.get("callout")
    if co:
        lines = co["lines"]
        bh = 34 + 22*len(lines) + (20 if co.get("credit") else 6)
        rounded(d, (14, 14, 264, 14+bh), 10,
                fill=(7, 15, 42, 218), outline=(120, 160, 210, 200),
                width=1)
        th(d, (26, 20), co["title"], 24, (255, 205, 110, 255), True)
        yy = 52
        for ln in lines:
            th(d, (26, yy), ln, 16, (235, 240, 248, 255))
            yy += 22
        if co.get("credit"):
            th(d, (26, yy+2), "Credit: "+co["credit"], 12,
               (150, 160, 180, 255))
    # ship
    sx, sy, ss = spec["ship"]
    ship = SHIP.resize((int(SHIP.width*ss), int(SHIP.height*ss)),
                       Image.LANCZOS)
    fg.paste(ship, (int(sx*W-ship.width/2),
                    int(sy*H-ship.height/2)), ship)
    # cockpit window edge (POV shots)
    if spec.get("window"):
        fg.paste(WINDOW, (0, 0), WINDOW)
    # subtitle bar
    txt = SUB_TEXT.get(spec["n"], "")
    if txt:
        rounded(d, (12, H-56, W-12, H-12), 10,
                fill=(7, 15, 42, 222), outline=(120, 160, 210, 160),
                width=1)
        f = font(19)
        tw = d.textlength(txt, font=f)
        d.text(((W-tw)/2, H-48), txt, font=f, fill=(240, 244, 250, 255))
    # frame border
    rounded(d, (6, 6, W-6, H-6), 12, outline=(110, 150, 200, 150),
            width=2)
    # privacy tag
    th(d, (W-20, 12), "PRIVATE REVIEW", 11, (255, 190, 90, 220),
       anchor="ra")
    return fg

def build_slate(title, lines):
    bg = starfield(seed=99).resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(bg, "RGBA")
    f = font(30, True)
    tw = d.textlength(title, font=f)
    d.text(((W-tw)/2, H*0.30), title, font=f,
           fill=(255, 205, 110, 255))
    yy = int(H*0.30)+56
    for ln in lines:
        f2 = font(16)
        tw = d.textlength(ln, font=f2)
        d.text(((W-tw)/2, yy), ln, font=f2, fill=(225, 232, 242, 255))
        yy += 26
    rounded(d, (6, 6, W-6, H-6), 12, outline=(110, 150, 200, 150),
            width=2)
    th(d, (W-20, 12), "PRIVATE REVIEW", 11, (255, 190, 90, 220),
       anchor="ra")
    return bg

# ----------------------------------------------------------------- ffmpeg
def render_scene(bg_png, fg_png, dur, out, zoom="in"):
    frames = int(round(dur*FPS))
    if zoom == "in":
        z = "'1+0.055*on/%d'" % frames
    elif zoom == "out":
        z = "'1.055-0.055*on/%d'" % frames
    else:
        z = "1"
    filt = (f"[0:v]zoompan=z={z}:x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}[b];"
            f"[b][1:v]overlay=0:0[v]")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-i", str(bg_png), "-i", str(fg_png),
        "-filter_complex", filt, "-map", "[v]",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", str(out)], check=True)

def srt_ts(t):
    ms = int(round(t*1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main(root):
    global NASA, SHIP, WINDOW
    root = Path(root)
    NASA = root/"assets"
    SHIP = Image.open(root/"assets/tour-ship-silhouette-v1.png")\
              .convert("RGBA")
    WINDOW = Image.open(root/"assets/cockpit-window-frame-v1.png")\
                .convert("RGBA")
    man = json.loads((root/"vo/vo-manifest-v3.json").read_text())
    durs, order = [], []
    for sh in man["shots"]:
        SUB_TEXT[sh["shot"]] = sh["text_th"]
        durs.append(sh["duration_s"])
        order.append(sh["shot"])
    assert order == list(range(1, 19)), order
    work = root/"render"; work.mkdir(exist_ok=True)
    outdir = root/"out"; outdir.mkdir(exist_ok=True)

    scene_files, report_rows = [], []
    def slate(name, title, lines):
        p = work/f"{name}.png"; p2 = work/f"{name}.mp4"
        build_slate(title, lines).save(p)
        subprocess.run(["ffmpeg", "-v", "error", "-y",
                        "-loop", "1", "-t", str(SLATE_S), "-i", str(p),
                        "-c:v", "libx264", "-preset", "medium",
                        "-crf", "20", "-pix_fmt", "yuv420p",
                        "-vf", f"fps={FPS}", str(p2)], check=True)
        return p2

    scene_files.append(slate(
        "title", "ระบบสุริยะ — ทัวร์ยานอวกาศ",
        ["เรื่องเล่าสำหรับ KK", "เสียงบรรยาย: โทนี่"]))

    t = SLATE_S
    srt, cues = [], 0
    for i, spec in enumerate(SHOTS):
        n = spec["n"]
        bg = work/f"bg{n:02d}.png"; fg = work/f"fg{n:02d}.png"
        build_bg(spec).save(bg)
        build_fg(spec, i, len(SHOTS)).save(fg)
        dur = durs[n-1]
        sc = work/f"scene-{n:02d}.mp4"
        render_scene(bg, fg, dur, sc, spec["zoom"])
        scene_files.append(sc)
        cues += 1
        srt.append(f"{cues}\n{srt_ts(t)} --> {srt_ts(t+dur)}\n"
                   f"{SUB_TEXT[n]}\n")
        report_rows.append((n, dur, spec["method"],
                            spec.get("img", "procedural"),
                            (spec.get("callout") or {}).get("credit", "-")))
        t += dur
        print(f"shot {n:02d} rendered ({dur:.2f}s)", flush=True)

    scene_files.append(slate(
        "end", "การเดินทางจบลงที่บ้านของเรา",
        ["ภาพนิ่ง NASA + เลเยอร์ยาน — ช็อต 8/9 ใช้ภาพนิ่ง",
         "แทน LTX ชั่วคราว (รอทรัพยากร GPU)",
         "ใช้เพื่อรีวิวภายในเท่านั้น"]))

    # concat video
    lst = work/"scenes.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in scene_files))
    vonly = work/"video-only.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", "scenes.txt", "-c", "copy",
                    "video-only.mp4"], check=True, cwd=work)

    # audio: silence + VO + silence
    au = work/"audio.wav"
    with wave.open(str(au), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"\x00" * int(SLATE_S*24000)*2)
        for i in range(1, 19):
            with wave.open(str(root/f"vo/v3-vo-{i:02d}.wav")) as vw:
                w.writeframes(vw.readframes(vw.getnframes()))
        w.writeframes(b"\x00" * int(SLATE_S*24000)*2)

    srt_path = outdir/"subtitles-th-v3-static-final-v1.srt"
    srt_path.write_text("\n".join(srt), encoding="utf-8")
    final = outdir/"v3-static-final-v1.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", str(vonly),
        "-i", str(au), "-i", str(srt_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-c:s", "mov_text", "-metadata:s:s:0", "language=tha",
        str(final)], check=True)
    print("final:", final)
    # report
    rep = ["# v3-static-final-v1 build report", "",
           f"video: {final.name}  640x384@{FPS}  slates {SLATE_S}s each",
           "", "| shot | dur_s | method | plate | credit |",
           "|---|---|---|---|---|"]
    rep += [f"| {n} | {d:.2f} | {m} | {p} | {c} |"
            for n, d, m, p, c in report_rows]
    rep += ["", "subs: burned bar + mov_text + sidecar SRT",
            "notes: shots 8/9 are NASA stills (LTX pending GPU lane);",
            "all assets private-review only pending public rights pass."]
    (outdir/"v3-static-final-v1-report.md").write_text(
        "\n".join(rep)+"\n", encoding="utf-8")
    print("report written")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
