---
title: Wiki docs panel UI standard (native MediaWiki)
description: Standard for structuring Education, Infrastructure and Reports wiki pages as native MediaWiki panels with Mermaid, Cargo and the Panel template.
tags: [wiki, mediawiki, ui-standard, panels, education]
created: 2026-11-24
updated: 2026-11-24
category: operations
related: [board-api-write-door.md, app-ssot-standards-content.md, ssot.docs-map.yml, ssot.mediawiki-news.yml]
search_keywords: [panel, mermaid, cargo, template panel, wikitext, education hierarchy, wiki page door]
---

# Wiki docs panel UI standard (native MediaWiki)

**Status:** proposed — native-panel direction approved 2026-11-24 (Tony).
**Applies to:** `Education:`, `Infrastructure:`, `Reports:` pages on
`wiki.h3.gizmo-thailand.com`, and any repo doc that is mirrored to a wiki page.
**Related:** `docs/ssot/infrastructure/ssot.docs-map.yml` (where docs live),
`docs/ssot/apps/ssot.mediawiki-news.yml` (News hierarchy),
`docs/kb/cms-page-standard.md` (CMS report families), and the live
`Wiki:Wiki-Hierarchy` namespace map.

Your wiki already has **Mermaid** and **Cargo** installed (siteinfo,
2026-11-24) plus **CategoryTree** and **PageForms**. That is enough for panels:
no new extension, no Plesk change, and the pages survive export/backup as
ordinary wikitext.

## 1. What counts as a panel

A *panel* is one bounded, titled block that answers one question with a table,
chart, or diagram. A page is a stack of panels, not a wall of prose.

| Panel kind | Wikitext mechanism | Use for |
|---|---|---|
| **Data** | `{| class="wikitable sortable" ... |}` (bare table or `{{#cargo_query:}}`) | Inventories, rate limits, model registries |
| **Chart** | `{{#cargo_query: ... format=bar/chart/pie}}` or a hosted SVG via `[[File:...]]` | Distributions, comparisons, trends |
| **Diagram** | `<graph-mermaid>...</graph-mermaid>` (Mermaid extension) | Hierarchy, flows, dependency chains |
| **Callout** | `{{Panel|tone=info|title=...|body=...}}` (new template, §3) | Verdicts, warnings, "read this first" |
| **Evidence** | Fenced `<syntaxhighlight lang="...">` + source link | Commands, payloads, provenance |

Rule: **every panel carries a source and a verified-on date in its footer.**
A chart with no lineage is decoration.

## 2. Panel anatomy (copy this)

```wikitext
{{Panel
|tone=info
|title=Plan vs API quota — what the upgrade changed
|body=
'''Bottom line:''' Google AI Pro (5 TB) raises Gemini ''Apps''/AI Studio
limits. Gemini API keys are still governed by the project's Cloud billing tier.
}}
{| class="wikitable sortable"
! Surface !! Control knob !! Your value !! Verified
|-
| Gemini Apps (gemini.google.com) || Google AI Pro subscription || 4× standard; 1M ctx || 2026-11-24
|-
| AI Studio web playground || "Google AI" billing option || burns subscription quota || 2026-11-06
|-
| Gemini API key || Cloud billing tier || unchanged by AI Pro || 2026-11-24
|}
<small>''Source:'' one.google.com/about/plans · support.google.com/gemini/answer/16275805 ·
[[Infrastructure:LLM Gateway#google_ai_pro|LLM Gateway SSOT]] — verified 2026-11-24.</small>
```

## 3. Templates to add (one-time, via `/wiki/page` door)

Two small templates, created as `Template:Panel` and `Template:PanelChart`:

```wikitext
<!-- Template:Panel — tones: info|warn|ok|danger -->
<div class="oc-panel oc-panel-{{{tone|info}}}" style="border-left:4px solid {{{color|#4f46e5}}};padding:.6rem 1rem;margin:.8rem 0;background:#f8fafc">
<div style="font-weight:600;margin-bottom:.35rem">{{{title|}}}</div>
<div>{{{body|}}}</div>
</div><noinclude>[[Category:Wiki UI Templates]]</noinclude>
```

```wikitext
<!-- Template:PanelChart — Cargo-backed chart with a mandatory source line -->
<div class="oc-panel-chart" style="padding:.6rem 1rem;margin:.8rem 0">
<div style="font-weight:600">{{{title|}}}</div>
{{#cargo_query:tables={{{table|}}}
 |fields={{{fields|}}}
 |format={{{format|bar}}}
 |limit={{{limit|100}}}
}}
<small>''Source:'' {{{source|unspecified}}} — verified {{{verified|unverified}}}.</small>
</div><noinclude>[[Category:Wiki UI Templates]]</noinclude>
```

Namespace note: your wiki's lesson template is `แม่แบบ:Education` (Thai
alias). Put the new templates in `Template:` (English) and add the Thai aliases
only if the Education template already follows that pattern — check before
creating, since `/wiki/page` only allowlists configured template names.

## 4. Hierarchy rule (one canonical home)

The panel standard is a *rendering* standard, not a second doc store. Content
stays where `ssot.docs-map.yml` says:

| Layer | Lives in | Role |
|---|---|---|
| Machine state / quota verdict | `docs/ssot/**` | Edit here; verdict rows only |
| Human explainer | `Education:<Topic>` | Panels + prose; mirrors to `chaba-lessons` |
| Runbook / procedure | `docs/kb/<slug>.md` | Editors' procedure incl. this standard |
| Dated audit | `docs/reports/<date>-<slug>.md` | Frozen snapshot |

**Gemini access family (proposed):**

```
Education:LLM Providers                         rollup (exists)
├── Education:LLM Providers/Gemini API           ← update: models, tiers, limits
├── Education:LLM Providers/Gemini API/Access & Plans   ← new leaf (AI Pro vs API tiers)
├── Education:LLM Providers/Gemini API/Rate Limits     ← new leaf (RPM/TPM/RPD + tiers)
├── Education:LLM Providers/Gemini API/QC              ← new QC leaf (staleness, source coverage)
├── Education:LLM Providers/Gemini API/System Adjustments ← new leaf (tier/model/batch proposal)
├── Education:LLM Providers/LiteLLM Key Management     (exists)
├── Education:LLM Providers/Openrouter                 (exists)
├── Education:LLM Providers/Cloudflare Workers AI      (exists)
├── Education:LLM Providers/Ollama                     (exists)
└── Education:LLM Providers/Groq                       (exists)
```

The rollup links down to every leaf; each leaf links back up and names its SSOT
source. QC counts leaves past their verify date and flags model IDs that no
longer appear in the official catalog.

## 5. Freshness contract

- Panels that quote prices/limits must show `verified YYYY-MM-DD`.
- `fresh_for` equivalent: 30 days for price/limit panels, 90 days for concept
  panels. Past that, the QC page flags the leaf ⚠STALE.
- Never hard-code another account's RPM/TPM/RPD. Say "read your dashboard".
- Deprecations carry an effective date (e.g. 2.5 Flash/Pro auto-route 2026-12-01).

## 6. Review checklist

- [ ] One question per panel; lede states the verdict.
- [ ] Every data/chart panel has source + verified date.
- [ ] Mermaid used for structure, Cargo for structured data, tables for small sets.
- [ ] Leaf links to rollup; rollup links to leaf; QC counts the family.
- [ ] No secrets, tailnet topology, or account-specific quota copied into public pages.
- [ ] Composite wikitext validated on a scratch page before writing the canonical title.
