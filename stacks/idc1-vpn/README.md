# idc1-vpn

This stack runs `wg-easy` (WireGuard VPN) and `wg-dns` (CoreDNS) for the `.vpn` domain.

## Files

- `docker-compose.yml`: wg-easy + CoreDNS (`wg-dns`) sharing the wg-easy network namespace.
- `config/coredns/Corefile`: CoreDNS config.
- `config/coredns/zones/vpn.db`: zone file for `vpn.`.
- `.env.example`: template for runtime configuration. Copy to `.env` on idc1.

## Deploy on idc1 (from the `idc1-vpn` git branch)

On idc1:

```bash
cd ~/chaba
git fetch origin
git checkout idc1-vpn
git pull

cd ~/chaba/stacks/idc1-vpn
cp -n .env.example .env

# Adjust if needed (esp. WG_EASY_HOST_GW)
${EDITOR:-nano} .env

docker compose up -d --force-recreate wg-easy wg-dns
```

## Verify SSH forwarding (`10.8.0.1:22` -> host sshd)

The compose config applies DNAT rules via wg-easy `WG_POST_UP`.

On idc1:

```bash
docker inspect idc1-wg-easy --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'WG_POST_UP|WG_EASY_HOST_GW' || true

docker exec -it idc1-wg-easy sh -lc 'iptables -t nat -S | grep -E "dport 22|--dport 22" || true'
```

From a VPN client:

```bash
ssh chaba@10.8.0.1
# or
ssh chaba@idc1.vpn
```

If DNAT rules are missing, ensure `.env` is present and `docker compose up -d --force-recreate wg-easy` was run from this directory.

## Migrate WireGuard to the host (so host + all containers can reach `10.8.0.0/24`)

If you want *any* process on the IDC1 host and *any* container to directly reach VPN peers (e.g. `10.8.0.11`, `10.8.0.12`) without using `network_mode: service:wg-easy` proxies, move the `10.8.0.0/24` WireGuard interface from `wg-easy` to the host.

Notes:

- This is disruptive (VPN drops briefly).
- Do not commit any keys to git.
- The IDC1 host already has a host `wg0` on a different subnet (`10.42.0.0/24`). Do not reuse `wg0`. Use a new interface name (example: `wg8`).

### Step 1: Extract current config from `wg-easy`

On IDC1:

```bash
docker exec -it idc1-wg-easy sh -lc 'cat /etc/wireguard/wg0.conf'
```

Copy the `PrivateKey` and each peer block (`PublicKey`, `PresharedKey`, `AllowedIPs`).

### Step 2: Create `/etc/wireguard/wg8.conf` on the host

On IDC1:

```bash
sudo mkdir -p /etc/wireguard
sudo nano /etc/wireguard/wg8.conf
sudo chmod 600 /etc/wireguard/wg8.conf
```

Template (fill in keys from `wg0.conf`):

```ini
[Interface]
Address = 10.8.0.1/24
ListenPort = 51820
PrivateKey = <PASTE_PRIVATE_KEY_FROM_WG_EASY>

# Allow host + Docker containers (172.16.0.0/12) to reach VPN peers.
# Without this SNAT, traffic from containers will have a 172.* source and peers won't route back.
PostUp = iptables -t nat -A POSTROUTING -s 172.16.0.0/12 -o %i -j MASQUERADE; iptables -A FORWARD -i %i -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -s 172.16.0.0/12 -o %i -j MASQUERADE || true; iptables -D FORWARD -i %i -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT || true; iptables -D FORWARD -o %i -j ACCEPT || true

[Peer]
PublicKey = <PC1_PUBLIC_KEY>
PresharedKey = <PC1_PRESHARED_KEY>
AllowedIPs = 10.8.0.11/32

[Peer]
PublicKey = <PC2_PUBLIC_KEY>
PresharedKey = <PC2_PRESHARED_KEY>
AllowedIPs = 10.8.0.12/32
```

### Step 3: Stop `wg-easy` (frees UDP/51820) and bring up host WG

Stop the `idc1-vpn` stack in Portainer (or stop the `wg-easy` service), then on IDC1:

```bash
sudo wg-quick up wg8
sudo systemctl enable wg-quick@wg8
```

### Step 4: Verify from the host

```bash
sudo wg show wg8
ip -br a | grep -E '^wg8'
ip route | grep -E '^10\.8\.0\.0/24'

ping -c 2 10.8.0.11 || true
ping -c 2 10.8.0.12 || true
```

If you want to test TCP reachability:

```bash
curl -v --max-time 5 http://10.8.0.12:9001/ping || true
```

### Step 5: Decide what replaces `wg-dns`

If you relied on `wg-dns` (`idc1-wg-dns`) for the `.vpn` zone, you can keep it, but it will no longer share the `wg-easy` network namespace. Run it as a normal container and point its upstream/zone config at the host as needed.

## Applying the same approach on PC1/PC2

- PC1/PC2 are Windows hosts. You typically keep WireGuard on the host (WireGuard app) and ensure the endpoint service is bound to the VPN interface and allowed through firewall.
- If you run WireGuard inside Docker on Windows, the same principle applies: the host won't automatically route to the container's WG subnet; either migrate WG to host or add explicit proxies.
