"""Add or update the protected Ada/OpenCode panel immediately after Board."""

from copy import deepcopy

OPENCODE_VIEW = {
    "title": "OpenCode / Ada",
    "path": "opencode-ada",
    "icon": "mdi:code-braces",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://opencode-ada.surf-thailand.com/",
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

    opencode_indexes = [i for i, view in enumerate(views) if view.get("path") == "opencode-ada"]
    if len(opencode_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate OpenCode / Ada views")

    if opencode_indexes:
        current_index = opencode_indexes[0]
        views.pop(current_index)
        if current_index < board_index:
            board_index -= 1
    views.insert(board_index + 1, deepcopy(OPENCODE_VIEW))
    return config
