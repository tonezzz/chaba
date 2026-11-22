"""Add or update the Ada Test panel immediately before Ada Code.

Card ADA-0064 (oswe-eval-ada-test-tab): the Ada Test tab iframes the
self-hosted OpenSWE (Robin) dashboard at https://oswe.surf-thailand.com/.
Future tools under evaluation join as additional tabs in this view.
"""

from copy import deepcopy

ADA_TEST_VIEW = {
    "title": "Ada Test",
    "path": "ada-test",
    "icon": "mdi:flask-outline",
    "type": "panel",
    "cards": [
        {
            "type": "iframe",
            "url": "https://oswe.surf-thailand.com/",
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

    test_indexes = [i for i, view in enumerate(views) if view.get("path") == "ada-test"]
    if len(test_indexes) > 1:
        raise ValueError("Ada chaba-admin dashboard has duplicate ada-test views")

    if test_indexes:
        current_index = test_indexes[0]
        views.pop(current_index)
        if current_index < ada_code_index:
            ada_code_index -= 1
    views.insert(ada_code_index, deepcopy(ADA_TEST_VIEW))
    return config
