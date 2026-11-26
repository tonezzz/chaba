# Dispatch outcome — cms-auto-cctv-roster (2026-11-26)

## What was found

The `cctv-roster` CMS automation staleness was an **intentionally parked
scheduler**, not a break — confirming Tony's 15:15 +07 triage on the card.

Verified live (MDDB `ada-cms-automation/cctv-roster` + `timer-timeline-*`
CMS pages, all current as of 2026-11-26 ~15:16 ICT):

- The registry doc's `last_run`/`last_status` are written exclusively by
  `scripts/cam-wall/cam-wall-roster-audit.py` (`written_by:
  cam-wall-roster-audit`).
- Its only remaining systemd timer is `cam-wall-roster-audit.timer` on
  **tony-omen**, and it is **disabled** — parked after the 2026-11-25 run
  ended with repeated `mddb add ... Remote end closed connection` errors.
- The tony-dell unit was already retired/not-found (2026-11-12 sweep).
- Sibling `cam-wall-cms-vps.timer` on idc03 is disabled for the same
  MDDB write-failure reason.

## What changed

1. **Live registry** (`ada-cms-automation/cctv-roster`, MDDB `/v1/add`):
   `enabled: false` + `disabled_reason` documenting the park and the
   re-enable path. `cms-auto-health.judge()` returns `ok — disabled — no
   check`, so the open card auto-closes via the normal GREEN_WINDOWS path
   and no new dispatches burn on it. Reversible: flip `enabled` back to
   `true` (Tony's call — the MDDB write-failure root cause is still open).
2. **`docs/ssot/infrastructure/ssot.audit.hosts.yml`** (committed on
   `dispatch/20261126-151845-cms-automation-cctv-roster-sta`, commit
   1c9dc82cd43):
   - tony-dell `cam-wall-roster-audit.timer`: moved `expected_services` →
     `expected_absent` (unit retired).
   - tony-omen `cam-wall-roster-audit.timer`: added with
     `expected_state: inactive` + PARKED note.
   - idc03 `cam-wall-cms-vps.timer`: `expected_state: inactive` + PARKED
     note.
   Both `timer-sentinel` and drift-reconcile key off `expected_state`, so
   the deliberate disables stop carding as failures.
3. **Trail doc**: `docs/ssot/jobs/cms/2026-11-26-cctv-roster-parked.yml`.

## How to verify

- `POST /v1/get {collection: ada-cms-automation, key: cctv-roster}` →
  `enabled: false` with `disabled_reason`.
- Next `kanban-sync` tick of `cms-auto-health` judges the slug `ok`;
  card `cms-auto-cctv-roster` auto-closes after 2 green ticks.
- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/infrastructure/ssot.audit.hosts.yml'))"` passes; pre-commit SSOT validation passed.

## Notes / follow-ups (in trail doc)

- `cam-wall-cms.timer` / `cam-wall-cms-kk.timer` still declared
  expected-active on tony-dell but absent from its timer-timeline — likely
  same VPS-lane retirement class; needs a host that can reach dell.
- Root cause of the MDDB "Remote end closed" write failures that parked
  both cam-wall timers remains open.

lessons:
- cms-auto-health has no "parked scheduler" state — the registry doc's own `enabled:false` knob is the intended way to park an automation; flipping it stops carding without any code change.
- timer-sentinel + drift-reconcile both read `expected_state` from ssot.audit.hosts.yml — marking deliberately-disabled units `expected_state: inactive` (or moving retired ones to `expected_absent`) is the durable way to stop false-positive cards; do it in the same dispatch that parks the job.
- The timer-timeline-* CMS pages are a reliable live source for per-host timer enabled/last-run state when SSH is unavailable — fresher than card comms.
- MDDB `/v1/get` + `/v1/add` on ada-cms-automation is directly reachable from dispatch worktrees; preserve the doc's `meta` (it's a list-valued map) and append to `written_by` for provenance.
