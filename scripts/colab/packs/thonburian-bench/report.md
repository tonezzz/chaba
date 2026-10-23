# thonburian-bench — Thai voice-clone eval (2026-10-23)

**Pack:** `ada-nest/packs/thonburian-bench` | **Worker:** colab-b6bdfc08 (Tesla T4)
**Model:** biodatlab/ThonburianTTS (megaF5, F5-TTS-based, ~330M, CC BY-NC-SA)
**Runtime:** 98 s total — model load + 10 clips (was >300 s/clip + never finished on VoxCPM2)

## Task

5 Thai sentences × 2 reference voices (ada-ref.wav, tony-ref-8s.wav), zero-shot
clone with supplied ref transcripts. Same bench set as the closed VoxCPM2 lane.

## Results

### Intelligibility — CER vs known text (qwen3-asr via ada-stt, char-level, Thai)

| clip | dur | CER | notes |
|------|-----|-----|-------|
| ada-0..4 | ~1.5s | **0.52 mean** | duration-compressed — rushed, semi-intelligible |
| tony-0..4 | 5-7.6s | **0.37 mean** | proper pacing but stuttery (word repetitions in ASR) |

### Speaker similarity — resemblyzer cosine (own-ref vs other-ref; floor = 0.47)

| | own-ref | other-ref |
|--|---------|-----------|
| ada clones | **0.79** | 0.43 |
| tony clones | **0.75** | 0.47 |

## Verdict

- **Timbre cloning: works** — own-speaker sim well above cross-speaker floor.
- **Thai intelligibility: baseline-grade** — CER 0.37-0.52 vs <0.10 target for a
  production Ada voice. Ada-ref clones suffer the F5 duration-prediction Thai
  weakness (JaiTTS paper documents it — UTF-8 byte-ratio duration is brittle
  for Thai script); tony-ref avoids the worst compression but stutters.
- **Speed: excellent** — real-time-factor ≪ 1 on T4; whole bench in 98 s.

## Next levers (if this lane continues)

- `speed` param <1.0 or longer `silence_padding` may fix the rushed ada clips.
- ThonburianTTS also ships an E2-model + Thai-IPA checkpoint — IPA input may
  bypass the duration-estimation issue entirely.
- JTS-AI/JaiTTS-F5TTS (RTF<0.2, neural duration predictor built *for* Thai) is
  the direct upgrade candidate if quality stays short.
- VoxCPM2 remains the high-quality target — needs A100 (~5.5GB, native bf16
  compile path), not T4.

Artifacts: `out/thon-{ada,tony}-[0-4].wav` (10 clips).
Scoring: Omen — ada-stt `100.72.146.39:8914` (qwen3-asr) + resemblyzer (venv-embeddings).
