---
id: current-news
name: Current News (CNN)
kind: sub_agent
version: 1
trigger_phrases: current news, cnn news, iran war, iran conflict, gold price, dollar price, oil price, thai baht, baht, thb, usd/thb
---

## Purpose
Prepare a cached context brief on the current situation of the Iran war and market moves (gold / dollar / oil), sourced from CNN.

## Behavior
- Fetch latest CNN RSS headlines.
- Build a short brief and cache structured context.
- Answer follow-up requests for more details within the continuation window.

## Status Payload Contract
- `summary`: short text
- `updated_at`: unix timestamp (seconds)
- `sources`: list of source URLs
- `topics`: object with `iran_war`, `gold`, `usd`, `oil`, `thb` sections
