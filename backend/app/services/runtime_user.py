from __future__ import annotations

from app.core.config import APP_ENV


def require_explicit_user_id_in_cloud(
    explicit_user_id: int | None,
    *,
    operation: str,
) -> int | None:
    if explicit_user_id is not None:
        return explicit_user_id
    if APP_ENV == "cloud":
        raise RuntimeError(
            f"{operation} requires an explicit user_id in cloud runtime."
        )
    return None
