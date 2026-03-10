---
id: deep-research
name: Deep Research (Gemini)
kind: sub_agent
version: 1
trigger_phrases: deep research, research report, investigate, research status, research result, research followup
---

## Purpose
Run long-running, cited research tasks via Gemini Deep Research (Interactions API) using a separate worker service.

## Behavior
- Start a research job when asked.
- Allow polling for status and retrieving results.
- Support follow-up questions using previous_interaction_id.

## Status Payload Contract
- `summary`: short text
- `job_id`: worker job id
- `interaction_id`: Gemini interaction id
- `status`: in_progress|completed|failed|cancelled
- `updated_at`: unix timestamp (seconds)
