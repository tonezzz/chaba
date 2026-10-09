# Dispatch outcome — ha-staging-actuation-guard

Delivered the staging-clone actuation guard for future `tony-dev`/`ada-dev` twins.
`scripts/home-assistant/stage-clone.sh` copies a prod HA config to a target dir
and applies `scripts/home-assistant/staging-overlay.py`, an SSOT-driven engine
whose strip/stub policy lives in reviewable SSOT
(`docs/ssot/infrastructure/ssot.home-assistant.staging-overlay.yml`). The overlay
keeps config byte-identical where possible — PyYAML node marks drive surgical
text splices so only write-path lines change — while neutralizing every outbound
actuation path: automations get `initial_state: false` plus `disabled_by: user`
in the entity registry, scripts/intent_scripts become `stop: staging-noop`,
shell_commands become logged no-op echoes, rest_command URLs sink to a refused
`127.0.0.1:9` endpoint (which also neuters mha_mirror template-switch writes),
external notify platforms and outbound state feeds (influxdb/mqtt) are dropped,
write-capable `.storage` config entries (tuya, cast, mobile_app, mqtt, cloud,
hue/shelly/zha…) are disabled, actuating yaml domains are removed, and
`http.server_host` is dropped with podman trusted-proxies added so a
Podman-networked container stays reachable. Sensors, history, dashboards,
Lovelace resources and themes are preserved; the runner refuses prod dirs,
non-marker targets, and same-path clones, and leaves a `.staging-guard/report.json`
audit trail. The card's open question is decided in-card: staging test
automations use `mha_mirror_*`/`dev_*` mocks, never real entities. Verified:
13/13 unit tests pass; end-to-end fixture clone applies 26 surgical changes and
`verify` exits 0 with only two intentional review warnings (a kept
`command_line` sensor, enabled review-tier frigate entry); all safety guards
exercised. Note: `node` is absent in this environment so
`ssot-validate-all.mjs` could not run — all touched YAML files parse cleanly and
index paths resolve (the two missing index paths are pre-existing drift).
Remaining runtime verification (24h logbook watch on a booted twin) belongs to
card `ha-dev-instances`, which this unblocks. Docs trail: runbook
`staging_actuation_guard` in `ssot.home-assistant.howto.yml`, job record
`docs/ssot/jobs/home-assistant/2026-10-09-staging-actuation-guard.yml`, index
entries, card moved to `review`. Committed on the dispatch branch; not pushed.
