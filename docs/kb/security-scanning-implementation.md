# Security Scanning: Findings and Procedures

## Last Scan: 2026-08-05

## Summary

| Category | Result |
|----------|--------|
| npm audits (4 packages) | ✅ 0 vulnerabilities |
| Docker images | ✅ 80%+ pulled within 4 weeks |
| System packages | ✅ NVIDIA 595.71.05 already patches known CVEs |
| starlette (status-api) | ✅ 1.3.1 — fully patched |
| starlette (embedding-service) | ✅ 1.0.1 transitive dep — Flask serves endpoints, not starlette |
| starlette (thai-legal-inference) | ✅ Uses llama.cpp server, not Python/FastAPI |

## Findings

### No Active CVEs in Running Services

`status-api` (the only service using starlette as a web framework) is on **starlette 1.3.1** and **fastapi 0.141.1** — fully patched against all known starlette CVEs.

Checked CVEs:
- **CVE-2026-48710** (Moderate): Host header validation bypass → fixed in starlette ≥ 1.0.1 ✅
- **CVE-2026-54282** (Moderate): Request path SSRF → fixed in starlette ≥ 1.3.0 ✅
- **GHSA-7f5h-v6xp-fcq8** (High 7.5): Range header DoS in FileResponse → fixed in starlette ≥ 1.3.0 ✅

### Legacy Dockerfile Updated (Preventive)
`stacks/web/thai-legal-inference/requirements.txt` (Dockerfile not currently used in compose —
service runs llama.cpp directly) updated from `fastapi==0.115.0` + `starlette==0.40.0` to
`fastapi==0.141.1` which resolves starlette 1.3.x. Prevents accidental future use of
vulnerable versions.

### Optional: Refresh activepieces
`ghcr.io/activepieces/activepieces:latest` image is from 2026-04-21 (3.5 months old).
Refresh with:
```bash
docker pull ghcr.io/activepieces/activepieces:latest
cd /home/tony/CascadeProjects/chaba && docker compose -f stacks/web/docker-compose.yml up -d activepieces
```

### NVIDIA Driver: No Action Needed
Driver 595.71.05 already patches all known driver CVEs (CVE-2026-24187, etc.).
Update to 595.84 is optional (gaming/stability bugfixes, not security).

## Scan Procedure

```bash
# 1. npm audits
for dir in . scripts/yomi scripts/weaviate scripts/gpu-queue; do
  cd /home/tony/CascadeProjects/chaba/$dir
  echo "=== $dir ===" && npm audit 2>/dev/null | tail -3
done

# 2. Running container starlette versions
for c in status-api embedding-service; do
  ver=$(docker exec $c pip show starlette 2>/dev/null | grep ^Version | awk '{print $2}')
  echo "$c: starlette $ver"
done

# 3. Docker image ages
docker images --format "{{.Repository}}:{{.Tag}}" | grep -v none | while read img; do
  created=$(docker inspect "$img" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Created'][:10])")
  echo "$created  $img"
done | sort

# 4. System security packages
apt list --upgradable 2>/dev/null | grep -v WARNING | grep security
```

## Tags
- security, dependencies, cve, starlette, fastapi, scanning, docker
