# Meshtastic Thailand node data collector (experimental)

This is an isolated branch to test collecting and parsing Meshtastic MQTT JSON traffic for the Thai mesh namespace `msh/TH`.

## What it does

- Spins up a local Eclipse Mosquitto broker.
- `collector.py` subscribes to `msh/TH/#` and stores parsed packets to `nodes.jsonl`.
- `synthetic-publisher.py` publishes sample Meshtastic-style JSON packets so you can test the collector without real hardware.
- Keeps sensitive data opt-in: GPS positions are only stored if `RECORD_POSITIONS=true`.

## Quick start

1. Install Python deps:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the broker:
   ```bash
   docker compose -f docker-compose.yml up -d
   ```
   Or with podman:
   ```bash
   podman-compose -f docker-compose.yml up -d
   ```

3. Run the collector:
   ```bash
   python3 collector.py
   ```

4. In another terminal, run the synthetic publisher:
   ```bash
   python3 synthetic-publisher.py
   ```

5. Inspect the JSONL output:
   ```bash
   tail -f nodes.jsonl
   ```

## Configuration

All settings are passed as environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MQTT_BROKER` | `localhost` | MQTT broker host |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_TOPIC` | `msh/TH/#` | Topic to subscribe to |
| `OUTPUT` | `nodes.jsonl` | Output JSONL file |
| `RECORD_POSITIONS` | `false` | Store `position` packets (set `true` to keep) |
| `MQTT_TLS` | `false` | Use TLS (needed for port 8883) |
| `MQTT_TLS_INSECURE` | `false` | Skip TLS cert verification (for self-signed brokers) |
| `MQTT_USER` | — | Username if broker requires auth |
| `MQTT_PASS` | — | Password if broker requires auth |

### Example: connect to the public Meshtastic broker

The Meshtastic project runs a public broker for testing. The Thailand community uses the `msh/TH` root topic.

```bash
MQTT_BROKER=mqtt.meshtastic.org \
MQTT_PORT=1883 \
MQTT_USER=meshdev \
MQTT_PASS=large4cats \
MQTT_TOPIC=msh/TH/# \
python3 collector.py
```

> Note: The default public credentials are published by Meshtastic. Do not use them for private or sensitive channels. Messages on `msh/TH/#` are encrypted (`.../2/e/...`) unless a gateway publishes JSON on `msh/TH/2/json/#`; this collector stores only the encrypted payloads it receives.

## Thai legal settings (NBTC)

For any real RF test in Thailand, configure devices with:

- Region: `TH`
- Frequency: AS923-1, 920.0–925.0 MHz
- Max power: 16 dBm (40 mW)

## Privacy / legal warning

Do **not** point this collector at a public or shared broker and do **not** collect positions, messages, or node metadata from other operators without explicit consent. Use your own nodes and your own broker, or synthetic data only.

## Data captured

- `text` messages
- `nodeinfo` (node ID, long/short name, hardware, firmware)
- `telemetry` (battery, temperature, etc.)
- `position` (GPS) — opt-in
- `device_metrics` (air utilization, channel utilization, etc.)
- `traceroute`
