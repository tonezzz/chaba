# doc-v2 shot QC — ss1-shot*.mp4 (640x384@24, 73f)

| shot | scene | mode | dur_s | KB | motion | p90 | frozen | grad | black_s | flags |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | hook | t2v | 3.04 | 38 | 0.209 | 0.256 | 72 | 3.72 | 0.00 | low-motion |
| 2 | depart | i2v:1 | 3.04 | 36 | 0.802 | 0.976 | 0 | 3.62 | 0.00 | ok |
| 3 | sun | t2v | 3.04 | 48 | 0.323 | 0.407 | 28 | 5.88 | 0.00 | low-motion |
| 4 | sun | t2v | 3.04 | 89 | 0.587 | 0.758 | 0 | 6.87 | 0.00 | ok |
| 5 | mercury | t2v | 3.04 | 63 | 0.297 | 0.390 | 46 | 7.98 | 0.00 | low-motion |
| 6 | venus | t2v | 3.04 | 36 | 0.391 | 0.505 | 7 | 5.01 | 0.00 | ok |
| 7 | earth | t2v | 3.04 | 57 | 0.132 | 0.231 | 71 | 9.79 | 0.00 | low-motion |
| 8 | mars | t2v | 3.04 | 78 | 0.602 | 0.741 | 0 | 6.39 | 0.00 | ok |
| 9 | jupiter | t2v | 3.04 | 43 | 0.863 | 0.984 | 0 | 5.69 | 0.00 | ok |
| 10 | jupiter | t2v | 3.04 | 33 | 0.246 | 0.299 | 65 | 4.75 | 0.00 | low-motion |
| 11 | saturn | t2v | 3.04 | 28 | 0.152 | 0.183 | 72 | 4.29 | 0.00 | low-motion |
| 12 | saturn | t2v | 3.04 | 218 | 2.501 | 3.161 | 0 | 12.52 | 0.00 | ok |
| 13 | uranus | t2v | 3.04 | 23 | 0.102 | 0.142 | 72 | 4.86 | 0.00 | low-motion |
| 14 | neptune | t2v | 3.04 | 27 | 0.109 | 0.181 | 72 | 4.31 | 0.00 | low-motion |
| 15 | kuiper | t2v | 3.04 | 28 | 0.099 | 0.166 | 72 | 1.63 | 0.00 | NEAR-FROZEN |
| 16 | orrery | t2v | 3.04 | 73 | 0.379 | 0.494 | 17 | 7.30 | 0.00 | ok |
| 17 | dot | t2v | 3.04 | 21 | 0.053 | 0.074 | 72 | 0.90 | 3.00 | NEAR-FROZEN, black3.0s |
| 18 | home | i2v:17 | 3.04 | 13 | 0.024 | 0.040 | 72 | 0.74 | 3.00 | NEAR-FROZEN, black3.0s |

weak (motion<0.1, re-render candidates): [15, 17, 18]
review (motion<0.35, eyeball first): [1, 3, 5, 7, 10, 11, 13, 14]
problems: none

weak-shots.txt is the machine-readable re-render list for
doc-v2-rerender-shots. i2v shots (2<-1, 18<-17) re-render
from the freshest available source frame.
