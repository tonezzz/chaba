"""Remove the dead 'Ada Code' view from the ada-ha chaba-admin dashboard.

Card ada-ha-chaba-admin-ada-code-view-iframes-d1c492: the view iframed
https://ada-code.surf-thailand.com/, a public edge route retired 2026-11-24
with the opencode public-route teardown (idc02 Caddyfile; quadlets
ada-code/ada-code-enroll/jack-* removed; live opencode is now the tailnet
opencode-serve.service on idc02 100.123.163.11:4096). The tab is dead.

Option (a) — remove the view — was chosen over repointing: option (b)
duplicates the existing OpenChamber (ada-ocb) view, and option (c) is not
viable as an iframe target: opencode-serve is plain http on a tailnet
IP:port, which a public https dashboard page would block as mixed content,
and it has no auth edge. Re-adding a view later is a one-line mutate.

Only the views[path=ada-code] entry is removed; view order and every
other view stay untouched.
"""


def mutate(config):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    matches = [i for i, v in enumerate(views)
               if isinstance(v, dict) and v.get("path") == "ada-code"]
    if len(matches) != 1:
        raise ValueError(f"expected one ada-code view, found {len(matches)}")

    removed = views.pop(matches[0])
    if removed.get("title") != "Ada Code":
        raise ValueError(
            f"ada-code view title is {removed.get('title')!r}, expected 'Ada Code'")
    return config
