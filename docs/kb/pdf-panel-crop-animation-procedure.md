# PDF panel cropping and shot animation procedure

## Two output variants

Every storyboard panel has two deliberate image variants:

```text
review variant:
  keeps shot ID/time/title overlay for human review and traceability

clean render variant:
  removes all storyboard text, captions, bubbles, and borders
```

The review variant is never the final-public image source. It is a reference
artifact that lets reviewers identify a shot while checking composition.

## Crop contract

For every panel, record:

```text
source PDF hash
page
shot ID
crop rectangle
overlay policy
output dimensions
prompt
seed
frame count
steps
```

The crop must exclude unrelated neighboring panels and captions. Review crops
may retain only the panel's own ID/time/title strip. Clean crops must contain
only the intended image content.

## Animation contract

1. Render a short review control first.
2. Use a resident MLX pipeline so the model loads once per batch.
3. Keep shots serial on Apple Silicon unified memory.
4. Use 4 steps for fast motion probes; use 8 steps when a shot is static,
   unstable, or needs stronger temporal movement.
5. Prompts must request concrete motion: breathing, blinking, hand movement,
   fabric/hair motion, and a bounded camera move. Avoid vague “make it
   cinematic” instructions alone.
6. Verify every MP4 by decode, frame count, non-black range, dimensions, and
   file size before assembly.
7. Preserve the review variant, clean variant, prompt, manifest, and QC
   result together.

## Promotion gate

```text
review crop + short animation
-> human shot approval
-> clean crop render
-> final-duration render
-> ordered assembly
-> narration/subtitle mux
-> final decode/QC
```

Shot overlays remain enabled for this review pass by Tony's request. They
must be removed before any public final cut.
