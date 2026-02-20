import secrets
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "/app/data/codeven.db"

AUTH_TOKEN_TTL = 24 * 60 * 60  # 24 saat


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY,
                instagram_user_id TEXT NOT NULL,
                access_token TEXT NOT NULL,
                expires_at INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            )
        """)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_account(user_id: str, instagram_user_id: str, access_token: str, expires_at: int = None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO accounts (user_id, instagram_user_id, access_token, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, instagram_user_id, access_token, expires_at),
        )


def get_account(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def list_accounts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id, instagram_user_id, expires_at FROM accounts").fetchall()
        return [dict(r) for r in rows]


def is_token_expired(account: dict) -> bool:
    if account.get("expires_at") is None:
        return False
    return time.time() > account["expires_at"] - 86400  # 1 gün kala uyar


def create_auth_token(user_id: str) -> str:
    """Tek kullanımlık auth token üret ve DB'ye kaydet."""
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + AUTH_TOKEN_TTL
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
            (token, user_id, expires_at),
        )
    return token


def consume_auth_token(token: str) -> str | None:
    """
    Token'ı doğrula ve kullanıldı olarak işaretle.
    Geçerliyse user_id döner, geçersiz/süresi dolmuş/kullanılmışsa None döner.
    """
    now = int(time.time())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at, used FROM auth_tokens WHERE token = ?",
            (token,),
        ).fetchone()

        if row is None:
            return None
        if row["used"] or row["expires_at"] < now:
            return None

        conn.execute("UPDATE auth_tokens SET used = 1 WHERE token = ?", (token,))
        return row["user_id"]
