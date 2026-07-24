"""SQLite cache for academic search results (Section 4.8).

Uses the same database as session_store (code_navi_mvp.db).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Connection (shared with session_store — same DB, different tables)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_DB_PATH = os.path.join(_DATA_DIR, "code_navi_mvp.db")

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def _ensure_cache_table() -> None:
    _conn().execute(
        """
        CREATE TABLE IF NOT EXISTS academic_search_cache (
            cache_key    TEXT PRIMARY KEY,
            source       TEXT NOT NULL,
            query_hash   TEXT NOT NULL,
            result_json  TEXT NOT NULL,
            status       TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            expires_at   TEXT NOT NULL,
            adapter_version TEXT NOT NULL
        )
        """
    )
    _conn().commit()


_ensure_cache_table()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
SUCCESS_TTL_HOURS = 12
EMPTY_TTL_MINUTES = 5
STALE_GRACE_HOURS = 168  # 7 days — allow stale cache
ADAPTER_VERSION = "2.0.0"


def _make_key(source: str, query: str) -> str:
    h = hashlib.sha256(f"{source}:{query.strip().lower()}".encode()).hexdigest()[:32]
    return f"{source}:{h}"


def cache_get(source: str, query: str) -> dict[str, Any] | None:
    """Return cached result dict or None."""
    key = _make_key(source, query)
    row = _conn().execute(
        "SELECT * FROM academic_search_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    expires = datetime.fromisoformat(d["expires_at"])
    now = datetime.now(timezone.utc)
    if now <= expires:
        result = json.loads(d["result_json"])
        result["cache_hit"] = True
        result["stale_cache"] = False
        return result
    # Expired — stale grace period
    if now - expires < timedelta(hours=STALE_GRACE_HOURS):
        result = json.loads(d["result_json"])
        result["cache_hit"] = True
        result["stale_cache"] = True
        return result
    return None


def cache_put(
    source: str,
    query: str,
    result_json: str,
    status: str,
    ttl_seconds: int | None = None,
) -> None:
    key = _make_key(source, query)
    now = datetime.now(timezone.utc).isoformat()
    if ttl_seconds is None:
        ttl = SUCCESS_TTL_HOURS * 3600
        if status in ("empty",):
            ttl = EMPTY_TTL_MINUTES * 60
    else:
        ttl = ttl_seconds
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
    _conn().execute(
        """INSERT OR REPLACE INTO academic_search_cache
           (cache_key, source, query_hash, result_json, status, created_at, expires_at, adapter_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (key, source, key, result_json, status, now, expires, ADAPTER_VERSION),
    )
    _conn().commit()
