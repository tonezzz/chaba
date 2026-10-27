# ada-nest RELEASE LIB — shared helpers for the pinned-release flow.
# Canonical source: scripts/colab/release_lib.py (chaba repo); deployed
# copy lives at ada-nest/releases/<id>/queue/release_lib.py.
#
# Drive layout (OPS release pinning):
#   ada-nest/releases/<release_id>/     immutable bundle — code ONLY
#     release.json                    {schema, release_id, commit,
#                                      generated_at, files{path:sha},
#                                      packs{name:{sha256,files}},
#                                      gap_packs{name:{sha256,files}}}
#     queue/   runner.py JOBS.py runtime_registry.py preflight-cell.py
#            queue-launcher-cell.py queue-runner-cell.py gap-runner.py
#            gap-launcher-cell.py release_lib.py img_gen.py
#            build-job-console.py ada-nest-job-console.ipynb
#     packs/<name>/    pack.yml + inputs/ + helpers (no state)
#     gap-packs/<name>/  pack.json (+ helpers)
#   ada-nest/queue/ACTIVE_RELEASE.json  {schema, release_id,
#     release_sha256 (= sha256 of release.json), commit, activated_at,
#     previous}
#   ada-nest/queue/ada-nest-job-console.ipynb  deployed copy — byte-equal
#     to releases/<id>/queue/ada-nest-job-console.ipynb
#   ada-nest/packs/<name>/     WORKSPACE — claim/ done failed out/ logs
#   ada-nest/gap-packs/<name>/ WORKSPACE — claim/ done failed out/
#
# Trust chain: ACTIVE_RELEASE.json -> release_sha256 -> release.json ->
# files{} -> every byte that runs. Cells hash-check release_lib.py alone
# first (the importer can't import unverified code), then this module
# verifies the rest. Rollback = repoint ACTIVE_RELEASE.json at a
# previously verified release.
#
# Markers are hash-aware: queue/done|env-done markers carry
#   rel=<release_id> jh=<job sha12>; pack done/failed carry ph=/gh=.
# A marker is honored only when its recorded hash equals the hash of the
# code about to run — stale markers can never skip new code. Markers
# without a hash (pre-pinning) are honored only when the workspace still
# holds byte-identical code (ws_pack_matches rescue) and are upgraded in
# place; everything else re-runs.
import hashlib
import json
import os
import re
import shutil
import time

RELEASE_SCHEMA = 1
POINTER_NAME = 'ACTIVE_RELEASE.json'
MANIFEST_NAME = 'release.json'
SRC_TRACKER = '.release-src.json'

# job dict fields that define the code a marker stamps — needs/timeout/
# artifacts/scope all change behavior, so all are hashed.
JOB_HASH_FIELDS = ('name', 'scope', 'prep', 'run', 'run_sh',
                   'artifacts', 'timeout_s', 'needs')


def sha256_file(path, _chunk=1 << 20):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            while True:
                b = f.read(_chunk)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def sha256_bytes(data):
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- pointer + manifest

def load_pointer(queue_dir):
    """queue/ACTIVE_RELEASE.json -> dict, or None when absent/unreadable."""
    try:
        d = json.loads(open(os.path.join(queue_dir, POINTER_NAME)).read())
        return d if isinstance(d, dict) and d.get('release_id') else None
    except Exception:
        return None


def release_dir(root, release_id):
    return os.path.join(root, 'releases', release_id)


def load_manifest(rel_dir):
    try:
        d = json.loads(open(os.path.join(rel_dir, MANIFEST_NAME)).read())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def manifest_sha(rel_dir):
    return sha256_file(os.path.join(rel_dir, MANIFEST_NAME))


def release_files(manifest):
    """{relpath: sha256} exactly as declared — the complete bundle set."""
    return dict((manifest or {}).get('files') or {})


def verify_release(root, release_id, manifest=None):
    """Full bundle check -> problems list ([] = verified). Every declared
    file must exist with a matching sha256, and the release dir must not
    hold files the manifest does not declare (release.json itself is the
    only allowed extra — its hash is anchored by the pointer, not by
    itself)."""
    problems = []
    rel_dir = release_dir(root, release_id)
    if manifest is None:
        manifest = load_manifest(rel_dir)
    if not manifest:
        return [f'{release_id}: release.json missing or unreadable']
    if int(manifest.get('schema') or 0) != RELEASE_SCHEMA:
        problems.append(
            f"{release_id}: schema {manifest.get('schema')} != "
            f"{RELEASE_SCHEMA} — build/verify version skew")
    files = release_files(manifest)
    if not files:
        problems.append(f'{release_id}: manifest declares no files')
    declared = set()
    for rel, want in sorted(files.items()):
        if rel == MANIFEST_NAME or rel.startswith('../') or rel.startswith('/'):
            problems.append(f'{release_id}: illegal manifest path {rel!r}')
            continue
        declared.add(rel)
        p = os.path.join(rel_dir, rel)
        if not os.path.isfile(p):
            problems.append(f'{release_id}: missing {rel}')
            continue
        got = sha256_file(p)
        if got != want:
            problems.append(
                f'{release_id}: hash mismatch {rel} '
                f'({(got or "unreadable")[:12]} != {want[:12]})')
    # extras: anything under the release dir not declared is unreviewed
    for base, dirs, names in os.walk(rel_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for n in names:
            if n.endswith('.pyc'):
                continue
            rel = os.path.relpath(os.path.join(base, n), rel_dir)
            if rel != MANIFEST_NAME and rel.replace(os.sep, '/') not in declared:
                problems.append(f'{release_id}: undeclared file {rel}')
    return problems


def resolve_active(root, queue_dir):
    """-> (status, release_id, rel_dir, manifest, problems).
    status: 'pinned' | 'unpinned' (no pointer) | 'bad' (pointer set but
    the chain is broken — callers must refuse, never fall back to stale
    code when a release was requested)."""
    ptr = load_pointer(queue_dir)
    if ptr is None:
        return 'unpinned', None, None, None, []
    rel_id = str(ptr.get('release_id'))
    rel_dir = release_dir(root, rel_id)
    manifest = load_manifest(rel_dir)
    if manifest is None:
        return 'bad', rel_id, rel_dir, None, [
            f'{rel_id}: release.json missing/unreadable — '
            f'pointer targets a broken release']
    want_sha = str(ptr.get('release_sha256') or '')
    got_sha = manifest_sha(rel_dir)
    if want_sha and got_sha != want_sha:
        return 'bad', rel_id, rel_dir, None, [
            f'{rel_id}: release.json sha {str(got_sha)[:12]} != pointer '
            f'{want_sha[:12]} — manifest tampered or half-uploaded']
    return 'pinned', rel_id, rel_dir, manifest, \
        verify_release(root, rel_id, manifest)


# ---------------------------------------------------------------- hashes

def job_hash(job):
    """sha256 over the fields that define what a JOBS.py entry runs."""
    d = {k: job.get(k) for k in JOB_HASH_FIELDS}
    return sha256_bytes(json.dumps(d, sort_keys=True, default=str))


def content_hash(file_shas):
    """sha256 over 'rel=sha\\n' lines, sorted — pack/manifest roll-up."""
    lines = ''.join(f'{r}={s}\n' for r, s in sorted(file_shas.items()))
    return sha256_bytes(lines)


def manifest_pack_hash(manifest, kind, name):
    """kind: 'packs' | 'gap_packs'. Release-declared pack content hash."""
    entry = ((manifest or {}).get(kind) or {}).get(name) or {}
    return entry.get('sha256')


def pack_file_set(manifest, prefix):
    """files under <prefix>/ declared in the manifest -> {basename-rel: sha}"""
    pre = prefix.rstrip('/') + '/'
    return {r[len(pre):]: s for r, s in release_files(manifest).items()
            if r.startswith(pre)}


def ws_pack_matches(ws_dir, manifest, prefix):
    """Legacy-marker rescue: True when every code file the release declares
    for this pack exists in the workspace byte-identical. Extra workspace
    files (out/, claim/, model/) are state and ignored. Caveat: proves the
    code present NOW equals the release — the same guarantee the unpinned
    flow ever had."""
    files = pack_file_set(manifest, prefix)
    if not files:
        return False
    for rel, want in files.items():
        if sha256_file(os.path.join(ws_dir, rel)) != want:
            return False
    return True


# ---------------------------------------------------------------- markers

_TOKEN_RE = re.compile(r'(?:^|\s)(rel|jh|ph|gh)=([0-9A-Za-z_.-]+)')


def marker_get(text, key):
    vals = dict(_TOKEN_RE.findall(text or ''))
    return vals.get(key)


def marker_fresh(marker_path, key, expected_sha):
    """-> (fresh: bool, why: str). key in ('jh','ph','gh'). A marker with
    no hash token is 'legacy' — callers decide (packs get a ws rescue;
    jobs re-run)."""
    if not os.path.exists(marker_path):
        return False, 'absent'
    try:
        txt = open(marker_path).read()
    except OSError:
        return False, 'unreadable'
    got = marker_get(txt, key)
    exp = (expected_sha or '')[:12]
    if got:
        return (got == exp,
                f'{key}={got} ' + ('match' if got == exp
                                  else f'stale (now {exp})'))
    return False, f'legacy (no {key}=)'


def stamp_marker(marker_path, seconds, boot, epoch, release_id, key, sha,
                 info=''):
    """Write a hash-aware done marker (text form, JOBS + pack style)."""
    tok = f'{key}={sha[:12]}' if sha else f'{key}=none'
    body = (f'{seconds:.0f}s boot={boot} ep={epoch} rel={release_id} '
            f'{tok} {info}\n')
    tmp = f'{marker_path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        f.write(body)
    os.replace(tmp, marker_path)
    return body


def upgrade_marker(marker_path, key, sha, release_id):
    """Append hash tokens to a rescued legacy marker so the provenance
    upgrade is recorded, not silent."""
    try:
        txt = open(marker_path).read().rstrip('\n')
        with open(marker_path, 'w') as f:
            f.write(f'{txt} rel={release_id} {key}={sha[:12]} '
                    f'upgrade=legacy-ws-match\n')
    except OSError:
        pass


def marker_json(marker_path):
    try:
        d = json.loads(open(marker_path).read())
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def stamp_marker_json(marker_path, **fields):
    """JSON-form markers (gap packs) — same rule, fields carry gh/rel."""
    tmp = f'{marker_path}.{os.getpid()}.tmp'
    with open(tmp, 'w') as f:
        json.dump(fields, f)
        f.write('\n')
    os.replace(tmp, marker_path)


# ---------------------------------------------------------------- materialize

def materialize_pack(src_dir, ws_dir, release_id):
    """Sync release-declared pack code into the writable workspace.
    src_dir contains ONLY code (git bundle); ws keeps state (claim/,
    out/, done, model/...). Files materialized previously that are gone
    from the new release are deleted — the workspace code view is always
    exactly the verified release, never a residue pile. Returns the
    materialized relpaths."""
    files = []
    for base, dirs, names in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for n in names:
            if n.endswith('.pyc'):
                continue
            src = os.path.join(base, n)
            rel = os.path.relpath(src, src_dir).replace(os.sep, '/')
            dst = os.path.join(ws_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if sha256_file(dst) != sha256_file(src):
                shutil.copy2(src, dst)
            files.append(rel)
    old = marker_json(os.path.join(ws_dir, SRC_TRACKER)) or {}
    for rel in old.get('files') or []:
        if rel not in files:
            try:
                os.unlink(os.path.join(ws_dir, rel))
            except OSError:
                pass
    stamp_marker_json(os.path.join(ws_dir, SRC_TRACKER),
                      release_id=release_id, files=files,
                      at=int(time.time()))
    return files
