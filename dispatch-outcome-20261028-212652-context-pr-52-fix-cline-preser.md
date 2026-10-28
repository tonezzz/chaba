# Dispatch outcome — cline-kanban-offline-image-build (KNB-0968)

## Headline

The shutdown guard is **already deployed** and a **fully offline rebuild path
exists and was tested**. No registry access is needed for repo-file-only
changes like PR #52.

## What was found (verified on con01)

- `localhost/cline-kanban:0.1.70` = image `d8427f43`, built 15:24:20 CET
  2026-10-28 by an operator session (podman event journal, build m=+254s).
  Units `cline-kanban.service` + `cline-kanban-proxy.service` restarted onto
  it at 15:24:53–56 CET, ~2 min before this dispatch opened. Running process:
  `kanban --host 0.0.0.0 --port 3485 --no-open --no-passcode --skip-shutdown-cleanup`.
- `kanban --help` inside the running container confirms
  `--skip-shutdown-cleanup` is a supported flag of installed `kanban@0.1.70`.
- `bash stacks/con01/cline-kanban/verify.sh` on con01: **PASS** (units active,
  unauth 401, auth 200). No secret values exposed.
- Preserved tags intact: `0.1.70-pre-shutdown-guard` (`9c55bd3d`),
  `0.1.70-pre-pr45` (`fa703215`). Isolated pack untouched. No restart or task
  run performed by this session.

## Tested offline build path

PR #52 changed only `entrypoint.sh`, which the image `COPY`s — `kanban@0.1.70`
is unchanged. Tested on con01:

```
podman build --network=none \
  -f stacks/con01/cline-kanban/Containerfile.offline \
  -t localhost/cline-kanban-offline-verify:0.1.70 \
  stacks/con01/cline-kanban
```

Build succeeded with zero external fetches. Content comparison vs the
deployed image `d8427f43`: the entire
`/usr/local/lib/node_modules/kanban` tree is **byte-identical**
(sha256-of-hashes `e9e29931…`), `dist/cli.js` (sed-patched) identical, all
`/opt/cline-kanban/*` identical. `podman image diff`'s ~32k entries were
mtime-only metadata and npm/apt bookkeeping — no content drift. Scratch tag
and temp file removed afterward; image store back to the 3 declared tags.

## Minimum registry access (only for full Containerfile rebuilds)

Needed only when base OS packages or the kanban version change:

- `registry-1.docker.io:443` + `auth.docker.io:443` +
  `production.cloudflare.docker.com:443` — `node:22.20.0-bookworm-slim`
- `deb.debian.org:80` — bookworm/bookworm-updates/debian-security for
  ca-certificates, git, g++, make, python3
- `registry.npmjs.org:443` — `kanban@0.1.70` tarball
  (`/kanban/-/kanban-0.1.70.tgz`) + dependency tree

Earlier EAI_AGAIN was an offline (`--network=none`-style) attempt, not a host
egress problem — con01 reached the registry fine at 15:19 CET.

## Repo changes (branch `dispatch/20261028-212652-context-pr-52-fix-cline-preser`, commit `30bf5a023`, not pushed)

- `stacks/con01/cline-kanban/Containerfile.offline` — offline layered recipe
  (ARG-overridable `BASE_IMAGE`, no apt/npm/docker.io steps).
- `stacks/con01/cline-kanban/stack.yml` — registry requirements scoped to full
  builds; exact minimum endpoints + offline path documented.
- `tests/test_cline_kanban_proxy.mjs` — regression test pinning the offline
  recipe's base tag and COPY set. `node --test` → 8/8 pass.
- `docs/ssot/jobs/infrastructure/2026-10-28-cline-kanban-offline-image-build.yml`
  — job record. `ssot-validate-all.mjs`: 3234 files valid, 0 errors.

## OpenCode gate

Moot for this card: no code change beyond docs/recipe was required; nothing
was armed on OpenCode and no paid model was used.

## How to verify

1. `ssh tony@con01 podman images | grep cline` — three tags as listed above.
2. `ssh tony@con01 'podman exec cline-kanban sh -c "tr \\0 \" \" </proc/1/cmdline"'`
   — shows `--skip-shutdown-cleanup`.
3. `ssh tony@con01 'cd ~/CascadeProjects/chaba/stacks/con01/cline-kanban && bash verify.sh'`
   — PASS.
4. Offline rebuild repro: run the `podman build --network=none` command above
   with a scratch tag.

## Remaining / open

- Deploy is live; the card can move to review/done after Tony confirms the
  smoke-task path (nest-worker adapter) — that retry is a separate, previously
  gated step.
