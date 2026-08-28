## Chaba-Specific Service Monitoring

**Critical Services:**
- **Yomi Services**: yomi-fetch.service, yomi-process.service
- **AI Services**: Llama Router (thai-legal-inference), Gemini API
- **Data Services**: Weaviate, PostgreSQL, Redis
- **Web Services**: Caddy, Status API, Trade API

**Common Failure Patterns:**
- API key expiration (401/403 errors)
- Service container failures (Docker health checks)
- Network connectivity issues (mobile vs home profile)
- Resource exhaustion (GPU memory, disk space)
