#!/usr/bin/env bash
# kk-mac-runner-onboard.sh — provision kk-mac (KK's Mac Studio,
# Mac16,9 M4 Max 36GB, macOS 15.x) as a chaba dispatch RUNNER under
# kkkakk (card kk-mac-launchd-runner-port — KK approved full fleet
# use of kk-mac 2026-10-30).
#
# Runbook: docs/kb/kk-mac-launchd-runner.md
#
# Runs ON kk-mac as kkkakk — no sudo anywhere: the runner lives in
# the gui/<uid> domain of the logged-in user. The ONE manual step is
# enrolling the generated deploy key at GitHub (deploykey reports
# NEEDS-MANUAL until `git ls-remote` authenticates).
#
# Usage:
#   bash kk-mac-runner-onboard.sh [step ...]   # default: all
#   bash kk-mac-runner-onboard.sh preflight    # single step
#
# Steps: preflight dirs deploykey checkout reposconf opencode secrets
#        agent verify teardown
#
# Env:
#   RUNNER_CAP        claimed tasks at once (default 1 — shared family
#                     machine; raise only with Tony's sign-off)
#   RUNNER_LABELS     default "desktop,mac,arm64,cpu" — `desktop` arms
#                     the Nice/LowPriorityIO/ulimit limits profile so
#                     tasks stay out of KK's way
#   RUNNER_API        board api (default tailnet route, same as fleet)
#   LAUNCHD_DOMAIN    gui|user (default gui — needs kkkakk logged in;
#                     "user" survives headless operation)
#   EXPECT_MODEL      hw.model interlock (default Mac16,9)
set -euo pipefail

BREW=/opt/homebrew/bin/brew
EXPECT_MODEL="${EXPECT_MODEL:-Mac16,9}"
RUNNER_CAP="${RUNNER_CAP:-1}"
RUNNER_LABELS="${RUNNER_LABELS:-desktop,mac,arm64,cpu}"
RUNNER_API="${RUNNER_API:-https://idc03.taila0626a.ts.net:10000}"
LAUNCHD_DOMAIN="${LAUNCHD_DOMAIN:-gui}"

KK_HOME="${HOME:?run as kkkakk}"
CHABA_CHECKOUT="$KK_HOME/CascadeProjects/chaba"
DISPATCH_DIR="$KK_HOME/.local/share/devin-dispatch"
RUNNER_STATE="$KK_HOME/.local/share/runner-agent"
REPOS_CONF="$DISPATCH_DIR/repos.conf"
SSH_KEY="$KK_HOME/.ssh/id_chaba_deploy"
AGENT_BIN="$KK_HOME/.local/bin/runner-agent"
AGENT_LABEL=ai.chaba.runner-agent
AGENT_PLIST="$KK_HOME/Library/LaunchAgents/${AGENT_LABEL}.plist"

say()  { printf '\n== %s\n' "$*"; }
ok()   { printf '   ok: %s\n' "$*"; }
warn() { printf '   WARN: %s\n' "$*" >&2; }
die()  { printf '   FAIL: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

PYBIN=""   # resolved in preflight — runner needs >=3.10

# ---------------------------------------------------------------------------
step_preflight() {
    say "preflight"
    [ "$(uname -s)" = Darwin ] || die "not macOS"
    [ "$(uname -m)" = arm64 ]  || die "not arm64"
    local model
    model="$(sysctl -n hw.model)"
    [ "$model" = "$EXPECT_MODEL" ] || die "hw.model=$model (expected $EXPECT_MODEL) — EXPECT_MODEL='' to bypass"
    [ "$(id -un)" = "kkkakk" ] || warn "running as $(id -un), not kkkakk — the runner belongs to kkkakk's gui domain"
    sw_vers | head -2
    df -h / | tail -1

    # python >= 3.10 for runner-agent.py (str | Path annotations etc.)
    local p
    for p in /opt/homebrew/bin/python3 /usr/bin/python3 python3; do
        if have "$p" 2>/dev/null || [ -x "$p" ]; then
            if "$p" -c 'import sys; exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
                PYBIN="$p"; break
            fi
        fi
    done
    [ -n "$PYBIN" ] || die "python3 >= 3.10 not found — brew install python@3.12"
    ok "python: $PYBIN ($("$PYBIN" -V 2>&1))"
    have git || die "git missing — install CLT: xcode-select --install"
    have launchctl || die "launchctl missing"

    # gui domain needs a login session for THIS uid
    if launchctl print "gui/$(id -u)" >/dev/null 2>&1; then
        ok "gui/$(id -u) domain reachable (logged in)"
    else
        warn "gui/$(id -u) unreachable — the gui domain only exists while kkkakk is logged in; enable auto-login or use LAUNCHD_DOMAIN=user"
    fi
    ok "kk-mac confirmed ($model)"
}

# ---------------------------------------------------------------------------
step_dirs() {
    say "dirs"
    mkdir -p "$KK_HOME/.local/bin" "$KK_HOME/.config/secrets" \
             "$DISPATCH_DIR/tasks" "$RUNNER_STATE" \
             "$KK_HOME/CascadeProjects" "$KK_HOME/Library/LaunchAgents"
    chmod 700 "$KK_HOME/.config/secrets"
    ok "~/.local/bin, ~/.config/secrets, $DISPATCH_DIR, $RUNNER_STATE"
}

# ---------------------------------------------------------------------------
step_deploykey() {
    say "deploy key + gh-chaba ssh alias (push creds under kkkakk)"
    mkdir -p "$KK_HOME/.ssh" && chmod 700 "$KK_HOME/.ssh"
    if [ -f "$SSH_KEY" ]; then
        ok "key exists: $SSH_KEY"
    else
        ssh-keygen -t ed25519 -N '' -C "kk-mac chaba deploy key" -f "$SSH_KEY"
        ok "generated $SSH_KEY"
    fi
    # Host alias — the fleet's write path for chaba is the gh-chaba
    # ssh alias (runner-agent jules_merge_pr, idc03). Each host keeps
    # its own deploy key behind the same alias.
    local cfg="$KK_HOME/.ssh/config"
    touch "$cfg" && chmod 600 "$cfg"
    if grep -q '^Host gh-chaba$' "$cfg"; then
        ok "Host gh-chaba stanza present"
    else
        cat >> "$cfg" <<EOF
Host gh-chaba
    HostName github.com
    User git
    IdentityFile $SSH_KEY
    IdentitiesOnly yes
EOF
        ok "wrote Host gh-chaba -> $SSH_KEY"
    fi
    # https -> gh-chaba rewrite so every consumer (sync_repo clones,
    # the runner's git fetches, devin-dispatch worktrees) rides the
    # deploy key — same trick the fleet uses on push-capable hosts.
    git config --global url."gh-chaba:tonezzz/".insteadOf \
        "https://github.com/tonezzz/"
    ok "git insteadOf: https://github.com/tonezzz/ -> gh-chaba:tonezzz/"

    if git ls-remote gh-chaba:tonezzz/chaba.git HEAD >/dev/null 2>&1; then
        ok "deploy key AUTHENTICATES against tonezzz/chaba"
    else
        cat <<EOF
   NEEDS-MANUAL — enroll this deploy key (write access) at
   https://github.com/tonezzz/chaba/settings/keys/new :

$(cat "$SSH_KEY.pub")

   then re-run:  bash $0 deploykey
EOF
    fi
}

# ---------------------------------------------------------------------------
step_checkout() {
    say "exec checkout $CHABA_CHECKOUT"
    if [ -d "$CHABA_CHECKOUT/.git" ]; then
        git -C "$CHABA_CHECKOUT" fetch --depth 50 origin master \
            && git -C "$CHABA_CHECKOUT" reset --hard FETCH_HEAD
        ok "fetched + reset to origin/master"
    else
        git clone --depth 50 gh-chaba:tonezzz/chaba.git "$CHABA_CHECKOUT" \
            || die "clone failed — deploy key enrolled? (run 'deploykey')"
        ok "cloned"
    fi
    # role stamp + hooks — exec checkout, never the writer
    if [ -x "$CHABA_CHECKOUT/scripts/install-hooks.sh" ]; then
        (cd "$CHABA_CHECKOUT" && scripts/install-hooks.sh --role exec) \
            || warn "install-hooks failed — stamp $CHABA_CHECKOUT/.git/chaba-role 'exec' manually"
    else
        echo exec > "$CHABA_CHECKOUT/.git/chaba-role" 2>/dev/null \
            || echo exec > "$CHABA_CHECKOUT/chaba-role"
    fi
    ok "checkout ready (role=exec)"
}

# ---------------------------------------------------------------------------
step_reposconf() {
    say "repos.conf -> $REPOS_CONF"
    # Only repos this host actually holds — the push guard probes
    # git push --dry-run origin against each declared checkout.
    cat > "$REPOS_CONF" <<EOF
# devin-dispatch repo whitelist — kk-mac (kkkakk)
# <name> <abs path> <default_branch>
chaba   $CHABA_CHECKOUT   master
EOF
    ok "wrote $(cat "$REPOS_CONF" | grep -vc '^\s*#') repo row(s)"
    # probe the push path once — a no-op ref, dry-run only
    if git -C "$CHABA_CHECKOUT" push --dry-run origin \
            HEAD:refs/heads/__runner-push-probe >/dev/null 2>&1; then
        ok "push probe PASSES (push:chaba capability real)"
    else
        warn "push probe failed — runner will decline dispatch cards until push:chaba verifies; check the deploy key has WRITE access"
    fi
}

# ---------------------------------------------------------------------------
step_opencode() {
    say "opencode (darwin-arm64) for the opencode executor lanes"
    local oc="$KK_HOME/.opencode/bin/opencode"
    if [ -x "$oc" ]; then
        ok "present: $oc ($("$oc" --version 2>/dev/null | head -1))"
        return
    fi
    # official installer -> ~/.opencode/bin (runner-agent's
    # opencode_bin() resolver checks there, then ~/.local/bin, PATH)
    curl -fsSL https://opencode.ai/install | bash \
        || die "opencode install failed — https://opencode.ai/docs"
    [ -x "$oc" ] || die "installer ran but $oc missing"
    ok "installed $($oc --version 2>/dev/null | head -1)"
    [ -f "$KK_HOME/.config/secrets/litellm-keys.env" ] \
        || warn "~/.config/secrets/litellm-keys.env absent — opencode lane payloads source it for LITELLM_KEY_*; copy from a provisioned runner (idc02: ~/.config/secrets/)"
}

# ---------------------------------------------------------------------------
step_secrets() {
    say "secrets check"
    local missing=0
    for f in litellm-keys.env; do
        [ -f "$KK_HOME/.config/secrets/$f" ] \
            && ok "$f present" \
            || { warn "$f missing — opencode lane needs it"; missing=1; }
    done
    [ "$missing" = 0 ] || warn "copy the fleet's secrets set: scp -r idc02:~/.config/secrets/ ~/.config/secrets/ (or hand KK the canonical set)"
}

# ---------------------------------------------------------------------------
write_agent_plist() {
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYBIN:-python3}</string>
        <string>${AGENT_BIN}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key><string>${KK_HOME}</string>
        <key>PATH</key><string>${KK_HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>RUNNER_API</key><string>${RUNNER_API}</string>
        <key>RUNNER_HOST</key><string>kk-mac</string>
        <key>RUNNER_CAP</key><string>${RUNNER_CAP}</string>
        <key>RUNNER_MAX_LOAD_PC</key><string>1.0</string>
        <key>RUNNER_LABELS</key><string>${RUNNER_LABELS}</string>
        <key>RUNNER_TASK_RUNTIME</key><string>launchd</string>
        <key>RUNNER_LAUNCHD_DOMAIN</key><string>${LAUNCHD_DOMAIN}</string>
        <key>OPENCODE_LANES</key><string>1</string>
        <key>JEV_LANE</key><string>1</string>
    </dict>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>LowPriorityIO</key>
    <true/>
    <key>Nice</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${RUNNER_STATE}/runner-agent.log</string>
    <key>StandardErrorPath</key>
    <string>${RUNNER_STATE}/runner-agent.log</string>
</dict>
</plist>
EOF
}

step_agent() {
    say "runner-agent + LaunchAgent (${AGENT_LABEL}, 60s poll)"
    [ -f "$CHABA_CHECKOUT/scripts/board/runner-agent.py" ] \
        || die "no runner-agent.py — run 'checkout' first"
    install -m 755 "$CHABA_CHECKOUT/scripts/board/runner-agent.py" "$AGENT_BIN"
    ok "installed $AGENT_BIN"
    write_agent_plist > "$AGENT_PLIST"
    plutil -lint "$AGENT_PLIST" >/dev/null || die "generated plist failed lint"
    ok "wrote $AGENT_PLIST"
    local dom="${LAUNCHD_DOMAIN}/$(id -u)"
    if launchctl print "${dom}/${AGENT_LABEL}" >/dev/null 2>&1; then
        launchctl bootout "${dom}/${AGENT_LABEL}"
        ok "booted out stale registration"
    fi
    launchctl bootstrap "$dom" "$AGENT_PLIST" \
        || die "bootstrap failed — gui domain needs kkkakk logged in (or LAUNCHD_DOMAIN=user)"
    ok "registered in $dom — first poll within 60s"
}

# ---------------------------------------------------------------------------
step_verify() {
    say "verify"
    local dom="${LAUNCHD_DOMAIN}/$(id -u)"
    launchctl print "${dom}/${AGENT_LABEL}" >/dev/null 2>&1 \
        && launchctl print "${dom}/${AGENT_LABEL}" | grep -E 'state|program|arguments' | head -5 \
        || warn "agent not registered"
    sysctl -n vm.loadavg | sed 's/^/   vm.loadavg = /'
    git -C "$CHABA_CHECKOUT" log --oneline -1 | sed 's/^/   checkout: /'
    [ -x "$KK_HOME/.opencode/bin/opencode" ] \
        && "$KK_HOME/.opencode/bin/opencode" --version | sed 's/^/   opencode: /' \
        || warn "opencode missing"
    curl -sf -m 8 -o /dev/null "${RUNNER_API}/health" \
        && ok "board api reachable" \
        || warn "board api unreachable — tailscale up?"
    tail -20 "$RUNNER_STATE/runner-agent.log" 2>/dev/null | sed 's/^/   log: /' || true
    ok "verify done — a queued card with action.labels ⊆ [$RUNNER_LABELS] should claim on the next pass"
}

# ---------------------------------------------------------------------------
step_teardown() {
    say "teardown — removes the runner; keeps checkout + deploy key"
    [ "${CONFIRM_TEARDOWN:-0}" = 1 ] || die "set CONFIRM_TEARDOWN=1"
    local dom="${LAUNCHD_DOMAIN}/$(id -u)"
    launchctl bootout "${dom}/${AGENT_LABEL}" 2>/dev/null || true
    rm -f "$AGENT_PLIST" "$AGENT_BIN"
    # unfinished task jobs: bootout each registered devin-task-*/runner-*
    launchctl print "$dom" 2>/dev/null \
        | grep -oE '(devin-task|runner)-[A-Za-z0-9_-]+' | sort -u \
        | while read -r j; do
            launchctl bootout "${dom}/${j}" 2>/dev/null || true
            echo "   booted out $j"
        done
    rm -rf "$RUNNER_STATE/launchd" "$RUNNER_STATE/exit"
    cat <<EOF
   Kept: $CHABA_CHECKOUT, $SSH_KEY, ~/.ssh/config stanza,
   $REPOS_CONF, ~/.opencode/bin/opencode, $RUNNER_STATE logs.
   Remove by hand if the machine leaves the fleet.
EOF
    ok "teardown done"
}

# ---------------------------------------------------------------------------
main() {
    local steps="$*"
    [ -z "$steps" ] && steps="preflight dirs deploykey checkout reposconf opencode secrets agent verify"
    # preflight resolves PYBIN — always run it first when present
    case " $steps " in
        *" preflight "*) : ;;
        *) step_preflight >/dev/null ;;
    esac
    local s
    for s in $steps; do
        case "$s" in
            preflight|dirs|deploykey|checkout|reposconf|opencode|secrets|agent|verify|teardown)
                "step_${s//-/_}" ;;
            *) die "unknown step: $s" ;;
        esac
    done
}
main "$@"
