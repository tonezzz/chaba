---
category: operations
---

# Root Cause Analysis

### Primary Cause: LLM API Corruption
- **Model**: Phi-3-mini-4k-instruct-q4
- **Issue**: Generating corrupted responses due to model limitations with Thai/English mixed content
- **Contributing Factors**:
  - Short max_tokens (50) causing truncation and partial responses
  - Temperature settings insufficient to prevent repetitive patterns
  - No content validation beyond basic length checks

### Secondary Cause: Cache System Issues
- **No corruption detection** in cache validation
- **Versioned cache keys** creating duplicate/malformed entries
- **Quality scoring** based on length, not content quality

## Corruption Patterns Discovered

### 1. Repeated Character Patterns
- **Example**: "ดดดดดดวดดกอดกงววมวมดดดดดงมมงอมมอมอดยดดอดอมอนอดดดดด..."
- **Detection**: Repeated same character 4+ times
- **Cause**: LLM model getting stuck in repetition loops

### 2. Garbled Text Patterns
- **Example**: "์ ไม่ม ไมกอม กด เมอดป กดแอกอป กอ กอดลอดกอ กอดกอบแก..."
- **Detection**: High ratio of random characters vs meaningful text
- **Cause**: Encoding issues or model hallucination

### 3. Name Repetition Patterns
- **Example**: "KKGT discusses discussing Savannah Guthrie'ranews about Savannah Guthron'ครiction..."
- **Detection**: Same name/word repeated 3+ times
- **Cause**: Model getting stuck on specific entities

### 4. Malformed Cache Keys
- **Example**: `c6d74470bfea6c4739b64b19ee6b45b5d,"{\"keyMaterial\":\"znlfvilva...\"`
- **Detection**: Cache keys containing keyMaterial strings
- **Cause**: Improper handling of encrypted message metadata

