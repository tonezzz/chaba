# vision-qa bench — kk-mac VLM run

entity: `ollama` model: `qwen2.5vl:7b` cases: 20 latency mean 2.1s total 42.6s

| metric | score | threshold | verdict |
|---|---|---|---|
| overall_accuracy | 0.85 | >= 0.8 | PASS |
| stock_lane_accuracy | 0.8462 | >= 0.8 | PASS |
| ui_lane_accuracy | 0.8571 | >= 0.7 | PASS |
| defect_recall | 0.75 | >= 0.75 | PASS |
| defect_specificity | 1.0 | - | - |
| parse_failures | 0 | <= 0 | PASS |

per-kind:
```json
{
  "stock/defect": 0.8333,
  "stock/match": 0.8571,
  "ui/triage": 0.8571
}
```

## confusion (gold -> predicted counts)
```json
{
  "empty_state": {
    "empty_state": 1
  },
  "error_state": {
    "error_state": 2
  },
  "layout_bug": {
    "ok": 1,
    "layout_bug": 1
  },
  "no": {
    "no": 5
  },
  "ok": {
    "ok": 2
  },
  "yes": {
    "no": 2,
    "yes": 6
  }
}
```

NOTE: thresholds are the provisional 'usable lane' bar for stock visual QA — not the nest-bench T3 gate.

## per-case

| case | lane | gold | predicted | s | ok |
|---|---|---|---|---|---|
| stock-match-001 | stock | yes | no | 0.5 | n |
| stock-match-002 | stock | yes | yes | 0.5 | y |
| stock-match-003 | stock | yes | yes | 2.6 | y |
| stock-match-004 | stock | yes | yes | 2.6 | y |
| stock-mismatch-001 | stock | no | no | 2.8 | y |
| stock-mismatch-002 | stock | no | no | 0.6 | y |
| stock-mismatch-003 | stock | no | no | 2.8 | y |
| stock-defect-001 | stock | yes | yes | 2.6 | y |
| stock-defect-002 | stock | yes | yes | 2.6 | y |
| stock-defect-003 | stock | yes | yes | 2.6 | y |
| stock-defect-004 | stock | yes | no | 2.5 | n |
| stock-defect-005 | stock | no | no | 0.4 | y |
| stock-defect-006 | stock | no | no | 0.4 | y |
| ui-ok-001 | ui | ok | ok | 2.7 | y |
| ui-ok-002 | ui | ok | ok | 2.8 | y |
| ui-error-001 | ui | error_state | error_state | 2.7 | y |
| ui-error-002 | ui | error_state | error_state | 2.7 | y |
| ui-layout-001 | ui | layout_bug | ok | 2.8 | n |
| ui-layout-002 | ui | layout_bug | layout_bug | 2.7 | y |
| ui-empty-001 | ui | empty_state | empty_state | 2.7 | y |
