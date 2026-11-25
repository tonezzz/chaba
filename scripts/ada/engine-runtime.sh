#!/usr/bin/env bash
# engine-runtime.sh — per-engine runtime slots for parallel ada engine
# versions on idc03 (card ada-engine-runtimes; design: docs/kb/ada-engine-runtimes.md).
#
# A runtime = ~/CascadeProjects/ada-engines/<engine-id>/ holding a pinned
# ada-voice checkout + its own .venv. Lanes bind to an engine via a
# systemd drop-in that repoints WorkingDirectory/ExecStart — lane env,
# keys, banks, ports are untouched. ada-1.x has no dir: the shared
# ~/CascadeProjects/ada-voice checkout IS its runtime.
#
# Subcommands (run on idc03 as the lane user):
#   provision <engine-id> [--ref <git-ref>] [--repo <git-url>]
#       clone ada-voice at <ref> into ada-engines/<engine-id> + build .venv
#   bind <unit> <engine-id>
#       write <unit>.service.d/engine-<engine-id>.conf repointing the unit
#       at the runtime (always daemon-reloads; restart is manual)
#   unbind <unit>
#       remove the engine drop-in(s); lane falls back to shared ada-1
#   lane <engine-id> <lane-id> <port> --from <src-unit> [--env <src-env>]
#       scaffold a variant test lane: env copy + unit + isolation + stagger
#   status [engine-id]
#       list runtimes and which units are bound to which engine
#
# Idempotent — safe to rerun. No secrets are stored in runtime dirs.
set -euo pipefail

ROOT="${ADA_ROOT:-$HOME/CascadeProjects}"
ENGINES_DIR="$ROOT/ada-engines"
SHARED_DIR="$ROOT/ada-voice"
UNITS_DIR="$HOME/.config/systemd/user"
SECRETS_DIR="$HOME/.config/secrets"
ADA_REPO="${ADA_VOICE_REPO:-$SHARED_DIR}"   # clone source; override for a fresh clone URL

log()  { printf '==> %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing tool: $1"; }

valid_engine_id() { [[ "$1" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; }
engine_dir()     { printf '%s/%s' "$ENGINES_DIR" "$1"; }

# Rewrite every checkout-path reference in a unit ExecStart line to the
# runtime dir. Handles %h, ~, and $HOME spellings of the shared checkout.
rewrite_exec() {
  local line="$1" dest="$2"
  line="${line//%h\/CascadeProjects\/ada-voice/$dest}"
  line="${line//\$HOME\/CascadeProjects\/ada-voice/$dest}"
  line="${line//\~\/CascadeProjects\/ada-voice/$dest}"
  line="${line//$SHARED_DIR/$dest}"
  printf '%s' "$line"
}

cmd_provision() {
  local engine_id="${1:-}"; shift || true
  [[ -n "$engine_id" ]] || die "usage: provision <engine-id> [--ref <ref>] [--repo <url>]"
  valid_engine_id "$engine_id" || die "bad engine id: $engine_id"
  local ref="origin/master" repo="$ADA_REPO"
  while (($#)); do case "$1" in
    --ref)  ref="${2:?--ref needs a value}"; shift 2;;
    --repo) repo="${2:?--repo needs a value}"; shift 2;;
    *) die "unknown arg: $1";;
  esac; done

  local dir; dir="$(engine_dir "$engine_id")"
  if [[ -d "$dir/.git" ]]; then
    log "runtime $engine_id exists at $dir — fetching + checking out $ref"
    git -C "$dir" fetch --all --quiet
    git -C "$dir" checkout --quiet "$ref"
    git -C "$dir" reset --hard --quiet "$(git -C "$dir" rev-parse "$ref")" 2>/dev/null \
      || git -C "$dir" checkout --quiet "$ref"
  else
    log "cloning ada-voice @ $ref -> $dir"
    mkdir -p "$ENGINES_DIR"
    git clone --quiet "$repo" "$dir"
    git -C "$dir" checkout --quiet "$ref"
  fi
  log "pinned at $(git -C "$dir" rev-parse --short HEAD) ($(git -C "$dir" describe --tags --always 2>/dev/null || true))"

  if [[ ! -x "$dir/.venv/bin/python" ]]; then
    log "building .venv in $dir"
    if [[ -f "$dir/uv.lock" || -f "$dir/pyproject.toml" ]] && command -v uv >/dev/null 2>&1; then
      (cd "$dir" && uv venv .venv --quiet && uv pip install --quiet -r requirements.txt 2>/dev/null || uv sync --quiet)
    elif [[ -f "$dir/requirements.txt" ]]; then
      python3 -m venv "$dir/.venv"
      "$dir/.venv/bin/pip" install --quiet -r "$dir/requirements.txt"
    else
      log "WARN: no requirements.txt/pyproject — venv created empty; install deps manually"
      python3 -m venv "$dir/.venv"
    fi
  else
    log ".venv already present — leaving it (delete $dir/.venv to rebuild)"
  fi
  log "runtime ready: $dir"
}

# Print the unit's current ExecStart lines (from `systemctl cat`, so drop-ins
# are already merged) with the shared-checkout path rewritten to $dest.
exec_lines_for() {
  local unit="$1" dest="$2" line
  systemctl --user cat "$unit" 2>/dev/null \
    | awk '/^\[Service\]/{s=1;next} /^\[/{s=0} s && /^ExecStart=/{sub(/^ExecStart=/,""); print}' \
    | while IFS= read -r line; do rewrite_exec "$line" "$dest"; echo; done
}

cmd_bind() {
  local unit="${1:-}" engine_id="${2:-}"
  [[ -n "$unit" && -n "$engine_id" ]] || die "usage: bind <unit> <engine-id> [--no-reload]"
  valid_engine_id "$engine_id" || die "bad engine id: $engine_id"
  local dir; dir="$(engine_dir "$engine_id")"
  [[ -d "$dir" ]] || die "no runtime at $dir — run: provision $engine_id"
  [[ -x "$dir/.venv/bin/python" ]] || log "WARN: $dir/.venv/bin/python missing — bind anyway? (deps may be incomplete)"

  local drop_dir="$UNITS_DIR/${unit}.service.d"
  mkdir -p "$drop_dir"
  local conf="$drop_dir/engine-${engine_id}.conf" tmp
  tmp="$(mktemp)"
  {
    echo "# Engine binding: $unit -> $engine_id ($(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo '?'))"
    echo "# Generated by scripts/ada/engine-runtime.sh — edit via bind/unbind, not by hand."
    echo "[Service]"
    echo "WorkingDirectory=$dir"
    echo "ExecStart="   # reset — drop-ins must clear before re-adding
    exec_lines_for "$unit" "$dir" | while IFS= read -r l; do [[ -n "$l" ]] && printf 'ExecStart=%s\n' "$l"; done
  } > "$tmp"
  [[ -s "$tmp" ]] || die "could not read ExecStart for $unit (unit missing or pathless?)"
  mv "$tmp" "$conf"
  log "bound $unit -> $engine_id via $conf"
  systemctl --user daemon-reload
  log "restart to apply: systemctl --user restart $unit"
}

cmd_unbind() {
  local unit="${1:-}"
  [[ -n "$unit" ]] || die "usage: unbind <unit>"
  local drop_dir="$UNITS_DIR/${unit}.service.d" removed=0 f
  for f in "$drop_dir"/engine-*.conf; do
    [[ -e "$f" ]] || continue
    rm -f "$f"; removed=1; log "removed $f"
  done
  (( removed )) || log "no engine drop-ins on $unit"
  systemctl --user daemon-reload
}

cmd_lane() {
  local engine_id="${1:-}" lane_id="${2:-}" port="${3:-}"
  shift 3 || true
  [[ -n "$engine_id" && -n "$lane_id" && -n "$port" ]] \
    || die "usage: lane <engine-id> <lane-id> <port> --from <src-unit> [--env <src-env>]"
  valid_engine_id "$engine_id" || die "bad engine id: $engine_id"
  local src_unit="" src_env=""
  while (($#)); do case "$1" in
    --from) src_unit="${2:?--from needs a unit}"; shift 2;;
    --env)  src_env="${2:?--env needs a file}";  shift 2;;
    *) die "unknown arg: $1";;
  esac; done
  [[ -n "$src_unit" ]] || die "--from <src-unit> is required (the lane to clone)"
  local dir; dir="$(engine_dir "$engine_id")"
  [[ -d "$dir" ]] || die "no runtime at $dir — run: provision $engine_id"

  local unit_file="$UNITS_DIR/${lane_id}.service"
  local src_unit_file="$UNITS_DIR/${src_unit}.service"
  [[ -f "$src_unit_file" ]] || die "source unit not found: $src_unit_file"
  [[ -f "$unit_file" ]] && die "$unit_file already exists — refusing to overwrite"

  # env: copy the source lane env (default <src-unit>.env minus .service)
  src_env="${src_env:-$SECRETS_DIR/${src_unit%.service}.env}"
  [[ -f "$src_env" ]] || die "source env not found: $src_env"
  local env_file="$SECRETS_DIR/${lane_id}.env"
  [[ -f "$env_file" ]] && die "$env_file already exists"
  install -m 600 "$src_env" "$env_file"
  log "env: $src_env -> $env_file"

  # unit: copy + mechanical substitutions
  sed -e "s/${src_unit%.service}/$lane_id/g" \
      -e "s|$SHARED_DIR|$dir|g" \
      -e "s|%h/CascadeProjects/ada-voice|$dir|g" \
      -e "s|\$HOME/CascadeProjects/ada-voice|$dir|g" \
      "$src_unit_file" > "$unit_file"
  chmod 644 "$unit_file"
  log "unit: $src_unit_file -> $unit_file (paths -> $dir)"

  # isolation + stagger drop-ins (host-hygiene: every ada unit is capped)
  local iso="$UNITS_DIR/${lane_id}.service.d/isolation.conf"
  mkdir -p "$UNITS_DIR/${lane_id}.service.d"
  cat > "$iso" <<'EOF'
[Service]
MemoryMax=2G
CPUQuota=150%
LogRateLimitIntervalSec=30s
LogRateLimitBurst=1000
EOF
  log "caps: $iso (MemoryMax=2G CPUQuota=150%)"

  if [[ -x "$HOME/.local/bin/ada-start-stagger.sh" ]]; then
    cat > "$UNITS_DIR/${lane_id}.service.d/stagger.conf" <<EOF
# Fleet-restart stagger — same shape as stacks/idc03/ada-start-stagger.
[Service]
TimeoutStartSec=180
ExecStartPre=%h/.local/bin/ada-start-stagger.sh 120
EOF
    log "stagger drop-in written (offset 120s — adjust to taste)"
  else
    log "WARN: ada-start-stagger.sh not installed — stagger.conf skipped"
  fi

  cat <<EOF

Scaffold done. MANUAL STEPS before starting $lane_id:
  1. Edit $env_file — set ADA_INSTANCE_ID=$lane_id, PORT/port=$port,
     and any lane-specific keys/banks (it is a copy of ${src_unit%.service}.env).
  2. Check $unit_file — verify ExecStart/EnvironmentFile/port substitutions;
     the port may live in the env file or ExecStart args, not the unit.
  3. systemctl --user daemon-reload && systemctl --user start $lane_id
  4. curl -sf http://127.0.0.1:$port/api/health
  5. Declare it: stacks/idc03/<lane>/stack.yml + ssot.audit.hosts.yml
     expected_services (host-hygiene R1 — declared-or-dead).
EOF
}

cmd_status() {
  log "engines under $ENGINES_DIR:"
  if [[ -d "$ENGINES_DIR" ]]; then
    for d in "$ENGINES_DIR"/*/; do
      [[ -d "$d" ]] || continue
      local id; id="$(basename "$d")"
      local head py
      head="$(git -C "$d" rev-parse --short HEAD 2>/dev/null || echo '?')"
      py=$([[ -x "$d/.venv/bin/python" ]] && echo venv-ok || echo NO-VENV)
      printf '  %-16s %s  %s\n' "$id" "$head" "$py"
    done
  else
    echo "  (none — only ada-1 shared checkout at $SHARED_DIR)"
  fi
  echo
  log "engine bindings (drop-ins under $UNITS_DIR):"
  local found=0 f unit
  for f in "$UNITS_DIR"/*.service.d/engine-*.conf; do
    [[ -e "$f" ]] || continue
    found=1
    unit="$(basename "$(dirname "$(dirname "$f")")" .service.d)"
    printf '  %-24s -> %s\n' "$unit" "$(basename "$f" .conf | sed 's/^engine-//')"
  done
  (( found )) || echo "  (none — all lanes on shared ada-1 checkout)"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    provision) cmd_provision "$@";;
    bind)      cmd_bind "$@";;
    unbind)    cmd_unbind "$@";;
    lane)      cmd_lane "$@";;
    status|list) cmd_status "$@";;
    *) sed -n '2,30p' "$0"; exit 2;;
  esac
}
main "$@"
