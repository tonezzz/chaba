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


async def get_state_text(mcp):
    states = []
    for eid in ['switch.plalhawetiiyng_local', 'switch.plakkaaaef_local']:
        try:
            r = await mcp.call_tool('ha_call_read_tool', {'name': 'ha_get_state', 'arguments': {'entity_id': eid}})
            data = json.loads(r.content[0].text)['data']
            states.append(f'{eid} is {data["state"]}')
        except Exception as e:
            states.append(f'{eid} unknown ({e})')
    return 'Current states: ' + '; '.join(states)


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


async def handle_audio(session, mcp, pcm_bytes, websocket):
    state_text = await get_state_text(mcp)
    log(state_text)
    prompt = (
        state_text + '\n'
        'Answer status from the current states. For on/off, call ha_call_write_tool(name="ha_call_service", arguments={"domain": "switch", "service": "turn_on" or "turn_off", "entity_id": "..."}).'
    )
    log(f'Sending {len(pcm_bytes)} bytes PCM to Gemini Live')
    await session.send_client_content(
        turns=types.Content(
            role='user',
            parts=[
                types.Part(text=prompt),
                types.Part(inline_data=types.Blob(data=pcm_bytes, mime_type='audio/pcm;rate=16000')),
            ],
        ),
    )

    texts = []
    tool_texts = []
    audio_parts = []
    audio_mime = None
    log('Waiting for Gemini response...')
    async for msg in session.receive():
        if msg.session_resumption_update:
            sru = msg.session_resumption_update
            log(f'session resumable={sru.resumable}, new_handle={sru.new_handle[:20] if sru.new_handle else None}')
            if sru.resumable:
                save_session_handle(sru.new_handle)

        log(f'Received message: tool_call={msg.tool_call is not None}, server_content={msg.server_content is not None}')
        if msg.tool_call:
            for call in msg.tool_call.function_calls:
                log(f'Tool call: {call.name}({call.args})')
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
                    function_responses=types.FunctionResponse(
                        id=call.id,
                        name=call.name,
                        response=resp,
                    )
                )

        if not msg.server_content:
            continue

        ot = getattr(msg.server_content, 'output_transcription', None)
        if ot and getattr(ot, 'text', None):
            texts.append(ot.text)
            try:
                await websocket.send(json.dumps({'type': 'text', 'text': ot.text}))
            except Exception:
                pass

        for part in (msg.server_content.model_turn or []):
            for p in (getattr(part, 'parts', []) or []):
                if p.text is not None:
                    texts.append(p.text)
                    try:
                        await websocket.send(json.dumps({'type': 'text', 'text': p.text}))
                    except Exception:
                        pass
                if p.inline_data is not None and p.inline_data.data:
                    log(f'Audio output part: {len(p.inline_data.data)} bytes, mime={p.inline_data.mime_type}')
                    audio_parts.append(p.inline_data.data)
                    audio_mime = p.inline_data.mime_type or audio_mime
                    try:
                        await websocket.send(json.dumps({
                            'type': 'audio',
                            'mime_type': p.inline_data.mime_type,
                            'data': base64.b64encode(p.inline_data.data).decode(),
                        }))
                    except Exception:
                        pass

        if msg.server_content.turn_complete:
            log('Turn complete')
            break

    reply = ' '.join(texts) if texts else (' '.join(tool_texts) if tool_texts else 'Done.')
    try:
        await websocket.send(json.dumps({'type': 'done', 'text': reply}))
    except Exception:
        pass
    log(f'Sent final text response: {reply[:100]}')


async def client_handler(websocket):
    log(f'Client connected {websocket.remote_address}')
    try:
        api_key, mcp_url = load_creds()
        client = genai.Client(api_key=api_key)

        async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as mcp:
                await mcp.initialize()
                tools = [mcp_to_gemini_tool(t) for t in (await mcp.list_tools()).tools]
                log(f'Loaded {len(tools)} HA-MCP tools')

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
                    system_instruction='''Concise HA voice assistant. Answer status from the current states provided in the user message. For on/off, call ha_call_write_tool(name="ha_call_service", arguments={"domain": "switch", "service": "turn_on" or "turn_off", "entity_id": "..."}). Switches: switch.plalhawetiiyng_local, switch.plakkaaaef_local.''',
                )

                async with client.aio.live.connect(
                    model='gemini-3.1-flash-live-preview',
                    config=config,
                ) as session:
                    log('Gemini Live session connected')
                    await websocket.send(json.dumps({'type': 'status', 'message': 'connected'}))

                    audio_parts = []

                    try:
                        async for message in websocket:
                            if isinstance(message, str):
                                try:
                                    obj = json.loads(message)
                                    if obj.get('type') == 'end':
                                        log(f'Received end from client, total audio bytes {sum(len(b) for b in audio_parts)}')
                                        pcm = b''.join(audio_parts)
                                        audio_parts = []
                                        try:
                                            await asyncio.wait_for(handle_audio(session, mcp, pcm, websocket), 60)
                                        except asyncio.TimeoutError:
                                            log('Gemini response timeout')
                                            await websocket.send(json.dumps({'type': 'error', 'message': 'Gemini response timeout'}))
                                        except Exception as e:
                                            log(f'handle_audio error: {e}')
                                            await websocket.send(json.dumps({'type': 'error', 'message': f'server error: {e}'}))
                                    else:
                                        log(f'Text from client: {message}')
                                except Exception:
                                    log(f'Text from client: {message}')
                                continue
                            audio_parts.append(message)
                    except websockets.exceptions.ConnectionClosed:
                        pass
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
