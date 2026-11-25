#!/usr/bin/env bash
# macbook-day-awake — hold a logind sleep inhibitor while tony-macbook should
# stay awake as a daytime dispatch runner (card tony-macbook-daytime-runner,
# OPS-0059). Complements lid-blank-watch: that unit blanks the panel on
# lid-close; this one decides when the whole host may sleep.
#
# Holds `systemd-inhibit --what=sleep:idle --mode=block` while ALL of:
#   - local time is inside DAY_START..DAY_END (default 07:00-23:00, env)
#   - on AC power (any /sys/class/power_supply/*/type=Mains with online=1),
#     OR (lid open AND battery >= DAY_AWAKE_MIN_BATTERY_PCT, default 30)
#
# Everything else keeps today's suspend behaviour:
#   - night -> inhibitor released, normal suspend paths apply
#   - on battery with lid closed -> suspend-then-hibernate stays reachable
#     (bag safety; also the only path that reaches the broken hibernate
#     resume — see card archive macbook-suspend-dgpu-wedge)
#   - battery below the floor -> inhibitor released so idle/lid suspend can
#     drain the runner slot instead of killing the pack
#
# Mechanism: the inhibitor is held by a child
#   systemd-inhibit ... bash -c 'while kill -0 $daemon && [ -e $flag ]; sleep 5'
# so release is event-driven (flag removal or daemon death, <=5s) and no
# stray `sleep infinity` processes accumulate across state flips.
#
# Env knobs (set in the unit's Environment=):
#   DAY_START / DAY_END               HH:MM local, overnight ranges allowed
#   DAY_AWAKE_MIN_BATTERY_PCT         battery floor for the unplugged path
#   DAY_AWAKE_POLL_SECONDS            re-eval cadence (default 60)
#
# Escape hatch: `systemctl --user stop macbook-day-awake.service` releases
# the inhibitor immediately (cgroup kill); disable to make it permanent.

DAY_START="${DAY_START:-07:00}"
DAY_END="${DAY_END:-23:00}"
MIN_BATTERY_PCT="${DAY_AWAKE_MIN_BATTERY_PCT:-30}"
POLL="${DAY_AWAKE_POLL_SECONDS:-60}"
[[ "$POLL" =~ ^[0-9]+$ ]] || POLL=60
INHIBIT_WHY="tony-macbook daytime runner (card tony-macbook-daytime-runner)"
HOLD_FLAG="${XDG_RUNTIME_DIR:-/tmp}/macbook-day-awake-$(id -u).hold"
BATTERY_CAPACITY="${BATTERY_CAPACITY:-/sys/class/power_supply/BAT0/capacity}"
LID_STATE="${LID_STATE:-/proc/acpi/button/lid/LID0/state}"
PS_BASE="${POWER_SUPPLY_BASE:-/sys/class/power_supply}"

child=""

ac_online() {
  local p
  for p in "$PS_BASE"/*/online; do
    [ -f "$p" ] || continue
    [ "$(cat "${p%/online}/type" 2>/dev/null)" = "Mains" ] || continue
    [ "$(cat "$p" 2>/dev/null)" = "1" ] && return 0
  done
  return 1
}

lid_open() {
  [ "$(grep -oE 'open|closed' "$LID_STATE" 2>/dev/null)" = "open" ]
}

battery_pct() {
  [ -f "$BATTERY_CAPACITY" ] && cat "$BATTERY_CAPACITY" 2>/dev/null || echo 0
}

in_daytime() {
  local now hm
  now=$(date +%H:%M)
  if [[ "$DAY_START" < "$DAY_END" ]]; then
    [[ "$now" > "$DAY_START" && "$now" < "$DAY_END" ]]
  else
    [[ "$now" > "$DAY_START" || "$now" < "$DAY_END" ]]
  fi
}

want_awake() {
  in_daytime || return 1
  ac_online && return 0
  lid_open || return 1
  [ "$(battery_pct)" -ge "$MIN_BATTERY_PCT" ] 2>/dev/null
}

ensure_child() {
  [ -n "$child" ] && kill -0 "$child" 2>/dev/null && return 0
  systemd-inhibit --what=sleep:idle --why="$INHIBIT_WHY" --mode=block \
    bash -c 'while kill -0 "$1" 2>/dev/null && [ -e "$2" ]; do sleep 5; done' \
    _ "$$" "$HOLD_FLAG" &
  child=$!
}

# Clear any stale hold from a previous run before evaluating.
rm -f "$HOLD_FLAG"

while :; do
  if want_awake; then
    : > "$HOLD_FLAG"
    ensure_child
  else
    rm -f "$HOLD_FLAG"
  fi
  sleep "$POLL"
done
