# Market Report — design

**Status:** approved (kanban: `market-report-design`)
**Ask (2026-10-06, Tony):** a structural report covering Thai gold, USD/THB,
other FX, and interesting stocks — published to CMS, usable by Ada.
**Decisions (2026-10-06):** rolling page (no daily leafs); watchlist =
`^SET.BK` + PTT/AOT/KBANK/DELTA `.BK`; feeds Ada's **proactive morning
briefing**.

## 1. What it is

A daily generated CMS page `market-report` (en + th): a fixed-section brief of
the market series we already own, rendered from the trade DB. Not a live
dashboard — a snapshot with provenance, regenerated once per day after ingest.

Structure follows the CMS page-family standard:
`index → rollup → leaf`. For v1, a single page is enough:

| Slug | Lang | Role | Contents |
|---|---|---|---|
| `market-report` | en, th | rollup | all sections below |

A `market-report` index + per-asset leaf pages only if sections grow long
enough to warrant splitting — not for v1.

## 2. Data sources

Everything except SET stocks is already in the trade prod DB
(PostgreSQL on tony-dell, tailnet `100.68.142.13:5432`, db `trade`):

| Section | Table | Key fields | Coverage |
|---|---|---|---|
| USD/THB + majors | `exchange_rates` | `date`, `quote_currency`, `rate` | 24 ccy, 1971+ |
| DXY | `dollar_index` | `date`, `value` | 1973+ |
| Thai gold bar | `commodity_prices` | `commodity='gold'`, `source='gta-api'` | 2006+ |
| XAU/USD, WTI | `commodity_prices` | `symbol='XAUUSD'` / `'USOIL'` | 1986+ |

Schema ref: `trade/src/models.py`. Series registry:
`trade/config/ssot/ssot.datasource-catalog.sources.yml`.

**Stocks:** no SET stock data in the DB; fetch at render time from Yahoo.
Verified live 2026-10-06: `^SET.BK` (SET index — the earlier "dead ticker"
note was stale), `PTT.BK` 41.25, `AOT.BK` 58.75, `KBANK.BK` 236,
`DELTA.BK` 268 all return. `^SETI` returns null — don't use it.

- **v1 (approved):** `^SET.BK` + PTT/AOT/KBANK/DELTA `.BK`, Yahoo chart API
  at render time.
- **v2 (option):** persist fetched quotes to a `stock_prices` table so the
  report and `ada_market_quote` share one source of truth.

**Trade API note (fixed 2026-10-06):** `trade-api` :9002 looked dead — root
cause was `async def` endpoints calling blocking sync SQLAlchemy on the
single uvicorn worker; one unbounded request starved the event loop so
every endpoint queued. Fixed: 26 handlers converted to sync `def`
(threadpool), `sqlalchemy<2.1` pinned (2.1 flips `postgresql://` to the
missing psycopg3 driver), explicit `postgresql+psycopg2` in
`database_config.py`. Commits on `research/banpu-ptt-strategy`. Generator
still uses **direct SQL** — simpler, no HTTP dependency.

## 3. Queries

Per series: latest row + the row ~7d and ~30d back for deltas.
Rule: use `ORDER BY date DESC LIMIT n` — never `date = today-1`
(weekends/holidays; Thai gold only fixes on business days).

```sql
-- pattern per series
SELECT date, rate FROM exchange_rates
WHERE quote_currency = 'THB' ORDER BY date DESC LIMIT 32;
```

Same shape for `dollar_index.value` and `commodity_prices.price`
(filtered by `symbol`/`source`). Thai gold section needs the last N rows
of `source='gta-api'` — includes buy/sell bars + ornaments.

## 4. Page rendering

Managed block per ssot.apps.cms-reports.yml:

```markdown
<!-- market:auto -->
<!-- generated: 2026-10-07T07:30+07:00 · source: trade-db (tony-dell) -->
### FX — USD/THB 33.42 (+0.3% d/d, −0.8% w/w)
| EUR | JPY | CNY | … |
### Gold — ทองแท่ง ขายออก 41,650 ฿ (+250) · XAU/USD 4,012
### DXY 97.2 (+0.1%)
### WTI $61.3
### SET watchlist — PTT 33.25 … 
<!-- /market:auto -->
```

Body static text (edit sections, caveats, links) lives outside the block —
same pattern as `flood-report`. Footer provenance is auto-appended.

Metadata: `generated_by: market-report-update.py`,
`sources: [trade-db:exchange_rates, trade-db:dollar_index,
trade-db:commodity_prices, yahoo:set-watchlist]`,
`report_role: rollup`, `parent` unset (top-level like `flood-report`).

## 5. Generator + schedule

- Script: `scripts/ada/market-report-update.py` — psycopg2 direct to
  `100.68.142.13:5432` (read-only user), renders en + th bodies, POSTs to
  MDDB via `ada-mddb-cli` (same as `flood-news-update.py`).
- Runs on **tony-dell** (local to the DB; matches flood pattern of
  scripts living where the data is).
- Timer: `ada-market-report.timer`, daily **07:30 ICT** — after
  `gta_history.py`/`yahoo_*` ingest completes, before Tony's morning.
- **Morning briefing (approved):** after publishing, the script also
  leaves a `market_briefing` hint that Ada's proactive morning routine
  reads — implementation detail TBD with the briefing pipeline (likely
  an `ada_remember` general-tier note the morning skill picks up, or a
  flag file the briefing script reads). Do not call Ada directly.
- Registry: `ada-cms-automation` doc `market-report` —
  `generated_by`, schedule, `pages: [market-report]`, `owner`.

## 6. Failure rules

- **Stale series:** if latest row for a section is >3 calendar days old,
  render `⚠ data as of YYYY-MM-DD` on that section — never fabricate.
- **DB unreachable:** log + `ada_remember` (general tier) + leave page
  untouched — a stale page with provenance beats a missing one.
- **Stock fetch fails:** section renders "unavailable"; FX/gold still publish.

## 7. Relation to Ada

- This report is the **audit/human surface**. The `ada_market_quote` tool
  (kanban `ada-market-tool`) answers ad-hoc voice queries from the same
  queries — keeping one data path for both.
- Ada can already say "check the market report" once the page exists;
  the tool is what turns it into live numbers.

## 8. Open questions — answered

1. ~~Stock watchlist~~ → `^SET.BK` + PTT/AOT/KBANK/DELTA `.BK` (approved).
2. ~~Spoken briefing~~ → yes, proactive morning briefing (approved).
3. ~~Rolling vs snapshots~~ → rolling page, no daily leafs.
4. THB cross-rates: USD-pairs only for v1 (THB crosses easy to add later).

## 9. Build order

1. `scripts/ada/market-report-update.py` (SQL → markdown, en+th)
2. Publish `market-report` en+th manually once; then hand to the timer
3. Registry doc `ada-cms-automation/market-report`
4. `ada-market-report.timer` on tony-dell
5. `cms-audit.py` — registry, generated_by, balanced block
6. `market_report` scenario — Ada answers "what's the market report" + summary

API fix is out of scope here; file it separately.
