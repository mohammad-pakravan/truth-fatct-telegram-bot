"""In-memory conversation / wizard state keyed by telegram user id."""

from __future__ import annotations

from typing import Any

_STATE: dict[int, dict[str, Any]] = {}


def get(tg_id: int) -> dict[str, Any]:
    return _STATE.setdefault(tg_id, {})


def set_state(tg_id: int, **kwargs: Any) -> dict[str, Any]:
    st = get(tg_id)
    st.update(kwargs)
    return st


def clear(tg_id: int) -> None:
    _STATE.pop(tg_id, None)


def pop(tg_id: int, key: str, default: Any = None) -> Any:
    st = get(tg_id)
    return st.pop(key, default)
