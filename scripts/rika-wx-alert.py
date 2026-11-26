#!/usr/bin/env python3
"""rika-wx-alert — RK600 weather alerts to the mn-ha Telegram group.

Polls RikaCloud /data/22100502; alerts on wind >= WIND_KT knots or rain
(e5 > 0). Edge-triggered per condition, re-alert at most every REPEAT_S
while sustained, plus an all-clear when it drops back. Stale dataTime =>
no alert (upload-outage tracking belongs to rika-hmi-watch).

Deployed copy: ~/.local/bin/rika-wx-alert.py on idc03
(rika-wx-alert.timer, every 60s). This repo file is canonical.
"""
import json, os, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.path.expanduser("~/.local/state/rika-wx-alert"))
STATE = STATE_DIR / "state.json"
LOG = STATE_DIR / "alert.log"
TOKEN_CACHE = STATE_DIR / "token.txt"
RIKA_ENV = os.path.expanduser("~/.config/secrets/rikacloud.env")
TG_ENV = os.path.expanduser("~/.config/secrets/telegram-mn-bot.env")
API = "http://39.99.253.232:8005"
FACILITY = "22100502"
WIND_KT = 15.0            # e2 is cm/s -> kt = e2/100*1.94384
WIND_E2 = int(WIND_KT / 1.94384 * 100)  # ~= 772
FRESH_S = 300             # ignore data older than 5 min
REPEAT_S = 3600           # sustained re-alert cadence
CHAT_ID = "-5426710106"   # mn-ha group: tony + michael + kraut
UA = "rika-wx-alert/1.0"


def load_env(path):
    env = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        pass
    return env


def load_state():
    """Missing/empty/corrupt state -> {} — a 0-byte STATE must not kill the
    run before it can rewrite it (card
    state-write-atomic-truncate-crash-loop)."""
    try:
        st = json.loads(STATE.read_text())
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def save_state(st):
    """tmp + fsync + os.replace — a kill mid-write leaves state.json.tmp,
    never a torn state.json (0-byte state -> json.loads crash-loop; card
    state-write-atomic-truncate-crash-loop)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    with tmp.open("w") as f:
        f.write(json.dumps(st))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE)


def log(msg):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def http(url, data=None, headers=None, timeout=20):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if data else "GET")
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout).read()


def login(env):
    tok = json.loads(http(f"{API}/login",
        {"username": env["RIKA_ACCOUNT"], "password": env["RIKA_PASSWORD"]}))["token"]
    TOKEN_CACHE.write_text(tok)
    return tok


def fetch_latest(env):
    try:
        tok = TOKEN_CACHE.read_text().strip() if TOKEN_CACHE.exists() else None
    except Exception:
        tok = None  # torn token.txt -> re-login instead of crash-looping
    for attempt in range(2):
        if not tok:
            tok = login(env)
        try:
            return json.loads(http(f"{API}/data/{FACILITY}", headers={"token": tok}))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and attempt == 0:
                tok = None
                continue
            raise
    raise RuntimeError("unreachable")


def tg_send(text, tg_env):
    http(f"https://api.telegram.org/bot{tg_env['TELEGRAM_BOT_TOKEN']}/sendMessage",
         {"chat_id": CHAT_ID, "text": text})


def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rika = load_env(RIKA_ENV)
    tg = load_env(TG_ENV)
    st = load_state()

    row = fetch_latest(rika)
    from datetime import timedelta
    dt = datetime.strptime(row["dataTime"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone(timedelta(hours=8)))  # dataTime is +08 server time
    age = time.time() - dt.timestamp()
    if age > FRESH_S:
        log(f"stale data ({age:.0f}s old, {row['dataTime']}) — skip")
        st["checked"] = datetime.now(timezone.utc).isoformat()
        st["stale"] = True
        save_state(st)
        return

    wind_kt = (row.get("e2") or 0) / 100 * 1.94384
    rain = (row.get("e5") or 0)
    temp_c = (row.get("e3") or 0) / 10
    hum = (row.get("e4") or 0) / 10
    cond = {
        "wind": wind_kt >= WIND_KT,
        "rain": rain > 0,
    }
    now = time.time()
    msgs = []
    for name, active in cond.items():
        was = st.get(f"active_{name}", False)
        last = st.get(f"sent_{name}", 0)
        if active and (not was or now - last > REPEAT_S):
            if name == "wind":
                msgs.append(f"Wind alert (Michael site): {wind_kt:.1f} kt "
                            f"(dir {row.get('e1')} deg, {temp_c:.1f}C, {hum:.0f}% RH)")
            else:
                msgs.append(f"Rain at Michael site: intensity {rain} "
                            f"(wind {wind_kt:.1f} kt, {temp_c:.1f}C)")
            st[f"sent_{name}"] = now
        if not active and was:
            msgs.append(f"{'Wind' if name == 'wind' else 'Rain'} all-clear at Michael site "
                        f"(wind {wind_kt:.1f} kt, rain {rain})")
        st[f"active_{name}"] = active
    for m in msgs:
        try:
            tg_send(m, tg)
            log(f"SENT: {m}")
        except Exception as e:
            log(f"TG FAIL: {e} for {m}")
    st["checked"] = datetime.now(timezone.utc).isoformat()
    st["stale"] = False
    st["wind_kt"] = round(wind_kt, 1)
    st["e5"] = rain
    save_state(st)


if __name__ == "__main__":
    main()
