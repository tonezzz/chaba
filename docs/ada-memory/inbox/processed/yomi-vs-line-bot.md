---
key: yomi-vs-line-bot
kind: fact
last_used: '2026-09-27'
scope: shared
source: voice
status: active
subject: yomi-line-bot-distinction
use_count: '1'
written_by: devin-cli
---
# Disambiguation: Yomi vs the LINE bot project

Two different LINE-related projects — do not conflate them.

**Yomi** (`mddb_collection: ada-ha-bank-yomi` + `yomi` MCP server):
- The LINE message **archive & search** service — pulls chats from the LINE
  API, summarizes them, stores digests in MDDB (~489 daily digests and
  counting), searchable via the `yomi` MCP tools and `ada_memory_search`.
- Read/analyze: "what did X say on LINE", daily digests, conversation search.
- Runs fetch+process pipeline (see chaba-docs `architecture/yomi-architecture-separation.md`).

**LINE bot / notification project** (earlier, separate):
- Outbound messaging — Ada/system sends LINE messages TO Tony (notifications,
  alerts). Not an archive, not search.
- When Tony says "the LINE bot" or "LINE notifications" he means this.

Rule of thumb: Yomi reads LINE; the LINE bot writes LINE.

