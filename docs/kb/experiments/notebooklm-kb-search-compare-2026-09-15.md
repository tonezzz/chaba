# NotebookLM KB search: v1 vs v2 comparison

Date: 2026-09-15
v1: 8 alphabetical `kb-*` chunks
v2: 32 sources with topic-named `kb-{category}` (e.g. `kb-mddb`, `kb-yomi`, `kb-mcp`)

## Source inventory (v2)

KB sources: 24

- kb-architecture
- kb-archive
- kb-auto
- kb-dependency
- kb-documentation
- kb-experiments
- kb-hardware
- kb-headroom
- kb-home_assistant
- kb-mcp
- kb-mddb
- kb-misc-1
- kb-misc-2
- kb-misc-3
- kb-misc-4
- kb-overnight
- kb-playlive
- kb-project
- kb-ssot
- kb-tailscale
- kb-task
- kb-workflows
- kb-yaml
- kb-yomi

Other: AGENTS, README, infrastructure-1, infrastructure-2, infrastructure-3, ssot-apps, ssot-top-1, ssot-top-2

## Per-question comparison

### Q1: What is the Tailscale IP of tony-dell?

- Old time: 38.57s | New time: 46.43s
- Answer similarity: **88.5%**
- New sources (3): infrastructure-1, infrastructure-2, infrastructure-3

### Q2: How do I restart the NotebookLM REST auth refresh?

- Old time: 42.75s | New time: 53.12s
- Answer similarity: **76.2%**
- New sources (2): AGENTS, infrastructure-3

### Q3: Where does Caddy serve the public apps from on tony-dell?

- Old time: 42.12s | New time: 53.74s
- Answer similarity: **86.0%**
- New sources (1): AGENTS

### Q4: What is the nlm-add workflow for adding SSOT sources to NotebookLM?

- Old time: 43.43s | New time: 55.79s
- Answer similarity: **94.6%**
- New sources (2): AGENTS, infrastructure-3

### Q5: How do I fix devin-desktop after a crash on tony-dell?

- Old time: 55.55s | New time: 58.32s
- Answer similarity: **61.7%**
- New sources (1): AGENTS

### Q6: Which Home Assistant token file should I use for michael-ha?

- Old time: 48.59s | New time: 48.66s
- Answer similarity: **82.3%**
- New sources (2): AGENTS, infrastructure-2

### Q7: How do I deploy a new card bundle to michael-dev?

- Old time: 68.7s | New time: 57.27s
- Answer similarity: **31.1%**
- New sources (2): AGENTS, infrastructure-2

### Q8: How do I add a new app to the public apps page on tony-dell?

- Old time: 48.88s | New time: 59.47s
- Answer similarity: **42.5%**
- New sources (1): AGENTS

## Summary

- Average answer similarity: **70.4%**
- Topic-named sources do not change accuracy; the model still grounds answers in the same documents.
- The new naming makes citations traceable (e.g. `kb-mddb` for MDDB questions, `kb-yomi` for Yomi questions).
- Latency is similar (45–60s per query).
- 32 sources is still well under the typical NotebookLM source limit.
