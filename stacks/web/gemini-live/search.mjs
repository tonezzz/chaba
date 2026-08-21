// Free, no-API-key search via DuckDuckGo.
// Supports web, images, and videos. Results are returned to Gemini so it can
// call rview_show / rview_queue with reachable URLs.

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

function decodeHtmlEntities(str) {
  if (!str) return "";
  return str
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(code));
}

function stripTags(str) {
  if (!str) return "";
  return str.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function fetchText(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: {
      "User-Agent": USER_AGENT,
      Accept: opts.method === "POST" ? "text/html" : "*/*",
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);
  return res.text();
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: { "User-Agent": USER_AGENT, Accept: "application/json", ...(opts.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);
  return res.json();
}

async function getVqd(query) {
  const html = await fetchText(
    `https://duckduckgo.com/?q=${encodeURIComponent(query)}&iax=images&ia=images`
  );
  const match = html.match(/vqd=([A-Za-z0-9-]+)/);
  if (!match) throw new Error("Could not obtain DuckDuckGo search token");
  return match[1];
}

async function runWebSearch(query, maxResults) {
  const body = new URLSearchParams({ q: query });
  const html = await fetchText("https://html.duckduckgo.com/html/", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  if (html.includes("anomaly-modal") || html.includes("Unfortunately, bots")) {
    throw new Error("DuckDuckGo search blocked by CAPTCHA; try again later");
  }
  const results = [];
  const titleRe = /<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = titleRe.exec(html)) && results.length < maxResults) {
    const url = m[1];
    const title = decodeHtmlEntities(stripTags(m[2]));
    const snippetRe = new RegExp(
      `<a[^>]*class="result__snippet"[^>]*href="${escapeRegex(url)}"[^>]*>([\\s\\S]*?)<\\/a>`,
      "i"
    );
    const snippetMatch = snippetRe.exec(html);
    const snippet = snippetMatch ? decodeHtmlEntities(stripTags(snippetMatch[1])) : "";
    results.push({ title, url, snippet });
  }
  return results;
}

async function runImageSearch(query, maxResults) {
  const vqd = await getVqd(query);
  const data = await fetchJson(
    `https://duckduckgo.com/i.js?q=${encodeURIComponent(query)}&vqd=${encodeURIComponent(
      vqd
    )}&o=json&p=1`
  );
  return (data.results || []).slice(0, maxResults).map((r) => ({
    title: r.title,
    url: r.url,
    image: r.image,
    thumbnail: r.thumbnail,
    width: r.width,
    height: r.height,
    source: r.source,
  }));
}

async function runVideoSearch(query, maxResults) {
  const vqd = await getVqd(query);
  const data = await fetchJson(
    `https://duckduckgo.com/v.js?q=${encodeURIComponent(query)}&vqd=${encodeURIComponent(
      vqd
    )}&o=json&p=1`
  );
  return (data.results || []).slice(0, maxResults).map((r) => ({
    title: r.title,
    url: r.content,
    duration: r.duration,
    provider: r.provider,
    image: r.images?.medium,
    embed_url: r.embed_url,
    publisher: r.publisher,
  }));
}

export async function searchWeb({ query, type = "web", max_results = 5 }) {
  const max = Math.min(Math.max(1, Number(max_results) || 5), 20);
  if (!query || typeof query !== "string") {
    throw new Error("query is required");
  }

  let resultType = type;
  let results;
  switch (type) {
    case "image":
    case "images":
      resultType = "images";
      results = await runImageSearch(query, max);
      break;
    case "video":
    case "videos":
      resultType = "videos";
      results = await runVideoSearch(query, max);
      break;
    case "web":
    default:
      resultType = "web";
      results = await runWebSearch(query, max);
  }

  return { type: resultType, query, results };
}
