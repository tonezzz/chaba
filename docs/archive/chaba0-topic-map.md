# chaba0 topic map — review before extraction

Source: `tonezzz/chaba0` @ `b5f1a62` (frozen 2026-03-28), 2228 files.
Manifest: `docs/archive/manifests/chaba0.yml` (unaccounted: 0).
Repo identity: "Super AI assistant" — predecessor platform to chaba/ada-pi.
Period: ~2025-10 → 2026-03 (git log range; verify during extraction).

## Proposed reports

| # | Topic | Files | Content | Disposition |
|---|---|---|---|---|
| 1 | host-infrastructure | 173 | host-*.json, stacks-*.json, system-inventory/, stacks/, docker/, templates/, .env.template | Distill: topology of pc1/pc2/idc1 era; tag every host/IP [historical] with current-name mapping (pc1→tony-omen, pc2→tony-dell/mn01, idc1→idc01) |
| 2 | network-dns | 12 | docs/dns zones, *url*.json, vpn.db | Historical only — tailnet replaced this entirely; note the surf-thailand.com/vpn domain layout |
| 3 | operations-runbooks | 106 | scripts/, docker-management, backlog, TODO, README, dev-host, tools/ | Distill procedures still-true vs superseded; backlog items may contain unmet goals worth porting |
| 4 | reorg-methodology | 2 | *reorganization-patterns.md | Rewrite for current hosts — methodology outlived the topology |
| 5 | deployment | 7 | installer/, line-webhook-deployment, mcp-nodehost | Mostly superseded by deploy-ada.sh; note the patterns |
| 6 | mcp-ecosystem | 171 | ~30 MCP server prototypes: deka-chat-api, mcp0 loader, acc, agents, assistant, audidoc, cuda, deka, devops, doc-archiver, docker, github-models, glama, http, imagen(+light), instrans, line, meeting, memory, openai-gateway, quickchart, rag(+light), task, tester, vaja(+stdio), webtops(+cp/router/windsurf-runtime), ws-gateway | Concept report — which MCPs existed, what each did, which ideas carried into today's MCP set, which were dropped and why. NOT a code archive |
| 7 | sites-apps | 438 | openchat-ui (vendored fork, 260), site-man (agent manager), site-chat, site-logger, a1-idc1, idc1, site-sample, site-webhook, test-ui, dev-host, tony | Concept report — app surfaces that existed; openchat-ui declared largely Not preserved (upstream vendored code) |
| — | excluded-noise | 1319 | mcp-playwright vendored (1290), tmp/temp, package-locks, dotfiles | No report — declared noise |

## Benchmark split (Devin vs Gemini/Ada)

- **Devin**: topics 1+2 (host-infrastructure, network-dns) — structured/JSON-heavy, needs careful entity tagging
- **Gemini**: topics 3–7 (prose + code-concept distillation) — larger file count but shallower per-file extraction
- **Ground truth** (pre-written, used to score fact retention):
  - host-infrastructure: the pc1/pc2/idc1 → current host mapping table must appear
  - network-dns: surf-thailand.com + vpn.db zone purpose must be stated
  - operations-runbooks: backlog items that later shipped (identify ≥3)
  - mcp-ecosystem: list which prototypes map to live MCP servers today (yomi/ha/etc.)
  - sites-apps: site-man's role as agent-manager predecessor must be stated

## Open for your call

- `sites/openchat-ui` — vendored upstream fork; plan is concept-note + Not-preserved for the 260 files. OK?
- `mcp/` code — reports distill *what existed + which ideas survived*, not code archaeology. OK?
- Backlog/TODO items — port still-relevant ones into chaba backlog, or note-only?
