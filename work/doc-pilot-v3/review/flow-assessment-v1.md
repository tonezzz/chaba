# Solar-System Documentary: Current Flow Assessment and Tourist-View Proposal

Status: review note for Tony; scoped to the private KK review cut. No public distribution or new GPU spend is proposed here.

## Current flow: proven strengths

- The 7-stage path is demonstrated end to end: idea/treatment → Thai-first script → storyboard → prompt embeddings → per-shot LTX clips → Tony-clone Thai VO → FFmpeg assembly/QC.
- Per-shot assets and reports are durable and independently replaceable in Drive; v6 has a fact-checked script, Thai subtitle track, finite-audio verification, and per-scene timing.
- A NASA-still/2.5D proof demonstrated a CPU-only alternative for static facts: Earth and Saturn use attributed stills with a consistent starfield, glow, small camera move, Thai narration, and credits.
- The hybrid v6 cut combines that approach for Earth/Saturn with LTX for the other 16 scenes; the 640x384/24fps review cut is technically playable without a new GPU node.

## Current flow: costs and weaknesses

- The film has several near-duplicate versions of scripts, storyboards, hard-coded TTS beats, and pack inputs. A change to one line can leave VO, subtitles, and the making-of post out of sync.
- Fixed 73-frame LTX shots do not naturally match Thai narration duration; v1 exposed a final-frame freeze, and v5 exposed a long Kuiper hold. v6 improves this by aligning holds per scene, but script duration should be checked before voice generation.
- Full LTX for every shot spends scarce GPU time on static planet portraits that can be represented more accurately and cheaply with sourced stills.
- NASA and partner imagery requires per-asset rights/credit checks; finding a file on a NASA site is not a blanket license. The Pluto candidate returned HTTP 403 and was deferred rather than worked around.
- At 640x384 the v6 cut is a review artifact, not a presentation master; motion continuity, image quality, sound design, and audience response still need human review.

## Recommended efficiency changes

1. Use one versioned shot manifest as the source of truth: Thai/English narration, target duration, object facts, distance/size callouts, source ID/credit/rights, visual method, ship-layer note, prompt, and subtitle text.
2. Make VO, subtitle, and assembly packs read that manifest instead of duplicating Thai beats. Cache by content hash and regenerate only changed audio/visual shots.
3. Use NASA/2.5D composites for still, fact-heavy views; reserve LTX/T4 for transitions, camera motion, storms, and scenes that benefit from generated movement.
4. Keep one reusable fictional, unbranded tour-ship layer and one callout template. Render labels/subtitles after image generation so text stays legible and accurate.
5. Display mean Sun distance in AU plus rounded million-km values, and equatorial diameter in km. Show the Moon's mean distance from Earth separately. State that cinematic views are not to scale.
6. Add gates before final export: numeric/source check, voice finite/peak/CER check, per-shot visual check, subtitle-timing check, complete-file playback, and Tony/KK acceptance.

## Tourist-ship script proposal

The review draft is `script-v3-tourist-review.yml`. It keeps the current audience (KK), Thai-first narration, and a short 18-shot structure; adds a fictional small tour ship as a recurring viewpoint; includes the Moon; and adds on-screen distance/diameter labels for the Sun, Moon, eight planets, and Pluto. The Kuiper Belt is labeled as a region with an estimated population, not as a single body with a diameter. It remains a draft until Tony reviews the ship viewpoint and scope.

No script-v3 VO, storyboard, render, or public-share operation is launched by this note.

## Research candidates assessed (2026-10-26)

The OPS-0793 research preview had a useful architecture proposal and a tool shortlist, but it was only a summary. I checked the main candidates and separated production tools from evaluation benchmarks and simulation tools.

### Use now: methods, not a large dependency stack

- The proposed control plane is sound: story truth → object/ship/lighting bible → storyboard graph → scratch-VO animatic → controlled generation → temporal finishing → QA/QC. For this film, an object/asset bible is more useful than a character bible.
- **VBench-2.0** ([repo](https://github.com/Vchitect/VBench/tree/master/VBench-2.0), Apache-2.0) adds physics, commonsense, controllability, and composition measures. Its CUDA/MMCV/vision dependencies are excessive for this 18-shot review cut. Borrow a few rubric dimensions; do not install the full benchmark now.
- **T2V-CompBench** ([repo](https://github.com/KaiyueSun98/T2V-CompBench), CVPR 2025) evaluates spatial relations, attribute binding, motion, interactions, and generative numeracy. Use those categories to make shot tests such as “ship remains in foreground,” “rings stay attached to Saturn,” and “the callout matches the planet.” Render numeric text as an overlay rather than asking a video model to spell it correctly.
- **VideoScore2** ([repo](https://github.com/TIGER-AI-Lab/VideoScore2), MIT) gives multi-dimensional video critiques. Treat it as a secondary judge only: its model stack and inference requirements are not necessary to decide whether a short Thai family documentary works for KK.
- Use a lightweight 0–2 rubric on three existing v6 shots (Earth, Saturn, Jupiter): fact/object accuracy; temporal stability; visual/prompt fit; Thai caption legibility/timing; and narration clarity. Assess Moon callouts and ship continuity only after the v3 review draft is approved and those assets exist. A low score must identify a repairable issue, not trigger an automatic full rerender.

### Candidate tools: fit and decision

| Candidate | Fit to this project | Decision |
|---|---|---|
| [DepthFlow](https://github.com/BrokenSource/DepthFlow) | Directly makes 2.5D parallax from stills. It is AGPL-3.0 and depends on depth estimation/GPU; the current Pillow/FFmpeg compositor already works on CPU. | Best optional A/B test if the current parallax looks flat; run separately and review license before integrating. |
| [SCoPE](https://github.com/TencentARC/SCoPE) | Camera-trajectory-conditioned I2V, released for Wan2.2-I2V-A14B; Apache-2.0. It could help controlled ship flybys, but is a different and much heavier model stack than LTX. | Defer until a larger GPU is available; first test a small camera-trajectory spec in the storyboard. |
| [StoryDiffusion](https://github.com/HVision-NKU/StoryDiffusion) | Strong image/character consistency ideas; the repo still lists video-generation source and weights as incomplete, and the method is SD1.5/SDXL-oriented rather than LTX-native. | Borrow the reference-sheet/consistency-bible idea; do not adopt as the video backend. |
| [Director](https://github.com/juspay/director) | Useful pipeline precedent: resumable phases, keyframe checks, scoring, captions, and cost tracking. It is provider/NeuroLink-oriented and its 10-star maturity signal is limited. | Adapt the workflow patterns only; do not replace our packs or add paid API calls. |
| [BlenderProc](https://github.com/DLR-RM/BlenderProc) | Mature GPL-3.0 synthetic-dataset generator, not a short-film compositor. | Not needed; use plain Blender only if a precise scale map or ship asset requires it. |
| [FlyByGen](https://github.com/RicDen/FlyByGen) / [SISIFOS](https://github.com/JasonVel6/SISIFOS) | Synthetic comet/asteroid datasets and spacecraft rendezvous/proximity-operation imagery, respectively; specialized research simulators rather than planet-tour generators. | Defer; reconsider only if we add an asteroid/comet or close spacecraft-operation sequence. |
| [DWPose](https://github.com/IDEA-Research/DWPose) | Human whole-body pose estimation. The current story has no actor or astronaut. | Not applicable unless a human character is added. |
| [FILM](https://github.com/google-research/frame-interpolation) / [RIFE](https://github.com/hzwer/ECCV2022-RIFE) | Frame interpolation can smooth motion but may warp rings, planet edges, or text and adds compute. | Do not apply globally at 24 fps; test only on a specific motion defect. |
| [OmniSG](https://github.com/scene-graph/OmniSG) / [Vid2Sim](https://github.com/Vid2Sim/Vid2Sim) | Scene-graph extraction and interactive urban simulation, not documentary shot generation; OmniSG is very new/low-star. | No direct fit. Our per-shot manifest should be simpler and source-controlled. |
| `ai-ci` | The preview did not identify a repository or URL; searches return unrelated video-evaluation/CI projects. | Need the exact link before assessing or adopting it. |

### Recommended next experiments

1. Use the 0–2 manual rubric on three private shots and record whether each issue can be fixed by an overlay, a new still, a VO edit, or an LTX rerender.
2. Keep the present CPU compositor as the baseline. Only compare DepthFlow on one already-cleared Earth or Saturn still if it can demonstrate better edges/parallax; do not copy AGPL code into our pipeline without a license review.
3. When the larger GPU node arrives, compare a controlled-camera I2V option such as SCoPE with the existing LTX lane. Until then, build and validate camera paths as storyboard metadata rather than downloading a 14B model.
