=== SSOT Optimization Suggestions ===

Generated: 2026-08-18T23:29:01.284Z
Bloat warnings: 27
Data-isolation warnings: 2
Other warnings: 0

## Bloat candidates (highest priority)

- `apps/ssot.apps.helm.yml`: Bloat: 12 sections exceeds review threshold of 10
- `apps/ssot.apps.helm.yml`: Bloat: 69 items exceeds hard threshold of 60
- `apps/ssot.apps.map3d.yml`: Bloat: 11 sections exceeds review threshold of 10
- `apps/ssot.apps.map3d.yml`: Bloat: 46 items exceeds review threshold of 45
- `apps/ssot.apps.raceman.yml`: Bloat: 46 items exceeds review threshold of 45
- `apps/ssot.apps.track4.yml`: Bloat: 12 sections exceeds review threshold of 10
- `apps/ssot.apps.track4.yml`: Bloat: 61 items exceeds hard threshold of 60
- `apps/ssot.apps.yomi.yml`: Bloat: 47 items exceeds review threshold of 45
- `infrastructure/performance-baselines.yml`: Bloat: 400 lines exceeds review threshold of 350
- `infrastructure/ssot.gemini-models.yml`: Bloat: 739 lines exceeds review threshold of 350
- `infrastructure/ssot.health.home.yml`: Bloat: 633 lines exceeds review threshold of 350
- `infrastructure/ssot.health.mobile.yml`: Bloat: 470 lines exceeds review threshold of 350
- `infrastructure/ssot.mcp-debug.yml`: Bloat: 648 lines exceeds review threshold of 350
- `infrastructure/ssot.mcp.yml`: Bloat: 366 lines exceeds review threshold of 350
- `infrastructure/ssot.services.yml`: Bloat: 388 lines exceeds review threshold of 350
- `ssot.focus.sessions.yml`: Bloat: 382 lines exceeds review threshold of 350
- `ssot.focus.yml`: Bloat: 1584 lines exceeds hard threshold of 750
- `ssot.focus.yml`: Bloat: 87 items exceeds hard threshold of 60
- `ssot.improvements.archive.2026.yml`: Bloat: 1003 lines exceeds hard threshold of 750
- `ssot.improvements.yml`: Bloat: 535 lines exceeds review threshold of 350
- `ssot.index.yml`: Bloat: 367 lines exceeds review threshold of 350
- `ssot.index.yml`: Bloat: 79 items exceeds hard threshold of 60
- `ssot.mysystem.home.yml`: Bloat: 12 sections exceeds review threshold of 10
- `ssot.mysystem.home.yml`: Bloat: 59 items exceeds review threshold of 45
- `ssot.mysystem.macbook.yml`: Bloat: 11 sections exceeds review threshold of 10
- `ssot.mysystem.macbook.yml`: Bloat: 67 items exceeds hard threshold of 60
- `ssot.registry.yml`: Bloat: 743 lines exceeds review threshold of 350

## Data isolation candidates

- `infrastructure/ssot.mcp.yml`: Data isolation: possible secret value embedded in YAML
- `infrastructure/ssot.services.yml`: Data isolation: possible secret value embedded in YAML

## Other warnings

No other warnings.

---
_Report produced by scripts/ssot-optimize.mjs in 4752ms_
