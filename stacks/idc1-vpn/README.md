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
