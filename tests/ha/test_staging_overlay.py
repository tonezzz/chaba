"""Unit tests for scripts/home-assistant/staging-overlay.py — the staging
actuation-guard transform (card ha-staging-actuation-guard).

Builds a fake prod HA config in a temp dir, applies the SSOT overlay, and
asserts every write path is neutralized while read-only config stays
byte-identical. Pure file ops — no HA, no network.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml


class HaLoader(yaml.SafeLoader):
    pass


HaLoader.add_multi_constructor("!", lambda l, s, n: f"<{s}>")


def ha_load(path):
    return yaml.load(Path(path).read_text(), Loader=HaLoader)


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/home-assistant/staging-overlay.py"
OVERLAY = REPO / "docs/ssot/infrastructure/ssot.home-assistant.staging-overlay.yml"

spec = importlib.util.spec_from_file_location("staging_overlay", SCRIPT)
so = importlib.util.module_from_spec(spec)
spec.loader.exec_module(so)

SINK = "http://127.0.0.1:9/staging-sink"

CONFIG_YAML = """homeassistant:
  name: Tony Home
  internal_url: "https://tony-dell.taila0626a.ts.net:8123"
  packages: !include_dir_named packages

default_config:

http:
  server_host: 127.0.0.1
  ip_ban_enabled: true

recorder:
  db_url: mysql://prod-db/homeassistant
  purge_keep_days: 14

influxdb:
  host: influx.local
  database: ha

mqtt_statestream:
  base_topic: ha

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

shell_command:
  snap_tv: /home/tony/.local/bin/cast.sh --tv
  post_board: "curl -s -X POST https://tony-dell.example/apps/board-api/comment -d '{}'"

rest_command:
  board_comment:
    url: https://tony-dell.taila0626a.ts.net/apps/board-api/comment
    method: POST
    payload: '{"id":"x"}'
  nobito_reload:
    url: http://127.0.0.1:8123/api/services/homeassistant/reload_config_entry
    method: POST

notify:
  - platform: smtp
    name: mail_me
    server: smtp.example.com
    recipient: tony@example.com
  - platform: file
    name: notify_file
    filename: /config/notify.log
  - platform: html5
    name: webpush

mqtt:
  broker: 127.0.0.1
  sensor:
    - name: mqtt_temp
      state_topic: "dev/temp"
  switch:
    - name: mqtt_plug
      command_topic: "dev/plug/set"

switch:
  - platform: mqtt
    name: plug_tv
    command_topic: "ha/plug_tv/set"
  - platform: template
    switches:
      fake_plug:
        turn_on:
          service: script.fake_on
        turn_off:
          service: script.fake_off
  - platform: wake_on_lan
    name: wake_tv

command_line:
  - sensor:
      name: cpu_temp
      command: "cat /sys/class/thermal/thermal_zone0/temp"
  - switch:
      name: gate
      command_on: "ssh gate open"

sensor:
  - platform: scrape
    resource: https://example.com
    name: scrape_read

template:
  - sensor:
      - name: readable
        state: "1"
"""

AUTOMATIONS_YAML = """- id: '1700000000001'
  alias: Cast idle shutdown
  description: ''
  trigger:
  - platform: event
    event_type: timer.finished
  condition: []
  action:
  - service: script.cast_cleanup
    data: {}
  mode: single

- id: '1700000000002'
  alias: Blueprint-driven
  use_blueprint:
    path: motion_light.yaml
  initial_state: 'off'
"""

SCRIPTS_YAML = """cast_cleanup:
  alias: Cast cleanup
  mode: single
  sequence:
  - service: media_player.turn_off
    target:
      entity_id: media_player.tony_tv_cast
  - delay: '00:00:05'

plug_cycle:
  fields:
    plug: {}
  sequence:
  - service: switch.turn_off
    target:
      entity_id: switch.plug_tv
"""

SCENES_YAML = """- id: '1700000000009'
  name: Movie time
  entities:
    light.lounge:
      state: 'off'
  icon: mdi:movie
"""

PKG_YAML = """timer:
  cast_idle:
    duration: '00:05:00'

automation:
- id: cast_idle_shutdown
  alias: 'Cast: idle shutdown'
  trigger:
  - platform: event
    event_type: timer.finished
  action:
  - service: script.cast_cleanup
  mode: single

script:
  cast_power_on:
    alias: Cast power on
    sequence:
    - service: switch.turn_on
      target:
        entity_id: switch.plug_tv
"""

CONFIG_ENTRIES = {
    "version": 1, "minor_version": 1, "key": "core.config_entries",
    "data": {"entries": [
        {"entry_id": "t1", "domain": "tuya", "title": "Tuya",
         "disabled_by": None, "data": {}, "options": {}},
        {"entry_id": "s1", "domain": "sun", "title": "Sun",
         "disabled_by": None, "data": {}, "options": {}},
        {"entry_id": "m1", "domain": "mobile_app", "title": "iPhone",
         "disabled_by": None, "data": {}, "options": {}},
        {"entry_id": "f1", "domain": "frigate", "title": "Frigate",
         "disabled_by": None, "data": {}, "options": {}},
    ]},
}

ENTITY_REGISTRY = {
    "version": 1, "minor_version": 1, "key": "core.entity_registry",
    "data": {"entities": [
        {"entity_id": "automation.cast_idle_shutdown", "disabled_by": None,
         "platform": "automation", "unique_id": "a1"},
        {"entity_id": "automation.other", "disabled_by": "user",
         "platform": "automation", "unique_id": "a2"},
        {"entity_id": "sensor.temp", "disabled_by": None,
         "platform": "mqtt", "unique_id": "s1"},
    ]},
}


def build_config(root: Path):
    (root / "packages").mkdir(parents=True)
    (root / ".storage").mkdir()
    (root / "configuration.yaml").write_text(CONFIG_YAML)
    (root / "automations.yaml").write_text(AUTOMATIONS_YAML)
    (root / "scripts.yaml").write_text(SCRIPTS_YAML)
    (root / "scenes.yaml").write_text(SCENES_YAML)
    (root / "packages" / "cast-safety.yaml").write_text(PKG_YAML)
    (root / "secrets.yaml").write_text("michael_ha_auth: Bearer x\n")
    (root / ".storage" / "core.config_entries").write_text(
        json.dumps(CONFIG_ENTRIES, indent=2))
    (root / ".storage" / "core.entity_registry").write_text(
        json.dumps(ENTITY_REGISTRY, indent=2))


def run(tmp: Path, cmd: str, set_keys=None):
    overlay = so.load_overlay(str(OVERLAY), "tony-dev")
    if set_keys:
        overlay["set_keys"] = set_keys
    rep = {"config_dir": str(tmp), "instance": "tony-dev", "mode": cmd,
           "at": "test", "changes": [], "warnings": [], "failures": []}
    eng = so.Engine(overlay, "verify" if cmd == "verify" else "apply", rep)
    eng.process_config(str(tmp))
    return rep


class TestStagingOverlay(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        build_config(self.root)

    def tearDown(self):
        self.td.cleanup()

    def apply(self, set_keys=None):
        return run(self.root, "apply", set_keys)

    def verify(self):
        return run(self.root, "verify")

    def test_apply_then_verify_clean(self):
        rep = self.apply()
        self.assertTrue(rep["changes"], "expected changes")
        vrep = self.verify()
        self.assertEqual(vrep["failures"], [],
                         f"residual write paths: {vrep['failures']}")

    def test_verify_fails_on_raw_prod(self):
        vrep = self.verify()
        rules = {f["rule"] for f in vrep["failures"]}
        for expected in ("automation", "script", "scene", "shell_command",
                         "rest_command", "notify", "actuating-domain",
                         "mqtt-subkeys", "command_line", "drop-block",
                         "http", "recorder", "config_entries",
                         "entity_registry"):
            self.assertIn(expected, rules, f"missing check: {expected}")

    def test_automations_get_initial_state_off(self):
        self.apply()
        text = (self.root / "automations.yaml").read_text()
        self.assertEqual(text.count("initial_state"), 2)
        doc = ha_load(self.root / "automations.yaml")
        for a in doc:
            self.assertIn(str(a["initial_state"]).lower(), ("false", "off"))

    def test_scripts_stubbed_alias_kept(self):
        self.apply()
        doc = ha_load(self.root / "scripts.yaml")
        self.assertEqual(doc["cast_cleanup"]["alias"], "Cast cleanup")
        self.assertEqual(doc["cast_cleanup"]["mode"], "single")
        self.assertEqual(doc["cast_cleanup"]["sequence"], [{"stop": "staging-noop"}])
        self.assertEqual(doc["plug_cycle"]["fields"], {"plug": {}})

    def test_scene_entities_emptied(self):
        self.apply()
        doc = ha_load(self.root / "scenes.yaml")
        self.assertEqual(doc[0]["entities"], {})
        self.assertEqual(doc[0]["name"], "Movie time")

    def test_package_automation_and_script_neutralized(self):
        self.apply()
        doc = ha_load(self.root / "packages" / "cast-safety.yaml")
        self.assertFalse(doc["automation"][0]["initial_state"])
        self.assertEqual(doc["script"]["cast_power_on"]["sequence"],
                         [{"stop": "staging-noop"}])
        self.assertIn("timer", doc)  # read-only helper kept

    def test_configuration_write_paths(self):
        self.apply()
        text = (self.root / "configuration.yaml").read_text()
        doc = ha_load(self.root / "configuration.yaml")
        # http fixed for podman-net
        self.assertNotIn("server_host", doc["http"])
        self.assertTrue(doc["http"]["use_x_forwarded_for"])
        self.assertIn("10.0.2.0/24", doc["http"]["trusted_proxies"])
        # recorder falls back to sqlite
        self.assertNotIn("db_url", doc["recorder"])
        self.assertEqual(doc["recorder"]["purge_keep_days"], 14)
        # outbound blocks gone
        self.assertNotIn("influxdb", doc)
        self.assertNotIn("mqtt_statestream", doc)
        # shell_command noop
        self.assertIn("staging-noop", doc["shell_command"]["snap_tv"])
        self.assertIn("staging-noop", doc["shell_command"]["post_board"])
        # rest_command sunk
        self.assertEqual(doc["rest_command"]["board_comment"]["url"], SINK)
        self.assertEqual(doc["rest_command"]["board_comment"]["method"], "POST")
        # notify: smtp+html5 dropped, file kept
        platforms = [n["platform"] for n in doc["notify"]]
        self.assertEqual(platforms, ["file"])
        # mqtt: broker kept, sensor kept, switch dropped
        self.assertEqual(doc["mqtt"]["broker"], "127.0.0.1")
        self.assertIn("sensor", doc["mqtt"])
        self.assertNotIn("switch", doc["mqtt"])
        # actuating platforms dropped; template switch kept
        self.assertEqual(len(doc["switch"]), 1)
        self.assertEqual(doc["switch"][0]["platform"], "template")
        # command_line: sensor kept, switch dropped
        cl = doc["command_line"]
        self.assertEqual(len(cl), 1)
        self.assertIn("sensor", cl[0])
        # read-only untouched
        self.assertEqual(doc["sensor"][0]["platform"], "scrape")
        self.assertEqual(doc["automation"], "<include>")  # !include tag stubbed

    def test_config_entries_disabled(self):
        self.apply()
        data = json.loads((self.root / ".storage" / "core.config_entries").read_text())
        by_domain = {e["domain"]: e for e in data["data"]["entries"]}
        self.assertEqual(by_domain["tuya"]["disabled_by"], "user")
        self.assertEqual(by_domain["mobile_app"]["disabled_by"], "user")
        self.assertIsNone(by_domain["sun"]["disabled_by"])
        self.assertIsNone(by_domain["frigate"]["disabled_by"])  # review only

    def test_entity_registry_automations_disabled(self):
        self.apply()
        data = json.loads((self.root / ".storage" / "core.entity_registry").read_text())
        by_eid = {e["entity_id"]: e for e in data["data"]["entities"]}
        self.assertEqual(by_eid["automation.cast_idle_shutdown"]["disabled_by"], "user")
        self.assertIsNone(by_eid["sensor.temp"]["disabled_by"])

    def test_idempotent(self):
        self.apply()
        rep2 = self.apply()
        self.assertEqual(rep2["changes"], [], f"not idempotent: {rep2['changes']}")

    def test_review_warnings(self):
        rep = self.apply()
        warns = [w["detail"] for w in rep["warnings"]]
        self.assertTrue(any("frigate" in w for w in warns))
        self.assertTrue(any("cpu_temp" in w or "command_line" in w for w in warns))

    def test_set_name(self):
        self.apply(set_keys={"name": "Tony DEV"})
        doc = ha_load(self.root / "configuration.yaml")
        self.assertEqual(doc["homeassistant"]["name"], "Tony DEV")
        self.assertEqual(doc["homeassistant"]["internal_url"],
                         "https://tony-dell.taila0626a.ts.net:8123")

    def test_byte_identical_untouched(self):
        self.apply()
        # secrets and read-only regions must be byte-identical
        self.assertEqual((self.root / "secrets.yaml").read_text(),
                         "michael_ha_auth: Bearer x\n")
        text = (self.root / "configuration.yaml").read_text()
        self.assertIn("ip_ban_enabled: true", text)
        self.assertIn("purge_keep_days: 14", text)


if __name__ == "__main__":
    unittest.main()
