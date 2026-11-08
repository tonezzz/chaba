# Lane CMS coverage procedure

Status: defined 2026-10-12 (card lane-cms-content-model)

## Declare

Each persona lane declares its CMS coverage in `persons.<id>.cms` inside
`docs/ssot/apps/ssot.apps.ada-persons.yml`: a map of section →
`{producer, cadence, source_allowlist}`. A lane with no `cms` block serves
no curated sections.

## Producers

CMS producers are collection-scoped and source-allowlisted. Member lanes
may only write to public zones — private/ops collections never appear in
a member lane's allowlist.

## Audit

Run a cms-auto-health-style coverage audit per lane: every declared
section exists on the CMS and is fresh within its cadence. Missing or
stale sections file an audit card rather than being silently served.

## Truthfulness

Every served section carries `fresh_for` plus timestamps. When Ada (or
any agent) quotes CMS data, she states the data's age — stale content is
never presented as current.
