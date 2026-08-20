---
category: operations
---

# Global Rules and MDDB Search Testing Guide

## What it is

**Abstract**: Comprehensive testing approaches for validating the effectiveness of updated global rules and MDDB search performance, including test scenarios, validation methods, and success criteria.

## Context/Background

Global rules were updated to reflect the MDDB-based architecture and comprehensive MCP service integration. This guide provides testing methods to validate that the rules are effective and that MDDB search performs as expected.

## Success Criteria Summary

### Global Rules Success
- ✅ 95%+ of documentation queries use MDDB first
- ✅ Appropriate MCP service selection in 90%+ of cases
- ✅ User confirmation obtained before fallback in 100% of cases
- ✅ No silent fallback to traditional tools
- ✅ Service failure detection works correctly

### MDDB Search Success
- ✅ Search relevance scores > 0.45 for top results
- ✅ Search response times < 600ms for 95% of queries
- ✅ All 13 collections present and functional
- ✅ 154+ documents indexed and searchable
- ✅ SSOT auto-sync working correctly
- ✅ MCP integration functional
- ✅ Health monitoring operational

## Related Documentation

- **Global Rules**: /home/tony/.codeium/windsurf/memories/global_rules.md
- **MDDB User Guide**: docs/kb/mddb-user-guide.md
- **Documentation Search**: docs/kb/documentation-search.md
- **MDDB Migration Summary**: docs/kb/mddb-migration-summary.md

## See also

- [Global Rules Automated](global-rules-automated.md)
- [Global Rules Mddb Search](global-rules-mddb-search.md)
- [Global Rules Rules](global-rules-rules.md)
