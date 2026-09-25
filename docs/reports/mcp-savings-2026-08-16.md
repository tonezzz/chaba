# MCP Debug Savings Report

## tony_omen

| Command | Raw chars | Compact chars | Saved chars | Char % | Word % |
|---------------------------------------|-----------|---------------|-------------|--------|--------|
| ps -eo pid,ppid,cmd,%cpu --sort=-%cpu | 36652     | 1508          | 35144       | 95.9   | 99.6   |
| ps -eo pid,ppid,cmd,%mem --sort=-%mem | 36701     | 1503          | 35198       | 95.9   | 99.6   |
| systemctl list-units                  | 78205     | 5181          | 73024       | 93.4   | 95.6   |
| ps                                    | 5302      | 1057          | 4245        | 80.1   | 99.8   |
| ss -tlnp                              | 7488      | 2120          | 5368        | 71.7   | 70.4   |
| ip -4 route                           | 799       | 472           | 327         | 40.9   | 97.2   |
| free -h                               | 207       | 148           | 59          | 28.5   | 88.2   |
| tailscale status                      | 535       | 491           | 44          | 8.2    | 46.2   |
| uptime                                | 69        | 69            | 0           | 0.0    | 75.0   |
| mount                                 | 33863     | 35454         | -1591       | -4.7   | 99.8   |
| ip -4 -br addr show                   | 526       | 593           | -67         | -12.7  | 84.8   |
| lsusb                                 | 432       | 535           | -103        | -23.8  | 56.9   |
| lsblk                                 | 1432      | 1991          | -559        | -39.0  | 99.4   |
| df -h                                 | 696       | 1000          | -304        | -43.7  | 97.5   |

**tony_omen totals**: raw=202907, compact=52122, saved=150785 (74.3%)

## tony_dell

| Command | Raw chars | Compact chars | Saved chars | Char % | Word % |
|---------------------------------------|-----------|---------------|-------------|--------|--------|
| systemctl list-units                  | 41070     | 3700          | 37370       | 91.0   | 95.4   |
| ps -eo pid,ppid,cmd,%cpu --sort=-%cpu | 15092     | 1385          | 13707       | 90.8   | 98.4   |
| ps -eo pid,ppid,cmd,%mem --sort=-%mem | 15092     | 1470          | 13622       | 90.3   | 98.4   |
| ps                                    | 2661      | 1034          | 1627        | 61.1   | 99.7   |
| free -h                               | 207       | 151           | 56          | 27.1   | 88.2   |
| ip -4 route                           | 382       | 284           | 98          | 25.7   | 94.1   |
| tailscale status                      | 594       | 491           | 103         | 17.3   | 53.3   |
| uptime                                | 72        | 71            | 1           | 1.4    | 69.2   |
| ss -tlnp                              | 1870      | 1951          | -81         | -4.3   | -1.1   |
| mount                                 | 5808      | 6663          | -855        | -14.7  | 99.7   |
| ip -4 -br addr show                   | 193       | 255           | -62         | -32.1  | 58.3   |
| lsusb                                 | 209       | 280           | -71         | -34.0  | 58.8   |
| df -h                                 | 547       | 754           | -207        | -37.8  | 96.7   |
| lsblk                                 | 1400      | 2074          | -674        | -48.1  | 99.5   |

**tony_dell totals**: raw=85197, compact=20563, saved=64634 (75.9%)

**Overall totals**: raw=288104, compact=72685, saved=215419 (74.8%)
