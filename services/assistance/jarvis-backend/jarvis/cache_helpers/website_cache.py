"""Website source cache helpers extracted from main.py."""

from typing import Any, Optional

import db_session


SESSION_DB_PATH = "sessions.db"


def website_source_cache_get(*, source_id: str) -> Optional[dict[str, Any]]:
    return db_session.website_source_cache_get(SESSION_DB_PATH, source_id=source_id)


def website_source_cache_set(*, source_id: str, content: Any) -> None:
    db_session.website_source_cache_set(SESSION_DB_PATH, source_id=source_id, content=content)
