import cors from "cors";
import express from "express";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { promises as fs } from "node:fs";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { InMemoryEventStore } from "@modelcontextprotocol/sdk/examples/shared/inMemoryEventStore.js";
import { z } from "zod";

const APP_NAME = "mcp-memory";
const APP_VERSION = "0.1.0";

const PORT = Number(process.env.PORT || 8470);
const MEMORY_FILE_PATH = process.env.MEMORY_FILE_PATH || "/data/memory.jsonl";

const TOOL_SCHEMAS = {
  create_entities: {
    name: "create_entities",
    description: "Create multiple new entities in the knowledge graph",
    input_schema: {
      type: "object",
      required: ["entities"],
      properties: {
        entities: {
          type: "array",
          items: {
            type: "object",
            required: ["name", "entityType", "observations"],
            properties: {
              name: { type: "string" },
              entityType: { type: "string" },
              observations: { type: "array", items: { type: "string" } },
            },
          },
        },
      },
    },
  },
  create_relations: {
    name: "create_relations",
    description: "Create multiple new relations between entities in the knowledge graph",
    input_schema: {
      type: "object",
      required: ["relations"],
      properties: {
        relations: {
          type: "array",
          items: {
            type: "object",
            required: ["from", "relationType", "to"],
            properties: {
              from: { type: "string" },
              relationType: { type: "string" },
              to: { type: "string" },
            },
          },
        },
      },
    },
  },
  add_observations: {
    name: "add_observations",
    description: "Add new observations to existing entities in the knowledge graph",
    input_schema: {
      type: "object",
      required: ["observations"],
      properties: {
        observations: {
          type: "array",
          items: {
            type: "object",
            required: ["entityName", "contents"],
            properties: {
              entityName: { type: "string" },
              contents: { type: "array", items: { type: "string" } },
            },
          },
        },
      },
    },
  },
  delete_entities: {
    name: "delete_entities",
    description: "Delete multiple entities and their associated relations from the knowledge graph",
    input_schema: {
      type: "object",
      required: ["entityNames"],
      properties: {
        entityNames: { type: "array", items: { type: "string" } },
      },
    },
  },
  delete_relations: {
    name: "delete_relations",
    description: "Delete multiple relations from the knowledge graph",
    input_schema: {
      type: "object",
      required: ["relations"],
      properties: {
        relations: {
          type: "array",
          items: {
            type: "object",
            required: ["from", "relationType", "to"],
            properties: {
              from: { type: "string" },
              relationType: { type: "string" },
              to: { type: "string" },
            },
          },
        },
      },
    },
  },
  delete_observations: {
    name: "delete_observations",
    description: "Delete specific observations from entities in the knowledge graph",
    input_schema: {
      type: "object",
      required: ["deletions"],
      properties: {
        deletions: {
          type: "array",
          items: {
            type: "object",
            required: ["entityName", "observations"],
            properties: {
              entityName: { type: "string" },
              observations: { type: "array", items: { type: "string" } },
            },
          },
        },
      },
    },
  },
  read_graph: {
    name: "read_graph",
    description: "Read the entire knowledge graph",
    input_schema: { type: "object", properties: {} },
  },
  search_nodes: {
    name: "search_nodes",
    description: "Search for nodes in the knowledge graph based on a query",
    input_schema: {
      type: "object",
      required: ["query"],
      properties: {
        query: { type: "string" },
      },
    },
  },
  open_nodes: {
    name: "open_nodes",
    description: "Open specific nodes in the knowledge graph by their names",
    input_schema: {
      type: "object",
      required: ["names"],
      properties: {
        names: { type: "array", items: { type: "string" } },
      },
    },
  },
};

async function ensureParentDir(filePath) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
}

class KnowledgeGraphManager {
  constructor(memoryFilePath) {
    this.memoryFilePath = memoryFilePath;
  }

  async loadGraph() {
    try {
      const data = await fs.readFile(this.memoryFilePath, "utf-8");
      const lines = data.split("\n").filter((line) => line.trim() !== "");
      return lines.reduce(
        (graph, line) => {
          const item = JSON.parse(line);
          if (item.type === "entity") graph.entities.push(item);
          if (item.type === "relation") graph.relations.push(item);
          return graph;
        },
        { entities: [], relations: [] },
      );
    } catch (err) {
      if (err && err.code === "ENOENT") {
        return { entities: [], relations: [] };
      }
      throw err;
    }
  }

  async saveGraph(graph) {
    await ensureParentDir(this.memoryFilePath);
    const lines = [
      ...graph.entities.map((e) =>
        JSON.stringify({
          type: "entity",
          name: e.name,
          entityType: e.entityType,
          observations: e.observations,
        }),
      ),
      ...graph.relations.map((r) =>
        JSON.stringify({
          type: "relation",
          from: r.from,
          to: r.to,
          relationType: r.relationType,
        }),
      ),
    ];
    await fs.writeFile(this.memoryFilePath, lines.join("\n"));
  }

  async createEntities(entities) {
    const graph = await this.loadGraph();
    const newEntities = entities.filter(
      (e) => !graph.entities.some((existing) => existing.name === e.name),
    );
    graph.entities.push(...newEntities);
    await this.saveGraph(graph);
    return newEntities;
  }

  async createRelations(relations) {
    const graph = await this.loadGraph();
    const newRelations = relations.filter(
      (r) =>
        !graph.relations.some(
          (existing) =>
            existing.from === r.from &&
            existing.to === r.to &&
            existing.relationType === r.relationType,
        ),
    );
    graph.relations.push(...newRelations);
    await this.saveGraph(graph);
    return newRelations;
  }

  async addObservations(observations) {
    const graph = await this.loadGraph();
    const results = [];

    for (const item of observations) {
      const entity = graph.entities.find((e) => e.name === item.entityName);
      if (!entity) continue;

      const newObs = item.contents.filter((c) => !entity.observations.includes(c));
      entity.observations.push(...newObs);
      results.push({ entityName: item.entityName, contents: newObs });
    }

    await this.saveGraph(graph);
    return results;
  }

  async deleteEntities(entityNames) {
    const graph = await this.loadGraph();
    const beforeCount = graph.entities.length;

    graph.entities = graph.entities.filter((e) => !entityNames.includes(e.name));
    graph.relations = graph.relations.filter(
      (r) => !entityNames.includes(r.from) && !entityNames.includes(r.to),
    );

    const deletedCount = beforeCount - graph.entities.length;
    await this.saveGraph(graph);
    return deletedCount;
  }

  async deleteRelations(relations) {
    const graph = await this.loadGraph();
    const toDelete = new Set(relations.map((r) => `${r.from}|${r.relationType}|${r.to}`));

    const beforeCount = graph.relations.length;
    graph.relations = graph.relations.filter(
      (r) => !toDelete.has(`${r.from}|${r.relationType}|${r.to}`),
    );

    const deletedCount = beforeCount - graph.relations.length;
    await this.saveGraph(graph);
    return deletedCount;
  }

  async deleteObservations(deletions) {
    const graph = await this.loadGraph();
    const results = [];

    for (const item of deletions) {
      const entity = graph.entities.find((e) => e.name === item.entityName);
      if (!entity) continue;

      const before = entity.observations.length;
      entity.observations = entity.observations.filter((o) => !item.observations.includes(o));
      const deletedCount = before - entity.observations.length;
      results.push({ entityName: item.entityName, deletedCount });
    }

    await this.saveGraph(graph);
    return results;
  }

  async readGraph() {
    return await this.loadGraph();
  }

  async searchNodes(query) {
    const q = query.toLowerCase();
    const graph = await this.loadGraph();

    const entities = graph.entities.filter((e) => {
      if (e.name.toLowerCase().includes(q)) return true;
      if ((e.entityType || "").toLowerCase().includes(q)) return true;
      return (e.observations || []).some((o) => String(o).toLowerCase().includes(q));
    });

    return { entities, relations: [] };
  }

  async openNodes(names) {
    const graph = await this.loadGraph();
    const entities = graph.entities.filter((e) => names.includes(e.name));
    const nameSet = new Set(names);
    const relations = graph.relations.filter((r) => nameSet.has(r.from) || nameSet.has(r.to));
    return { entities, relations };
  }
}

function createMemoryServer() {
  const server = new McpServer({ name: APP_NAME, version: APP_VERSION });
  const graph = new KnowledgeGraphManager(MEMORY_FILE_PATH);

  server.tool(
    "create_entities",
    "Create multiple new entities in the knowledge graph",
    {
      entities: z.array(
        z.object({
          name: z.string(),
          entityType: z.string(),
          observations: z.array(z.string()),
        }),
      ),
    },
    async ({ entities }) => {
      const created = await graph.createEntities(entities);
      return { content: [{ type: "text", text: JSON.stringify({ entities: created }) }] };
    },
  );

  server.tool(
    "create_relations",
    "Create multiple new relations between entities in the knowledge graph",
    {
      relations: z.array(
        z.object({
          from: z.string(),
          relationType: z.string(),
          to: z.string(),
        }),
      ),
    },
    async ({ relations }) => {
      const created = await graph.createRelations(relations);
      return { content: [{ type: "text", text: JSON.stringify({ relations: created }) }] };
    },
  );

  server.tool(
    "add_observations",
    "Add new observations to existing entities in the knowledge graph",
    {
      observations: z.array(
        z.object({
          entityName: z.string(),
          contents: z.array(z.string()),
        }),
      ),
    },
    async ({ observations }) => {
      const added = await graph.addObservations(observations);
      return { content: [{ type: "text", text: JSON.stringify({ observations: added }) }] };
    },
  );

  server.tool(
    "delete_entities",
    "Delete multiple entities and their associated relations from the knowledge graph",
    {
      entityNames: z.array(z.string()),
    },
    async ({ entityNames }) => {
      const deletedCount = await graph.deleteEntities(entityNames);
      return { content: [{ type: "text", text: JSON.stringify({ deletedCount }) }] };
    },
  );

  server.tool(
    "delete_relations",
    "Delete multiple relations from the knowledge graph",
    {
      relations: z.array(
        z.object({
          from: z.string(),
          relationType: z.string(),
          to: z.string(),
        }),
      ),
    },
    async ({ relations }) => {
      const deletedCount = await graph.deleteRelations(relations);
      return { content: [{ type: "text", text: JSON.stringify({ deletedCount }) }] };
    },
  );

  server.tool(
    "delete_observations",
    "Delete specific observations from entities in the knowledge graph",
    {
      deletions: z.array(
        z.object({
          entityName: z.string(),
          observations: z.array(z.string()),
        }),
      ),
    },
    async ({ deletions }) => {
      const deleted = await graph.deleteObservations(deletions);
      return { content: [{ type: "text", text: JSON.stringify({ deletions: deleted }) }] };
    },
  );

  server.tool(
    "read_graph",
    "Read the entire knowledge graph",
    {},
    async () => {
      const data = await graph.readGraph();
      return { content: [{ type: "text", text: JSON.stringify(data) }] };
    },
  );

  server.tool(
    "search_nodes",
    "Search for nodes in the knowledge graph based on a query",
    { query: z.string() },
    async ({ query }) => {
      const result = await graph.searchNodes(query);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  server.tool(
    "open_nodes",
    "Open specific nodes in the knowledge graph by their names",
    { names: z.array(z.string()) },
    async ({ names }) => {
      const result = await graph.openNodes(names);
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );

  return server;
}

const app = express();
app.use(
  cors({
    origin: "*",
    methods: "GET,POST,DELETE",
    preflightContinue: false,
    optionsSuccessStatus: 204,
    exposedHeaders: ["mcp-session-id", "last-event-id", "mcp-protocol-version"],
  }),
);

app.use("/invoke", express.json({ limit: process.env.JSON_BODY_LIMIT || "1mb" }));

const transports = new Map();

app.get("/health", async (_req, res) => {
  res.json({ status: "ok", app: APP_NAME, version: APP_VERSION });
});

app.get("/.well-known/mcp.json", async (_req, res) => {
  res.json({
    name: APP_NAME,
    version: APP_VERSION,
    description: "MCP memory provider backed by a JSONL knowledge graph.",
    capabilities: {
      tools: Object.values(TOOL_SCHEMAS),
    },
    metadata: {
      memory_file_path: MEMORY_FILE_PATH,
    },
  });
});

app.post("/invoke", async (req, res) => {
  const { tool, arguments: args = {} } = req.body || {};
  if (!tool || typeof tool !== "string") {
    res.status(400).json({ error: "tool is required" });
    return;
  }
  if (!TOOL_SCHEMAS[tool]) {
    res.status(404).json({ error: `Unknown tool '${tool}'` });
    return;
  }

  const graph = new KnowledgeGraphManager(MEMORY_FILE_PATH);
  try {
    switch (tool) {
      case "create_entities": {
        const created = await graph.createEntities(args.entities || []);
        res.json({ outputs: { entities: created } });
        return;
      }
      case "create_relations": {
        const created = await graph.createRelations(args.relations || []);
        res.json({ outputs: { relations: created } });
        return;
      }
      case "add_observations": {
        const added = await graph.addObservations(args.observations || []);
        res.json({ outputs: { observations: added } });
        return;
      }
      case "delete_entities": {
        const deletedCount = await graph.deleteEntities(args.entityNames || []);
        res.json({ outputs: { deletedCount } });
        return;
      }
      case "delete_relations": {
        const deletedCount = await graph.deleteRelations(args.relations || []);
        res.json({ outputs: { deletedCount } });
        return;
      }
      case "delete_observations": {
        const deletions = await graph.deleteObservations(args.deletions || []);
        res.json({ outputs: { deletions } });
        return;
      }
      case "read_graph": {
        const data = await graph.readGraph();
        res.json({ outputs: data });
        return;
      }
      case "search_nodes": {
        const result = await graph.searchNodes(String(args.query || ""));
        res.json({ outputs: result });
        return;
      }
      case "open_nodes": {
        const result = await graph.openNodes(args.names || []);
        res.json({ outputs: result });
        return;
      }
      default:
        res.status(400).json({ error: `Tool '${tool}' not implemented` });
        return;
    }
  } catch (err) {
    res.status(502).json({ error: err?.message || String(err) });
  }
});

app.post(
  "/mcp",
  express.text({ type: "application/json", limit: process.env.JSON_BODY_LIMIT || "1mb" }),
  async (req, res) => {
  try {
    const sessionId = req.headers["mcp-session-id"];

    let transport;
    if (sessionId && transports.has(sessionId)) {
      transport = transports.get(sessionId);
    } else if (!sessionId) {
      const server = createMemoryServer();
      const eventStore = new InMemoryEventStore();
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        eventStore,
        onsessioninitialized: (sid) => {
          transports.set(sid, transport);
        },
      });

      server.onclose = async () => {
        const sid = transport.sessionId;
        if (sid && transports.has(sid)) {
          transports.delete(sid);
        }
      };

      await server.connect(transport);
      await transport.handleRequest(req, res);
      return;
    } else {
      res.status(400).json({
        jsonrpc: "2.0",
        error: { code: -32000, message: "Bad Request: No valid session ID provided" },
        id: req?.body?.id,
      });
      return;
    }

    await transport.handleRequest(req, res);
  } catch {
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: req?.body?.id,
      });
    }
  }
  },
);

app.get("/mcp", async (req, res) => {
  const sessionId = req.headers["mcp-session-id"];
  if (!sessionId || !transports.has(sessionId)) {
    res.status(400).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Bad Request: No valid session ID provided" },
      id: req?.body?.id,
    });
    return;
  }

  const transport = transports.get(sessionId);
  await transport.handleRequest(req, res);
});

app.delete("/mcp", async (req, res) => {
  const sessionId = req.headers["mcp-session-id"];
  if (!sessionId || !transports.has(sessionId)) {
    res.status(400).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Bad Request: No valid session ID provided" },
      id: req?.body?.id,
    });
    return;
  }

  const transport = transports.get(sessionId);
  await transport.handleRequest(req, res);

  transports.delete(sessionId);
});

app.listen(PORT, () => {
  process.stderr.write(`mcp-memory listening on :${PORT} using ${MEMORY_FILE_PATH}\n`);
});
