# Jarvis Frontend Services
<!-- rebuild: 2026-04-13 -->

Modular WebSocket and audio services for the Jarvis voice assistant.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        LiveService                          │
│  (Orchestrator: WS lifecycle, public API, state management)   │
└──────────────────┬──────────────────────────────────────────┘
                   │ delegates
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
┌─────────┐  ┌──────────────┐  ┌─────────────────┐
│liveAudio│  │liveVoiceCmd  │  │liveMessageHandlers
│         │  │              │  │                 │
│- I/O    │  │- Phrase      │  │- WS message     │
│  ctx    │  │  parsing     │  │  routing        │
│- PCM    │  │- Extractors   │  │- UI callbacks   │
│  conv    │  │  (pure)      │  │- Cmd triggers   │
└─────────┘  └──────────────┘  └─────────────────┘
```

## Module Responsibilities

### `liveService.ts` — The Orchestrator
- WebSocket lifecycle (connect, disconnect, reconnect)
- Public API for UI components (sendText, startStreaming, etc.)
- State coordination (session IDs, tool pending, voice command debounce)
- Creates `HandlerContext` for message handlers

**Key Pattern:** Delegates all message handling to `liveMessageHandlers.handleBackendMessage()`

### `liveAudio.ts` — Audio I/O
- `AudioManager` interface for input/output contexts
- `setupAudioInput()` — AudioWorklet-based PCM capture
- `teardownAudio()` — Safe cleanup (prevents memory leaks)
- `playPcmAudio()` — Scheduled audio playback with gapless sequencing

**Safety Features:**
- Lazy initialization (contexts created on-demand, not at module load)
- Worklet port callback nulled before disconnect (prevents late callbacks)
- All refs nulled after close (GC-friendly)

### `liveVoiceCmd.ts` — Pure Parsers
- **Pure functions only** — no `this`, no globals, no side effects
- Text normalization (`compactVoiceText`)
- Phrase detectors (`isGemsListPhrase`, `isReloadSystemPhrase`)
- Extractors (`extractGemsCreateId`, `extractReminderAddText`, etc.)

**Testing Strategy:**
```typescript
// Trivial to unit test — no mocks needed
expect(extractGemsCreateId("สร้างเจม my-model")).toBe("my-model");
expect(isReloadSystemPhrase("reload system")).toBe(true);
```

### `liveMessageHandlers.ts` — Message Router
- Single entry point: `handleBackendMessage(ctx, message)`
- Switch-based dispatcher by `message.type`
- Mutates `HandlerContext` state directly (timestamps, dedup)
- Triggers voice commands via pure functions from `liveVoiceCmd`

**HandlerContext Contract:**
- Primitive state fields mutated directly (numbers, strings, nulls)
- Object refs (`audio`, `toolPending`) stable — only contents modified
- Callbacks fire-and-forget (never awaited)
- `reconnectWithBackoff()` provided to prevent recursion storms

## Key Design Decisions

### 1. Why Pure Functions for Voice Commands?
- **Testability:** No mocks, no setup, just input→output
- **Reusability:** Can be used in other contexts (e.g., text chat)
- **Predictability:** Same input always same output

### 2. Why HandlerContext Instead of Direct Method Calls?
- **Decoupling:** Handlers don't depend on `LiveService` class
- **Testability:** Handlers can be unit tested with a mock context
- **Isolation:** Clear contract of what handlers can access/mutate

### 3. Why Bounded Reconnect?
Old pattern (dangerous):
```typescript
// In handler:
await ctx.disconnect();
await ctx.connect();  // Risk: recursive reconnect loops
```

New pattern (safe):
```typescript
// In handler:
await ctx.reconnectWithBackoff();  // Single attempt with jitter
```

### 4. Lazy Audio Initialization
Contexts are NOT created in `makeAudioManager()`. They are created in `ensureAudioInput()` which is only called:
- After a user gesture (Talk button)
- Or when explicitly starting streaming

This satisfies browser autoplay policies that require user interaction before AudioContext creation.

## Migration Guide

### From Monolithic liveService.ts

| Old Location | New Location |
|--------------|--------------|
| `setupAudioInput()` method | `liveAudio.ts` `setupAudioInput()` |
| `teardownAudio()` method | `liveAudio.ts` `teardownAudio()` |
| `playPcmAudio()` method | `liveAudio.ts` `playPcmAudio()` |
| `extractGems*()` methods | `liveVoiceCmd.ts` pure functions |
| `isReloadSystemPhrase()` | `liveVoiceCmd.ts` `isReloadSystemPhrase()` |
| `handleBackendMessage()` method | `liveMessageHandlers.ts` function |
| `shouldAutoTriggerVoiceCommand()` | `liveMessageHandlers.ts` (private) |

## Testing Checklist

- [ ] `liveVoiceCmd.ts` — Add unit tests for all extractors
- [ ] `liveAudio.ts` — Test rapid connect/disconnect cycles (memory leak check)
- [ ] `liveMessageHandlers.ts` — Mock context and test message routing
- [ ] `LiveService.ts` — Integration test WS lifecycle

## Memory Safety Notes

### Audio Cleanup Sequence
1. Null the `AudioWorkletNode.port.onmessage` callback
2. Disconnect the worklet node
3. Disconnect the media stream source
4. Close the AudioContexts
5. Null all refs

This prevents the worklet from posting messages after disconnection, which could cause "message posted to closed context" errors.

### WebSocket Cleanup
- `wsSeq` counter invalidates stale callbacks
- `toolPending` entries cleaned up on disconnect
- `keepaliveTimer` cleared on close/error

## Future Improvements

1. **State Machine:** Consider explicit FSM for connection states (idle → connecting → connected → streaming → disconnecting)
2. **Retry Logic:** Add exponential backoff for initial connection failures
3. **Metrics:** Add timing hooks for latency measurement (STT latency, TTFB)
4. **Type Safety:** Stricter message types (discriminated unions for each `type`)
