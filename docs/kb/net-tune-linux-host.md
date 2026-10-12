# Network Tune — Linux Host (LAN + WiFi)

Standard procedure for "tune this host's network for max performance". Verify hardware limits first — most "slow link" cases are hardware caps, not config.

First run: tony-macbook 2026-10-11. Findings used as the worked example.

## 1. Find the link's hardware ceiling (check first)

- Wired: `ethtool <if>` → `Speed:` line. Then identify the adapter chip:
  `lsusb | grep -iE "ethernet|8152|8153|asix|realtek"`.
  - **RTL8152 = Fast Ethernet (10/100)** — 100 Mb/s IS the ceiling, no software fix. Needs an RTL8153-class USB3 adapter for gigabit.
  - RTL8153/8156 = gigabit/2.5G — if it negotiated 100M, try `ethtool -r <if>` or check the cable/port.
- WiFi: `nmcli -t -f SSID,CHAN,RATE,SIGNAL dev wifi list` — channel ≤14 = 2.4 GHz (≈30–70 Mb/s real, often worse than 100M wire); >14 = 5 GHz (fast). Also `iw dev <if> link` for negotiated rates when connected.

## 2. Decide the primary path

- Same LAN behind both interfaces → pick ONE (dual-homed same-subnet adds asymmetric routing, not bandwidth).
- **Docked**: keep ethernet primary even at 100M — it's still more consistent than congested 2.4 GHz WiFi.
- **5 GHz SSID present + weak/no wired link** → WiFi wins.
- On tony-macbook (2026-10-11): only 2.4 GHz SSIDs visible → keeping WiFi disconnected was already optimal; nothing to gain.

## 3. Safe runtime tuning (no hardware needed)

Needs root (pkexec one-shot):

```bash
# Better TCP congestion control — biggest real win on WAN/tailnet paths
sysctl -w net.core.default_qdisc=fq
sysctl -w net.ipv4.tcp_congestion_control=bbr

# Persist:
echo -e "net.core.default_qdisc=fq\nnet.ipv4.tcp_congestion_control=bbr" > /etc/sysctl.d/90-net-tune.conf
```

- WiFi only (when it IS the primary link): `iw dev <if> set power_save off` — kills latency spikes from PSM.
- Wired NIC powersave off if the driver exposes it: `ethtool -s <if> wol d` is NOT that; real control is `nmcli con mod <conn> 802-3-ethernet.wake-on-lan ignore` or driver quirks — usually unnecessary.

## 4. Verify

- `ethtool <if>` Speed/Duplex, `ip -s link show <if>` for errors/drops.
- WiFi: `iw dev <if> link` — signal > -70 dBm and rates near PHY cap.
- Throughput spot check: `curl -o /dev/null http://tony-dell:8000/big-file` or iperf3 to a LAN host; compare against the ceiling found in step 1. If you're already at ceiling → done, report hardware as the limit.

## 5. What NOT to do

- Don't force `ethtool -s speed 1000` on an adapter that can't do it — the port dies.
- Don't enable WiFi alongside docked ethernet on the same subnet "for speed" — adds flapping, not throughput.
- Don't touch MTU unless there's evidence of fragmentation (tailnet already handles its own).
