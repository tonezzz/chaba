#!/usr/bin/env python3
"""nest-pack-submit — validate a pack dir and stage it to the Drive store.

Producer half of the pull-based queue: agents/sessions build packs in the
repo (scripts/colab/packs/<name>/), this validates the contract and pushes
to gdrive:ada-nest/packs/<name>/ — from then on ANY capable worker (Colab
runtime, future fleet workers) claims and runs it. Connect-later is the
whole point: staged packs wait indefinitely.

Run wherever rclone has gdrive: configured (tony-dell, con01 canonical).

Usage:
  nest-pack-submit.py <pack-dir> [--remote gdrive:ada-nest] [--dry-run]
  nest-pack-submit.py --list            # what's staged/claimed/done
"""
import argparse, os, re, subprocess, sys

NEED_KEYS = {'gpu_gb', 'disk_gb', 'ram_gb', 'egress_only_ok'}
NAME_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,60}')


def die(msg):
    print(f'nest-pack-submit: {msg}', file=sys.stderr)
    sys.exit(1)


def load_yml(path):
    try:
        import yaml
    except ImportError:
        die('pyyaml required — pip install pyyaml')
    try:
        return yaml.safe_load(open(path))
    except Exception as e:
        die(f'bad pack.yml: {e}')


def validate(spec, dirname):
    errs = []
    name = spec.get('name') or dirname
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}', name):
        errs.append(f'name {name!r} must match [a-z0-9-]')
    if name != dirname:
        errs.append(f'name {name!r} != dir {dirname!r} (keep them equal)')
    needs = spec.get('needs') or {}
    if not isinstance(needs, dict):
        errs.append('needs must be a map')
    else:
        for k, v in needs.items():
            if k not in NEED_KEYS:
                errs.append(f'needs.{k} unknown (known: {sorted(NEED_KEYS)})')
            elif k != 'egress_only_ok' and not isinstance(v, (int, float)):
                errs.append(f'needs.{k} must be numeric')
    has_run = bool(spec.get('run')) ^ bool(spec.get('run_sh'))
    if not has_run:
        errs.append('exactly one of run / run_sh required')
    reqs = spec.get('requires')
    if reqs is not None:
        if not (isinstance(reqs, list)
                and all(isinstance(r, str) for r in reqs)):
            errs.append('requires must be a list of pack-name strings')
        else:
            for r in reqs:
                if not NAME_RE.fullmatch(r):
                    errs.append(f'requires entry {r!r} is not a valid '
                                'pack name')
                if r == name:
                    errs.append('requires must not self-reference')
    fetch = spec.get('fetch')
    if fetch is not None and not (isinstance(fetch, list)
                                  and all(isinstance(f, str)
                                          for f in fetch)):
        errs.append('fetch must be a list of store-relative paths')
    pub = spec.get('publish')
    if pub is not None and not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in (pub or {}).items()):
        errs.append('publish must be a str->str map')
    arts = spec.get('artifacts')
    if arts is not None and not (isinstance(arts, list) and all(
            isinstance(a, str) for a in arts)):
        errs.append('artifacts must be a list of glob strings')
    if arts and not all(a.startswith('packs/') or a.startswith('renders/')
                        or a.startswith('voice-bench/') for a in arts):
        errs.append('artifacts globs should live under packs/<n>/, renders/, '
                    'or voice-bench/ (checked vs ada-nest/ root)')
    if spec.get('timeout_s') is not None and not isinstance(
            spec['timeout_s'], int):
        errs.append('timeout_s must be int seconds')
    if spec.get('scope') not in (None, 'work', 'env'):
        errs.append("scope must be 'work' or 'env'")
    return errs


def rclone(*args, capture=True):
    cmd = ['rclone'] + list(args)
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            die(f'rclone {args[0]} failed: {r.stderr.strip()[:300]}')
        return r.stdout
    subprocess.run(cmd, check=True)


def lsf_or_empty(path):
    """lsf that tolerates absent dirs — a pack with no claim/ dir is queued,
    not an error."""
    r = subprocess.run(['rclone', 'lsf', path], capture_output=True,
                       text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pack_dir', nargs='?')
    ap.add_argument('--remote', default='gdrive:ada-nest')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--list', action='store_true')
    args = ap.parse_args()

    if args.list:
        packs = rclone('lsf', f'{args.remote}/packs')
        for d in [x.rstrip('/') for x in packs.splitlines() if x.strip()]:
            entries = lsf_or_empty(f'{args.remote}/packs/{d}').split()
            claim = lsf_or_empty(f'{args.remote}/packs/{d}/claim').strip()
            state = 'DONE' if 'done' in entries else (
                'CLAIMED' if claim else 'queued')
            print(f'{d}: {state}')
        return

    if not args.pack_dir:
        die('pack-dir required (or --list)')
    d = args.pack_dir.rstrip('/')
    py = f'{d}/pack.yml'
    if not os.path.isfile(py):
        die(f'{py} not found')
    spec = load_yml(py)
    dirname = os.path.basename(d)
    errs = validate(spec, dirname)
    if errs:
        for e in errs:
            print(f'  ✗ {e}')
        die(f'{len(errs)} validation error(s)')

    name = spec.get('name') or dirname
    print(f'pack {name}: valid — staging to {args.remote}/packs/{name}/')
    if args.dry_run:
        print('(dry run — not pushed)')
        return
    rclone('copy', d, f'{args.remote}/packs/{name}',
           '--exclude', 'claim/**', '--exclude', 'done',
           capture=False)
    print(f'staged. workers will discover it on their next pass.')
    print(f'check: nest-queue-status.py   (packs section)')


if __name__ == '__main__':
    main()
