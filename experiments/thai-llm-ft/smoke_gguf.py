#!/usr/bin/env python3
"""CPU smoke test for a Thai GGUF via llama-cpp-python.

Verifies "usable Thai TODAY" qualitatively + measures tok/s. Not a benchmark —
for scores use eval_run.py --backend openai against llama.cpp --server or ollama.

  .venv/bin/pip install llama-cpp-python
  .venv/bin/python smoke_gguf.py models/typhoon2.5-qwen3-4b-q4_k_m.gguf
"""
import sys
import time

from llama_cpp import Llama

PROMPTS = [
    "สวัสดีครับ ช่วยแนะนำตัวหน่อยว่าคุณเป็น AI ตัวไหน ทำอะไรได้บ้าง",
    "สรุปข่าวต่อไปนี้เป็นประโยคเดียว: เจ้าหน้าที่ทางการระบุว่า ตั้งแต่วันที่ 4 "
    "ถึง 15 พ.ย. รถยนต์ที่มีเลขทะเบียนคู่หรือคี่ ต้องสลับวันกันวิ่งบนท้องถนน "
    "อินเดียเคยใช้มาตรการดังกล่าวมาแล้ว แต่ไม่มีความชัดเจนว่า ช่วยลดปัญหา"
    "มลพิษได้จริง ขณะนี้ ในกรุงนิวเดลี ระดับ PM2.5 สูงเกินค่ามาตรฐานต่อเนื่อง",
    "Translate into Thai: The central bank decided to keep interest rates "
    "unchanged amid uncertain inflation outlook.",
]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "models/typhoon2.5-qwen3-4b-q4_k_m.gguf"
    n_predict = int(sys.argv[2]) if len(sys.argv) > 2 else 160

    llm = Llama(
        model_path=path,
        n_ctx=4096,
        n_threads=4,
        n_gpu_layers=0,
        verbose=False,
    )
    for i, p in enumerate(PROMPTS):
        t0 = time.time()
        r = llm.create_chat_completion(
            messages=[{"role": "user", "content": p}],
            max_tokens=n_predict,
            temperature=0.0,
        )
        dt = time.time() - t0
        txt = r["choices"][0]["message"]["content"] or ""
        usage = r.get("usage", {})
        ct = usage.get("completion_tokens", 0)
        print(f"\n===== prompt {i+1} ({dt:.1f}s, ~{ct/dt:.1f} tok/s) =====")
        print("Q:", p[:80])
        print("A:", txt[:800])


if __name__ == "__main__":
    main()
