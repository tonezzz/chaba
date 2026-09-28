#!/usr/bin/env python3
"""cast-cam — "show me the security camera on the TV" scenario runner.

Flow: discover cast-capable TVs -> user selects/confirms one -> check power
state (offer to wake if off/standby) -> pick a camera -> cast via HA
camera/play_stream (HLS) -> verify playback started.

Usage:
  cast-cam.py scan                    list TVs + cameras with live states
  cast-cam.py run                     full interactive scenario
  cast-cam.py run -c xiaomi_c100      pre-pick camera
  cast-cam.py run -t "TONY-TV Cast"   pre-pick TV (still confirms power)
  cast-cam.py run --yes               no prompts (defaults: first TV + camera)

Env: HASS_TOKEN (or secrets file), HA_BASE (default http://127.0.0.1:8123)
"""
import json
import os
import sys
import time
import urllib.request

HA_BASE = os.environ.get('HA_BASE', 'http://127.0.0.1:8123')
TOKEN = os.environ.get('HASS_TOKEN') or os.environ.get('HA_LONG_LIVED_TOKEN')
if not TOKEN:
    for f in ('~/.config/secrets/home-assistant-token.env',
              '~/.config/secrets/nodered-ha.env'):
        try:
            for line in open(os.path.expanduser(f)):
                if line.startswith(('HA_LONG_LIVED_TOKEN=', 'HASS_TOKEN=')):
                    TOKEN = line.split('=', 1)[1].strip()
        except OSError:
            pass
if not TOKEN:
    sys.exit('no HA token — set HASS_TOKEN or a secrets file')

# Physical displays: cast entity -> optional power/control entity (androidtv
# can turn_on / report real power state; pure-cast devices wake on cast).
TVS = {
    'media_player.tony_tv_cast': {'power': 'media_player.tony_tv'},
    'media_player.tv_40c5000':   {'power': 'media_player.tv_40c5000'},
}
CAM_SKIP_PREFIXES = ('camera.desktop_', 'camera.tony_omen_', 'camera.chuangmi_077ac1')


def api(path, data=None):
    req = urllib.request.Request(
        HA_BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30 if data else 8) as r:
        return json.loads(r.read())


def state(eid):
    try:
        return api(f'/api/states/{eid}')
    except Exception as e:
        return {'state': 'unreachable', 'attributes': {}}


def call(domain, service, data):
    return api(f'/api/services/{domain}/{service}', data)


def cameras():
    out = []
    for e in api('/api/states'):
        eid = e['entity_id']
        if eid.startswith('camera.') and not eid.startswith(CAM_SKIP_PREFIXES) \
                and e['state'] not in ('unavailable', 'unknown'):
            out.append((eid, e['attributes'].get('friendly_name', eid)))
    return sorted(out, key=lambda c: c[1])


def tv_status(cast_eid):
    cast = state(cast_eid)
    power_eid = TVS.get(cast_eid, {}).get('power', cast_eid)
    power = state(power_eid)
    return {
        'cast_eid': cast_eid, 'power_eid': power_eid,
        'name': power['attributes'].get('friendly_name') or cast['attributes'].get('friendly_name', cast_eid),
        'cast_state': cast['state'], 'power_state': power['state'],
        'app': power['attributes'].get('app_name') or cast['attributes'].get('app_name', '-'),
    }


def ask(prompt, default=''):
    d = f' [{default}]' if default else ''
    v = input(f'{prompt}{d}: ').strip()
    return v or default


def cmd_scan(_):
    print('Cast targets (TVs):')
    for ce in TVS:
        t = tv_status(ce)
        print(f"  {t['name']:16} cast={t['cast_state']:8} power={t['power_state']:8} app={t['app']}  ({ce})")
    print('\nCameras:')
    for eid, name in cameras():
        print(f'  {name:24} {eid}')
    print(f'\ninput_select.tv_display    = {state("input_select.tv_display")["state"]}')
    print(f'input_select.tv_cast_target = {state("input_select.tv_cast_target")["state"]}')


def cmd_run(args):
    # Managed kill switch (packages/cast-safety.yaml).
    try:
        if state('input_boolean.cast_enabled')['state'] != 'on':
            sys.exit('input_boolean.cast_enabled is off — managed casting disabled')
    except KeyError:
        pass  # helper not present on this instance — continue

    cams = cameras()
    if not cams:
        sys.exit('no cameras available')

    # --- Step 1: select / confirm TV -------------------------------------
    tvs = {ce: tv_status(ce) for ce in TVS}
    names = list(tvs.values())
    print('Available TVs:')
    for i, t in enumerate(names, 1):
        print(f"  {i}. {t['name']}  (cast={t['cast_state']}, power={t['power_state']})")

    cast_eid = args.tv
    if not cast_eid:
        if len(names) == 1 or args.yes:
            pick = 0 if args.yes else int(ask(f'Select TV [1-{len(names)}]', '1')) - 1
        else:
            pick = int(ask(f'Select TV [1-{len(names)}]', '1')) - 1
        cast_eid = names[pick]['cast_eid']
    tv = tvs.get(cast_eid) or tv_status(cast_eid)
    if not args.yes and not args.tv:
        if ask(f"Cast to {tv['name']}? [Y/n]", 'y').lower().startswith('n'):
            sys.exit('aborted')

    # --- Step 2: power check / confirm-open -------------------------------
    if tv['power_state'] in ('off', 'standby', 'unavailable', 'unreachable'):
        print(f"{tv['name']} appears {tv['power_state']}.")
        if args.yes or ask('Turn it on? [Y/n]', 'y').lower().startswith('y'):
            call('media_player', 'turn_on', {'entity_id': tv['power_eid']})
            for _ in range(15):
                time.sleep(2)
                tv['power_state'] = state(tv['power_eid'])['state']
                if tv['power_state'] not in ('off', 'unavailable'):
                    break
            print(f"  -> power state: {tv['power_state']}")
        else:
            print('Continuing anyway — casting usually wakes the receiver.')
    else:
        print(f"{tv['name']} is on (app: {tv['app']})")

    # --- Step 3: pick camera ----------------------------------------------
    cam = args.camera
    if not cam:
        print('Cameras:')
        for i, (eid, name) in enumerate(cams, 1):
            print(f'  {i}. {name}')
        pick = 0 if args.yes else int(ask(f'Select camera [1-{len(cams)}]', '1')) - 1
        cam = cams[pick][0]
    cam = cam if cam.startswith('camera.') else f'camera.{cam}'

    # --- Step 4: cast ------------------------------------------------------
    # Point the shared selector at this TV so timer-driven casts agree.
    call('input_select', 'select_option',
         {'entity_id': 'input_select.tv_cast_target',
          'option': tv['name'] if tv['name'].endswith(' Cast') else f"{tv['name']} Cast"})
    print(f"Casting {cam} -> {cast_eid} (hls)…")
    try:
        call('camera', 'play_stream', {'entity_id': cam, 'media_player': cast_eid, 'format': 'hls'})
    except Exception as e:
        sys.exit(f'play_stream failed: {e}')

    # cast-ha-panel.timer re-casts input_select.tv_display every 60s and would
    # reclaim the TV. Point input_select.tv_camera at this camera first — the
    # timer's script reads it — then tv_display=camera keeps the cast alive.
    try:
        opts = state('input_select.tv_camera')['attributes'].get('options', [])
        if cam in opts:
            call('input_select', 'select_option', {'entity_id': 'input_select.tv_camera', 'option': cam})
            call('input_select', 'select_option', {'entity_id': 'input_select.tv_display', 'option': 'camera'})
            print(f"  set input_select.tv_camera={cam} + tv_display=camera — timer keeps this cast alive")
        else:
            print(f"  note: {cam} not in input_select.tv_camera options —")
            print("        the 60s timer will reclaim the TV; `systemctl --user stop cast-ha-panel.timer` to hold.")
    except KeyError:
        print("  note: input_select.tv_camera missing — timer will reclaim the TV;")
        print("        `systemctl --user stop cast-ha-panel.timer` to hold this cast.")

    # --- Step 5: verify ----------------------------------------------------
    time.sleep(6)
    after = tv_status(cast_eid)
    print(f"  cast player: {after['cast_state']}  app: {after['app']}")
    if after['cast_state'] in ('playing', 'buffering', 'idle'):
        print('TV should now show the stream. (Chromecast receivers may sit at idle briefly while HLS buffers.)')
    else:
        print(f"WARNING: unexpected state {after['cast_state']!r}")


def main():
    import argparse
    p = argparse.ArgumentParser(description='cast a security camera to a TV')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('scan')
    r = sub.add_parser('run')
    r.add_argument('-c', '--camera')
    r.add_argument('-t', '--tv')
    r.add_argument('-y', '--yes', action='store_true')
    args = p.parse_args()
    {'scan': cmd_scan, 'run': cmd_run}[args.cmd](args if args.cmd == 'run' else None)


if __name__ == '__main__':
    main()
