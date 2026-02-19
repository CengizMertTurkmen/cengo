import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "cengo.db"


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
