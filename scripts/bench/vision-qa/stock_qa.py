#!/usr/bin/env python3
"""stock_qa.py — visual QA pass over landed Adobe Stock campaign candidates.

Card: adobe-stock-kkmac-vision-qa (OPS-0222). Depends on the
kk-mac-vision-lane-eval verdict — qwen2.5vl:7b PASSED the vision-qa bench
(run-kkmac-qwen25vl7b.{md,json} in this dir, 2026-11-27: overall 0.85,
stock lane 0.846, defect recall 0.75, 0 parse failures, ~2.1s/case).

For each candidate image (downloaded from gdrive:ada-nest/adobe-stock
campaigns/*/30-candidates + 50-upscaled, downscaled to <=1792px JPEG):
ask qwen2.5vl:7b on kk-mac ollama for a structured QA verdict —
spec-match, defect list, AI-artifact flags, photorealism read,
keep/revise/reject suggestion. Results land as
stock-qa-<ts>.{md,json} next to this script; human-QC labels from
40-qc-review.md / manifests are embedded for the agreement table.

Usage:
  python3 stock_qa.py --src /tmp/adobe-vqa/q90 --base-url http://kk-mac:11434
"""
import argparse, base64, json, re, sys, time, urllib.request
from pathlib import Path

MAX_DIM = 1792

# campaign spec shared by the remote-work comparisons (from the baseline
# manifest prompt + negative prompt)
RW_SPEC = ("Adobe Stock photorealistic stock photo: bright modern home "
           "office prepared for remote work — laptop, clean desk, soft "
           "natural morning light, copy space, landscape. No logos, "
           "brands, readable text, or distorted anatomy.")
MANGROVE_SPEC = ("Adobe Stock photorealistic stock photo: a hut in the "
                "middle of a mangrove forest cluster, half buried in the "
                "tree lines, evening light, a fishing boat passing at "
                "sunset, clear summer sky with white clouds.")
CAL_SPEC = ("Adobe Stock printable calendar/planner design image."
            )

# asset_id -> (campaign, spec, intent, human_qc_gold or None)
ASSETS = {
    # --- AS-2026-11-05-REMOTE-WORK-001: remote-work home office lane ---
    "remote-work-home-office-001": (
        "remote-work", RW_SPEC,
        "Baseline kk-mac SDXL 20-step render of the campaign spec.",
        "keep_for_comparison (blurry plant leaves noted)"),
    "comparison-b-sharp-leaves": (
        "remote-work", RW_SPEC,
        "Revision targeting sharper plant leaves (kk-mac SDXL).",
        "revise — floor behind door + chair surface under table weird"),
    "comparison-c-omen-sdxl": (
        "remote-work", RW_SPEC,
        "Same scene on omen SDXL-Lightning 4-step (painterly output).",
        "reject-for-photorealism; KEEP as illustration-category pilot"),
    "comparison-d-omen-sdxl-q8": (
        "remote-work", RW_SPEC,
        "Omen SDXL-base Q8 20-step render, same scene family.",
        "revise — smooth, doesn't feel photorealistic"),
    "comparison-d-x4": (
        "remote-work", RW_SPEC,
        "Real-ESRGAN x4 upscale of comparison-d-omen-sdxl-q8.",
        None),
    "comparison-d-x4-sharp40": (
        "remote-work", RW_SPEC,
        "Real-ESRGAN x4 + unsharp40 post-pass of comparison-d.",
        None),
    "comparison-d-x4-sharp60": (
        "remote-work", RW_SPEC,
        "Real-ESRGAN x4 + unsharp60 post-pass of comparison-d.",
        None),
    "comparison-e-cf-flux-schnell": (
        "remote-work", RW_SPEC,
        "FLUX.1-schnell render; leaves sharp, wall-corner defect known.",
        "revise — wall corner looks weird"),
    "comparison-e-cf-inpaint-wheels": (
        "remote-work", RW_SPEC,
        "CF Workers-AI SD1.5 inpaint repair of chair wheels on "
        "fix3-region (512-native upscaled into mask — expected soft).",
        "pending — semantically correct but soft"),
    "comparison-e-gemini-fix2": (
        "remote-work", RW_SPEC,
        "Gemini full-image edit: relight + wall-corner attempt.",
        "revise — corner still misaligned, shelf floating"),
    "comparison-e-gemini-fix3-region": (
        "remote-work", RW_SPEC,
        "Picker region edit fixing wall corner; chair wheels still "
        "defective (blobby ball-casters).",
        "revise — corner fixed; remaining defect: chair wheels"),
    "comparison-e-gemini-fix4-wheels": (
        "remote-work", RW_SPEC,
        "Gemini region-edit attempt on chair wheels — known near-no-op.",
        "revise — wheels geometry unchanged"),
    "comparison-e-gemini-wallfix": (
        "remote-work", RW_SPEC,
        "Gemini edit targeting wall corner only.",
        "revise — corner misaligned at floor, shelf floating, too dark"),
    "comparison-e-omen-sdxl-inpaint-wheels": (
        "remote-work", RW_SPEC,
        "Omen SDXL-lightning masked inpaint + composite of chair "
        "wheels — the lane winner; expect proper 5-star base + casters.",
        "pending — expected winner of inpaint lane"),
    "comparison-g-omen-sdxl-q8-wallfix": (
        "remote-work", RW_SPEC,
        "Omen Q8 wallfix render attempt.",
        None),
    "comparison-h-omen-sdxl-q8-cprompt": (
        "remote-work", RW_SPEC,
        "Controlled re-run: omen Q8 with verbatim candidate-C prompt "
        "(OPS-1078 photorealism A/B vs C and D).",
        None),
    # --- mangrove-hut family (same campaign, new subject 2026-11-26) ---
    "mangrove-hut-kk-mac-sdxl-20261126": (
        "mangrove", MANGROVE_SPEC,
        "Base kk-mac SDXL render of the mangrove-hut spec (v5).",
        "keep (Tony)"),
    "mangrove-hut-bright-gemedit-20261126-v1": (
        "mangrove", MANGROVE_SPEC,
        "Gemini bright/texture edit of the base render (v1).",
        "keep (Tony) — add more texture on tree/hut/branches"),
    "mangrove-hut-bright-gemedit-20261126-v2": (
        "mangrove", MANGROVE_SPEC,
        "Gemini edit v2 — more leaf/bark detail requested.",
        "keep (Tony) — more details on leaves and tree barks"),
    "mangrove-hut-bright-gemedit-20261126-v3": (
        "mangrove", MANGROVE_SPEC,
        "Gemini edit v3 — declared FINAL asset by Tony.",
        "keep (Tony) — final asset"),
    "mangrove-x4": (
        "mangrove", MANGROVE_SPEC,
        "Real-ESRGAN x4 upscale of the kk-mac mangrove base render "
        "(upscaler-eval output).",
        None),
    "mangrove-v3-2k-x4": (
        "mangrove", MANGROVE_SPEC,
        "Real-ESRGAN x4 upscale of the v3-2k derived mangrove image.",
        None),
    # --- trip-calendar campaign ---
    "calendar_en_v2": (
        "trip-calendar", CAL_SPEC,
        "English calendar design, gemini-3.1-flash-image.",
        None),
    "calendar_en_pro_v3": (
        "trip-calendar", CAL_SPEC,
        "English calendar design, gemini-3-pro-image (pro tier).",
        None),
    "calendar_th_v2": (
        "trip-calendar", CAL_SPEC,
        "Thai-language calendar design, gemini-3.1-flash-image.",
        None),
}

PROMPT = """You are a strict visual QA judge for Adobe Stock submissions.

ASSET SPEC: {spec}
ASSET INTENT: {intent}

Inspect the image and answer with ONLY a JSON object (no prose, no
markdown fences):
{{"spec_match": "full|partial|poor",
  "spec_notes": "<=20 words on what matches/misses the spec",
  "defects": ["visible defects: warped geometry, extra/missing parts,
    gibberish text, watermarks, blur, distortion — empty list if none"],
  "artifacts": ["likely AI-generation artifacts — empty list if none"],
  "photorealism": "photo|illustration|unclear",
  "qc_suggestion": "keep|revise|reject",
  "confidence": "low|med|high",
  "summary": "<=25 words overall verdict"}}
"""


def _post(url, body, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ask_ollama(base_url, model, prompt, img_b64):
    body = {"model": model, "stream": False,
            "messages": [
                {"role": "system", "content":
                 "You are a precise visual QA judge. Answer ONLY the "
                 "JSON object requested."},
                {"role": "user", "content": prompt,
                 "images": [img_b64]}],
            "options": {"temperature": 0, "num_predict": 400}}
    d = _post(base_url.rstrip("/") + "/api/chat", body)
    return d["message"]["content"]


def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"_parse_error": (text or "")[:200]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"_parse_error": (text or "")[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--base-url", default="http://kk-mac:11434")
    ap.add_argument("--model", default="qwen2.5vl:7b")
    ap.add_argument("--only", default="")
    ap.add_argument("--out-prefix", default="")
    args = ap.parse_args()

    src = Path(args.src)
    files = sorted(src.iterdir())
    if args.only:
        want = set(args.only.split(","))
        files = [f for f in files if f.stem in want]
    results = []
    for i, f in enumerate(files, 1):
        aid = f.stem
        spec = ASSETS.get(aid)
        if spec is None:
            print(f"[{i}] {aid}: NO SPEC ENTRY — skipped", file=sys.stderr)
            continue
        campaign, asset_spec, intent, gold = spec
        b64 = base64.b64encode(f.read_bytes()).decode()
        t0 = time.time()
        try:
            raw = ask_ollama(args.base_url, args.model,
                             PROMPT.format(spec=asset_spec, intent=intent),
                             b64)
        except Exception as e:
            raw = f"ERROR {e}"
        s = round(time.time() - t0, 1)
        parsed = parse_json(raw)
        rec = {"asset_id": aid, "campaign": campaign, "file": f.name,
               "intent": intent, "human_qc": gold, "seconds": s,
               "raw": raw[:600], **parsed}
        results.append(rec)
        sug = parsed.get("qc_suggestion", "?")
        sm = parsed.get("spec_match", "?")
        print(f"[{i}/{len(files)}] {aid}: spec={sm} qc={sug} "
              f"conf={parsed.get('confidence','?')} {s}s", file=sys.stderr)

    ts = time.strftime("%Y%m%d-%H%M%S")
    prefix = args.out_prefix or f"stock-qa-{ts}"
    out_json = Path(__file__).parent / f"{prefix}.json"
    out_md = Path(__file__).parent / f"{prefix}.md"
    out_json.write_text(json.dumps(
        {"model": args.model, "base_url": args.base_url,
         "ran_at": ts, "results": results}, indent=2))

    lines = ["# adobe-stock visual QA — kk-mac qwen2.5vl:7b", "",
             f"model: `{args.model}` @ `{args.base_url}` "
             f"cases: {len(results)}", "",
             "| asset | campaign | spec_match | defects | artifacts | "
             "photo? | qc_sugg | conf | human QC | seconds |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        defs = "; ".join(r.get("defects") or []) or "-"
        arts = "; ".join(r.get("artifacts") or []) or "-"
        lines.append(
            f"| {r['asset_id']} | {r['campaign']} | "
            f"{r.get('spec_match','?')} | {defs[:80]} | {arts[:60]} | "
            f"{r.get('photorealism','?')} | {r.get('qc_suggestion','?')} | "
            f"{r.get('confidence','?')} | {r.get('human_qc') or '-'} | "
            f"{r['seconds']} |")
    lines += ["", "## per-asset detail", ""]
    for r in results:
        lines += [f"### {r['asset_id']}", "",
                  f"- intent: {r['intent']}",
                  f"- human QC: {r.get('human_qc') or 'none recorded'}",
                  f"- spec_match: {r.get('spec_match')} — "
                  f"{r.get('spec_notes','')}",
                  f"- photorealism: {r.get('photorealism')} · "
                  f"qc_suggestion: {r.get('qc_suggestion')} "
                  f"({r.get('confidence')})",
                  f"- defects: {r.get('defects')}",
                  f"- artifacts: {r.get('artifacts')}",
                  f"- summary: {r.get('summary','')}", ""]
    out_md.write_text("\n".join(lines) + "\n")
    print(f"[done] {out_md} + {out_json}", file=sys.stderr)


if __name__ == "__main__":
    main()
