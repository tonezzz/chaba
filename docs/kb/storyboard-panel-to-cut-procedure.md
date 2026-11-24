# Storyboard Panel-to-Cut and Action-Continuity Procedure

Use this procedure when a storyboard page contains multiple numbered panels
that guide a generated scene. A panel is an action beat and visual anchor,
not a page to animate. A panel may guide one cut or, when it depicts several
distinct beats, an ordered sequence of subshots. A page collage is a
scene-level overview, not a substitute for the ordered panel/shot sequence.

## Source and extraction

1. Identify the authoritative source revision and SHA-256. Confirm that the
   source pages and any recognizable references are approved for the intended
   private or public use.
2. Extract embedded page-image objects without modifying them. Record the
   PDF page, object index, dimensions, byte count, SHA-256, and private source
   path. One embedded page image may itself contain many numbered panels.
3. Inspect the page layout and inventory every numbered panel in printed
   reading order. Do not assume equal-size cells or rely on OCR alone to
   determine panel boundaries/order.
4. Preserve two crops per numbered panel:
   - `panel-full`: the complete cell, including its number/caption, for audit.
   - `panel-visual`: the clean visual area for image conditioning, excluding
     labels/captions/overlaid lettering where practical.
5. Record exact crop bounds and SHA-256 for both files. Keep unnumbered cast
   sheets, portraits, quotes, and closing art in a separate context-reference
   list; do not silently count them as timed cuts.

## Cut ledger

Before prompt lock, create one ledger row per panel with:

- scene and cut IDs, source page/object/panel, source and crop hashes;
- printed caption and timecode, transcribed and checked against the full-cell crop;
- caption/narrative context kept separate from visible action and actors in
  the clean visual crop;
- intended duration, positive/negative prompt hashes, embedding/model revision,
  seed, and eventual output path/hash;
- actors visibly present, explicit action verbs, prop contact, gaze, starting
  /middle/ending state, camera/framing, and screen direction;
- a `shot-sequence` list when one panel depicts several distinct actions;
  subshot durations must sum to that panel's allocated target duration;
- continuity links to the preceding and following panels; QC and review status.

Write the generation action from the clean crop's visible gesture and object
interaction. Captions may clarify intent, but off-frame narrative context
must not become an extra actor or action in the shot. In particular, name
who is in frame and what each visible person does; do not substitute broad
story prose such as "a warm memory" for concrete movement. Do not invent
biography, dialogue, diagnoses, relationships, or events. Keep fact/memory,
dream/interpretation, and later evidence distinct; a dream is not proof that
an event was supernatural.

## Generation and continuity

1. Use the panel's `panel-visual` crop as the composition/identity/prop guide;
   never ask the model to animate the surrounding page, border, or caption.
2. Before prompt lock, write a visible-action plan: actors present, action
   verbs, prop contact, reaction, beginning/end pose, and camera plan. Keep
   caption context in metadata unless it is visibly depicted.
3. Use one generated cut for one visible action. If a panel depicts a sequence,
   create ordered subshots under that panel ID and assign a camera/action plan
   to each; their durations sum to the panel target. Do not turn a sequence
   into a generic zoom across a still.
4. Default to a locked camera for a single-panel I2V cut. Request zoom, pan,
   tilt, or dolly only when the storyboard or checked shot plan calls for it.
   Negatively constrain page/book/collage reveals, camera-only movement,
   extra/off-panel people, and text.
5. Carry the prior final frame only when the panels show continuous movement.
   At a scene/time change, make a clean cut rather than forcing pose continuity.
6. Keep character design, age, wardrobe, props, lighting, geography, eyelines,
   and screen direction consistent. Composite approved text in post.
7. Render serially with immutable pack/revision names. A technical pass with
   only camera motion, an invented actor, or missing character action is a
   creative reject: stop the dependent sequence, revise the prompt/shot plan,
   and produce a new version; never overwrite the failed/rejected output.

## KK-Mac admission

Before any heavy cut, run the trusted one-shot admission from the Mac owner
lane. Require AC power, sufficient free unified memory for the planned frame
count, cached/offline model files, no resident Ollama model, and no competing
Nest worker. Active render/export processes (for example `kk_mac_video_batch.py`,
FFmpeg, Premiere, After Effects, Media Encoder, Resolve, Final Cut, Blender, or
MLX) remain hard blocks. Scan full process command lines for known render
workers; an idle UI signal must never override an active render process or a
failed memory-capacity gate.

An open design app or recent keyboard/mouse input is not, by itself, a
resource conflict. Use the read-only resource probe instead:

- sample for 10 seconds; require each tracked design-app process tree
  (Illustrator, Photoshop, InDesign) to use at most one additional CPU-second;
- require total system CPU use to stay at or below 65% of available cores;
- the pack's independent memory gate still requires at least 80% free memory.

HID input idle time is reported for context but never blocks on its own. Active
render/export processes (including `kk_mac_video_batch.py`, FFmpeg, Premiere,
After Effects, Media Encoder, Resolve, Final Cut, Blender, or MLX), unknown
resource readings, resident Ollama models, and competing Nest workers remain
hard blocks. Process inspection is command-line/resource-only; it does not
inspect windows, documents, screenshots, or file contents. Since no process
probe can prove that a GPU-only export is idle, known export jobs must remain
hard blocks even if their CPU sample is low.

The probe does not inspect windows, documents, screenshots, or file contents.
Do not close, suspend, or unload owner apps/models. An online Mac is not
necessarily idle; if a separate Nest worker is active, wait for it even when
the design app appears inactive. Report the measured reason when admission is
refused.

When checking for competing Nest workers from a shell preflight, ensure the
process-matching command does not count its own `awk` process. Use an escaped
literal-dot pattern such as `nest-worker[.]py --once` and exclude `awk` rows;
the one worker running the current pack is allowed, a second worker is not.

The shared Nest worker scans every package in its remote root. For a small
smoke test, use an isolated root containing only the explicitly selected
packages and their dependencies; do not run the production root expecting a
one-pack selection.

## Per-cut QC and release gates

- Compare sampled frames with the panel's visible action, not merely the
  scene topic. Confirm actors and props move; camera motion alone is not an
  action pass. Include early, middle, and late frames in the review.
- Reject page-like zooms, slideshows, unexpected extra actors, frozen poses,
  or actions unrelated to the panel. Check ordered subshots and continuity
  across panels without forcing one continuous take.
- Run technical media checks after each cut: non-empty output, codec,
  dimensions, frame count/duration, full decode, black/freeze threshold, hash,
  and private visibility.
- Record technical QC separately from human visual approval. Stop the scene
  chain on failure; a technical pass alone does not approve creative quality.
- Keep private source material and generated previews private. Publishing or
  uploading to public media requires a separate explicit gate.

## Timing and scope

Compare the source panel timecodes with the approved deliverable duration
before rendering. If the source timing would materially exceed the target,
raise one clear decision request with concrete choices (preserve source
timings, retime to the master, or select a shorter subset). Do not silently
compress, omit, or duplicate panels.

## Worked application

The private project crop map and contact sheets demonstrate this procedure:
30 numbered panels across three pages, with hash-bound full/visual crops.
The project-specific source hashes, paths, and timing decision remain in its
private Drive bundle and board card; do not copy them into public KB text.
