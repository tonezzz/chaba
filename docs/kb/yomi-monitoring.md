---
category: operations
---

# Monitoring Integration

Yomi is integrated into the health check system with comprehensive monitoring:

### Health Check Configuration
- **Yomi API**: Monitored at `http://tony-omen.local:8080/api/yomi/conversations`
- **Yomi Summarization**: Monitored at `http://tony-omen.local:8080/api/yomi/summarization-status`
- **Yomi Rate Limiter**: Monitored at `http://tony-omen.local:8080/api/yomi/rate-limiter-status`
- **Category**: API services
- **Timeout**: 5 seconds
- **Config**: `docs/ssot/infrastructure/ssot.health.home.yml`

### GPU Load Management (2026-08-03, Updated 2026-08-04)
- **Rate Limiting**: Optimized settings (3 concurrent for daily summaries, 1 for regular summaries) to balance speed and GPU load
- **Circuit Breakers**: Automatic protection when GPU overloaded (2-5 failures trigger open state)
- **Queue Management**: Prevents request pile-up with configurable timeouts
- **GPU Monitoring**: Real-time GPU utilization, memory, and temperature tracking
- **Alerting**: Automatic detection of circuit breaker triggers, high GPU load, and temperature issues

### Rate Limiter Status (Updated 2026-08-04)
- **Summary Rate Limiter**: 1 concurrent, 2min queue timeout
- **Daily Rate Limiter**: 3 concurrent, 3min queue timeout (increased from 1 for faster processing)
- **Summary Circuit Breaker**: Opens after 2 failures, 3min timeout
- **Daily Circuit Breaker**: Opens after 5 failures, 4min timeout (more tolerant for batch processing)

### Rate Limiter and Circuit Breaker Architecture

**Implementation File:** `scripts/yomi/llama-rate-limiter.mjs`

**Rate Limiter Class:**
- Tracks running requests and queue depth
- Implements FIFO queue with timeout
- Automatically processes queued requests when slots available
- Returns statistics: running, queued, maxConcurrent

**Circuit Breaker Class:**
- Tracks failure count and last failure time
- Implements state machine (closed → open → half-open → closed)
- Automatic reset on successful requests
- Manual reset capability via API

**Circuit Breaker States:**
- **Closed**: Normal operation, requests pass through
- **Open**: Requests blocked after threshold failures, timeout period active
- **Half-open**: Testing recovery after timeout, allows single request to test

**Integration Points:**
- Process stage wraps Llama API calls with rate limiters
- API server provides `/api/yomi/rate-limiter-status` endpoint
- Health check system monitors rate limiter status

**Rate Limiter Status API Response:**
```json
{
  "summaryRateLimiter": {
    "running": 0,
    "queued": 0,
    "maxConcurrent": 1
  },
  "dailyRateLimiter": {
    "running": 0,
    "queued": 0,
    "maxConcurrent": 3
  },
  "summaryCircuitBreaker": {
    "state": "closed",
    "failureCount": 0,
    "lastFailureTime": null
  },
  "dailyCircuitBreaker": {
    "state": "closed",
    "failureCount": 0,
    "lastFailureTime": null
  }
}
```

