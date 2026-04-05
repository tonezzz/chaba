#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  {
    name: "mcp-news",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "news_help",
        description: "Get help with news operations",
        inputSchema: {
          type: "object",
          properties: {},
        },
      },
      {
        name: "news_run",
        description: "Run news pipeline",
        inputSchema: {
          type: "object",
          properties: {
            start_at: {
              type: "string",
              enum: ["fetch", "process", "render"],
              description: "Where to start the pipeline",
            },
            stop_after: {
              type: "string",
              enum: ["fetch", "process", "render"],
              description: "Where to stop the pipeline",
            },
          },
          required: ["start_at", "stop_after"],
        },
      },
    ],
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "news_help":
        return {
          content: [
            {
              type: "text",
              text: `News MCP Server Tools:

1. news_help - Show this help message
2. news_run - Run news pipeline
   - start_at: "fetch" | "process" | "render"
   - stop_after: "fetch" | "process" | "render"

Example: Run full pipeline
  news_run(start_at="fetch", stop_after="render")

The news pipeline fetches RSS feeds, processes articles, and generates a brief summary.`,
            },
          ],
        };

      case "news_run":
        const { start_at, stop_after } = args as any;
        
        // Simple mock implementation
        const mockBrief = `
📰 **News Brief** - ${new Date().toLocaleDateString()}

• Technology: Major AI breakthrough announced in natural language processing
• Business: Stock markets show positive trends amid economic recovery
• Science: New discoveries in renewable energy research
• Health: Medical advances in personalized medicine treatments

*This is a mock news brief for testing purposes.*
        `.trim();

        return {
          content: [
            {
              type: "text",
              text: `News pipeline completed: ${start_at} → ${stop_after}\n\n${mockBrief}`,
            },
          ],
          brief: mockBrief,
        };

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Unknown error";
    return {
      content: [
        {
          type: "text",
          text: `Error: ${errorMessage}`,
        },
      ],
      isError: true,
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP News server running on stdio");
}

main().catch((error) => {
  console.error("Server error:", error);
  process.exit(1);
});
