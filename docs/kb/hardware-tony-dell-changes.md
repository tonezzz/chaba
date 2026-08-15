---
hostname: tony-dell
date: 2026-07-21
tags: [hardware, changelog]
status: active
---

# tony-dell — Change log

| Date | Change | Reason | Result | Reference |
|------|--------|--------|--------|-----------|
| 2026-06-25 | Disk health check with `smartmontools` | Establish hardware baseline | Internal Seagate HDD has 8 pending sectors and 8 offline uncorrectable sectors; SMART still PASSED, monitor ongoing | `hardware/tony-dell/2026-06-25-sensors.md` |
| 2026-07-21 | Updated IP in KB dashboard/context from `192.168.1.37` to current lease | Current-context refresh | Dashboard now reflects `192.168.1.37` as the known address | `current-context.md`, `hardware/README.md` |

## Notes

- No configuration changes have been applied to this machine yet; only monitoring and documentation.
