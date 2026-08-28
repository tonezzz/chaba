# Yomi Summarization Service Improvements

## Current Issues

### 1. Summary Quality Problems
- Generic error messages in summaries ("Conversation unavailable, no summary possible")
- Very short or meaningless summaries
- Empty summaries for valid conversations

### 2. Cache Staleness
- Summaries cached based on lastMessageTime only
- Failed summarizations cached and not retried
- No re-summarization mechanism

### 3. Error Handling
- Failed summarizations fall back to stale cache
- Llama server failures cascade to skip remaining summaries
- No retry logic for transient failures

### 4. Content Threshold Issues
- Conversations with insufficient text get null summaries
- Media-heavy conversations skipped entirely
- No partial summarization for mixed content

## Recommended Improvements

### 1. Enhanced Summary Quality
- Add summary quality validation (min length, meaningful content check)
- Filter out generic error messages from being stored as summaries
- Add retry mechanism for failed summaries with exponential backoff
- Improve prompt engineering for better summarization

### 2. Cache Management
- Add cache versioning or timestamp for invalidation
- Store summary quality metrics in cache
- Add manual cache invalidation endpoint
- Implement cache warming for high-priority conversations

### 3. Error Handling & Resilience
- Add retry logic with exponential backoff (3-5 retries)
- Separate transient failures from permanent failures
- Queue failed summaries for later retry
- Add dead letter queue for permanently failed conversations

### 4. Content Processing
- Implement hybrid summarization (text + media descriptions)
- Add minimum content thresholds with configurable levels
- Support partial summaries for limited content
- Add conversation activity scoring to prioritize summarization

### 5. Monitoring & Metrics
- Add summary success/failure rates
- Track summary quality scores
- Monitor cache hit/miss ratios
- Alert on summarization pipeline failures

### 6. API Enhancements
- Add re-summarization endpoint (`POST /api/yomi/resummarize`)
- Add summary quality endpoint (`GET /api/yomi/summary-quality`)
- Add bulk re-summarization for conversations
- Add summary regeneration by date range

### 7. Database Schema Improvements
- Add summary_quality column (0-100 score)
- Add summary_generated_at timestamp
- Add summary_retry_count column
- Add summary_error_message column for debugging

## Implementation Priority

### High Priority
1. Add summary quality validation
2. Implement retry logic with backoff
3. Add re-summarization endpoint
4. Improve error handling and logging

### Medium Priority
1. Cache management improvements
2. Content processing enhancements
3. Monitoring and metrics

### Low Priority
1. Database schema changes
2. Advanced API features
3. ML-based quality scoring

## Quick Wins

1. **Add Summary Validation**: Check if summary contains generic error messages before storing
2. **Manual Re-summarization**: Add endpoint to force re-summarization of specific conversations
3. **Better Logging**: Log summarization failures with conversation context
4. **Cache Invalidation**: Add flag to bypass cache for re-summarization

## Testing Strategy

1. Test with various conversation types (text-heavy, media-heavy, mixed)
2. Test error scenarios (Llama down, network issues, invalid responses)
3. Test cache invalidation and re-summarization
4. Monitor summary quality improvements over time