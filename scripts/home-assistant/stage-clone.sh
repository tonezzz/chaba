#!/usr/bin/env bash
# Clone a prod HA config into a staging twin and apply the actuation-guard
# overlay (card ha-staging-actuation-guard).
#
#   stage-clone.sh --source tony-ha --target tony-dev
#
# The clone is byte-identical except where the overlay neutralizes write
# paths — the strip/stub list lives in
#   docs/ssot/infrastructure/ssot.home-assistant.staging-overlay.yml
# and is applied by scripts/home-assistant/staging-overlay.py.
#
# Usage:
#   --source <id|dir>     instance id (tony-ha|ada-ha|michael-dev) or a path
#   --target <name>       staging name; config lands in ~/.config/<name>
#   --source-dir DIR      explicit source config dir (overrides --source id)
#   --target-dir DIR      explicit target config dir (overrides ~/.config/<n>)
#   --instance ID         overlay instance override key (default: --target)
#   --overlay FILE        alternate overlay policy file
#   --name NAME           set homeassistant.name (e.g. "Tony DEV")
#   --internal-url URL    set homeassistant.internal_url
#   --external-url URL    set homeassistant.external_url
#   --package FILE        copy an extra yaml package into packages/ (repeatable;
#                       use for mirror/mock packages like z_staging_mirrors.yaml)
#   --with-db             also copy home-assistant_v2.db* (skipped by default)
#   --with-backups        also copy backups/ (skipped by default)
#   --force               allow refreshing an existing staging target
#   --skip-verify         don't run the overlay's verify pass at the end
#   --dry-run             print the plan + audit only; writes nothing
#
# Safety: the script refuses to target any known prod config dir, refuses to
# clobber an existing HA-ish directory that lacks the .staging-guard marker,
# and never touches the source read-write.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." &>/dev/null && pwd)
OVERLAY_DEFAULT="$REPO_ROOT/docs/ssot/infrastructure/ssot.home-assistant.staging-overlay.yml"
OVERLAY_PY="$SCRIPT_DIR/staging-overlay.py"

log() { echo "[stage-clone] $*"; }
die() { echo "[stage-clone] ERROR: $*" >&2; exit 1; }

# ---- known prod config dirs — never a valid clone target ------------------
PROD_DIRS=(
  "$HOME/.config/home-assistant"   # tony-ha
  "$HOME/.config/ada-ha"           # ada-ha
  "$HOME/.config/michael-dev"      # michael-dev (real lane, not a staging toy)
)

resolve_source() {
  case "$1" in
    tony-ha)     echo "$HOME/.config/home-assistant" ;;
    ada-ha)      echo "$HOME/.config/ada-ha" ;;
    michael-dev) echo "$HOME/.config/michael-dev" ;;
    michael-ha)  die "michael-ha is remote — clone from a mounted path with --source-dir" ;;
    *)           echo "$1" ;;
  esac
}

SOURCE=""; TARGET=""; SOURCE_DIR=""; TARGET_DIR=""
OVERLAY="$OVERLAY_DEFAULT"; INSTANCE=""
SET_KEYS=(); PACKAGES=()
WITH_DB=0; WITH_BACKUPS=0; FORCE=0; SKIP_VERIFY=0; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --source)       SOURCE="$2"; shift 2 ;;
    --target)       TARGET="$2"; shift 2 ;;
    --source-dir)   SOURCE_DIR="$2"; shift 2 ;;
    --target-dir)   TARGET_DIR="$2"; shift 2 ;;
    --overlay)      OVERLAY="$2"; shift 2 ;;
    --instance)     INSTANCE="$2"; shift 2 ;;
    --name)         SET_KEYS+=("name=$2"); shift 2 ;;
    --internal-url) SET_KEYS+=("internal_url=$2"); shift 2 ;;
    --external-url) SET_KEYS+=("external_url=$2"); shift 2 ;;
    --package)      PACKAGES+=("$2"); shift 2 ;;
    --with-db)      WITH_DB=1; shift ;;
    --with-backups) WITH_BACKUPS=1; shift ;;
    --force)        FORCE=1; shift ;;
    --skip-verify)  SKIP_VERIFY=1; shift ;;
    --dry-run)      DRY=1; shift ;;
    -h|--help)      sed -n '2,40p' "$0"; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[ -n "$SOURCE" ] || [ -n "$SOURCE_DIR" ] || die "need --source <id|dir>"
[ -n "$TARGET" ] || [ -n "$TARGET_DIR" ] || die "need --target <name>"
[ -f "$OVERLAY" ] || die "overlay not found: $OVERLAY"
[ -f "$OVERLAY_PY" ] || die "overlay engine not found: $OVERLAY_PY"

[ -n "$SOURCE_DIR" ] || SOURCE_DIR=$(resolve_source "$SOURCE")
SOURCE_DIR=$(cd "$SOURCE_DIR" 2>/dev/null && pwd) || die "source dir missing: $SOURCE_DIR"
[ -n "$TARGET_DIR" ] || TARGET_DIR="$HOME/.config/$TARGET"
TARGET_DIR=$(readlink -m "${TARGET_DIR%/}")  # canonicalize w/o creating
[ -n "$INSTANCE" ] || INSTANCE="$TARGET"

# ---- guards ----------------------------------------------------------------
[ "$SOURCE_DIR" != "$TARGET_DIR" ] || die "source == target ($SOURCE_DIR)"
case "$TARGET_DIR" in "$SOURCE_DIR"/*) die "target is inside the source" ;; esac
for p in "${PROD_DIRS[@]}"; do
  [ "$TARGET_DIR" != "$p" ] || die "refusing to treat prod config as target: $p"
done
[ -f "$SOURCE_DIR/configuration.yaml" ] || [ -d "$SOURCE_DIR/.storage" ] \
  || die "source does not look like an HA config: $SOURCE_DIR"

if [ -d "$TARGET_DIR" ] && [ "$(ls -A "$TARGET_DIR" 2>/dev/null | head -1)" ]; then
  if [ ! -d "$TARGET_DIR/.staging-guard" ]; then
    die "target exists and is not a staging clone (no .staging-guard marker): $TARGET_DIR — refusing unconditionally"
  fi
  [ "$FORCE" -eq 1 ] || die "staging target exists; re-clone with --force"
fi

EXCLUDES=(
  --exclude 'home-assistant.log*'
  --exclude 'tts/'
  --exclude 'deps/'
  --exclude '__pycache__/'
  --exclude '.venv/'
)
[ "$WITH_DB" -eq 1 ]      || EXCLUDES+=(--exclude 'home-assistant_v2.db*')
[ "$WITH_BACKUPS" -eq 1 ] || EXCLUDES+=(--exclude 'backups/')

log "source : $SOURCE_DIR"
log "target : $TARGET_DIR (instance=$INSTANCE)"
log "overlay: $OVERLAY"

if [ "$DRY" -eq 1 ]; then
  log "dry-run: would rsync -a ${EXCLUDES[*]} $SOURCE_DIR/ -> $TARGET_DIR/"
  TMPD=$(mktemp -d)
  trap 'rm -rf "$TMPD"' EXIT
  rsync -a "${EXCLUDES[@]}" "$SOURCE_DIR/" "$TMPD/" 2>/dev/null \
    || die "dry-run copy failed"
  python3 "$OVERLAY_PY" audit --config "$TMPD" --overlay "$OVERLAY" \
    --instance "$INSTANCE" "${SET_KEYS[@]/#/--set-key }" 2>/dev/null || true
  log "dry-run complete (scratch copy at $TMPD discarded)"
  exit 0
fi

# ---- copy ------------------------------------------------------------------
DELETE=""
if [ -d "$TARGET_DIR/.staging-guard" ] && [ "$FORCE" -eq 1 ]; then
  DELETE="--delete"
  log "refreshing existing staging clone (rsync --delete)"
fi
mkdir -p "$TARGET_DIR"
rsync -a $DELETE "${EXCLUDES[@]}" "$SOURCE_DIR/" "$TARGET_DIR/" \
  || die "rsync failed"
log "copied $(du -sh "$TARGET_DIR" | cut -f1) -> $TARGET_DIR"

# ---- optional mirror/mock packages ------------------------------------------
for pkg in "${PACKAGES[@]}"; do
  [ -f "$pkg" ] || die "--package file missing: $pkg"
  mkdir -p "$TARGET_DIR/packages"
  cp -a "$pkg" "$TARGET_DIR/packages/"
  log "installed package $(basename "$pkg")"
done

# ---- apply overlay -----------------------------------------------------------
SETKEY_ARGS=()
for kv in "${SET_KEYS[@]:-}"; do
  [ -n "$kv" ] && SETKEY_ARGS+=(--set-key "$kv")
done
python3 "$OVERLAY_PY" apply --config "$TARGET_DIR" --overlay "$OVERLAY" \
  --instance "$INSTANCE" "${SETKEY_ARGS[@]}" \
  || die "overlay apply failed"

# ---- clone marker -------------------------------------------------------------
cat > "$TARGET_DIR/.staging-guard/clone.json" <<EOF
{
  "source": "$SOURCE_DIR",
  "target": "$TARGET_DIR",
  "instance": "$INSTANCE",
  "overlay": "$OVERLAY",
  "cloned_at": "$(date -Is)",
  "cloned_by": "stage-clone.sh",
  "note": "staging twin — write paths neutralized per ha-staging-actuation-guard"
}
EOF

# ---- verify ------------------------------------------------------------------
if [ "$SKIP_VERIFY" -eq 0 ]; then
  log "verify pass:"
  if ! python3 "$OVERLAY_PY" verify --config "$TARGET_DIR" --overlay "$OVERLAY" \
       --instance "$INSTANCE"; then
    die "verify found residual write paths — inspect output above"
  fi
fi

cat <<EOF

[stage-clone] done. Next steps (card ha-dev-instances):
  - quadlet: Volume=$TARGET_DIR:/config:Z , podman network + publish
    127.0.0.1:<port>:8123 (never host-network for staging)
  - boot, then watch 24h of logbook + prod state for duplicate actions
  - full policy + residual risks: $OVERLAY
EOF
