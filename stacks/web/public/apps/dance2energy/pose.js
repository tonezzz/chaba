// MediaPipe PoseLandmarker — webcam capture + landmark extraction
import { PoseLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

const WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";

let landmarker = null;
let videoEl = null;
let lastTimestamp = -1;

let _prevLandmarks = null;
let _curLandmarks  = null;
let _hasNewPose    = false;

export function getPrev() { return _prevLandmarks; }
export function getCur()  { return _curLandmarks; }

export async function initPose(video) {
  videoEl = video;
  const vision = await FilesetResolver.forVisionTasks(WASM_URL);
  landmarker = await PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
    runningMode: "VIDEO",
    numPoses: 1,
    minPoseDetectionConfidence: 0.5,
    minPosePresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
    outputSegmentationMasks: false,
  });
}

export async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
    audio: false,
  });
  videoEl.srcObject = stream;
  await videoEl.play();
}

export function detectFrame(timestamp) {
  if (!landmarker || !videoEl || videoEl.readyState < 2) return;
  // MediaPipe requires strictly increasing timestamps
  const ts = Math.round(timestamp);
  if (ts <= lastTimestamp) return;
  lastTimestamp = ts;
  _hasNewPose = false;

  const result = landmarker.detectForVideo(videoEl, ts);
  if (!result.landmarks || result.landmarks.length === 0) return;

  const lm = result.landmarks[0];
  _prevLandmarks = _curLandmarks;
  const arr = new Float32Array(34);
  for (let i = 0; i < 17; i++) {
    arr[i * 2]     = lm[i].x;
    arr[i * 2 + 1] = lm[i].y;
  }
  _curLandmarks = arr;
  _hasNewPose = _prevLandmarks !== null;
}

export function consumeNewPose() {
  const had = _hasNewPose;
  _hasNewPose = false;
  return had;
}
