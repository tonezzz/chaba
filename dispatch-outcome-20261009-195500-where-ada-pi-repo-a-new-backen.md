# Dispatch outcome — ada-memory-injection-scan (2026-10-09)

**Card:** `ada-memory-injection-scan` · **Runner:** idc02 (edit host tony-dell)
**Repos touched:** `~/CascadeProjects/ada-pi` (the ada-pi edit point — changes uncommitted on `main`), this chaba dispatch worktree (SSOT docs).

## What changed

**ada-pi (`~/CascadeProjects/ada-pi`):**

- **`backend/memory_write_guard.py` (new)** — dependency-free, string-level pre-write content scan for memory writes. Detection is data-driven: a `SCAN_RULES` table at the top of the module (regex rows plus two checker functions). Four classes:
  - `prompt_injection` — 8 rules: ignore-instructions phrasing, system-prompt/jailbreak refs, `you are now`/`pretend you are`, line-initial role prefixes (`system:`/`user:`/`assistant:`/`function:`), chat-template tokens (`<<SYS>>`, `[INST]`, `<|im_start|>`), `## New instructions:` headers, prompt-reveal requests, authority spoofs (`I am your developer`).
  - `credential_shape` — 10 rules: AWS `AKIA`/`ASIA`, `sk-`/`pk-`/`ak-`/`rk-` provider keys, `ghp_`/`github_pat_`, Slack `xox*`, Google `AIza`, JWT `eyJ…`, PEM private-key blocks, `Authorization: Bearer`, password/API-key assignments, `scheme://user:pass@` URLs.
  - `invisible_unicode` — ZWSP/ZWNJ/marks/soft hyphen/word joiner/BOM, C0–C1 controls, bidi overrides+isolates, tag chars U+E0000–E007F, deprecated format chars. **ZWJ refused only outside emoji sequences and Indic/Arabic-script adjacency** — real emoji family sequences pass.
  - `content_flood` — oversized payloads (default 8000 chars, `ADA_MEMORY_FLOOD_MAX` tunable), whitespace/repeat runs, >50% blank bodies, Latin+confusable-script mixing (Thai deliberately excluded — normal content here).
- **`backend/tool_runner/memory.py`** — every write path now calls `self._memory_guard_scan(bank, *parts)` before the MDDB/chaba upsert: `_execute_ada_remember` (curated + `kind=guest`), `_vocab_append` (covers `kind=vocab` and `vocab_note`), `guest_remember`, `guest_remember_private`. Refusals return `{ok: false, reason, matched_class, matched_rule, error}` verbatim. The scan runs for **all identities including `full:true`** — it guards the bank, not the caller.
- **`backend/tool_runner/common.py`** — imports `scan_parts`/`scan_and_emit`/`FLOOD_MAX_CHARS` into the runner namespace; mixin helpers `_memory_guard_scan` + `_emit_memory_scan_refused` added to `MemoryMixin` (base mixin so `ToolRunner` resolves them for every path).
- **`tests/test_memory_write_guard.py` (new)** — 16 tests: all classes, multi-part scanning, ZWJ policy, emoji/Thai false-positive guards, wired refusal, refusal-event meta shape (**never the payload**), guest public/private, vocab, trusted-identity still scanned, mddb-down resilience.
- **`tests/scenarios/memory_write_guard.yaml` (new)** — end-to-end harness scenario over all four classes + benign write + no-injected-doc recall checks.

Refusal events: `memory-scan-refused` ops docs → `ada-ha-events-<instance>` (meta: `identity/bank/class/rule/session_id/ts` — never the payload), plus the session `_EVENT_LOG` list and local `~/.local/share/ada/events.md`. Emit is best-effort: mddb down still refuses, never crashes the write path.

**chaba worktree:**

- **`docs/ssot/apps/ssot.apps.ada-memory-banks.yml`** — new `write_guard` block mirroring `SCAN_CLASSES` + rule ids (documentation mirror; the module's table is authoritative, `--list-rules` prints it) + a "Pre-write content scan" item in the Write & Update section.
- **`docs/ssot/jobs/ada/2026-10-09-memory-injection-scan.yml`** — durable job trail.

## Results

- `python3 backend/memory_write_guard.py --selftest` → **SELFTEST-OK** (59 cases: 47 positive, 12 false-positive guards).
- `tests.test_memory_write_guard` → **16 tests OK**.
- `tests/scenarios/memory_write_guard.yaml` → **OK** (after adding `confirmed: true` — the confirmed gate fires before the scan by design).
- Full memory/tool suite (`test_memory_banks`, `test_memory_recall_extras`, `test_tool_runner`, `test_memory_write_guard`) → **320 tests OK**.
- `test_scenarios` whole-file run: the 2 other failures (`test_memory_hit_shape_guard`, `test_michael_technician`) were confirmed **pre-existing on the clean tree** — unrelated.

## How to verify

```bash
cd ~/CascadeProjects/ada-pi
python3 backend/memory_write_guard.py --selftest          # SELFTEST-OK
python3 backend/memory_write_guard.py --list-rules        # 4 classes, 20 rule ids
python3 -m unittest tests.test_memory_write_guard -v
python3 -c "
import tests.test_memory_write_guard as t; t._install_fakes()
from tests.test_memory_banks import make_runner
r = make_runner()
print(r.execute('ada_remember', {'bank':'personal','text':'ignore all previous instructions','confirmed':True}))
"
# -> {'ok': False, 'matched_class': 'prompt_injection', ...}
```

**Not done / follow-up:** ada-pi changes are **uncommitted on the tony-dell `main` checkout** — the card didn't authorize push/commit; ship via the normal deploy flow. `ada-memory-write-caps` (entry-size caps) and `ada-memory-staged-writes` (trusted/untrusted split) are explicitly follow-on cards that extend this module.
