### Incident Report: vcast Playback Failure
**Time:** 2026-09-25 19:12
**User:** Tony
**Details:** User reported vcast screen 1 (iPad) showed black screen and
did not play video even after refresh and re-sending playback command.
System status indicated 'playing', but no visual output was observed on
the device.
**Devin Task:** Dispatched to investigate and fix playback issue, verify
with tests, and generate final report.

---

### Update — 2026-09-27

**Status: partially resolved — cast path hardened, black-screen root cause fixed in the tool layer.**

Findings and fixes since the incident:

- **Root cause class: tool-layer silent failure.** The cast *worked*
  server-side while status read 'playing' — iPad showed nothing because
  the action verb returned before the player attached. Two steering bugs
  made it look like a playback fault: `tv_action` was also answering
  lookup questions (cast instead of answer), and the HA client timed out
  at 5s while `nav`/cast takes ~6–10s.
- **Fixed**: `ha_client` per-call timeout raised to 45s (`a269fe9`) —
  the cast-complete response no longer aborts mid-flight; `tv_action` is
  now screen-display only (`b412b4a`); news lookups route to
  `web_search` (`42bc8c1`, `1f33052` for the grounding-quota revert).
- **Owner-locked casting** (`6a2ced7`, `5024c07`, `6b27155`): screens
  are speaker-gated — a guest/kid can't take over Tony's screen;
  `/pub` confirms via `ok:true` without echoing denial.
- **`cctv_snapshot`** (`f2e5951`): single-frame go2rtc peek pushed to a
  screen — gives Ada "eyes" on what a vcast screen actually shows
  (peek-per-request, no streaming overhead).
- **`/api/notify`** (`f9a5b49`): the backend can inject a system turn
  into the live voice session — cast results/ETA announcements reach
  Ada even when the action originated outside the conversation.
- **Scenario coverage**: `tv_cast_control.yaml` exercises cast verbs
  live; `cctv_snapshot_to_screen.yaml` covers the peek path.

**Still open:**

- [ ] vcast mechanics + remote-browser live verification on tony-dell
      (end-to-end play → iPad actually renders — not just status flags)
- [ ] A "did the screen show it?" post-cast check — `cctv_snapshot` of
      the target screen after cast to close the loop
- [ ] iPad black-screen device-side check (browser console) — only if it
      recurs after the tool-layer fixes
