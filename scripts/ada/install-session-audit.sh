#!/usr/bin/env bash
# install-session-audit.sh — install the Ada session-audit timer on tony-dell.
#
# Bundles session-audit.py + the rendered systemd user units
# (systemd/generated/tony_dell/session-audit.{service,timer} from
# ssot.jobs.yml), pushes them over ssh, and enables the timer. The audit
# runs self-contained from ~/.local/share/session-audit/ — deliberately
# NOT the repo checkout, so a stale/divergent checkout can never break it
# (same policy as install-log-shipper.sh).
#
# Usage:
#   install-session-audit.sh                 # install on tony-dell
#   install-session-audit.sh tony-dell       # same, explicit
#   install-session-audit.sh --via tony-omen # push through a jump host
#   install-session-audit.sh --no-run        # install, don't self-test
#
# The installed unit needs, on the target host:
#   * ssh idc03 (journal + transcripts) and ssh idc01 (archive) — BatchMode
#   * MDDB reachable (leader, MDDB_BASE_URL in the unit env)
#   * board-api on 127.0.0.1:8787 (loopback caller is trusted)
#   * PyYAML for focus-inbox writes (dell has it)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRIPT="$HERE/session-audit.py"
GEN="$REPO/systemd/generated"
STAGE='~/.cache/session-audit-install'

VIA=""
RUN=1
HOSTS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --via) VIA="$2"; shift ;;
        --no-run) RUN=0 ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
        *) HOSTS+=("$1") ;;
    esac
    shift
done
[ ${#HOSTS[@]} -gt 0 ] || HOSTS=(tony-dell)

# Re-render generated units from the manifest (idempotent).
python3 "$REPO/scripts/render-jobs.py" >/dev/null

ssot_key() { echo "$1" | tr '-' '_'; }

on() {
    if [ -n "$VIA" ]; then
        ssh -o BatchMode=yes -o ConnectTimeout=8 "$VIA" \
            "ssh -o BatchMode=yes -o ConnectTimeout=8 $host $(printf '%q' "$1")"
    else
        ssh -o BatchMode=yes -o ConnectTimeout=8 "$host" "$1"
    fi
}

write_remote_install() {
    cat > "$1/remote-install.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
S="$HOME/.cache/session-audit-install"
D="$HOME/.local/share/session-audit"
U="$HOME/.config/systemd/user"
mkdir -p "$D" "$U"
install -m 0644 "$S/session-audit.py" "$D/session-audit.py"
install -m 0644 "$S/session-audit.service" "$S/session-audit.timer" "$U/"
systemctl --user daemon-reload
systemctl --user enable --now session-audit.timer
echo "installed + armed: session-audit.timer"
systemctl --user list-timers session-audit.timer --no-pager
EOS
    cat > "$1/run-once.sh" <<'EOS'
#!/usr/bin/env bash
# self-test only — a real run bumps the production marker
/usr/bin/python3 "$HOME/.local/share/session-audit/session-audit.py" --selftest 2>&1 | tail -5
EOS
}

for host in "${HOSTS[@]}"; do
    key="$(ssot_key "$host")"
    gdir="$GEN/$key"
    for u in session-audit.service session-audit.timer; do
        [ -f "$gdir/$u" ] || { echo "$host: missing $gdir/$u — manifest job for $key?"; exit 1; }
    done
    tmp="$(mktemp -d)"
    cp "$SCRIPT" "$tmp/"
    cp "$gdir"/session-audit.service "$gdir"/session-audit.timer "$tmp/"
    write_remote_install "$tmp"

    if [ "$host" = "$(hostname -s)" ] || [ "$host" = localhost ]; then
        echo "== $host (local)"
        rm -rf "$HOME/.cache/session-audit-install"
        mkdir -p "$HOME/.cache/session-audit-install"
        tar cf - -C "$tmp" . | tar xf - -C "$HOME/.cache/session-audit-install"
        bash "$HOME/.cache/session-audit-install/remote-install.sh"
        [ "$RUN" = 1 ] && bash "$HOME/.cache/session-audit-install/run-once.sh"
    else
        [ -n "$VIA" ] && echo "== $host (via $VIA)" || echo "== $host"
        tar czf - -C "$tmp" . | on "rm -rf $STAGE && mkdir -p $STAGE && tar xzf - -C $STAGE"
        on "bash $STAGE/remote-install.sh"
        [ "$RUN" = 1 ] && on "bash $STAGE/run-once.sh"
    fi
    rm -rf "$tmp"
    echo "== $host done"
done
