# Task: bounded single-file write — {{TASK}}

Job {{JOB}} on host {{HOST}}. Write EXACTLY ONE file — the artifact
path declared in the job spec (repeated in the lane rails below) —
using the write or edit tool. Ground the content in real reads of
this checkout: cite real paths, real enums, real function names.

- `{{TASK}}` is the content spec: what the file must contain.
- Markdown; no TODO/TBD/FIXME/placeholder markers; the file must have
  real substance (the held-out verifier rejects stubs).
- You have NO shell — read/grep/glob/list only for inputs.
- Do NOT emit the document as your final message — write the file,
  then end with a one-line summary of what you wrote.
- Writes outside the declared artifact path, or any bash call, fail
  the job. Every denied call is recorded.
