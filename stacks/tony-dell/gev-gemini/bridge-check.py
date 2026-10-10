#!/usr/bin/env python3
"""bridge-check — self-test the /command relay without websockets/genai.

Covers the frame-loading gap fix (card gev-relay-frame-loading-404):
a screen-targeted command that arrives before the GEV page registers its
?remote=1 socket must wait for it (grace), not 404/fail immediately; if
the grace elapses the error must be marked retryable with a retry hint.

    python3 bridge-check.py        # exits 0 on pass, 1 with diff on fail
"""
import asyncio
import json
import os
import sys
import threading
import time
import types as pytypes
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ.setdefault('GEV_CMD_PORT', '18790')
os.environ.setdefault('GEV_REMOTE_GRACE_S', '1.5')
os.environ.setdefault('GEV_REMOTE_RETRY_S', '1')

# bridge.py imports websockets + google.genai at module top; neither is
# needed on the /command path, so stub them for a dependency-free check.
sys.modules.setdefault('websockets', pytypes.ModuleType('websockets'))
_google = pytypes.ModuleType('google')
_genai = pytypes.ModuleType('google.genai')
_gtypes = pytypes.ModuleType('google.genai.types')
_gtypes.__getattr__ = lambda n: type(n, (), {'__init__': lambda s, *a, **k: None})
_genai.types = _gtypes
_google.genai = _genai
sys.modules.setdefault('google', _google)
sys.modules.setdefault('google.genai', _genai)
sys.modules.setdefault('google.genai.types', _gtypes)

import bridge  # noqa: E402

BASE = f"http://127.0.0.1:{os.environ['GEV_CMD_PORT']}"
GRACE = float(os.environ['GEV_REMOTE_GRACE_S'])

_checks = 0


def check(label, cond, detail=''):
    global _checks
    _checks += 1
    status = 'PASS' if cond else 'FAIL'
    print(f'[{status}] {label}' + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        sys.exit(1)


def post(body):
    req = urllib.request.Request(
        f'{BASE}/command', data=json.dumps(body).encode(),
        headers={'content-type': 'application/json'})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=30) as r:
        return time.monotonic() - t0, json.loads(r.read())


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def main():
    loop = asyncio.new_event_loop()
    bridge._loop = loop
    threading.Thread(target=loop.run_forever, daemon=True).start()
    bridge._cmd_handler()
    time.sleep(0.2)

    # 1. no remote anywhere: screen-targeted call waits out the grace,
    #    then fails with a retryable loading hint — not instantly.
    dt, out = post({'name': 'fly_to_location', 'args': {}, 'screen': 6})
    check('grace: no remote waits ~grace_s', dt >= GRACE * 0.9,
          f'elapsed {dt:.2f}s < {GRACE * 0.9:.2f}s')
    check('grace: no remote -> ok:false', out.get('ok') is False, str(out))
    check('grace: failure marked retryable', out.get('retryable') is True,
          str(out))
    check('grace: retry_after_s present',
          out.get('retry_after_s') == int(os.environ['GEV_REMOTE_RETRY_S']),
          str(out))
    check('grace: error says still loading + retry',
          'loading' in out.get('error', '') and 'retry' in out.get('error', ''),
          out.get('error', ''))

    # 2. remote appears mid-grace -> command is delivered to it.
    fake = FakeWS()

    def late_register():
        time.sleep(GRACE * 0.3)
        bridge.REMOTE[fake] = {'screen': 6, 'pane': None}
    threading.Thread(target=late_register, daemon=True).start()
    dt, out = post({'name': 'fly_to_location', 'args': {'query': 'x'},
                    'screen': 6})
    check('grace: late remote delivers', out.get('ok') is True
          and out.get('delivered') == 1, str(out))
    check('grace: delivery beat the deadline', dt < GRACE,
          f'elapsed {dt:.2f}s')
    sent = [json.loads(m) for m in fake.sent]
    check('grace: function_call reached remote',
          sent and sent[0].get('type') == 'function_call'
          and sent[0].get('name') == 'fly_to_location', str(sent))

    # 3. wrong screen still misses the registered remote -> retryable.
    dt, out = post({'name': 'fly_to_location', 'args': {}, 'screen': 9})
    check('wrong screen -> ok:false retryable',
          out.get('ok') is False and out.get('retryable') is True, str(out))

    # 4. broadcast (screen=None) unchanged: no wait, ok:true, delivered n.
    dt, out = post({'name': 'noop', 'args': {}})
    check('broadcast: no grace wait', dt < GRACE, f'elapsed {dt:.2f}s')
    check('broadcast: ok:true delivered=1',
          out.get('ok') is True and out.get('delivered') == 1, str(out))

    # 5. pane filter still respected during grace: a remote that
    #    announced pane=0 does not satisfy a pane=2 command.
    bridge.REMOTE.clear()
    fake0 = FakeWS()
    bridge.REMOTE[fake0] = {'screen': 6, 'pane': 0}
    dt, out = post({'name': 'noop', 'args': {}, 'screen': 6, 'pane': 2})
    check('pane mismatch waits grace then retryable',
          dt >= GRACE * 0.9 and out.get('ok') is False
          and out.get('retryable') is True, f'{dt:.2f}s {out}')
    bridge.REMOTE.clear()
    bridge.REMOTE[fake] = {'screen': 6, 'pane': None}

    # 6. health endpoint unaffected.
    with urllib.request.urlopen(f'{BASE}/command/health', timeout=10) as r:
        health = json.loads(r.read())
    check('health: 200 + remote listed', health.get('ok') is True
          and any(m.get('screen') == 6 for m in health.get('remotes', [])),
          str(health))

    print(f'{_checks} checks passed')


if __name__ == '__main__':
    main()
