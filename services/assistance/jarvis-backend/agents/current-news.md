---
id: current-news
name: Current News (CNN)
kind: sub_agent
version: 1
trigger_phrases: current news, cnn news, iran war, iran conflict, gold price, dollar price, oil price, thai baht, baht, thb, usd/thb
---

## Purpose
Prepare a cached context brief from configured news sources and topic definitions.

## Behavior
- Fetch latest items from configured sources.
- Build a short brief and cache structured context.
- Topics are driven by the `news_topics` sheet (SSOT).
- Answer follow-up requests for more details by topic key.

## Status Payload Contract
- `summary`: short text
- `updated_at`: unix timestamp (seconds)
- `sources`: list of source URLs
- `topics`: object keyed by topic id (sheet key). Each value contains:
  - `headlines`: list of strings
  - `items`: list of item objects
