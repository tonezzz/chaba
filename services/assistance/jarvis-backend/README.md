# jarvis-backend

Python 3.12 / FastAPI backend for the Jarvis voice-assistant service (port 8018).

## Running locally

```bash
pip install -r requirements.txt
PORT=8018 python main.py
```

## Configuration

| Env var | Default | Description |
|---|---|---|
| `PORT` | `8018` | HTTP listen port |
| `SKILLS_ROUTING_ENABLED` | _(unset / off)_ | Set to `true` to enable deterministic skill routing |
| `NEWS_RSS_FEEDS` | BBC Thai + Thai Rath + Bangkok Post | Comma-separated RSS feed URLs |
| `NEWS_FETCH_TIMEOUT_SECONDS` | `10` | Per-feed HTTP timeout |
| `NEWS_MAX_ARTICLES` | `10` | Max articles returned per query |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/news_search` | Direct news search (routing gate bypassed) |
| `POST` | `/api/dispatch` | Route text utterance through skills sheet |

### POST `/api/news_search`

```json
{
  "query": "หาข่าวที่เกี่ยวกับราคาทองคำ",
  "max_articles": 10
}
```

> Feed URLs are **operator-configured** via `NEWS_RSS_FEEDS` (env var).  
> Callers cannot override them – this prevents SSRF.

Response (`type: news_search_result`):

```json
{
  "type": "news_search_result",
  "brief": "พบข่าวเกี่ยวกับ \"ราคาทองคำ\" จำนวน 3 รายการ:\n\n1. ราคาทองคำพุ่งสูง\n   🔗 https://...",
  "sources": ["https://..."],
  "articles": [...],
  "query": "หาข่าวที่เกี่ยวกับราคาทองคำ",
  "keywords": ["ราคาทองคำ"]
}
```

### POST `/api/dispatch`

Requires `SKILLS_ROUTING_ENABLED=true`. Routes the text to the matching skill
handler. Falls through with `type: dispatch_fallthrough` when no pattern matches.

```json
{ "text": "หาข่าวที่เกี่ยวกับราคาทองคำ" }
```

## Skills Sheet patterns

| Thai pattern | English pattern | Skill |
|---|---|---|
| `หาข่าว` | `find news` | `news_search` |
| `ค้นข่าว` | `search news` | `news_search` |
| `ข่าวเกี่ยวกับ` | `news about` | `news_search` |

## Verification

**Phrase: "หาข่าวที่เกี่ยวกับราคาทองคำ"**

```bash
# 1. Start service
SKILLS_ROUTING_ENABLED=true PORT=8018 python main.py

# 2. Direct news search
curl -s -X POST http://localhost:8018/api/news_search \
  -H "Content-Type: application/json" \
  -d '{"query": "หาข่าวที่เกี่ยวกับราคาทองคำ"}' | python -m json.tool

# 3. Via dispatch (skills routing)
curl -s -X POST http://localhost:8018/api/dispatch \
  -H "Content-Type: application/json" \
  -d '{"text": "หาข่าวที่เกี่ยวกับราคาทองคำ"}' | python -m json.tool
```

Expected: response contains `"type": "news_search_result"` with a Thai `brief`
listing headlines and `sources` URLs. If no matching articles are found, a
helpful Thai message is returned suggesting alternate keywords.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest test_news_search.py -v
```
