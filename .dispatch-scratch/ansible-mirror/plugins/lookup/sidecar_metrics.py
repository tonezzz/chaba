#!/usr/bin/env python3
"""
Ansible lookup plugin: sidecar_metrics

Fetches host metrics from Redis (populated by sidecar collector).

Usage in playbook:
  - name: Fetch sidecar metrics
    ansible.builtin.set_fact:
      sidecar_metrics: "{{ query('sidecar_metrics', inventory_hostname, redis_host) }}"

Returns dict with keys:
  timestamp, hostname, cpu_pct, mem_pct, mem_used_mb, mem_total_mb,
  load1, load5, load15, disk_pct, disk_used_b, disk_total_b,
  gpu_count, gpus (list), gpu_mem_free_mb, gpu_mem_total_mb,
  container_count, containers (list),
  opencode_serve (dict), tags (list)
"""

from ansible.plugins.lookup import LookupBase
from ansible.errors import AnsibleError
import json
import redis


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        """
        terms[0] = hostname (or 'auto' to use inventory_hostname)
        terms[1] = redis host (optional, defaults to 100.123.163.11)
        """
        if not terms:
            raise AnsibleError("sidecar_metrics lookup requires at least hostname argument")

        hostname = terms[0]
        if hostname == "auto":
            hostname = variables.get("inventory_hostname", "") if variables else ""
            if not hostname:
                raise AnsibleError("Cannot determine hostname: inventory_hostname not in variables")

        redis_host = terms[1] if len(terms) > 1 else "100.123.163.11"
        redis_port = int(terms[2]) if len(terms) > 2 else 6379
        redis_db = int(terms[3]) if len(terms) > 3 else 0

        try:
            r = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)
            key = f"sidecar:{hostname}"
            data = r.hgetall(key)

            if not data:
                self._display.warning(f"No sidecar metrics found for {hostname} at {redis_host}:{redis_port}")
                return [{}]

            # Parse JSON fields
            parsed = {}
            for k, v in data.items():
                try:
                    parsed[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed[k] = v

            return [parsed]

        except redis.ConnectionError as e:
            raise AnsibleError(f"Cannot connect to Redis at {redis_host}:{redis_port}: {e}")
        except Exception as e:
            raise AnsibleError(f"sidecar_metrics lookup failed: {e}")