#!/usr/bin/env bash
# install-log-shipper.sh — install the per-host local log-shipper timer.
#
# Bundles log-shipper.py + the rendered systemd user units for a fleet
# host, pushes them over ssh, and enables the timer. The shipper runs
# self-contained from ~/.local/share/log-shipper/ — deliberately NOT the
# repo checkout, so a stale/divergent checkout never breaks shipping.
# Adding a new host = add the job to ssot.jobs.yml, re-render, run this.
#
# Usage:
#   install-log-shipper.sh tony-dell mn01 idc01     # install on hosts
#   install-log-shipper.sh --all                    # all manifest hosts
#   install-log-shipper.sh idc03 --via tony-omen    # via a jump host
#                                                   # (ssh runs ON the
#                                                   # jump host, so its
#                                                   # keys are used —
#                                                   # idc03's id_idc03
#                                                   # lives on omen only)
#   install-log-shipper.sh tony-dell --no-run       # install, don't run
#
# michael-ha is NOT a target (no python3/systemd on the HAOS ssh addon) —
# it is covered by the log-shipper-mha pull timer on tony-dell.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SHIPPER="$HERE/log-shipper.py"
GEN="$REPO/systemd/generated"
STAGE='~/.cache/log-shipper-install'   # remote staging dir (recreated)

VIA=""
RUN=1
HOSTS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --all) HOSTS=(tony-dell tony-omen idc01 idc02 idc03 mn01) ;;
        --via) VIA="$2"; shift ;;
        --no-run) RUN=0 ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        *) HOSTS+=("$1") ;;
    esac
    shift
done
[ ${#HOSTS[@]} -gt 0 ] || { echo "usage: $0 <host>... [--via JUMP] [--no-run]"; exit 2; }

# Re-render generated units from the manifest (idempotent).
python3 "$REPO/scripts/render-jobs.py" >/dev/null

ssot_key() { echo "$1" | tr '-' '_'; }

# Run a remote command on $host, through $VIA when set. stdin is
# forwarded through both hops, so `tar` bundles stream fine.
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
S="$HOME/.cache/log-shipper-install"
D="$HOME/.local/share/log-shipper"
U="$HOME/.config/systemd/user"
mkdir -p "$D" "$U"
install -m 0644 "$S/log-shipper.py" "$D/log-shipper.py"
install -m 0644 "$S/log-shipper.service" "$S/log-shipper.timer" "$U/"
TIMERS="log-shipper.timer"
if [ -f "$S/log-shipper-mha.timer" ]; then
    install -m 0644 "$S/log-shipper-mha.service" "$S/log-shipper-mha.timer" "$U/"
    TIMERS="$TIMERS log-shipper-mha.timer"
fi
systemctl --user daemon-reload
# shellcheck disable=SC2086
systemctl --user enable --now $TIMERS
echo "installed + armed: $TIMERS"
EOS
    cat > "$1/run-once.sh" <<'EOS'
#!/usr/bin/env bash
/usr/bin/python3 "$HOME/.local/share/log-shipper/log-shipper.py" --self 2>&1 | tail -3
if [ -f "$HOME/.config/systemd/user/log-shipper-mha.timer" ]; then
    /usr/bin/python3 "$HOME/.local/share/log-shipper/log-shipper.py" \
        --hosts michael-ha 2>&1 | tail -3
fi
EOS
}

for host in "${HOSTS[@]}"; do
    key="$(ssot_key "$host")"
    gdir="$GEN/$key"
    for u in log-shipper.service log-shipper.timer; do
        [ -f "$gdir/$u" ] || { echo "$host: missing $gdir/$u — manifest job for $key?"; exit 1; }
    done
    tmp="$(mktemp -d)"
    cp "$SHIPPER" "$tmp/"
    cp "$gdir"/log-shipper.service "$gdir"/log-shipper.timer "$tmp/"
    # pull-lane units only exist where the manifest renders them (dell)
    if [ -f "$gdir/log-shipper-mha.timer" ]; then
        cp "$gdir"/log-shipper-mha.service "$gdir"/log-shipper-mha.timer "$tmp/"
    fi
    write_remote_install "$tmp"

    if [ "$host" = "$(hostname -s)" ] || [ "$host" = localhost ]; then
        echo "== $host (local)"
        rm -rf "$HOME/.cache/log-shipper-install"
        mkdir -p "$HOME/.cache/log-shipper-install"
        tar cf - -C "$tmp" . | tar xf - -C "$HOME/.cache/log-shipper-install"
        bash "$HOME/.cache/log-shipper-install/remote-install.sh"
        [ "$RUN" = 1 ] && bash "$HOME/.cache/log-shipper-install/run-once.sh"
    else
        [ -n "$VIA" ] && echo "== $host (via $VIA)" || echo "== $host"
        tar czf - -C "$tmp" . | on "rm -rf $STAGE && mkdir -p $STAGE && tar xzf - -C $STAGE"
        on "bash $STAGE/remote-install.sh"
        [ "$RUN" = 1 ] && on "bash $STAGE/run-once.sh"
    fi
    rm -rf "$tmp"
    echo "== $host done"
done
