"""Frozen P0 corpus — Sudoku + Thai fixtures + fixed short prompts.

Everything here is deterministic: Sudoku puzzles come from a pure-python
port of ncmthai.sudoku_data (BOS/SEP/BLANK token format kept for reference);
Thai fixtures + the AR training corpus are authored generic Thai text (no
personal data); short prompts are fixed instruction tasks.

Frozen BEFORE running: freeze.py emits corpus/frozen.json once; run/replay
read it and never regenerate tasks.
"""
import random

FREEZE_SEED = 20261113
SEED_SET = [42, 7]
N_SUDOKU = 4
SUDOKU_CLUES = 40

# ---------------------------------------------------------------- Sudoku
# Token format from ncmthai.sudoku_data: BOS=11, SEP=10, BLANK=0.
BOS, SEP, BLANK = 11, 10, 0


def _solve(board, rng):
    empties = [(r, c) for r in range(9) for c in range(9)
               if board[r][c] == 0]

    def bt(i):
        if i == len(empties):
            return True
        r, c = empties[i]
        nums = list(range(1, 10))
        rng.shuffle(nums)
        for n in nums:
            if all(board[r][j] != n for j in range(9)) and \
               all(board[j][c] != n for j in range(9)) and \
               all(board[r // 3 * 3 + a][c // 3 * 3 + b] != n
                   for a in range(3) for b in range(3)):
                board[r][c] = n
                if bt(i + 1):
                    return True
                board[r][c] = 0
        return False

    return board if bt(0) else None


def _carve(sol, clues, rng):
    cells = [(r, c) for r in range(9) for c in range(9)]
    keep = set(rng.sample(cells, clues))
    return [[sol[r][c] if (r, c) in keep else BLANK for c in range(9)]
            for r in range(9)]


def grid_to_line(grid):
    """9x9 grid -> '581|739|...' single-line canonical input (0 = blank)."""
    return "|".join("".join(str(v) for v in row) for row in grid)


def make_sudoku_tasks():
    rng = random.Random(FREEZE_SEED)
    tasks = []
    seen = set()
    while len(tasks) < N_SUDOKU:
        sol = _solve([[0] * 9 for _ in range(9)], rng)
        flat = tuple(x for row in sol for x in row)
        if flat in seen:
            continue
        seen.add(flat)
        pzl = _carve(sol, SUDOKU_CLUES, rng)
        i = len(tasks)
        tasks.append({
            "task_id": f"sudoku-{i:02d}",
            "kind": "sudoku",
            "input": grid_to_line(pzl),
            "meta": {
                "clues": SUDOKU_CLUES,
                "solution": grid_to_line(sol),
                "token_format": "BOS=11 SEP=10 BLANK=0 (ncmthai.sudoku_data)",
            },
        })
    return tasks


# ---------------------------------------------------------------- Thai
# Authored generic Thai lines — the AR baseline's frozen training corpus.
# No personal data; every line written for this fixture.
THAI_CORPUS = [
    "วันนี้อากาศร้อนมาก แดดจ้าตั้งแต่เช้าจนถึงเย็น",
    "ตลาดเช้ามีผักสดและผลไม้ตามฤดูกาลขายราคาถูก",
    "ข้าวผัดกะเพราหมูสับเป็นอาหารจานด่วนที่คนนิยม",
    "รถไฟฟ้าสายสีเขียวขยายเส้นทางออกไปถึงชานเมือง",
    "เด็ก ๆ กำลังเรียนภาษาไทยกับคุณครูที่โรงเรียน",
    "แม่ค้าแนะนำให้ซื้อมะม่วงตอนนี้เพราะกำลังหวาน",
    "ฝนตกหนักทำให้ถนนหลายสายน้ำท่วมขังรถติดมาก",
    "เขาไปวิ่งออกกำลังกายที่สวนสาธารณะทุกเช้า",
    "ร้านกาแฟข้างทางเปิดตั้งแต่หกโมงเช้าถึงเย็น",
    "งานประจำปีของวัดจัดขึ้นช่วงเดือนธันวาคม",
    "น้องชายกำลังซ้อมขับรถจักรยานยนต์ที่บ้าน",
    "หนังสือเล่มนี้เล่าเรื่องประวัติศาสตร์ไทยสมัยอยุธยา",
    "ชาวสวนเริ่มเก็บเกี่ยวผลผลิตก่อนฤดูฝนมาถึง",
    "อาหารเช้าวันนี้เป็นโจ๊กหมูใส่ไข่กับขนมปังปิ้ง",
    "ทีมฟุตบอลเยาวชนฝึกซ้อมกันที่สนามทุกวันเสาร์",
    "เส้นทางไปจังหวัดเชียงใหม่ผ่านภูเขาหลายลูก",
    "ป้าร้านข้าวแกงทำอาหารรสชาติจัดจ้านมาก",
    "นักเรียนกำลังเตรียมสอบปลายภาคเรียนที่สอง",
    "เรือด่วนเจ้าพระยาวิ่งระหว่างท่าน้ำทุกสิบนาที",
    "หมาบ้านนี้ชอบนอนอยู่ใต้ต้นมะม่วงตอนบ่าย",
    "ช่างประปามาซ่อมท่อน้ำที่รั่วใต้ซิงก์ครัว",
    "ผักบุ้งผัดไฟแดงใส่กระเทียมเยอะถึงจะอร่อย",
    "ห้องสมุดเปิดให้ยืมหนังสือได้ถึงสองสัปดาห์",
    "คนขับรถเมล์จำเส้นทางทุกซอยในเมืองได้แม่น",
]

THAI_TASKS = [
    {
        "task_id": "thai-00",
        "kind": "thai_continue",
        "input": "วันนี้อากาศร้อนมาก",
        "meta": {"reference": "แดดจ้าตั้งแต่เช้าจนถึงเย็น"},
    },
    {
        "task_id": "thai-01",
        "kind": "thai_continue",
        "input": "ฝนตกหนักทำให้ถนนหลายสาย",
        "meta": {"reference": "น้ำท่วมขังรถติดมาก"},
    },
    {
        "task_id": "thai-02",
        "kind": "thai_continue",
        "input": "ชาวสวนเริ่มเก็บเกี่ยวผลผลิต",
        "meta": {"reference": "ก่อนฤดูฝนมาถึง"},
    },
]

# -------------------------------------------------------- short prompts
PROMPT_TASKS = [
    {
        "task_id": "prompt-00",
        "kind": "short_prompt",
        "input": ("Classify the following as exactly one of chore|idea|fact, "
                  "reply with only the label: "
                  "'fix the leaking kitchen tap'"),
        "meta": {"check": "contains_label",
                 "labels": ["chore", "idea", "fact"],
                 "expected": "chore"},
    },
    {
        "task_id": "prompt-01",
        "kind": "short_prompt",
        "input": ("Translate to Thai, reply with only the translation: "
                  "'the meeting starts at nine'"),
        "meta": {"check": "thai_output"},
    },
    {
        "task_id": "prompt-02",
        "kind": "short_prompt",
        "input": ("Summarize in one English sentence under 30 words: "
                  "'The city council approved a new night-market permit "
                  "system after complaints about noise. Stalls must "
                  "register weekly and close by 22:00.'"),
        "meta": {"check": "word_count", "min_words": 4, "max_words": 30},
    },
]

# ---------------------------------------------------- prompt templates
PROMPT_TEMPLATES = {
    "sudoku": (
        "Solve this Sudoku puzzle. Rows are separated by | and blanks are"
        " 0.\n{input}\nReply with only the solved grid in the same format,"
        " nine rows of nine digits separated by |, no explanation."
    ),
    "thai_continue": (
        "Continue the following Thai text naturally with one short "
        "sentence. Reply in Thai only, no explanation.\n{input}"
    ),
    "short_prompt": "{input}",
}


def render_prompt(task):
    return PROMPT_TEMPLATES[task["kind"]].format(input=task["input"])


def build_tasks():
    return make_sudoku_tasks() + THAI_TASKS + PROMPT_TASKS


def training_texts(tasks):
    """Frozen training corpus for the AR/NCM-sim workers: every text the
    small local models are allowed to see (corpus lines + task inputs +
    reference answers). Deterministic order = task order then corpus."""
    texts = list(THAI_CORPUS)
    for t in tasks:
        texts.append(t["input"])
        sol = t["meta"].get("solution") or t["meta"].get("reference") \
            or t["meta"].get("expected")
        if sol:
            texts.append(str(sol))
    return texts
