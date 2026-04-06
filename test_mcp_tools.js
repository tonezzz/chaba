const http = require('http');

// First initialize
const initPayload = JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: {
    protocolVersion: '2024-11-05',
    capabilities: { tools: {} },
    clientInfo: { name: 'test', version: '1.0' }
  }
});

const makeRequest = (payload, sessionId = null) => {
  return new Promise((resolve, reject) => {
    const path = sessionId ? `/mcp?app=windsurf&sessionId=${sessionId}` : '/mcp?app=windsurf';
    const options = {
      hostname: '127.0.0.1',
      port: 3051,
      path: path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream'
      }
    };

    const req = http.request(options, (res) => {
      let responseData = '';
      res.on('data', (chunk) => {
        responseData += chunk;
      });
      res.on('end', () => {
        console.log('Raw response:', responseData);
        // Parse Server-Sent Events
        const lines = responseData.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.substring(6));
              console.log('Parsed data:', JSON.stringify(data, null, 2));
              if (data.result || data.error) {
                resolve(data);
                return;
              }
            } catch (e) {
              console.log('Failed to parse line:', line);
            }
          }
        }
        resolve({ error: 'No valid data found', debug: responseData });
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
};

async function testMCP() {
  try {
    const sessionId = 'test-session-' + Date.now();
    console.log('Using session ID:', sessionId);
    
    console.log('Initializing MCP session...');
    const initResult = await makeRequest(initPayload, sessionId);
    
    if (initResult.error) {
      console.error('Init failed:', initResult.error);
      return;
    }
    
    console.log('✅ Initialized successfully');

    // Now list tools
    console.log('Listing tools...');
    const toolsPayload = JSON.stringify({
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/list',
      params: {}
    });

    const toolsResult = await makeRequest(toolsPayload, sessionId);
    
    if (toolsResult.error) {
      console.error('Tools list failed:', toolsResult.error);
      return;
    }

    console.log('✅ Tools retrieved:');
    if (toolsResult.result && toolsResult.result.tools) {
      toolsResult.result.tools.forEach(tool => {
        console.log(`  - ${tool.name}`);
      });
    }

    // Test news tool
    console.log('Testing news tool...');
    const newsPayload = JSON.stringify({
      jsonrpc: '2.0',
      id: 3,
      method: 'tools/call',
      params: {
        name: 'news_1mcp_news_run',
        arguments: {
          start_at: 'fetch',
          stop_after: 'render'
        }
      }
    });

    const newsResult = await makeRequest(newsPayload, sessionId);
    
    if (newsResult.error) {
      console.error('News tool failed:', newsResult.error);
    } else {
      console.log('✅ News tool worked!');
      console.log('Result preview:', JSON.stringify(newsResult.result).substring(0, 200) + '...');
    }

  } catch (error) {
    console.error('Test failed:', error);
  }
}

testMCP();
