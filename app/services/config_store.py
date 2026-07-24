"""SQLite-backed runtime configuration with encrypted secret values."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values, set_key

from app.core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "code_navi_mvp.db"
ENV_PATH = PROJECT_ROOT / ".env"
MASTER_KEY_NAME = "CODE_NAVI_CONFIG_KEY"


def _connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_config (
            config_key TEXT PRIMARY KEY,
            config_value TEXT,
            is_secret INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _master_key(create: bool = False) -> bytes | None:
    value = os.getenv(MASTER_KEY_NAME)
    if not value and ENV_PATH.exists():
        value = dotenv_values(ENV_PATH).get(MASTER_KEY_NAME)
    if not value and create:
        value = Fernet.generate_key().decode("ascii")
        ENV_PATH.touch(exist_ok=True)
        set_key(str(ENV_PATH), MASTER_KEY_NAME, value, quote_mode="never")
        os.environ[MASTER_KEY_NAME] = value
    return value.encode("ascii") if value else None


def _encrypt(value: str) -> str:
    key = _master_key(create=True)
    if key is None:
        raise RuntimeError("无法初始化配置加密密钥")
    return Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str | None:
    key = _master_key(create=False)
    if key is None:
        return None
    try:
        return Fernet(key).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def get_value(key: str) -> str | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT config_value, is_secret FROM runtime_config WHERE config_key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    return _decrypt(row[0]) if row[1] else row[0]


def set_value(key: str, value: str | None, *, secret: bool = False) -> None:
    with _connection() as connection:
        if value is None:
            connection.execute("DELETE FROM runtime_config WHERE config_key = ?", (key,))
            return
        stored = _encrypt(value) if secret else value
        connection.execute(
            """
            INSERT INTO runtime_config(config_key, config_value, is_secret, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(config_key) DO UPDATE SET
                config_value=excluded.config_value,
                is_secret=excluded.is_secret,
                updated_at=excluded.updated_at
            """,
            (
                key,
                stored,
                1 if secret else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def validate_base_url(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("Base URL 必须是有效的 HTTP(S) 地址")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("远程模型地址必须使用 HTTPS；HTTP 只允许本机模型")
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不能包含用户名或密码")
    return cleaned


def load_runtime_config() -> None:
    api_key = get_value("llm_api_key")
    base_url = get_value("llm_base_url")
    model = get_value("llm_model")
    if api_key is not None:
        settings.LLM_API_KEY = api_key
    if base_url:
        settings.LLM_BASE_URL = base_url
    if model:
        settings.LLM_MODEL = model


def update_runtime_config(
    *,
    api_key_action: str,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> None:
    # Validate the complete patch before writing any value so an invalid
    # Base URL/model cannot leave a newly saved API key behind.
    if api_key_action not in {"keep", "replace", "clear"}:
        raise ValueError("api_key_action 必须是 keep、replace 或 clear")
    cleaned_key = api_key.strip() if api_key is not None else None
    if api_key_action == "replace" and not cleaned_key:
        raise ValueError("替换 API Key 时必须提供非空密钥")
    validated_url = validate_base_url(base_url) if base_url is not None else None
    cleaned_model = model.strip() if model is not None else None
    if model is not None and not cleaned_model:
        raise ValueError("模型名称不能为空")

    if api_key_action == "replace":
        set_value("llm_api_key", cleaned_key, secret=True)
        settings.LLM_API_KEY = cleaned_key
    elif api_key_action == "clear":
        set_value("llm_api_key", None, secret=True)
        settings.LLM_API_KEY = None

    if validated_url is not None:
        set_value("llm_base_url", validated_url)
        settings.LLM_BASE_URL = validated_url
    if cleaned_model is not None:
        set_value("llm_model", cleaned_model)
        settings.LLM_MODEL = cleaned_model


def config_view() -> dict[str, object]:
    key = settings.LLM_API_KEY
    hint = None
    if key:
        hint = f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "已配置"
    return {
        "api_key_configured": bool(key),
        "api_key_hint": hint,
        "base_url": settings.LLM_BASE_URL,
        "model": settings.LLM_MODEL,
    }
