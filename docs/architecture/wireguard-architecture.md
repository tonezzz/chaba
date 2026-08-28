# WireGuard Architecture Diagram

## Basic WireGuard Setup (Peer-to-Peer)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          WireGuard Peer-to-Peer Network                      │
└─────────────────────────────────────────────────────────────────────────────┘

    Mobile Device (WiFi Network A)                    Home Workstation (WiFi Network B)
    ┌──────────────────────────────┐                ┌──────────────────────────────┐
    │   WireGuard Interface        │                │   WireGuard Interface        │
    │   wg0: 10.0.0.1/24           │                │   wg0: 10.0.0.2/24           │
    │                              │                │                              │
    │  Public Key: AAAAAAAAAAAA    │◄──────────────►│  Public Key: BBBBBBBBBBBB    │
    │  Private Key: (secret)       │   Encrypted    │  Private Key: (secret)       │
    │                              │    Tunnel      │                              │
    │  Endpoint: dynamic IP       │                │  Endpoint: dynamic IP       │
    │  Port: 51820                 │                │  Port: 51820                 │
    └──────────────────────────────┘                └──────────────────────────────┘
                │                                                │
                │                                                │
                ▼                                                ▼
    ┌──────────────────────────────┐                ┌──────────────────────────────┐
    │   WiFi Network A             │                │   WiFi Network B             │
    │   IP: 192.168.0.15           │                │   IP: 192.168.1.48           │
    │   Gateway: 192.168.0.1       │                │   Gateway: 192.168.1.1       │
    └──────────────────────────────┘                └──────────────────────────────┘
                │                                                │
                │                                                │
                └────────────────────┬───────────────────────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │   Internet           │
                          │   (No coordination   │
                          │    servers needed)   │
                          └──────────────────────┘
```

## WireGuard Configuration Files

### Mobile Device (wg0.conf)
```ini
[Interface]
PrivateKey = <Mobile_Private_Key>
Address = 10.0.0.1/24
DNS = 1.1.1.1

[Peer]
PublicKey = <Home_Public_Key>
Endpoint = <Home_Dynamic_IP>:51820
AllowedIPs = 10.0.0.2/32
PersistentKeepalive = 25
```

### Home Workstation (wg0.conf)
```ini
[Interface]
PrivateKey = <Home_Private_Key>
Address = 10.0.0.2/24
ListenPort = 51820

[Peer]
PublicKey = <Mobile_Public_Key>
AllowedIPs = 10.0.0.1/32
```

## Key Differences vs Tailscale

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Comparison Summary                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WireGuard                          │  Tailscale                            │
│  ────────────────────────────────── │  ───────────────────────────────────  │
│  • Manual configuration            │  • Automatic configuration            │
│  • No coordination servers         │  • Uses coordination servers          │
│  • Manual key exchange             │  • Automatic key exchange              │
│  • Manual IP management            │  • Automatic IP management             │
│  • Direct P2P only                 │  • P2P with relay fallback             │
│  • Must handle NAT/firewalls       │  • Automatic NAT traversal            │
│  • Must update dynamic IPs         │  • Handles dynamic IPs automatically  │
│  • More control/complexity         │  • Easier setup, less control          │
│  • No external dependencies       │  • Requires Tailscale coordination    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## WireGuard Connection Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WireGuard Connection Establishment                       │
└─────────────────────────────────────────────────────────────────────────────┘

1. Initial Setup (One-time)
   ┌──────────────┐    Generate Keys    ┌──────────────┐
   │ Mobile Device│ ──────────────────► │ wg genkey     │
   └──────────────┘                    └──────────────┘
         │                                    │
         │                                    ▼
         │                           ┌──────────────┐
         │                           │ Public/Private│
         │                           │ Key Pair      │
         │                           └──────────────┘
         │
         ▼
   ┌──────────────┐    Exchange Public Keys   ┌──────────────┐
   │ Mobile Device│ ◄──────────────────────► │Home Workstation│
   └──────────────┘    (manually, secure channel) └──────────────┘

2. Connection Establishment
   ┌──────────────┐    Send Handshake    ┌──────────────┐
   │ Mobile Device│ ──────────────────► │Home Workstation│
   │ (10.0.0.1)   │   to <Home_IP>:51820│ (10.0.0.2)   │
   └──────────────┘                    └──────────────┘
         │                                    │
         │                                    ▼
         │                           ┌──────────────┐
         │                           │ Verify Public │
         │                           │ Key, Respond  │
         │                           └──────────────┘
         │                                    │
         ▼                                    ▼
   ┌──────────────┐    Encrypted Tunnel     ┌──────────────┐
   │ Mobile Device│ ◄─────────────────────► │Home Workstation│
   └──────────────┘    Established           └──────────────┘
```

## Dynamic IP Challenge with WireGuard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Dynamic IP Problem in WireGuard                          │
└─────────────────────────────────────────────────────────────────────────────┘

Scenario: Mobile device moves from Home Network to Coffee Shop

Home Network:
  Mobile IP: 192.168.1.15
  Home Workstation IP: 192.168.1.48
  WireGuard Config: Endpoint = 192.168.1.48:51820 ✓

Coffee Shop Network:
  Mobile IP: 192.168.0.42
  Home Workstation IP: Unknown (different network)
  WireGuard Config: Endpoint = 192.168.1.48:51820 ✗ (IP no longer valid)

Solution Options:
1. Update Endpoint manually each time network changes
2. Use DDNS to get stable hostname for home workstation
3. Use PersistentKeepalive to maintain connection across NAT
4. Set up port forwarding and use public IP with DDNS
```

## WireGuard + DDNS Solution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   WireGuard with DDNS for Dynamic IPs                        │
└─────────────────────────────────────────────────────────────────────────────┘

    Mobile Device                    DDNS Service               Home Workstation
    ┌──────────────┐              ┌──────────────┐           ┌──────────────┐
    │ WireGuard    │              │ DuckDNS/     │           │ WireGuard    │
    │ wg0.conf:    │              │ No-IP/Cloud  │           │ wg0.conf:    │
    │ Endpoint =   │              │ flare        │           │ ListenPort = │
    │ tony-omen.   │              │              │           │ 51820        │
    │ duckdns.org: │              │              │           │              │
    │ 51820        │              │              │           │ DDNS Updater │
    └──────────────┘              └──────────────┘           └──────────────┘
         │                              │                          │
         │                              │                          │
         │    1. Home workstation updates DDNS with current IP    │
         │                              │                          │
         │                              ◄──────────────────────────┤
         │                              │                          │
         │    2. Mobile resolves hostname to current IP           │
         │                              │                          │
         ├─────────────────────────────►│                          │
         │                              │                          │
         │    3. Mobile connects to current IP via WireGuard       │
         │                              │                          │
         ├─────────────────────────────►├─────────────────────────►│
         │                              │                          │
         ▼                              ▼                          ▼
    Encrypted WireGuard Tunnel Established
```

## Summary

**WireGuard Advantages:**
- Pure P2P, no coordination servers
- Lightweight, fast, minimal code
- Full control over configuration
- Works great for static IPs or with DDNS
- Open source, auditable

**WireGuard Challenges:**
- Manual configuration and key management
- Must handle dynamic IPs manually (DDNS, scripts)
- NAT traversal requires additional setup
- No built-in peer discovery
- More complex for multi-device networks

**Best for:** Technical users who want full control, have few devices, and are comfortable with manual configuration.
