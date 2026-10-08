# Voice-fallback bench — LATEST

| combo | stt | device | lang | n | stt ms | llm ft ms | llm ms | tts ms | ttfa ms | total ms | WER/CER | tool exact/partial/none |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cascade-whisper-piper | small | cuda | en | 10 | 652 | 5071 | 13522 | 1900 | 7624 | 16226 | 0.029 | 5/3/2 |
| cascade-whisper-piper | small | cuda | th | 5 | 814 | 1556 | 14245 | — | 2370 | 15367 | 0.120 | 1/0/4 |
| cascade-whisper-piper | medium | cpu | en | 10 | 15248 | 641 | 5866 | 1403 | 17293 | 22668 | 0.045 | 5/2/3 |
| cascade-whisper-piper | medium | cpu | th | 5 | 17227 | 1229 | 7774 | — | 18455 | 25154 | 0.137 | 1/0/4 |

source: `cascade-whisper-piper-20261009-065457.json` (llm=phi3-gguf:latest, 2026-10-08T23:44:28.717335+00:00)
