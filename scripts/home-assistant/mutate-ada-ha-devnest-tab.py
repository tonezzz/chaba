"""Point Ada HA's DevNest tab at the existing CMS visual report."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _page_url(config, path):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    matches = [view for view in views if view.get("path") == path]
    if len(matches) != 1:
        raise ValueError(f"expected one {path!r} view, found {len(matches)}")

    cards = matches[0].get("cards")
    if not isinstance(cards, list) or not cards or cards[0].get("type") != "iframe":
        raise ValueError(f"{path!r} view has no iframe card")
    url = cards[0].get("url")
    if not isinstance(url, str):
        raise ValueError(f"{path!r} iframe has no URL")
    return cards[0], url


def _devnest_report_url(ada_pages_url):
    parts = urlsplit(ada_pages_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not parts.scheme or not parts.netloc or not any(
        key.lower() == "api_key" and value for key, value in query
    ):
        raise ValueError("Ada Pages iframe has no reusable CMS viewer key")

    query = [(key, value) for key, value in query if key.lower() != "embed"]
    query.append(("embed", "1"))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            "/devnest-visual-map",
        )
    )


def mutate(config):
    devnest_card, _ = _page_url(config, "devnest")
    _, ada_pages_url = _page_url(config, "ada-pages")
    devnest_card["url"] = _devnest_report_url(ada_pages_url)
    return config
