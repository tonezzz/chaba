#!/usr/bin/env bash
# openchamber-wire.sh — wire the claude-agent provider into OpenChamber's
# managed opencode on a host (the "tony-dell recipe" made repeatable).
#
# claude-agent is a native opencode provider (>= 2.2.x) that runs the local
# Claude Code binary via the Agent SDK — subscription auth, no API key. It is
# a separate provider lane: it does NOT go through LiteLLM.
#
# Usage:
#   openchamber-wire.sh                 wire the local host's OpenChamber
#   openchamber-wire.sh --check         verify only, no writes (exit 1 on fail)
#   openchamber-wire.sh --smoke         wire + send one real haiku prompt
#   openchamber-wire.sh --host HOST     run the same steps on HOST over ssh
#   openchamber-wire.sh --port N        override OpenChamber port discovery
#   openchamber-wire.sh --no-reload     skip POST /api/config/reload
#   openchamber-wire.sh --force         rewrite env var + re-login + reload
#
# Steps (idempotent — a fully wired host gets zero writes and no reload):
#   1. Ensure pinned claude-code install at
#      ~/CascadeProjects/tony-projects/claude-code (exact pin
#      $CLAUDE_CODE_VERSION, default 2.1.327).
#   2. Require `claude auth status` -> loggedIn:true. OAuth login cannot be
#      automated — if absent, run `claude auth login` on the host manually.
#   3. Discover the OpenChamber port: --port flag > systemd user unit
#      ExecStart > running process args > probe :3000.
#   4. PUT /api/environment {variables:{OPENCODE_CLAUDE_PATH:<claude bin>}}.
#      The env store is CACHED IN MEMORY — direct edits to
#      ~/.config/openchamber/environment.json do not apply; use this API or
#      Settings > General > Environment variables.
#   5. `opencode auth login claude-agent --method claude-login`
#      (non-interactive; records an external credential in opencode.db).
#   6. POST /api/config/reload when the env var changed or login was fresh —
#      the managed opencode restart defers while sessions are busy.
#   7. Verify GET /api/model lists claude-agent models enabled.
#   8. --smoke: POST /api/session -> POST /api/session/<id>/model
#      {model:{id:"haiku",providerID:"claude-agent",modelID:"haiku"}}
#      — id must be the BARE model id; "claude-agent/haiku" doubles the
#      prefix and 400s — then POST /api/session/<id>/prompt {text:"..."}
#      (opencode >= 2.3 shape; older 2.x took parts[]) and poll
#      GET /api/session/<id>/message for a claude-agent assistant reply.
#
# OpenChamber API auth: mints a UI session JWT (HS256, {type:"ui-session"})
# from ~/.config/openchamber/jwt-secret and sends it as cookie
# oc_ui_session_<port>. Fallback: POST /auth/session with
# OPENCHAMBER_UI_PASSWORD read from ~/.config/openchamber/startup.env.

set -euo pipefail

PIN="${CLAUDE_CODE_VERSION:-2.1.327}"
CLAUDE_DIR="${CLAUDE_CODE_DIR:-$HOME/CascadeProjects/tony-projects/claude-code}"
OC_CFG="${OPENCHAMBER_CONFIG_DIR:-$HOME/.config/openchamber}"
VAR_NAME="OPENCODE_CLAUDE_PATH"
SMOKE_MODEL="haiku"
SMOKE_PROMPT="Reply with exactly one word: ok"

MODE="wire"          # wire | check
SMOKE=0
FORCE=0
NO_RELOAD=0
PORT=""
HOST=""
VERBOSE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE="check" ;;
    --smoke) SMOKE=1 ;;
    --force) FORCE=1 ;;
    --no-reload) NO_RELOAD=1 ;;
    --port) PORT="${2:?--port needs a value}"; shift ;;
    --host) HOST="${2:?--host needs a value}"; shift ;;
    -v|--verbose) VERBOSE=1 ;;
    -h|--help) sed -n '2,50p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

# --- remote mode: re-run this same script on the target host ---------------
if [ -n "$HOST" ]; then
  args=()
  [ "$MODE" = "check" ] && args+=(--check)
  [ "$SMOKE" = 1 ] && args+=(--smoke)
  [ "$FORCE" = 1 ] && args+=(--force)
  [ "$NO_RELOAD" = 1 ] && args+=(--no-reload)
  [ -n "$PORT" ] && args+=(--port "$PORT")
  [ "$VERBOSE" = 1 ] && args+=(--verbose)
  exec ssh -o BatchMode=yes "$HOST" \
    "CLAUDE_CODE_VERSION='$PIN' bash -s -- ${args[*]:-}" < "$0"
fi

log()  { printf '%s\n' "$*"; }
vlog() { [ "$VERBOSE" = 1 ] && printf '  %s\n' "$*" || true; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing required tool: $1"; }

need curl

# --- helpers ----------------------------------------------------------------

# Mint an OpenChamber UI session JWT. Prints the token or nothing.
mint_jwt() {
  local secret_file="$OC_CFG/jwt-secret"
  [ -r "$secret_file" ] || return 1
  python3 - "$secret_file" <<'PY' 2>/dev/null || return 1
import json, hmac, hashlib, base64, time, sys
secret = open(sys.argv[1], 'rb').read().strip()
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=')
now = int(time.time())
h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
p = b64(json.dumps({"type": "ui-session", "iat": now, "exp": now + 900}).encode())
s = b64(hmac.new(secret, h + b'.' + p, hashlib.sha256).digest())
print((h + b'.' + p + b'.' + s).decode())
PY
}

COOKIE=""        # "oc_ui_session_<port>=<token>" once auth is resolved
BASE=""          # http://127.0.0.1:<port>

# api METHOD PATH [JSON_BODY] -> body on stdout; returns curl http code in $?
api() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS -X "$method" -H 'Accept: application/json')
  [ -n "$COOKIE" ] && args+=(-H "Cookie: $COOKIE")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' -d "$body")
  curl "${args[@]}" "$BASE$path"
}

# api_status METHOD PATH [JSON_BODY] -> "<code> <body>" ; does not die on 4xx
api_status() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS -X "$method" -H 'Accept: application/json' -o /tmp/ocwire-body.$$ -w '%{http_code}')
  [ -n "$COOKIE" ] && args+=(-H "Cookie: $COOKIE")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' -d "$body")
  local code
  code=$(curl "${args[@]}" "$BASE$path" || true)
  local out
  out=$(cat /tmp/ocwire-body.$$ 2>/dev/null || true)
  rm -f /tmp/ocwire-body.$$
  printf '%s %s' "$code" "$out"
}

json_get() {  # json_get '<expr>' — python3 json eval on stdin
  python3 -c "import json,sys
d=json.load(sys.stdin)
$1" 2>/dev/null
}

# --- step 1: pinned claude-code install -------------------------------------

claude_bin() { printf '%s' "$CLAUDE_DIR/node_modules/.bin/claude"; }

ensure_claude() {
  local bin; bin=$(claude_bin)
  if [ ! -x "$bin" ]; then
    [ "$MODE" = "check" ] && fail "claude binary missing: $bin"
    log "[1] claude-code not installed at $CLAUDE_DIR — installing pinned $PIN"
    need npm
    mkdir -p "$CLAUDE_DIR"
    if [ -x "$CLAUDE_DIR/install.sh" ]; then
      (cd "$CLAUDE_DIR" && CLAUDE_CODE_VERSION="$PIN" ./install.sh >/dev/null)
    else
      (cd "$CLAUDE_DIR" && \
        { [ -f package.json ] || npm init -y >/dev/null; } && \
        npm install --save-exact "@anthropic-ai/claude-code@$PIN" >/dev/null)
    fi
    [ -x "$bin" ] || fail "install finished but $bin still missing"
  fi
  local ver; ver=$("$bin" --version 2>/dev/null | awk '{print $1}')
  log "[1] claude-code $ver at $bin"
  if [ "$ver" != "$PIN" ]; then
    if [ "$MODE" = "wire" ]; then
      log "    pinned version is $PIN — running install.sh to re-pin"
      (cd "$CLAUDE_DIR" && { [ -x install.sh ] && CLAUDE_CODE_VERSION="$PIN" ./install.sh >/dev/null; } || \
        npm install --save-exact "@anthropic-ai/claude-code@$PIN" >/dev/null)
      ver=$("$bin" --version 2>/dev/null | awk '{print $1}')
    fi
    [ "$ver" = "$PIN" ] || log "    WARN: version $ver != pin $PIN"
  fi
  CLAUDE_BIN="$bin"
}

# --- step 2: claude auth ------------------------------------------------------

check_claude_auth() {
  local status logged
  status=$("$CLAUDE_BIN" auth status 2>/dev/null || true)
  logged=$(printf '%s' "$status" | json_get 'print(d.get("loggedIn"))' || true)
  if [ "$logged" = "True" ]; then
    log "[2] claude auth: logged in ($(printf '%s' "$status" | json_get 'print(d.get("authMethod","?"))'))"
    return 0
  fi
  if [ "$MODE" = "check" ]; then
    log "[2] claude auth: NOT logged in"
    return 1
  fi
  fail "claude not authenticated on this host — run: $CLAUDE_BIN auth login"
}

# --- step 3: discover OpenChamber ---------------------------------------------

discover_port() {
  if [ -n "$PORT" ]; then return 0; fi
  local p=""
  # systemd user unit ExecStart --port
  p=$(systemctl --user cat openchamber.service 2>/dev/null \
      | grep -oE '\-\-port[ =][0-9]+' | grep -oE '[0-9]+' | head -1 || true)
  # running process args
  [ -z "$p" ] && p=$(pgrep -af 'openchamber.*serve' 2>/dev/null \
      | grep -oE '\-\-port[ =][0-9]+' | grep -oE '[0-9]+' | head -1 || true)
  # last resort: the conventional port
  PORT="${p:-3000}"
  vlog "discovered OpenChamber port: $PORT (from ${p:+config}${p:-default})"
}

resolve_auth() {
  BASE="http://127.0.0.1:$PORT"
  # Fast path: no UI password configured => API is open on loopback.
  local probe
  probe=$(api_status GET /api/environment)
  if [ "${probe%% *}" = "200" ]; then
    log "[3] OpenChamber on :$PORT (no auth required)"
    return 0
  fi
  # Preferred: minted JWT (works without knowing the UI password).
  local tok
  if tok=$(mint_jwt) && [ -n "$tok" ]; then
    COOKIE="oc_ui_session_$PORT=$tok"
    probe=$(api_status GET /api/environment)
    if [ "${probe%% *}" = "200" ]; then
      log "[3] OpenChamber on :$PORT (minted UI JWT)"
      return 0
    fi
    COOKIE=""
    vlog "minted JWT rejected (${probe%% *}) — trying password login"
  fi
  # Fallback: password session via /auth/session.
  local pw=""
  if [ -r "$OC_CFG/startup.env" ]; then
    pw=$(grep -E '^OPENCHAMBER_UI_PASSWORD=' "$OC_CFG/startup.env" \
         | head -1 | cut -d= -f2- | tr -d "\"'" || true)
  fi
  if [ -n "$pw" ]; then
    curl -sS -X POST -H 'Content-Type: application/json' \
      -d "{\"password\":\"$pw\"}" -D /tmp/ocwire-hdr.$$ -o /dev/null \
      "$BASE/auth/session" >/dev/null 2>&1 || true
    COOKIE=$(grep -i '^set-cookie:' /tmp/ocwire-hdr.$$ 2>/dev/null \
      | grep -oE "oc_ui_session_${PORT}=[^;]+" | head -1 || true)
    rm -f /tmp/ocwire-hdr.$$
    if [ -n "$COOKIE" ]; then
      probe=$(api_status GET /api/environment)
      [ "${probe%% *}" = "200" ] && { log "[3] OpenChamber on :$PORT (password session)"; return 0; }
      COOKIE=""
    fi
  fi
  fail "cannot authenticate to OpenChamber on :$PORT (last probe: ${probe%% *}). Check OPENCHAMBER_UI_PASSWORD/jwt-secret under $OC_CFG"
}

# --- step 4: register OPENCODE_CLAUDE_PATH ------------------------------------

ENV_FILE_READABLE=0
ENV_VALUE=""
read_env_file() {  # best-effort read of the on-disk store for change detect
  ENV_FILE_READABLE=0; ENV_VALUE=""
  [ -r "$OC_CFG/environment.json" ] || return 0
  ENV_FILE_READABLE=1
  ENV_VALUE=$(json_get "print(d.get('user',{}).get('variables',{}).get('$VAR_NAME') or '')" \
    < "$OC_CFG/environment.json" || true)
}

wire_env() {
  local want="$CLAUDE_BIN" have changed=1
  read_env_file; have="$ENV_VALUE"
  if [ "$ENV_FILE_READABLE" = 1 ] && [ "$have" = "$want" ]; then changed=0; fi

  if [ "$MODE" = "check" ]; then
    local names
    names=$(api GET /api/environment | json_get 'print(" ".join(d.get("names",[])))' || true)
    case " $names " in
      *" $VAR_NAME "*) log "[4] $VAR_NAME registered${have:+ (=$have)}" ;;
      *) log "[4] $VAR_NAME NOT registered"; return 1 ;;
    esac
    if [ "$ENV_FILE_READABLE" = 1 ]; then
      [ "$have" = "$want" ] || { log "    value mismatch: want $want"; return 1; }
    else
      log "    WARN: $OC_CFG/environment.json unreadable — value not verified"
    fi
    return 0
  fi

  if [ "$changed" = 0 ] && [ "$FORCE" = 0 ]; then
    log "[4] $VAR_NAME already = $want (unchanged)"
    return 0
  fi
  local resp
  resp=$(api_status PUT /api/environment "{\"variables\":{\"$VAR_NAME\":\"$want\"}}")
  [ "${resp%% *}" = "200" ] || fail "PUT /api/environment -> $resp"
  log "[4] $VAR_NAME registered -> $want"
  ENV_CHANGED=1
}

# --- step 5: opencode auth login ----------------------------------------------

opencode_bin() {
  if command -v opencode >/dev/null 2>&1; then command -v opencode; return; fi
  for c in "$HOME/.local/node/bin/opencode" /usr/local/bin/opencode \
           "$(grep -E '^OPENCODE_BINARY=' "$OC_CFG/startup.env" 2>/dev/null | cut -d= -f2- | tr -d '"')"; do
    [ -n "$c" ] && [ -x "$c" ] && { printf '%s' "$c"; return; }
  done
  return 1
}

wire_auth() {
  local oc; oc=$(opencode_bin) || fail "opencode binary not found on this host"
  local stored
  stored=$("$oc" auth list 2>/dev/null | grep -ic 'claude agent.*stored\|claude-agent' || true)
  if [ "$MODE" = "check" ]; then
    [ "${stored:-0}" -ge 1 ] && log "[5] opencode credential: Claude Agent stored" || { log "[5] opencode credential: Claude Agent NOT stored"; return 1; }
    return 0
  fi
  if [ "${stored:-0}" -ge 1 ] && [ "$FORCE" = 0 ]; then
    log "[5] opencode credential: Claude Agent already stored"
    return 0
  fi
  "$oc" auth login claude-agent --method claude-login </dev/null >/dev/null 2>&1 \
    || "$oc" auth login claude-agent </dev/null >/dev/null
  log "[5] opencode credential: Claude Agent stored (claude-login)"
  AUTH_CHANGED=1
}

# --- step 6: config reload ------------------------------------------------------

maybe_reload() {
  [ "$MODE" = "check" ] && return 0
  if [ "$NO_RELOAD" = 1 ]; then log "[6] reload skipped (--no-reload)"; return 0; fi
  if [ "${ENV_CHANGED:-0}" = 0 ] && [ "${AUTH_CHANGED:-0}" = 0 ] && [ "$FORCE" = 0 ]; then
    log "[6] reload skipped (nothing changed)"
    return 0
  fi
  local resp
  resp=$(api_status POST /api/config/reload '{}')
  log "[6] POST /api/config/reload -> ${resp%% *} (managed opencode restart defers while sessions are busy)"
}

# --- step 7: verify models ------------------------------------------------------

claude_models() {
  api GET /api/model | json_get '
ms = d.get("data", d if isinstance(d, list) else [])
en = sorted(m["id"] for m in ms if m.get("providerID") == "claude-agent" and m.get("enabled"))
print(" ".join(en))' || true
}

verify_models() {
  local deadline=$((SECONDS + ${1:-15})) models=""
  while [ $SECONDS -lt $deadline ]; do
    models=$(claude_models)
    [ -n "$models" ] && break
    sleep 3
  done
  if [ -z "$models" ]; then
    log "[7] FAIL: no enabled claude-agent models in GET /api/model"
    return 1
  fi
  log "[7] claude-agent models enabled: $models"
  for m in opus sonnet haiku; do
    case " $models " in *" $m "*) ;; *) log "    WARN: expected model '$m' not listed" ;; esac
  done
}

# --- step 8: smoke prompt -------------------------------------------------------

smoke() {
  log "[8] smoke: creating session"
  local sid
  sid=$(api POST /api/session '{}' | json_get 'print(d.get("data",{}).get("id") or d.get("id",""))')
  [ -n "$sid" ] || fail "session create returned no id"
  vlog "session $sid"
  local resp
  resp=$(api_status POST "/api/session/$sid/model" \
    "{\"model\":{\"id\":\"$SMOKE_MODEL\",\"providerID\":\"claude-agent\",\"modelID\":\"$SMOKE_MODEL\"}}")
  [ "${resp%% *}" = "204" ] || [ "${resp%% *}" = "200" ] || \
    fail "model switch -> $resp (use the BARE model id, not claude-agent/$SMOKE_MODEL)"
  resp=$(api_status POST "/api/session/$sid/prompt" "{\"text\":\"$SMOKE_PROMPT\"}")
  [ "${resp%% *}" = "200" ] || fail "prompt -> $resp"
  local deadline=$((SECONDS+120)) reply=""
  while [ $SECONDS -lt $deadline ]; do
    sleep 4
    reply=$(api GET "/api/session/$sid/message" | json_get '
for m in d.get("data", []):
    if m.get("type") == "assistant" and m.get("model", {}).get("providerID") == "claude-agent" and m.get("finish"):
        txt = "".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
        print(txt.strip()[:200]); break' || true)
    [ -n "$reply" ] && break
  done
  api_status DELETE "/api/session/$sid" >/dev/null || true
  [ -n "$reply" ] || fail "no claude-agent assistant reply within 120s"
  log "[8] smoke OK — claude-agent/$SMOKE_MODEL replied: $reply"
}

# --- main ----------------------------------------------------------------------

log "== openchamber-wire ($MODE$([ $SMOKE = 1 ] && echo ' +smoke')) on $(hostname) =="

ensure_claude
check_claude_auth || CHECK_FAIL=1
discover_port
resolve_auth

STEP_RC=0
wire_env || STEP_RC=1
wire_auth || STEP_RC=1
maybe_reload
verify_models "${VERIFY_WAIT:-60}" || STEP_RC=1
[ "$SMOKE" = 1 ] && [ "$MODE" = "wire" ] && { smoke || STEP_RC=1; }

if [ "$STEP_RC" = 0 ] && [ "${CHECK_FAIL:-0}" = 0 ]; then
  log "== done: claude-agent provider $([ "$MODE" = check ] && echo verified || echo wired) =="
else
  fail "one or more steps failed (see above)"
fi
