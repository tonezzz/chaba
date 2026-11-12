"""Add or update the OpenChamber panel immediately before Ada Code."""

from copy import deepcopy

OCB_VIEW = {
    "title": "OpenChamber",
    "path": "ada-ocb",
    "icon": "mdi:hexagon-multiple-outline",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://ada-ocb.surf-thailand.com/",
        }
    ],
}


def mutate(config):
    views = config.get("views")
    if not isinstance(views, list):
        raise ValueError("Ada chaba-admin dashboard has no views list")

    ada_code_index = next(
        (i for i, view in enumerate(views) if view.get("path") == "ada-code"),
        None,
    )
    if ada_code_index is None:
        raise ValueError("Ada chaba-admin dashboard has no ada-code view")

    ocb_indexes = [i for i, view in enumerate(views) if view.get("path") == "ada-ocb"]
    if len(ocb_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate ada-ocb views")

    if ocb_indexes:
        current_index = ocb_indexes[0]
        views.pop(current_index)
        if current_index < ada_code_index:
            ada_code_index -= 1
    views.insert(ada_code_index, deepcopy(OCB_VIEW))
    return config
