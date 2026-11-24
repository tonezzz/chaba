// webgpu-bge-compat — headless check that transformers.js Xenova/bge-m3
// (the model the iPhone WebGPU page loads) sits in the SAME vector space
// as ollama bge-m3 (the :11028 embed bank's space, MEM-0805 lane B).
//
// Vector space is device-independent, so this runs on CPU — it answers
// the compat question without needing the phone. The on-device run
// (webgpu-bench button 6) remains the final WebGPU-EP confirmation.
//
// Result 2026-11-24 (onnxruntime-node, dtype q4):
//   pooling=cls  cosine=0.9664  COMPATIBLE
//   pooling=mean cosine=0.7598  divergent (bge-m3 is a CLS model)
//
// Setup (one-off, ~300MB model download):
//   mkdir -p /tmp/bge-compat && cd /tmp/bge-compat
//   npm init -y && ONNXRUNTIME_NODE_INSTALL_CUDA=skip \
//     npm i @huggingface/transformers@3.7.6
//   node <this file> [path-to-bge-ref.json]
import { pipeline } from "@huggingface/transformers";
import { readFileSync } from "node:fs";

const refPath =
  process.argv[2] ||
  new URL("../../stacks/web/public/apps/webgpu-bench/bge-ref.json", import.meta.url).pathname;
const ref = JSON.parse(readFileSync(refPath, "utf8"));

function cosine(a, b) {
  let d = 0;
  for (let i = 0; i < a.length; i++) d += a[i] * b[i];
  return d;
}

const t0 = Date.now();
const bge = await pipeline("feature-extraction", "Xenova/bge-m3", { dtype: "q4" });
console.log(`loaded in ${((Date.now() - t0) / 1000).toFixed(1)}s`);

let compatible = false;
for (const pooling of ["cls", "mean"]) {
  const t1 = Date.now();
  const out = await bge(ref.phrase, { pooling, normalize: true });
  const v = Array.from(out.data);
  const sim = cosine(v, ref.vector);
  if (sim > 0.85) compatible = true;
  console.log(
    `pooling=${pooling} dims=${v.length} ` +
      `embed_ms=${Date.now() - t1} cosine_vs_ollama=${sim.toFixed(4)} ` +
      `${sim > 0.85 ? "COMPATIBLE" : "divergent"}`
  );
}
console.log(
  compatible
    ? "VERDICT: compatible — browser bge-m3 can feed the bank vector space"
    : "VERDICT: divergent — do not wire browser bge-m3 into the bank lane"
);
process.exit(compatible ? 0 : 1);
