"""Google Home / Chromecast LAN MCP server.

Exposes local-network control of Cast devices (Chromecast, Android TV with
Chromecast built-in, Google Home/Nest speakers) over MCP streamable HTTP.

Runs on mn01 in rootless podman with host networking so it can do mDNS
discovery on the mn-home LAN and reach cross-subnet devices listed in
CAST_HOSTS (e.g. TONY-TV at 192.168.2.85 via Tailscale routing).

Env:
  BIND_HOST   listen address for the HTTP transport (default 127.0.0.1)
  PORT        listen port (default 8004)
  CAST_HOSTS  comma-separated static device IPs merged into discovery
"""

import json
import os
import urllib.request
from contextlib import contextmanager

import pychromecast
from fastmcp import FastMCP
from pychromecast.discovery import discover_listed_chromecasts, get_device_info
from pychromecast.models import CastInfo, HostServiceInfo

BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8004"))
CAST_HOSTS = [h.strip() for h in os.environ.get("CAST_HOSTS", "").split(",") if h.strip()]

mcp = FastMCP("google-home-lan")


def _cast_info_for_host(host: str) -> CastInfo:
    """CastInfo for a static host, enriched via the eureka endpoint so it has
    a friendly name/model. Falls back to bare host on failure."""
    info = CastInfo(
        services={HostServiceInfo(host, 8009)},
        uuid=None,
        model_name=None,
        friendly_name=None,
        host=host,
        port=8009,
        cast_type=None,
        manufacturer=None,
    )
    try:
        dev = get_device_info(host, timeout=5)
        if dev:
            info = CastInfo(
                services=info.services,
                uuid=dev.uuid,
                model_name=dev.model_name,
                friendly_name=dev.friendly_name,
                host=host,
                port=8009,
                cast_type=dev.cast_type,
                manufacturer=dev.manufacturer,
            )
    except Exception:
        pass
    return info


def _discover(timeout: float = 5.0) -> dict[str, CastInfo]:
    """mDNS discovery plus static CAST_HOSTS. Returns friendly_name/host keyed map."""
    cast_infos, browser = discover_listed_chromecasts(
        known_hosts=CAST_HOSTS or None,
        discovery_timeout=timeout,
    )
    pychromecast.discovery.stop_discovery(browser)
    devices: dict[str, CastInfo] = {}
    for info in cast_infos:
        if info.friendly_name:
            devices[info.friendly_name.strip().lower()] = info
        devices[info.host] = info
    for host in CAST_HOSTS:
        if not any(i.host == host for i in devices.values()):
            info = _cast_info_for_host(host)
            if info.friendly_name:
                devices[info.friendly_name.strip().lower()] = info
            devices[host] = info
    return devices


def _resolve(device: str) -> CastInfo:
    device = device.strip()
    if device.replace(".", "").isdigit():
        return _cast_info_for_host(device)
    devices = _discover()
    info = devices.get(device.lower())
    if info is None:
        known = ", ".join(sorted({i.friendly_name or i.host for i in devices.values()}))
        raise ValueError(f"Device '{device}' not found. Discovered: {known or 'none'}")
    return info


@contextmanager
def _connect(info: CastInfo):
    cast = pychromecast.Chromecast(info, tries=2, timeout=8, retry_wait=1)
    try:
        cast.wait()
        yield cast
    finally:
        try:
            cast.disconnect(timeout=2, blocking=True)
        except Exception:
            pass


def _media_status(mc) -> dict:
    s = mc.status
    return {
        "player_state": s.player_state,
        "title": s.title,
        "content_id": s.content_id,
        "content_type": s.content_type,
        "current_time": s.current_time,
        "duration": s.duration,
        "volume_level": s.volume_level,
        "volume_muted": s.volume_muted,
        "idle_reason": s.idle_reason,
    }


@mcp.tool
def discover_devices(timeout: float = 5.0) -> list[dict]:
    """Discover Google Cast / Google Home devices on the LAN (mDNS plus
    statically configured CAST_HOSTS). Returns friendly names for use in the
    other tools."""
    devices = _discover(timeout)
    seen = set()
    out = []
    for i in devices.values():
        if i.host in seen:
            continue
        seen.add(i.host)
        out.append({
            "name": i.friendly_name,
            "host": i.host,
            "port": i.port,
            "model": i.model_name,
            "manufacturer": i.manufacturer,
            "cast_type": i.cast_type,
            "uuid": str(i.uuid) if i.uuid else None,
        })
    return out


@mcp.tool
def device_info(device: str) -> dict:
    """Raw device info from the device's eureka endpoint (name, model, build,
    network state). Device may be a friendly name or an IP address."""
    info = _resolve(device)
    with _connect(info) as cast:
        s = cast.device
        return {
            "friendly_name": s.friendly_name,
            "model_name": s.model_name,
            "manufacturer": s.manufacturer,
            "cast_type": s.cast_type,
            "uuid": str(s.uuid) if s.uuid else None,
            "host": info.host,
        }


@mcp.tool
def cast_status(device: str) -> dict:
    """Current status of a Cast device: running app, volume, player state and
    now-playing media. Device may be a friendly name or an IP address."""
    info = _resolve(device)
    with _connect(info) as cast:
        status = {
            "app_id": cast.app_id,
            "app_display_name": cast.status.display_name,
            "is_idle": cast.is_idle,
            "volume_level": cast.status.volume_level,
            "volume_muted": cast.status.volume_muted,
        }
        status["media"] = _media_status(cast.media_controller)
        return status


@mcp.tool
def cast_play_media(device: str, url: str, content_type: str = "video/mp4") -> dict:
    """Play a media URL on a Cast device using the default media receiver.
    The URL must be reachable by the device itself (LAN or public)."""
    info = _resolve(device)
    with _connect(info) as cast:
        mc = cast.media_controller
        mc.play_media(url, content_type)
        mc.block_until_active(timeout=8)
        return {"started": True, "media": _media_status(mc)}


@mcp.tool
def cast_media_control(device: str, action: str) -> dict:
    """Control media playback on a Cast device.
    action: play | pause | stop"""
    info = _resolve(device)
    with _connect(info) as cast:
        mc = cast.media_controller
        if action == "play":
            mc.play()
        elif action == "pause":
            mc.pause()
        elif action == "stop":
            mc.stop()
        else:
            raise ValueError("action must be one of: play, pause, stop")
        mc.block_until_active(timeout=5)
        return {"action": action, "media": _media_status(mc)}


@mcp.tool
def cast_volume(device: str, action: str, value: float | None = None) -> dict:
    """Volume control on a Cast device.
    action: set (value 0.0-1.0) | up | down | mute | unmute"""
    info = _resolve(device)
    with _connect(info) as cast:
        if action == "set":
            if value is None or not 0.0 <= value <= 1.0:
                raise ValueError("set requires value between 0.0 and 1.0")
            cast.set_volume(value)
        elif action == "up":
            cast.volume_up()
        elif action == "down":
            cast.volume_down()
        elif action == "mute":
            cast.set_volume_muted(True)
        elif action == "unmute":
            cast.set_volume_muted(False)
        else:
            raise ValueError("action must be one of: set, up, down, mute, unmute")
        cast.wait()
        return {
            "action": action,
            "volume_level": cast.status.volume_level,
            "volume_muted": cast.status.volume_muted,
        }


@mcp.tool
def cast_quit_app(device: str) -> dict:
    """Stop the currently running app on a Cast device (returns it to idle)."""
    info = _resolve(device)
    with _connect(info) as cast:
        cast.quit_app()
        return {"quit": True, "is_idle": cast.is_idle}


@mcp.tool
def eureka_info(device: str, params: str = "device_info,name,net,wifi") -> dict:
    """Fetch raw /setup/eureka_info from a Cast device port 8008.
    params: comma-separated eureka params (device_info,name,net,wifi,setup,...)"""
    info = _resolve(device)
    url = f"http://{info.host}:8008/setup/eureka_info?params={params}"
    with urllib.request.urlopen(url, timeout=8) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    mcp.run(transport="http", host=BIND_HOST, port=PORT, path="/mcp")
