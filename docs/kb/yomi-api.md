---
category: operations
---

# API Endpoints

### Implemented Endpoints (in `yomi-api.mjs`)
- `GET /api/yomi/health` - Health check
- `GET /api/yomi/conversations` - List all conversations
- `GET /api/yomi/messages?chat=<id>` - Get messages for a conversation
- `GET /api/yomi/daily?chat=<id>` - Get daily summaries
- `GET/POST /api/yomi/refresh?chat=<id>` - Manual refresh trigger
- `POST /api/yomi/send` - Send a message
- `GET /api/yomi/media/<chatId>/<messageId>` - Download media
- `GET /api/yomi/last-updated` - Last database update timestamp
- `GET/POST /api/yomi/fetch?chat=<id>` - Trigger fetch stage manually
- `GET/POST /api/yomi/process?chat=<id>&force=<bool>` - Trigger process stage manually
- `GET /api/yomi/activity-status` - Comprehensive system status, GPU status, rate limiter status
- `GET /api/yomi/rate-limiter-status` - Rate limiter and circuit breaker status (GPU monitoring)
- `GET /api/yomi/summarization-status` - Summarization statistics and quality metrics
- `GET /api/yomi/summary-quality` - Detailed quality metrics per conversation
- `POST /api/yomi/resummarize` - Trigger re-summarization of conversations

