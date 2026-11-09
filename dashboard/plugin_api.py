"""Backend routes for the Desktop chip and the dashboard page.

Mounted by Hermes at /api/plugins/undo-send/. Reads and writes the same
SQLite store the agent's middleware polls, so a tap here cancels a held
action in any Hermes process.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

# The plugin root holds the undo_send package; make it importable here.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from undo_send.store import Store  # noqa: E402

_store = None


def store():
    global _store
    if _store is None:
        _store = Store()
    return _store


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "tool": row["tool"],
        "summary": row["summary"],
        "status": row["status"],
        "seconds_left": max(0, round(row["due"] - time.time(), 1)),
        "window": round(row["due"] - row["created"], 1),
        "created": row["created"],
        "detail": row.get("detail"),
    }


router = APIRouter()


@router.get("/pending")
def pending():
    return {"now": time.time(), "items": [_public(r) for r in store().pending()]}


@router.get("/recent")
def recent(limit: int = 20):
    return {"items": [_public(r) for r in store().recent(min(limit, 100))]}


@router.post("/unsend/{aid}")
def unsend(aid: str):
    s = store()
    row = s.get(aid)
    if not row:
        raise HTTPException(404, "No such action")
    if s.cancel(aid):
        return {"ok": True, "status": "cancelled", "summary": row["summary"]}
    return {"ok": False, "status": s.get(aid)["status"], "summary": row["summary"]}


@router.post("/sendnow/{aid}")
def sendnow(aid: str):
    ok = store().send_now(aid)
    return {"ok": ok}


@router.post("/unsend-all")
def unsend_all():
    s = store()
    n = sum(s.cancel(r["id"]) for r in s.pending())
    return {"ok": True, "cancelled": n}
