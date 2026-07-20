#!/usr/bin/env python3
"""
Camera registry generator — reads cameras.json, generates config.yml cameras section
and camera-map.html cameras array.

Usage:
  python3 generate_config.py              Generate config.yml + camera-map.html
  python3 generate_config.py --check      Test all stream URLs, update status
  python3 generate_config.py --discover        Scan Longdo + Windy for new cameras (adds to registry)
  python3 generate_config.py --discover --dry-run  Scan only, don't modify registry
  python3 generate_config.py --enable NAME   Enable a camera
  python3 generate_config.py --disable NAME  Disable a camera
  python3 generate_config.py --list      List all cameras with status
"""

import json
import os
import sys
import subprocess
import urllib.request
import urllib.error
import datetime
import time
import socket
import concurrent.futures
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
CAMERAS_JSON = SCRIPT_DIR / "cameras.json"
CONFIG_YML = SCRIPT_DIR / "config.yml"
MAP_HTML = SCRIPT_DIR / "camera-map.html"

# --- Defaults for HLS traffic cameras ---
DEFAULT_HLS_RECORD_ARGS = "-f segment -segment_time 10 -segment_format mp4 -reset_timestamps 1 -strftime 1 -an -c:v copy"
DEFAULT_HLS_INPUT_ARGS = "-analyzeduration 10000000 -probesize 10000000"
DEFAULT_RTSP_INPUT_ARGS = "-rtsp_transport tcp -analyzeduration 10000000 -probesize 10000000"
DEFAULT_DETECT = {"width": 640, "height": 480, "fps": 5}
DEFAULT_OBJECTS = ["car", "person", "motorcycle"]
DEFAULT_RECORD_RETAIN = {"alerts_days": 3, "detections_days": 3, "continuous_days": 0, "motion_days": 1}


def load_registry():
    with open(CAMERAS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(data):
    with open(CAMERAS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_map_group(registry, group_name):
    g = registry["groups"].get(group_name, {})
    return g.get("map_group", group_name.lower())


def generate_camera_yaml(cam, registry):
    """Generate YAML block for a single camera."""
    lines = []
    name = cam["name"]
    overrides = cam.get("frigate_overrides", {})

    if cam.get("stream_type") == "rtsp":
        # RTSP camera with custom config or discovered endpoint
        if overrides:
            record_args = overrides.get("ffmpeg_output_record", DEFAULT_HLS_RECORD_ARGS)
            inputs = overrides.get("ffmpeg_inputs", [])
            detect = overrides.get("detect", DEFAULT_DETECT)
            objects = overrides.get("objects", DEFAULT_OBJECTS)
            retain = overrides.get("record_retain", DEFAULT_RECORD_RETAIN)
        else:
            rtsp_url = cam.get("rtsp_url", "")
            record_args = DEFAULT_HLS_RECORD_ARGS
            inputs = [{'path': rtsp_url, 'input_args': DEFAULT_RTSP_INPUT_ARGS, 'roles': ['record', 'detect']}]
            detect = DEFAULT_DETECT
            objects = DEFAULT_OBJECTS
            retain = DEFAULT_RECORD_RETAIN
    else:
        # HLS camera
        record_args = DEFAULT_HLS_RECORD_ARGS
        hls_url = cam.get("hls_url", "")
        inputs = [{
            "path": hls_url,
            "input_args": DEFAULT_HLS_INPUT_ARGS,
            "roles": ["record", "detect"]
        }]
        detect = DEFAULT_DETECT
        objects = DEFAULT_OBJECTS
        retain = DEFAULT_RECORD_RETAIN

    enabled = cam.get("enabled", True)
    lines.append(f"  {name}:")
    lines.append(f"    enabled: {str(enabled).lower()}")
    lines.append(f"    ffmpeg:")
    lines.append(f"      output_args:")
    lines.append(f"        record: {record_args}")
    lines.append(f"      inputs:")
    for inp in inputs:
        lines.append(f"        - path: {inp['path']}")
        lines.append(f"          input_args: {inp['input_args']}")
        lines.append(f"          roles:")
        for role in inp["roles"]:
            lines.append(f"            - {role}")
    lines.append(f"    detect:")
    lines.append(f"      width: {detect['width']}")
    lines.append(f"      height: {detect['height']}")
    lines.append(f"      fps: {detect['fps']}")
    lines.append(f"    record:")
    lines.append(f"      enabled: true")
    lines.append(f"      alerts:")
    lines.append(f"        retain:")
    lines.append(f"          days: {retain['alerts_days']}")
    lines.append(f"      detections:")
    lines.append(f"        retain:")
    lines.append(f"          days: {retain['detections_days']}")
    lines.append(f"      continuous:")
    lines.append(f"        days: {retain['continuous_days']}")
    lines.append(f"      motion:")
    lines.append(f"        days: {retain['motion_days']}")
    lines.append(f"    snapshots:")
    lines.append(f"      enabled: true")
    lines.append(f"    objects:")
    lines.append(f"      track:")
    for obj in objects:
        lines.append(f"        - {obj}")

    return "\n".join(lines)


def generate_config_yml(registry):
    """Generate the cameras section and camera_groups section of config.yml."""
    # Read existing config.yml to preserve the header (everything before 'cameras:')
    # and the optional/footer sections (logger, version) that come after camera_groups.
    header = ""
    footer = ""
    if CONFIG_YML.exists():
        with open(CONFIG_YML, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract header: everything up to and including 'cameras:'
        cam_idx = content.find("\ncameras:")
        if cam_idx < 0:
            cam_idx = content.find("cameras:")
        if cam_idx >= 0:
            header = content[:cam_idx].rstrip("\n") + "\n"
        else:
            header = """# Frigate configuration template
# Docs: https://docs.frigate.video/configuration/

mqtt:
  enabled: false

detectors:
  cpu:
    type: cpu
    num_threads: 2

"""

        # Extract footer: optional sections, logger, version — everything after
        # the last camera entry but before camera_groups.
        # Strategy: find the first '# Optional:' or 'logger:' marker that appears
        # after the cameras section, then cut at camera_groups.
        footer = ""
        for marker in ["# Optional:", "logger:", "version:"]:
            m_idx = content.find(marker)
            if m_idx >= 0:
                # Find camera_groups after this marker — cut there
                cg_after = content.find("camera_groups:", m_idx)
                if cg_after >= 0:
                    footer = content[m_idx:cg_after].rstrip("\n")
                else:
                    footer = content[m_idx:].rstrip("\n")
                break

    # Generate cameras section
    lines = ["cameras:"]
    # Group cameras by their group for organized output
    cameras = registry["cameras"]
    groups = registry["groups"]

    # Sort cameras by group order then by name
    group_order = {name: g["order"] for name, g in groups.items()}
    sorted_cams = sorted(cameras, key=lambda c: (group_order.get(c["group"], 99), c["name"]))

    current_group = None
    for cam in sorted_cams:
        g = cam["group"]
        if g is None:
            continue  # Skip cameras without a group assignment
        if g != current_group:
            current_group = g
            lines.append("")
            lines.append(f"  # --- {g} ---")

        # Add comment with metadata
        if cam.get("lat") is not None:
            lines.append(f"  # {cam['title']}")
            lines.append(f"  # lat={cam['lat']}, lon={cam['lon']}")
        lines.append(generate_camera_yaml(cam, registry))
        lines.append("")

    # Generate camera_groups section
    lines.append("camera_groups:")
    for gname in sorted(groups.keys(), key=lambda n: groups[n]["order"]):
        g = groups[gname]
        cam_names = [c["name"] for c in sorted_cams if c["group"] == gname]
        lines.append(f"  {gname}:")
        lines.append(f"    order: {g['order']}")
        lines.append(f"    icon: {g['icon']}")
        lines.append(f"    cameras: {','.join(cam_names)}")

    # Append footer (optional sections, logger, version)
    if footer:
        lines.append("")
        lines.append(footer)

    output = header + "\n".join(lines) + "\n"

    with open(CONFIG_YML, "w", encoding="utf-8") as f:
        f.write(output)

    enabled = sum(1 for c in cameras if c.get("enabled", True))
    total = len(cameras)
    print(f"✅ Generated {CONFIG_YML.name}: {enabled}/{total} cameras enabled, {len(groups)} groups")


def generate_map_html(registry):
    """Generate the cameras array portion of camera-map.html."""
    cameras = registry["cameras"]
    groups = registry["groups"]

    # Build map_group lookup
    map_groups = {}
    for gname, g in groups.items():
        map_groups[gname] = g.get("map_group", gname.lower())

    # Generate cameras JS array
    cam_lines = []
    for cam in cameras:
        if cam.get("group") is None:
            continue  # Skip cameras without a group assignment
        mg = map_groups.get(cam["group"], cam["group"].lower())
        hls = cam.get("hls_url")
        hls_str = json.dumps(hls) if hls else "null"
        heading = cam.get("heading")
        heading_str = "null" if heading is None else str(heading)
        cam_lines.append(
            f'            {{\n'
            f'                name: {json.dumps(cam["name"])},\n'
            f'                title: {json.dumps(cam["title"])},\n'
            f'                lat: {cam["lat"]}, lon: {cam["lon"]},\n'
            f'                group: {json.dumps(mg)},\n'
            f'                hls: {hls_str},\n'
            f'                heading: {heading_str},\n'
            f'                frigate: {json.dumps(registry.get("frigate_url", "http://localhost:5000"))}\n'
            f'            }}'
        )
    cameras_js = ",\n".join(cam_lines)

    # Generate groupColors and groupIcons
    color_entries = []
    icon_entries = []
    legend_entries = []
    css_entries = []
    for gname in sorted(groups.keys(), key=lambda n: groups[n]["order"]):
        g = groups[gname]
        mg = g.get("map_group", gname.lower())
        color_entries.append(f"            {mg}: '{g['color']}'")
        icon_entries.append(f"            {mg}: '{g['map_icon']}'")
        legend_entries.append(
            f'        <div><span class="dot {mg}"></span> {gname}</div>'
        )
        css_entries.append(f"        .legend .{mg} {{ background: {g['color']}; }}")

    group_colors_js = ",\n".join(color_entries)
    group_icons_js = ",\n".join(icon_entries)
    legend_html = "\n".join(legend_entries)
    legend_css = "\n".join(css_entries)

    # Read existing HTML and replace the cameras array + groups section
    with open(MAP_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Replace legend CSS
    old_css_start = "        .legend .local {"
    old_css_end = ".legend .chonburi { background: #9b59b6; }"
    if old_css_start in html and old_css_end in html:
        start = html.find(old_css_start)
        end = html.find(old_css_end) + len(old_css_end)
        html = html[:start] + legend_css + html[end:]

    # Replace legend HTML
    old_legend_start = '        <div><span class="dot local"></span>'
    old_legend_end = 'DOH (ชลบุรี)</div>'
    if old_legend_start in html and old_legend_end in html:
        start = html.find(old_legend_start)
        end = html.find(old_legend_end) + len(old_legend_end)
        html = html[:start] + legend_html + html[end:]

    # Replace cameras array
    old_cams_start = "        const cameras = ["
    old_cams_end = "        ];\n\n        const groupColors"
    if old_cams_start in html and old_cams_end in html:
        start = html.find(old_cams_start)
        end = html.find(old_cams_end) + len("        ];")
        new_cams = f"        const cameras = [\n{cameras_js}\n        ];"
        html = html[:start] + new_cams + html[end:]

    # Replace groupColors
    old_gc_start = "        const groupColors = {"
    old_gc_end = "        };\n\n        const groupIcons"
    if old_gc_start in html and old_gc_end in html:
        start = html.find(old_gc_start)
        end = html.find(old_gc_end) + len("        };")
        new_gc = f"        const groupColors = {{\n{group_colors_js}\n        }};"
        html = html[:start] + new_gc + html[end:]

    # Replace groupIcons
    old_gi_start = "        const groupIcons = {"
    old_gi_end = "        };\n\n        const map"
    if old_gi_start in html and old_gi_end in html:
        start = html.find(old_gi_start)
        end = html.find(old_gi_end) + len("        };")
        new_gi = f"        const groupIcons = {{\n{group_icons_js}\n        }};"
        html = html[:start] + new_gi + html[end:]

    # Replace hardcoded localhost:5000 in snapshot functions with configurable URL
    frigate_url = registry.get("frigate_url", "http://localhost:5000")
    html = html.replace("http://localhost:5000/api/", f"{frigate_url}/api/")

    with open(MAP_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Generated {MAP_HTML.name}: {len(cameras)} cameras, {len(groups)} groups")


def check_streams(registry):
    """Test all stream URLs and update status."""
    cameras = registry["cameras"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for cam in cameras:
        url = cam.get("hls_url")
        if not url:
            print(f"  ⏭️  {cam['name']:30s} — no HLS URL (RTSP/snapshot)")
            continue

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                has_ts = ".ts" in content or ".m3u8" in content
                if has_ts:
                    status = "live"
                    print(f"  ✅ {cam['name']:30s} — LIVE")
                else:
                    status = "empty"
                    print(f"  ⚠️  {cam['name']:30s} — 200 but empty manifest")
        except urllib.error.HTTPError as e:
            status = f"http_{e.code}"
            print(f"  ❌ {cam['name']:30s} — HTTP {e.code}")
        except Exception as e:
            status = "error"
            print(f"  ❌ {cam['name']:30s} — {type(e).__name__}: {e}")

        cam["stream_status"] = status
        cam["last_checked"] = now

    save_registry(registry)
    print(f"\n✅ Updated {CAMERAS_JSON.name} with stream status")


def discover_cameras(registry):
    """Scan Longdo + Windy APIs for cameras not yet in registry."""
    existing_names = {c["name"] for c in registry["cameras"]}
    existing_camids = {c.get("camid") for c in registry["cameras"] if c.get("camid")}
    existing_hls = {c.get("hls_url") for c in registry["cameras"] if c.get("hls_url")}

    found = []

    # --- Longdo API ---
    print("🔍 Scanning Longdo API...")
    try:
        url = registry["sources"]["longdo"]["url"]
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            cams = json.loads(resp.read())
        print(f"   Found {len(cams)} cameras in Longdo API")
    except Exception as e:
        print(f"   ❌ Longdo API error: {e}")
        cams = []

    for c in cams:
        hls_url = c.get("hls_url")
        camid = c.get("camid")
        if not hls_url:
            continue
        if hls_url in existing_hls or camid in existing_camids:
            continue
        try:
            lat = float(c.get("latitude", 0))
            lon = float(c.get("longitude", 0))
        except (ValueError, TypeError):
            continue
        found.append({
            "name": camid.lower().replace("-", "_").replace(".", "_"),
            "title": c.get("title", camid),
            "lat": lat,
            "lon": lon,
            "source": "longdo",
            "stream_type": "hls",
            "hls_url": hls_url,
            "camid": camid,
            "enabled": False,
        })

    # --- Windy API ---
    print("🔍 Scanning Windy API...")
    windy_key = registry["sources"]["windy"]["api_key"]
    windy_endpoint = registry["sources"]["windy"]["endpoint"]

    # Cover Thailand with multiple nearby search centers
    centers = [
        (13.7, 100.5),   # Bangkok
        (18.8, 98.9),    # Chiang Mai
        (7.9, 98.3),     # Phuket
        (12.9, 100.9),   # Pattaya/Chonburi
        (12.6, 102.0),   # Rayong
        (16.4, 102.8),   # Khon Kaen
        (13.8, 99.9),    # Kanchanaburi
        (17.0, 104.3),   # Nakhon Phanom
        (6.9, 100.4),    # Hat Yai
    ]

    for center_lat, center_lon in centers:
        try:
            url = f"{windy_endpoint}?nearby={center_lat},{center_lon},50&limit=50&include=categories,images,location,player,urls&lang=en"
            req = urllib.request.Request(url, headers={
                "x-windy-api-key": windy_key,
                "User-Agent": "curl/8.0"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            wcams = data.get("webcams", [])
            print(f"   Found {len(wcams)} webcams near {center_lat},{center_lon}")
        except Exception as e:
            print(f"   ❌ Windy API error near {center_lat},{center_lon}: {e}")
            wcams = []

        for wc in wcams:
            urls = wc.get("urls", {})
            provider = urls.get("provider", "")
            if not provider or not provider.endswith(".m3u8"):
                continue
            if provider in existing_hls:
                continue

            loc = wc.get("location", {})
            wid = str(wc.get("webcamId", ""))
            cats = [c.get("name", "") if isinstance(c, dict) else str(c) for c in wc.get("categories", [])]

            try:
                lat = float(loc.get("latitude", 0))
                lon = float(loc.get("longitude", 0))
            except (ValueError, TypeError):
                continue

            title = wc.get("title", wid)
            name = f"windy_{wid}"

            found.append({
                "name": name,
                "title": title,
                "lat": lat,
                "lon": lon,
                "source": "windy",
                "stream_type": "hls",
                "hls_url": provider,
                "enabled": False,
                "windy_id": wid,
                "category": ", ".join(cats),
            })

        time.sleep(1)  # be polite to Windy free tier

    # Deduplicate by hls_url
    seen_hls = set()
    unique = []
    for c in found:
        if c["hls_url"] not in seen_hls:
            seen_hls.add(c["hls_url"])
            unique.append(c)

    if not unique:
        print("\n✅ No new cameras found — registry is up to date!")
        return

    print(f"\n🆕 Found {len(unique)} new cameras:")
    for c in unique:
        print(f"   {c['name']:40s}  {c['lat']:.4f}, {c['lon']:.4f}  {c['title'][:60]}")
        print(f"      HLS: {c['hls_url'][:80]}")

    # Check for --dry-run flag
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print(f"\n   (--dry-run) Not adding to registry. Run without --dry-run to add them.")
        return

    # Add to registry (disabled by default, no group)
    for c in unique:
        c["group"] = None  # User must assign a group
        registry["cameras"].append(c)

    save_registry(registry)
    print(f"\n   Added {len(unique)} cameras as disabled with no group.")
    print("   Edit cameras.json to assign groups and enable them, then run: python3 generate_config.py")


def enable_camera(registry, name):
    for cam in registry["cameras"]:
        if cam["name"] == name:
            cam["enabled"] = True
            save_registry(registry)
            print(f"✅ Enabled: {name}")
            return
    print(f"❌ Camera not found: {name}")


def disable_camera(registry, name):
    for cam in registry["cameras"]:
        if cam["name"] == name:
            cam["enabled"] = False
            save_registry(registry)
            print(f"✅ Disabled: {name}")
            return
    print(f"❌ Camera not found: {name}")


def list_cameras(registry):
    cameras = registry["cameras"]
    groups = registry["groups"]
    group_order = {name: g["order"] for name, g in groups.items()}
    sorted_cams = sorted(cameras, key=lambda c: (group_order.get(c["group"] or "~", 99), c["name"]))

    print(f"\n{'Name':<30s} {'Group':<25s} {'Enabled':<8s} {'Status':<10s} {'Lat':>9s} {'Lon':>9s}  Title")
    print("-" * 140)
    for cam in sorted_cams:
        enabled = "✅" if cam.get("enabled", True) else "❌"
        status = cam.get("stream_status", "?")
        group = cam.get("group") or "(none)"
        print(f"{cam['name']:<30s} {group:<25s} {enabled:<8s} {status:<10s} {cam['lat']:9.4f} {cam['lon']:9.4f}  {cam['title'][:50]}")
    print(f"\nTotal: {len(cameras)} cameras")


def _expand_network(net):
    base, suffix = net.rsplit('/', 1)
    if suffix == '24':
        prefix = base.rsplit('.', 1)[0]
        return [f'{prefix}.{i}' for i in range(1, 255)]
    return [base]


def _probe_rtsp(ip, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((ip, port))
            newline = '\r\n'
            req = f'OPTIONS rtsp://{ip}:{port}/ RTSP/1.0' + newline + 'CSeq: 1' + newline + 'User-Agent: curl/8.0' + newline + newline
            s.sendall(req.encode('ascii'))
            data = s.recv(512)
            if data and data.startswith(b'RTSP/1.0'):
                return (ip, port, True)
    except Exception:
        pass
    return (ip, port, False)


def discover_rtsp(registry):
    """Scan local network subnets for open RTSP services and add them to registry."""
    dry_run = '--dry-run' in sys.argv
    networks = ['192.168.1.0/24', '192.168.2.0/24']
    ports = [554, 10554, 8554]
    existing_names = {c['name'] for c in registry['cameras']}
    found = []

    targets = [(ip, port) for net in networks for ip in _expand_network(net) for port in ports]
    print(f'🔍 Scanning {len(targets)} local RTSP targets...')

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(_probe_rtsp, ip, port): (ip, port) for ip, port in targets}
        for future in concurrent.futures.as_completed(futures):
            ip, port, ok = future.result()
            if not ok:
                continue
            name = 'rtsp_' + ip.replace('.', '_') + '_' + str(port)
            title = f'Local RTSP {ip}:{port}'
            if name in existing_names:
                print(f'   {name} already in registry, skipping')
                continue
            found.append({
                'name': name,
                'title': title,
                'lat': 13.7,
                'lon': 100.5,
                'group': None,
                'source': 'rtsp-scan',
                'stream_type': 'rtsp',
                'enabled': False,
                'rtsp_url': f'rtsp://{ip}:{port}/',
                'hls_url': None,
            })
            existing_names.add(name)
            print(f'   🎥 Found RTSP: {title}')

    if not found:
        print('\n✅ No new RTSP cameras found')
        return

    print(f'\n🆕 Found {len(found)} new RTSP cameras:')
    for c in found:
        print('   {:40s}  {}'.format(c['name'], c['rtsp_url']))

    if dry_run:
        print('\n   (--dry-run) Not adding to registry. Run without --dry-run to add them.')
        return

    for c in found:
        c['group'] = None
        registry['cameras'].append(c)

    save_registry(registry)
    print(f'\n   Added {len(found)} RTSP cameras as disabled with no group.')
    print('   Edit cameras.json to set credentials/group, then run: python3 generate_config.py')


def _probe_enixma(i):
    hls_url = 'https://drr-kpp-svr02.enixma.net/live/192.168.48.{}.stream/playlist.m3u8'.format(i)
    try:
        req = urllib.request.Request(hls_url, headers={'User-Agent': 'curl/8.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read(256)
        if b'#EXTM3U' in data or b'.m3u8' in data or b'.ts' in data:
            return (i, hls_url, True)
    except Exception:
        pass
    return (i, None, False)


def discover_enixma(registry):
    """Enumerate the Enixma DRR HLS playlist server."""
    dry_run = '--dry-run' in sys.argv
    existing_names = {c['name'] for c in registry['cameras']}
    existing_hls = {c.get('hls_url') for c in registry['cameras'] if c.get('hls_url')}
    for c in registry['cameras']:
        for u in c.get('alt_urls', []):
            if u:
                existing_hls.add(u)
    found = []

    print('🔍 Scanning Enixma DRR HLS server...')
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(_probe_enixma, i): i for i in range(1, 255)}
        for future in concurrent.futures.as_completed(futures):
            i, hls_url, ok = future.result()
            if not ok or not hls_url:
                continue
            if hls_url in existing_hls:
                print('   {} already in registry, skipping'.format(hls_url))
                continue
            name = 'enixma_192_168_48_{}'.format(i)
            if name in existing_names:
                continue
            found.append({
                'name': name,
                'title': 'Enixma 192.168.48.{}'.format(i),
                'lat': 13.7,
                'lon': 100.5,
                'group': None,
                'source': 'enixma',
                'stream_type': 'hls',
                'enabled': False,
                'hls_url': hls_url,
            })
            existing_names.add(name)
            existing_hls.add(hls_url)
            print('   🎥 Found Enixma: {}'.format(hls_url))

    if not found:
        print('\n✅ No new Enixma cameras found')
        return

    print('\n🆕 Found {} new Enixma cameras:'.format(len(found)))
    for c in found:
        print('   {}'.format(c['hls_url']))

    if dry_run:
        print('\n   (--dry-run) Not adding to registry. Run without --dry-run to add them.')
        return

    for c in found:
        c['group'] = None
        registry['cameras'].append(c)

    save_registry(registry)
    print('\n   Added {} Enixma cameras as disabled with no group.'.format(len(found)))
    print('   Edit cameras.json to assign groups, then run: python3 generate_config.py')


def _probe_itic(server, name):
    hls_url = 'https://{}/hls/{}.m3u8'.format(server, name)
    try:
        req = urllib.request.Request(hls_url, headers={'User-Agent': 'curl/8.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read(256)
        if b'#EXTM3U' in data or b'.m3u8' in data or b'.ts' in data:
            return (server, name, hls_url, True)
    except Exception:
        pass
    return (server, name, None, False)


def _build_itic_candidates():
    candidates = []
    for a in range(18, 23):
        for c in range(8001, 8017):
            candidates.append('10.8.0.{}_{}'.format(a, c))
    for n in range(1, 31):
        candidates.append('charlie-new-tran-{}'.format(n))
    for n in range(5, 13):
        candidates.append('charlie-new{}'.format(n))
    for x in ['a', 'b', 'c', 'd', 'e', 'f']:
        candidates.append('cl211-{}'.format(x))
    return candidates


def discover_itic(registry):
    """Enumerate iTIC HLS playlist endpoints."""
    dry_run = '--dry-run' in sys.argv
    existing_names = {c['name'] for c in registry['cameras']}
    existing_hls = {c.get('hls_url') for c in registry['cameras'] if c.get('hls_url')}
    for c in registry['cameras']:
        for u in c.get('alt_urls', []):
            if u:
                existing_hls.add(u)
    candidates = _build_itic_candidates()
    found = []
    servers = ['camera1.iticfoundation.org', 'camerai1.iticfoundation.org']
    targets = [(s, n) for s in servers for n in candidates]
    print('🔍 Scanning iTIC HLS servers...')
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(_probe_itic, s, n): (s, n) for s, n in targets}
        for future in concurrent.futures.as_completed(futures):
            server, name, hls_url, ok = future.result()
            if not ok or not hls_url:
                continue
            if hls_url in existing_hls:
                print('   {} already in registry, skipping'.format(hls_url))
                continue
            prefix = server.split('.')[0]
            safe_name = name.replace('.', '_').replace('-', '_')
            cam_name = 'itic_{}_{}'.format(prefix, safe_name)
            if cam_name in existing_names:
                continue
            found.append({
                'name': cam_name,
                'title': 'iTIC {} {}'.format(server, name),
                'lat': 13.7,
                'lon': 100.5,
                'group': None,
                'source': 'itic',
                'stream_type': 'hls',
                'enabled': False,
                'hls_url': hls_url,
            })
            existing_names.add(cam_name)
            existing_hls.add(hls_url)
            print('   🎥 Found iTIC: {}'.format(hls_url))

    if not found:
        print('\n✅ No new iTIC cameras found')
        return

    print('\n🆕 Found {} new iTIC cameras:'.format(len(found)))
    for c in found:
        print('   {}'.format(c['hls_url']))

    if dry_run:
        print('\n   (--dry-run) Not adding to registry. Run without --dry-run to add them.')
        return

    for c in found:
        c['group'] = None
        registry['cameras'].append(c)

    save_registry(registry)
    print('\n   Added {} iTIC cameras as disabled with no group.'.format(len(found)))
    print('   Edit cameras.json to assign groups, then run: python3 generate_config.py')


def main():
    if len(sys.argv) < 2:
        # Default: generate
        registry = load_registry()
        generate_config_yml(registry)
        generate_map_html(registry)
        print("\n💡 Restart Frigate: docker compose -f frigate/docker-compose.yml restart")
        return

    cmd = sys.argv[1]

    if cmd == "--check":
        registry = load_registry()
        check_streams(registry)

    elif cmd == "--discover":
        registry = load_registry()
        discover_cameras(registry)

    elif cmd == "--discover-rtsp":
        registry = load_registry()
        discover_rtsp(registry)

    elif cmd == "--discover-enixma":
        registry = load_registry()
        discover_enixma(registry)

    elif cmd == "--discover-itic":
        registry = load_registry()
        discover_itic(registry)

    elif cmd == "--enable":
        if len(sys.argv) < 3:
            print("Usage: python3 generate_config.py --enable CAMERA_NAME")
            sys.exit(1)
        registry = load_registry()
        enable_camera(registry, sys.argv[2])
        generate_config_yml(registry)
        generate_map_html(registry)

    elif cmd == "--disable":
        if len(sys.argv) < 3:
            print("Usage: python3 generate_config.py --disable CAMERA_NAME")
            sys.exit(1)
        registry = load_registry()
        disable_camera(registry, sys.argv[2])
        generate_config_yml(registry)
        generate_map_html(registry)

    elif cmd == "--list":
        registry = load_registry()
        list_cameras(registry)

    elif cmd in ("--help", "-h"):
        print(__doc__)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
