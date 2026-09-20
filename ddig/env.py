"""
Shared environment variable reader.

Always reads directly from .env file via dotenv_values() so that stale
shell environment variables (e.g. set via `export` in a parent shell)
cannot override credentials at runtime.
"""
from __future__ import annotations

from dotenv import dotenv_values

_cache: dict[str, str | None] | None = None


def get_env(key: str, default: str = "") -> str:
    """Read a value from .env, falling back to default. Never reads os.environ."""
    global _cache
    if _cache is None:
        _cache = dotenv_values()
    return _cache.get(key) or default


def reload_env() -> None:
    """Force a fresh read of .env on next get_env() call."""
    global _cache
    _cache = None