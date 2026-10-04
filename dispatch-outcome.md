# dispatch-outcome: ada-memory inbox triage round 2

## What changed

Triaged the live Ada-memory inbox on idc01 (`~/CascadeProjects/chaba-vault/docs/ada-memory/inbox/`), which held **654 files** — far more than the card's ~194 estimate (the estimate predated weeks of accumulated draft + voice exports).

Breakdown of the 654:

| population | files | handling |
|---|---|---|
| MDDB draft docs | 368 | classified per content |
| voice-active promotes | 64 | classified per content |
| stale exports (doc already active/superseded/retracted) | 148 | file removed, MDDB untouched |
| orphans (file, no MDDB doc) | 44 | classified; tombstones created where archived |
| devin-handoff queue | ~81 | left untouched (round-1 convention) |

Bucket results (MDDB writes, no deletions):

- **keep/promote: 195** — draft→active + voice-active stamped `written_by=obsidian-vault`; 191 vault files moved to their bank dirs (general/, people/, personal/tony/, personal-kk/, personal-testo/, purchase/, note/, tony-projects/)
- **supersede: 76** — `status=superseded` + `superseded_by` link; all 87 superseded docs verified to resolve to live targets
- **archive/retract: 168** — `status=retracted` + `retracted_reason` (empty/transient/test/meta/gap-note content preserved, excluded from recall)
- **rehomed: 2** — misrouted content recreated in the correct bank (`mano-address` → personal-tony, `kk-flood-saraburi-interest` → personal-kk) with the originals superseded to the new docs
- 148 stale export files removed (docs already terminal elsewhere)
- `devin-handoff` (81 files) and `ideas` queues left alone per round-1

Inbox after: **81 files, all devin-handoff**. Draft docs across all writable banks: **0**.

## Trail / artifacts

- Job trail: `docs/ssot/jobs/ada/2026-10-04-memory-inbox-triage-round2.yml`
- Decision map + executor + file plan (reproducible): `.triage/decisions.py`, `.triage/execute.py`, `.triage/file-ops.json`, `.triage/<bank>.txt` review listings

## How to verify

```bash
# inbox state
ssh idc01 'find ~/CascadeProjects/chaba-vault/docs/ada-memory/inbox -name "*.md" | wc -l'   # -> 81

# MDDB statuses (0 drafts expected in writable banks)
python3 - <<'EOF'
import json, urllib.request
from collections import Counter
for c in ["ada-ha-bank-general","ada-ha-bank-people","ada-ha-bank-personal-tony",
          "ada-ha-bank-personal-kk","ada-ha-bank-projects-tony","ada-ha-bank-note-tony",
          "ada-ha-bank-developer-tony","ada-ha-bank-purchase"]:
    r=urllib.request.Request("http://100.74.146.0:11023/v1/search",
        data=json.dumps({"collection":c,"limit":2000}).encode(),
        headers={"Content-Type":"application/json"})
    docs=json.loads(urllib.request.urlopen(r).read())
    print(c, Counter((d.get("meta") or {}).get("status",["?"])[0] for d in docs))
EOF

# sync convergence on idc01
ssh idc01 'cd ~/CascadeProjects/chaba-vault && python3 scripts/ada/sync-ada-memory-to-mddb.py --dry-run | grep -c CONFLICT'   # -> 0
```

## Notes / leftovers

- chaba-vault on idc01 has **no git identity configured** — the 351 changed vault paths are uncommitted (rules forbid touching git config; files on disk are the live state the sync reads).
- `developer` bank has no vault directory; its 4 triaged docs were handled MDDB-only.
- The next hourly `ada-memory-sync` (13:00 +07) will normalize residual meta churn (`last_used`/`use_count` drops on vault push — same behavior as round-1).
- `~194` in the card spec was stale; real population documented above.
