# Dispatch outcome — eval-ide-antigravity (mn01)

## What was done
- Downloaded Antigravity IDE for linux-x64 from antigravity.google (v2.5.5-4923483625488384,
  240MB tar.gz — no .deb offered). Unpacked to the task dir; runs as `antigravity-ide`.
- Installed `agy` CLI v1.4.7 via antigravity.google/cli/install.sh (~/.local/bin/agy).
  Full agent CLI: --print, --mode, --model, --output-format stream-json, MCP/plugins.
- Launched IDE on the live chrome-remote-desktop X session (:20). Onboarding reaches
  "Continue with Google"; IDE listens for OAuth on http://localhost:PORT/oauth-callback.
- Raised the Google-sign-in board request + posted the full OAuth URL to the card.
- Staged a demo repo ($TASK_DIR/demo-repo) with a seeded fib(10)=89 bug for the
  free-tier task.
- Confirmed `agy` has a quota_manager (FetchQuotaStatus -> QuotaSummaryGroup) that
  activates after login — "quota visible" criterion can be met via the CLI.
- Wrote SSOT trail: docs/ssot/jobs/devnest/2026-10-26-antigravity-ide-eval-mn01.yml

## Key findings
- **mn01 Chrome is broken (pre-existing host bug):** google-chrome 150.0.7871.128 on
  kernel 7.0.0-38 / Ubuntu 26.04 crash-loops every renderer — "Aw, Snap! error 15" even
  on data: URLs, reproduced with --no-sandbox/--disable-gpu/--disable-quic/
  --single-process/fresh profile. Network itself is fine (curl OK). Suspected
  Chrome-150 vs kernel-7.0 incompatibility. Worth its own card — Chrome on mn01
  cannot show any web content at all.
- Stale Chrome SingletonLock from host tony-usb (Sep 14) removed so Chrome starts.
- **Remote sign-in path:** `agy` OAuth uses redirect_uri=https://antigravity.google/
  oauth-callback (not localhost) — completable on any device; returns an
  authorization code to paste into the CLI. This bypasses the broken local browser.
- No GUI automation tools on mn01; drove X input via python-xlib + XTEST and
  screenshotted via xwd + a small parser (helpers in /tmp are ephemeral).

## Result
BLOCKED on Tony's Google login — the card's known gate. Board request + needs-input.txt
filed with the exact steps (open posted OAuth URL on any signed-in device, reply with
the authorization code). On resume: paste code into agy (restart for fresh URL if the
TUI died), run the bugfix task on demo-repo, read quota, and (optionally) re-attempt
IDE sign-in once mn01 Chrome is fixed.

## How to verify
- `ls ~/.local/bin/agy` (v1.4.7); IDE at $TASK_DIR/antigravity-dl/ide/
- Job file: docs/ssot/jobs/devnest/2026-10-26-antigravity-ide-eval-mn01.yml
- Board requests on eval-ide-antigravity carry the live OAuth URL + steps.
