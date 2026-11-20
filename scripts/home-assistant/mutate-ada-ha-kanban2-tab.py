"""Add or update the Board2 panel immediately after the classic Kanban view."""

from copy import deepcopy


CLASSIC_KANBAN_URL = (
    "https://tony-ha.surf-thailand.com/apps/board/classic.html?v=1"
)
CURRENT_KANBAN_URL = (
    "https://tony-ha.surf-thailand.com/apps/board/index.html?v=6"
)
KANBAN2_VIEW = {
    "title": "Kanban 2",
    "path": "kanban2",
    "icon": "mdi:view-column-outline",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://tony-ha.surf-thailand.com/apps/board2/index.html?v=1",
        }
    ],
}


def mutate(config):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    classic_indexes = [
        i for i, view in enumerate(views) if view.get("path") == "kanban"
    ]
    if len(classic_indexes) != 1:
        raise ValueError(
            f"expected one classic Kanban view, found {len(classic_indexes)}"
        )

    classic_index = classic_indexes[0]
    classic_view = views[classic_index]
    classic_cards = classic_view.get("cards")
    if (
        classic_view.get("type") != "panel"
        or not isinstance(classic_cards, list)
        or len(classic_cards) != 1
        or classic_cards[0].get("url")
        not in (CURRENT_KANBAN_URL, CLASSIC_KANBAN_URL)
    ):
        raise ValueError("Kanban view no longer matches a known board URL")
    classic_view["title"] = "Kanban"
    classic_cards[0]["url"] = CLASSIC_KANBAN_URL

    kanban2_indexes = [
        i for i, view in enumerate(views) if view.get("path") == "kanban2"
    ]
    if len(kanban2_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate kanban2 views")

    if kanban2_indexes:
        current_index = kanban2_indexes[0]
        views.pop(current_index)
        if current_index < classic_index:
            classic_index -= 1

    views.insert(classic_index + 1, deepcopy(KANBAN2_VIEW))
    return config
