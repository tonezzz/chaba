import asyncio
import json
import os
import sys
import traceback

import websockets
from google import genai
from google.genai import types

HOST = os.environ.get('GEV_GEMINI_HOST', '0.0.0.0')
PORT = int(os.environ.get('GEV_GEMINI_PORT', '8789'))
CMD_PORT = int(os.environ.get('GEV_CMD_PORT', '8790'))
MODEL = os.environ.get('GEV_GEMINI_MODEL', 'gemini-3.1-flash-live-preview')

# Connected GEV browser clients — the same sockets Gemini tool calls are
# forwarded to. /command pushes function_call frames into these.
CLIENTS = set()
# Passive command clients (ws connected with ?remote=1) — the page registers
# on load WITHOUT starting a Gemini Live session, so a casted display can be
# driven via /command with nobody talking to it. ws -> {'screen': int|None}
REMOTE: dict = {}
# cmd_id -> asyncio.Queue — remote clients' tool_response frames resolve
# here so /command can return what the page actually did.
PENDING: dict = {}
_loop = None

SYSTEM_INSTRUCTION = (
    "You are GEV Voice Control, a concise voice controller for the God's Eye View Cesium geospatial app. "
    "Have a natural spoken conversation. Treat direct commands like 'zoom into London', 'show flights', or 'what am I looking at' as GEV control requests. "
    "Use the provided tools for navigation, layer visibility, camera motion, context mode, visual style, HUD, detection, scene playback, radio, CCTV, annotations, and analytical queries. "
    "Never invent tool names or arguments. Keep confirmations short. When a request requires a tool, call it before speaking. "
    "For ordinary conversation, answer normally without tools."
)


def load_api_key():
    if 'GEMINI_API_KEY' in os.environ:
        return os.environ['GEMINI_API_KEY'].strip()
    secret_path = '/run/secrets/gemini-api-key'
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    raise RuntimeError('GEMINI_API_KEY not set and /run/secrets/gemini-api-key not found')


def _clean_schema(schema):
    if not isinstance(schema, dict):
        return schema
    schema.pop('additionalProperties', None)
    schema.pop('additional_properties', None)
    for key in list(schema.keys()):
        val = schema[key]
        if isinstance(val, dict):
            schema[key] = _clean_schema(val)
        elif isinstance(val, list):
            schema[key] = [_clean_schema(v) if isinstance(v, dict) else v for v in val]
    return schema


def load_tools():
    tool_path = os.path.join(os.path.dirname(__file__), 'tools.json')
    if not os.path.exists(tool_path):
        log('tools.json not found, running without function calling')
        return []
    try:
        with open(tool_path) as f:
            raw = json.load(f)
    except Exception as e:
        log(f'failed to load tools.json: {e}')
        return []
    declarations = []
    for item in raw:
        name = item.get('name')
        description = item.get('description') or ''
        parameters = _clean_schema(item.get('parameters') or {'type': 'object'})
        if not name:
            continue
        declarations.append(types.FunctionDeclaration(
            name=name,
            description=description,
            parameters=parameters,
        ))
    log(f'Loaded {len(declarations)} tool declarations')
    return declarations


def log(msg):
    print(msg, flush=True)


async def pump_responses(session, websocket):
    """Forward model output to the client."""
    try:
        async for msg in session.receive():
            if msg.tool_call:
                for call in (msg.tool_call.function_calls or []):
                    log(f'Tool call: {call.name}({call.args})')
                    try:
                        await websocket.send(json.dumps({
                            'type': 'function_call',
                            'id': call.id,
                            'name': call.name,
                            'args': dict(call.args or {}),
                        }))
                    except Exception:
                        pass

            sc = msg.server_content
            if not sc:
                continue

            if getattr(sc, 'interrupted', False):
                try:
                    await websocket.send(json.dumps({'type': 'interrupted'}))
                except Exception:
                    pass
                continue

            ot = getattr(sc, 'output_transcription', None)
            if ot and getattr(ot, 'text', None):
                try:
                    await websocket.send(json.dumps({'type': 'text', 'text': ot.text}))
                except Exception:
                    pass

            if sc.turn_complete:
                try:
                    await websocket.send(json.dumps({'type': 'done'}))
                except Exception:
                    pass
    except Exception as e:
        log(f'response pump ended: {e}')
        try:
            await websocket.send(json.dumps({'type': 'error', 'message': f'session ended: {e}'}))
        except Exception:
            pass


async def _dispatch(msg: str, screen: int | None = None,
                    wait_s: float = 0.0):
    """Send msg to matching clients. screen=None broadcasts to voice CLIENTS
    + every remote client; a number narrows remotes to that screen.
    With wait_s>0, collects tool_response frames for the call's id."""
    targets = list(CLIENTS) + [
        w for w, m in REMOTE.items()
        if screen is None or m.get('screen') == screen]
    delivered = 0
    for ws in targets:
        try:
            await ws.send(msg)
            delivered += 1
        except Exception:
            pass
    if wait_s <= 0 or not delivered:
        return delivered, []
    cmd_id = json.loads(msg).get('id')
    q: asyncio.Queue = asyncio.Queue()
    PENDING[cmd_id] = q
    responses = []
    deadline = _loop.time() + wait_s
    try:
        while len(responses) < delivered:
            try:
                r = await asyncio.wait_for(
                    q.get(), timeout=max(0.05, deadline - _loop.time()))
                responses.append(r)
            except asyncio.TimeoutError:
                break
    finally:
        PENDING.pop(cmd_id, None)
    return delivered, responses


def _cmd_handler():
    import http.server
    import threading
    import uuid

    class H(http.server.BaseHTTPRequestHandler):
        def _reply(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/command/health':
                # screen may be None — a remote that connected before its
                # vcast page exposed __vcastScreen (hello-retry covers it,
                # but health must not crash meanwhile)
                screens = [m.get('screen') for m in REMOTE.values()]
                self._reply(200, {'ok': True, 'clients': len(CLIENTS),
                                  'remote': len(REMOTE),
                                  'remote_screens': sorted(
                                      s for s in screens if s is not None),
                                  'remote_pending': sum(
                                      1 for s in screens if s is None)})
            else:
                self._reply(404, {'error': 'not found'})

        def do_POST(self):
            if self.path != '/command':
                return self._reply(404, {'error': 'not found'})
            n = int(self.headers.get('Content-Length') or 0)
            try:
                body = json.loads(self.rfile.read(n) or b'{}')
            except Exception as e:
                return self._reply(400, {'error': str(e)})
            name = body.get('name')
            if not name:
                return self._reply(400, {'error': 'name required'})
            screen = body.get('screen')
            # wait>0 collects the clients' tool_response frames — lets
            # get_current_view_state (and friends) actually answer.
            wait_s = min(float(body.get('wait') or 0), 10.0)
            msg = json.dumps({
                'type': 'function_call',
                'id': 'cmd-' + uuid.uuid4().hex[:8],
                'name': name,
                'args': body.get('args') or {},
            })
            try:
                delivered, responses = asyncio.run_coroutine_threadsafe(
                    _dispatch(msg, screen, wait_s),
                    _loop).result(timeout=wait_s + 5)
            except Exception as e:
                return self._reply(502, {'error': str(e)})
            out = {'ok': True, 'delivered': delivered}
            if responses:
                out['responses'] = responses
            self._reply(200, out)

        def log_message(self, fmt, *args):
            log('cmd http: ' + (fmt % args))

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', CMD_PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f'command endpoint on 127.0.0.1:{CMD_PORT} (bind loopback — tailnet via Caddy)')


async def client_handler(websocket):
    # websockets>=10: websocket.request.path; legacy: websocket.path
    req = getattr(websocket, 'request', None)
    path = (getattr(req, 'path', '') if req else '') or getattr(websocket, 'path', '') or ''
    if 'remote=1' in path:
        meta = {'screen': None}
        REMOTE[websocket] = meta
        log(f'Remote client connected {websocket.remote_address} ({len(REMOTE)} remote, {len(CLIENTS)} voice)')
        try:
            async for raw in websocket:
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                t = obj.get('type')
                if t == 'hello':
                    # page announces its vcast screen number (same-origin
                    # parent knows it) so /command can target screen=N
                    meta['screen'] = obj.get('screen')
                elif t == 'tool_response':
                    for r in obj.get('responses') or []:
                        q = PENDING.get(r.get('id'))
                        if q:
                            q.put_nowait(r)
        except Exception:
            pass
        finally:
            REMOTE.pop(websocket, None)
            log(f'Remote client disconnected ({len(REMOTE)} remote)')
        return
    CLIENTS.add(websocket)
    log(f'Client connected {websocket.remote_address} ({len(CLIENTS)} online)')
    try:
        api_key = load_api_key()
        client = genai.Client(api_key=api_key)
        declarations = load_tools()
        tools = [types.Tool(function_declarations=declarations)] if declarations else []
        config_kwargs = {
            'response_modalities': ['AUDIO'],
            'output_audio_transcription': types.AudioTranscriptionConfig(),
            'system_instruction': types.Content(
                role='system',
                parts=[types.Part(text=SYSTEM_INSTRUCTION)],
            ),
        }
        if tools:
            config_kwargs['tools'] = tools
        config = types.LiveConnectConfig(**config_kwargs)
        live_ctx = client.aio.live.connect(model=MODEL, config=config)
        session = await live_ctx.__aenter__()
        try:
            log('Gemini Live session connected')
            await websocket.send(json.dumps({'type': 'status', 'message': 'connected'}))
            pump = asyncio.create_task(pump_responses(session, websocket))

            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            obj = json.loads(message)
                            t = obj.get('type', '')
                            if t == 'end':
                                await session.send_client_content(turn_complete=True)
                            elif t == 'text':
                                await session.send_client_content(
                                    turns=types.Content(
                                        role='user',
                                        parts=[types.Part(text=obj.get('text', ''))],
                                    ),
                                    turn_complete=True,
                                )
                            elif t == 'tool_response':
                                responses = [
                                    types.FunctionResponse(
                                        id=r.get('id', ''),
                                        name=r.get('name', ''),
                                        response=r.get('response', {}),
                                    )
                                    for r in obj.get('responses', [])
                                ]
                                await session.send_tool_response(function_responses=responses)
                        except Exception as e:
                            log(f'message handling error: {e}')
                    else:
                        await session.send_realtime_input(
                            audio=types.Blob(data=message, mime_type='audio/pcm;rate=16000')
                        )
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                pump.cancel()
                try:
                    await pump
                except asyncio.CancelledError:
                    pass
        finally:
            await live_ctx.__aexit__(None, None, None)
    except Exception as e:
        log(f'client_handler setup error: {e}')
        log(traceback.format_exc())
        try:
            await websocket.send(json.dumps({'type': 'error', 'message': f'setup: {e}'}))
        except Exception:
            pass
    CLIENTS.discard(websocket)
    log(f'Client disconnected ({len(CLIENTS)} online)')


async def main():
    global _loop
    _loop = asyncio.get_running_loop()
    _cmd_handler()
    async with websockets.serve(client_handler, HOST, PORT):
        log(f'Bridge on ws://{HOST}:{PORT}')
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
