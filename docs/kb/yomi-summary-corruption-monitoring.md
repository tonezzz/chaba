---
category: operations
---

# Detection and Monitoring

### Manual Detection Queries
```sql
-- Check for corrupted summaries
SELECT chat_id, name, summary 
FROM conversations 
WHERE summary IS NOT NULL 
AND (
  summary ILIKE '%Guthron%' OR 
  summary ILIKE '%Guthrie%' OR 
  summary ILIKE '%ดดดด%' OR 
  summary ILIKE '%วววงง%' OR
  summary ILIKE '%ไมกอม%'
);

-- Check for malformed cache keys
SELECT key 
FROM summaries_cache 
WHERE key LIKE '%,%' OR key LIKE '%keyMaterial%';
```

### Automated Monitoring
- **Quality score tracking**: Monitor summary_quality field for 0 scores
- **Pattern detection**: Regular scans for known corruption patterns
- **Cache validation**: Check for malformed cache keys
- **API monitoring**: Track LLM API response patterns

## Troubleshooting

### Issue: New corruption patterns appearing
**Solution**:
1. Identify the new pattern in corrupted summaries
2. Add detection pattern to `detectCorruptionPatterns()`
3. Update quality scoring to reject new pattern
4. Clean affected entries from cache and database

### Issue: High corruption rate despite fixes
**Solution**:
1. Check LLM API response quality
2. Consider increasing max_tokens further
3. Evaluate temperature settings
4. Consider model change or fine-tuning

### Issue: False positives in corruption detection
**Solution**:
1. Review detection patterns for over-matching
2. Adjust thresholds (e.g., character repetition count)
3. Add whitelist for legitimate patterns
4. Monitor quality score distribution

