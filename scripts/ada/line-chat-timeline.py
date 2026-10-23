#!/usr/bin/env python3
"""LINE journal -> WP timeline sync, per lane (idempotent).
Rebuilds the timelines[] array inside the timeline_block CPT post each run.
Media files upload once (cached by filename in state file)."""
import base64, json, mimetypes, os, re, sys, urllib.request, urllib.error
from datetime import datetime

# lane -> (LINE chat archive dir, WP timeline_block post id)
LANES = {
    "kk-ha":   ("C822026077530a29620b5041bd1a955c5", 35),
    "tony-ha": ("C4fb0ce548a58e2d758335b7e21ce3411", 69),
    "ada-ha":  ("Cb754717565d4cee5eab43a0e848654a2", 77),
    "ops":     (None, 108),   # relay/fleet anomaly stream
}
OPS_SUPPRESS_MIN = 15  # collapse repeats of (code, chat_id)
MEDIA_ROOT = os.path.expanduser("~/.local/share/ada/line-media")
STATE = os.path.join(MEDIA_ROOT, "wp-timeline-state.json")
OPS_EVENTS = os.path.join(MEDIA_ROOT, "ops-events.jsonl")
MAX_ITEMS = 200

env = {}
for l in open(os.path.expanduser("~/.config/secrets/wp-boards.env")):
    if "=" in l:
        k, v = l.rstrip("\n").split("=", 1); env[k] = v
BASE = env["WP_SITE_URL"].strip().rstrip("/")
AUTH = "Basic " + base64.b64encode(
    f"{env['WP_APP_USER'].strip()}:{env['WP_APP_PASSWORD'].strip()}".encode()).decode()
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

def api(method, route, data=None, raw=None, ctype="application/json", filename=None):
    route = route.replace("?", "&")
    url = f"{BASE}/index.php?rest_route=/wp/v2/{route}"
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", AUTH)
    req.add_header("User-Agent", UA)
    if body:
        req.add_header("Content-Type", ctype)
        if filename:
            req.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read())
        except Exception: return e.code, {"raw": e.read()[:200].decode(errors="replace")}

state = json.load(open(STATE)) if os.path.exists(STATE) else {"media": {}}

# --- activity CPT dedupe (card wp-activity-cpt-timeline-links) ----------
# Tool executions (renders/translate) are durable `activity` posts — a
# journal media row whose url is a post's artifact_url, or that carries
# the relay-stamped event_id, renders a link to the post instead of
# re-uploading + re-inlining the media (nothing stored twice).
def _act_norm(u):
    u = (u or "").strip()
    u = re.sub(r"^https?://boards\.h3\.gizmo-thailand\.com",
               "https://boards.surf-thailand.com", u)
    return u.split("?", 1)[0]  # relay-img URLs can carry query junk

def load_activity_maps():
    """({artifact_url: (link, title)}, {event_id: (link, title)}) over
    the most recent activity posts — failures degrade to empty maps so a
    WP outage can't wedge the timeline (items just render as before)."""
    by_url, by_event = {}, {}
    for page in range(1, 6):  # cap 500 recent rows
        s, r = api("GET", f"activity&status=private&per_page=100&page={page}")
        if s != 200 or not isinstance(r, list) or not r:
            break
        for p in r:
            meta = p.get("meta") or {}
            link = _act_norm(p.get("link")) or p.get("link") or ""
            title = html_unescape(
                (p.get("title") or {}).get("rendered") or "activity")
            au = _act_norm(meta.get("artifact_url"))
            if au:
                by_url[au] = (link, title)
            ev = (meta.get("event_id") or "").strip()
            if ev:
                by_event[ev] = (link, title)
    return by_url, by_event

def html_unescape(s):
    return s.replace("&#8217;", "'").replace("&#8211;", "-") \
            .replace("&#8212;", "—").replace("&amp;", "&")

ACT_BY_URL, ACT_BY_EVENT = load_activity_maps()

ICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'>"
        "<path d='M256 32C114.6 32 0 125.1 0 240c0 49.6 21.4 95 57 130.7C44.5 421.1 2.7 466 2.2 466.5"
        "c-2.2 2.3-2.8 5.7-1.5 8.7S4.8 480 8 480c66.3 0 116-31.8 140.6-51.4 32.7 12.3 69 19.4 107.4 19.4"
        " 141.4 0 256-93.1 256-208S397.4 32 256 32z'/></svg>")

def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def upload_media(path):
    orig = os.path.basename(path)
    if orig in state["media"]:
        return state["media"][orig]
    with open(path, "rb") as fh:
        raw = fh.read()
    head = raw[:12]
    ctype = mimetypes.guess_type(orig)[0]
    ext = None
    if head[:3] == b"\xff\xd8\xff": ctype, ext = "image/jpeg", ".jpg"
    elif head[:8] == b"\x89PNG\r\n\x1a\n": ctype, ext = "image/png", ".png"
    elif head[:4] == b"GIF8": ctype, ext = "image/gif", ".gif"
    elif head[:4] == b"%PDF": ctype, ext = "application/pdf", ".pdf"
    elif head[4:8] == b"ftyp": ctype, ext = "video/mp4", ".mp4"
    if not ctype:
        print("  media skip unknown type", orig, file=sys.stderr); return None
    if not orig.lower().endswith(ext or ""):
        name = os.path.splitext(orig)[0] + ext
    else:
        name = orig
    s, res = api("POST", "media", raw=raw, ctype=ctype, filename=name)
    if s in (200, 201) and res.get("source_url"):
        url = res["source_url"].replace("http://", "https://")
        url = re.sub(r"^https://boards\.h3\.gizmo-thailand\.com", "https://boards.surf-thailand.com", url)
        state["media"][orig] = url
        return url
    print("  media upload FAIL", orig, s, res, file=sys.stderr)
    return None


def load_ops_events():
    """ops-events.jsonl -> [(rec, count)] newest-last, suppressing
    repeats of (code, chat_id) within OPS_SUPPRESS_MIN minutes."""
    out = []
    if not os.path.exists(OPS_EVENTS):
        return out
    for ln in open(OPS_EVENTS):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("kind") != "ops":
            continue
        if out:
            prev, n = out[-1]
            if (prev.get("code") == d.get("code")
                    and prev.get("chat_id") == d.get("chat_id")):
                try:
                    gap = (datetime.fromisoformat(d["ts"])
                           - datetime.fromisoformat(prev["ts"])).total_seconds()
                    if gap < OPS_SUPPRESS_MIN * 60:
                        out[-1] = (d, n + 1)
                        continue
                except Exception:
                    pass
        out.append((d, 1))
    return out

def ops_item(rec, count):
    try:
        dt = datetime.fromisoformat(rec.get("ts", ""))
        date_s = dt.strftime("%d %b %H:%M")
    except Exception:
        date_s = (rec.get("ts") or "")[:16]
    bits = [rec.get("code", "ops")]
    if count > 1:
        bits.append(f"×{count}")
    for k in ("chat_id", "user_id", "http", "detail"):
        v = rec.get(k)
        if v:
            bits.append(f"{k}={v}")
    sev = rec.get("severity", "warn")
    color = {"error": "#b3261e", "warn": "#a05a00", "info": "#1967d2"}.get(sev, "#5f6368")
    desc = (f'<span style="color:{color};font-weight:600">{"⚠" if sev != "info" else "ℹ"} '
            f'{esc(" · ".join(str(b) for b in bits))}</span>')
    return {"icon": ICON, "date": date_s, "label": "ops",
            "description": desc, "isAddTinyEditor": False}

ops_events = load_ops_events()

for lane, (chat_id, post_id) in LANES.items():
    chat_dir = (os.path.join(MEDIA_ROOT, chat_id)
                if chat_id else None)
    # collect messages from all journals for this lane
    msgs = []
    if chat_dir and os.path.isdir(chat_dir):
        for fn in sorted(os.listdir(chat_dir)):
            if not fn.startswith("journal-"): continue
            for line in open(os.path.join(chat_dir, fn)):
                try: d = json.loads(line)
                except Exception: continue
                kind = d.get("kind")
                if kind not in ("text", "image", "file", "audio", "video", "sticker"): continue
                msgs.append(d)

    def sort_key(d):
        return (d.get("ts") or "", str(d.get("message_id") or ""))
    msgs.sort(key=sort_key)
    msgs = list(reversed(msgs[-MAX_ITEMS:]))  # newest on top

    def find_media(mid):
        if not mid or not chat_dir or not os.path.isdir(chat_dir): return None
        for f in os.listdir(chat_dir):
            if f.startswith(str(mid) + "."):
                return os.path.join(chat_dir, f)
        return None

    lane_ops = []
    for rec, n in ops_events:
        cid = rec.get("chat_id")
        if lane == "ops" or (chat_id and cid == chat_id):
            lane_ops.append(ops_item(rec, n))

    items = []
    for d in msgs:
        sender = esc(d.get("from") or ("them" if d.get("dir") == "in" else "ada"))
        ts = d.get("ts", "")
        try:
            dt = datetime.fromisoformat(ts)
            date_s = dt.strftime("%d %b %H:%M")
        except Exception:
            date_s = ts[:16]
        kind = d.get("kind")
        desc = ""
        if kind == "text":
            txt = d.get("text") or ""
            if txt.strip().startswith('{\n  "tool"'): continue  # skip internal tool chatter
            desc = esc(txt).replace("\n", "<br>")
        elif kind in ("image", "file", "audio", "video", "sticker"):
            # activity dedupe — a journal row that already produced an
            # activity post links it instead of re-inlining the media
            act = (ACT_BY_EVENT.get(str(d.get("event_id") or ""))
                   or ACT_BY_URL.get(_act_norm(d.get("url"))))
            if act:
                link, atitle = act
                desc = f'🔧 <a href="{esc(link)}">{esc(atitle)}</a>'
                if d.get("text"):
                    desc += "<br>" + esc(d["text"])
            else:
                fpath = find_media(d.get("message_id"))
                if fpath and os.path.getsize(fpath) == 0:
                    fpath = None  # zero-byte capture — nothing to upload
                murl = upload_media(fpath) if fpath else d.get("url")
                if murl:
                    if kind == "image" or (murl.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))):
                        desc = f'<img src="{murl}" style="max-width:100%" loading="lazy">'
                    else:
                        desc = f'<a href="{murl}">attachment ({kind})</a>'
                    if d.get("text"):
                        desc += "<br>" + esc(d["text"])
                else:
                    desc = f"[{kind}]"
        if not desc: continue
        items.append({"icon": ICON, "date": date_s, "label": sender,
                      "description": desc, "isAddTinyEditor": False})

    # merge lane ops entries by date desc alongside chat items
    def _it_ts(it):
        return it.get("date", "")
    items = sorted(items + lane_ops, key=_it_ts, reverse=True)

    content = ("<!-- wp:tlgb/b-timeline-block " +
               json.dumps({"timelines": items, "type": "vertical",
                           "itemPosition": "right", "labelLocation": "right"},
                          ensure_ascii=False) + " /-->")

    s2, res = api("POST", f"timeline_block/{post_id}", {"content": content})
    print(f"{lane}: items={len(items)} update={s2} modified={res.get('modified', '?')}")

json.dump(state, open(STATE, "w"), indent=1)
