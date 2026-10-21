#!/usr/bin/env bash
# kk-mac-onboard.sh — idempotent Ada Nest onboarding for kk-mac
# (KK's Mac Studio, Mac16,9 M4 Max 36GB, macOS 15.x).
#
# Card: kk-mac-ada-nest-onboarding (ADA-0765)
# Runbook: docs/kb/ada-nest-kk-mac-onboarding.md
#
# Runs ON kk-mac as an admin user (kkkakk). Sudo steps prompt — that is
# intentional: KK is present and signs off at install time.
#
# Usage:
#   bash kk-mac-onboard.sh [step ...]        # default: all
#   bash kk-mac-onboard.sh preflight         # single step
#   ssh -t kkkakk@<ip> 'bash -s' < kk-mac-onboard.sh   # remote, sudo prompts
#
# Steps: preflight power user keys ollama-daemon tailscale models verify
#        teardown (destructive — explicit only)
#
# Env:
#   FLEET_KEYS_FILE  file of ssh pubkey lines seeded into adanest (and
#                    kkkakk with SEED_KKKAKK=1) authorized_keys.
#   MODELS           ollama pulls as adanest (default "llama3.1:8b qwen3:14b")
#   OLLAMA_BIND      ollama listen addr (default 127.0.0.1:11434 — tailnet
#                    or LAN binding is a later, explicit choice)
#   TAILSCALE_SSH    1 → `tailscale up --ssh` after install
#   ADANEST_UID      override auto-picked UID (first free >= 503)
#   EXPECT_MODEL     expected hw.model (default Mac16,9) — safety interlock
set -euo pipefail

BREW=/opt/homebrew/bin/brew
OLLAMA=/opt/homebrew/bin/ollama
PLIST_LABEL=ai.adanest.ollama
PLIST_PATH=/Library/LaunchDaemons/${PLIST_LABEL}.plist
ADANEST_HOME=/Users/adanest
EXPECT_MODEL="${EXPECT_MODEL:-Mac16,9}"
MODELS="${MODELS:-llama3.1:8b qwen3:14b}"
OLLAMA_BIND="${OLLAMA_BIND:-127.0.0.1:11434}"

say()  { printf '\n== %s\n' "$*"; }
ok()   { printf '   ok: %s\n' "$*"; }
warn() { printf '   WARN: %s\n' "$*" >&2; }
die()  { printf '   FAIL: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
step_preflight() {
    say "preflight"
    [ "$(uname -s)" = Darwin ] || die "not macOS"
    [ "$(uname -m)" = arm64 ]  || die "not arm64"
    local model
    model="$(sysctl -n hw.model)"
    [ "$model" = "$EXPECT_MODEL" ] || die "hw.model=$model (expected $EXPECT_MODEL) — refusing to run on the wrong machine (EXPECT_MODEL='' to bypass)"
    sw_vers
    df -h / | tail -1
    local free_gb
    free_gb=$(df -g / | tail -1 | awk '{print $4}')
    [ "${free_gb:-0}" -ge 30 ] || warn "only ${free_gb}GB free — model pulls want ~20GB headroom"
    [ -x "$BREW" ]   || die "homebrew missing at $BREW"
    [ -x "$OLLAMA" ] || die "ollama missing at $OLLAMA"
    ok "kk-mac confirmed ($model), brew + ollama present"
}

# ---------------------------------------------------------------------------
step_power() {
    say "power policy — no system sleep on AC, keep wake-on-LAN"
    sudo pmset -a sleep 0 disksleep 0 displaysleep 15 womp 1 powernap 0
    pmset -g | grep -E 'sleep|displaysleep|womp|powernap|disksleep'
    ok "pmset applied"
}

# ---------------------------------------------------------------------------
pick_uid() {
    local u=503
    while dscl . -list /Users UniqueID 2>/dev/null | awk '{print $2}' | grep -qx "$u"; do
        u=$((u+1))
    done
    echo "$u"
}

step_user() {
    say "adanest service user (standard, hidden, no password login)"
    if id adanest >/dev/null 2>&1; then
        ok "adanest exists (uid $(id -u adanest))"
    else
        local uid="${ADANEST_UID:-$(pick_uid)}"
        sudo dscl . -create /Users/adanest
        sudo dscl . -create /Users/adanest UserShell /bin/bash
        sudo dscl . -create /Users/adanest RealName "Ada Nest"
        sudo dscl . -create /Users/adanest UniqueID "$uid"
        sudo dscl . -create /Users/adanest PrimaryGroupID 20
        sudo dscl . -create /Users/adanest NFSHomeDirectory "$ADANEST_HOME"
        sudo dscl . -create /Users/adanest IsHidden 1
        sudo dscl . -create /Users/adanest Password '*'
        sudo createhomedir -c -u adanest >/dev/null 2>&1 || true
        ok "adanest created (uid $uid)"
    fi
    # Remote Login group: only needed when sshd is restricted to a group.
    if dscl . -read /Groups/com.apple.access_ssh >/dev/null 2>&1; then
        if ! dscl . -read /Groups/com.apple.access_ssh GroupMembership 2>/dev/null | grep -qw adanest; then
            sudo dseditgroup -o edit -a adanest -t user com.apple.access_ssh
            ok "adanest added to com.apple.access_ssh"
        fi
    else
        ok "com.apple.access_ssh absent — Remote Login allows all users"
    fi
    sudo -u adanest mkdir -p "$ADANEST_HOME/.ssh" "$ADANEST_HOME/Library/Logs"
    sudo -u adanest chmod 700 "$ADANEST_HOME/.ssh"
}

# ---------------------------------------------------------------------------
seed_keys_for() {  # $1=user $2=home
    local user="$1" home="$2" key as=""
    [ "$user" = "$(id -un)" ] || as="sudo -u $user"
    $as touch "$home/.ssh/authorized_keys"
    $as chmod 600 "$home/.ssh/authorized_keys"
    while IFS= read -r key; do
        case "$key" in ''|'#'*) continue;; esac
        if ! $as grep -qF "$key" "$home/.ssh/authorized_keys"; then
            printf '%s\n' "$key" | $as tee -a "$home/.ssh/authorized_keys" >/dev/null
            ok "seeded ${key##* } -> $user"
        fi
    done < "$FLEET_KEYS_FILE"
}

step_keys() {
    say "fleet ssh keys"
    [ -n "${FLEET_KEYS_FILE:-}" ] || die "FLEET_KEYS_FILE not set — see runbook §1 for the standard key set"
    [ -f "$FLEET_KEYS_FILE" ]     || die "FLEET_KEYS_FILE=$FLEET_KEYS_FILE unreadable"
    id adanest >/dev/null 2>&1 || die "adanest missing — run 'user' step first"
    seed_keys_for adanest "$ADANEST_HOME"
    if [ "${SEED_KKKAKK:-0}" = 1 ]; then
        mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
        seed_keys_for "$(id -un)" "$HOME"
    fi
}

# ---------------------------------------------------------------------------
write_plist() {  # stdout
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>UserName</key>
    <string>adanest</string>
    <key>ProgramArguments</key>
    <array>
        <string>${OLLAMA}</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${ADANEST_HOME}</string>
        <key>OLLAMA_HOST</key>
        <string>${OLLAMA_BIND}</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>${ADANEST_HOME}/Library/Logs/ollama.log</string>
    <key>StandardErrorPath</key><string>${ADANEST_HOME}/Library/Logs/ollama.err.log</string>
    <key>SoftResourceLimits</key>
    <dict><key>NumberOfFiles</key><integer>4096</integer></dict>
</dict>
</plist>
EOF
}

step_ollama_daemon() {
    say "ollama LaunchDaemon (boot-level, runs as adanest)"
    id adanest >/dev/null 2>&1 || die "adanest missing — run 'user' step first"

    # Migrate the kkkakk-owned nohup server: keep her model pulls.
    if pgrep -u "$(id -un)" -f 'ollama serve' >/dev/null 2>&1; then
        warn "user-session 'ollama serve' running under $(id -un) — will stop after daemon is up"
    fi
    if [ -d "$HOME/.ollama/models" ] && [ ! -d "$ADANEST_HOME/.ollama/models" ]; then
        say "migrating $HOME/.ollama -> $ADANEST_HOME/.ollama (keeps pulled models)"
        sudo ditto "$HOME/.ollama" "$ADANEST_HOME/.ollama"
        sudo chown -R adanest:staff "$ADANEST_HOME/.ollama"
    fi

    local want
    want="$(write_plist)"
    if [ -f "$PLIST_PATH" ] && [ "$(sudo cat "$PLIST_PATH")" = "$want" ]; then
        ok "plist unchanged"
    else
        printf '%s\n' "$want" | sudo tee "$PLIST_PATH" >/dev/null
        sudo chown root:wheel "$PLIST_PATH"; sudo chmod 644 "$PLIST_PATH"
        ok "wrote $PLIST_PATH"
    fi

    if sudo launchctl print "system/${PLIST_LABEL}" >/dev/null 2>&1; then
        sudo launchctl kickstart -k "system/${PLIST_LABEL}"
    else
        sudo launchctl bootstrap system "$PLIST_PATH" \
          || sudo launchctl load -w "$PLIST_PATH"   # pre-bootstrap fallback
    fi
    # Stop the login-session server once the daemon owns :11434.
    sleep 2
    if curl -sf "http://${OLLAMA_BIND}/api/tags" >/dev/null 2>&1; then
        pkill -u "$(id -un)" -f 'ollama serve' 2>/dev/null || true
        ok "daemon serving on ${OLLAMA_BIND}; login-session server stopped"
    else
        warn "daemon not answering yet — check ${ADANEST_HOME}/Library/Logs/ollama.err.log"
    fi
}

# ---------------------------------------------------------------------------
step_tailscale() {
    say "tailscale (away-from-home reachability)"
    if [ -d /Applications/Tailscale.app ]; then
        ok "Tailscale.app already installed"
    else
        "$BREW" install --cask tailscale
        ok "tailscale cask installed"
    fi
    cat <<'EOF'
   MANUAL (KK at the console — cannot be scripted):
     1. open /Applications/Tailscale.app
     2. approve the system extension when prompted
        (System Settings -> General -> Login Items & Extensions ->
         Network Extensions if macOS defers it)
     3. sign in — browser flow as tony's tailnet invite, or:
        sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale up --authkey <tskey>
EOF
    if [ "${TAILSCALE_SSH:-0}" = 1 ]; then
        sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale up --ssh
        ok "tailscale up --ssh"
    fi
}

# ---------------------------------------------------------------------------
step_models() {
    say "model pulls as adanest: ${MODELS}"
    curl -sf "http://${OLLAMA_BIND}/api/tags" >/dev/null \
        || die "ollama not serving on ${OLLAMA_BIND} — run 'ollama-daemon' first"
    local m
    for m in $MODELS; do
        sudo -u adanest env HOME="$ADANEST_HOME" OLLAMA_HOST="$OLLAMA_BIND" \
            "$OLLAMA" pull "$m"
        ok "pulled $m"
    done
}

# ---------------------------------------------------------------------------
step_verify() {
    say "verify"
    pmset -g | grep -E '^\s*(sleep|displaysleep|disksleep|womp)' || true
    id adanest
    sudo launchctl print "system/${PLIST_LABEL}" 2>/dev/null | grep -E 'state|pid|program' || warn "daemon not loaded"
    curl -sf "http://${OLLAMA_BIND}/api/tags" | python3 -c 'import json,sys;print("models:",[m["name"] for m in json.load(sys.stdin)["models"]])' \
        || warn "ollama :api/tags failed"
    [ -d /Applications/Tailscale.app ] \
        && sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale status 2>/dev/null | head -4 \
        || warn "Tailscale.app not installed"
    ok "verify done — review WARNs above"
}

# ---------------------------------------------------------------------------
step_teardown() {
    say "teardown — reverses user/ollama-daemon; brew+tailscale removal is manual"
    [ "${CONFIRM_TEARDOWN:-0}" = 1 ] || die "set CONFIRM_TEARDOWN=1 — this deletes the adanest user + plist"
    sudo launchctl bootout "system/${PLIST_LABEL}" 2>/dev/null || true
    sudo rm -f "$PLIST_PATH"
    sudo sysadminctl -deleteUser adanest 2>/dev/null || sudo dscl . -delete /Users/adanest
    sudo rm -rf "$ADANEST_HOME"
    cat <<'EOF'
   Remaining manual teardown: brew uninstall --cask ollama tailscale;
   delete /opt/homebrew if brew is otherwise unused; restore pmset if
   KK wants sleep back: sudo pmset -a sleep 1 powernap 1
EOF
    ok "teardown done"
}

# ---------------------------------------------------------------------------
main() {
    local steps="$*"
    [ -z "$steps" ] && steps="preflight power user keys ollama-daemon tailscale models verify"
    local s
    for s in $steps; do
        case "$s" in
            preflight|power|user|keys|ollama-daemon|tailscale|models|verify|teardown)
                "step_${s//-/_}" ;;
            *) die "unknown step: $s" ;;
        esac
    done
}
main "$@"
