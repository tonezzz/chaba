export const config = {
  runtime: 'edge',
};

const handler = async (req: Request): Promise<Response> => {
  if (req.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  try {
    const form = await req.formData();
    const file = (form.get('file') || form.get('attachment')) as File | null;
    if (!file) {
      return new Response(JSON.stringify({ ok: false, error: 'missing_file' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const filename = (file as any).name || 'attachment';
    const mimeType = file.type || 'application/octet-stream';
    const buf = await file.arrayBuffer();

    let binary = '';
    const bytes = new Uint8Array(buf);
    // Avoid spreading Uint8Array into String.fromCharCode (breaks with es5 target).
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    const b64 = btoa(binary);

    const dataUrl = `data:${mimeType};base64,${b64}`;

    const isImage = mimeType.startsWith('image/');
    const markdown = isImage ? `![${filename}](${dataUrl})` : `[${filename}](${dataUrl})`;

    return new Response(
      JSON.stringify({ ok: true, filename, mimeType, size: bytes.length, dataUrl, markdown }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
      },
    );
  } catch (e: any) {
    return new Response(JSON.stringify({ ok: false, error: 'internal_error', detail: String(e?.message || e) }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};

export default handler;
