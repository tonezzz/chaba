# Media inbox standard — received-media page family & dedup

**Status:** defined (card `media-inbox-report`)
**Applies to:** every file/photo/video/audio a lane receives over LINE (and
TG when its relay gains file ingest) — the durable record of "what arrived,
from whom, what was in it."

Follows `cms-page-standard.md` (§4 family pattern) and mirrors
`house-timeline-update.py` — same rollup/leaf/QC shape, different source.

---

## 1. Why a page family

A received file today lives in three places: archive bytes
(`~/.local/share/ada/line-media/<chat>/<messageId>.<ext>`), a
`manifest.jsonl` line, and a journal entry. None of those answers "what
documents do we have?" — a person can't grep a journal. The page family is
the human surface over the same records; the manifest stays the machine
authority.

## 2. Page family — `media-inbox`

Per lane, in that lane's `ADA_CMS_COLLECTION` (kk → `ada-cms-pages-kk`, tony
→ `ada-cms-pages`):

```
media-inbox                 rollup — one row per received item, newest first
media-<messageId>           leaf   — receipt record for one item
media-<messageId>-extract   leaf   — doc_read extraction, written lazily
media-inbox-qc              leaf   — coverage/dup/parse self-checks
```

**Receipt leaf** (`media-<mid>`) — generator-owned, rendered from the
manifest line:

```markdown
# Media — <fileName or mid> · <YYYY-MM-DD HH:MM>

<One line: who sent what, when, over which chat.>

## Receipt
| field | value |
|---|---|
| sender | <display label> |
| chat | <chat_id> |
| kind | file / video / image / audio |
| file | <fileName> (<mime>, <size>) |
| message_id | <mid> |
| sha256 | <first 16 chars> |
| archive | [<mid>.<ext>](<relay-img URL>) |
| duplicate_of | <media-<earlier-mid> or —> |

---
_meta: parent=media-inbox · report_role=leaf · sources=manifest.jsonl_
```

**Extract leaf** (`media-<mid>-extract`) — `doc_read`-owned. Written the
first time extraction runs for that mid; never re-rendered by the generator.
Carries the structured fields (booking ref, dates, route, totals) plus
`parent: media-inbox` and `sources: doc_read + <archive path>`.

**Rollup** — day-grouped table
`| when | sender | file | kind | dup | leaf | extract |`, last N days
(default 30), links down both directions. `media-inbox-qc` reports:
manifest lines without leaves, leaves without manifest lines (stale),
duplicate chains, extraction coverage.

**Adoption rule:** the rollup adopts any leaf carrying
`meta.parent: media-inbox` — so trip pages can ALSO point at a leaf
(`attachments:` / bookings `doc:` column) without owning it. A media leaf
has exactly one parent; it may be *referenced* from anywhere.

## 3. Deduplication — three tiers

Duplicates arrive three different ways; each tier answers a different
"is this the same?" question. **Never merge — mark and link.**

| Tier | Trigger | Key | Behavior |
|---|---|---|---|
| **T1 transport** | LINE webhook redelivery (retry/timeout) | `message_id` | Archive write is already idempotent (`dest.exists()` → no rewrite). Generator groups manifest lines by `message_id` → **one leaf per mid**, extra manifest lines noted on the leaf, not new leaves. |
| **T2 content** | Human resends the same file (new messageId) | `sha256` of archived bytes | A resend is a real second event — it GETS a leaf (someone resent it on purpose), but the leaf carries `duplicate_of: media-<first-mid>` and the rollup `dup` column shows `↳ <first-mid>`. Extraction redirects: `doc_read` on a dup mid returns the first mid's extract leaf. |
| **T3 extraction** | "Read it again" / re-asks | extract leaf + normalized ask | `doc_read` checks `media-<mid>-extract` **before** calling Gemini. A bare "read it" returns the stored default extraction. A **different ask** ("what's the hotel?" vs "what's the flight?" vs "translate it") appends a new `## Extraction — <ask>` section to the same leaf — extractions accumulate, each labeled with the question asked. The leaf is the cache; the tool decides, not the model. |

Tier order matters: T1 is free and always-on; T2 costs a hash (cheap —
bytes already on disk); T3 is where the money is saved.

**The "asked differently" rule:** extraction results are per-ask, not
per-file — the same PDF legitimately yields different answers to different
questions, and that's not a duplication bug. The cache key is
`(message_id, normalized ask)`; identical re-asks hit the cache, new
angles append a section. What stays single: one receipt leaf per mid, one
extract leaf per mid (sections inside it grow).

## 4. Who writes what (single-writer)

| Writer | Owns | Never touches |
|---|---|---|
| `ada-line-relay` | archive bytes, `manifest.jsonl`, journal | CMS pages |
| `media-inbox-update.py` (timer, per lane) | `media-inbox`, `media-<mid>` receipt leaves, `media-inbox-qc`, `reports-index` regen | extract leaves — re-render skips any `*-extract` slug |
| `doc_read` tool | `media-<mid>-extract` | receipt leaves, rollup |
| Ada (chat) | links/asks only — `cms_read` a leaf to answer "what was that file?" | writing receipt leaves by hand |

The generator is deterministic and free — receipts exist whether or not
anyone asks. Extraction is lazy — only when a human wants the contents.

## 5. Connecting up

- **Rollup → leaf:** `leaf`/`extract` columns link every row.
- **Leaf → rollup:** `meta.parent: media-inbox` + footer link.
- **Trip/booking pages:** when an extract is a booking, the trip generator
  links `media-<mid>-extract` in `bookings | doc |` — the media family
  stays the archive of record, trip pages just reference it.
- **Cross-lane:** leaves live in the receiving lane's collection. A file
  sent to Kaewta is hers; Tony's lane never sees it unless she shares the
  leaf (chat_send the link) or it's re-sent to his lane (new mid, new leaf).

## 6. Public publishing

Receipt/extract leaves are **never** `public: true` — they name senders,
booking refs, and archive URLs. A shareable derivative (e.g. the trip
rollup) is the only public surface, and only after the §5 publish gate
(explicit ask + `confirmed='yes'`).

## 7. Implementation checklist (card `media-inbox-report`)

- [ ] `scripts/ada/media-inbox-update.py` — manifest → family, `--dry-run`,
      mirrors `house-timeline-update.py` (leaf cap, qc, index regen)
- [ ] relay: `sha256` field appended to manifest lines (hash at archive
      time — bytes already in memory); journal entry gains `message_id`
- [ ] `doc_read`: extract-leaf check + write + T2 redirect
- [ ] timer per lane (`media-inbox-update@<lane>`), cadence 15m +
      on-receipt trigger is a v2 nicety, not required
- [ ] scenario: send dup mid → one leaf; send same bytes twice →
      `duplicate_of` set; ask doc_read twice → second call reads the leaf

*Procedure: when anything about "did we get that file / read it again /
show all docs" comes up — this is the answer.*
