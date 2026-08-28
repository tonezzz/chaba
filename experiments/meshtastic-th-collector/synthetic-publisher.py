#!/usr/bin/env python3
"""Publish synthetic Meshtastic-style MQTT packets for local testing."""

import json
import os
import random
import time

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "5"))


def publish(client, topic, payload):
    client.publish(topic, json.dumps(payload, ensure_ascii=False))
    print(f"published to {topic}")


def main():
    client = mqtt.Client()
    client.connect(BROKER, PORT, 60)
    client.loop_start()

    base = "msh/TH/2/json"
    nodes = [
        {"id": "!a1b2c3d4", "short": "BKK-01", "long": "BKK-Sathorn-01", "hw": "LILYGO_TBEAM_1.2"},
        {"id": "!e5f6789a", "short": "CNX-01", "long": "Chiang-Mai-01", "hw": "HELTEC_V3"},
    ]

    i = 0
    while True:
        node = nodes[i % len(nodes)]

        publish(client, f"{base}/{node['id']}/info", {
            "type": "nodeinfo",
            "id": node["id"],
            "shortname": node["short"],
            "longname": node["long"],
            "hw_model": node["hw"],
            "region": "TH",
            "modem_preset": "LONG_FAST",
        })

        if random.random() > 0.3:
            publish(client, f"{base}/{node['id']}/telemetry", {
                "type": "telemetry",
                "id": node["id"],
                "battery_level": random.randint(20, 100),
                "voltage": round(random.uniform(3.3, 4.2), 2),
                "air_util_tx": round(random.uniform(0.0, 15.0), 2),
            })

        if random.random() > 0.5:
            lat = 13.7563 + random.uniform(-0.05, 0.05)
            lon = 100.5018 + random.uniform(-0.05, 0.05)
            publish(client, f"{base}/{node['id']}/position", {
                "type": "position",
                "id": node["id"],
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "altitude": random.randint(0, 200),
            })

        i += 1
        time.sleep(PUBLISH_INTERVAL)


if __name__ == "__main__":
    main()
