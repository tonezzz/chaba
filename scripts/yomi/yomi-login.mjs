import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
import { readFileSync, existsSync } from 'node:fs';

const YOMI_MCP_PATH = '/home/tony/.yomi/mcpb/run.mjs';
const transport = new StdioClientTransport({ command: '/usr/bin/node', args: [YOMI_MCP_PATH] });
const client = new Client({ name: 'yomi-login', version: '0.1' });
await client.connect(transport);

const creds = existsSync('/home/tony/.local/share/yomi/line-credentials.json')
  ? JSON.parse(readFileSync('/home/tony/.local/share/yomi/line-credentials.json', 'utf8'))
  : {};
const phone = process.env.YOMI_PHONE || creds.line_phone;
const region = process.env.YOMI_REGION || creds.line_region;

if (!phone || !region) {
  console.error('Missing phone or region. Set YOMI_PHONE and YOMI_REGION or have line-credentials.json.');
  process.exit(1);
}

console.log('Starting LINE login with persisted phone/region...');
const loginRes = await client.callTool({ name: 'login', arguments: { phone, region } });
const loginText = loginRes.content?.[0]?.text ?? JSON.stringify(loginRes, null, 2);
console.log(loginText);

console.log('login_complete: waiting for approval on your primary phone...');
const completeRes = await client.callTool({ name: 'login_complete', arguments: {} });
const completeText = completeRes.content?.[0]?.text ?? JSON.stringify(completeRes, null, 2);
console.log('Login result:', completeText);
