import { Client } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '/home/tony/.yomi/mcpb/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';

const transport = new StdioClientTransport({
  command: '/usr/bin/node',
  args: ['/home/tony/.yomi/mcpb/run.mjs'],
});

const client = new Client({ name: 'yomi-send-message', version: '0.1' });
await client.connect(transport);

const chatId = process.argv[2];
const text = process.argv[3];

if (!chatId || !text) {
  console.error('Usage: send-message.mjs <chatId> <text>');
  process.exit(1);
}

try {
  const result = await client.callTool({
    name: 'send_message',
    arguments: { chatId, text }
  });
  console.log('Message sent successfully');
  process.exit(0);
} catch (err) {
  console.error('Failed to send message:', err.message);
  process.exit(1);
} finally {
  await client.close();
}
