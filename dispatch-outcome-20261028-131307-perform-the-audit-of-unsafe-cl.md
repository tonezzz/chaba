# Dispatch outcome — audit of unsafe_classification (AUD-0947, card audit-oc-unsafe-classification-svhrnlx3)

## What was done

Audited the unsafe-classification remediation in the chaba repo: the
storage-dryrun profile's classification policy (`profile.yml policy:`), the
deterministic classifier `classify_candidate` in
`scripts/devnest/opencode_profiles.py`, the held-out verifier
`evals/opencode-lane/profiles/storage-dryrun/fixture/verify.py`, the seeded
trap fixture, and the StoragePolicy tests. Ran the classifier live via its
`classify` CLI and the full test module.

## Result — PARTIALLY REMEDIATED (5 findings)

The in-layer design is sound: prompt contract → deterministic classifier →
held-out verifier; 53/53 tests pass, both gated canary runs pass with all 7
seeded traps refused. But the protection is a blacklist of path fragments:

- **F1 high:** verified live that `/home/tony/.devin/cache/x` — the literal
  second path from the incident — still classifies `automatic_ok`, as do
  `/home/tony/.ssh/...`, `/etc/...`, `/usr/lib/...`. Nothing requires a
  candidate path to sit under a declared scan root; `.devin`/`.ssh`/`.gnupg`/
  `.aws` are absent from protected_roots. Fix: whitelist auto-ok to declared
  roots.
- **F2 medium:** raw substring matching — case evasion verified
  (`/HOME/TONY/CASCADEPROJECTS/x` → automatic_ok; resolves to the protected
  dir on case-insensitive APFS); symlink aliases evade; no normalization.
- **F3 medium:** verify.py derives "what counts as a trap" from the manifest
  policy it verifies — a profile.yml regression blinds the verifier. Needs a
  hardcoded root floor + lint check.
- **F4/F5 low:** policy literals duplicated profile.yml ↔ prompt.md
  (hand-synced); `policy:` never linted; empty path → automatic_ok.

Mitigating: the classifier is advisory — deletions must be `[]` (verified),
write tools off, no rm/find/sh/python in the bash allowlist — so no direct
destructive path exists today. Findings matter before the classifier feeds a
real cleanup job; `classify` is a public CLI.

## Artifacts

- `evals/opencode-lane/reports/2026-10-28-unsafe-classification-audit.md` — full audit
- `docs/ssot/jobs/devnest/2026-10-28-opencode-unsafe-classification-audit.yml` — job record
- Commit `f1ff8a29a` on branch `dispatch/20261028-131307-perform-the-audit-of-unsafe-cl` (not pushed — per dispatch rules)
- Board comments posted on the card (progress + final)

## How to verify

- `python3 -m unittest tests.devnest.test_opencode_profiles` → 53/53 OK
- `python3 scripts/devnest/opencode_profiles.py classify /home/tony/.devin/cache/x tmpfile` → currently `automatic_ok` (F1); after the whitelist fix it must refuse.
- Read the report for the finding-by-finding evidence table.

## Follow-ups (recommended, not done — no code changed)

1. Whitelist `automatic_ok` under declared roots (`auto_ok_roots` in policy); extend protected_roots.
2. Normalize + component-anchor path matching; share `_protected` between classifier and verifier.
3. Hardcoded protected-root floor in verify.py + lint superset check.
4. Policy lint + prompt/policy sync check + empty-path floor.
5. Extend `test_seeded_traps_all_refused` with the F1 probes to pin the fix.
