---
key: tv-casting
kind: fact
status: active
subject: ada-tools
scope: shared
source: vault
written_by: tony
last_verified: 2026-09-25
---

How to cast and control the TV by voice. Everything goes through the tv_action tool (cmd + text).

Cast a web page on the TV's browser — cmd 'nav', text = the URL. This is a real headless browser on TONY-TV; once a page is showing you can control it: cmd 'scroll' text 'up'|'down', cmd 'click' text '<visible button text>' (or role '<role>' / selector '<css>'), cmd 'type' text '<text>', cmd 'press' text '<key name like Enter, Escape, ArrowDown>', cmd 'back', cmd 'shot' text '<name>' for a screenshot.

Cast Tony's desktop — cmd 'nav', text 'tony-omen:workspace:N' (N = GNOME workspace number; this also switches his live workspace and streams it to the TV). To cast another workspace while already streaming, nav to a different N. This is one-way video — there is no click/type into his desktop.

Cast this host's seat display — cmd 'nav', text 'screenlive:workspace:N[:pad|crop]'.

YouTube on the TV — use yt_cast (with subtitles support), not tv_action.

Stop casting — cmd 'nav' to a normal page or use yt_cast_stop for YouTube casts.

Examples: "cast my screen" → nav tony-omen:workspace:1. "cast my browser" → ask which workspace, or nav a URL directly. "scroll down on the TV" → scroll down. "click play" → click text 'Play'. "press enter" → press text 'Enter'.

Screen ownership (added 2026-09-26): personal screens are locked to their owner — a speaker may only cast to/from their own screens. The living-room TV (media_player.tony_tv / tony_tv_cast) is shared: anyone can use it. Tony's desktops (tony-omen workspaces, the tony-dell seat display) are person.tony only; vcast screens (cast_to_screen) each have an owner — unlisted screens are shared. If the speaker is not identified, personal screens deny with "identify the speaker first". If a cast fails with 'denied: ... private screen', say so and offer a shared alternative. Owner maps: cast-browser screens.json on tony-dell (sources+destinations) and ~/.local/share/ada-pi/cast-screens.json on idc01 (vcast screens).
