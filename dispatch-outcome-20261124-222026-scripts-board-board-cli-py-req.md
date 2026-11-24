# Dispatch outcome — board-cli-request-ask-field (2026-11-24 22:20)

## Result: already fixed on master — verified live, no code change needed

The card asked to change `"text": args.text` → `"ask": args.text` in the
`scripts/board/board-cli.py` `request` branch. On inspection the worktree HEAD
(and idc03's served checkout) already sends `"ask": args.text` at
`scripts/board/board-cli.py:240` — the fix landed earlier today via commit
`80101e81ce5` (the KNB-1257 work committed 2026-11-09 as `3b4cd22430` /
PR #138 evidently reached master through the board-api sync path; `git
merge-base` shows `3b4cd22430` itself is not an ancestor, but the resulting
content is identical).

## Verification performed (all via `--ssh idc03`, real board-api)

1. Created scratch card `board-cli-ask-verify-scratch` (KNB-1331) via
   `board-cli.py --ssh idc03 card`.
2. `board-cli.py --ssh idc03 request board-cli-ask-verify-scratch "..." --options "proceed|hold"`
   — first invocation's output was lost to a shell pipe mishap, but the
   server-side write landed; a retry returned HTTP 400
   `duplicate request id verify-ask-field-lands-dispatch-board-cl-ebcf9d`,
   proving the `ask` payload was accepted by `do_request` (which reads
   `body["ask"]` and would 400 on `text`).
3. `board-cli.py --ssh idc03 get` confirmed the request recorded with
   `ask: "verify ask field lands ..."`, `status: open`, options `["proceed"]`.
4. `respond` round-trip: `--ssh idc03 respond ... <rid> "proceed — verify ok"`
   → `{"ok": true, "message": "answer saved"}` — confirms `id` +
   `request_id` + `answer` + `from` contract (the 2026-11-09 comms bug about
   missing card id is also fixed; `do_respond` accepts `answer` or `text`).
5. Scratch card closed via `action close` → `verified: true`.

## Endpoint field-name audit (spec's "check those too" item)

- `POST /comment` — board-api reads `body["text"]` (board-api.py:6162);
  CLI sends `"text"`. Correct. Live-proven by this session's progress comms.
- `POST /request` — reads `body["ask"]` (board-api.py:2396); CLI now sends
  `"ask"`. Correct.
- `POST /respond` — reads `body["answer"]` with `body["text"]` fallback
  (board-api.py:2092), plus `id`, `request_id`, `from`; CLI sends all four.
  Correct — live-proven above.

## Files changed

None — no diff; fix was already present. Deliverable is this verification.

## How to verify

```
python3 scripts/board/board-cli.py --ssh idc03 get board-cli-ask-verify-scratch
# card shows requests[0].ask populated, status answered; column done
```

lessons:
- board-cli --ssh builds the JSON payload locally and pipes it to the remote
  `__api` mode — it exercises the worktree's payload code, not the remote
  checkout's parser; a "duplicate request id" 400 is itself proof the first
  post landed when client output is lost.
- Shell pipelines inside argparse values (`--options a|b`) must be quoted —
  an unquoted `|` turns the CLI into half a pipeline and the POST can still
  land server-side.
- Card specs filed against line numbers go stale fast on this repo; check
  `git log -S`/blame before editing — this one was already fixed.
