---
category: troubleshooting
status: verified
created: 2026-11-26
source: auto-kb
---

# Root cause (verified 2026-11-26): Devin Desktop (Windsurf fo

## What it is

- Root cause (verified 2026-11-26): Devin Desktop (Windsurf fork) on tony-dell produced a "starting error" that was actually a GPU child crash loop — fresh Crashpad minidump (exception code 5 on a child thread) at the exact death ~10s after every launch, with no OOM or kernel trap

## Context/Background

Created 2026-11-26 from automated KB creation workflow.



## Key Details

### Technical Details
- **Generated**: 2026-11-26
- **Source**: Automated KB creation skill
- **Category**: troubleshooting

### Implementation
- Root cause (verified 2026-11-26): Devin Desktop (Windsurf fork) on tony-dell produced a "starting error" that was actually a GPU child crash loop — fresh Crashpad minidump (exception code 5 on a child thread) at the exact death ~10s after every launch, with no OOM or kernel trap. This is distinct from the earlier XDG_RUNTIME_DIR single-instance split-brain.
- Workaround verified: relaunching with --disable-gpu stayed stable with a window on :20. The persistent fix is "disable-hardware-acceleration": true in the app's argv.json — confirmed in the installed mainImpl.js to call app.disableHardwareAcceleration(). The key "disable-gpu" in argv.json is silently ignored, even though --disable-gpu on the command line works.
- Configuration path pattern: product.json dataFolderName ".devin" means the app reads ~/.devin/argv.json, NOT its user-data dir ~/.config/Devin/argv.json. Check BOTH the config path and the supported key against the installed product.json/mainImpl.js before claiming a setting is pinned.
- Config-file pattern: argv.json is JSONC — preserve comments and host-specific keys (e.g. crash-reporter-id) when pinning a value. Use an idempotent regex edit with a timestamped backup (ansible/files/devin-argv-pin.py from the chaba repo) rather than overwriting the file.
- Watchdog pitfall: a stale modal "Devin" X window can make devin-desktop-watchdog.sh TERM a genuinely healthy GUI; confirm the window no longer exists on the relevant displays and clear hang state before blaming the app fix.
- Verification pattern for GUI fixes: visible window on the real display, singleton socket /run/user/$UID/vscode-*-main.sock, code.lock matching the live main PID, and expected GPU switch (--use-gl=disabled) in the gpu-process cmdline.
- Ansible convergence pattern: --check --diff --limit host, real run with --limit, then a re-check proving changed=0, with no handler so a healthy running instance is not restarted.

## Related Documentation

- **[auto-chaba-creation.md](../../.windsurf/workflows/auto-chaba-creation.md)** - Automated KB creation workflow

## Tags

- **auto-generated**: Automatically created KB entry
- **2026**: Year tag
