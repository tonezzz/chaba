const { McpServer } = require('@codeium/mcp');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

class IDC1Server extends McpServer {
  async initialize() {
    // Load configuration
    const configPath = path.join(process.cwd(), 'mcp_idc1_config.json');
    let config = {};
    
    try {
      config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    } catch (error) {
      console.warn(`Could not load config from ${configPath}, using environment variables`);
      config = {
        IDC1_API_URL: process.env.IDC1_API_URL,
        IDC1_API_KEY: process.env.IDC1_API_KEY
      };
    }

    if (!config.IDC1_API_URL || !config.IDC1_API_KEY) {
      throw new Error('Missing required configuration. Please set IDC1_API_URL and IDC1_API_KEY in mcp_idc1_config.json or environment variables');
    }

    this.client = axios.create({
      baseURL: config.IDC1_API_URL,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${config.IDC1_API_KEY}`
      }
    });
  }

  async getResources() {
    try {
      const response = await this.client.get('/resources');
      return response.data;
    } catch (error) {
      console.error('Error fetching resources:', error);
      throw error;
    }
  }

  // Add more methods as needed
}

module.exports = IDC1Server;
