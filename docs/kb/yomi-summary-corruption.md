---
category: operations
---

# Yomi Summary Corruption Prevention

## What it is

Root cause analysis and prevention strategies for Yomi conversation summary corruption issues. Covers detection patterns, fixes implemented, and ongoing prevention measures for LLM-generated summaries.
## Context/Background

Created 2026-08-04 as part of Chaba infrastructure documentation.


## Context

Yomi conversation summaries were experiencing corruption patterns including repeated text, garbled characters, and name repetition. Investigation revealed the root cause was LLM API generating malformed responses due to short max_tokens settings and insufficient content validation.

## Related Files

| File | Purpose |
|------|---------|
| `scripts/yomi/process-conversations.mjs` | LLM API configuration and summarization |
| `scripts/yomi/summary-utils.mjs` | Corruption detection and quality scoring |
| `scripts/yomi/db.mjs` | Database operations for summaries |
| `docs/kb/yomi.md` | Yomi LINE web app comprehensive documentation |

## Performance Impact

### Before Fixes
- **Corrupted summaries**: 3 corrupted + 10 missing + 3 low-quality
- **Cache entries**: 4 corrupted + 1 malformed
- **Database entries**: 4 corrupted + 1 malformed

### After Fixes
- **Corrupted summaries**: 0
- **Cache entries**: 0 corrupted
- **Database entries**: 0 corrupted
- **Total conversations**: 65 with valid summaries

## Lessons Learned

1. **Short max_tokens causes corruption**: Provide adequate space for complete responses
2. **Content validation is critical**: Length-based scoring insufficient for quality
3. **Pattern detection works**: Specific corruption patterns can be detected and prevented
4. **Cache hygiene matters**: Regular cleanup prevents corrupted data persistence
5. **Thai/English mixed content challenging**: Requires specialized handling and validation

## Tags

- **yomi**: LINE conversation management system
- **corruption**: Data corruption patterns and prevention
- **llm**: LLM API response quality issues
- **validation**: Content validation and quality scoring
- **thai-english**: Mixed language content challenges
- **prevention**: Data corruption prevention strategies

## See also

- [Yomi Summary Corruption Analysis](yomi-summary-corruption-analysis.md)
- [Yomi Summary Corruption Fixes](yomi-summary-corruption-fixes.md)
- [Yomi Summary Corruption Monitoring](yomi-summary-corruption-monitoring.md)
