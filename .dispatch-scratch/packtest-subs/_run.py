PACK_DIR='/home/tony/CascadeProjects/dispatch-wt-20261124-154021-items-1-music-bed-source-decis/.dispatch-scratch/packtest-subs'
NEST_ROOT='/home/tony/CascadeProjects/dispatch-wt-20261124-154021-items-1-music-bed-source-decis/.dispatch-scratch/nestroot'
import os, re, subprocess, shutil
import yaml

ROOT = NEST_ROOT
MASTER = f'{ROOT}/doc-pilot/final/ss1-hybrid-v6.mp4'
TH_SRT = f'{ROOT}/doc-pilot/final/subtitles-th-v6.srt'
SUBS = f'{PACK_DIR}/subs'
FIN = f'{PACK_DIR}/final-v7'
STORE_SUBS = f'{ROOT}/doc-pilot/subs'
STORE_FIN = f'{ROOT}/doc-pilot/final-v7'
for d in (SUBS, FIN, STORE_SUBS, STORE_FIN):
    os.makedirs(d, exist_ok=True)

script = yaml.safe_load(open(f'{ROOT}/doc-pilot/script.yml',
                             encoding='utf-8'))
en = {int(s['shot']): s.get('en', '') for s in script['shots']}

# --- parse v6 SRT: cue index == shot number --------------------------
blocks = [b.strip() for b in open(TH_SRT, encoding='utf-8').read()
          .replace('\r\n', '\n').split('\n\n') if b.strip()]
cues = []   # (shot_no, [text lines])
for b in blocks:
    lines = b.split('\n')
    if len(lines) < 3 or '-->' not in lines[1]:
        continue
    idx = int(lines[0].strip())
    timing = lines[1].strip()
    text = '\n'.join(lines[2:]).strip()
    cues.append((idx, timing, text))
if not cues:
    raise SystemExit('no cues parsed from subtitles-th-v6.srt')

def fmt_srt(pairs):
    """pairs: list of (shot, timing, text-or-None-for-custom)."""
    out, i = [], 1
    for shot, timing, text in pairs:
        out += [str(i), f'{timing}', text, '']
        i += 1
    return '\n'.join(out) + '\n'

th_pairs, en_pairs, bi_pairs, missing_en = [], [], [], []
for idx, timing, text in cues:
    th_pairs.append((idx, timing, text))
    etext = en.get(idx, '')
    if not etext:
        missing_en.append(idx)
        etext = text
    en_pairs.append((idx, timing, etext))
    bi_pairs.append((idx, timing, f'{text}\n{etext}'))

th_srt = fmt_srt(th_pairs)
en_srt = fmt_srt(en_pairs)
bi_srt = fmt_srt(bi_pairs)
for name, content in (('subtitles-th-v7.srt', th_srt),
                      ('subtitles-en-v1.srt', en_srt),
                      ('subtitles-bi-v1.srt', bi_srt)):
    for base in (SUBS, STORE_SUBS):
        open(f'{base}/{name}', 'w', encoding='utf-8').write(content)

# --- soft-subtitle mux variants (stream copy, mov_text) --------------
STYLE = ("FontName=DejaVu Sans,Fontsize=15,PrimaryColour=&H00FFFFFF,"
         "OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0,"
         "Alignment=2,MarginV=10")
variants = [('th', 'subs/subtitles-th-v7.srt'),
            ('en', 'subs/subtitles-en-v1.srt'),
            ('bi', 'subs/subtitles-bi-v1.srt')]
soft_ok, burn_ok, burn_skip = [], [], []
for tag, rel in variants:
    srt = f'{PACK_DIR}/{rel}'
    dst = f'{FIN}/ss1-hybrid-v7-subs-{tag}.mp4'
    r = subprocess.run(
        ['ffmpeg', '-y', '-v', 'error', '-i', MASTER, '-i', srt,
         '-map', '0:v:0', '-map', '0:a:0', '-map', '1:s:0',
         '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'mov_text',
         '-metadata:s:s:0', 'language=tha' if tag != 'en' else 'eng',
         dst], capture_output=True, text=True)
    (soft_ok if r.returncode == 0 else burn_skip).append(
        f'soft-{tag}: ' + ('ok' if r.returncode == 0
                          else r.stderr.strip()[-120:]))
    if r.returncode == 0:
        shutil.copyfile(dst, f'{STORE_FIN}/ss1-hybrid-v7-subs-{tag}.mp4')

# --- burned-in variants (best effort; need libass) -------------------
has_ass = subprocess.run(['ffmpeg', '-hide_banner', '-filters'],
                         capture_output=True, text=True)
can_burn = 'subtitles' in has_ass.stdout
if can_burn:
    for tag, rel in (('th', 'subs/subtitles-th-v7.srt'),
                     ('en', 'subs/subtitles-en-v1.srt')):
        srt = f'{PACK_DIR}/{rel}'
        dst = f'{FIN}/ss1-hybrid-v7-burn-{tag}.mp4'
        vf = (f"subtitles='{srt}':force_style='{STYLE}'")
        r = subprocess.run(
            ['ffmpeg', '-y', '-v', 'error', '-i', MASTER, '-vf', vf,
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
             '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags',
             '+faststart', dst], capture_output=True, text=True)
        (burn_ok if r.returncode == 0 else burn_skip).append(
            f'burn-{tag}: ' + ('ok' if r.returncode == 0
                              else r.stderr.strip()[-120:]))
        if r.returncode == 0:
            shutil.copyfile(dst,
                            f'{STORE_FIN}/ss1-hybrid-v7-burn-{tag}.mp4')
else:
    burn_skip.append('burn-*: ffmpeg lacks libass subtitles filter')

# --- report ------------------------------------------------------------
rep = ['# doc-v2 subs report', '',
       f'cues: {len(cues)} (from subtitles-th-v6.srt; index==shot#)',
       f'shots without EN line in script.yml: {missing_en or "none"}',
       '',
       '## SRT files (store: doc-pilot/subs/)',
       '- subtitles-th-v7.srt — canonical TH, v6 timings verbatim',
       '- subtitles-en-v1.srt — EN parallel lines, same timings',
       '- subtitles-bi-v1.srt — TH line + EN line per cue',
       '',
       '## preview muxes (store: doc-pilot/final-v7/)',
       *[f'- {s}' for s in soft_ok],
       *[f'- {s}' for s in burn_ok],
       *[f'- SKIP {s}' for s in burn_skip],
       '',
       'note: previews carry the v6 audio (VO only, no music bed).',
       'doc-v2-delivery rebuilds the v7 master with the ducked bed',
       'and lets you pick the subtitle track.']
open(f'{PACK_DIR}/subs-report.md', 'w', encoding='utf-8').write(
    '\n'.join(rep) + '\n')
open(f'{STORE_SUBS}/subs-report.md', 'w', encoding='utf-8').write(
    '\n'.join(rep) + '\n')
print(f'doc-v2-subs done cues={len(cues)} soft={len(soft_ok)} '
      f'burn={len(burn_ok)}', flush=True)
