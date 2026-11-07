"""Add or update the keyless Cline panel immediately after the Board view."""

from copy import deepcopy

CLINE_VIEW = {
    "title": "Cline",
    "path": "cline",
    "icon": "mdi:code-braces",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://cline.surf-thailand.com/?v=1",
        }
    ],
}


def mutate(config):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    board_index = next(
        (
            i for i, view in enumerate(views)
            if view.get("path") == "board" or view.get("title") == "Board"
        ),
        None,
    )
    if board_index is None:
        raise ValueError("Ada chaba-admin dashboard has no Board view")

    cline_indexes = [i for i, view in enumerate(views) if view.get("path") == "cline"]
    if len(cline_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate Cline views")

    if cline_indexes:
        current_index = cline_indexes[0]
        views.pop(current_index)
        if current_index < board_index:
            board_index -= 1
    views.insert(board_index + 1, deepcopy(CLINE_VIEW))
    return config
