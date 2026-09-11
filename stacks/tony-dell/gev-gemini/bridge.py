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
MODEL = os.environ.get('GEV_GEMINI_MODEL', 'gemini-3.1-flash-live-preview')

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


async def client_handler(websocket):
    log(f'Client connected {websocket.remote_address}')
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
    log('Client disconnected')


async def main():
    async with websockets.serve(client_handler, HOST, PORT):
        log(f'Bridge on ws://{HOST}:{PORT}')
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
