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
    if (OPENAI_API_TYPE !== 'openai') {
      return new Response(
        JSON.stringify({ ok: false, error: 'stt_not_supported_for_api_type', apiType: OPENAI_API_TYPE }),
        { status: 501, headers: { 'Content-Type': 'application/json' } },
      );
    }

    const form = await req.formData();
    const file = (form.get('file') || form.get('audio')) as File | null;
    if (!file) {
      return new Response(JSON.stringify({ ok: false, error: 'missing_file' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const env = _env();
    const key = (form.get('key') as string | null) || env.OPENAI_API_KEY || '';
    if (!key) {
      return new Response(JSON.stringify({ ok: false, error: 'missing_api_key' }), {
        status: 501,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const model = ((form.get('model') as string | null) || env.OPENAI_STT_MODEL || 'whisper-1').trim();
    const language = ((form.get('language') as string | null) || env.OPENAI_STT_LANGUAGE || '').trim();

    const upstreamForm = new FormData();
    upstreamForm.set('file', file, (file as any).name || 'audio.webm');
    upstreamForm.set('model', model);
    if (language) {
      upstreamForm.set('language', language);
    }

    const upstream = await fetch(`${OPENAI_API_HOST}/v1/audio/transcriptions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${key}`,
      },
      body: upstreamForm,
    });

    if (!upstream.ok) {
      const errText = await upstream.text().catch(() => '');
      return new Response(
        JSON.stringify({ ok: false, error: 'upstream_error', status: upstream.status, body: errText }),
        { status: 502, headers: { 'Content-Type': 'application/json' } },
      );
    }

    const json = await upstream.json();
    const text = (json?.text || '').toString();

    return new Response(JSON.stringify({ ok: true, text }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: 'internal_error', detail: String(e?.message || e) }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

export default handler;
