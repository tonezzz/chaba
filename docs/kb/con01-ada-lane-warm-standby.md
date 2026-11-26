# con01 warm standby — ada-line-relay + ada-ha-tony

Card: `con01-ada-lane-warm-standby` (ADA-0784). Implements the proven con01 DR
pattern (mddb-follower, standby caddy-edge, ada-stt) for the two Ada lanes that
otherwise exist only on idc03.

## Topology (confirmed, not from memory)

| Role | Host | Unit / endpoint |
|---|---|---|
| Live LINE relay | idc03 | `ada-line-relay.service`, `127.0.0.1:8912` |
| Live Tony voice lane | idc03 | `ada-ha-tony.service`, `127.0.0.1:8002` |
| Warm standby (inert) | con01 | `*.service.standby`, canonical names **masked** |
| Standby public edge | con01 | `caddy-edge` Caddyfile already routes `/webhook/line`, `/relay-img/*`, `/apps/ha/ada-tony/*` to those local ports |
| Secrets source | idc03 | daily 03:00 `secrets-backup.timer` → age-encrypted tarball on con01 |

Targets confirmed from `docs/ssot/infrastructure/ssot.audit.hosts.yml` (con01 =
declared DR/absorber, "never a live writer") and `ansible/inventory/hosts.yml`
(`con01`, `100.72.146.39` tailnet / `169.58.241.208` public bind in Caddyfile).

## Installed state (2026-11-26)

`ansible/playbooks/deploy-con01-ada-warm-standby.yml` was run with
`--check --diff --limit con01` (0 unreachable / 0 failed) and converged with
`--limit con01` (idempotent: `changed=0` on re-run). It only:

- installed `~/.config/systemd/user/standby/{ada-ha-tony,ada-line-relay}.service.standby`
- masked `~/.config/systemd/user/{ada-ha-tony,ada-line-relay}.service -> /dev/null`
- reloaded the user systemd manager

`systemctl --user list-unit-files` reports both as `masked`; both are `inactive`.
No service was started, no edge/Caddy config changed, no DNS/firewall/package
change. The units **cannot** run while masked.

Preflight findings worth knowing before a failover:

- The 2026-11-26 03:00 tarball (`~/secrets-backup/secrets-20261126-0300.tar.age`)
  was verified to contain `line-bot.env`, `notebooklm-rest-api.env`,
  `tony-ha/backend.env`, `tony-ha/keys.json`, and both live unit files.
- con01 has `~/CascadeProjects/ada-voice` at `65a7464` (2026-10-22) but **no
  `.venv`** and no user-level `uvicorn`. Provisioning it is a gated step below.
- `caddy-edge.service` is **inactive** on con01 (stopped 2026-11-25). The image
  `docker.io/library/caddy:2` and cert pair are present. Starting it is a
  gated step below.
- The con01 Caddyfile already carries the required failover routes. **No
  Caddyfile edit is needed** and none was made.

## Failover procedure

> **Approval gate:** steps 4, 6, 7 and 8 are disruptive (package install, service
> start, edge start, DNS change). Do not run them without explicit Tony
> approval. Steps 1–3 and 5 are read-only/file-only.

### 0. Preconditions

Confirm idc03 is genuinely unavailable and that this is an approved failover,
not a routine restart. Prefer restoring idc03 over promoting con01.

### 1. Confirm the standby artifacts are intact (read-only)

```sh
ssh con01 'ls -l ~/.config/systemd/user/standby/*.service.standby; \
  ls -l ~/.config/systemd/user/ada-{ha-tony,line-relay}.service; \
  XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user list-unit-files \
  ada-ha-tony.service ada-line-relay.service --no-pager'
```

Expected: two `.service.standby` files, two symlinks → `/dev/null`, both units
`masked`.

### 2. Promote / verify the data + dependency lanes (read-only first)

- con01 `mddb-follower` must be healthy and, if idc03 is permanently gone,
  promoted per `stacks/con01/mddb-follower/stack.yml` restore note:

```sh
ssh con01 'curl -sf http://100.72.146.39:11123/v1/health | grep -q healthy && \
  curl -sf http://100.72.146.39:11123/v1/replication/status'
```

- `notebooklm-rest` on idc02 (`100.123.163.11:3011`) must still answer
  `/health` — the live `ada-ha-tony` dep-gate waits on it.

### 3. Restore only the needed env/secret files from the age tarball

The daily tarball already contains everything; extract only these paths into a
staging dir. **Never untar `.config/systemd/user` wholesale** — that would
overwrite con01's masks and all its other units.

```sh
ssh con01 'set -euo pipefail
  T=$(ls -t ~/secrets-backup/secrets-*.tar.age | head -1)
  S=$(mktemp -d)
  age -d -i ~/.config/secrets/backup-age.key "$T" | tar xz -C "$S" \
    .config/secrets/line-bot.env \
    .config/secrets/notebooklm-rest-api.env \
    .config/secrets/tony-ha/backend.env \
    .config/secrets/tony-ha/keys.json
  install -m 600 "$S/.config/secrets/line-bot.env" ~/.config/secrets/line-bot.env
  install -m 600 "$S/.config/secrets/notebooklm-rest-api.env" ~/.config/secrets/notebooklm-rest-api.env
  install -m 600 "$S/.config/secrets/tony-ha/backend.env" ~/.config/secrets/tony-ha/backend.env
  install -m 600 "$S/.config/secrets/tony-ha/keys.json" ~/.config/secrets/tony-ha/keys.json
  rm -rf "$S"
  echo "restored env files from $T"'
```

The standby units carry `MDDB_BASE_URL=http://100.72.146.39:11123` as a
post-`EnvironmentFile` override, so the stale idc03 `:11023` value in
`backend.env` is neutralised. Keep secrets in these files — never inline.

### 4. GATED — provision the runtime venv

con01's checkout is stale (`65a7464`, 2026-10-22) and has no venv. Align the
code with the live idc03 lane first, then build the venv:

```sh
ssh con01 'cd ~/CascadeProjects/ada-voice && \
  git fetch origin && git checkout origin/main && \
  python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt'
```

Note: `ai-edge-litert` is a heavy wheel; budget time and disk. This step
installs packages and changes a checkout — explicit approval required.

### 5. Unmask and install the standby units (file-only)

```sh
ssh con01 'set -euo pipefail
  cd ~/.config/systemd/user
  rm -f ada-ha-tony.service ada-line-relay.service       # drop the /dev/null masks
  cp standby/ada-ha-tony.service.standby ada-ha-tony.service
  cp standby/ada-line-relay.service.standby ada-line-relay.service
  XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user daemon-reload'
```

### 6. GATED — start in dependency order

```sh
ssh con01 'export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user enable --now ada-ha-tony.service
  for i in $(seq 1 60); do curl -sf http://127.0.0.1:8002/api/health -o /dev/null && break; sleep 5; done
  systemctl --user enable --now ada-line-relay.service
  systemctl --user is-active ada-ha-tony.service ada-line-relay.service'
```

Start `ada-ha-tony` **before** `ada-line-relay`; the relay's `ADA_WS_URL`
defaults to `ws://127.0.0.1:8002/ws` and it will not answer without it.

### 7. GATED — start the standby edge

`caddy-edge.service` was inactive as of 2026-11-26. Start it (no Caddyfile
edit — routes and cert pair are already present):

```sh
ssh con01 'export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user enable --now caddy-edge.service
  systemctl --user is-active caddy-edge.service'
```

### 8. GATED — repoint DNS and verify

Repoint the `api.surf-thailand.com` A record to `169.58.241.208` (Cloudflare),
then verify:

```sh
curl -sk --resolve api.surf-thailand.com:443:169.58.241.208 \
  https://api.surf-thailand.com/install -o /dev/null -w '%{http_code}\n'
curl -sf --resolve api.surf-thailand.com:443:169.58.241.208 \
  -X POST https://api.surf-thailand.com/webhook/line -o /dev/null -w '%{http_code}\n'
ssh con01 'ss -ltnp | grep -E ":8912|:8002"'
```

`200` on `/install` proves the edge; a signed LINE POST reaching the relay
(prove via relay journal, not the 403 signature-reject code) proves the lane.

## Rollback

1. Restore the Cloudflare A record to its prior value.
2. `ssh con01 'XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user disable --now ada-line-relay.service ada-ha-tony.service caddy-edge.service'`
3. Re-mask the two units:
   `ssh con01 'cd ~/.config/systemd/user && rm -f ada-ha-tony.service ada-line-relay.service && ln -s /dev/null ada-ha-tony.service && ln -s /dev/null ada-line-relay.service'`
4. Leave the extracted env files in place (600, they are the synced copies) or
   remove them if a clean standby is wanted; they are recreated from the
   tarball at the next failover.
5. Return the `ada-voice` checkout to its prior commit if step 4 was run.

## Lessons / gotchas

- A "standby unit" must be inert. Masking + a non-systemd `.standby` suffix
  survives accidental `enable`/`start` and fleet-wide globs; a plain disabled
  unit does not.
- `secrets-backup.sh` bundles all of `.config/systemd/user` — restoring the
  whole tarball on con01 would unmask these units and clobber con01-only
  timers. Extract only the named env files.
- The con01 `caddy-edge` route already existed; the real gap was the absent
  activation path (no venv, masked units, inactive edge), not a missing route.
- Ansible `file: state=link` follows the link for `owner`/`group` — never set
  them when masking to `/dev/null` (`chown` on `/dev/null` fails).
