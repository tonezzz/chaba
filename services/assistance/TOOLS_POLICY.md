# TOOLS POLICY

## Purpose

This document defines general rules for how Jarvis uses tools.

## Principles

- Least privilege: only enable tools that are required
- Confirm before dangerous actions
- Keep tool outputs user-visible when they affect the user

## Confirmation gating

Some tools require explicit confirmation before execution. This is enforced via the backend `pending_*` flow.

## Logging

- Log tool name and high-level parameters
- Do not log secrets

## Tool-specific policies

- Memory: see `MEMORY_POLICY.md`
