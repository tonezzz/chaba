#!/usr/bin/env python3
from pathlib import Path
import numpy as np
import soundfile as sf
root=Path(__file__).resolve().parent
clips=[]
for name in ('earth-vo.wav','saturn-vo.wav'):
    w,sr=sf.read(root/'audio'/name,dtype='float32')
    if sr != 24000 or not np.isfinite(w).all():
        raise SystemExit(f'invalid voice input {name}: sr={sr}')
    target=round(73/24*sr)
    if len(w)<target:
        w=np.concatenate((w,np.zeros(target-len(w),dtype='float32')))
    clips.append(w)
gap=np.zeros(round(7/24*24000),dtype='float32')
audio=np.concatenate((clips[0],gap,clips[1]))
sf.write(root/'audio.wav',audio,24000,subtype='PCM_16')
print(f'samples={len(audio)} duration={len(audio)/24000:.3f}s finite={bool(np.isfinite(audio).all())}')
