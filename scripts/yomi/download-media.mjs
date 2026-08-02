import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';

const MEDIA_DIR = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/media';

const transport = new StdioClientTransport({
  command: '/usr/bin/node',
  args: ['/home/tony/.yomi/mcpb/run.mjs'],
  stderr: 'pipe',
});

const client = new Client({ name: 'yomi-media-download', version: '0.1' });
await client.connect(transport);
transport.stderr.on('data', () => {});

const MIME_TO_EXT = {
  'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
  'image/webp': 'webp', 'image/heic': 'heic', 'image/heif': 'heif',
  'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'video/3gpp': '3gp',
  'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/m4a': 'm4a', 'audio/ogg': 'ogg',
  'audio/aac': 'aac', 'audio/amr': 'amr',
  'application/pdf': 'pdf', 'application/zip': 'zip',
};

const EXT_TO_MIME = {
  jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', gif: 'image/gif',
  webp: 'image/webp', heic: 'image/heic', heif: 'image/heif',
  mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime', '3gp': 'video/3gpp',
  mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg', aac: 'audio/aac', amr: 'audio/amr',
  pdf: 'application/pdf', zip: 'application/zip',
};

function extFromMime(mime, fallback = 'bin') {
  if (!mime) return fallback;
  if (MIME_TO_EXT[mime]) return MIME_TO_EXT[mime];
  const tail = mime.split('/').pop().replace(/[^a-z0-9]/gi, '');
  return tail || fallback;
}

function extFromName(name) {
  if (!name || !name.includes('.')) return null;
  const ext = name.split('.').pop().replace(/[^a-z0-9]/gi, '');
  return ext || null;
}

function guessMime(part) {
  if (part.mimeType) return part.mimeType;
  if (part.resource?.mimeType) return part.resource.mimeType;
  const name = part.name || part.resource?.name;
  const ext = extFromName(name);
  if (ext && EXT_TO_MIME[ext.toLowerCase()]) return EXT_TO_MIME[ext.toLowerCase()];
  if (part.type === 'image') return 'image/jpeg';
  if (part.type === 'audio') return 'audio/m4a';
  return 'application/octet-stream';
}

async function downloadMedia(chatId, messageId) {
  const dir = `${MEDIA_DIR}/${chatId}`;
  mkdirSync(dir, { recursive: true });

  const cached = readdirSync(dir).find(f => f.startsWith(`${messageId}.`));
  if (cached) {
    const ext = cached.split('.').pop().toLowerCase();
    return { fileName: cached, mime: EXT_TO_MIME[ext] || 'application/octet-stream' };
  }

  const result = await client.callTool({ name: 'get_message_media', arguments: { chatId, messageId, preview: false } });
  const part = result.content?.[0];
  if (!part) throw new Error('empty media response');
  if (part.type === 'text') {
    return { unavailable: true, error: 'media unavailable' };
  }

  let buffer;
  let mime = guessMime(part);

  if (part.type === 'image' || part.type === 'audio') {
    if (!part.data) throw new Error(`no data in ${part.type} response`);
    buffer = Buffer.from(part.data, 'base64');
  } else if (part.type === 'resource' || part.blob) {
    const payload = part.data || part.blob;
    if (!payload) throw new Error('no data in resource response');
    buffer = Buffer.from(payload, 'base64');
    if (part.resource?.name) {
      const ext = extFromName(part.resource.name);
      if (ext) mime = EXT_TO_MIME[ext] || mime;
    }
  } else {
    throw new Error(`unsupported media type ${part.type}`);
  }

  const nameHint = part.name || part.resource?.name;
  const ext = extFromName(nameHint) || extFromMime(mime) || 'bin';
  const fileName = `${messageId}.${ext}`;
  const filePath = `${dir}/${fileName}`;
  writeFileSync(filePath, buffer);
  return { fileName, mime };
}

const [,, chatId, messageId] = process.argv;
if (!chatId || !messageId) {
  console.error(JSON.stringify({ error: 'Usage: node download-media.mjs <chatId> <messageId>' }));
  await client.close();
  process.exit(1);
}

try {
  const info = await downloadMedia(chatId, messageId);
  console.log(JSON.stringify(info));
  await client.close();
} catch (err) {
  const msg = err.message || String(err);
  const unavailable = /missing_decrypt_material|media unavailable|not available/i.test(msg);
  console.log(JSON.stringify({ unavailable, error: msg }));
  await client.close();
  process.exit(unavailable ? 0 : 1);
}
