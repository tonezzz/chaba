import os, re, json, subprocess, glob as g
import numpy as np
import yaml

ROOT = NEST_ROOT
SHOTS = f'{ROOT}/doc-pilot/shots'
OUT = f'{PACK_DIR}/out'
FR = f'{PACK_DIR}/frames'
STORE = f'{ROOT}/doc-pilot/qc/shot-qc'
for d in (OUT, FR, STORE):
    os.makedirs(d, exist_ok=True)

W2, H2 = 160, 96           # metric grid (matches manual probe)
CONTACT_W, CONTACT_H = 320, 192
I2V = {2: 1, 18: 17}       # shot -> last-frame source (doc-render-ss1)
WEAK_MOTION = 0.10         # mean |frame diff| below -> near-frozen
REVIEW_MOTION = 0.35       # below -> low-motion, human eyeball

script = yaml.safe_load(open(f'{ROOT}/doc-pilot/script.yml',
                             encoding='utf-8'))
scene = {int(s['shot']): s.get('scene', '') for s in script['shots']}

def gray_frames(mp4):
    r = subprocess.run(
        ['ffmpeg', '-v', 'quiet', '-i', mp4,
         '-vf', f'scale={W2}:{H2},format=gray',
         '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
        capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    n = len(a) // (W2 * H2)
    return a[:n * W2 * H2].reshape(n, W2 * H2).astype(np.float32)

def probe(mp4):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries',
         'format=duration,size:stream=codec_type,width,height,nb_frames',
         '-of', 'json', mp4], capture_output=True, text=True)
    j = json.loads(r.stdout or '{}')
    v = next((s for s in j.get('streams', [])
              if s.get('codec_type') == 'video'), {})
    return j.get('format', {}), v

def blackdetect(mp4):
    r = subprocess.run(
        ['ffmpeg', '-i', mp4, '-vf',
         'blackdetect=d=0.2:pic_th=0.98', '-an', '-f', 'null', '-'],
        capture_output=True, text=True)
    hits = re.findall(r'black_start:([\d.]+) black_end:([\d.]+)',
                      r.stderr)
    return [(float(a), float(b)) for a, b in hits]

rows = ['# doc-v2 shot QC — ss1-shot*.mp4 (640x384@24, 73f)', '',
        '| shot | scene | mode | dur_s | KB | motion | p90 | frozen | '
        'grad | black_s | flags |',
        '|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
metrics, weak, review, problems = {}, [], [], []

for n in range(1, 19):
    mp4 = f'{SHOTS}/ss1-shot{n:02d}.mp4'
    if not os.path.isfile(mp4):
        problems.append(n)
        rows.append(f'| {n} | {scene.get(n, "")} | - | MISSING | - |'
                    ' - | - | - | - | - | MISSING |')
        continue
    fmt, v = probe(mp4)
    fr = gray_frames(mp4)
    if len(fr) < 2:
        problems.append(n)
        rows.append(f'| {n} | {scene.get(n, "")} | decode | - | - |'
                    ' DECODE-FAIL | - | - | - | - | BAD |')
        continue
    d = np.abs(np.diff(fr, axis=0)).mean(axis=1)
    motion = float(d.mean())
    p90 = float(np.percentile(d, 90))
    frozen = int((d < 0.3).sum())
    # blur proxy: mean gradient magnitude on the mid frame
    mid = fr[len(fr) // 2].reshape(H2, W2)
    gx = np.abs(np.diff(mid, axis=1)).mean()
    gy = np.abs(np.diff(mid, axis=0)).mean()
    grad = float(gx + gy)
    blacks = blackdetect(mp4)
    black_s = sum(b - a for a, b in blacks)
    dur = float(fmt.get('duration') or 0)
    kb = os.path.getsize(mp4) / 1024
    mode = f'i2v:{I2V[n]}' if n in I2V else 't2v'
    fl = []
    if motion < WEAK_MOTION:
        fl.append('NEAR-FROZEN')
        weak.append(n)
    elif motion < REVIEW_MOTION:
        fl.append('low-motion')
        review.append(n)
    if black_s > 0.2:
        fl.append(f'black{black_s:.1f}s')
    if dur < 2.5 or dur > 4.0:
        fl.append(f'dur{dur:.2f}')
    if v.get('width') != 640 or v.get('height') != 384:
        fl.append('res?')
    metrics[f'ss1-shot{n:02d}'] = dict(
        scene=scene.get(n, ''), mode=mode, duration=round(dur, 3),
        bytes=os.path.getsize(mp4), motion=round(motion, 4),
        p90=round(p90, 4), frozen=frozen, grad=round(grad, 3),
        black_s=round(black_s, 2), flags=fl)
    rows.append(f'| {n} | {scene.get(n, "")} | {mode} | {dur:.2f} | '
                f'{kb:.0f} | {motion:.3f} | {p90:.3f} | {frozen} | '
                f'{grad:.2f} | {black_s:.2f} | {", ".join(fl) or "ok"} |')

    # contact-sheet frame at ~50% (also the eyeball reference)
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'quiet', '-ss', f'{dur/2:.2f}',
         '-i', mp4, '-frames:v', '1',
         '-vf', f'scale={CONTACT_W}:{CONTACT_H}',
         f'{FR}/shot{n:02d}.jpg'], capture_output=True)

# contact sheet 6x3 via ffmpeg tile
subprocess.run(
    ['ffmpeg', '-y', '-v', 'quiet', '-framerate', '1',
     '-i', f'{FR}/shot%02d.jpg', '-vf', 'tile=6x3',
     '-frames:v', '1', f'{OUT}/contact-sheet.jpg'],
    capture_output=True)

rows += ['',
         f'weak (motion<{WEAK_MOTION}, re-render candidates): '
         f'{weak or "none"}',
         f'review (motion<{REVIEW_MOTION}, eyeball first): '
         f'{review or "none"}',
         f'problems: {problems or "none"}',
         '',
         'weak-shots.txt is the machine-readable re-render list for',
         'doc-v2-rerender-shots. i2v shots (2<-1, 18<-17) re-render',
         'from the freshest available source frame.']
rep = '\n'.join(rows) + '\n'
open(f'{OUT}/shot-qc-report.md', 'w', encoding='utf-8').write(rep)
open(f'{OUT}/weak-shots.txt', 'w').write(
    ''.join(f'{n}\n' for n in weak) or 'none\n')
open(f'{OUT}/metrics.json', 'w').write(
    json.dumps(metrics, indent=1, ensure_ascii=False) + '\n')
for name in ('shot-qc-report.md', 'weak-shots.txt', 'metrics.json'):
    open(f'{STORE}/{name}', 'w', encoding='utf-8').write(
        open(f'{OUT}/{name}', encoding='utf-8').read())
import shutil
shutil.copyfile(f'{OUT}/contact-sheet.jpg',
                f'{STORE}/contact-sheet.jpg')

verdict = 'FAIL' if problems else f'PASS weak={weak or "none"}'
print(f'doc-v2-shot-qc {verdict}', flush=True)
if problems:
    raise SystemExit(f'missing/unreadable shots: {problems}')
