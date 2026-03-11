const axios = require('axios');
const fs = require('fs');
const path = require('path');

async function testConnection() {
  try {
    // Load configuration
    const configPath = path.join(process.cwd(), 'mcp_idc1_config.json');
    const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));

    console.log('Testing connection to:', config.IDC1_API_URL);
    
    const client = axios.create({
      baseURL: config.IDC1_API_URL,
      timeout: 5000,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${config.IDC1_API_KEY}`
      }
    });

    console.log('Sending test request...');
    const response = await client.get('/');  // Try root endpoint or a known endpoint
    
    console.log('Connection successful!');
    console.log('Status:', response.status);
    console.log('Response:', response.data);
  } catch (error) {
    console.error('Connection test failed:');
    if (error.response) {
      // The request was made and the server responded with a status code
      console.log('Status:', error.response.status);
      console.log('Data:', error.response.data);
    } else if (error.request) {
      // The request was made but no response was received
      console.log('No response received. Check if the server is running and accessible.');
      console.log('Error:', error.message);
    } else {
      // Something happened in setting up the request
      console.log('Error:', error.message);
    }
  }
}

testConnection();
