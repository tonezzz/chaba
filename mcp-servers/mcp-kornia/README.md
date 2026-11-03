# mcp-kornia

Read-only image-set evaluation tools for Gaussian Splat capture triage.

The first tool is deterministic and has no model or network requirement.
Kornia-backed matching/masking tools can be added behind the same interface
without changing Ada's contract.

Run locally:

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

The server never trains, edits, uploads, deletes, or publishes media.
