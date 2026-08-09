# Gemini API Free Tier Limits

## What it is

Google's Gemini API provides free tier access for developers and small projects. The free tier includes limited access to certain models, free input & output tokens, and Google AI Studio access. Content from free tier usage may be used to improve Google's products.

## Free Tier Model Access

### Available Models (Free Tier)
- **gemini-3.6-flash** - Latest model balancing speed with intelligence
- **gemini-3.5-flash** - Most intelligent for agentic/coding tasks
- **gemini-3.5-flash-lite** - Fastest, most cost-effective 3.5 model
- **gemini-3.1-flash-lite** - Frontier-class performance at fraction of cost
- **gemini-2.5-flash** - Lightning-fast with controllable thinking budgets
- **gemini-2.5-flash-lite** - Smallest, most cost-effective for massive scale
- **gemma-4-31b-it** - 30.7B dense model, 256K context, Apache 2.0 licensed
- **gemma-4-26b-a4b-it** - 25.2B MoE model, 256K context, Apache 2.0 licensed

### Model Context Windows
| Model | Context Window | Max Output | Special Features |
|-------|---------------|------------|------------------|
| gemini-3.6-flash | ~1M tokens | ~8K tokens | Thinking, search grounding |
| gemini-3.5-flash | ~1M tokens | ~8K tokens | Agentic capabilities |
| gemini-3.5-flash-lite | ~1M tokens | ~8K tokens | High throughput |
| gemini-3.1-flash-lite | ~128K tokens | ~8K tokens | Cost-effective |
| gemini-2.5-flash | 1M tokens | ~8K tokens | Hybrid reasoning |
| gemini-2.5-flash-lite | ~1M tokens | ~8K tokens | Massive scale |
| gemma-4-31b-it | 256K tokens | 8K tokens | Apache 2.0, 140+ languages |
| gemma-4-26b-a4b-it | 256K tokens | 8K tokens | Apache 2.0, MoE architecture |

## Free Tier Rate Limits

### Rate Limit Dimensions
- **RPM** (Requests per minute) - Varies by model
- **TPM** (Tokens per minute - input) - Varies by model  
- **RPD** (Requests per day) - Varies by model, resets at midnight Pacific
- **No spend-based limits** - Free tier has no monetary spend limits

### Typical Free Tier Limits (Estimates)
| Model Category | RPM | TPM | Notes |
|----------------|-----|-----|-------|
| Flash models (3.x) | 15-50 | 1M-2M | Higher limits for stable models |
| Flash-Lite models | 20-60 | 1M-3M | Optimized for high throughput |
| Gemma 4 models | 10-30 | 500K-1M | Open weights models |
| Preview models | 5-15 | 500K-1M | More restricted limits |

**Note**: Exact limits vary by account and are viewable in Google AI Studio. Preview/experimental models have more restrictive limits.

## Free Tier Features

### Included Features
- ✅ Free input & output tokens (within rate limits)
- ✅ Google AI Studio access
- ✅ Limited access to advanced models
- ✅ Standard API endpoints
- ✅ Basic function calling
- ✅ Multimodal capabilities (text, images for supported models)

### Not Included (Paid Tier Only)
- ❌ Higher rate limits for production deployments
- ❌ Context caching
- ❌ Batch API (50% cost reduction)
- ❌ Access to most advanced models (some restricted)
- ❌ Content protection from product improvement
- ❌ Priority inference
- ❌ Dedicated support

## Usage Considerations

### Rate Limit Management
- Rate limits are applied per project, not per API key
- Limits reset on different schedules (RPM: rolling minute, RPD: midnight Pacific)
- Exceeding any limit dimension triggers 429 RESOURCE_EXHAUSTED error
- Preview models have more restrictive limits than stable models

### Best Practices for Free Tier
1. **Use Flash-Lite models** for high-volume, cost-sensitive tasks
2. **Implement exponential backoff** when encountering rate limits
3. **Cache responses** when possible to reduce API calls
4. **Monitor usage** in Google AI Studio to avoid hitting limits
5. **Use appropriate context windows** - smaller contexts reduce token usage
6. **Batch requests** when possible (though Batch API requires paid tier)

### Error Handling
```javascript
// Handle rate limit errors with exponential backoff
async function callWithBackoff(fn, maxRetries = 5) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      if (error.status === 429 && i < maxRetries - 1) {
        const delay = Math.pow(2, i) * 1000; // 1s, 2s, 4s, 8s, 16s
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }
      throw error;
    }
  }
}
```

## Model Selection Guide

### For Yomi Summarization (Current Use Case)
- **gemma-4-31b-it**: Best choice for Thai/English mixed content
  - 256K context window handles long conversations
  - 140+ languages including Thai
  - Apache 2.0 license (no restrictions)
  - Good reasoning capabilities for summarization

### Alternative Options
- **gemini-3.5-flash-lite**: Higher throughput, lower latency
  - Better for real-time applications
  - Lower token costs if upgrading to paid tier
  - Slightly smaller context window

- **gemini-2.5-flash**: 1M context window
  - Best for very long conversations
  - Hybrid reasoning capabilities
  - More expensive if upgrading to paid tier

## Monitoring and Management

### Check Your Limits
1. Go to [Google AI Studio](https://ai.google.dev/)
2. Sign in with your Google account
3. Navigate to "API keys" or "Usage" section
4. View your active rate limits and current usage

### Upgrade Path
- **Tier 1**: Set up billing account ($250 billing cap)
- **Tier 2**: Paid $100+ after 3 days ($2,000 billing cap)
- **Tier 3**: Paid $1,000+ after 30 days ($20,000-$100,000+ billing cap)

Each tier provides progressively higher rate limits and access to more features.

## Related Documentation

- [Gemini API Official Documentation](https://ai.google.dev/gemini-api/docs)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemma 4 Models](https://ai.google.dev/gemini-api/docs/models/gemma)
- [Yomi Documentation](yomi.md) - Current Yomi implementation using Gemini API
- [Yomi Media Analysis HTTP 500](yomi-media-analysis-http500.md) - Gemini API environment variable configuration issues

## Current Implementation

### Yomi Gemini Integration
- **File**: `chaba/scripts/yomi/gemini-integration.mjs`
- **Model**: `gemma-4-31b-it` (31B Dense model)
- **Context**: 256K tokens
- **Language Support**: Thai and English (language-aware prompts)
- **Usage**: Daily conversation summarization with timezone handling

### Configuration
```javascript
// Current model configuration
const GEMINI_MODEL = "gemma-4-31b-it";
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
```

### Usage Patterns
- Language detection for Thai/English content
- Thailand timezone handling (UTC+7)
- Batch daily summary generation
- Rate limiting to stay within free tier limits

## Troubleshooting

### Common Issues
- **429 RESOURCE_EXHAUSTED**: Rate limit exceeded - implement backoff
- **Model not available**: Some models restricted to paid tier
- **Context window exceeded**: Reduce input size or use larger context model
- **API key invalid**: Check API key in Google AI Studio

### Debug Tips
```bash
# Check API key validity
curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"

# Test specific model
curl "https://generativelanguage.googleapis.com/v1beta/models/gemma-4-31b-it?key=$GEMINI_API_KEY"
```

---

Last updated: 2026-08-06
Based on Gemini API documentation as of August 2026
