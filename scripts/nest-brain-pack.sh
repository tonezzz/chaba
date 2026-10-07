#!/usr/bin/env bash
# Pack a Nest entity into a portable brain bundle and push it to the brain
# store (default gdrive:nest/brains/<entity>/<version>/).
#
# Bundle layout per version dir:
#   manifest.yml   entity, version, epoch, per-blob {path,sha256,bytes,role},
#                  resume.{hydrate,verify}, bench.{score,metric,suite},
#                  parent_version, sensitivity  (schema: ssot.nest-brains.yml)
#   blobs.tar      every blob at its entity-relative path + blobs.sha256
#   SHA256SUMS     sha256 of manifest.yml + blobs.tar (sha256sum -c)
# Plus <entity>/latest — small mutable pointer file containing the version.
#
# The version dir gets Drive appProperties {entity,version,epoch,sensitivity}
# via scripts/nest-brain-drive.py (REST; rclone can't set appProperties).
# If the REST helper fails we warn and fall back to plain rclone paths —
# the round-trip still works, discovery just degrades to path walking.
#
# Epoch (fencing token, see policy_defaults.fencing): higher wins on respawn
# conflicts. Resolution order:
#   --epoch N > (<src>/.nest-brain-state epoch + 1)  # packing a respawned copy
#             > parent brain's epoch               # plain checkpoint
#             > 1
#
# Usage:
#   nest-brain-pack.sh <entity> [--repo DIR] [--src DIR] [--remote R]
#                      [--epoch N] [--keep N] [--notes TXT]
#                      [--no-verify] [--no-prune] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE="gdrive:nest/brains"
ENTITY=""; REPO=""; SRC=""; EPOCH=""; KEEP=""; NOTES=""
VERIFY=1; PRUNE=1; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --src) SRC="$2"; shift 2;;
    --remote) REMOTE="${2%/}"; shift 2;;
    --epoch) EPOCH="$2"; shift 2;;
    --keep) KEEP="$2"; shift 2;;
    --notes) NOTES="$2"; shift 2;;
    --no-verify) VERIFY=0; shift;;
    --no-prune) PRUNE=0; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    *) if [ -z "$ENTITY" ]; then ENTITY="$1"; shift; else echo "unknown arg: $1" >&2; exit 2; fi;;
  esac
done
[ -n "$ENTITY" ] || { echo "usage: nest-brain-pack.sh <entity> [options]" >&2; exit 2; }

REPO="${REPO:-$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR/..")}"
SSOT="$REPO/docs/ssot/infrastructure/ssot.nest-brains.yml"
[ -f "$SSOT" ] || { echo "registry not found: $SSOT" >&2; exit 1; }

STAGE="$(mktemp -d /tmp/nest-brain-pack.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

# --- read entity def from the registry -------------------------------------
python3 - "$SSOT" "$ENTITY" "$STAGE" <<'PY'
import shlex, sys, yaml
ssot, entity, stage = sys.argv[1], sys.argv[2], sys.argv[3]
reg = yaml.safe_load(open(ssot))
ent = next((e for e in reg.get("entities", []) if e.get("entity") == entity), None)
if not ent:
    sys.exit(f"entity '{entity}' not in {ssot}")
bench = ent.get("bench") or {}
env = {
    "ENT_PATH": ent.get("path", ""),
    "ENT_SENS": ent.get("sensitivity", "internal"),
    "ENT_BENCH_METRIC": bench.get("metric", ""),
    "ENT_BENCH_SUITE": bench.get("suite", ""),
    "ENT_BENCH_SCORE": str(bench.get("score", "")),
    "ENT_TIER": ent.get("tier", ""),
    "KEEP_DEFAULT": str((reg.get("policy_defaults") or {}).get("retention_versions", 5)),
}
with open(f"{stage}/env.sh", "w") as f:
    for k, v in env.items():
        f.write(f"{k}={shlex.quote(str(v))}\n")
with open(f"{stage}/blobs-req.tsv", "w") as f:
    for b in ent.get("blobs", []):
        f.write(f"{b['path']}\t{b.get('role', 'config')}\n")
PY
# shellcheck disable=SC1090
source "$STAGE/env.sh"
KEEP="${KEEP:-$KEEP_DEFAULT}"

SRC="${SRC:-$REPO/$ENT_PATH}"
[ -d "$SRC" ] || { echo "entity src not found: $SRC" >&2; exit 1; }

# --- stage blobs ------------------------------------------------------------
BROOT="$STAGE/blobs"; mkdir -p "$BROOT"
: > "$STAGE/blobs-meta.tsv"   # manifest path \t role \t aggregate-sha \t bytes
: > "$BROOT/blobs.sha256"     # per-file sha for post-extract verify

add_file() {  # $1 abs path, $2 rel path -> echoes "<sha> <bytes>"
  local rel="$2"
  mkdir -p "$BROOT/$(dirname "$rel")"
  cp -a "$1" "$BROOT/$rel"
  local sha bytes
  sha=$(sha256sum "$BROOT/$rel" | cut -d' ' -f1)
  bytes=$(stat -c%s "$BROOT/$rel")
  echo "$sha  $rel" >> "$BROOT/blobs.sha256"
  echo "$sha $bytes"
}

while IFS=$'\t' read -r bpath role; do
  [ -n "$bpath" ] || continue
  # 'a+b' notation = several explicit paths; trailing '/' = whole dir
  IFS='+' read -ra parts <<< "$bpath"
  agg_lines=""
  total=0
  for part in "${parts[@]}"; do
    part="${part%/}"
    ap="$SRC/$part"
    if [ -d "$ap" ]; then
      while IFS= read -r f; do
        rel="${f#$SRC/}"
        read -r sha bytes <<< "$(add_file "$f" "$rel")"
        agg_lines+="$rel $sha"$'\n'
        total=$((total + bytes))
      done < <(find "$ap" -type f | sort)
    elif [ -f "$ap" ]; then
      read -r sha bytes <<< "$(add_file "$ap" "$part")"
      agg_lines+="$part $sha"$'\n'
      total=$((total + bytes))
    else
      echo "WARNING: blob listed in registry missing from src: $part" >&2
    fi
  done
  if [ -n "$agg_lines" ]; then
    agg_sha=$(printf '%s' "$agg_lines" | sha256sum | cut -d' ' -f1)
    printf '%s\t%s\t%s\t%s\n' "$bpath" "$role" "$agg_sha" "$total" >> "$STAGE/blobs-meta.tsv"
  fi
done < "$STAGE/blobs-req.tsv"

# respawn lineage marker rides along as a state blob
if [ -f "$SRC/.nest-brain-state" ]; then
  cp -a "$SRC/.nest-brain-state" "$BROOT/.nest-brain-state"
  sha=$(sha256sum "$BROOT/.nest-brain-state" | cut -d' ' -f1)
  echo "$sha  .nest-brain-state" >> "$BROOT/blobs.sha256"
  printf '.nest-brain-state\tstate\t%s\t%s\n' "$sha" "$(stat -c%s "$BROOT/.nest-brain-state")" >> "$STAGE/blobs-meta.tsv"
fi

[ -s "$STAGE/blobs-meta.tsv" ] || { echo "no blobs staged — nothing to pack" >&2; exit 1; }

# --- tar + manifest ---------------------------------------------------------
mkdir -p "$STAGE/bundle"
tar -cf "$STAGE/bundle/blobs.tar" -C "$BROOT" .
TAR_SHA=$(sha256sum "$STAGE/bundle/blobs.tar" | cut -d' ' -f1)
TAR_BYTES=$(stat -c%s "$STAGE/bundle/blobs.tar")

# epoch + parent
PARENT=$(rclone cat "$REMOTE/$ENTITY/latest" 2>/dev/null || true)
PARENT_EPOCH=0
if [ -n "$PARENT" ]; then
  PARENT_EPOCH=$(rclone cat "$REMOTE/$ENTITY/$PARENT/manifest.yml" 2>/dev/null | sed -n 's/^epoch:[[:space:]]*//p' | head -1)
  PARENT_EPOCH="${PARENT_EPOCH:-0}"
fi
STATE_EPOCH=0
if [ -f "$SRC/.nest-brain-state" ]; then
  STATE_EPOCH=$(sed -n 's/^epoch:[[:space:]]*//p' "$SRC/.nest-brain-state" | head -1)
  STATE_EPOCH=$(( ${STATE_EPOCH:-0} + 1 ))   # packing a respawned copy -> next generation
fi
EPOCH="${EPOCH:-$(( STATE_EPOCH > PARENT_EPOCH ? STATE_EPOCH : (PARENT_EPOCH > 0 ? PARENT_EPOCH : 1) ))}"

GSHA=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "${TAR_SHA:0:7}")
VERSION="$(date -u +%Y%m%d-%H%M)-$GSHA"
CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# continuity check: prefer the entity's own eval when it ships one
VERIFY_CMD="see entity bench suite"
if [ -f "$SRC/eval.py" ] && [ -n "$ENT_BENCH_SCORE" ]; then
  VERIFY_CMD="python3 eval.py --expect $ENT_BENCH_SCORE"
fi

MANIFEST_ENTITY="$ENTITY" MANIFEST_VERSION="$VERSION" \
MANIFEST_AT="$CREATED_AT" MANIFEST_HOST="$(hostname)" \
MANIFEST_PARENT="$PARENT" MANIFEST_EPOCH="$EPOCH" \
MANIFEST_SENS="$ENT_SENS" MANIFEST_NOTES="$NOTES" \
MANIFEST_TAR_SHA="$TAR_SHA" MANIFEST_TAR_BYTES="$TAR_BYTES" \
MANIFEST_BENCH_SCORE="$ENT_BENCH_SCORE" MANIFEST_BENCH_METRIC="$ENT_BENCH_METRIC" \
MANIFEST_BENCH_SUITE="$ENT_BENCH_SUITE" MANIFEST_VERIFY="$VERIFY_CMD" \
python3 - "$STAGE/blobs-meta.tsv" "$STAGE/bundle/manifest.yml" <<'PY'
import os, sys, yaml
tsv, out = sys.argv[1], sys.argv[2]
e = os.environ
blobs = []
for line in open(tsv):
    path, role, sha, b = line.rstrip("\n").split("\t")
    blobs.append({"path": path, "role": role, "sha256": sha, "bytes": int(b)})
m = {
    "entity": e["MANIFEST_ENTITY"],
    "version": e["MANIFEST_VERSION"],
    "epoch": int(e["MANIFEST_EPOCH"]),
    "sensitivity": e["MANIFEST_SENS"],
    "created": {"at": e["MANIFEST_AT"], "on_host": e["MANIFEST_HOST"]},
    "archive": {"file": "blobs.tar", "sha256": e["MANIFEST_TAR_SHA"], "bytes": int(e["MANIFEST_TAR_BYTES"])},
    "blobs": blobs,
    "resume": {"hydrate": "nest-brain-restore.sh " + e["MANIFEST_ENTITY"], "verify": e["MANIFEST_VERIFY"]},
    "bench": {"score": float(e["MANIFEST_BENCH_SCORE"]) if e["MANIFEST_BENCH_SCORE"] else None,
              "metric": e["MANIFEST_BENCH_METRIC"], "suite": e["MANIFEST_BENCH_SUITE"]},
}
if e["MANIFEST_PARENT"]:
    m["parent_version"] = e["MANIFEST_PARENT"]
if e["MANIFEST_NOTES"]:
    m["notes"] = e["MANIFEST_NOTES"]
with open(out, "w") as f:
    yaml.safe_dump(m, f, sort_keys=False, default_flow_style=False)
PY

(cd "$STAGE/bundle" && sha256sum manifest.yml blobs.tar > SHA256SUMS)

echo "== nest-brain-pack =="
echo "entity:   $ENTITY   epoch: $EPOCH   sensitivity: $ENT_SENS"
echo "version:  $VERSION  parent: ${PARENT:-<none>}"
echo "blobs:    $(wc -l < "$STAGE/blobs-meta.tsv") entries, tar $TAR_BYTES bytes ($TAR_SHA)"

if [ "$DRY" = 1 ]; then
  echo "-- dry-run: bundle staged at $STAGE/bundle (kept)"; trap - EXIT
  echo "-- manifest:"; cat "$STAGE/bundle/manifest.yml"; exit 0
fi

# --- upload -----------------------------------------------------------------
DEST="$REMOTE/$ENTITY/$VERSION"
VERDIR_ID=$(python3 "$SCRIPT_DIR/nest-brain-drive.py" ensure "$ENTITY" "$VERSION" \
    --set "entity=$ENTITY,version=$VERSION,epoch=$EPOCH,sensitivity=$ENT_SENS" 2>/dev/null) || VERDIR_ID=""
if [ -n "$VERDIR_ID" ]; then
  rclone copy "$STAGE/bundle" "gdrive:" --drive-root-folder-id "$VERDIR_ID" -q
else
  echo "WARNING: appProperties not set (REST helper unavailable) — plain path upload" >&2
  rclone copy "$STAGE/bundle" "$DEST" -q
fi
printf '%s\n' "$VERSION" > "$STAGE/latest"
rclone copyto "$STAGE/latest" "$REMOTE/$ENTITY/latest" -q

# --- verify: re-download + sha256sum -c -------------------------------------
if [ "$VERIFY" = 1 ]; then
  VDIR="$STAGE/rt"; mkdir -p "$VDIR"
  rclone copy "$DEST" "$VDIR" -q
  (cd "$VDIR" && sha256sum -c SHA256SUMS >/dev/null)
  echo "verify:   OK — re-downloaded bundle matches SHA256SUMS"
fi

# --- retention ---------------------------------------------------------------
if [ "$PRUNE" = 1 ]; then
  mapfile -t vers < <(rclone lsf --dirs-only "$REMOTE/$ENTITY/" 2>/dev/null | sed 's:/$::' | sort -r)
  n=${#vers[@]}
  if [ "$n" -gt "$KEEP" ]; then
    for old in "${vers[@]:$KEEP}"; do
      echo "prune:    $REMOTE/$ENTITY/$old (retention $KEEP)"
      rclone purge "$REMOTE/$ENTITY/$old" -q
    done
  fi
fi

mkdir -p "$HOME/.local/share/nest-brains"
cat > "$HOME/.local/share/nest-brains/packed-$ENTITY" <<EOF
version: $VERSION
epoch: $EPOCH
packed_at: $CREATED_AT
on_host: $(hostname)
EOF

echo "done:     $DEST  (latest -> $VERSION)"
