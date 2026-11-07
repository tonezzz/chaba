#!/usr/bin/env bash
# jack-enroll — admin CLI for the Jack IDE enrollment gateway on idc02.
# Talks to the loopback admin API with the token from the secrets env file.
#   jack-enroll mint [--ttl SECONDS] [--label NAME] [--shared]
#       Mint a one-time enrollment code (default: re-registration — revokes
#       the prior Jack session and burns pending codes; --shared keeps them).
#   jack-enroll status        Sessions + pending codes.
#   jack-enroll revoke [SID]  Revoke one session, or all with no arg.
#   jack-enroll reset         Burn every session and code.
#   jack-enroll audit [N]     Last N audit events (default 40).
#   jack-enroll health        Gateway + upstream health.
set -euo pipefail

ENV_FILE="${JACK_ENROLL_ENV:-$HOME/.config/secrets/jack-enroll.env}"
GW="${JACK_GW_URL:-http://127.0.0.1:8377}"
# shellcheck disable=SC1090
[[ -r "$ENV_FILE" ]] && source "$ENV_FILE"
: "${JACK_ADMIN_TOKEN:?no JACK_ADMIN_TOKEN — check $ENV_FILE}"

cmd="${1:-}"; shift || true

api() { # api METHOD PATH [JSON]
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -m 15 -X "$method" -H "x-admin-token: $JACK_ADMIN_TOKEN")
  [[ -n "$data" ]] && args+=(-H 'content-type: application/json' -d "$data")
  curl "${args[@]}" "$GW$path"
}

case "$cmd" in
  mint)
    ttl="" ; label="jack" ; shared=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --ttl) ttl="$2"; shift 2;; --label) label="$2"; shift 2;;
      --shared) shared=1; shift;; *) echo "unknown flag: $1" >&2; exit 2;; esac; done
    body="{\"label\":\"$label\"}"
    [[ -n "$ttl" ]] && body="{\"ttl_s\":$ttl,\"label\":\"$label\"}"
    [[ "$shared" == 1 ]] && body="${body%\}},\"exclusive\":false}"
    resp="$(api POST /admin/codes "$body")"
    echo "$resp" | python3 -c '
import json,sys; r=json.load(sys.stdin)
print("code:       " + r["code"])
print("redeem url: https://idc02.taila0626a.ts.net:8448" + r["redeem_path"])
print("expires in: %ds   (exclusive=%s)" % (r["expires_in"], r["exclusive"]))
'
    ;;
  status)  api GET /admin/status | python3 -m json.tool ;;
  revoke)  sid="${1:-}"; if [[ -n "$sid" ]]; then api POST /admin/revoke "{\"session_id\":\"$sid\"}"; else api POST /admin/revoke '{"all":true}'; fi; echo ;;
  reset)   api POST /admin/reset '{}'; echo ;;
  audit)   api GET "/admin/audit?n=${1:-40}" | python3 -c 'import json,sys; [print(json.dumps(l)) for l in json.load(sys.stdin)["lines"]]' ;;
  health)  curl -fsS -m 10 "$GW/health" | python3 -m json.tool ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
