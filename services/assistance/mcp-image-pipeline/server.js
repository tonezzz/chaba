import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

import { GoogleGenAI } from "@google/genai";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const APP_NAME = "mcp-image-pipeline";
const APP_VERSION = "0.1.0";

const ASSETS_DIR = (process.env.IMAGE_PIPELINE_ASSETS_DIR || "/data/assets").trim() || "/data/assets";
const MODEL_DEFAULT = (process.env.IMAGE_PIPELINE_MODEL || "gemini-3.1-flash-image-preview").trim() || "gemini-3.1-flash-image-preview";
const ALLOWED_MODELS = String(process.env.IMAGE_PIPELINE_ALLOWED_MODELS || MODEL_DEFAULT)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

function requireApiKey() {
  const apiKey = String(process.env.API_KEY || process.env.GEMINI_API_KEY || "").trim();
  if (!apiKey) {
    throw new Error("missing_api_key");
  }
  return apiKey;
}

function ensureAssetsDir() {
  fs.mkdirSync(ASSETS_DIR, { recursive: true });
}

function safeId(s) {
  return String(s || "").replace(/[^a-zA-Z0-9_\-]/g, "_");
}

function assetPaths(assetId) {
  const id = safeId(assetId);
  return {
    blobPath: path.join(ASSETS_DIR, `${id}.bin`),
    metaPath: path.join(ASSETS_DIR, `${id}.json`),
  };
}

function sha256(buf) {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

function pickModel(model) {
  const m = String(model || "").trim() || MODEL_DEFAULT;
  if (!ALLOWED_MODELS.includes(m)) {
    const err = new Error("model_not_allowed");
    err.details = { model: m, allowed: ALLOWED_MODELS };
    throw err;
  }
  return m;
}

function extractInlineImageBytes(response) {
  const parts = response?.candidates?.[0]?.content?.parts || [];
  for (const part of parts) {
    const inlineData = part?.inlineData || part?.inline_data;
    if (!inlineData) continue;
    const mimeType = inlineData.mimeType || inlineData.mime_type || "image/png";
    const data = inlineData.data;
    if (typeof data === "string" && data.length) {
      return { bytes: Buffer.from(data, "base64"), mimeType };
    }
    if (data instanceof Uint8Array) {
      return { bytes: Buffer.from(data), mimeType };
    }
  }
  throw new Error("no_inline_image");
}

async function generateImage({ prompt, model, aspect_ratio, image_size }) {
  const apiKey = requireApiKey();
  const m = pickModel(model);

  const ai = new GoogleGenAI({ apiKey });

  // Gemini-native image generation (Nano Banana) is via generateContent -> inlineData
  // Imagen models may require a different API surface; attempt if SDK supports it.
  if (m.startsWith("imagen-")) {
    const fn = ai?.models?.generateImages;
    if (typeof fn !== "function") {
      const e = new Error("imagen_generate_images_not_supported_in_js_sdk");
      e.details = { model: m };
      throw e;
    }
    const res = await fn.call(ai.models, {
      model: m,
      prompt,
      config: {
        aspectRatio: aspect_ratio || undefined,
        imageSize: image_size || undefined,
      },
    });

    const generated = res?.generatedImages || res?.generated_images || [];
    const first = Array.isArray(generated) ? generated[0] : null;
    const img = first?.image || first;
    const mimeType = img?.mimeType || img?.mime_type || "image/png";
    const bytes = img?.imageBytes || img?.image_bytes || img?.data;
    if (typeof bytes === "string" && bytes.length) {
      return { bytes: Buffer.from(bytes, "base64"), mimeType, model: m };
    }
    if (bytes instanceof Uint8Array) {
      return { bytes: Buffer.from(bytes), mimeType, model: m };
    }
    throw new Error("imagen_no_generated_image");
  }

  const config = { imageConfig: {} };
  if (aspect_ratio) config.imageConfig.aspectRatio = String(aspect_ratio);
  if (image_size) config.imageConfig.imageSize = String(image_size);
  if (!Object.keys(config.imageConfig).length) delete config.imageConfig;

  const response = await ai.models.generateContent({
    model: m,
    contents: prompt,
    config: Object.keys(config).length ? config : undefined,
  });
  const { bytes, mimeType } = extractInlineImageBytes(response);
  return { bytes, mimeType, model: m };
}

const server = new McpServer({ name: APP_NAME, version: APP_VERSION });

server.tool(
  "image_generate",
  {
    prompt: z.string().min(1).max(8000),
    model: z.string().optional(),
    aspect_ratio: z.string().optional(),
    image_size: z.string().optional(),
    return_data_url: z.boolean().optional(),
  },
  async ({ prompt, model, aspect_ratio, image_size, return_data_url }) => {
    ensureAssetsDir();
    const { bytes, mimeType, model: usedModel } = await generateImage({
      prompt,
      model,
      aspect_ratio,
      image_size,
    });

    const asset_id = `ip_${crypto.randomUUID().replace(/-/g, "").slice(0, 24)}`;
    const digest = sha256(bytes);
    const { blobPath, metaPath } = assetPaths(asset_id);

    fs.writeFileSync(blobPath, bytes);
    const meta = {
      asset_id,
      model: usedModel,
      mime_type: mimeType,
      sha256: digest,
      prompt,
      aspect_ratio: aspect_ratio || null,
      image_size: image_size || null,
      created_at: Math.floor(Date.now() / 1000),
    };
    fs.writeFileSync(metaPath, JSON.stringify(meta));

    const data_url =
      return_data_url === false
        ? null
        : `data:${mimeType};base64,${Buffer.from(bytes).toString("base64")}`;

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ ...meta, data_url }),
        },
      ],
    };
  }
);

server.tool(
  "image_asset_get",
  {
    asset_id: z.string().min(1),
  },
  async ({ asset_id }) => {
    const { metaPath } = assetPaths(asset_id);
    if (!fs.existsSync(metaPath)) {
      throw new Error("asset_not_found");
    }
    const text = fs.readFileSync(metaPath, "utf-8");
    return { content: [{ type: "text", text }] };
  }
);

server.tool(
  "image_asset_blob_get",
  {
    asset_id: z.string().min(1),
  },
  async ({ asset_id }) => {
    const { blobPath, metaPath } = assetPaths(asset_id);
    if (!fs.existsSync(blobPath)) {
      throw new Error("asset_not_found");
    }
    let mime_type = "application/octet-stream";
    try {
      if (fs.existsSync(metaPath)) {
        const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
        if (meta && typeof meta.mime_type === "string" && meta.mime_type) {
          mime_type = meta.mime_type;
        }
      }
    } catch {
      // ignore
    }
    const bytes = fs.readFileSync(blobPath);
    const b64 = Buffer.from(bytes).toString("base64");
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({ asset_id, mime_type, data_base64: b64 }),
        },
      ],
    };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
