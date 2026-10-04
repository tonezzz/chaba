# Dispatch outcome — fix-api-key-issue-on-cms-page

## Task
"Fix API key issue on CMS page on idc01.taila0626a.ts.net repo:chaba"

## Result — parked, not fixed
The original dispatch session (2026-10-03 23:20 ICT) ended before any work:
its first `exec` was rejected, which ends a dispatch session. The follow-up
session was asked to finish & close, so the findings below are parked for a
follow-up to execute. **Note: the fix likely belongs in the `ada-pi` repo,
not `chaba`** — the CMS page code lives there.

## What was found (verified live, 2026-10-04)

- The CMS page is `pwa/cms/index.html` in `tonezzz/ada-pi`, served on idc01 by
  two services, both with `ADA_INSTANCE_ID=tony` (same keys file
  `~/.config/secrets/ada-ha-tony-keys.json`):
  - `ada-pi-pwa.service` (127.0.0.1:8001) → `https://idc01.taila0626a.ts.net/cms/`
  - `ada-ha-tony.service` (127.0.0.1:8002) → `…/apps/ha/ada-tony/cms/`
    (also reachable via mn01 → `https://mn01.taila0626a.ts.net/apps/ha/ada-tony/cms/`)
- Auth chain: `pwa_server._require_api_key` → `auth.caller_name` accepts
  `x-api-key` header → `?api_key=` query → `ada_session` cookie; then
  `auth.enforce_device` binds file-issued keys to `x-device-id` (TOFU),
  `device="*"` disables binding.
- The `cms-viewer` issued key exists with `device=*` (shared — made for
  viewer URLs/iframes). Verified: `GET /api/cms/pages` → 200 on BOTH mounts.
- Reproduced symptom in logs: `GET /api/cms/pages?limit=500` → **401** from
  `tony-omen` (100.75.102.88) at **2026-10-03 23:19:50** — one minute before
  the task was filed. That 401 is the frontend's page-list call; the page
  then shows the "Unlock Pages — API key required (or invalid for this
  device)" overlay. So the reported issue = CMS page demanded a key when
  opened on tony-omen.
- Frontend: `getApiKey()` reads `?api_key=` once (stores to localStorage
  `ada_api_key`, strips from URL); `apiFetch` sends `x-api-key` +
  `x-device-id`; 401 → unlock overlay. The page never calls
  `POST /api/auth/session`, so no cookie is minted from a stored key.
- `stacks/web/public/apps/apps.yml` `ada-cms` entry links to the CMS with no
  key parameter — any fresh browser hits the unlock overlay.

## Fix options for the follow-up (pick by intent)

1. If the goal is "open CMS on any of Tony's browsers without re-entering a
   key": share the viewer URL `…/cms/?api_key=<cms-viewer key>` once per
   browser (key persists in localStorage). The `cms-viewer` shared key is
   purpose-built for this (`device=*`). Do NOT commit the key anywhere —
   read it on idc01:
   `python3 -c "import json; print(json.load(open('~/.config/secrets/ada-ha-tony-keys.json'.replace('~','/home/tony')))['cms-viewer']['key'])"`
2. If the stored key is rejected as "invalid for this device": the issued key
   is device-bound — either `auth.unbind_device(<name>)` on idc01 (edit the
   keys file `device: null`) or re-pair via `/apps/ha/pair/` (view app →
   `/cms`).
3. Frontend improvement in ada-pi `pwa/cms/index.html`: on 401, first try
   `POST /api/auth/session` with the stored key to mint the `ada_session`
   cookie, and split the error message — "no key stored" vs "key invalid /
   device-bound" vs "key bound to another device (re-pair or unbind)".

## Artifacts left behind
- `docs/ssot/jobs/ada/2026-10-04-cms-page-api-key.yml` — full trail.
- `docs/ssot/focus-inbox/2026-10-04-1015-cms-page-api-key.yml` — triage item.

## How to verify after a fix
- Fresh browser/profile on tony-omen opens
  `https://idc01.taila0626a.ts.net/cms/` and lists pages without the unlock
  overlay (or unlocks once with the shared key and stays unlocked).
- `curl -s -o /dev/null -w '%{http_code}' -H "x-api-key: <cms-viewer>" \
  https://idc01.taila0626a.ts.net/api/cms/pages` → 200.
