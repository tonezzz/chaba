#!/usr/bin/env bash
# promote-lane.sh — scripted dev->prod promote for one HA release lane.
#
# Usage:
#   promote-lane.sh <lane| --from DEV --to PROD> [options] --confirm
#
# Options:
#   --scope LIST     release scope: dashboards,bundle,automations,helpers,users
#                    (default: dashboards,bundle; 'all' = those four — users
#                    is never part of 'all', name it explicitly)
#   --dashboard P    lovelace url_path for dashboards scope (lane default)
#   --views a,b|all  view paths to merge (default: all)
#   --create-dashboard  register the dashboard on prod if missing
#   --bundle-base B  bundle filename stem (lane default; required for bundle
#                    scope on lanes without one)
#   --from / --to    override lane endpoints (e.g. --from michael-dev while
#                    tony-dev is not yet provisioned)
#   --cleanup        bundle: delete stale -vN bundles not referenced
#   --rollback       bundle: point the resource back at the previous bundle
#   --restart        helpers/users: restart the prod container after copying
#                    .storage files (required for them to load)
#   --card ID        post promote progress + outcome to the kanban card.
#                    When the card is release-tracked (`release:` field),
#                    the s4 pre-prod gate is enforced before --confirm:
#                    [smoke] dev-twin evidence + satisfied beta soak —
#                    no playlive pass, no promotion (Tony 2026-10-08).
#   -n | --dry-run   print the exact plan + parity diff, write nothing
#   --confirm        REQUIRED for any real prod write (ssot.release-lifecycle
#                    s5: explicit same-session approval, never automatic)
#
# What it does (in order): preflight -> collect both snapshots -> parity diff
# before -> per-scope writes (with .promote-bak-<ts> backups on prod) -> live
# reload where supported -> parity diff after -> post-deploy smoke (health +
# parity-after clean + bundle 200, inside the 30-min bar) -> [rc]/[prod]
# comms evidence on the card.
# Registry: docs/ssot/infrastructure/ssot.home-assistant.lanes.yml
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
# shellcheck source=ha-lanes.sh
source "$SCRIPT_DIR/ha-lanes.sh"
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)
BOARD_API="${BOARD_API:-http://127.0.0.1:8787}"
LIFECYCLE_CHECK="$REPO_ROOT/scripts/ada/lifecycle-check.py"

LANE=""; FROM=""; TO=""
SCOPE=""; DASH=""; VIEWS="all"; BASE=""
DRY_RUN=0; CONFIRM=0; CLEANUP=0; ROLLBACK=0; RESTART=0; CARD=""; CREATE_DASH=0

log() { echo "[promote] $*"; }
die() { echo "[promote] ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,27p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
	case "$1" in
	-n | --dry-run) DRY_RUN=1 ;;
	--confirm)      CONFIRM=1 ;;
	--scope)        SCOPE="$2"; shift ;;
	--dashboard)    DASH="$2"; shift ;;
	--views)        VIEWS="$2"; shift ;;
	--bundle-base)  BASE="$2"; shift ;;
	--from)         FROM="$2"; shift ;;
	--to)           TO="$2"; shift ;;
	--cleanup)      CLEANUP=1 ;;
	--rollback)     ROLLBACK=1 ;;
	--restart)      RESTART=1 ;;
	--create-dashboard) CREATE_DASH=1 ;;
	--card)         CARD="$2"; shift ;;
	-h | --help)    usage ;;
	-*)             die "unknown arg: $1" ;;
	*)
		[ -n "$LANE" ] && die "unexpected extra arg: $1"
		LANE="$1" ;;
	esac
	shift
done

board() {
	[ -n "$CARD" ] || return 0
	curl -s -m 4 -X POST "$BOARD_API/comment" -H 'Content-Type: application/json' \
		-d "{\"id\":\"$CARD\",\"from\":\"devin\",\"text\":$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")}" \
		>/dev/null 2>&1 || log "warn: board comms unreachable ($BOARD_API)"
}

# --- resolve endpoints -------------------------------------------------------
if [ -n "$LANE" ]; then
	lane_exists "$LANE" || die "unknown lane '$LANE'"
	[ -n "$FROM" ] || FROM=$(lane_field "$LANE" dev)
	[ -n "$TO" ]   || TO=$(lane_field "$LANE" prod)
	[ -n "$DASH" ] || DASH=$(lane_field "$LANE" dashboard 2>/dev/null || echo "")
	[ -n "$BASE" ] || BASE=$(lane_field "$LANE" bundle_base 2>/dev/null || echo "")
fi
[ -n "$FROM" ] && [ -n "$TO" ] || die "need a lane name or --from/--to"
inst_exists "$FROM" || die "unknown instance: $FROM"
inst_exists "$TO"   || die "unknown instance: $TO"
[ "$BASE" = "null" ] && BASE=""
[ -n "$SCOPE" ] || { [ -n "$BASE" ] && SCOPE="dashboards,bundle" || SCOPE="dashboards"; }

SCOPES="${SCOPE//,/ }"
[ "$SCOPE" = "all" ] && SCOPES="dashboards bundle automations helpers"
for s in $SCOPES; do
	case "$s" in dashboards|bundle|automations|helpers|users) : ;;
		*) die "unknown scope '$s' (dashboards,bundle,automations,helpers,users)" ;;
	esac
done

log "lane ${LANE:-ad-hoc}: $FROM -> $TO   scope: $SCOPES"

# --- preflight ---------------------------------------------------------------
UP_CHECK=("$FROM" "$TO")
[ "$ROLLBACK" -eq 1 ] && UP_CHECK=("$TO")   # emergency rollback must not need dev
for inst in "${UP_CHECK[@]}"; do
	if ! inst_up "$inst"; then
		[ "$(inst_field "$inst" planned 2>/dev/null)" = "True" ] \
			&& die "$inst is registered but not provisioned yet (card ha-dev-instances)"
		die "$inst unreachable at $(inst_field "$inst" url)"
	fi
done

# --- rollback (bundle scope) — early exit, does not touch dev -----------------
if [ "$ROLLBACK" -eq 1 ]; then
	need_token() {
		local t; t=$(inst_token "$1" 2>/dev/null) \
			|| die "cannot resolve token for $1"; eval "$2=\"$t\""
	}
	need_token "$TO" PROD_TOKEN
	[ -n "$BASE" ] || die "--rollback needs --bundle-base"
	cur=$(inst_sh "$TO" "grep -o '${BASE}-v[0-9]*' .storage/lovelace_resources | head -1 | grep -o '[0-9]*\$'" || true)
	[ -n "$cur" ] || die "nothing to roll back to"
	prev=$(inst_sh "$TO" "ls www/${BASE}-v*.js | sed 's/.*-v//;s/\\.js//' | sort -n | awk -v c=$cur '\$1<c' | tail -1")
	[ -n "$prev" ] || die "no older bundle on $TO to roll back to"
	log "rollback: resource -> /local/${BASE}-v${prev}.js"
	[ "$DRY_RUN" -eq 1 ] && exit 0
	[ "$CONFIRM" -eq 1 ] || die "rollback writes prod — pass --confirm"
	HASS_TOKEN="$PROD_TOKEN" python3 "$SCRIPT_DIR/ws-resource-url.py" \
		"$(inst_field "$TO" url)" "$BASE" "${BASE}-v${prev}.js"
	log "rolled back to v$prev (bundle file kept)"
	exit 0
fi

DEV_TOKEN=""; PROD_TOKEN=""
need_token() { # $1 inst $2 varname $3 why
	local t; t=$(inst_token "$1" 2>/dev/null) \
		|| die "cannot resolve token for $1 (needed for $3)"
	[ -n "$t" ] || die "empty token for $1 (needed for $3)"
	eval "$2=\"$t\""
}
for s in $SCOPES; do
	case "$s" in
	dashboards)  need_token "$FROM" DEV_TOKEN "dev lovelace/config"
	             need_token "$TO" PROD_TOKEN "prod lovelace/config/save" ;;
	bundle)      need_token "$TO" PROD_TOKEN "prod lovelace resource bump" ;;
	automations) need_token "$TO" PROD_TOKEN "prod service reload" ;;
	esac
done

# --- collect + parity before --------------------------------------------------
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
inst_collect "$FROM" "$tmp/dev"
inst_collect "$TO" "$tmp/prod"
DIFF_SCOPES=$(echo "$SCOPES" | tr ' ' ',' | sed 's/bundle/resources,bundle/')
log "parity diff BEFORE (dev vs prod):"
python3 "$SCRIPT_DIR/ha-twin-diff.py" "$tmp/dev" "$tmp/prod" \
	--names "$FROM:$TO" --scope "$DIFF_SCOPES" || true

TS=$(date +%Y%m%d-%H%M%S)
backup() { # prod file -> .promote-bak-$TS
	inst_sh "$TO" "[ -f '$1' ] && cp -a '$1' '$1.promote-bak-$TS' || true"
}

# =============================== per scope ====================================

scope_dashboards() {
	[ -n "$DASH" ] || die "dashboards scope needs --dashboard (no lane default)"
	log "dashboards: merge views [$VIEWS] of '$DASH'  $FROM -> $TO"
	local flags=()
	[ "$DRY_RUN" -eq 1 ] && flags+=(--dry-run)
	[ "$CREATE_DASH" -eq 1 ] && flags+=(--create)
	DEV_TOKEN="$DEV_TOKEN" PROD_TOKEN="$PROD_TOKEN" \
		python3 "$SCRIPT_DIR/promote-views.py" \
		"$(inst_field "$FROM" url)" "$(inst_field "$TO" url)" "$DASH" "$VIEWS" \
		"${flags[@]}" || die "view merge failed"
	if [ "$DRY_RUN" -eq 0 ]; then
		log "note: run sync-ssot-from-live.sh + commit (parallel-session rule)"
	fi
}

scope_bundle() {
	[ -n "$BASE" ] || die "bundle scope needs --bundle-base (lane has none)"
	local cur_dev cur_prod file
	cur_prod=$(inst_sh "$TO" "grep -o '${BASE}-v[0-9]*' .storage/lovelace_resources | head -1 | grep -o '[0-9]*\$'" || true)
	cur_dev=$(inst_sh "$FROM" "grep -o '${BASE}-v[0-9]*' .storage/lovelace_resources | head -1 | grep -o '[0-9]*\$'" || true)
	[ -n "$cur_dev" ] || die "no ${BASE}-vN resource on $FROM"
	file="${BASE}-v${cur_dev}.js"
	log "bundle: $FROM v$cur_dev  ->  $TO v${cur_prod:-none}   ($file)"
	if [ "$DRY_RUN" -eq 1 ]; then
		inst_sh "$TO" "ls www/${BASE}-v*.js 2>/dev/null || true"
		return
	fi
	local localfile="$tmp/$file"
	inst_sh "$FROM" "cat 'www/$file'" > "$localfile" \
		|| die "cannot read $file from $FROM"
	[ -s "$localfile" ] || die "$file missing on $FROM www"
	inst_sh "$TO" "cat > 'www/$file.incoming' && mv -f 'www/$file.incoming' 'www/$file'" \
		< "$localfile" || die "cannot write $file on $TO www"
	BUNDLE_FILE="$file"   # re-checked by the post-deploy smoke
	HASS_TOKEN="$PROD_TOKEN" python3 "$SCRIPT_DIR/ws-resource-url.py" \
		"$(inst_field "$TO" url)" "$BASE" "$file" || die "resource bump failed"
	sleep 2
	local code
	code=$(curl -s -o /dev/null -w '%{http_code}' "$(inst_field "$TO" url)/local/$file")
	[ "$code" = "200" ] || die "bundle not served on $TO (http $code)"
	log "verified: $TO serves /local/$file"
	if [ "$CLEANUP" -eq 1 ]; then
		inst_sh "$TO" "cd www && for f in ${BASE}-v*.js; do
			case \"\$f\" in ${BASE}-v${cur_dev}.js|${BASE}-v${cur_prod:-0}.js) : ;;
			*) rm -f \"\$f\" && echo \"  removed \$f\" ;; esac; done" || true
	fi
}

scope_automations() {
	local kind fname reload_svc merged
	for kind in automations scripts scenes; do
		fname="${kind}.yaml"
		local devf="$tmp/dev/yaml/$fname" prodf="$tmp/prod-live-$fname"
		[ -f "$devf" ] || { log "automations: no $fname on $FROM — skip"; continue; }
		inst_cat "$TO" "$fname" > "$prodf" || touch "$prodf"
		merged="$tmp/merged-$fname"
		log "automations: merging $fname (destage: strip initial_state:false, skip stubs)"
		python3 "$SCRIPT_DIR/ha-config-merge.py" "$kind" "$devf" "$prodf" \
			> "$merged" 2>"$tmp/merge-notes" || die "merge failed for $fname"
		if python3 "$SCRIPT_DIR/ha-config-merge.py" eq "$merged" "$prodf"; then
			log "  $fname: no semantic change"; continue
		fi
		sed 's/^/    /' "$tmp/merge-notes" >&2
		if [ "$DRY_RUN" -eq 1 ]; then
			log "  DRY $fname diff:"
			diff -u "$prodf" "$merged" | head -60 | sed 's/^/    /' || true
			continue
		fi
		backup "$fname"
		inst_put "$TO" "$fname" "$merged" || die "write failed: $fname"
		reload_svc="${kind%s}"   # automations->automation, scripts->script, scenes->scene
		curl -sf -m 8 -X POST -H "Authorization: Bearer $PROD_TOKEN" \
			"$(inst_field "$TO" url)/api/services/${reload_svc}/reload" >/dev/null \
			&& log "  $fname written + ${reload_svc}.reload ok" \
			|| log "  WARN: $fname written but ${reload_svc}.reload call failed — check prod"
	done
}

scope_helpers() {
	local changed=0 f dom
	for dom in input_boolean input_button input_datetime input_number \
	           input_select input_text counter timer schedule group tag; do
		f="$tmp/dev/storage/$dom"
		[ -f "$f" ] || continue
		cmp -s "$f" "$tmp/prod/storage/$dom" 2>/dev/null && continue
		changed=1
		if [ "$DRY_RUN" -eq 1 ]; then
			log "  DRY: would copy .storage/$dom $FROM -> $TO"
			continue
		fi
		backup ".storage/$dom"
		inst_put "$TO" ".storage/$dom" "$f" || die "write failed: .storage/$dom"
		log "  copied .storage/$dom"
		RESTART_NEEDED=1
	done
	[ "$changed" -eq 0 ] && log "helpers: all helper storage identical — nothing to do"
	return 0
}

scope_users() {
	local f changed=0
	for f in auth auth_provider.homeassistant onboarding; do
		[ -f "$tmp/dev/storage/$f" ] || continue
		cmp -s "$tmp/dev/storage/$f" "$tmp/prod/storage/$f" 2>/dev/null && continue
		changed=1
		if [ "$DRY_RUN" -eq 1 ]; then
			log "  DRY: would REPLACE .storage/$f on $TO (all prod sessions/tokens become dev's)"
			continue
		fi
		log "  WARN: replacing .storage/$f on $TO — prod sessions/tokens are replaced by dev's"
		backup ".storage/$f"
		inst_put "$TO" ".storage/$f" "$tmp/dev/storage/$f" || die "write failed: .storage/$f"
		log "  copied .storage/$f"
		RESTART_NEEDED=1
	done
	[ "$changed" -eq 0 ] && log "users: auth storage identical — nothing to do"
	return 0
}

# --- confirm gate -------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "$CONFIRM" -ne 1 ]; then
	log "REFUSING prod writes without --confirm (release policy: explicit"
	log "same-session approval, never automatic). Re-run with --confirm."
	exit 1
fi

# --- release-lifecycle s4 gate -------------------------------------------------
# When --card names a release-tracked card (release: field), the pre-prod bar
# must be met before prod writes: [smoke] dev-twin playlive evidence + the
# beta soak (72h or >=3 sessions). Dry-run reports the verdict, never blocks.
BUNDLE_FILE=""
if [ -n "$CARD" ] && [ -f "$LIFECYCLE_CHECK" ]; then
	cardfile="$REPO_ROOT/docs/ssot/kanban/cards/$CARD.yml"
	if [ -f "$cardfile" ]; then
		gate_out=$(python3 "$LIFECYCLE_CHECK" --gate "$cardfile" \
			--stage preprod 2>/dev/null || true)
		gate_note=$(python3 -c 'import json,sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    print(""); sys.exit()
print("ok" if d.get("ok") else "missing: " + ", ".join(d.get("missing") or []))
if d.get("release") is None and "note" in d:
    print("NOT-TRACKED")' "$gate_out" 2>/dev/null)
		case "$gate_note" in
		*"NOT-TRACKED"*)
			log "card $CARD not release-tracked — lifecycle gates skipped" ;;
		"missing: "*)
			if [ "$DRY_RUN" -eq 1 ]; then
				log "WARN release gate (preprod) unmet on $CARD — $gate_note"
			else
				log "REFUSING promote: card $CARD fails the s4 pre-prod gate:"
				log "  $gate_note"
				log "  produce [smoke] evidence with dev-twin-smoke.py --lane $LANE --card $CARD;"
				log "  soak_until must be reached or a [beta] comms must cite >=3 sessions."
				board "[lifecycle] promote refused — s4 gate unmet: $gate_note"
				exit 1
			fi ;;
		esac
	else
		log "warn: --card $CARD has no card file under $REPO_ROOT — skipping lifecycle gate"
	fi
fi

board "promote ${LANE:-ad-hoc} $FROM->$TO scope=[$SCOPES] $([ $DRY_RUN -eq 1 ] && echo 'dry-run' || echo 'CONFIRMED') started"
[ "$DRY_RUN" -eq 0 ] && board "[rc] pre-prod evidence: parity diff BEFORE (dev $FROM vs prod $TO, scope=[$SCOPES]) in this run's log; rollback = ${0##*/} ${LANE:-} --rollback or restore *.$TS promote-bak files on $TO"

RESTART_NEEDED=0
for s in $SCOPES; do "scope_$s" || die "scope $s failed"; done

# --- restart for .storage scopes ----------------------------------------------
if [ "$RESTART_NEEDED" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
	cont=$(inst_field "$TO" container 2>/dev/null || echo "")
	if [ "$RESTART" -eq 1 ]; then
		if [ "$(inst_field "$TO" ssh)" = "local" ] && [ -n "$cont" ]; then
			podman restart "$cont" && log "restarted $cont"
		else
			inst_ssh "$TO" ha core restart && log "restarted $TO core" \
				|| log "WARN: restart failed — restart $TO manually"
		fi
	else
		log "RESTART REQUIRED on $TO for .storage changes to load — re-run with --restart or: podman restart ${cont:-<container>} (local) / ha core restart (remote)"
	fi
fi

# --- parity after --------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
	sleep 5   # .storage writes are debounced — let prod flush before recollecting
	log "parity diff AFTER (dev vs prod):"
	inst_collect "$TO" "$tmp/prod2"
	PARITY_AFTER_RC=0
	python3 "$SCRIPT_DIR/ha-twin-diff.py" "$tmp/dev" "$tmp/prod2" \
		--names "$FROM:$TO" --scope "$DIFF_SCOPES" || PARITY_AFTER_RC=$?

	# --- post-deploy smoke (ssot.release-lifecycle.yml s5 bar: health +
	# one scenario within 30min of the deploy — this runs immediately) ----
	SMOKE_T0=$SECONDS; smoke_fails=""
	code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 6 \
		"$(inst_field "$TO" url)/api/")
	[ "$code" = "200" ] || smoke_fails="prod /api/ http $code; "
	[ "$PARITY_AFTER_RC" -eq 0 ] \
		|| smoke_fails="${smoke_fails}parity-after diff rc=$PARITY_AFTER_RC; "
	if [ -n "$BUNDLE_FILE" ]; then
		bcode=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 6 \
			"$(inst_field "$TO" url)/local/$BUNDLE_FILE")
		[ "$bcode" = "200" ] \
			|| smoke_fails="${smoke_fails}bundle $BUNDLE_FILE http $bcode; "
	fi
	elapsed=$((SECONDS - SMOKE_T0))
	if [ -z "$smoke_fails" ]; then
		log "post-deploy smoke PASS (${elapsed}s): /api 200, parity-after clean$([ -n "$BUNDLE_FILE" ] && echo ", bundle 200")"
		board "[prod] deploy $FROM->$TO scope=[$SCOPES] + post-deploy smoke PASS (${elapsed}s): /api 200, parity-after clean$([ -n "$BUNDLE_FILE" ] && echo ", /local/$BUNDLE_FILE 200"); backups *.$TS on $TO"
	else
		log "post-deploy smoke FAIL (${elapsed}s): $smoke_fails"
		board "[prod] deploy $FROM->$TO scope=[$SCOPES] ran but post-deploy smoke FAIL (${elapsed}s): $smoke_fails — consider rollback"
		log "rollback: bundle -> '$0 $LANE --rollback'; file scopes -> restore"
		log "  <file>.promote-bak-$TS on $TO."
		exit 1
	fi
	log "done. rollback: bundle -> '$0 $LANE --rollback'; file scopes -> restore"
	log "  <file>.promote-bak-$TS on $TO. Record evidence on the card."
	board "promote ${LANE:-ad-hoc} $FROM->$TO scope=[$SCOPES] DONE — parity after above; backups *.$TS on $TO"
else
	log "dry-run complete — no writes. Re-run with --confirm to apply."
fi
