import importlib.util
import json
import os
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/devnest/devnest-tg-relay.py"
SPEC = importlib.util.spec_from_file_location("devnest_tg_relay", SCRIPT)
relay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(relay)


def test_general_topic_has_no_thread():
    topic, thread = relay._topic({"chat": {"id": -100}, "message_id": 1})
    assert (topic, thread) == ("general", None)


def test_forum_topic_is_lane_candidate():
    topic, thread = relay._topic({
        "chat": {"id": -100},
        "message_id": 2,
        "message_thread_id": 42,
    })
    assert (topic, thread) == ("thread-42", 42)


def test_lane_mapping():
    assert relay._lane("HA Lab") == "ha-lab"
    assert relay._lane("unknown-topic") == "unknown"


def test_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "STATE_DIR", tmp_path)
    monkeypatch.setattr(relay, "OFFSET_FILE", tmp_path / "state.json")
    relay._save_offset(123)
    assert relay._state_offset() == 123
