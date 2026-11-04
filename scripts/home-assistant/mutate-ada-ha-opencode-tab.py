"""Make the dashboard's OpenCode slot Ada-first and retain a worker tab."""

from copy import deepcopy

ADA_CONTROL_VIEW = {
    "title": "Ada Control",
    "path": "opencode-ada",
    "icon": "mdi:account-voice",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://ada-ha.surf-thailand.com/chaba-home/ai",
        }
    ],
}

OPENCODE_WORKER_VIEW = {
    "title": "OpenCode Worker",
    "path": "opencode-worker",
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

    ada_indexes = [i for i, view in enumerate(views) if view.get("path") == "opencode-ada"]
    worker_indexes = [i for i, view in enumerate(views) if view.get("path") == "opencode-worker"]
    if len(ada_indexes) > 1 or len(worker_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate OpenCode views")

    remove_indexes = sorted(ada_indexes + worker_indexes, reverse=True)
    if remove_indexes:
        current_index = min(remove_indexes)
        for index in remove_indexes:
            views.pop(index)
        if current_index < board_index:
            board_index -= len(remove_indexes)
    views[board_index + 1:board_index + 1] = [
        deepcopy(ADA_CONTROL_VIEW),
        deepcopy(OPENCODE_WORKER_VIEW),
    ]
    return config
