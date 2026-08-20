"""MCP RView state proxy.

This module talks to the rview PHP API over HTTP.
The API URL can be set with the RVIEW_API_URL environment variable,
defaulting to the local chaba-h3 Caddy endpoint.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _api_url():
    return os.environ.get(
        "RVIEW_API_URL",
        "http://localhost:8080/apps/rview/api/state.php",
    )


def _request(action, view_id=None, payload=None):
    payload = payload or {}
    url = _api_url()

    if action in ("list", "status"):
        qs = []
        if action == "list":
            qs.append("action=list")
        if view_id is not None:
            qs.append(f"view_id={urllib.parse.quote(view_id)}")
        if qs:
            url += "?" + "&".join(qs)
        req = urllib.request.Request(url, method="GET")
    else:
        body = {"action": action, "view_id": view_id}
        body.update(payload)
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"{e.code} {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_views():
    return _request("list")


def create_view(view_id, display_name=None):
    return _request(
        "create",
        view_id=view_id,
        payload={"display_name": display_name or view_id},
    )


def show(view_id, url, title=None, media_type="auto", enqueue=False):
    return _request(
        "show",
        view_id=view_id,
        payload={
            "url": url,
            "title": title or "",
            "media_type": media_type or "auto",
            "enqueue": bool(enqueue),
        },
    )


def queue(view_id, items, mode="replace"):
    return _request(
        "queue",
        view_id=view_id,
        payload={"items": list(items or []), "mode": mode},
    )


def control(view_id, action, value=None):
    payload = {"command": action}
    if value is not None:
        payload["value"] = value
    return _request("control", view_id=view_id, payload=payload)


def status(view_id):
    return _request("status", view_id=view_id)


def delete_view(view_id):
    return _request("delete", view_id=view_id)
