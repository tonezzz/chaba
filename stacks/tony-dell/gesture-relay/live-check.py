#!/usr/bin/env python3
"""Smoke check for gesture-relay: ws fan-out + /health.

Usage:
    live-check.py [--url ws://127.0.0.1:8794/ws]

For the tailnet path use the wss://.../apps/gesture-live/ws URL; health is
checked on the same authority at /apps/gesture-live/health (or /health for
a direct port URL).
"""
import asyncio
import json
import sys
import urllib.request

import websockets

WS_URL = 'ws://127.0.0.1:8794/ws'
if '--url' in sys.argv:
    WS_URL = sys.argv[sys.argv.index('--url') + 1]

# ws(s)://host[:port]/ws[?...] -> http(s)://host[:port]<dir-of-ws>/health
from urllib.parse import urlsplit

_u = urlsplit(WS_URL)
_dir = _u.path.rsplit('/', 1)[0]  # '/ws' -> '' ; '/apps/gesture-live/ws' -> '/apps/gesture-live'
HEALTH_URL = ('https' if _u.scheme == 'wss' else 'http') + '://' \
    + _u.netloc + _dir + '/health'


async def main():
    with urllib.request.urlopen(HEALTH_URL, timeout=10) as r:
        health = json.loads(r.read())
    assert health.get('ok'), health
    print('health:', health)

    async with websockets.connect(WS_URL + '?role=screen') as scr, \
            websockets.connect(WS_URL + '?role=controller') as ctl:
        peer = json.loads(await asyncio.wait_for(scr.recv(), 5))
        assert peer['type'] == 'peer', peer
        await ctl.send(json.dumps({
            'type': 'gesture', 'x': 0.5, 'y': 0.4, 'wx': 0.5, 'wy': 0.6}))
        got = None
        for _ in range(4):  # peer event may interleave; skip to the gesture
            msg = json.loads(await asyncio.wait_for(scr.recv(), 5))
            if msg.get('type') == 'gesture':
                got = msg
                break
        assert got and abs(got['x'] - 0.5) < 1e-9, got
        print('fan-out ok:', got)
    print('PASS', WS_URL)


asyncio.run(main())
