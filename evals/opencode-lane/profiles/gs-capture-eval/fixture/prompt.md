Evaluate the Gaussian Splat capture set described in {{TASK}} using ONLY
the mcp-kornia MCP tools — call inspect_image_set on the image_dir, then
score_capture_manifest on the same set; call match_views too when the
set has 20 images or fewer. Emit the JSON artifact exactly per contract
as your final message. Read-only: no training, no deletes, no uploads,
no publishing. If a tool errors, record the error in the artifact
rather than guessing.
