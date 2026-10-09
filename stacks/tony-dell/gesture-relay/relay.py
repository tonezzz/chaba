#!/usr/bin/env python3
"""gesture-relay — tiny WS fan-out for the ada_v2 gesture rebuild.

Two roles via query param on /ws:
  ?role=controller — the iPhone camera page; emits {type:"gesture",x,y,...}
  ?role=screen     — the TV/display page; receives controller frames

Everything a controller sends is forwarded verbatim to every screen.
Both sides get {type:"peer",...} presence events so pages can show link
state without a second channel. GET /health -> 200 JSON (same port).

Mirrors the gev-gemini shape (quadlet, asyncio, single port). The relay is
deliberately dumb: no auth (tailnet edge only, Caddy-gated), no state, no
persistence — gesture frames are ephemeral.
"""
import asyncio
import json
import os
import time

HOST = os.environ.get('GESTURE_RELAY_HOST', '127.0.0.1')
PORT = int(os.environ.get('GESTURE_RELAY_PORT', '8794'))

CONTROLLERS: set = set()
SCREENS: set = set()


def log(msg):
    print(msg, flush=True)


def _role_of(websocket) -> str:
    # websockets>=13 asyncio impl: websocket.request.path; legacy: .path
    req = getattr(websocket, 'request', None)
    path = (getattr(req, 'path', '') if req else '') \
        or getattr(websocket, 'path', '') or ''
    return 'controller' if 'role=controller' in path else 'screen'


async def _notify_peers():
    """Tell everyone who is on the bus."""
    msg = json.dumps({
        'type': 'peer',
        'controllers': len(CONTROLLERS),
        'screens': len(SCREENS),
        'ts': time.time(),
    })
    for ws in list(CONTROLLERS | SCREENS):
        try:
            await ws.send(msg)
        except Exception:
            pass


async def handler(websocket):
    role = _role_of(websocket)
    pool = CONTROLLERS if role == 'controller' else SCREENS
    pool.add(websocket)
    log(f'{role} connected {websocket.remote_address} '
        f'({len(CONTROLLERS)} ctl, {len(SCREENS)} scr)')
    await _notify_peers()
    try:
        async for raw in websocket:
            if not isinstance(raw, str):
                continue
            if role == 'controller':
                # Fan out verbatim — the screen owns all interpretation
                # (smoothing, snap, hit-test). Drop frames to dead screens.
                for scr in list(SCREENS):
                    try:
                        await scr.send(raw)
                    except Exception:
                        pass
    except Exception:
        pass
    finally:
        pool.discard(websocket)
        log(f'{role} disconnected '
            f'({len(CONTROLLERS)} ctl, {len(SCREENS)} scr)')
        await _notify_peers()


def _health_payload() -> bytes:
    return json.dumps({
        'ok': True,
        'controllers': len(CONTROLLERS),
        'screens': len(SCREENS),
        'ts': time.time(),
    }).encode()


def _process_request_new(connection, request):
    """websockets>=15 asyncio impl hook: answer /health over plain HTTP."""
    if request.path.split('?')[0].rstrip('/') == '/health':
        body = _health_payload()
        resp = connection.respond(200, body.decode())
        resp.headers['Content-Type'] = 'application/json'
        return resp
    return None


def main():
    from websockets.asyncio.server import serve

    async def run():
        async with serve(handler, HOST, PORT,
                         process_request=_process_request_new,
                         # 20Hz gesture frames don't benefit from
                         # per-message deflate; skip the negotiation cost.
                         compression=None):
            log(f'gesture-relay on {HOST}:{PORT} '
                f'(ws /ws?role=controller|screen, GET /health)')
            await asyncio.Future()  # run forever
    asyncio.run(run())


if __name__ == '__main__':
    main()
