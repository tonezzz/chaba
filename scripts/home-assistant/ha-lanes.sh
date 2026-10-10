#!/usr/bin/env bash
# ha-lanes.sh — shared registry + access helpers for the HA release pipeline.
# Sourced by frontend-parity-check.sh and promote-lane.sh; not run directly.
#
# Registry: docs/ssot/infrastructure/ssot.home-assistant.lanes.yml
#   (override with LANES_FILE). Provides per-lane dev/prod instance ids and
#   per-instance ssh/config/url/auth metadata.
#
# Functions:
#   lane_field <lane> <field>          -> prints lanes.<lane>.<field>
#   inst_field <inst> <field>          -> prints instances.<inst>.<field>
#   inst_exists <inst>                 -> rc 0 if instance id is in the registry
#   inst_run <inst> <cmd...>           -> run command on the instance's host
#   inst_cat <inst> <config-relpath>   -> cat file under <config>/ (rc 1 if absent)
#   inst_put <inst> <config-relpath> <localfile> -> write file under <config>/
#   inst_ls <inst> <config-reldir> <glob> -> list matching files (rel paths)
#   inst_token <inst>                  -> prints a bearer token per auth kind
#   inst_up <inst>                     -> rc 0 when the instance answers HTTP
#   inst_collect <inst> <destdir>      -> snapshot config for ha-twin-diff.py

# shellcheck disable=SC2034  # vars are consumed by sourcing scripts

LANES_FILE="${LANES_FILE:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." &>/dev/null && pwd)/docs/ssot/infrastructure/ssot.home-assistant.lanes.yml}"

_lanes_py() {
	python3 - "$LANES_FILE" "$@" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
op, key = sys.argv[2], sys.argv[3]
if op == "inst":
    node = (d.get("instances") or {}).get(key)
elif op == "lane":
    node = (d.get("lanes") or {}).get(key)
else:
    node = d.get(key)
if node is None:
    sys.exit(1)
if len(sys.argv) > 4:
    for f in sys.argv[4].split("."):
        node = (node or {}).get(f)
    if node is None:
        sys.exit(1)
print(node if not isinstance(node, (dict, list)) else __import__("json").dumps(node))
PY
}

lane_field() { _lanes_py lane "$1" "$2" 2>/dev/null; }
inst_field() { _lanes_py inst "$1" "$2" 2>/dev/null; }
inst_exists() { _lanes_py inst "$1" >/dev/null 2>&1; }
lane_exists() { _lanes_py lane "$1" >/dev/null 2>&1; }
lanes_top() { _lanes_py top "$1" 2>/dev/null; }

# --- remote execution -------------------------------------------------------
# `ssh: local` means the config dir is on this machine. Otherwise the value is
# an ssh target; `ssh_key` adds -i. BatchMode so a dead host fails fast.
# Remote args are %q-quoted: ssh re-parses the joined command line remotely,
# so `inst_ssh x sh -c 'a && b'` must arrive as `sh -c 'a && b'`.
inst_ssh() {
	local inst="$1"; shift
	local target key
	target=$(inst_field "$inst" ssh) || return 1
	if [ "$target" = "local" ]; then
		"$@"
	else
		local args=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no)
		key=$(inst_field "$inst" ssh_key 2>/dev/null || true)
		[ -n "$key" ] && args+=(-i "$key" -o IdentitiesOnly=yes)
		local cmd
		cmd=$(printf '%q ' "$@")
		ssh "${args[@]}" "$target" "$cmd"
	fi
}

inst_cat() {
	local inst="$1" rel="$2" cfg
	cfg=$(inst_field "$inst" config) || return 1
	inst_ssh "$inst" cat "$cfg/$rel" 2>/dev/null
}

inst_put() {  # atomic: stage to <rel>.incoming then mv — no partial prod files
	local inst="$1" rel="$2" src="$3" cfg target
	cfg=$(inst_field "$inst" config) || return 1
	target=$(inst_field "$inst" ssh)
	if [ "$target" = "local" ]; then
		cp -a "$src" "$cfg/$rel.incoming" && mv -f "$cfg/$rel.incoming" "$cfg/$rel"
	else
		local args=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no)
		local key; key=$(inst_field "$inst" ssh_key 2>/dev/null || true)
		[ -n "$key" ] && args+=(-i "$key" -o IdentitiesOnly=yes)
		scp "${args[@]}" "$src" "$target:$cfg/$rel.incoming" \
			&& inst_ssh "$inst" mv -f "$cfg/$rel.incoming" "$cfg/$rel"
	fi
}

# run a small shell script on the instance host with config dir as cwd.
# Output: stdout. Missing files are simply skipped by the caller's [ -f ].
inst_sh() {
	local inst="$1" script="$2" cfg
	cfg=$(inst_field "$inst" config) || return 1
	inst_ssh "$inst" sh -c "cd $(printf '%q' "$cfg") || exit 1; $script"
}

# --- reachability -----------------------------------------------------------
inst_up() {
	local inst="$1" url code
	url=$(inst_field "$inst" url) || return 1
	code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 6 "$url/api/" 2>/dev/null)
	[ "$code" != "000" ]
}

# --- auth -------------------------------------------------------------------
# kind env:     VAR=value lines in file           -> echo var value
# kind file:    whole file is the token           -> cat
# kind refresh: named refresh_token in .storage/auth -> exchange at url/auth/token
inst_token() {
	local inst="$1" kind file var client url cfg_dir
	kind=$(inst_field "$inst" auth.kind) || return 1
	case "$kind" in
	env)
		file=$(inst_field "$inst" auth.file); var=$(inst_field "$inst" auth.var)
		[ -f "$file" ] || return 1
		grep -m1 "^${var}=" "$file" | cut -d= -f2-
		;;
	file)
		file=$(inst_field "$inst" auth.file)
		[ -f "$file" ] || return 1
		cat "$file"
		;;
	refresh)
		client=$(inst_field "$inst" auth.client_name)
		url=$(inst_field "$inst" url)
		cfg_dir=$(inst_field "$inst" config)
		local authfile="$cfg_dir/.storage/auth"
		local tmp="$authfile"
		if [ "$(inst_field "$inst" ssh)" != "local" ]; then
			tmp=$(mktemp)
			inst_cat "$inst" .storage/auth > "$tmp" || { rm -f "$tmp"; return 1; }
		fi
		python3 - "$tmp" "$client" "$url" <<'PY'
import json, sys, urllib.request
auth = json.load(open(sys.argv[1]))
rt = next(t["token"] for t in auth["data"]["refresh_tokens"]
          if t.get("client_name") == sys.argv[2])
req = urllib.request.Request(
    sys.argv[3] + "/auth/token", method="POST",
    data=f"grant_type=refresh_token&refresh_token={rt}".encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"})
print(json.load(urllib.request.urlopen(req))["access_token"])
PY
		local rc=$?
		[ "$tmp" != "$authfile" ] && rm -f "$tmp"
		return $rc
		;;
	*) return 1 ;;
	esac
}

# --- snapshot collection ----------------------------------------------------
# One remote call: tar the comparable files out of <config> (globs expanded
# remotely, absent paths skipped), plus a second call for www md5s.
# Layout produced in <destdir>:
#   storage/<name>            each fetched .storage file
#   yaml/<file>               automations/scripts/scenes
#   yaml/packages/<file>      packages/*.yaml
#   bundles.md5               "md5  ./path" lines for every www/**/*.js
COLLECT_GLOBS='.storage/lovelace* .storage/auth .storage/auth_provider.homeassistant .storage/onboarding .storage/input_* .storage/counter .storage/timer .storage/schedule .storage/group .storage/tag .storage/person automations.yaml scripts.yaml scenes.yaml packages/*.yaml'

inst_collect() {
	local inst="$1" dest="$2"
	mkdir -p "$dest"
	inst_sh "$inst" \
		'for f in '"$COLLECT_GLOBS"'; do [ -f "$f" ] && echo "$f"; done | tar cf - -T -' \
		| (cd "$dest" && tar xf - 2>/dev/null) || true
	[ -d "$dest/.storage" ] && mv "$dest/.storage" "$dest/storage"
	mkdir -p "$dest/storage" "$dest/yaml"
	local f
	for f in automations.yaml scripts.yaml scenes.yaml; do
		[ -f "$dest/$f" ] && mv "$dest/$f" "$dest/yaml/$f"
	done
	[ -d "$dest/packages" ] && mv "$dest/packages" "$dest/yaml/packages"
	mkdir -p "$dest/yaml/packages"

	inst_sh "$inst" \
		'cd www 2>/dev/null && find . -name "*.js" -type f -print0 | sort -z | xargs -0 md5sum' \
		> "$dest/bundles.md5" 2>/dev/null || touch "$dest/bundles.md5"
}
