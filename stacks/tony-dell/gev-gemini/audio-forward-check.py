#!/usr/bin/env python3
# audio-forward-check — unit check that pump_responses forwards Gemini
# model_turn audio to the client websocket as binary frames.
#
# The bridge requests response_modalities=['AUDIO']; model speech arrives as
# server_content.model_turn.parts[*].inline_data.data (24 kHz PCM16 chunks).
# Before 2026-10-06 the pump forwarded only output_transcription text — the
# audio was decoded by google-genai and dropped, so the GEV page could not
# play anything no matter what the client did. This check pins the fix:
# inline audio -> binary ws frames, JSON control frames unchanged.
#
# google.genai and websockets are stubbed in sys.modules before import so
# the check runs anywhere (no Gemini key, no network, no pip deps).
#
#   python3 audio-forward-check.py
# Exit 0 = all checks passed, 1 = a check failed.
import asyncio
import json
import sys
import types as pytypes
from types import SimpleNamespace

# --- stub deps so bridge.py imports without google-genai / websockets ------
class _T:
    def __init__(self, *a, **kw):
        self.__dict__.update(kw)


_google = pytypes.ModuleType('google')
_genai = pytypes.ModuleType('google.genai')
_gtypes = pytypes.ModuleType('google.genai.types')
for name in ('FunctionDeclaration', 'Tool', 'FunctionResponse',
             'AudioTranscriptionConfig', 'Content', 'Part',
             'LiveConnectConfig', 'Blob'):
    setattr(_gtypes, name, type(name, (_T,), {}))
_genai.types = _gtypes
_genai.Client = object
_google.genai = _genai

_ws = pytypes.ModuleType('websockets')
_ws_exc = pytypes.ModuleType('websockets.exceptions')
_ws_exc.ConnectionClosed = type('ConnectionClosed', (Exception,), {})
_ws.exceptions = _ws_exc
_ws.serve = lambda *a, **kw: None

sys.modules.setdefault('google', _google)
sys.modules.setdefault('google.genai', _genai)
sys.modules.setdefault('google.genai.types', _gtypes)
sys.modules.setdefault('websockets', _ws)
sys.modules.setdefault('websockets.exceptions', _ws_exc)

sys.path.insert(0, __file__.rsplit('/', 1)[0])
import bridge  # noqa: E402

checks = []


def check(name, ok, detail=''):
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ''))
    checks.append(bool(ok))


class FakeWS:
    def __init__(self):
        self.frames = []

    async def send(self, data):
        self.frames.append(data)

    @property
    def binary(self):
        return [f for f in self.frames if isinstance(f, (bytes, bytearray))]

    @property
    def jsons(self):
        out = []
        for f in self.frames:
            if isinstance(f, str):
                out.append(json.loads(f))
        return out


class FakeSession:
    def __init__(self, msgs):
        self._msgs = msgs

    async def receive(self):
        for m in self._msgs:
            yield m
        # pump_responses iterates until the session ends


def msg(sc=None, tool_call=None):
    return SimpleNamespace(server_content=sc, tool_call=tool_call)


def sc(**kw):
    base = dict(input_transcription=None, interrupted=False,
                output_transcription=None, turn_complete=False,
                model_turn=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def main():
    pcm = b'\x00\x01\x02\x03' * 64  # fake 24 kHz PCM16 chunk

    ws = FakeWS()
    session = FakeSession([
        # two audio parts + one empty part in one model_turn
        msg(sc(model_turn=SimpleNamespace(parts=[
            SimpleNamespace(inline_data=SimpleNamespace(data=pcm)),
            SimpleNamespace(inline_data=None),
            SimpleNamespace(inline_data=SimpleNamespace(data=b'\xAA' * 32)),
        ]))),
        # transcription text still forwards as JSON
        msg(sc(output_transcription=SimpleNamespace(text='hello there'))),
        msg(sc(turn_complete=True)),
    ])
    await bridge.pump_responses(session, ws, {'user_text': '', 'calls': 0})

    check('model_turn audio forwarded as binary frames',
          ws.binary == [pcm, b'\xAA' * 32],
          f'{len(ws.binary)} binary frames')
    check('binary frames are verbatim PCM bytes',
          all(isinstance(f, bytes) for f in ws.binary))
    jsons = ws.jsons
    check('output_transcription still forwarded as {type:text}',
          {'type': 'text', 'text': 'hello there'} in jsons)
    check('turn_complete still forwarded as {type:done}',
          {'type': 'done'} in jsons)
    check('no audio leaked into JSON frames',
          all(pcm not in f.encode() for f in ws.frames if isinstance(f, str)))

    # interrupted turn: client must get the interrupted marker (it flushes
    # its playback queue) and no trailing audio from that message.
    ws2 = FakeWS()
    session2 = FakeSession([msg(sc(interrupted=True,
                                 model_turn=SimpleNamespace(parts=[
                                     SimpleNamespace(inline_data=SimpleNamespace(
                                         data=b'\xFF' * 8))])))])
    await bridge.pump_responses(session2, ws2, {'user_text': '', 'calls': 0})
    check('interrupted -> {type:interrupted} JSON sent',
          {'type': 'interrupted'} in ws2.jsons)

    # send-failure resilience: a client that dies mid-turn must not kill
    # the pump for the remaining parts of the same message.
    class HalfDeadWS(FakeWS):
        def __init__(self):
            super().__init__()
            self._failed = False

        async def send(self, data):
            if isinstance(data, (bytes, bytearray)) and not self._failed:
                self._failed = True
                raise RuntimeError('client gone')
            await super().send(data)

    ws3 = HalfDeadWS()
    session3 = FakeSession([msg(sc(model_turn=SimpleNamespace(parts=[
        SimpleNamespace(inline_data=SimpleNamespace(data=b'\x01')),
        SimpleNamespace(inline_data=SimpleNamespace(data=b'\x02')),
    ])))])
    try:
        await bridge.pump_responses(session3, ws3, {'user_text': '', 'calls': 0})
        check('send failure on one audio part does not kill the pump',
              ws3.binary == [b'\x02'], f'frames={ws3.frames!r}')
    except Exception as e:
        check('send failure on one audio part does not kill the pump',
              False, f'raised {e!r}')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        print(f'audio-forward-check: harness error: {e!r}')
        sys.exit(1)
    print(f"audio-forward-check: {'PASS' if all(checks) and checks else 'FAIL'}")
    sys.exit(0 if all(checks) and checks else 1)
