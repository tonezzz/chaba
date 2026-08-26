#!/usr/bin/env python3
"""Subscribe to a Meshtastic Thailand MQTT namespace and log packets to JSONL."""

import json
import os
import ssl
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC = os.getenv("MQTT_TOPIC", "msh/TH/#")
OUTPUT = os.getenv("OUTPUT", "nodes.jsonl")
RECORD_POSITIONS = os.getenv("RECORD_POSITIONS", "false").lower() in ("1", "true", "yes")

USE_TLS = os.getenv("MQTT_TLS", "false").lower() in ("1", "true", "yes")
TLS_INSECURE = os.getenv("MQTT_TLS_INSECURE", "false").lower() in ("1", "true", "yes")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"connected to {BROKER}:{PORT}, subscribing to {TOPIC}")
        client.subscribe(TOPIC)
    else:
        msg = {
            1: "unacceptable protocol version",
            2: "identifier rejected",
            3: "server unavailable",
            4: "bad username or password",
            5: "not authorized",
        }.get(rc, f"unknown ({rc})")
        print(f"connection failed: {msg}", file=sys.stderr)


def on_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8", errors="replace")
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "topic": msg.topic,
        "qos": msg.qos,
        "retain": msg.retain,
        "raw": payload,
    }
    try:
        data = json.loads(payload)
        record["decoded"] = data
        record["type"] = data.get("type") or data.get("payload", {}).get("type") or data.get("portnum") or "unknown"
        # Optionally drop positions for privacy
        if record["type"] == "position" and not RECORD_POSITIONS:
            record["decoded"] = {"note": "position redacted"}
    except json.JSONDecodeError:
        record["decoded"] = {"error": "not valid JSON"}

    with open(OUTPUT, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[{record['ts']}] {record.get('type', 'raw')} on {msg.topic}")


def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    if USE_TLS:
        if TLS_INSECURE:
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)
        else:
            client.tls_set()

    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    client.connect(BROKER, PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
