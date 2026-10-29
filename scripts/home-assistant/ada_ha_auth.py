"""Home Assistant refresh-token exchange helpers for Ada HA automation."""

import json
import os
import urllib.parse
import urllib.request


def get_access_token(
    ha,
    client_name=None,
    auth_path=None,
    urlopen=urllib.request.urlopen,
):
    """Exchange a named refresh token for a short-lived Home Assistant token."""
    client_name = client_name or os.environ.get(
        "ADA_HA_REFRESH_TOKEN_CLIENT", "ada-ha-live"
    )
    auth_path = auth_path or os.path.expanduser(
        "~/.config/ada-ha/.storage/auth"
    )
    with open(auth_path, encoding="utf-8") as auth_file:
        auth = json.load(auth_file)

    record = next(
        (
            item
            for item in auth["data"]["refresh_tokens"]
            if item.get("client_name") == client_name
        ),
        None,
    )
    if not record:
        raise RuntimeError(
            f"refresh token {client_name!r} not found in Ada HA auth store"
        )

    payload = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": record["token"],
        }
    ).encode()
    request = urllib.request.Request(
        ha + "/auth/token",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request) as response:
        return json.load(response)["access_token"]
