#!/usr/bin/env node
// vcast-screens-card-check — DOM-stub regression check for
// vcast-screens-card.js. Feeds fixture /displays payloads (old relay shape
// and new lifecycle shape) and asserts the card lists only real,
// currently-registered cast targets: live screens render as cast rows,
// dead registry entries collapse into the offline section.
//
// Usage: node vcast-screens-card-check.mjs [--card <path>]
// Exit 0 = pass, 1 = fail. No browser or HA needed.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const cardPath = process.argv.includes("--card")
  ? process.argv[process.argv.indexOf("--card") + 1]
  : join(here, "vcast-screens-card.js");

// ---- minimal DOM stub -------------------------------------------------
let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ok  ${msg}`);
  else { failures++; console.log(`FAIL  ${msg}`); }
};

class StubEl {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.attributes = {};
    this._text = "";
    this._html = "";
    this.isConnected = true;
    this.onclick = null;
  }
  set textContent(v) { this._text = String(v); this.children = []; this._html = ""; }
  get textContent() {
    const own = this._html ? this._html.replace(/<[^>]*>/g, " ") : this._text;
    return own + this.children.map((c) => c.textContent).join("");
  }
  set innerHTML(v) { this._html = String(v); this.children = []; this._text = ""; }
  get innerHTML() { return this._html; }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  append(...cs) { for (const c of cs) this.appendChild(c); }
  prepend(c) { c.parentNode = this; this.children.unshift(c); }
  setAttribute(k, v) { this.attributes[k] = v; }
  get className() { return this.attributes.class || ""; }
  set className(v) { this.attributes.class = v; }
}

const registry = {};
globalThis.HTMLElement = class extends StubEl {
  constructor() { super("div"); }
};
globalThis.customElements = {
  define(name, cls) { registry[name] = cls; },
};
globalThis.document = {
  createElement: (t) => new StubEl(t),
  head: { appendChild() {} },
  body: { appendChild() {} },
};
globalThis.window = {};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.alert = () => {};
globalThis.confirm = () => true;

// ---- load the card -----------------------------------------------------
const src = readFileSync(cardPath, "utf8");
const fn = new Function("window", "document", "customElements", "HTMLElement",
  "setInterval", "clearInterval", "fetch", "alert", "confirm", src);

let fixture = { screens: [], pending: [] };
const fetchStub = async () => ({ json: async () => fixture });
fn(globalThis.window, globalThis.document, globalThis.customElements,
  globalThis.HTMLElement, globalThis.setInterval, globalThis.clearInterval,
  fetchStub, globalThis.alert, globalThis.confirm);

const Card = registry["vcast-screens-card"];
if (!Card) { console.log("FAIL  card did not register custom element"); process.exit(1); }

const settle = () => new Promise((r) => setTimeout(r, 0));

async function render(data) {
  fixture = data;
  const card = new Card();
  card.setConfig({ api: "https://example.test/api/input-bridge" });
  await card._poll();
  await settle();
  return card;
}

// rows of the card's list that are NOT inside the offline <details>
function liveRows(card) {
  const list = card._list;
  return list.children.filter((c) => c.tagName !== "DETAILS");
}
function offlineSection(card) {
  return card._list.children.find((c) => c.tagName === "DETAILS") || null;
}
function allText(card) { return card._list.textContent; }

const NOW = Date.now();
const iso = (msAgo) => new Date(NOW - msAgo).toISOString();

// ---- case 1: old relay shape — zombie entries must not be cast targets -
console.log("case 1: old /displays shape (connected flag + last_seen)");
{
  const card = await render({
    screens: [
      { screen: 2, name: "screen-2", label: "headless-2", connected: true,
        last_seen: iso(18 * 3600 * 1000), state: "idle" },
      { screen: 4, name: "screen-4", label: "headless-4", connected: true,
        last_seen: iso(30 * 60 * 1000), state: "play" },
      { screen: 6, name: "screen-6", label: "vcast-real-6", connected: true,
        last_seen: iso(20 * 1000), state: "idle" },
      { screen: 7, name: "screen-7", label: "vcast-real-7", connected: false,
        last_seen: iso(3600 * 1000) },
    ],
    pending: [],
  });
  const live = liveRows(card).map((r) => r.textContent).join("\n");
  ok(live.includes("#6"), "live screen 6 listed as cast target");
  ok(!live.includes("#2") && !live.includes("#4") && !live.includes("#7"),
    "stale/dead screens 2,4,7 excluded from target list");
  const off = offlineSection(card);
  ok(off !== null, "offline registry section rendered");
  ok(off && off.textContent.includes("3 offline registry"),
    "offline section counts 3 dead entries");
  ok(off && off.textContent.includes("headless-2"), "offline section names the dead display");
  ok(allText(card).includes("last seen"), "offline rows show last-seen age");
}

// ---- case 2: new relay shape — lifecycle is authoritative ------------
console.log("case 2: new /displays shape (lifecycle field)");
{
  const card = await render({
    screens: [
      { screen: 2, name: "screen-2", label: "headless-2", connected: true,
        lifecycle: "stale", age_s: 64000, last_seen: iso(18 * 3600 * 1000) },
      { screen: 6, name: "screen-6", label: "vcast-real-6", connected: true,
        lifecycle: "idle", last_seen: iso(10 * 1000) },
      { screen: 7, name: "screen-7", label: "vcast-real-7", connected: true,
        lifecycle: "playing", lifecycle_detail: "nav", last_seen: iso(5 * 1000) },
      { screen: 8, name: "screen-8", label: "reconnecting", connected: false,
        lifecycle: "reconnecting", reclaim_in_s: 12, last_seen: iso(70000) },
    ],
    pending: [],
    health: { connected: 2, reconnecting: 1, stale: 1, pending: 0, released: 0,
      flaps_24h: 3 },
  });
  const live = liveRows(card).map((r) => r.textContent).join("\n");
  ok(live.includes("#6") && live.includes("#7"), "idle+playing screens listed");
  ok(!live.includes("#2") && !live.includes("#8"),
    "stale + reconnecting screens excluded from target list");
  const off = offlineSection(card);
  ok(off && off.textContent.includes("2 offline registry"),
    "offline section counts stale+reconnecting");
}

// ---- case 3: pending + empty registry still render --------------------
console.log("case 3: pending displays and empty registry");
{
  const card = await render({
    screens: [],
    pending: [{ sid: "s1", label: "new-ipad", code: "1234", expires_in_s: 300 }],
  });
  ok(allText(card).includes("waiting to pair"), "pending display listed");
  const card2 = await render({ screens: [], pending: [] });
  ok(allText(card2).includes("No screens yet"), "empty state shown");
  ok(offlineSection(card2) === null, "no offline section when registry empty");
}

// ---- --live: render against the real relay and report the split -------
if (process.argv.includes("--live")) {
  const api = process.argv.includes("--api")
    ? process.argv[process.argv.indexOf("--api") + 1]
    : "https://idc02.taila0626a.ts.net/api/input-bridge";
  console.log(`live check against ${api}/displays`);
  const real = await (await fetch(`${api}/displays`)).json();
  const card = await render(real);
  const targets = liveRows(card)
    .map((r) => r.textContent.replace(/\s+/g, " ").trim())
    .filter((t) => /#\d/.test(t));
  const off = offlineSection(card);
  console.log(`  cast targets listed: ${targets.length}`);
  for (const r of targets) console.log(`    ${r}`);
  console.log(`  offline entries: ${off ? off.children.length - 1 : 0}`);
  if (off) for (const d of off.children.slice(1))
    console.log(`    ${d.textContent.replace(/\s+/g, " ").trim()}`);
  process.exit(0);
}

console.log(failures ? `\n${failures} check(s) FAILED` : "\nall checks passed");
process.exit(failures ? 1 : 0);
