export const config = {
  runtime: 'edge',
};

import { OPENAI_API_HOST, OPENAI_API_TYPE } from '@/utils/app/const';

const _env = () => (globalThis as any)?.process?.env || {};

const handler = async (req: Request): Promise<Response> => {
  if (req.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  try {
    const body = (await req.json()) as {
      text?: string;
      voice?: string;
      model?: string;
      format?: string;
      key?: string;
    };

    const text = (body.text || '').trim();
    if (!text) {
      return new Response(JSON.stringify({ ok: false, error: 'missing_text' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    if (OPENAI_API_TYPE !== 'openai') {
      return new Response(
        JSON.stringify({ ok: false, error: 'tts_not_supported_for_api_type', apiType: OPENAI_API_TYPE }),
        { status: 501, headers: { 'Content-Type': 'application/json' } },
      );
    }

    const env = _env();
    const key = body.key || env.OPENAI_API_KEY || '';
    if (!key) {
      return new Response(JSON.stringify({ ok: false, error: 'missing_api_key' }), {
        status: 501,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const voice = (body.voice || env.OPENAI_TTS_VOICE || 'alloy').trim();
    const model = (body.model || env.OPENAI_TTS_MODEL || 'gpt-4o-mini-tts').trim();
    const format = (body.format || 'mp3').trim();

    const upstream = await fetch(`${OPENAI_API_HOST}/v1/audio/speech`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify({
        model,
        voice,
        input: text,
        format,
      }),
    });

    if (!upstream.ok) {
      const errText = await upstream.text().catch(() => '');
      return new Response(
        JSON.stringify({ ok: false, error: 'upstream_error', status: upstream.status, body: errText }),
        { status: 502, headers: { 'Content-Type': 'application/json' } },
      );
    }

    const audioBuf = await upstream.arrayBuffer();
    const contentType = upstream.headers.get('content-type') || 'audio/mpeg';

    return new Response(audioBuf, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'no-store',
      },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: 'internal_error', detail: String(e?.message || e) }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

export default handler;
