"""Rename the classic Kanban tab title to lowercase 'kanban'.

Card chaba-admin-kanban-tab-rename-lowercase: only the display title of
views[path=kanban] changes; the path, view order, and every other view
(including Kanban 2) stay untouched.
"""


def mutate(config):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    matches = [v for v in views if isinstance(v, dict) and v.get("path") == "kanban"]
    if len(matches) != 1:
        raise ValueError(f"expected one kanban view, found {len(matches)}")

    view = matches[0]
    if view.get("title") != "Kanban":
        raise ValueError(f"kanban view title is {view.get('title')!r}, expected 'Kanban'")
    view["title"] = "kanban"
    return config
