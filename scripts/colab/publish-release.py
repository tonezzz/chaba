#!/usr/bin/env python3
"""publish-release.py — the hands-off ada-nest Colab release publisher.

Builds an immutable release bundle from the canonical chaba commit
(origin/master — NEVER the working tree), writes release.json with per-file
sha256 + per-pack content hashes, uploads to a versioned Drive dir
(gdrive:ada-nest/releases/<release_id>/), verifies EVERY remote artifact
against the manifest (rclone hashsum), and only then atomically repoints
queue/ACTIVE_RELEASE.json (write-tmp + server-side moveto). Also deploys
the released job-console notebook to queue/ and purges the legacy
unversioned queue/*.py copies so no unreviewed code path remains runnable.

Rollback is a pointer change, not a re-upload:
    publish-release.py --activate <release_id>

Usage:
    publish-release.py [--repo <checkout>] [--remote gdrive:ada-nest]
        [--ref origin/master] [--no-fetch] [--dry-run] [--force]
        [--no-notebook-deploy] [--keep-legacy]
    publish-release.py --activate <release_id>   # rollback / repoint
    publish-release.py --list                    # releases + active pointer
    publish-release.py --verify <release_id>     # remote re-verify only

Idempotent: when origin/master's scripts/colab content already matches the
active release's commit the publish is a no-op (logged, exit 0) — the timer
can fire freely. A release_id that already exists remotely is re-verified,
not re-uploaded.

Requires: git + rclone with the gdrive remote (idc02 holds it).
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    REPO = HERE.parents[2]
except IndexError:
    REPO = Path.home() / 'CascadeProjects' / 'chaba'
SCHEMA = 1
COLAB_SUBDIR = 'scripts/colab'

# canonical source -> path inside releases/<id>/ (explicit map: a new
# top-level file is unmapped until reviewed here — never auto-shipped)
FILE_MAP = {
    'queue-runner.py': 'queue/runner.py',
    'JOBS.py': 'queue/JOBS.py',
    'runtime_registry.py': 'queue/runtime_registry.py',
    'preflight-cell.py': 'queue/preflight-cell.py',
    'queue-launcher-cell.py': 'queue/queue-launcher-cell.py',
    'queue-runner-cell.py': 'queue/queue-runner-cell.py',
    'gap-runner.py': 'queue/gap-runner.py',
    'gap-launcher-cell.py': 'queue/gap-launcher-cell.py',
    'release_lib.py': 'queue/release_lib.py',
    'build-job-console.py': 'queue/build-job-console.py',
    'img_gen.py': 'queue/img_gen.py',
    'ada-nest-job-console.ipynb': 'queue/ada-nest-job-console.ipynb',
    'colab-batch-jobs.ipynb': 'notebooks/colab-batch-jobs.ipynb',
    'colab-serve-worker.ipynb': 'notebooks/colab-serve-worker.ipynb',
}
DIR_MAP = {'packs': 'packs', 'gap-packs': 'gap-packs'}

# pre-pinning Drive copies — purged after the first verified activation so
# an old notebook can't spawn unversioned code (loud failure, not stale run)
LEGACY_QUEUE_FILES = [
    'runner.py', 'JOBS.py', 'runtime_registry.py', 'preflight-cell.py',
    'queue-launcher-cell.py', 'queue-runner-cell.py', 'gap-runner.py',
    'gap-launcher-cell.py', 'img_gen.py', 'build-job-console.py',
]


def log(msg):
    print(f'{time.strftime("%H:%M:%S")} {msg}', flush=True)


def die(msg, rc=1):
    sys.exit(f'publish-release: {msg}')


def git(repo, *args, check=True):
    r = subprocess.run(['git', '-C', str(repo), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        die(f'git {" ".join(args)} failed: {r.stderr.strip()}')
    return r


def rclone(*args, check=True, timeout=600):
    r = subprocess.run(['rclone', *args], capture_output=True, text=True,
                       timeout=timeout)
    if check and r.returncode != 0:
        die(f'rclone {" ".join(args[:2])}… failed: '
            f'{(r.stderr or r.stdout).strip()[:400]}')
    return r


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def content_hash(file_shas):
    lines = ''.join(f'{r}={s}\n' for r, s in sorted(file_shas.items()))
    return hashlib.sha256(lines.encode()).hexdigest()


# ------------------------------------------------------------------- bundle

def extract_bundle(repo, ref, dest):
    """git archive <ref>:scripts/colab -> dest/scripts/colab (committed
    bytes only — the working tree is never read)."""
    src = dest / 'src'
    src.mkdir(parents=True)
    r = subprocess.run(
        ['git', '-C', str(repo), 'archive', '--format=tar', ref,
         '--', COLAB_SUBDIR],
        capture_output=True)
    if r.returncode != 0:
        die(f'git archive {ref} failed: {r.stderr.decode().strip()}')
    tf = tarfile.open(fileobj=io.BytesIO(r.stdout))
    for member in tf.getmembers():          # filter='data' needs py3.12;
        name = member.name.lstrip('./')     # stay compatible: manual check
        if name.startswith('../') or name.startswith('/') or '..' \
                in Path(name).parts:
            die(f'unsafe path in git archive: {member.name}')
        tf.extract(member, src)
    colab = src / COLAB_SUBDIR
    if not colab.is_dir():
        die(f'{COLAB_SUBDIR} absent at {ref}')
    # rebuild the console notebook inside the extracted tree so the
    # shipped .ipynb is provably generated from the shipped cell sources
    build = colab / 'build-job-console.py'
    r = subprocess.run([sys.executable, str(build)], capture_output=True,
                       text=True, cwd=str(colab))
    if r.returncode != 0:
        die(f'build-job-console failed at {ref}: {r.stdout}{r.stderr}')
    return colab


def stage_release(colab_dir, rel_root):
    """Map the extracted tree into the release layout; returns
    {relpath: sha256} + unmapped top-level files (warnings)."""
    files = {}
    unmapped = []
    for p in sorted(colab_dir.iterdir()):
        if p.name in ('__pycache__', '.scratch'):
            continue
        if p.is_file():
            tgt = FILE_MAP.get(p.name)
            if not tgt:
                unmapped.append(p.name)
                continue
            dst = rel_root / tgt
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            files[tgt] = sha256_file(dst)
        elif p.is_dir() and p.name in DIR_MAP:
            tgt_dir = DIR_MAP[p.name]
            for f in sorted(p.rglob('*')):
                if f.is_dir() or '__pycache__' in f.parts \
                        or f.suffix == '.pyc':
                    continue
                rel = f.relative_to(p)
                dst = rel_root / tgt_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                files[f'{tgt_dir}/{rel.as_posix()}'] = sha256_file(dst)
        elif p.is_dir():
            unmapped.append(p.name + '/')
    return files, unmapped


def pack_rollup(files, kind):
    """kind 'packs'|'gap-packs' -> {name: {sha256, files}}."""
    out = {}
    pre = kind + '/'
    for rel, sha in files.items():
        if not rel.startswith(pre):
            continue
        rest = rel[len(pre):]
        if '/' not in rest:
            continue                    # top-level docs (PROCEDURE.md)
        name = rest.split('/', 1)[0]
        out.setdefault(name, {})[rest] = sha
    return {n: {'sha256': content_hash(v), 'files': len(v)}
            for n, v in sorted(out.items())}


def build_manifest(commit, ref, rel_id, files):
    packs = pack_rollup(files, 'packs')
    gap = pack_rollup(files, 'gap-packs')
    return {
        'schema': SCHEMA,
        'release_id': rel_id,
        'commit': commit,
        'ref': ref,
        'generated_at': int(time.time()),
        'generated_by': f'publish-release.py@{os.uname().nodename}',
        'files': files,
        'packs': packs,
        'gap_packs': gap,
    }


# -------------------------------------------------------------------- remote

def remote_json(remote_path):
    r = rclone('cat', remote_path, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def remote_bytes(remote_path):
    r = rclone('cat', remote_path)
    return r.stdout.encode()


def remote_hashsum(remote_dir):
    """-> {relpath: sha256} for every file under remote_dir. --download is
    required on gdrive (no sha256 metadata) and is ALSO the stronger check:
    it hashes the actual remote bytes, not Drive's stored record."""
    r = rclone('hashsum', 'sha256', '--download', remote_dir, timeout=1800)
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r'^([0-9a-f]{64})\s+(.+)$', line.strip())
        if m:
            out[m.group(2).strip()] = m.group(1)
    return out


def remote_files(remote_dir):
    r = rclone('lsf', '-R', '--files-only', remote_dir, check=False)
    if r.returncode != 0:
        return set()
    return {l.strip() for l in r.stdout.splitlines() if l.strip()}


def verify_remote(remote, rel_id, manifest):
    """Every manifest file must exist remotely with the declared sha256,
    and the remote dir must hold nothing else (release.json excepted)."""
    problems = []
    rdir = f'{remote}/releases/{rel_id}'
    got = remote_hashsum(rdir)
    want = manifest.get('files') or {}
    for rel, sha in sorted(want.items()):
        g = got.get(rel)
        if g is None:
            problems.append(f'missing remote {rel}')
        elif g != sha:
            problems.append(f'hash mismatch {rel} ({g[:12]} != {sha[:12]})')
    extras = remote_files(rdir) - set(want) - {'release.json'}
    for rel in sorted(extras):
        problems.append(f'undeclared remote file {rel}')
    return problems


def activate(remote, rel_id, manifest_bytes, commit, previous,
             dry_run=False):
    """Atomic pointer flip: upload ACTIVE_RELEASE.json.tmp then moveto.
    Only ever called AFTER verify_remote() is clean."""
    ptr = {
        'schema': SCHEMA,
        'release_id': rel_id,
        'release_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
        'commit': commit,
        'activated_at': int(time.time()),
        'activated_by': f'publish-release.py@{os.uname().nodename}',
        'previous': previous,
    }
    body = json.dumps(ptr, indent=1) + '\n'
    if dry_run:
        log(f'[dry-run] would activate {rel_id} (previous: {previous})')
        return ptr
    with tempfile.NamedTemporaryFile(
            'w', suffix='.json', delete=False) as f:
        f.write(body)
        tmp_local = f.name
    try:
        tmp_remote = (f'{remote}/queue/.{uuid.uuid4().hex[:8]}'
                      f'.ACTIVE_RELEASE.json.tmp')
        rclone('copyto', tmp_local, tmp_remote)
        rclone('moveto', tmp_remote, f'{remote}/queue/ACTIVE_RELEASE.json')
        got = remote_json(f'{remote}/queue/ACTIVE_RELEASE.json')
        if got != ptr:
            die('pointer verify failed — remote ACTIVE_RELEASE.json '
                'does not match what was written')
    finally:
        os.unlink(tmp_local)
    log(f'activated {rel_id} (previous: {previous})')
    return ptr


def deploy_notebook(remote, rel_id, manifest, dry_run=False):
    """queue/ada-nest-job-console.ipynb := the released notebook — a
    server-side copy out of the verified release dir, re-hashed after."""
    rel = 'queue/ada-nest-job-console.ipynb'
    want = (manifest.get('files') or {}).get(rel)
    if not want:
        die(f'manifest lacks {rel} — cannot deploy the operator surface')
    if dry_run:
        log(f'[dry-run] would deploy {rel} -> queue/')
        return
    rclone('copyto', f'{remote}/releases/{rel_id}/{rel}',
           f'{remote}/queue/ada-nest-job-console.ipynb')
    got = remote_hashsum(f'{remote}/queue/ada-nest-job-console.ipynb')
    if got.get('ada-nest-job-console.ipynb') != want:
        die('deployed notebook hash mismatch — refusing to leave an '
            'unverified operator surface')
    log('deployed queue/ada-nest-job-console.ipynb (hash verified)')


def purge_legacy(remote, dry_run=False):
    """Delete the pre-pinning queue/*.py copies + __pycache__ so no
    unversioned code path remains runnable."""
    q = f'{remote}/queue'
    have = remote_files(q)
    doomed = [f for f in LEGACY_QUEUE_FILES if f in have]
    doomed += [f for f in have
               if f.startswith('__pycache__/') or f.endswith('.pyc')]
    for f in doomed:
        if dry_run:
            log(f'[dry-run] would purge queue/{f}')
        else:
            rclone('deletefile', f'{q}/{f}', check=False)
            log(f'purged legacy queue/{f}')
    return doomed


# -------------------------------------------------------------------- main

def cmd_list(args):
    ptr = remote_json(f'{args.remote}/queue/ACTIVE_RELEASE.json')
    print('active:', json.dumps(ptr, indent=1) if ptr else '(none)')
    r = rclone('lsf', f'{args.remote}/releases', '--dirs-only', check=False)
    if r.returncode == 0:
        for d in sorted(r.stdout.split()):
            print(' release:', d.rstrip('/'))
    return 0


def cmd_verify(args):
    manifest = remote_json(
        f'{args.remote}/releases/{args.verify}/release.json')
    if not manifest:
        die(f'no readable release.json for {args.verify}')
    problems = verify_remote(args.remote, args.verify, manifest)
    if problems:
        for p in problems:
            print(' PROBLEM:', p)
        return 1
    print(f'{args.verify}: verified '
          f'({len(manifest.get("files") or {})} files, '
          f'{len(manifest.get("packs") or {})} packs)')
    return 0


def cmd_activate(args):
    rel_id = args.activate
    mbytes = remote_bytes(f'{args.remote}/releases/{rel_id}/release.json')
    try:
        manifest = json.loads(mbytes)
    except Exception:
        die(f'no readable release.json for {rel_id} — refusing to point '
            f'at an unverifiable release')
    problems = verify_remote(args.remote, rel_id, manifest)
    if problems:
        for p in problems:
            print(' PROBLEM:', p)
        die(f'{rel_id} does not verify — pointer NOT moved')
    prior = remote_json(f'{args.remote}/queue/ACTIVE_RELEASE.json') or {}
    ptr = activate(args.remote, rel_id, mbytes,
                   manifest.get('commit'), prior.get('release_id'),
                   dry_run=args.dry_run)
    deploy_notebook(args.remote, rel_id, manifest, dry_run=args.dry_run)
    if not args.dry_run:
        log(f'ACTIVE_RELEASE -> {rel_id} '
            f'(rollback complete; release_sha256 '
            f'{ptr["release_sha256"][:12]})')
    return 0


def cmd_publish(args):
    repo = Path(args.repo)
    if not args.no_fetch:
        git(repo, 'fetch', 'origin', 'master')
    ref = args.ref
    commit = git(repo, 'rev-parse', ref).stdout.strip()
    log(f'{ref} = {commit[:12]}')

    prior = remote_json(f'{args.remote}/queue/ACTIVE_RELEASE.json') or {}
    prior_commit = prior.get('commit')
    if prior_commit and not args.force:
        d = git(repo, 'diff', '--name-only', prior_commit, commit, '--',
                COLAB_SUBDIR, check=False)
        if d.returncode == 0 and not d.stdout.strip():
            log(f'scripts/colab unchanged since {prior_commit[:12]} '
                f'(active {prior.get("release_id")}) — nothing to publish')
            return 0
        if d.returncode != 0:
            log(f'cannot diff {prior_commit[:12]}..{commit[:12]} '
                '(force-publishing — history may have been rewritten)')

    rel_id = f'rel-{commit[:12]}-{time.strftime("%Y%m%d-%H%M")}'
    log(f'building {rel_id}')

    with tempfile.TemporaryDirectory(prefix='colab-release-') as td:
        td = Path(td)
        colab = extract_bundle(repo, ref, td)
        staged_rel = td / 'release'
        staged_rel.mkdir()
        files, unmapped = stage_release(colab, staged_rel)
        for u in unmapped:
            log(f'  unmapped (not shipped): {u}')
        manifest = build_manifest(commit, ref, rel_id, files)
        mbytes = (json.dumps(manifest, indent=1, sort_keys=True)
                  + '\n').encode()
        (staged_rel / 'release.json').write_bytes(mbytes)
        log(f'manifest: {len(files)} files, '
            f'{len(manifest["packs"])} packs, '
            f'{len(manifest["gap_packs"])} gap-packs')

        # local self-verify: re-hash the staged tree against the manifest
        bad = [rel for rel, sha in files.items()
               if sha256_file(staged_rel / rel) != sha]
        if bad:
            die(f'staging self-verify failed: {bad}')

        if args.dry_run:
            log(f'[dry-run] would upload -> {args.remote}/releases/{rel_id}/')
            for p in sorted(files)[:12]:
                log(f'[dry-run]   {p}')
            if len(files) > 12:
                log(f'[dry-run]   … +{len(files) - 12} more')
            activate(args.remote, rel_id, mbytes, commit,
                     prior.get('release_id'), dry_run=True)
            if not args.no_notebook_deploy:
                deploy_notebook(args.remote, rel_id, manifest,
                                dry_run=True)
            if not args.keep_legacy:
                purge_legacy(args.remote, dry_run=True)
            log('[dry-run] done — nothing was uploaded or changed')
            return 0

        rclone('copy', str(staged_rel), f'{args.remote}/releases/{rel_id}')
        problems = verify_remote(args.remote, rel_id, manifest)
        if problems:
            for p in problems:
                log(f' PROBLEM: {p}')
            die(f'{rel_id} upload did not verify — pointer NOT moved '
                f'(partial dir left for forensics: releases/{rel_id}/)')

        activate(args.remote, rel_id, mbytes, commit,
                 prior.get('release_id'))
        if not args.no_notebook_deploy:
            deploy_notebook(args.remote, rel_id, manifest)
        if not args.keep_legacy:
            purge_legacy(args.remote)

    log(f'RELEASE-OK {rel_id} commit {commit[:12]}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', default=str(REPO),
                    help='chaba checkout (canonical git — never the tree)')
    ap.add_argument('--remote', default='gdrive:ada-nest',
                    help='rclone remote for the ada-nest root')
    ap.add_argument('--ref', default='origin/master',
                    help='git ref the bundle is cut from')
    ap.add_argument('--no-fetch', action='store_true',
                    help='skip git fetch (tests/offline)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true',
                    help='publish even when scripts/colab is unchanged')
    ap.add_argument('--activate', metavar='RELEASE_ID',
                    help='repoint ACTIVE_RELEASE at a verified old release')
    ap.add_argument('--verify', metavar='RELEASE_ID',
                    help='verify a remote release dir and exit')
    ap.add_argument('--list', action='store_true',
                    help='list releases + the active pointer')
    ap.add_argument('--no-notebook-deploy', action='store_true')
    ap.add_argument('--keep-legacy', action='store_true',
                    help='do not purge legacy queue/*.py copies')
    args = ap.parse_args()
    if args.list:
        return cmd_list(args)
    if args.verify:
        return cmd_verify(args)
    if args.activate:
        return cmd_activate(args)
    return cmd_publish(args)


if __name__ == '__main__':
    sys.exit(main())
