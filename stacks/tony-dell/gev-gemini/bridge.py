import asyncio
import json
import os
import re
import sys
import time
import traceback
import urllib.request
import uuid

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
    "LANGUAGE: always reply in the language the user is currently speaking — Thai in, Thai out; English in, "
    "English out. If the user asks you to switch languages (\"speak Thai\", \"พูดภาษาไทย\"), switch immediately "
    "and stay in that language until asked again."
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


# ---------------------------------------------------------------- guards
# Same model Ada's provider applies: the model proposes, the program
# enforces. Three guards, all deterministic:
#  1. per-turn tool-call budget (storm break)
#  2. confirm gate — state-changing tools need the user's own last
#     utterance to affirm (input transcription); otherwise the call is
#     dropped and the model gets an error it can act on ("ask the user")
#  3. guard interventions emit ops events to MDDB for the digest
TURN_TOOL_BUDGET = int(os.environ.get('GEV_TURN_TOOL_BUDGET', '12'))
# Screen-targeted /command calls wait this long for a matching remote to
# register before answering — a freshly casted GEV page needs a few
# seconds of frame-loading before its ?remote=1 socket + hello land
# (the 2026-10-08 "nav OK, flyTo 404" gap). Broadcasts (screen=None)
# don't wait — nobody may be watching at all.
REMOTE_GRACE_S = float(os.environ.get('GEV_REMOTE_GRACE_S', '12'))
REMOTE_POLL_S = 0.25
# Hint embedded in the retryable error once the grace expires — callers
# get "client may still be loading; retry in ~Ns" instead of a bare
# "reached nobody".
REMOTE_RETRY_S = int(os.environ.get('GEV_REMOTE_RETRY_S', '5'))
CONFIRM_TOOLS = set(filter(None, os.environ.get(
    'GEV_CONFIRM_TOOLS', 'clear_annotations,control_cctv').split(',')))
MDDB_URL = os.environ.get('GEV_MDDB_URL', 'http://100.102.134.91:11023/v1')
OPS_COLLECTION = os.environ.get('GEV_OPS_COLLECTION', 'gev-ops-events')

# Compact copy of Ada's _CONFIRM_RE + negation veto (keep in sync —
# ada-pi backend/realtime_provider.py).
_CONFIRM_RE = re.compile(
    r"\b(yes|yeah|yep|yup|confirm(ed)?|go ahead|do it|sure|okay?|"
    r"approved?|proceed|absolutely|mhm|uh huh|sounds good)\b|"
    r"ใช่|ยืน\s*ยัน|ตก\s*ลง|เอา\s*เลย|ทำ\s*เลย|ได้\s*เลย|ทำ\s*ได้|โอเค|ออเค|เออ|อือ|"
    r"เริ่ม\s*เลย|จัดการ\s*เลย|ลอง\s*เลย|ต่อไป|จัด\s*ไป|เอา\s*สิ|ไป\s*เลย|"
    r"ทำ\s*ไป|เผยแพร่\s*เลย|ส่ง\s*เลย",
    re.IGNORECASE,
)
_CONFIRM_NEG_RE = re.compile(
    r"\b(no|nope|nah|not|don't|dont|do not|cancel|wait|hold on|stop)\b|"
    r"อย่า|หยุด|ยกเลิก|ไม่(?!ต้อง)",
    re.IGNORECASE,
)
_CONFIRM_QUESTION_RE = re.compile(r"[?？]\s*$|ไหม\s*$|มั้ย\s*$")
_CONFIRM_LEAD_WINDOW = 20
_CONFIRM_MAX_TURN = 60


def _user_affirmed(text: str) -> bool:
    """True when the user's last utterance affirms (same rules as Ada's
    gate: affirmation must lead or the turn must be short; an opening
    negation or a question-ending vetoes)."""
    text = (text or '').strip()
    if not text or _CONFIRM_QUESTION_RE.search(text):
        return False
    span = text if len(text) <= _CONFIRM_MAX_TURN else text[:_CONFIRM_LEAD_WINDOW]
    aff = _CONFIRM_RE.search(span)
    if not aff:
        return False
    neg = _CONFIRM_NEG_RE.search(span)
    return not (neg and neg.start() < aff.start())


def _needs_confirm(name: str, args: dict) -> bool:
    if name in CONFIRM_TOOLS:
        return True
    # annotate_map persists user-visible state only when asked to keep it
    return name == 'annotate_map' and bool(args.get('persist'))


def _ops_event(kind: str, detail: str, tool: str = '') -> None:
    """Fire-and-forget ops event; failure is log-only, never blocks."""
    try:
        body = json.dumps({
            'collection': OPS_COLLECTION,
            'key': f'gev-{kind}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}',
            'lang': 'en',
            'contentMd': detail,
            'meta': {'type': [kind], 'tool': [tool]},
        }).encode()
        req = urllib.request.Request(
            f'{MDDB_URL}/add', data=body,
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        log(f'ops event failed ({kind}): {e}')


async def pump_responses(session, websocket, state):
    """Forward model output to the client, enforcing guards on tool calls."""
    try:
        async for msg in session.receive():
            sc = msg.server_content
            if sc is not None:
                it = getattr(sc, 'input_transcription', None)
                if it and getattr(it, 'text', None):
                    state['user_text'] = it.text

            if msg.tool_call:
                blocked = []
                for call in (msg.tool_call.function_calls or []):
                    args = dict(call.args or {})
                    state['calls'] += 1
                    if state['calls'] > TURN_TOOL_BUDGET:
                        log(f'Guard: tool budget exceeded, dropped {call.name}')
                        blocked.append(types.FunctionResponse(
                            id=call.id, name=call.name,
                            response={'error': 'tool budget exceeded for this turn'}))
                        asyncio.ensure_future(asyncio.to_thread(
                            _ops_event, 'gev_budget_block',
                            f'tool budget ({TURN_TOOL_BUDGET}) exceeded; dropped {call.name}',
                            call.name))
                        continue
                    if _needs_confirm(call.name, args) and not _user_affirmed(state.get('user_text')):
                        log(f'Guard: {call.name} blocked — no user affirmation')
                        blocked.append(types.FunctionResponse(
                            id=call.id, name=call.name,
                            response={'error': 'confirmation required: ask the user, '
                                               'call again only if they affirm'}))
                        asyncio.ensure_future(asyncio.to_thread(
                            _ops_event, 'gev_confirm_block',
                            f'{call.name} blocked — last user turn did not affirm',
                            call.name))
                        continue
                    log(f'Tool call: {call.name}({args})')
                    try:
                        await websocket.send(json.dumps({
                            'type': 'function_call',
                            'id': call.id,
                            'name': call.name,
                            'args': args,
                        }))
                    except Exception:
                        pass
                if blocked:
                    try:
                        await session.send_tool_response(function_responses=blocked)
                    except Exception as e:
                        log(f'guard tool_response failed: {e}')

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
                state['calls'] = 0
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
                    wait_s: float = 0.0, pane: int | None = None,
                    grace_s: float = 0.0):
    """Send msg to matching clients. screen=None broadcasts to voice CLIENTS
    + every remote client; a number narrows remotes to that screen. pane=N
    further narrows to the Nth split-screen pane (clients that never
    announced a pane are treated as the whole screen / pane 0).
    With wait_s>0, collects tool_response frames for the call's id.
    With grace_s>0 and zero matching targets, keeps polling REMOTE/CLIENTS
    until one appears or the grace elapses — covers the freshly casted
    page still in frame-loading."""
    # screen=None broadcasts to voice CLIENTS + every remote; a screen
    # number targets ONLY remotes that announced that screen — voice
    # clients have no screen binding, so including them sends a
    # screen-targeted command to whichever GEV tab happens to be open
    # (2026-09-29: "fly screen 4 to Joburg" answered from a stale tab
    # parked on Austin).
    deadline = _loop.time() + max(0.0, grace_s)
    while True:
        remotes = [
            w for w, m in REMOTE.items()
            if (screen is None or m.get('screen') == screen)
            and (pane is None or m.get('pane') in (None, pane))]
        targets = remotes + (list(CLIENTS) if screen is None else [])
        if targets or _loop.time() >= deadline:
            break
        await asyncio.sleep(REMOTE_POLL_S)
    delivered = 0
    hit_screens = set()
    for ws in targets:
        try:
            await ws.send(msg)
            delivered += 1
            m = REMOTE.get(ws)
            if m and m.get('screen') is not None:
                hit_screens.add(m['screen'])
        except Exception:
            pass
    if wait_s <= 0 or not delivered:
        return delivered, [], sorted(hit_screens)
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
    return delivered, responses, sorted(hit_screens)


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
                                      1 for s in screens if s is None),
                                  'remotes': [{'screen': m.get('screen'),
                                               'pane': m.get('pane')}
                                              for m in REMOTE.values()]})
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
            try:
                screen = int(screen) if screen is not None else None
            except (TypeError, ValueError):
                pass  # unmatched screen type just never matches a remote
            pane = body.get('pane')
            pane = int(pane) if pane is not None else None
            # wait>0 collects the clients' tool_response frames — lets
            # get_current_view_state (and friends) actually answer.
            wait_s = min(float(body.get('wait') or 0), 10.0)
            args = body.get('args') or {}
            # Normalize nested-coordinate quirks — the model emits
            # {"location": {"latitude":…,"longitude":…}} instead of the
            # flat schema the client implements (seen live 2026-09-29:
            # every coord flight on the za-windsurf tour errored).
            loc = args.get('location')
            if isinstance(loc, dict):
                for k in ('latitude', 'longitude', 'lat', 'lon',
                          'rangeM', 'altM'):
                    if k in loc and k not in args:
                        args[k] = loc[k]
                args.pop('location', None)
            if 'lat' in args and 'latitude' not in args:
                args['latitude'] = args.pop('lat')
            if 'lon' in args and 'longitude' not in args:
                args['longitude'] = args.pop('lon')
            msg = json.dumps({
                'type': 'function_call',
                'id': 'cmd-' + uuid.uuid4().hex[:8],
                'name': name,
                'args': args,
            })
            # Grace: hold screen-targeted commands until a matching
            # remote registers — the common "cast nav succeeded, page
            # still loading" case then just works instead of failing.
            grace_s = REMOTE_GRACE_S if screen is not None else 0.0
            try:
                delivered, responses, hit = asyncio.run_coroutine_threadsafe(
                    _dispatch(msg, screen, wait_s, pane, grace_s),
                    _loop).result(timeout=wait_s + grace_s + 5)
            except Exception as e:
                return self._reply(502, {'error': str(e)})
            out = {'ok': True, 'delivered': delivered,
                   'delivered_screens': hit}
            if screen is not None and delivered == 0:
                out['ok'] = False
                out['retryable'] = True
                out['retry_after_s'] = REMOTE_RETRY_S
                out['error'] = (
                    f'no GEV remote on screen {screen} after {grace_s:.0f}s'
                    ' — client may still be loading; '
                    f'retry in ~{REMOTE_RETRY_S}s')
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
                    meta['pane'] = obj.get('pane')
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
            # user-side transcription feeds the confirm gate
            'input_audio_transcription': types.AudioTranscriptionConfig(),
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
            # Per-session guard state: last user utterance (confirm source)
            # + tool-call count this turn (storm budget).
            guard = {'user_text': '', 'calls': 0}
            pump = asyncio.create_task(pump_responses(session, websocket, guard))

            try:
                async for message in websocket:
                    if isinstance(message, str):
                        try:
                            obj = json.loads(message)
                            t = obj.get('type', '')
                            if t == 'end':
                                await session.send_client_content(turn_complete=True)
                            elif t == 'text':
                                # typed turns bypass input transcription —
                                # feed the confirm gate directly
                                guard['user_text'] = obj.get('text', '')
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
