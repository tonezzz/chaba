# Lab bench — local YOLO object detect on home camera snapshots

Card: `lab-yolo-ha-detect`. Runner: tony-omen (GTX1650, i7-9750H).
Date: 2026-10-23.

## Corpus

22 labeled stills, gathered ~15:10–15:40 ICT:

- **20× vms-snap** (`http://100.106.196.22:8377/snap?ch=`, XMEye CCTV on
  mn01): 12 channels once + 8 channels second-round (~20 min later) for
  temporal variety. `D06`/`D10` are offline rows (attach fails) — skipped.
- **2× HA camera entities** on tony-ha (`camera_proxy`): `omen_cam`,
  `tony_dell_usb`. The other tony-ha cams (`ip_cam_65`, `xiaomi_c100*`,
  `xiaomi_c201_sd`) return HTTP 500 on stills — broken integrations, not
  a bench problem.
- **michael-dev was unusable**: token in `~/.config/secrets/ha-michael-dev.env`
  returns 401 on idc03:8124 (stale token — flag for refresh).

Labels in `labels.yml` — manual visual inspection, classes
`person | vehicle | package | none`. When several classes are present the
label follows security-cam priority: person > package > vehicle > none.
Distribution: 5 person / 7 vehicle / 1 package / 9 none.

## Method

- Models: `yolov8n.pt`, `yolo11n.pt` exported to ONNX (opset 17, imgsz 640,
  onnxslim-simplified) via ultralytics 8.4.184.
- Inference: onnxruntime-gpu 1.31.0, `CPUExecutionProvider` vs
  `CUDAExecutionProvider`. CUDA needs the pip nvidia libs
  (`nvidia-cublas`, `nvidia-cudnn-cu13` 9.x, `nvidia-cuda-runtime`,
  `nvidia-curand`, `nvidia-cufft`, `nvidia-cusparse`, `nvidia-cusolver`,
  `nvidia-cuda-nvrtc`, `nvidia-cuda-cupti`) — `bench.py` preloads them via
  ctypes so no `LD_LIBRARY_PATH` export is needed.
- `bench.py`: warmup pass + timed pass over all 22 images. Latency =
  end-to-end (cv2 decode → letterbox → `session.run` → NMS decode); raw
  `session.run` also recorded. Predicted class = mapped class of the
  highest-confidence detection at conf≥0.25, NMS IoU 0.45. COCO→bench map:
  person→person; bicycle/car/motorcycle/bus/truck→vehicle;
  backpack/handbag/suitcase→package; anything else→other (cannot promote).
- `results.json` also carries `correct_alt`: a person-priority rule
  (any person det ⇒ predict person).

## Scorecard

| config        | e2e p50 | e2e p95 | ort p50 | correct | gate                  |
|---------------|--------:|--------:|--------:|--------:|-----------------------|
| yolov8n@cpu   | 139 ms  | 184 ms  |  98 ms  | 17/22 (77%) | p50<800 ✓ / ≥70% ✓ |
| yolov8n@cuda  |  40 ms  |  63 ms  |  12 ms  | 17/22 (77%) | ✓ / ✓                |
| yolo11n@cpu   | 157 ms  | 226 ms  |  94 ms  | 16/22 (73%) | ✓ / ✓                |
| yolo11n@cuda  |  49 ms  |  62 ms  |  14 ms  | 16/22 (73%) | ✓ / ✓                |

CPU↔CUDA detections are identical; CUDA is ~3× faster end-to-end (~8× on
raw inference). Person-priority rescoring: v8n 16/22 (73%), 11n 17/22 (77%).

## Failure modes (all configs, deterministic)

- `package` is a structural miss: COCO has no package/box class. The one
  package-labeled frame (`ha_omen_cam`, cardboard boxes on sofa) is
  classified none; boxes surface as couch/chair/other. Stock weights can
  never hit this class — custom training or drop the class.
- Small/partial edge objects missed: scooter at frame edge (Walkway_In,
  Washing_Machines), distant car (Road_Corner under 11n).
- One false-positive person (0.28) on an empty tennis court (r2).
- Argmax class tie-break can lose a real person: `Road_In_r2` under 11n —
  person detected at 0.84 but motorcycle at 0.86 won argmax. The
  person-priority rule recovers it (that is why 11n gains under `alt`).

## Verdict

**PROMOTE to cms-auto-cctv-*** — recommended config `yolov8n.onnx` +
CUDAExecutionProvider on tony-omen: 40 ms e2e p50 (20× headroom vs the
800 ms gate; capture overhead dominates anyway at ~10 s/vms-snap frame),
77% correct vs 70% gate.

Caveats to carry into the promo card:

1. `package` needs a custom-trained class or must be dropped from the spec.
2. Keep argmax scoring for v8n; if 11n is preferred for other reasons, add
   the person-priority post-rule (raises it to 77%).
3. Small/edge objects are the main recall gap — acceptable at this
   threshold, improves with yolov8s or a 1280px input if ever needed.

## Repro

```bash
cd experiments/ultralytics-yolo-ha
./fetch_snaps.sh            # ~3-4 min; vms-snap is strictly serial
.venv/bin/python bench.py   # writes results.json
```

`.venv/` recipe: `python3 -m venv --system-site-packages .venv`,
`pip install --no-deps ultralytics`, `pip install torchvision --index-url
https://download.pytorch.org/whl/cpu`, `pip install opencv-python-headless
onnx onnxslim onnxruntime onnxruntime-gpu matplotlib pandas py-cpuinfo
ultralytics-thop pyyaml`, then force-reinstall `onnxruntime-gpu` so its
CUDA binaries win over the CPU wheel, plus the `nvidia-*` CUDA-13 libs.
