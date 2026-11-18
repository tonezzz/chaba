"""Parser + classifier tests for scripts/audit-edge-upstreams.py.

The incident fixture reproduces 2026-11-18: serve :8125 -> 127.0.0.1:8125
while the only listener was :8123 — must classify dead."""
import sys
import urllib.error
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "audit_edge_upstreams",
    Path(__file__).resolve().parents[1] / "scripts" / "audit-edge-upstreams.py")
a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(a)  # noqa: E402


# ------------------------------------------------------------- serve json

SERVE_INCIDENT = {
    "TCP": {"443": {"HTTPS": True}, "8125": {"HTTPS": True},
            "3000": {"TCPForward": "127.0.0.1:3000"}},
    "Web": {
        "tony-omen.taila0626a.ts.net:443": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8520"}}},
        "tony-omen.taila0626a.ts.net:8125": {
            "Handlers": {"/": {"Proxy": "http://127.0.0.1:8125"}}},
    },
    "Foreground": {
        "af63685cf246e0c1": {
            "TCP": {"8080": {"HTTPS": True}},
            "Web": {"tony-omen.taila0626a.ts.net:8080": {
                "Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}}},
        }
    },
    "AllowFunnel": {"tony-omen.taila0626a.ts.net:443": True},
}


def test_parse_serve_status_finds_web_tcp_and_foreground():
    rows = a.parse_serve_status(SERVE_INCIDENT)
    got = {(r["surface"], r["mount"], r["target"]) for r in rows}
    assert ("serve:tony-omen.taila0626a.ts.net:8125", "/",
            "http://127.0.0.1:8125") in got
    assert ("serve-tcp:3000", "-", "127.0.0.1:3000") in got
    # foreground session target included, tagged with its scope
    assert any(r["target"] == "http://127.0.0.1:8080" and "fg:" in r["surface"]
               for r in rows)
    assert len(rows) == 4   # HTTPS:true entries are listeners, not targets


def test_incident_proxy_to_dead_port_flags_dead():
    """The :8125 -> 127.0.0.1:8125 wiring must surface as dead."""
    listeners = {8123: {"127.0.0.1"}, 8520: {"127.0.0.1"},
                 8080: {"0.0.0.0"}}
    cls = a.classify_target("http://127.0.0.1:8125")
    assert cls == {"kind": "loopback", "port": 8125}
    status, ev = a.check_loopback(cls["port"], listeners)
    assert status == "dead"
    assert "nothing listening" in ev


def test_fixed_wiring_8125_to_8123_passes():
    listeners = {8123: {"127.0.0.1"}}
    cls = a.classify_target("http://127.0.0.1:8123")
    status, ev = a.check_loopback(cls["port"], listeners)
    assert status == "ok"


def test_loopback_bound_only_on_tailnet_ip_is_dead():
    """A proxy to 127.0.0.1:P where P listens only on the tailnet IP still
    refuses loopback clients."""
    listeners = {8124: {"100.123.163.11"}}
    status, ev = a.check_loopback(8124, listeners)
    assert status == "dead"
    assert "bound only" in ev


# --------------------------------------------------------- classify target

def test_classify_target_variants():
    assert a.classify_target("http://127.0.0.1:80") == \
        {"kind": "loopback", "port": 80}
    assert a.classify_target("tcp://127.0.0.1:9002")["kind"] == "loopback"
    assert a.classify_target("127.0.0.1:3000")["kind"] == "loopback"
    r = a.classify_target("https://idc03.taila0626a.ts.net:10000")
    assert r["kind"] == "http" and r["host"] == "idc03.taila0626a.ts.net"
    r = a.classify_target("https+insecure://foo.ts.net:1/x")
    assert r["kind"] == "http" and r["insecure"] is True
    r = a.classify_target("http+unix:///run/foo.sock")
    assert r["kind"] == "unix" and r["path"] == "/run/foo.sock"
    r = a.classify_target("frigate:5000")
    assert r["kind"] == "container" and r["name"] == "frigate"
    assert a.classify_target("tailscale-only")["kind"] == "skip"
    r = a.classify_target("100.102.134.91:11023")
    assert r["kind"] == "http" and r["url"].startswith("http://")


# ----------------------------------------------------------- caddy parsing

CADDY_SNIPPET = """\
# comment with reverse_proxy inside — must not parse
tony-ha.surf-thailand.com {
	bind 45.136.236.190
	handle_path /apps/board-api/* {
		reverse_proxy https://idc03.taila0626a.ts.net:10000 {
			header_up Host idc03.taila0626a.ts.net
		}
	}
	handle {
		reverse_proxy https://tony-omen.taila0626a.ts.net:8123
	}
}

http://:8088 {
	bind 127.0.0.1
	reverse_proxy http://127.0.0.1:8099 {
		header_up Host idc02-web-origin
	}
}

multi.example.com {
	reverse_proxy http://10.0.0.1:8380 http://10.0.0.2:8380
	reverse_proxy @api https://api.internal:9000
}
"""


def test_parse_caddyfile_vhosts_and_upstreams():
    rows = a.parse_caddyfile(CADDY_SNIPPET)
    got = {(r["vhost"], r["upstream"]) for r in rows}
    assert ("tony-ha.surf-thailand.com",
            "https://idc03.taila0626a.ts.net:10000") in got
    assert ("tony-ha.surf-thailand.com",
            "https://tony-omen.taila0626a.ts.net:8123") in got
    assert ("http://:8088", "http://127.0.0.1:8099") in got
    # multi-upstream + leading @matcher
    assert ("multi.example.com", "http://10.0.0.1:8380") in got
    assert ("multi.example.com", "http://10.0.0.2:8380") in got
    assert ("multi.example.com", "https://api.internal:9000") in got
    assert len(rows) == 6
    # comment line was not parsed
    assert all(r["line"] > 1 for r in rows)


def test_parse_caddyfile_real_file():
    """The live idc02 edge Caddyfile parses to the expected upstreams."""
    p = Path.home() / ".config/caddy/Caddyfile"
    if not p.exists():
        import pytest
        pytest.skip("no live Caddyfile on this host")
    rows = a.parse_caddyfile(p.read_text())
    ups = {r["upstream"] for r in rows}
    assert "https://tony-omen.taila0626a.ts.net:8125" in ups
    assert "https://idc03.taila0626a.ts.net:10000" in ups
    assert all(r["vhost"] for r in rows)


# ------------------------------------------------------------- probe class

def test_url_error_classification():
    dead, _ = a._classify_url_error(
        urllib.error.URLError(ConnectionRefusedError("x")), "u")
    assert dead == "dead"
    dead, _ = a._classify_url_error(
        urllib.error.URLError(socket.gaierror("nx")), "u")
    assert dead == "dead"
    import ssl
    deg, _ = a._classify_url_error(
        urllib.error.URLError(ssl.SSLError("wrong version")), "u")
    assert deg == "degraded"
