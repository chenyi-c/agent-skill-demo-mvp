"""SQLite-backed session store for research clarification sessions.

Section 3.8 of the task book: WAL mode, optimistic locking (version),
24-hour TTL, expired / unknown IDs return explicit errors.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.errors import AppError, ErrorCode

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_DB_PATH = os.path.join(_DATA_DIR, "code_navi_mvp.db")

_SESSION_TTL_HOURS = 24
_UNSET = object()

# ---------------------------------------------------------------------------
# Thread-local connection (WAL-safe single-writer)
# ---------------------------------------------------------------------------
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        _local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def _ensure_tables() -> None:
    conn = _get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_sessions (
            session_id   TEXT PRIMARY KEY,
            status       TEXT NOT NULL,
            brief_json   TEXT NOT NULL DEFAULT '{}',
            current_field TEXT,
            version      INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            expires_at   TEXT NOT NULL
        )
        """
    )
    conn.commit()


@contextmanager
def _transaction():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_ensure_tables()


def create_session(session_id: str, brief: dict) -> dict:
    """Create a new session. Raises if session_id already exists."""
    now = _now_iso()
    expires = _expires_at()
    with _transaction() as conn:
        existing = conn.execute(
            "SELECT 1 FROM research_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            raise AppError(
                ErrorCode.SESSION_CONFLICT,
                f"Session '{session_id}' already exists.",
                retryable=False,
                http_status=409,
            )
        conn.execute(
            """INSERT INTO research_sessions
               (session_id, status, brief_json, version, created_at, updated_at, expires_at)
               VALUES (?, 'collecting', ?, 1, ?, ?, ?)""",
            (session_id, json.dumps(brief, ensure_ascii=False), now, now, expires),
        )
    return _row_to_dict(
        _get_conn().execute(
            "SELECT * FROM research_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    )


def get_session(session_id: str) -> dict:
    """Get a session by ID. Raises AppError for not-found or expired."""
    row = _get_conn().execute(
        "SELECT * FROM research_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise AppError(
            ErrorCode.SESSION_NOT_FOUND,
            f"Session '{session_id}' not found.",
            retryable=False,
            http_status=404,
        )
    d = dict(row)
    expires_at = datetime.fromisoformat(d["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        raise AppError(
            ErrorCode.SESSION_EXPIRED,
            f"Session '{session_id}' expired at {d['expires_at']}.",
            retryable=False,
            http_status=410,
        )
    return d


def update_session(
    session_id: str,
    *,
    status: str | None = None,
    brief: dict | None = None,
    current_field: str | None | object = _UNSET,
    expected_version: int,
) -> dict:
    """Update a session with optimistic locking.

    Raises SESSION_CONFLICT if the version has changed.
    """
    with _transaction() as conn:
        row = conn.execute(
            "SELECT version, expires_at FROM research_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise AppError(
                ErrorCode.SESSION_NOT_FOUND,
                f"Session '{session_id}' not found.",
                retryable=False,
                http_status=404,
            )
        current_version = row["version"]
        if current_version != expected_version:
            raise AppError(
                ErrorCode.SESSION_CONFLICT,
                f"Session '{session_id}' was modified concurrently.",
                retryable=True,
                http_status=409,
            )

        new_version = current_version + 1
        set_clauses = ["version = ?", "updated_at = ?", "expires_at = ?"]
        params: list[Any] = [new_version, _now_iso(), _expires_at()]

        if status is not None:
            set_clauses.append("status = ?")
            params.append(status)
        if brief is not None:
            set_clauses.append("brief_json = ?")
            params.append(json.dumps(brief, ensure_ascii=False))
        if current_field is not _UNSET:
            set_clauses.append("current_field = ?")
            params.append(current_field)

        params.append(session_id)
        conn.execute(
            f"UPDATE research_sessions SET {', '.join(set_clauses)} WHERE session_id = ?",
            params,
        )

    return get_session(session_id)
