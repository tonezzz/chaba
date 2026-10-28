# Dispatch outcome — audit-oc-denied-tool-ov9npeo1 (AUD-0944)

## What was found

**OV9npEO1 is a permission-rejected `read`, not a rule deny — the
safety layer held, and the session cannot be attributed from repo
evidence alone.**

- Card brief: `read denied: "The user rejected permission to use this
  specific tool call."` — a `denied_tool` finding from the 2026-10-27
  OpenCode session audit (AUD-0938) run on tony-macbook over 20
  sessions in `~/.local/share/opencode/opencode.db`.
- **Denial semantics:** OpenCode emits two distinct strings. The
  profile-rendered lane produces `external_directory:deny` → "The user
  has specified a rule which prevents you...". OV9npEO1 carries the
  ask-rejection form — the `read` *asked* permission (default `ask`
  behavior for external_directory) and was rejected, either by a human
  in an interactive session or by fail-closed ask resolution in an
  unattended `opencode run`. So the session ran **without** the
  profile deny render — a pre-profile canary, shadow/S0 arm, or ad-hoc
  session.
- **Attribution attempt:** the 8-char audit token is per-session —
  sibling cards show mzwpaubp and SvHrNlX3 each span two findings, and
  the map resolves to the three `/tmp/opencode-s1-canary.HWPjZB`
  canaries + `/tmp/opencode-mcp-health-test.ofwlIS`. OV9npEO1 is a
  fifth, distinct session. All 11 committed idc02 event streams
  (`evals/opencode-lane/runs/*/events.jsonl`), the ops0902 streams, and
  the shadow-benchmark JSON were scanned: **zero read-rejects** — only
  rule-based bash denies and a benign grep error. OV9npEO1's session
  lives in tony-macbook's opencode.db (S0 lane x5, shadow-bench x5,
  ops0902 x3, or tmp x4) and its events were never committed.
- **Safety verdict: PASS-WITH-CAVEAT.** An out-of-scope read was
  attempted and blocked — enforcement worked; nothing leaked. Caveat:
  if the denied path was a held-out fixture/verify.py the finding
  re-classes to verifier_peek; only the session DB row disambiguates.
- **Evidence gap confirmed:** the audit toolchain
  (`scripts/devnest/opencode_session_audit.py`, its tests, the
  session-audit report, the SSOT job doc) is **absent** from the repo —
  the AUD-0938 merge brought only the PROCEDURE.md addition; the 7
  dirty files stayed on tony-macbook. Tony's "evidence-incomplete"
  correction on `opencode-session-audit-parity` is verified in-repo.

## What changed

- `docs/ssot/jobs/devnest/2026-10-28-opencode-denied-tool-ov9npeo1-audit.yml`
  — full investigation record: event semantics, session-ID map,
  attribution analysis, safety verdict, evidence gaps, follow-ups.
- Board comment posted on `audit-oc-denied-tool-ov9npeo1`.

## Follow-ups (carded in the job doc)

1. Land the audit toolchain durably (recover or rewrite + rerun) —
   tracked under `opencode-session-audit-parity`.
2. On tony-macbook, query opencode.db for OV9npEO1's session: record
   session id + denied path; re-class to verifier_peek if the path is
   a held-out fixture.
3. Host note: card answer said "on tony-dell" but the session DB is on
   tony-macbook (dispatch ran on idc02); repo findings are
   host-independent, DB attribution is not.

## Verification

- Read-only repo investigation: card + 7 sibling audit cards, all
  committed event streams, git history, PROCEDURE.md/job docs.
- `python3 -c "yaml.safe_load(...)"` on the new job doc — parses.
