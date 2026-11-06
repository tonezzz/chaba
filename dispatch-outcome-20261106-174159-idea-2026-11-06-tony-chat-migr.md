# Dispatch outcome — wiki member-knowledge surface (idea → plan + decision)

Card: `wiki-member-knowledge-surface-migrate-wp-3a1cf2`
Runner: tony-macbook · 2026-11-06

## What changed the card's premise (verified live)

The card brief analyzed a three-way engine decision (MediaWiki beside WP /
Wiki.js / ada-cms-pages). Verified today: **the wiki already exists and is
fully integrated** — the brief's "recommended option A" is already built:

- `wiki.h3.gizmo-thailand.com` — MediaWiki 1.46.2, PHP 8.3, MariaDB, th/en —
  on the SAME managed host (103.99.11.249) as boards.h3/chaba.h3;
  boards.surf-thailand.com fronts it via Cloudflare.
- Extensions installed (via door `/wiki/extension` list): Lockdown,
  CategoryTree, Mermaid, MsUpload, MultimediaViewer, Cargo, PageForms,
  PluggableAuth, OpenID Connect, Springboard.
- **Private boundary enforced**: anon content read on `PrivateNews:` and
  `Infrastructure:` returns accessdenied (Lockdown). Hosts tree already
  populated under `Infrastructure:`.
- board-api `/publish` registers 9 sinks incl. `wiki` (public, News/) and
  `wiki-private` (private, PrivateNews:); `/wiki/news-review` +
  `/wiki/news-diagnose` give a card-authorized private→public promotion
  workflow; Springboard gives an extension-control door.
- SSO login live (PluggableAuth/OIDC); users: Ada, Tony, Tonezzzz@gmail.com.
- Lesson corpus: **124 posts** (door `/lesson op=topics`); ~half ops-internal
  by topic (procedures, fleet/tool names).

## Result

- Posted card comment with the corrected verified state.
- Raised board request `wiki-member-knowledge-surface-the-wiki-a-0b8e38`:
  scope decision — **★ A** protected `Education:`/`Reports:` namespaces on
  wiki.h3 (needs one LocalSettings edit via the Plesk/admin path that made
  `PrivateNews:`/`Infrastructure:`), staff-only readers at cutover, WP lesson
  CPT read-only+301; B = public Education tree w/ split; C = stay in WP.
  Also asks who can edit LocalSettings.
- No production writes to wiki or WP were made; the only live calls were
  read-only (siteinfo, allpages, access checks, `/publish op=sinks`,
  `/lesson op=topics`, `/wiki/extension list`) plus card comment/request.

## Files

- NEW `docs/ssot/jobs/education/2026-11-06-wiki-member-knowledge-surface.yml`
  — full structure plan: namespace map, Education template/categories,
  migration mechanics (door-export → wikitext, MediaWikiSink retarget,
  dual-write→cutover, 301s, lessons-due/education-report retarget via
  Cargo), decision matrix, implementation sequence.
- EDIT `docs/ssot/apps/ssot.mediawiki-news.yml` — drift repair only:
  phase_1/phase_2 marked installed, Lockdown boundary marked enforced,
  Springboard/OIDC/namespaces recorded, install_gate superseded by the
  extension door (LocalSettings edits still admin/Plesk).

## How to verify

- `curl -s "https://wiki.h3.gizmo-thailand.com/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&titles=Infrastructure:Hosts&format=json"` → accessdenied (anon) proves the boundary.
- `POST /publish {"op":"sinks"}` on board-api → 9 sinks incl. wiki/wiki-private.
- `POST /wiki/extension {"action":"list"}` → installed set.
- Plan doc at `docs/ssot/jobs/education/2026-11-06-wiki-member-knowledge-surface.yml`.

## Blocked on

Tony's scope answer (A/B/C) + the LocalSettings admin path for the two new
namespaces — both captured in the board request; next dispatch can execute
the migration end-to-end once answered.
