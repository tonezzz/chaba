# Market Report — design

**Status:** design (kanban: `market-report-design`)
**Ask (2026-10-06, Tony):** a structural report covering Thai gold, USD/THB,
other FX, and interesting stocks — published to CMS, usable by Ada.

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

**Stocks (the gap):** no SET stock data in the DB. Options:

- **v1:** fetch a small watchlist (e.g. `PTT.BK`, `AOT.BK`, `KBANK.BK`,
  `DELTA.BK`) from Yahoo at render time — 5 tickers is cheap. `^SET.BK` was
  a dead ticker on Yahoo (today's probe confirmed); use `^SETI` or skip the
  index and rely on constituents.
- **v2:** persist fetched quotes to a new `stock_prices` table so the report
  and the future `ada_market_quote` tool share one source of truth.

**Trade API note:** `trade-api.service` on tony-dell (port 9002) answers `/`
but data endpoints hang (observed 2026-10-04 — DB query stall, likely needs
the postgres-era code path or index attention). The generator should use
**direct SQL**, not the HTTP API. Fixing the API is a separate card.

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

## 8. Open questions

1. Stock watchlist contents — which names does Tony actually want daily?
2. Does the spoken briefing need it (proactive morning read) or is
   pull-only enough for v1?
3. THB cross-rates worth showing (THB/JPY, THB/EUR) or USD-pairs only?
4. Retention: does each day snapshot into a leaf page, or is
   `market-report` rolling? (v1: rolling — leafs only if asked.)

## 9. Build order

1. `scripts/ada/market-report-update.py` (SQL → markdown, en+th)
2. Publish `market-report` en+th manually once; then hand to the timer
3. Registry doc `ada-cms-automation/market-report`
4. `ada-market-report.timer` on tony-dell
5. `cms-audit.py` — registry, generated_by, balanced block
6. `market_report` scenario — Ada answers "what's the market report" + summary

API fix is out of scope here; file it separately.
