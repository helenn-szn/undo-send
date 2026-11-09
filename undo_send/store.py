"""Shared store of held actions.

SQLite on disk, so the agent process, the gateway and the Desktop backend
route can all see and cancel the same pending actions.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

PENDING = "pending"
SENDING = "sending"
SENT = "sent"
CANCELLED = "cancelled"
FAILED = "failed"


def default_dir() -> Path:
    try:  # Hermes' sanctioned per-plugin data root (survives updates)
        from plugins.plugin_storage import plugin_data_dir  # type: ignore

        return Path(plugin_data_dir("undo-send"))
    except Exception:
        home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
        d = home / "plugin-data" / "undo-send"
        d.mkdir(parents=True, exist_ok=True)
        return d


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path or default_dir() / "pending.db")
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    session_id TEXT,
                    created REAL NOT NULL,
                    due REAL NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT
                )"""
            )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def add(self, tool: str, summary: str, window: float, session_id: str = "") -> str:
        aid = uuid.uuid4().hex[:6]
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                (aid, tool, summary, session_id, now, now + window, PENDING, None),
            )
        return aid

    def get(self, aid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
        return dict(row) if row else None

    def _transition(self, aid: str, frm: str, to: str, detail: str | None = None) -> bool:
        """Atomic compare-and-set: only one process wins a race."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE actions SET status=?, detail=COALESCE(?, detail) WHERE id=? AND status=?",
                (to, detail, aid, frm),
            )
            return cur.rowcount == 1

    def cancel(self, aid: str) -> bool:
        return self._transition(aid, PENDING, CANCELLED)

    def send_now(self, aid: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE actions SET due=? WHERE id=? AND status=?", (time.time(), aid, PENDING)
            )
            return cur.rowcount == 1

    def claim(self, aid: str) -> bool:
        return self._transition(aid, PENDING, SENDING)

    def finish(self, aid: str, ok: bool, detail: str | None = None) -> None:
        self._transition(aid, SENDING, SENT if ok else FAILED, detail)

    def pending(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM actions WHERE status=? ORDER BY created", (PENDING,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM actions ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_pending(self) -> dict | None:
        p = self.pending()
        return p[-1] if p else None
