PACK_DIR='/home/tony/CascadeProjects/dispatch-wt-20261124-154021-items-1-music-bed-source-decis/.dispatch-scratch/packtest-dlv'
NEST_ROOT='/home/tony/CascadeProjects/dispatch-wt-20261124-154021-items-1-music-bed-source-decis/.dispatch-scratch/nestroot'
import os, json, shutil, subprocess
import numpy as np
import soundfile as sf
import yaml

ROOT = NEST_ROOT
SHOTS = f'{ROOT}/doc-pilot/shots'
VO = f'{ROOT}/doc-pilot/vo'
VO_V2 = f'{ROOT}/doc-pilot/vo-v2'
VO_V4 = f'{ROOT}/doc-pilot/vo-v4'
VO_V5 = f'{ROOT}/doc-pilot/vo-v5'
AUDIO = f'{ROOT}/doc-pilot/audio'
SUBS = f'{ROOT}/doc-pilot/subs'
NASA_POC = (f'{ROOT}/doc-pilot/alternatives/nasa-2p5d-v1/'
            'nasa-2p5d-earth-saturn-v1.mp4')
SCRIPT = yaml.safe_load(open(f'{ROOT}/doc-pilot/script.yml',
                             encoding='utf-8'))
SCRIPT_LINES = {int(s['shot']): s['th'] for s in SCRIPT['shots']}
SCRIPT_EN = {int(s['shot']): s.get('en', '') for s in SCRIPT['shots']}
TMP = f'{PACK_DIR}/tmp'
OUT = f'{PACK_DIR}/final-v7'
STORE_FIN = f'{ROOT}/doc-pilot/final-v7'
for d in (TMP, OUT, STORE_FIN):
    os.makedirs(d, exist_ok=True)
GAP_S = 0.3
SR = 24000
rows = ['# doc-v2 delivery — v7 assembly report', '',
        '| shot | visual | VO | video_s | vo_s | hold_s |',
        '|---:|---|---|---:|---:|---:|']
videos, missing, invalid = [], [], []
cursor = 0.0
shot_windows = {}          # shot -> (start_s, end_s) in final timeline

def probe_duration(path):
    return float(subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', path], capture_output=True, text=True,
        check=True).stdout.strip())

def vo_path(n):
    if n in (4, 8):
        return f'{VO_V2}/ss1-vo-{n:02d}-v2.wav'
    if n in (6, 7):
        return f'{VO_V4}/ss1-vo-{n:02d}-v4.wav'
    if n == 15:
        return f'{VO_V5}/ss1-vo-15-v5.wav'
    return f'{VO}/ss1-vo-{n:02d}.wav'

# --- NASA composite plates (identical trims to v6) --------------------
nasa_scenes = {
    1: (0, 73, f'{TMP}/nasa-earth-v7.mp4'),
    11: (80, 153, f'{TMP}/nasa-saturn-v7.mp4'),
}
for start, end, out in nasa_scenes.values():
    subprocess.run(
        ['ffmpeg', '-y', '-i', NASA_POC, '-vf',
         f'trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS',
         '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
         '-pix_fmt', 'yuv420p', '-r', '24', out],
        check=True, capture_output=True)

# --- per-scene video segments (v6 recipe: clip + clone-hold) -----------
for n in range(1, 19):
    if n in nasa_scenes:
        video, visual = nasa_scenes[n][2], 'NASA 2.5D still'
    else:
        video = f'{SHOTS}/ss1-shot{n:02d}.mp4'
        visual = 'LTX'
    voice = vo_path(n)
    if not (os.path.isfile(video) and os.path.isfile(voice)):
        missing.append(n)
        continue
    wav, sr = sf.read(voice, dtype='float32')
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    finite = sr == 24000 and bool(np.isfinite(wav).all())
    if not finite:
        invalid.append(n)
        continue
    dur_v, dur_a = probe_duration(video), len(wav) / sr
    hold = max(0.0, dur_a - dur_v)
    gap = GAP_S if n < 18 else 0.0
    segment = f'{TMP}/scene-{n:02d}.mp4'
    vf = (f'tpad=stop_mode=clone:stop_duration={hold + gap:.3f}'
          if hold + gap > 0.01 else 'null')
    subprocess.run(
        ['ffmpeg', '-y', '-i', video, '-vf', vf, '-an',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
         '-pix_fmt', 'yuv420p', '-r', '24', segment],
        check=True, capture_output=True)
    videos.append(segment)
    target = max(dur_v, dur_a)
    shot_windows[n] = (cursor, cursor + target)
    rows.append(f'| {n} | {visual} | {os.path.basename(voice)} | '
                f'{dur_v:.2f} | {dur_a:.2f} | {hold:.2f} |')
    cursor += target + gap
if missing or invalid:
    open(f'{PACK_DIR}/delivery-report.md', 'w').write(
        '\n'.join(rows + ['', f'missing={missing}',
                          f'invalid_vo={invalid}']) + '\n')
    raise SystemExit(f'missing={missing}, invalid_vo={invalid}')

# --- continuous audio: VO stem + ducked music bed ----------------------
vo_stem = f'{AUDIO}/vo-stem-v6.wav'
bed = f'{AUDIO}/music-bed-ducked-v1.wav'
if not os.path.isfile(vo_stem):
    # fallback: rebuild narration track from per-shot VO (v6 style)
    parts = []
    for n in range(1, 19):
        w, sr = sf.read(vo_path(n), dtype='float32')
        if w.ndim > 1:
            w = w.mean(axis=1)
        dur_v = probe_duration(
            nasa_scenes[n][2] if n in nasa_scenes
            else f'{SHOTS}/ss1-shot{n:02d}.mp4')
        dur_a = len(w) / sr
        silence = max(0.0, dur_v - dur_a)
        gap = GAP_S if n < 18 else 0.0
        pad = int(round((silence + gap) * sr))
        parts.append(np.concatenate(
            (w, np.zeros(pad, dtype='float32'))))
    audio = np.concatenate(parts).astype('float32')
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    music_note = 'vo-stem absent — rebuilt VO track; NO music bed'
else:
    vo, _ = sf.read(vo_stem, dtype='float32')
    if vo.ndim > 1:
        vo = vo.mean(axis=1)
    vo = vo.astype('float32')
    if os.path.isfile(bed):
        b, bsr = sf.read(bed, dtype='float32')
        if bsr != SR:
            raise RuntimeError(f'bed sr {bsr} != {SR}')
        n = min(len(vo), len(b))
        if b.ndim == 1:
            b = np.stack([b, b], axis=1)
        mix = b[:n].astype('float32').copy()
        mix[:, 0] += vo[:n]
        mix[:, 1] += vo[:n]
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix *= 0.98 / peak
        audio = mix
        music_note = 'VO stem + ducked bed (sidechain under VO)'
    else:
        audio = vo
        music_note = 'VO stem only — music-bed-ducked-v1.wav missing'
dur_audio = len(audio) / SR
audio_path = f'{TMP}/audio-v7.wav'
sf.write(audio_path, audio, SR)

# --- subtitle files: prefer doc-v2-subs output, fallback v6 TH ----------
def pick(*names):
    for nm in names:
        p = f'{SUBS}/{nm}'
        if os.path.isfile(p):
            return p, nm
    return None, None
sub_th, sub_th_name = pick('subtitles-th-v7.srt')
if not sub_th:
    sub_th = f'{ROOT}/doc-pilot/final/subtitles-th-v6.srt'
    sub_th_name = 'subtitles-th-v6.srt (fallback)'
sub_en, sub_en_name = pick('subtitles-en-v1.srt')
sub_bi, sub_bi_name = pick('subtitles-bi-v1.srt')

# --- concat video -------------------------------------------------------
concat = f'{TMP}/scenes-v7.txt'
open(concat, 'w').write(''.join(f"file '{v}'\n" for v in videos))
video = f'{TMP}/video-v7.mp4'
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i',
                concat, '-c:v', 'copy', video],
               check=True, capture_output=True)

# --- mux variants (video copy; only audio+subs differ) -----------------
def mux(srt_path, lang, title, dst):
    cmd = ['ffmpeg', '-y', '-i', video, '-i', audio_path]
    meta = []
    if srt_path:
        cmd += ['-i', srt_path]
        meta = ['-map', '2:s:0', '-c:s', 'mov_text',
                '-metadata:s:s:0', f'language={lang}',
                '-metadata:s:s:0', f'title={title}',
                '-disposition:s:0', 'default']
    cmd += ['-map', '0:v:0', '-map', '1:a:0', *meta,
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
            '-t', f'{dur_audio:.3f}', dst]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst

made = {}
made['th'] = mux(sub_th, 'tha', 'Thai',
                 f'{OUT}/ss1-master-v7-th.mp4')
if sub_en:
    made['en'] = mux(sub_en, 'eng', 'English',
                     f'{OUT}/ss1-master-v7-en.mp4')
if sub_bi:
    made['bi'] = mux(sub_bi, 'tha+eng', 'Thai+English',
                     f'{OUT}/ss1-master-v7-bi.mp4')
for tag, p in made.items():
    shutil.copyfile(p, f'{STORE_FIN}/ss1-master-v7-{tag}.mp4')

# --- 720p export (TH master is the primary-language deliverable) -------
p720 = f'{OUT}/ss1-master-v7-720p.mp4'
subprocess.run(
    ['ffmpeg', '-y', '-i', made['th'],
     '-vf', 'scale=1280:720:flags=lanczos,unsharp=5:5:0.5',
     '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
     '-pix_fmt', 'yuv420p', '-c:a', 'copy',
     '-movflags', '+faststart', p720],
    check=True, capture_output=True)
shutil.copyfile(p720, f'{STORE_FIN}/ss1-master-v7-720p.mp4')

# --- poster frames ------------------------------------------------------
# shot 12 (Saturn — highest detail/motion in QC) mid-window; shot 7
# (Earth) as alternate.
posters = {}
for tag, n in (('saturn', 12), ('earth', 7)):
    s, e = shot_windows.get(n, (30.0, 33.0))
    t = (s + e) / 2
    p = f'{OUT}/poster-v7-{tag}.jpg'
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'quiet', '-ss', f'{t:.2f}', '-i', p720,
         '-frames:v', '1', '-q:v', '3', p], check=True,
        capture_output=True)
    shutil.copyfile(p, f'{STORE_FIN}/poster-v7-{tag}.jpg')
    posters[tag] = p

# --- verify --------------------------------------------------------------
dur_final = probe_duration(made['th'])
if dur_final < dur_audio - 0.75:
    raise RuntimeError(
        f'v7 mux truncated audio: final={dur_final:.2f} '
        f'audio={dur_audio:.2f}')
rows += ['', f'audio_track={dur_audio:.3f}s',
         f'final_th={dur_final:.3f}s',
         f'music={music_note}',
         f'subs_th={sub_th_name}',
         f'subs_en={sub_en_name or "MISSING"}',
         f'subs_bi={sub_bi_name or "MISSING"}',
         f'masters={sorted(made)}',
         '720p + posters written alongside masters',
         'verdict=PASS: v7 assembled, muxed, exported']
report = '\n'.join(rows) + '\n'
open(f'{PACK_DIR}/align-report-v7.md', 'w').write(report)
open(f'{STORE_FIN}/align-report-v7.md', 'w').write(report)

# --- CMS destination manifest -------------------------------------------
manifest = {
    'pack': 'doc-v2-delivery', 'version': 'v7',
    'generated_by': 'nest pack doc-v2-delivery',
    'store_root': 'gdrive:ada-nest',
    'master_640p': {
        'th': 'doc-pilot/final-v7/ss1-master-v7-th.mp4',
        'en': 'doc-pilot/final-v7/ss1-master-v7-en.mp4',
        'bi': 'doc-pilot/final-v7/ss1-master-v7-bi.mp4'},
    'delivery_720p': 'doc-pilot/final-v7/ss1-master-v7-720p.mp4',
    'posters': ['doc-pilot/final-v7/poster-v7-saturn.jpg',
                'doc-pilot/final-v7/poster-v7-earth.jpg'],
    'subtitle_files': 'doc-pilot/subs/',
    'audio_stems': 'doc-pilot/audio/',
    'destination': {
        'primary': 'Education lesson post 2157 (doc-pilot KK series) '
                   '— attach ss1-master-v7-720p.mp4 + poster-v7-saturn.jpg',
        'secondary': 'ada-cms-pages MDDB dossier note '
                     'doc-pilot-delivery-v7 (report + links)',
        'publish_path': 'board-api /lesson or /publish endpoints '
                        '(human/Ada confirms before publish)'},
    'notes': [
        'TH is the primary language; EN/bi are option tracks.',
        'If doc-v2-rerender-shots completes after this run, delete '
        'packs/doc-v2-delivery/done on the store and re-run to pick '
        'up re-rendered shots.',
        'Music bed is generated ambient (see doc-pilot/audio/'
        'music-bed-report.md); licensed swap-in = drop a file under '
        'doc-pilot/assets/music/ and re-run doc-v2-music-bed then '
        'this pack.']}
open(f'{PACK_DIR}/cms-destination.json', 'w').write(
    json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
open(f'{STORE_FIN}/cms-destination.json', 'w').write(
    json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')

open(f'{PACK_DIR}/delivery-report.md', 'w').write(report)
print(f'doc-v2-delivery PASS {dur_final:.2f}s '
      f'variants={sorted(made)}', flush=True)
