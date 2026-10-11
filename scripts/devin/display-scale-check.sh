#!/usr/bin/env bash
# display-scale-check.sh — diagnose display/font/Chrome scaling on GNOME (Wayland or X11).
# Codeword procedure "scalecheck" — see .devin/skills/scalecheck/SKILL.md.
#
# Usage:
#   display-scale-check.sh                    diagnose only (read-mostly, safe)
#   display-scale-check.sh --fix              apply unambiguous fixes (mutter fractional
#                                             scaling, chrome wayland flag)
#   display-scale-check.sh --set-text-scale N set text-scaling-factor to N (e.g. 1.0)
#   display-scale-check.sh --enable CONN [--right-of CONN]   enable a connected monitor
#   display-scale-check.sh --scale CONN N     set logical scale (positions repack)
#   display-scale-check.sh --save NAME        save layout profile (by EDID, replug-safe)
#   display-scale-check.sh --restore NAME     restore saved layout profile
#   display-scale-check.sh --profiles         list saved profiles
set -u
CHABA="${CHABA_REPO:-$HOME/CascadeProjects/chaba}"
PROFDIR="$HOME/.config/scalecheck"
FIX=0; TEXT_SCALE=""; ENABLE_CONN=""; RIGHT_OF=""; SCALE_CONN=""; SCALE_VAL=""
SAVE=""; RESTORE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fix) FIX=1 ;;
    --set-text-scale) TEXT_SCALE="$2"; shift ;;
    --enable) ENABLE_CONN="$2"; shift ;;
    --right-of) RIGHT_OF="$2"; shift ;;
    --scale) SCALE_CONN="$2"; SCALE_VAL="$3"; shift 2 ;;
    --save) SAVE="$2"; shift ;;
    --restore) RESTORE="$2"; shift ;;
    --profiles) ls -1 "$PROFDIR" 2>/dev/null | sed 's/\.json$//;s/^/  /'; exit 0 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n=== %s ===\n' "$*"; }
flag() { printf '  [!] %s\n' "$*"; }
ok()   { printf '  [+] %s\n' "$*"; }
inf()  { printf '      %s\n' "$*"; }
# --enable CONN [--right-of CONN2] | --scale CONN N — handled by python helper below

FINDINGS=()
add() { FINDINGS+=("$1"); flag "$1"; }

hdr "Session"
say "  session_type=$XDG_SESSION_TYPE  desktop=$XDG_CURRENT_DESKTOP  host=$(hostname)"

hdr "GNOME scaling state"
SF=$(gsettings get org.gnome.desktop.interface scaling-factor 2>/dev/null)
TS=$(gsettings get org.gnome.desktop.interface text-scaling-factor 2>/dev/null)
EF=$(gsettings get org.gnome.mutter experimental-features 2>/dev/null)
inf "interface.scaling-factor     = $SF   (0 = auto; legacy integer path, normally unused)"
inf "interface.text-scaling-factor = $TS   (GNOME Tweaks > Fonts > Scaling Factor; default 1.0)"
inf "mutter.experimental-features = $EF"
case "$EF" in
  *scale-monitor-framebuffer*) ok "fractional scaling enabled" ;;
  *) add "mutter fractional scaling OFF — external monitors can't get per-monitor non-integer scale" ;;
esac
case "$EF" in
  *xwayland-native-scaling*) ok "xwayland-native-scaling enabled" ;;
  *) add "xwayland-native-scaling OFF — X11 apps (incl. non-Wayland Chrome) may render blurry/wrong-sized" ;;
esac
if python3 -c "import sys; sys.exit(0 if abs(float('$TS') - 1.0) > 0.01 else 1)" 2>/dev/null; then
  add "text-scaling-factor $TS != 1.0 — global font compensation; multiplies font size on EVERY monitor (GNOME Tweaks > Fonts > Scaling Factor)"
fi
if [ -n "$TEXT_SCALE" ]; then
  gsettings set org.gnome.desktop.interface text-scaling-factor "$TEXT_SCALE" \
    && ok "text-scaling-factor -> $TEXT_SCALE"
fi

hdr "Monitors (mutter DisplayConfig)"
RAW=$(timeout 8 gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
  --object-path /org/gnome/Mutter/DisplayConfig \
  --method org.gnome.Mutter.DisplayConfig.GetCurrentState 2>/dev/null)
MON_OUT=$(python3 - "$RAW" "$ENABLE_CONN" "$RIGHT_OF" "$SCALE_CONN" "$SCALE_VAL" "$SAVE" "$RESTORE" "$PROFDIR" "$TS" <<'PY'
import json, os, re, subprocess, sys, time
raw, ena, rof, sconn, sval, save, restore, profdir, ts = \
    (sys.argv[1:10] + ["", "", "", "", "", "", "", "", ""])[:9]
if not raw.strip():
    print("  (mutter DisplayConfig unavailable — X11 session or older GNOME; use xrandr instead)")
    sys.exit(0)
CONN = r"(?:eDP|DP|HDMI-A|USB-C|DVI|VGA)[-\w]*"
serial = (re.search(r"uint32 (\d+)", raw) or [None]).group(1)
logi = list(re.finditer(
    r"\((-?\d+), (-?\d+), ([\d.]+), (?:uint32 )?(\d+), (true|false), \[([^\]]*)\]", raw))
monsec = raw[:logi[0].start()] if logi else raw
heads = list(re.finditer(r"\('(%s)', '([^']*)', '([^']*)', '([^']*)'\), \[" % CONN, monsec))
MODE = r"\('(\d+x\d+@[\d.]+)', (\d+), (\d+), [\d.]+, ([\d.]+), \[([^\]]*)\], \{([^}]*)\}"
info = {}
for i, h in enumerate(heads):
    block = monsec[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(monsec)]
    info[h.group(1)] = dict(
        spec=h.groups()[1:],                    # (vendor, product, serial) — survives replug
        modes=[m.groups() for m in re.finditer(MODE, block)],
        cur=next((m.groups() for m in re.finditer(MODE, block)
                  if "'is-current': <true>" in m.group(6)), None),
        pref=next((m.groups() for m in re.finditer(MODE, block)
                   if "'is-preferred': <true>" in m.group(6)), None),
        name=(re.search(r"'display-name': <'([^']*)'>", block) or [None, "?"])[1],
        builtin="'is-builtin': <true>" in block)
for i, m in enumerate(logi):
    x, y, scale, tr, prim, conn = m.groups()
    for c in re.findall(r"'(%s)'" % CONN, conn):
        d = info.get(c, {}); cm = d.get("cur") or ("?",) * 7
        print(f"  logical[{i}] {c} \"{d.get('name','?')}\"  {cm[1]}x{cm[2]} {cm[0]}"
              f"  scale={scale}  pos={x},{y}  primary={prim}  builtin={d.get('builtin')}")
        print(f"      pref-scale={cm[3]}  offered=[{cm[4]}]")
active = {c for m in logi for c in re.findall(r"'(%s)'" % CONN, m.group(6))}
for c, d in info.items():
    if c not in active and not d.get("builtin"):
        print(f"!F!monitor {c} \"{d.get('name','?')}\" connected but DISABLED in GNOME "
              f"— fix: display-scale-check.sh --enable {c}")
    elif c not in active:
        print(f"  inactive    {c} \"{d.get('name','?')}\"  builtin panel suspended (lid closed?)")

def cur_state():
    out = []
    for m in logi:
        x, y, scale, tr, prim, conn = m.groups()
        conns = re.findall(r"'(%s)'" % CONN, conn)
        out.append([int(x), int(y), float(scale), prim == "true", conns])
    return out

def apply_gdctl(cfg, extra=None):
    if subprocess.run(["which", "gdctl"], capture_output=True).returncode:
        print("  [!] gdctl not found (needs GNOME >= 48) — apply manually via Settings > Displays")
        return
    args = ["gdctl", "set", "-P"]
    for x, y, sc, prim, conns in cfg:
        args += ["-L", "-M", conns[0], "--x", str(x), "--y", str(y),
                 "--scale", str(sc)]
        if prim:
            args.append("--primary")
    if extra:
        args += extra
    r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    ok = r.returncode == 0
    print(f"  {'[+]' if ok else '[!]'} gdctl set {' '.join(extra or [])} "
          f"{'applied' if ok else 'FAILED: ' + (r.stderr or r.stdout).strip()}")

if ena and ena in active:
    print(f"  [+] {ena} already active")
elif ena and ena in info:
    cfg = cur_state()
    anchor = next((g for g in cfg if rof and rof in g[4]),
                  max(cfg, key=lambda g: g[0])) if cfg else None
    anchor_conn = anchor[4][0] if anchor else None
    print(f"  enabling {ena} \"{info[ena]['name']}\""
          + (f" right of {anchor_conn}" if anchor_conn else " at 0,0"))
    apply_gdctl(cfg, extra=(["-L", "-M", ena, "--right-of", anchor_conn]
                            if anchor_conn else ["-L", "-M", ena, "--primary"]))
elif sconn and sconn in active:
    from itertools import groupby
    cfg = cur_state()
    for g in cfg:
        if sconn in g[4]:
            g[2] = float(sval)
    # repack each row so scaled monitors stay edge-adjacent
    cfg.sort(key=lambda g: (g[1], g[0]))
    for _, row in groupby(cfg, key=lambda g: g[1]):
        x = None
        for g in row:
            if x is not None:
                g[0] = x
            cm = info[g[4][0]].get("cur")
            x = g[0] + int((int(cm[1]) if cm else 0) / g[2])
    print(f"  scale {sconn} -> {sval}")
    apply_gdctl(cfg)
elif sconn:
    print(f"  [!] {sconn} not active — enable it first")

if save:
    prof = {"version": 1, "saved": time.strftime("%Y-%m-%d %H:%M"),
            "text_scale": ts, "logicals": []}
    for m in logi:
        x, y, sc, tr, prim, conn = m.groups()
        for c in re.findall(r"'(%s)'" % CONN, conn):
            d = info.get(c, {})
            prof["logicals"].append({
                "spec": list(d.get("spec", [])), "conn": c,
                "mode": (d.get("cur") or ("?",))[0],
                "x": int(x), "y": int(y), "scale": float(sc),
                "primary": prim == "true"})
    os.makedirs(profdir, exist_ok=True)
    path = os.path.join(profdir, save + ".json")
    json.dump(prof, open(path, "w"), indent=1)
    print(f"  [+] saved profile '{save}' ({len(prof['logicals'])} monitors, "
          f"text_scale={ts}) -> {path}")

if restore:
    path = os.path.join(profdir, restore + ".json")
    if not os.path.exists(path):
        print(f"  [!] no profile '{restore}' — profiles: "
              f"{', '.join(f[:-5] for f in os.listdir(profdir) if f.endswith('.json')) or 'none'}")
    else:
        prof = json.load(open(path))
        by_spec = {tuple(d["spec"]): c for c, d in info.items()}
        cfg, missing = [], []
        for lg in prof["logicals"]:
            c = by_spec.get(tuple(lg["spec"]))
            if c:
                cfg.append([lg["x"], lg["y"], lg["scale"], lg["primary"], [c]])
            else:
                missing.append(f"{lg['conn']} ({' '.join(lg['spec'][1:3])})")
        for m_ in missing:
            print(f"  [!] saved monitor absent, skipping: {m_}")
        if cfg:
            print(f"  restoring '{restore}': "
                  + ", ".join(f"{g[4][0]}@{g[2]} pos({g[0]},{g[1]})" for g in cfg))
            apply_gdctl(cfg)
            if prof.get("text_scale") and prof["text_scale"] != ts:
                subprocess.run(["gsettings", "set", "org.gnome.desktop.interface",
                                "text-scaling-factor", prof["text_scale"]])
                print(f"  [+] text-scaling-factor -> {prof['text_scale']}")
PY
)
echo "$MON_OUT" | grep -v '^!F!' | sed 's/^/ /'
while IFS= read -r f; do add "$f"; done < <(echo "$MON_OUT" | grep '^!F!' | sed 's/^!F! *//')

hdr "DRM connectors"
conn=""; disc=""
for c in /sys/class/drm/card?-*/status; do
  n=${c%/status}; n=${n##*/}; n=${n#card?-}
  s=$(cat "$c" 2>/dev/null)
  case "$s" in connected) conn="$conn $n" ;; *) disc="$disc $n" ;; esac
done
inf "connected:   ${conn:- none}"
inf "disconnected:${disc:- none}"

hdr "Recent kernel display errors"
journalctl -k -b --no-pager 2>/dev/null \
  | grep -iE "MST payload|link train|failed to retrieve link|edid.*(fail|error|corrupt)" \
  | tail -8 || true

hdr "Chrome"
if pgrep -f "/opt/google/chrome/chrome " >/dev/null || pgrep -x chrome >/dev/null; then
  OZ=$(tr '\0' ' ' < /proc/$(pgrep -f "/opt/google/chrome/chrome --type=gpu-process" | head -1)/cmdline 2>/dev/null | grep -o "ozone-platform=[a-z]*")
  inf "running: yes   gpu-process ${OZ:-ozone-platform=(default/x11)}"
  case "$OZ" in
    *wayland*) ok "Chrome on Wayland — per-monitor scale works" ;;
    *) add "Chrome NOT on Wayland ozone — on Wayland session it can't track per-monitor scale" ;;
  esac
else
  inf "running: no"
fi
FLAGS="$HOME/.config/chrome-flags.conf"
if [ -f "$FLAGS" ]; then inf "chrome-flags.conf: $(cat "$FLAGS")"; else inf "chrome-flags.conf: (absent)"; fi
grep -rhoE "force-device-scale-factor=[0-9.]+" /proc/*/cmdline 2>/dev/null | sort -u \
  | sed 's/^/  [!] /' | grep . && add "Chrome launched with --force-device-scale-factor override" || true

if [ "$FIX" = 1 ]; then
  hdr "Applying safe fixes"
  cur=$(gsettings get org.gnome.mutter experimental-features 2>/dev/null)
  want="scale-monitor-framebuffer|xwayland-native-scaling"
  missing=""
  for f in scale-monitor-framebuffer xwayland-native-scaling; do
    case "$cur" in *"$f"*) ;; *) missing="$missing '$f'," ;; esac
  done
  if [ -n "$missing" ]; then
    gsettings set org.gnome.mutter experimental-features "[$missing]" \
      && ok "mutter experimental-features enabled (takes effect on next login)"
  else ok "mutter features already set"; fi
  if ! grep -q ozone-platform "$FLAGS" 2>/dev/null; then
    printf -- "--ozone-platform=wayland\n" > "$FLAGS"
    ok "wrote $FLAGS (Chrome picks it up on next launch)"
  fi
fi

if [ ${#FINDINGS[@]} -gt 0 ]; then
  hdr "FINDINGS"
  printf '  - %s\n' "${FINDINGS[@]}"
else
  hdr "FINDINGS"; say "  none — state looks standard"
fi
