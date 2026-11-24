#!/usr/bin/env python3
"""pack-preflight — deterministic release gate for a video-project pack
set (OPS-09xx / kk-video-preflight-stage).

Runs INSIDE a lightweight CPU-only pack (gpu_gb: 0) before any GPU work in
a queue release, and equally from a fleet host before staging. Validates
the project package and every declared dependent pack, then writes a
deterministic preflight.json + preflight.md. A nonzero exit means verdict
'fail' — the preflight pack then never marks done and every pack that
declares `requires: [<preflight-pack>]` is refused at claim time by both
queue-runners (scripts/colab/queue-runner.py, scripts/ada/nest-worker.py).

Determinism: same inputs -> byte-identical preflight.json and preflight.md
(no wall-clock fields anywhere; provenance is content hashes). Idempotent:
outputs are written atomically (tmp + os.replace) so re-runs are safe.

Checks (order is fixed — check ids are stable API):
  project_manifest          project.json parses, ids agree
  source_provenance         sources[] sha256 formats, project-id hash
                            binding, optional materialized-file rehash
  planning_files            required brief/scene/prompt/rights/qc docs
                            exist and are non-trivial
  fact_dream_labels         declared evidence files carry both `fact`
                            and `dream` labels
  identity_policy           symbolic-identity evidence present; any
                            recorded manifest value is in allowed set
  audio_subtitle_decision   Thai narration + Thai & English subtitle
                            evidence recorded
  pack:<name>:syntax        pack.yml contract (name, needs keys, exactly
                            one of run/run_sh, types)
  pack:<name>:needs         gpu_gb/disk_gb/timeout_s declared and sane
  pack:<name>:artifacts     non-empty artifact globs under allowed
                            prefixes; packs/ globs stay in own dir
  pack:<name>:output_privacy artifacts/publish/fetch never target public
                            or escaping paths
  pack:<name>:banned_flags  no paid-service or public-publish tokens/keys

Usage:
  pack-preflight.py --policy POLICY.yml [--project DIR]
                    [--packs DIR] [--nest-root DIR] [--out DIR]
Exit: 0 pass|warn (artifact written), 2 fail, 3 usage/io error.
"""
import argparse
import hashlib
import json
import os
import re
import sys

SCHEMA = 1
STATUS_RANK = {'pass': 0, 'warn': 1, 'fail': 2}

# Files hashed for the release hash reference — the staged inputs of a
# pack, never its runtime outputs (shots/, embeds/, claim/, done, out/,
# preflight.json...). Adding a file here changes the release hash only
# when staged content actually changes.
RELEASE_FILES = ('pack.yml', 'policy.yml', 'pack-preflight.py')
RELEASE_DIRS = ('inputs',)

NEED_KEYS = {'gpu_gb', 'disk_gb', 'ram_gb', 'egress_only_ok'}
NAME_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,60}')
SHA_RE = re.compile(r'[0-9a-f]{64}')

DEFAULT_BANNED_TOKENS = [
    # public-publish surfaces / paid generation APIs — word-boundary match
    'youtube', 'yt_upload', 'tiktok', 'instagram', 'twitter',
    'public_publish', 'publish_public', 'stripe', 'billing', 'paid',
    'kling', 'runway', 'pika', 'luma', 'sora', 'veo',
]
DEFAULT_BANNED_KEYS = [
    'public', 'publish_public', 'public_url', 'paid', 'spend',
]
DEFAULT_ARTIFACT_PREFIXES = ('packs/', 'renders/', 'voice-bench/',
                             'model-archive/', 'projects/')
DEFAULT_PUBLISH_PREFIXES = ('packs/', 'renders/', 'model-archive/',
                            'projects/', 'voice-bench/', 'doc-pilot/')
DEFAULT_BANNED_PREFIXES = ('public/', 'www/', 'web/', 'stacks/',
                          'http://', 'https://', '/', '..')


def _say(msg):
    print(f'pack-preflight: {msg}', flush=True)


def _load_yaml(path):
    import yaml
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def _worst(checks):
    worst = 'pass'
    for c in checks:
        if STATUS_RANK[c['status']] > STATUS_RANK[worst]:
            worst = c['status']
    return worst


def _check(status, detail):
    return status, detail


# ---------------------------------------------------------------------------
# project-side checks
# ---------------------------------------------------------------------------

def check_project_manifest(project_dir, policy):
    if not project_dir:
        return [_check('fail', 'project dir not materialized — pass '
                       '--project, stage inputs/<project_id>/ in the '
                       'preflight pack, or mirror the project to '
                       '<nest>/projects/<project_id>/')], {}
    pj = os.path.join(project_dir, 'project.json')
    if not os.path.isfile(pj):
        return [_check('fail', f'{pj} missing')], {}
    try:
        manifest = json.loads(_read_text(pj))
    except Exception as e:
        return [_check('fail', f'project.json unreadable: {e}')], {}
    out = []
    pid = manifest.get('project_id')
    if pid != policy.get('project_id'):
        out.append(_check('fail', f'project_id {pid!r} != policy '
                          f"{policy.get('project_id')!r}"))
    if not manifest.get('status'):
        out.append(_check('warn', 'project.json has no status field'))
    return out or [_check('pass', f'project_id={pid} '
                          f'status={manifest.get("status")}')], manifest


def check_source_provenance(project_dir, manifest, policy):
    out = []
    sources = manifest.get('sources')
    if not isinstance(sources, list):
        sources = ([manifest['source']]
                   if isinstance(manifest.get('source'), dict) else [])
    if not sources:
        return [_check('fail', 'project.json has no sources[]')]
    shas = []
    for i, s in enumerate(sources):
        sha = str(s.get('sha256') or '')
        if not SHA_RE.fullmatch(sha):
            out.append(_check('fail', f'sources[{i}].sha256 invalid: '
                              f'{sha[:20]!r}'))
            continue
        shas.append(sha)
        if not s.get('filename'):
            out.append(_check('fail', f'sources[{i}] missing filename'))
        if not isinstance(s.get('bytes'), int) or s['bytes'] <= 0:
            out.append(_check('fail', f'sources[{i}].bytes invalid'))
        src = os.path.join(project_dir, 'source', str(s.get('filename')))
        if os.path.isfile(src):
            actual = _sha256_file(src)
            if actual != sha:
                out.append(_check('fail', f'source/{s["filename"]} sha256 '
                                  f'mismatch: file {actual[:16]} != '
                                  f'manifest {sha[:16]}'))
            else:
                out.append(_check('pass', f'source/{s["filename"]} '
                                  f'rehashed ok ({sha[:16]})'))
        elif policy.get('source_required'):
            out.append(_check('fail', f'source/{s.get("filename")} '
                              'required but not materialized'))
        else:
            out.append(_check('warn', f'source/{s.get("filename")} not '
                              'materialized — manifest hash binding only'))
    # project-id <-> source hash binding: ids like kk-video-<sha12> must
    # name a source they were minted from (provenance anchor).
    want = policy.get('project_id') or ''
    m = re.search(r'-([0-9a-f]{12})$', want)
    if m and shas:
        suffix = m.group(1)
        if not any(sha.startswith(suffix) for sha in shas):
            out.append(_check('fail', f'project_id suffix {suffix} is not '
                              'a prefix of any source sha256'))
        else:
            out.append(_check('pass', f'project_id binds sha256 '
                              f'{suffix}…'))
    return out or [_check('fail', 'no usable sources[] entries')]


def check_planning_files(project_dir, policy):
    out = []
    for req in (policy.get('required_files') or []):
        rel = req['path'] if isinstance(req, dict) else str(req)
        min_b = int(req.get('min_bytes', 1)) if isinstance(req, dict) else 1
        p = os.path.join(project_dir, rel)
        if not os.path.isfile(p):
            out.append(_check('fail', f'{rel} missing'))
        elif os.path.getsize(p) < min_b:
            out.append(_check('fail', f'{rel} too small '
                              f'({os.path.getsize(p)}B < {min_b}B)'))
        else:
            out.append(_check('pass', f'{rel} ({os.path.getsize(p)}B)'))
    return out or [_check('warn', 'policy declares no required_files')]


def _project_text(project_dir, rel):
    p = os.path.join(project_dir, rel)
    try:
        return _read_text(p)
    except OSError:
        return None


def check_fact_dream_labels(project_dir, policy):
    spec = policy.get('fact_dream') or {}
    files = spec.get('files') or []
    labels = spec.get('require_labels') or ['fact', 'dream']
    out = []
    for rel in files:
        text = _project_text(project_dir, rel)
        if text is None:
            out.append(_check('fail', f'{rel} unreadable'))
            continue
        for label in labels:
            n = len(re.findall(rf'(?i)\b{re.escape(label)}s?\b', text))
            if n == 0:
                out.append(_check('fail', f'{rel}: no {label!r} label — '
                                  'fact-vs-dream separation not evidenced'))
            else:
                out.append(_check('pass', f'{rel}: {n}x {label!r} label'))
    return out or [_check('warn', 'policy declares no fact_dream.files')]


def _walk_manifest_scalars(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f'{path}.{k}' if path else str(k)
            yield p, k, v
            yield from _walk_manifest_scalars(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_manifest_scalars(v, f'{path}[{i}]')


def check_identity_policy(project_dir, manifest, policy):
    spec = policy.get('identity') or {}
    out = []
    # 1. any decision recorded in the manifest must be in the allowed set
    key_names = {str(k).lower() for k in (spec.get('manifest_keys') or [])}
    found = []
    for path, key, val in _walk_manifest_scalars(manifest):
        kl = str(key).lower()
        if kl in key_names or 'identity' in kl or 'likeness' in kl:
            if isinstance(val, (str, int, float, bool)):
                found.append((path, str(val).lower()))
    allowed = [str(a).lower() for a in (spec.get('allowed_values')
                                      or ['symbolic', 'mixed'])]
    for path, val in found:
        if any(a in val for a in allowed):
            out.append(_check('pass', f'manifest {path}={val!r} allowed'))
        else:
            out.append(_check('fail', f'manifest {path}={val!r} not in '
                              f'allowed identity policies {allowed}'))
    # 2. documentary evidence — the rights matrix must carry the terms
    terms = spec.get('required_terms') or ['symbolic']
    files = spec.get('evidence_files') or []
    for rel in files:
        text = _project_text(project_dir, rel)
        if text is None:
            out.append(_check('fail', f'{rel} unreadable'))
            continue
        for term in terms:
            if re.search(rf'(?i)\b{re.escape(term)}\b', text):
                out.append(_check('pass', f'{rel}: identity term '
                                  f'{term!r} present'))
            else:
                out.append(_check('fail', f'{rel}: missing identity term '
                                  f'{term!r}'))
    if not found and not files:
        out.append(_check('fail', 'no identity policy recorded anywhere '
                          '(manifest keys or evidence files)'))
    return out or [_check('fail', 'identity policy check inconclusive')]


def check_audio_subtitles(project_dir, policy):
    spec = policy.get('audio') or {}
    out = []
    files = spec.get('evidence_files') or []
    texts = []
    missing = []
    for rel in files:
        t = _project_text(project_dir, rel)
        (texts.append((rel, t)) if t is not None else missing.append(rel))
    if missing:
        out.append(_check('warn', 'audio evidence files absent: '
                          + ', '.join(missing)))
    blob = '\n'.join(t for _, t in texts)
    nre = spec.get('narration_re')
    if nre:
        hit = [rel for rel, t in texts if re.search(nre, t)]
        out.append(_check('pass' if hit else 'fail',
                          f'Thai narration evidence: {hit or "none"}'))
    for lang, rex in (spec.get('subtitle_res') or {}).items():
        hit = [rel for rel, t in texts if re.search(rex, t)]
        out.append(_check('pass' if hit else 'fail',
                          f'subtitle[{lang}] evidence: {hit or "none"}'))
    return out or [_check('warn', 'policy declares no audio checks')]


# ---------------------------------------------------------------------------
# pack-side checks
# ---------------------------------------------------------------------------

def _load_pack_spec(packs_dir, name):
    d = os.path.join(packs_dir, name)
    py = os.path.join(d, 'pack.yml')
    if not os.path.isfile(py):
        return None, None, f'{name}: pack.yml missing under {packs_dir}'
    try:
        spec = _load_yaml(py)
    except Exception as e:
        return None, None, f'{name}: bad pack.yml ({e})'
    if not isinstance(spec, dict):
        return None, None, f'{name}: pack.yml is not a mapping'
    spec.setdefault('name', name)
    return d, spec, None


def check_pack_syntax(packs_dir, name):
    d, spec, err = _load_pack_spec(packs_dir, name)
    if err:
        return [_check('fail', err)], None
    out = []
    if spec.get('name') != name:
        out.append(_check('fail', f'pack.yml name {spec.get("name")!r} '
                          f'!= dir {name!r}'))
    if not NAME_RE.fullmatch(name):
        out.append(_check('fail', f'pack name {name!r} fails '
                          '[a-z0-9-] contract'))
    needs = spec.get('needs')
    if needs is not None:
        if not isinstance(needs, dict):
            out.append(_check('fail', 'needs must be a map'))
        else:
            bad = [k for k in needs if k not in NEED_KEYS]
            if bad:
                out.append(_check('fail', f'needs keys unknown: {bad}'))
            for k, v in needs.items():
                if k != 'egress_only_ok' and not isinstance(
                        v, (int, float)):
                    out.append(_check('fail', f'needs.{k} not numeric'))
    if bool(spec.get('run')) == bool(spec.get('run_sh')):
        out.append(_check('fail', 'exactly one of run / run_sh required'))
    for key, kind in (('artifacts', list), ('fetch', list),
                      ('requires', list)):
        v = spec.get(key)
        if v is not None and not (isinstance(v, kind)
                                  and all(isinstance(x, str) for x in v)):
            out.append(_check('fail', f'{key} must be a list of strings'))
    if spec.get('publish') is not None and not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in (spec.get('publish') or {}).items()):
        out.append(_check('fail', 'publish must be a str->str map'))
    if spec.get('timeout_s') is not None and not isinstance(
            spec['timeout_s'], int):
        out.append(_check('fail', 'timeout_s must be int seconds'))
    if spec.get('scope') not in (None, 'work', 'env'):
        out.append(_check('fail', "scope must be 'work' or 'env'"))
    if spec.get('venv') is not None and not isinstance(
            spec['venv'], bool):
        out.append(_check('fail', 'venv must be boolean'))
    return (out or [_check('pass', 'pack.yml contract ok')]), spec


def check_pack_needs(spec):
    out = []
    needs = spec.get('needs') or {}
    for k in ('gpu_gb', 'disk_gb'):
        v = needs.get(k)
        if not isinstance(v, (int, float)):
            out.append(_check('fail', f'needs.{k} undeclared'))
        elif k == 'gpu_gb' and v < 0 or k == 'disk_gb' and v <= 0:
            out.append(_check('fail', f'needs.{k}={v} insane'))
    if 'ram_gb' in needs and not isinstance(needs['ram_gb'], (int, float)):
        out.append(_check('fail', 'needs.ram_gb not numeric'))
    t = spec.get('timeout_s')
    if not isinstance(t, int) or t <= 0 or t > 86400:
        out.append(_check('fail', f'timeout_s {t!r} must be int in '
                          '(0, 86400]'))
    return out or [_check('pass',
                          f"gpu={needs.get('gpu_gb')}GB "
                          f"disk={needs.get('disk_gb')}GB "
                          f"ram={needs.get('ram_gb', '-')}GB "
                          f"timeout={spec.get('timeout_s')}s")]


def _unsafe_path(rel):
    return (rel.startswith('/') or '://' in rel or rel == '..'
            or rel.startswith('../') or '/..' in rel)


def check_pack_artifacts(name, spec, policy):
    out = []
    arts = spec.get('artifacts') or []
    if not arts:
        return [_check('fail', 'pack declares no artifact globs — '
                       'verify-before-mark has nothing to gate on')]
    prefixes = tuple(policy.get('artifact_prefixes')
                     or DEFAULT_ARTIFACT_PREFIXES)
    for g in arts:
        if _unsafe_path(g):
            out.append(_check('fail', f'artifact {g!r} escapes the store'))
            continue
        if not g.startswith(prefixes):
            out.append(_check('fail', f'artifact {g!r} outside allowed '
                              f'prefixes {prefixes}'))
            continue
        if g.startswith('packs/') and not g.startswith(f'packs/{name}/'):
            out.append(_check('fail', f'artifact {g!r} writes into '
                              "another pack's dir"))
            continue
        out.append(_check('pass', f'artifact {g!r}'))
    return out


def check_output_privacy(name, spec, policy):
    out = []
    banned = tuple(policy.get('banned_prefixes') or DEFAULT_BANNED_PREFIXES)
    pub_ok = tuple(policy.get('publish_prefixes') or DEFAULT_PUBLISH_PREFIXES)
    # the project's own store tree (ada-nest/<project_id>/) is private
    pid = policy.get('project_id')
    if pid:
        pub_ok += (f'{pid}/',)
    targets = ([('artifact', g) for g in (spec.get('artifacts') or [])]
               + [('publish-src', s) for s in (spec.get('publish') or {})]
               + [('publish-dest', d)
                  for d in (spec.get('publish') or {}).values()])
    for kind, rel in targets:
        bad = next((b for b in banned if rel.startswith(b)), None)
        if bad:
            out.append(_check('fail', f'{kind} {rel!r} targets banned '
                              f'prefix {bad!r}'))
        elif kind == 'publish-dest' and not rel.startswith(pub_ok):
            out.append(_check('fail', f'publish dest {rel!r} outside '
                              f'allowed store prefixes {pub_ok}'))
        else:
            out.append(_check('pass', f'{kind} {rel!r}'))
    return out or [_check('pass', 'no publish/fetch destinations')]


def _tok_re(token):
    """Alnum-boundary token match — catches youtube_upload/public_publish
    forms that \\b misses (underscore is a word char) while still letting
    'paid' inside 'repaid' etc. alone."""
    return re.compile(rf'(?i)(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])')


def check_banned_flags(name, spec, policy, extra_texts):
    """Serialized pack spec + declared policy text surfaces scanned for
    paid-service / public-publish markers. Keys are matched exactly;
    tokens use the alnum-boundary matcher."""
    out = []
    tokens = policy.get('banned_tokens') or DEFAULT_BANNED_TOKENS
    bkeys = set(policy.get('banned_keys') or DEFAULT_BANNED_KEYS)
    blob = json.dumps(spec, ensure_ascii=False)
    hits = [t for t in tokens if _tok_re(t).search(blob)]
    for t in hits:
        out.append(_check('fail', f'pack spec contains banned token '
                          f'{t!r}'))
    for path, key, _v in _walk_manifest_scalars(spec):
        if str(key).lower() in bkeys:
            out.append(_check('fail', f'pack spec has banned key '
                              f'{path}'))
    for label, text in extra_texts:
        for t in tokens:
            if _tok_re(t).search(text):
                out.append(_check('fail', f'{label} contains banned '
                                  f'token {t!r}'))
    return out or [_check('pass', 'no paid/public-publish markers')]


# ---------------------------------------------------------------------------
# release hash reference
# ---------------------------------------------------------------------------

def _release_files(pack_dir):
    out = []
    for f in RELEASE_FILES:
        p = os.path.join(pack_dir, f)
        if os.path.isfile(p):
            out.append(f)
    for d in RELEASE_DIRS:
        root = os.path.join(pack_dir, d)
        for base, _dirs, files in os.walk(root):
            for f in files:
                out.append(os.path.relpath(
                    os.path.join(base, f), pack_dir))
    return sorted(out)


def pack_release_hash(pack_dir):
    """sha256 over the pack's staged inputs only — the release hash is
    stable across runs because runtime outputs are never hashed."""
    h = hashlib.sha256()
    n = total = 0
    for rel in _release_files(pack_dir):
        digest = _sha256_file(os.path.join(pack_dir, rel))
        h.update(rel.encode())
        h.update(b'\0')
        h.update(digest.encode())
        h.update(b'\n')
        n += 1
        total += os.path.getsize(os.path.join(pack_dir, rel))
    return h.hexdigest(), n, total


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def resolve_project_dir(policy, args):
    pid = policy.get('project_id')
    cands = []
    if args.project:
        cands.append(args.project)
    if args.pack_dir:
        cands += [os.path.join(args.pack_dir, 'inputs', pid or 'project'),
                  os.path.join(args.pack_dir, 'inputs', 'project')]
    if args.nest_root and pid:
        cands.append(os.path.join(args.nest_root, 'projects', pid))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, 'project.json')):
            return os.path.abspath(c)
    return cands[0] if cands and args.project else None


def emit_check(checks, cid, results):
    status = _worst([{'status': s} for s, _ in results])
    detail = '; '.join(f'[{s}] {d}' for s, d in results)
    checks.append({'id': cid, 'status': status, 'detail': detail})
    return results


def run_preflight(policy_path, project_dir, packs_dir, extra_text_dirs=()):
    policy = _load_yaml(policy_path) or {}
    checks = []
    proj_checks, manifest = check_project_manifest(project_dir, policy)
    emit_check(checks, 'project_manifest', proj_checks)
    if manifest:
        emit_check(checks, 'source_provenance',
                   check_source_provenance(project_dir, manifest, policy))
    else:
        checks.append({'id': 'source_provenance', 'status': 'fail',
                       'detail': 'skipped — manifest unreadable'})
    if project_dir and os.path.isdir(project_dir):
        emit_check(checks, 'planning_files',
                   check_planning_files(project_dir, policy))
        emit_check(checks, 'fact_dream_labels',
                   check_fact_dream_labels(project_dir, policy))
        emit_check(checks, 'identity_policy',
                   check_identity_policy(project_dir, manifest or {},
                                         policy))
        emit_check(checks, 'audio_subtitle_decision',
                   check_audio_subtitles(project_dir, policy))
    else:
        for cid in ('planning_files', 'fact_dream_labels',
                    'identity_policy', 'audio_subtitle_decision'):
            checks.append({'id': cid, 'status': 'fail',
                           'detail': 'skipped — project dir absent'})

    packs = {}
    pack_names = list(policy.get('packs') or [])
    for name in pack_names:
        res, spec = check_pack_syntax(packs_dir, name)
        emit_check(checks, f'pack:{name}:syntax', res)
        if spec is None:
            for kind in ('needs', 'artifacts', 'output_privacy',
                         'banned_flags'):
                checks.append({'id': f'pack:{name}:{kind}',
                               'status': 'fail',
                               'detail': 'skipped — pack.yml unreadable'})
            packs[name] = {'sha256': None, 'error': 'pack.yml unreadable'}
            continue
        emit_check(checks, f'pack:{name}:needs', check_pack_needs(spec))
        emit_check(checks, f'pack:{name}:artifacts',
                   check_pack_artifacts(name, spec, policy))
        emit_check(checks, f'pack:{name}:output_privacy',
                   check_output_privacy(name, spec, policy))
        extra = [(f'project.json', json.dumps(manifest,
                                              ensure_ascii=False))]
        scan_dirs = list(extra_text_dirs)
        proj_packs = (os.path.join(project_dir, 'packs')
                      if project_dir else '')
        if proj_packs and os.path.isdir(proj_packs):
            scan_dirs.append(proj_packs)   # plan-level specs can carry
        for d in scan_dirs:                # publish flags too
            for base, _ds, fs in os.walk(d):
                for f in sorted(fs):
                    rel = os.path.relpath(os.path.join(base, f), d)
                    extra.append((f'{os.path.basename(d)}/{rel}',
                                  _read_text(os.path.join(base, f))))
        emit_check(checks, f'pack:{name}:banned_flags',
                   check_banned_flags(name, spec, policy, extra))
        sha, nfiles, nbytes = pack_release_hash(
            os.path.join(packs_dir, name))
        packs[name] = {'sha256': sha, 'files': nfiles, 'bytes': nbytes}

    # preflight pack's own staged inputs are part of the release too
    if packs_dir and policy.get('self_pack'):
        sha, nfiles, nbytes = pack_release_hash(
            os.path.join(packs_dir, policy['self_pack']))
        packs[policy['self_pack']] = {'sha256': sha, 'files': nfiles,
                                      'bytes': nbytes}

    inputs_hashes = {}
    if project_dir and os.path.isdir(project_dir):
        rels = ['project.json']
        for req in (policy.get('required_files') or []):
            rels.append(req['path'] if isinstance(req, dict) else str(req))
        for grp in ('fact_dream', 'identity', 'audio'):
            spec = policy.get(grp) or {}
            rels += spec.get('files') or []
            rels += spec.get('evidence_files') or []
        for rel in sorted(set(rels)):
            p = os.path.join(project_dir, rel)
            if os.path.isfile(p):
                inputs_hashes[rel] = _sha256_file(p)

    rel = hashlib.sha256()
    for name in sorted(packs):
        rel.update(f'{name}={packs[name]["sha256"]}\n'.encode())

    fails = sum(1 for c in checks if c['status'] == 'fail')
    warns = sum(1 for c in checks if c['status'] == 'warn')
    report = {
        'kind': 'pack-preflight',
        'schema': SCHEMA,
        'project_id': policy.get('project_id'),
        'verdict': 'fail' if fails else ('warn' if warns else 'pass'),
        'fail_count': fails,
        'warn_count': warns,
        'checks': checks,
        'packs': packs,
        'inputs_sha256': inputs_hashes,
        'release_sha256': rel.hexdigest(),
    }
    return report


def render_md(report):
    lines = ['# pack-preflight report', '',
             f"- project: `{report['project_id']}`",
             f"- verdict: **{report['verdict'].upper()}** "
             f"({report['fail_count']} fail, {report['warn_count']} warn)",
             f"- release_sha256: `{report['release_sha256']}`",
             '', '## checks', '',
             '| check | status | detail |', '|---|---|---|']
    for c in report['checks']:
        lines.append(f"| {c['id']} | {c['status']} | "
                     f"{c['detail'].replace('|', '/')[:400]} |")
    lines += ['', '## pack release hashes', '',
              '| pack | sha256 | files | bytes |', '|---|---|---|---|']
    for name in sorted(report['packs']):
        p = report['packs'][name]
        lines.append(f"| {name} | {p.get('sha256') or 'ERROR'} "
                     f"| {p.get('files', '-')} | {p.get('bytes', '-')} |")
    lines += ['', '## input hashes (project docs consumed)', '']
    for rel in sorted(report['inputs_sha256']):
        lines.append(f"- `{rel}` = {report['inputs_sha256'][rel]}")
    lines += ['', '_deterministic output — no timestamps by design._', '']
    return '\n'.join(lines)


def _atomic_write(path, text):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--policy', required=True)
    ap.add_argument('--project', help='explicit project dir '
                    '(default: pack inputs/ or <nest>/projects/<id>)')
    ap.add_argument('--packs', help='packs root dir (default: parent of '
                    'pack dir or $NEST_ROOT/packs)')
    ap.add_argument('--pack-dir', help='preflight pack dir '
                    '(default: policy dir)')
    ap.add_argument('--nest-root', default=os.environ.get('NEST_ROOT'),
                    help='ada-nest root for projects/ lookup')
    ap.add_argument('--out', help='output dir (default: pack dir)')
    ap.add_argument('--scan-dir', action='append', default=[],
                    help='extra text dir scanned for banned tokens')
    args = ap.parse_args(argv)

    try:
        pack_dir = args.pack_dir or os.path.dirname(
            os.path.abspath(args.policy))
        args.pack_dir = pack_dir
        packs_dir = args.packs or os.path.join(
            args.nest_root or os.path.dirname(
                os.path.dirname(pack_dir)), 'packs')
        project_dir = resolve_project_dir(
            _load_yaml(args.policy) or {}, args)
        out_dir = args.out or pack_dir
        os.makedirs(out_dir, exist_ok=True)

        report = run_preflight(args.policy, project_dir, packs_dir,
                               extra_text_dirs=args.scan_dir)
    except Exception as e:
        _say(f'ERROR: {e}')
        return 3

    _atomic_write(os.path.join(out_dir, 'preflight.json'),
                  json.dumps(report, indent=1, sort_keys=True,
                             ensure_ascii=False) + '\n')
    _atomic_write(os.path.join(out_dir, 'preflight.md'),
                  render_md(report))
    _say(f"verdict={report['verdict']} checks={len(report['checks'])} "
         f"fail={report['fail_count']} warn={report['warn_count']} "
         f"release={report['release_sha256'][:12]} "
         f"-> {out_dir}/preflight.json")
    return 0 if report['verdict'] in ('pass', 'warn') else 2


if __name__ == '__main__':
    sys.exit(main())
