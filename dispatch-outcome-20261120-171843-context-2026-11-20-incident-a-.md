# dispatch-outcome — ocb-models-status-patch-durability (2026-11-20)

## What was done

The hand-patch adding `models.status` + `GET /api/openchamber/models/status`
(LiteLLM gateway liveness probe) to @openchamber/web@2.7.3 on idc02 lived only
in `node_modules` — the monthly `openchamber-update.timer` would silently
revert it. It is now durable:

1. **Patch extracted** — diffed the 5 modified files on idc02 against pristine
   `@openchamber/web@2.7.3` (`npm pack`): 161-line unified diff at
   `stacks/idc02/openchamber/openchamber-models-status.patch` (`patch -p1 -d
   <pkg root>`).
2. **Durable home = option (b)** — upstream repo github.com/openchamber/openchamber
   is public (MIT) but the patch edits the dist bundle and is site-specific
   (provider `litellm`, `LITELLM_URL`/`LITELLM_KEY` env); a real PR needs a
   TS-source port + generalization → follow-up card
   `upstream-pr-models-status-endpoint-for-o-280615` (OPS-0024). Mechanism:
   `stacks/idc02/openchamber/apply-models-status-patch.sh` — idempotent,
   `patch --dry-run` gate, `node --check` on all 5 files, prefix arg.
3. **Wired on idc02** — `~/.config/systemd/user/openchamber-update.service`
   gained `ExecStartPost=.../apply-models-status-patch.sh` BEFORE the restart;
   no `-` prefix → a patch failure fails the oneshot unit loudly and skips the
   restart (old process keeps serving; failed-units triage sees it). Patch +
   script staged into `~/CascadeProjects/chaba/stacks/idc02/openchamber/` so
   the ExecStartPost path resolves now and survives the next repo sync.
4. **Verified** — fresh `npm i -g --prefix=/tmp/ocb-verify @openchamber/web@2.7.3`
   + apply → all 5 files **md5-identical** to the live install that serves the
   endpoint; idempotent second run; corrupted file → exit 1 with regenerate
   instructions. Live endpoint: session auth → 200, `{total:38, active:31,
   unavailable:7, error:0}` — cf-* litellm models correctly flagged
   (Cloudflare daily-neuron 429). openchamber.service stayed active
   throughout; update unit not executed (would bump the version).
5. **Recorded** — `ssot.audit.hosts.yml` idc02 `openchamber.service` and
   `openchamber-update.service` notes updated (2.7.3, patch, fail-loud
   semantics); job record
   `docs/ssot/jobs/infrastructure/2026-11-20-openchamber-models-status-patch-durability.yml`.

## How to verify

- `ssh idc02 systemctl --user cat openchamber-update.service` — two
  ExecStartPost lines, patch first.
- `ssh idc02 ~/CascadeProjects/chaba/stacks/idc02/openchamber/apply-models-status-patch.sh`
  → "already applied".
- Endpoint: POST `http://127.0.0.1:3000/auth/session` `{password:$OPENCHAMBER_UI_PASSWORD}`
  then GET `/api/openchamber/models/status` → 200 + summary.

## Notes

- A transient 502 (`Location plugins did not finish activating`) was the
  opencode backend still activating plugins, not the patch — retried OK.
- `openchamber-update.service.bak-20261120` backup left on idc02.

lessons:
- Verify patched-node_modules equivalence by md5-paring scratch+patch output against the live install — proves fresh-install+apply reproduces exactly the code serving the verified endpoint.
- The endpoint needs session auth: POST /auth/session {password:$OPENCHAMBER_UI_PASSWORD} -> cookie; an unauthenticated probe gets 401 (route exists) vs 404.
- A 502 "Location plugins did not finish activating" from the control service is the opencode backend warming up — retry before suspecting the patch.
- ExecStartPost ordering matters: put the patch step BEFORE the service restart and drop the '-' prefix so a non-applying patch fails the unit loudly instead of silently dropping the feature.
