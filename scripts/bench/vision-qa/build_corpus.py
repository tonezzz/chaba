#!/usr/bin/env python3
"""build_corpus.py — vision-qa bench corpus generator.

Builds ~18 deterministic PNG cases into images/ plus corpus.jsonl, the
proving ground for the kk-mac qwen2.5vl:7b visual-QA lane evaluation:

  lane "stock" — adobe-stock style asset QA
    kind=match   does the image match its submitted description (yes/no)
    kind=defect  visible technical defect — blur, watermark, noise, banding (yes/no)
  lane "ui"    — screenshot triage
    kind=triage  classify ok | error_state | layout_bug | empty_state

Images are synthetic (imglib canvas, stdlib+numpy) so gold labels are exact
and the corpus is reproducible offline — no external downloads.

Usage: build_corpus.py [--out-dir DIR]   (default: this script's directory)
"""
import argparse
import json
from pathlib import Path

from imglib import Canvas

W, H = 320, 240
UW, UH = 380, 280


# ------------------------------------------------------------ stock scenes
def scene_apple():
    c = Canvas(W, H, (244, 244, 244))
    c.ellipse(160, 205, 70, 12, (218, 218, 218))
    c.circle(160, 140, 52, (196, 30, 30))
    c.circle(143, 118, 16, (226, 80, 66), alpha=0.7)
    c.line(160, 90, 168, 62, (101, 67, 33), width=5)
    c.ellipse(186, 64, 18, 9, (76, 140, 60))
    return c


def scene_laptop_desk():
    c = Canvas(W, H)
    c.gradient_v((170, 122, 76), (118, 80, 46))
    for y in (60, 110, 170, 215):
        c.line(0, y, 320, y - 8, (140, 96, 56), width=2, alpha=0.5)
    c.poly([(60, 190), (260, 190), (276, 206), (44, 206)], (58, 58, 64))
    c.rect(70, 62, 180, 128, (40, 40, 46))
    c.rect(78, 70, 164, 112, (78, 128, 168))
    c.rect(78, 70, 164, 18, (44, 82, 112))
    c.rect(92, 100, 80, 8, (140, 175, 200), alpha=0.8)
    c.rect(92, 116, 120, 8, (120, 160, 190), alpha=0.6)
    c.rect(92, 132, 64, 8, (120, 160, 190), alpha=0.6)
    c.circle(288, 152, 19, (236, 236, 236))
    c.circle(288, 152, 13, (122, 74, 42))
    c.circle(309, 152, 7, (236, 236, 236), fill=False, width=3)
    return c


def scene_mountains():
    c = Canvas(W, H)
    c.gradient_v((250, 182, 92), (118, 58, 108))
    c.circle(160, 104, 26, (255, 222, 122))
    c.poly([(0, 240), (70, 120), (150, 240)], (62, 42, 72))
    c.poly([(110, 240), (208, 94), (310, 240)], (46, 32, 60))
    c.poly([(228, 240), (288, 150), (320, 190), (320, 240)], (72, 50, 82))
    c.rect(0, 216, 320, 24, (40, 30, 50))
    return c


def scene_city_night():
    c = Canvas(W, H, (10, 14, 40))
    for i, (sx, sy) in enumerate([(30, 24), (80, 44), (140, 20), (200, 36),
                                  (250, 18), (296, 50), (60, 70), (230, 66)]):
        c.rect(sx, sy, 2, 2, (240, 240, 220))
    c.circle(280, 40, 16, (235, 235, 210))
    for bx, bw, bh in [(10, 55, 120), (75, 48, 160), (133, 60, 100),
                       (203, 50, 140), (263, 47, 110)]:
        c.rect(bx, 240 - bh, bw, bh, (28, 32, 55))
        for wy in range(240 - bh + 10, 230, 18):
            for wx in range(bx + 7, bx + bw - 8, 14):
                if (wx * 7 + wy * 13) % 5 < 3:
                    c.rect(wx, wy, 6, 8, (250, 210, 90))
    return c


def scene_field():
    c = Canvas(W, H)
    c.gradient_v((118, 182, 236), (192, 226, 246))
    c.circle(268, 40, 22, (255, 230, 110))
    c.rect(0, 130, 320, 110, (86, 158, 70))
    for y in (150, 175, 205, 230):
        c.line(0, y, 320, y + 6, (70, 140, 58), width=3, alpha=0.6)
    for fx, fy, col in [(60, 170, (240, 90, 90)), (130, 200, (250, 230, 90)),
                        (210, 165, (240, 240, 240)), (270, 210, (240, 90, 160)),
                        (95, 222, (250, 200, 80))]:
        c.circle(fx, fy, 5, col)
        c.line(fx, fy + 5, fx, fy + 16, (50, 110, 45), width=2)
    return c


def scene_beach():
    c = Canvas(W, H)
    c.rect(0, 0, 320, 95, (150, 200, 240))
    c.rect(0, 95, 320, 60, (60, 130, 190))
    c.line(0, 95, 320, 95, (240, 250, 255), width=3, alpha=0.8)
    c.rect(0, 155, 320, 85, (232, 214, 164))
    c.line(140, 90, 140, 185, (150, 90, 50), width=4)
    c.poly([(95, 92), (185, 92), (140, 55)], (220, 60, 60))
    c.poly([(140, 55), (185, 92), (163, 92)], (240, 240, 240))
    c.circle(245, 195, 16, (240, 90, 60))
    c.line(232, 188, 258, 202, (250, 240, 230), width=4)
    return c


# --------------------------------------------------------------- ui scenes
def _ui_window(title, body=(246, 246, 248)):
    c = Canvas(UW, UH, (58, 62, 70))
    c.rect(40, 30, 300, 200, body)
    c.rect(40, 30, 300, 26, (208, 210, 215))
    c.circle(54, 43, 5, (255, 95, 86))
    c.circle(72, 43, 5, (255, 189, 46))
    c.circle(90, 43, 5, (39, 201, 63))
    c.text(104, 36, title, (55, 55, 60), scale=1)
    return c


def _btn(c, x, y, w, label, fg=(255, 255, 255), bg=(45, 110, 210)):
    c.rect(x, y, w, 24, bg)
    tw, _ = c.text_size(label, scale=1)
    c.text(x + (w - tw) // 2, y + 8, label, fg, scale=1)


def scene_ui_settings_ok():
    c = _ui_window("SETTINGS")
    c.text(56, 70, "ENABLE SYNC   [X]", (40, 40, 45), scale=1)
    c.text(56, 92, "DARK MODE     [ ]", (40, 40, 45), scale=1)
    c.text(56, 114, "NOTIFICATIONS [X]", (40, 40, 45), scale=1)
    c.rect(56, 140, 268, 1, (210, 210, 214))
    _btn(c, 180, 196, 64, "OK")
    _btn(c, 254, 196, 70, "CANCEL", fg=(60, 60, 64), bg=(225, 226, 230))
    return c


def scene_ui_dashboard_ok():
    c = _ui_window("DASHBOARD")
    c.rect(40, 56, 74, 174, (232, 234, 238))
    for i, lbl in enumerate(["HOME", "FILES", "STATS", "ADMIN"]):
        c.text(50, 68 + i * 20, lbl, (70, 70, 76), scale=1)
    c.rect(122, 56, 218, 30, (70, 130, 200))
    c.text(132, 67, "PROJECT STATUS", (255, 255, 255), scale=1)
    for i in range(4):
        c.rect(122, 96 + i * 30, 218, 22, (252, 252, 253))
        c.rect(122, 96 + i * 30, 218, 22, (190, 192, 198), fill=False)
        c.text(130, 103 + i * 30, f"TASK ROW {i + 1}", (90, 90, 96), scale=1)
    return c


def scene_ui_error_banner():
    c = _ui_window("SETTINGS")
    c.rect(40, 56, 300, 34, (200, 50, 45))
    c.text(52, 68, "CONNECTION FAILED - RETRY", (255, 255, 255), scale=1)
    c.text(56, 104, "ENABLE SYNC   [X]", (40, 40, 45), scale=1)
    c.text(56, 126, "DARK MODE     [ ]", (40, 40, 45), scale=1)
    _btn(c, 180, 196, 64, "OK")
    _btn(c, 254, 196, 70, "CANCEL", fg=(60, 60, 64), bg=(225, 226, 230))
    return c


def scene_ui_crash():
    c = Canvas(UW, UH, (30, 26, 30))
    c.rect(70, 55, 240, 170, (245, 240, 240))
    c.rect(70, 55, 240, 40, (178, 34, 34))
    c.text(84, 70, "APPLICATION CRASHED", (255, 255, 255), scale=2)
    c.poly([(190, 128), (164, 168), (216, 168)], (240, 180, 40))
    c.text(187, 138, "!", (60, 50, 40), scale=2)
    c.text(110, 185, "ERROR 0X2F - RESTART?", (120, 40, 40), scale=1)
    _btn(c, 158, 202, 64, "QUIT", bg=(150, 40, 40))
    return c


def scene_ui_layout_overflow():
    c = _ui_window("PROFILE")
    c.text(56, 70, "NAME:", (40, 40, 45), scale=1)
    c.rect(56, 84, 160, 20, (255, 255, 255))
    c.rect(56, 84, 160, 20, (170, 172, 178), fill=False)
    c.text(60, 90, "ALEJANDRO CONSTANTINOPOLE-WORTH", (30, 30, 35), scale=1)
    _btn(c, 296, 150, 120, "SAVE PROFILE")
    c.text(56, 186, "LAST LOGIN: 2026-11-19T08:59:59+07:00 UTC", (90, 90, 96),
           scale=1)
    _btn(c, 56, 196, 64, "OK")
    return c


def scene_ui_layout_overlap():
    c = _ui_window("DOCUMENTS")
    for i in range(3):
        c.rect(56, 66 + i * 26, 200, 20, (252, 252, 253))
        c.rect(56, 66 + i * 26, 200, 20, (190, 192, 198), fill=False)
    c.rect(180, 90, 160, 120, (250, 250, 250))
    c.rect(180, 90, 160, 120, (140, 140, 150), fill=False, width=2)
    c.rect(180, 90, 160, 22, (200, 202, 208))
    c.text(192, 97, "POPUP", (60, 60, 66), scale=1)
    c.text(150, 130, "OVERLAPPING TEXT HERE", (200, 40, 40), scale=1)
    _btn(c, 200, 176, 80, "CONFIRM")
    _btn(c, 56, 200, 70, "SUBMIT")
    return c


def scene_ui_empty():
    c = _ui_window("DETAILS")
    return c


# ------------------------------------------------------------------ corpus
_MATCH_PROMPT = (
    'Stock asset submitted with title "{desc}". Look at the image. '
    'Does it actually show this subject? Answer ONLY JSON: '
    '{{"answer": "yes"|"no", "reason": "<5-12 words>"}}')
_DEFECT_PROMPT = (
    "QC check for a stock-asset submission. Inspect the image for technical "
    "defects: heavy blur, watermark/text overlay, sensor noise, "
    "banding/striping, or cut-off content. Answer ONLY JSON: "
    '{"answer": "yes"|"no", "defects": ["<type>", ...]}')
_UI_PROMPT = (
    "Triage this application screenshot. Pick the ONE state that fits: "
    '"ok" (normal rendered UI), "error_state" (an error/failure is '
    'displayed), "layout_bug" (broken layout - overflow, overlap, '
    'clipping), "empty_state" (window chrome present but body blank). '
    'Answer ONLY JSON: {"answer": "ok"|"error_state"|"layout_bug"|'
    '"empty_state", "reason": "<5-12 words>"}')


def build():
    """Returns list of (case_id, lane, kind, gold, canvas, prompt)."""
    cases = []

    def stock(cid, kind, gold, canvas, prompt):
        cases.append((cid, "stock", kind, gold, canvas, prompt))

    def ui(cid, gold, canvas):
        cases.append((cid, "ui", "triage", gold, canvas, _UI_PROMPT))

    # ---- stock: description match
    stock("stock-match-001", "match", "yes", scene_apple(),
          _MATCH_PROMPT.format(desc="a single red apple on a plain white background"))
    stock("stock-match-002", "match", "yes", scene_mountains(),
          _MATCH_PROMPT.format(desc="mountain landscape at sunset with the sun over the peaks"))
    stock("stock-match-003", "match", "yes", scene_laptop_desk(),
          _MATCH_PROMPT.format(desc="a laptop and a coffee cup on a wooden desk"))
    stock("stock-match-004", "match", "yes", scene_city_night(),
          _MATCH_PROMPT.format(desc="city skyline at night with lit windows"))
    stock("stock-mismatch-001", "match", "no", scene_field(),
          _MATCH_PROMPT.format(desc="city skyline at night with neon lights"))
    stock("stock-mismatch-002", "match", "no", scene_apple(),
          _MATCH_PROMPT.format(desc="two people shaking hands in an office"))
    stock("stock-mismatch-003", "match", "no", scene_beach(),
          _MATCH_PROMPT.format(desc="a laptop on a wooden desk"))

    # ---- stock: defect detection
    c = scene_mountains(); c.box_blur(r=4, passes=3)
    stock("stock-defect-001", "defect", "yes", c, _DEFECT_PROMPT)
    c = scene_laptop_desk()
    c.text_rot(60, 120, "STOCKPREVIEW", (255, 255, 255), scale=3, angle_deg=-24, alpha=0.5)
    c.text_rot(70, 124, "STOCKPREVIEW", (40, 40, 40), scale=3, angle_deg=-24, alpha=0.4)
    stock("stock-defect-002", "defect", "yes", c, _DEFECT_PROMPT)
    c = scene_apple(); c.noise(sigma=42, seed=7)
    stock("stock-defect-003", "defect", "yes", c, _DEFECT_PROMPT)
    c = scene_city_night(); c.banding(period=3, amp=42)
    stock("stock-defect-004", "defect", "yes", c, _DEFECT_PROMPT)
    stock("stock-defect-005", "defect", "no", scene_beach(), _DEFECT_PROMPT)
    stock("stock-defect-006", "defect", "no", scene_field(), _DEFECT_PROMPT)

    # ---- ui: screenshot triage
    ui("ui-ok-001", "ok", scene_ui_settings_ok())
    ui("ui-ok-002", "ok", scene_ui_dashboard_ok())
    ui("ui-error-001", "error_state", scene_ui_error_banner())
    ui("ui-error-002", "error_state", scene_ui_crash())
    ui("ui-layout-001", "layout_bug", scene_ui_layout_overflow())
    ui("ui-layout-002", "layout_bug", scene_ui_layout_overlap())
    ui("ui-empty-001", "empty_state", scene_ui_empty())
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()
    out = Path(args.out_dir)
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for cid, lane, kind, gold, canvas, prompt in build():
        rel = f"images/{cid}.png"
        canvas.save(out / rel)
        lines.append({"case_id": cid, "lane": lane, "kind": kind,
                      "gold": gold, "image": rel, "prompt": prompt})
        print(f"  {cid}: {rel} gold={gold}")
    (out / "corpus.jsonl").write_text(
        "\n".join(json.dumps(l) for l in lines) + "\n")
    print(f"wrote {out/'corpus.jsonl'} ({len(lines)} cases)")


if __name__ == "__main__":
    main()
