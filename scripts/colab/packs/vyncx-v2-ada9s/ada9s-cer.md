# vyncx-v2-ada9s — CER result (short-ref hypothesis)

**Verdict: hypothesis CONFIRMED — ref-content bleed eliminated.**

Baseline (vyncx-v2-bench, 17s ada ref): every clip prepended hallucinated
"อาหารเย็นให้ทุกคนกินกัน" (ref-transcript leakage), mean CER 0.571.
This pack (9s ada ref, ref_text_9s.txt): no bleed on any clip.

| clip | dur_s | CER | note |
|---|---|---|---|
| vx9s-ada-0 | 3.24 | 0.000 | perfect |
| vx9s-ada-1 | 3.62 | 0.000 | perfect |
| vx9s-ada-2 | 4.90 | 1.000 | **silent** — 0.0dB; deterministic failure on the longest sentence with the 9s ref (reproduced at step 32 and 64; the 17s ref produced audio for this sentence — ref-length-dependent) |
| vx9s-ada-3 | 3.56 | 0.162 | minor stutter (เผ็ดเผ็ด/มามาก), no bleed |
| vx9s-ada-4 | 3.03 | 0.000 | perfect |

voiced-clip mean CER: **0.04** — tony-quality tier (0.007).

Worker: tony-omen (GTX 1650, ~93s/clip — unmetered fleet GPU works,
30x slower than T4 but free). Scored via ada-stt qwen3-asr on omen.
