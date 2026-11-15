"""Deterministic verifier/ranker — the only scorer P0 trusts.

score(task, output) -> (score 0..1, detail). verdict = pass iff score >=
PASS_THRESHOLD[kind], else fail. Decision rows and guard violations are
checked separately. No LLM judge anywhere in the gate.
"""
import json
import re

PASS_THRESHOLD = {"sudoku": 0.99, "thai_continue": 0.75,
                  "short_prompt": 0.99}

THAI_RE = re.compile(r"[ก-๙]")
DIGITS_RE = re.compile(r"\d")


# ---------------------------------------------------------------- sudoku
def _parse_grid(output):
    """Pull a 9x9 digit grid out of arbitrary text. Verbose outputs echo
    the puzzle/reasoning first — the claimed answer is the LAST grid."""
    rows = re.findall(r"(?<!\d)(\d{9})(?!\d)", output)
    if len(rows) >= 9:
        return [[int(c) for c in r] for r in rows[-9:]]
    # tolerate '|' separators and spaced digits
    body = "".join(ch for ch in output if ch.isdigit() or ch in "| \n")
    groups = re.findall(r"\d(?:[ \t]*\d){8}", body)
    if len(groups) >= 9:
        return [[int(c) for c in re.sub(r"\s", "", g)]
                for g in groups[-9:]]
    flat = [int(c) for c in DIGITS_RE.findall(output)]
    if len(flat) >= 81:
        flat = flat[-81:]
        return [flat[i:i + 9] for i in range(0, 81, 9)]
    return None


def _valid_grid(grid):
    for i in range(9):
        if len(set(grid[i])) != 9:
            return False
        if len({grid[r][i] for r in range(9)}) != 9:
            return False
    for br in range(3):
        for bc in range(3):
            if len({grid[3 * br + a][3 * bc + b]
                    for a in range(3) for b in range(3)}) != 9:
                return False
    return True


def _puzzle_grid(line):
    return [[int(c) for c in row] for row in line.split("|")]


def score_sudoku(task, output):
    grid = _parse_grid(output)
    if not grid or len(grid) != 9 or any(len(r) != 9 for r in grid):
        return 0.0, {"wellformed": False}
    pzl = _puzzle_grid(task["input"])
    clues_ok = all(grid[r][c] == pzl[r][c]
                   for r in range(9) for c in range(9)
                   if pzl[r][c] != 0)
    valid = _valid_grid(grid)
    solved = valid and clues_ok
    score = 0.2 + 0.3 * valid + 0.5 * solved
    return score, {"wellformed": True, "valid": valid,
                   "clues_preserved": clues_ok, "solved": solved}


# ------------------------------------------------------------------ thai
def score_thai(task, output):
    out = _answer_line(output)
    if not out:
        return 0.0, {"empty": True}
    # degenerate-repeat guard: same 4-gram > 4 times, or char run > 12
    grams = {}
    for i in range(len(out) - 3):
        g = out[i:i + 4]
        grams[g] = grams.get(g, 0) + 1
    if (grams and max(grams.values()) > 4) or \
            re.search(r"(.)\1{11,}", out):
        return 0.0, {"degenerate": True}
    thai = len(THAI_RE.findall(out))
    latin = sum(1 for c in out if c.isascii() and c.isalpha())
    ratio = thai / max(1, thai + latin)
    len_ok = 10 <= len(out) <= 200
    score = 0.3 + 0.5 * ratio + 0.2 * len_ok
    return min(1.0, score), {"thai_ratio": round(ratio, 3),
                             "len": len(out), "len_ok": len_ok}


# ----------------------------------------------------------- short prompt
def _answer_line(output):
    """The claimed answer = last non-empty line, think-tags stripped.
    Reasoning may precede it; we score what the model finally claims."""
    lines = [re.sub(r"</?think>", "", l).strip()
             for l in output.strip().splitlines()]
    lines = [l for l in lines if l]
    return lines[-1] if lines else ""


def score_prompt(task, output):
    meta = task["meta"]
    out = _answer_line(output)
    check = meta["check"]
    if check == "contains_label":
        low = out.lower()
        found = [l for l in meta["labels"] if re.search(
            r"\b" + re.escape(l) + r"\b", low)]
        ok = found == [meta["expected"]]
        return (1.0 if ok else 0.0), {"labels_found": found}
    if check == "thai_output":
        thai = len(THAI_RE.findall(out))
        latin = sum(1 for c in out if c.isascii() and c.isalpha())
        ratio = thai / max(1, thai + latin)
        ok = ratio >= 0.5 and thai >= 4
        return (1.0 if ok else round(ratio * 0.5, 3)), \
            {"thai_ratio": round(ratio, 3)}
    if check == "word_count":
        n = len(out.split())
        ok = meta["min_words"] <= n <= meta["max_words"]
        return (1.0 if ok else 0.0), {"words": n}
    return 0.0, {"unknown_check": check}


# ------------------------------------------------------------------ API
def score(task, output):
    if task["kind"] == "sudoku":
        return score_sudoku(task, output)
    if task["kind"] == "thai_continue":
        return score_thai(task, output)
    return score_prompt(task, output)


def verdict_for(task, score_val):
    return "pass" if score_val >= PASS_THRESHOLD[task["kind"]] else "fail"


def check_decision(obj, allowed_routes):
    """Validate a JEV route-only decision object."""
    errs = []
    if not isinstance(obj, dict):
        return ["decision not an object"]
    if obj.get("route") not in allowed_routes:
        errs.append(f"route {obj.get('route')!r} not an arm")
    sc = obj.get("scores")
    if not isinstance(sc, dict) or not sc:
        errs.append("scores missing")
    else:
        for a, v in sc.items():
            if not isinstance(v, (int, float)) or not 0 <= v <= 1:
                errs.append(f"score[{a}] out of range")
    return errs


def parse_decision(output):
    try:
        return json.loads(output), None
    except Exception as e:
        return None, str(e)
