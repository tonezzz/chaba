import asyncio, base64, datetime, json, os, re, sys, traceback, urllib.request
import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers
from google import genai
from google.genai import types
from google.genai.live import mcp_to_gemini_tool
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

WWW = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(WWW, 'session.json')
CONFIG_FILE = '/config/.storage/core.config_entries'


def log(msg):
    print(msg, flush=True)


def parse_pcm_rate(mime_type):
    if not mime_type:
        return 16000
    m = re.search(r'rate=(\d+)', mime_type)
    return int(m.group(1)) if m else 16000


def load_session_handle():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE) as f:
                return json.load(f).get('handle')
        except Exception as e:
            log(f'failed to load session handle: {e}')
    return None


def save_session_handle(handle, resumable=True):
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump({'handle': handle or '', 'resumable': resumable}, f)
    except Exception as e:
        log(f'failed to save session handle: {e}')


def load_creds():
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    api_key = [e for e in cfg['data']['entries'] if e['domain'] == 'google_generative_ai_conversation'][0]['data']['api_key']
    ha = [e for e in cfg['data']['entries'] if e['domain'] == 'ha_mcp_tools'][0]
    return api_key, f'http://127.0.0.1:9584{ha["data"]["secret_path"]}'


def build_context_text(token):
    """Compact snapshot of controllable device states, fetched fresh each turn.

    Replaces the previous hardcoded two-switch list so renamed or added
    devices are picked up automatically.
    """
    try:
        states = fetch_ha_states(token)
    except Exception as e:
        return f'Device states unavailable: {e}'
    lines = []
    for s in states:
        eid = s['entity_id']
        domain = eid.split('.', 1)[0]
        if domain not in ('switch', 'light', 'media_player', 'input_boolean'):
            continue
        name = (s.get('attributes') or {}).get('friendly_name', eid)
        lines.append(f'{eid} ({name}) = {s["state"]}')
    return 'Current device states:\n' + '\n'.join(lines[:80])


CAST_SERVER = 'http://127.0.0.1:8799/cmd'

# Local tools executed directly by the bridge — flat, enum-constrained schemas
# so the model picks them precisely instead of nesting MCP proxy calls.
LOCAL_TOOL_DECLS = [
    {
        'name': 'tv_command',
        'description': (
            'Control the TV cast display: navigate to a page, scroll, go back, '
            'stop casting, or show the camera. Use this whenever the user asks '
            'to cast, show, scroll, go back/home, stop the TV, or view the camera.'
        ),
        'parameters': {
            'type': 'OBJECT',
            'properties': {
                'cmd': {
                    'type': 'STRING',
                    'enum': ['nav', 'scroll', 'back', 'stop', 'camera'],
                    'description': 'Action to perform on the TV display.',
                },
                'arg': {
                    'type': 'STRING',
                    'description': (
                        'Required for nav (smart-home, dossier, photos, youtube, '
                        'map, panel, help) and scroll (up, down, left, right). '
                        'Empty for back, stop, camera.'
                    ),
                },
            },
            'required': ['cmd'],
        },
    },
    {
        'name': 'photo_slideshow',
        'description': (
            'Control the photo slideshow on the TV: next or previous photo, '
            'or pause and resume the slideshow.'
        ),
        'parameters': {
            'type': 'OBJECT',
            'properties': {
                'action': {
                    'type': 'STRING',
                    'enum': ['next', 'previous', 'pause', 'resume'],
                    'description': 'Slideshow action.',
                },
            },
            'required': ['action'],
        },
    },
]


def _post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def _ha_service(token, domain, service, data):
    req = urllib.request.Request(
        f'{HA_URL}/api/services/{domain}/{service}',
        data=json.dumps(data).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def execute_local_tool(name, args, token):
    """Run a bridge-local tool deterministically; returns a result dict."""
    try:
        if name == 'tv_command':
            cmd = (args.get('cmd') or '').strip()
            arg = (args.get('arg') or '').strip()
            if cmd == 'stop':
                status = _ha_service(token, 'media_player', 'turn_off',
                                     {'entity_id': 'media_player.tony_tv_cast'})
                return {'result': f'TV off (HTTP {status})'}
            if cmd == 'camera':
                status = _ha_service(token, 'camera', 'play_stream', {
                    'entity_id': 'camera.ip_cam_65',
                    'media_player': 'media_player.tony_tv_cast',
                    'format': 'hls',
                })
                return {'result': f'Camera streaming (HTTP {status})'}
            if cmd in ('nav', 'scroll', 'back'):
                payload = {'cmd': cmd, 'text': arg, 'selector': '', 'role': ''}
                status = _post_json(CAST_SERVER, payload)
                return {'result': f'{cmd} {arg} sent (HTTP {status})'}
            return {'error': f'unknown tv_command cmd: {cmd}'}
        if name == 'photo_slideshow':
            action = (args.get('action') or '').strip()
            if action == 'next':
                status = _ha_service(token, 'button', 'press',
                                     {'entity_id': 'button.album_slideshow_google_photos_next_slide'})
            elif action == 'previous':
                status = _ha_service(token, 'button', 'press',
                                     {'entity_id': 'button.album_slideshow_google_photos_previous_slide'})
            elif action == 'pause':
                status = _ha_service(token, 'switch', 'turn_on',
                                     {'entity_id': 'switch.album_slideshow_google_photos_pause_slideshow'})
            elif action == 'resume':
                status = _ha_service(token, 'switch', 'turn_off',
                                     {'entity_id': 'switch.album_slideshow_google_photos_pause_slideshow'})
            else:
                return {'error': f'unknown slideshow action: {action}'}
            return {'result': f'slideshow {action} (HTTP {status})'}
        return {'error': f'unknown local tool: {name}'}
    except Exception as e:
        return {'error': f'{name} failed: {e}'}


# TV / cast commands handled by the dedicated tv_command / photo_slideshow tools.
TV_INSTRUCTION = (
    'TV control: ALWAYS use the tv_command tool for casting pages, scrolling, '
    'going back, stopping the TV, or showing the camera, and the photo_slideshow '
    'tool for next/previous/pause/resume. Never use ha_call_service for these. '
    'Examples: "cast the photos" -> tv_command(cmd="nav", arg="photos"); '
    '"scroll down" -> tv_command(cmd="scroll", arg="down"); '
    '"go back" -> tv_command(cmd="back"); '
    '"stop the tv" -> tv_command(cmd="stop"); '
    '"cast the camera" -> tv_command(cmd="camera"); '
    '"next photo" -> photo_slideshow(action="next"); '
    '"pause the slideshow" -> photo_slideshow(action="pause").'
)

SYSTEM_BASE = (
    'You are a concise Home Assistant voice assistant. Keep replies short, natural '
    'for speech; no markdown, lists, or bullet points. Answer questions from the '
    'device states provided. For device on/off or state changes, call '
    'ha_call_write_tool(name="ha_call_service", arguments={"domain": DOMAIN, '
    '"service": "turn_on"/"turn_off", "service_data": {"entity_id": "..."}}). '
    'The user may speak English or Thai; answer in the language they used.'
)


HA_URL = 'http://127.0.0.1:8123'

# Ordered search patterns for each snapshot panel. Earlier patterns win.
# These support both Sunsynk-style IDs (sensor.sunsynk_*, sensor.batteries_1_*,
# sensor.inverters_1_*) and the current tony-dell test sensors.
PANEL_PATTERNS = {
    'battery': [
        r'battery.*(soc|state_of_charge|level)',
        r'batteries.*state_of_charge',
        r'battery.*power',
        r'batteries.*power',
    ],
    'solar': [
        r'sensor\..*pv.*power',
        r'pv.*power',
        r'solar.*power',
        r'inverters.*pv_power',
    ],
    'power': [
        r'sensor\..*load.*power',
        r'load.*power',
        r'inverters.*load_power',
        r'sensor\..*grid.*power',
        r'grid.*power',
        r'inverters.*grid_power',
        r'sensor\..*_power',
        r'.*_power',
    ],
    'grid_voltage': [
        r'sensor\..*grid.*voltage',
        r'grid.*voltage',
        r'inverters.*grid_voltage',
        r'sensor\..*_voltage',
        r'.*_voltage',
    ],
}


def fetch_ha_states(token):
    req = urllib.request.Request(
        f'{HA_URL}/api/states',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def find_first(states, patterns, exclude=None):
    exclude = set(exclude or [])
    for eid, s in states.items():
        if eid in exclude:
            continue
        if not eid.startswith('sensor.'):
            continue
        for pat in patterns:
            if re.search(pat, eid):
                return eid, s
    return None, None


def fmt(s):
    if not s:
        return '—'
    unit = (s.get('attributes') or {}).get('unit_of_measurement', '')
    return f'{s["state"]}{unit}'.strip()


def build_snapshot(token):
    states = {s['entity_id']: s for s in fetch_ha_states(token)}

    used = set()
    battery_soc_eid, battery_soc = find_first(states, PANEL_PATTERNS['battery'], exclude=used)
    if battery_soc_eid:
        used.add(battery_soc_eid)

    battery_power_eid, battery_power = find_first(states, PANEL_PATTERNS['battery'], exclude=used)
    if battery_power_eid:
        used.add(battery_power_eid)

    pv_eid, pv = find_first(states, PANEL_PATTERNS['solar'], exclude=used)
    if pv_eid:
        used.add(pv_eid)

    load_eid, load = find_first(states, PANEL_PATTERNS['power'], exclude=used)
    if load_eid:
        used.add(load_eid)

    grid_eid, grid = find_first(states, PANEL_PATTERNS['power'], exclude=used)
    if grid_eid:
        used.add(grid_eid)

    grid_volt_eid, grid_volt = find_first(states, PANEL_PATTERNS['grid_voltage'], exclude=used)
    if grid_volt_eid:
        used.add(grid_volt_eid)

    entities = []
    for eid, s in states.items():
        if eid in used:
            unit = (s.get('attributes') or {}).get('unit_of_measurement', '')
            entities.append({'entity_id': eid, 'state': s['state'], 'attributes': s.get('attributes', {}), 'unit': unit})

    return {
        'updated': datetime.datetime.now().isoformat(),
        'entities': entities,
        'panels': {
            'battery': f'Battery {fmt(battery_soc)}  {fmt(battery_power)}',
            'solar': f'Solar {fmt(pv)}',
            'power': f'Load {fmt(load)}  Grid {fmt(grid)}  {fmt(grid_volt)}',
        }
    }


async def process_request(connection, request):
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        return None
    if request.path == '/':
        with open(os.path.join(WWW, 'index.html'), 'rb') as f:
            body = f.read()
        return Response(200, 'OK', Headers({'Content-Type': 'text/html', 'Connection': 'close', 'Cache-Control': 'no-store, no-cache, must-revalidate'}), body)
    if request.path in ('/snapshot', '/snapshot.json'):
        token = os.environ.get('HA_LONG_LIVED_TOKEN')
        if not token:
            body = json.dumps({'error': 'HA_LONG_LIVED_TOKEN not set'}).encode()
            return Response(500, 'Internal Server Error', Headers({'Content-Type': 'application/json', 'Connection': 'close'}), body)
        try:
            snapshot = await asyncio.to_thread(build_snapshot, token)
            body = json.dumps(snapshot).encode()
            return Response(200, 'OK', Headers({
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Cache-Control': 'no-store, no-cache, must-revalidate',
                'Connection': 'close',
            }), body)
        except Exception as e:
            log(f'snapshot error: {e}')
            body = json.dumps({'error': str(e)}).encode()
            return Response(500, 'Internal Server Error', Headers({
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Connection': 'close',
            }), body)
    return None


async def end_turn(session, websocket):
    """Inject fresh device context and close the current audio input turn."""
    token = os.environ.get('HA_LONG_LIVED_TOKEN')
    ctx = await asyncio.to_thread(build_context_text, token)
    await session.send_realtime_input(
        text=ctx + '\nUse the device states above to answer or act via tools.'
    )
    await session.send_realtime_input(audio_stream_end=True)
    log('Turn ended by client (audio_stream_end sent)')


async def pump_responses(session, mcp, websocket):
    """Continuously forward model output to the client and execute tool calls.

    Runs for the lifetime of the session so VAD-completed turns and
    interruptions (barge-in) are handled even while mic audio is streaming.
    """
    texts = []
    tool_texts = []
    try:
        async for msg in session.receive():
            if msg.session_resumption_update:
                sru = msg.session_resumption_update
                log(f'session resumable={sru.resumable}, new_handle={sru.new_handle[:20] if sru.new_handle else None}')
                if sru.resumable:
                    save_session_handle(sru.new_handle)

            if msg.go_away:
                # Server will terminate the session soon; the saved handle keeps
                # context alive for the next connection.
                log(f'go_away received, time_left={msg.go_away.time_left}')

            if msg.tool_call:
                for call in (msg.tool_call.function_calls or []):
                    log(f'Tool call: {call.name}({call.args})')
                    if call.name in {d['name'] for d in LOCAL_TOOL_DECLS}:
                        token = os.environ.get('HA_LONG_LIVED_TOKEN')
                        resp = await asyncio.to_thread(
                            execute_local_tool, call.name, dict(call.args or {}), token
                        )
                        log(f'local tool {call.name}: {resp}')
                        if 'error' in resp:
                            tool_texts.append(f'{call.name} failed')
                        else:
                            tool_texts.append(f'{call.name} OK')
                        await session.send_tool_response(
                            function_responses=[types.FunctionResponse(
                                id=call.id, name=call.name, response=resp,
                            )]
                        )
                        continue
                    try:
                        result = await mcp.call_tool(call.name, call.args or {})
                        result_text = result.content[0].text if result.content else 'no output'
                        if result.isError:
                            tool_texts.append(f'{call.name} failed')
                            resp = {'error': result_text}
                        else:
                            tool_texts.append(f'{call.name} OK')
                            resp = {'result': result_text}
                    except Exception as e:
                        tool_texts.append(f'{call.name} error: {e}')
                        resp = {'error': str(e)}
                    await session.send_tool_response(
                        function_responses=[types.FunctionResponse(
                            id=call.id,
                            name=call.name,
                            response=resp,
                        )]
                    )

            sc = msg.server_content
            if not sc:
                continue

            if getattr(sc, 'interrupted', False):
                # User barged in while the model was speaking.
                texts = []
                log('Model output interrupted by user')
                try:
                    await websocket.send(json.dumps({'type': 'interrupted'}))
                except Exception:
                    pass
                continue

            ot = getattr(sc, 'output_transcription', None)
            if ot and getattr(ot, 'text', None):
                texts.append(ot.text)
                try:
                    await websocket.send(json.dumps({'type': 'text', 'text': ot.text}))
                except Exception:
                    pass

            for part in (sc.model_turn or []):
                for p in (getattr(part, 'parts', []) or []):
                    if p.text is not None:
                        texts.append(p.text)
                        try:
                            await websocket.send(json.dumps({'type': 'text', 'text': p.text}))
                        except Exception:
                            pass
                    if p.inline_data is not None and p.inline_data.data:
                        try:
                            await websocket.send(json.dumps({
                                'type': 'audio',
                                'mime_type': p.inline_data.mime_type,
                                'data': base64.b64encode(p.inline_data.data).decode(),
                            }))
                        except Exception:
                            pass

            if sc.turn_complete:
                reply = ' '.join(texts) if texts else (' '.join(tool_texts) if tool_texts else 'Done.')
                try:
                    await websocket.send(json.dumps({'type': 'done', 'text': reply}))
                except Exception:
                    pass
                log(f'Turn complete, response: {reply[:100]}')
                texts = []
                tool_texts = []
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log(f'response pump ended: {e}')
        try:
            await websocket.send(json.dumps({'type': 'error', 'message': f'session ended: {e}'}))
        except Exception:
            pass


async def client_handler(websocket):
    log(f'Client connected {websocket.remote_address}')
    try:
        api_key, mcp_url = load_creds()
        client = genai.Client(api_key=api_key)

        async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as mcp:
                await mcp.initialize()
                tools = [mcp_to_gemini_tool(t) for t in (await mcp.list_tools()).tools]
                # Flat, deterministic local tools — higher selection precision
                # than nested MCP proxy calls for common TV/photo commands.
                tools.append(types.Tool(function_declarations=[
                    types.FunctionDeclaration(**decl) for decl in LOCAL_TOOL_DECLS
                ]))
                log(f'Loaded {len(tools) - len(LOCAL_TOOL_DECLS)} HA-MCP tools + {len(LOCAL_TOOL_DECLS)} local tools')

                # Build the system instruction once per connection with a live
                # snapshot of controllable devices (no hardcoded entity IDs).
                token = os.environ.get('HA_LONG_LIVED_TOKEN')
                ctx = await asyncio.to_thread(build_context_text, token)
                system_instruction = SYSTEM_BASE + '\n' + TV_INSTRUCTION + '\n' + ctx

                config = types.LiveConnectConfig(
                    response_modalities=['AUDIO'],
                    tools=tools,
                    output_audio_transcription=types.AudioTranscriptionConfig(),
                    input_audio_transcription=types.AudioTranscriptionConfig(),
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name='Puck')
                        )
                    ),
                    system_instruction=system_instruction,
                    # Resume the previous session when possible so context survives reconnects.
                    session_resumption=types.SessionResumptionConfig(handle=load_session_handle()),
                    # Realtime streaming input: each turn covers only detected speech activity,
                    # which suits push-to-talk clients.
                    realtime_input_config=types.RealtimeInputConfig(
                        turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY
                    ),
                )

                try:
                    live_ctx = client.aio.live.connect(
                        model='gemini-3.1-flash-live-preview',
                        config=config,
                    )
                    session = await live_ctx.__aenter__()
                except websockets.exceptions.ConnectionClosedError as e:
                    # A stale resumption handle causes 'session not found';
                    # drop it and reconnect fresh.
                    if 'session not found' in str(e) and config.session_resumption:
                        log('stale resumption handle, reconnecting fresh')
                        save_session_handle(None)
                        config.session_resumption = types.SessionResumptionConfig()
                        live_ctx = client.aio.live.connect(
                            model='gemini-3.1-flash-live-preview',
                            config=config,
                        )
                        session = await live_ctx.__aenter__()
                    else:
                        raise
                try:
                    log('Gemini Live session connected')
                    await websocket.send(json.dumps({'type': 'status', 'message': 'connected'}))

                    # Responses are pumped for the whole session so VAD-completed
                    # turns and barge-in interruptions work even while mic audio
                    # is still streaming in.
                    pump = asyncio.create_task(pump_responses(session, mcp, websocket))

                    audio_bytes = 0

                    try:
                        async for message in websocket:
                            if isinstance(message, str):
                                try:
                                    obj = json.loads(message)
                                    if obj.get('type') == 'end':
                                        log(f'Received end from client, total audio bytes {audio_bytes}')
                                        audio_bytes = 0
                                        try:
                                            await end_turn(session, websocket)
                                        except Exception as e:
                                            log(f'end_turn error: {e}')
                                            await websocket.send(json.dumps({'type': 'error', 'message': f'end turn: {e}'}))
                                    elif obj.get('type') == 'text':
                                        # Typed input: send as a complete user turn.
                                        await session.send_client_content(
                                            turns=types.Content(
                                                role='user',
                                                parts=[types.Part(text=obj.get('text', ''))],
                                            ),
                                            turn_complete=True,
                                        )
                                    else:
                                        log(f'Text from client: {message}')
                                except Exception:
                                    log(f'Text from client: {message}')
                                continue
                            # Stream each PCM chunk straight into the Live session
                            # (realtime input) instead of buffering the whole turn.
                            audio_bytes += len(message)
                            try:
                                await session.send_realtime_input(
                                    audio=types.Blob(data=message, mime_type='audio/pcm;rate=16000')
                                )
                            except Exception as e:
                                log(f'realtime audio send error: {e}')
                    except websockets.exceptions.ConnectionClosed:
                        pass
                    finally:
                        pump.cancel()
                finally:
                    await live_ctx.__aexit__(None, None, None)
    except Exception as e:
        log(f'client_handler setup error: {e}')
        log(traceback.format_exc())
        try:
            await websocket.send(json.dumps({'type': 'error', 'message': f'setup: {e}'}))
        except Exception:
            pass
    log('Client disconnected')


async def main():
    async with websockets.serve(client_handler, '0.0.0.0', 9005, process_request=process_request):
        log('Bridge on http://0.0.0.0:9005')
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
