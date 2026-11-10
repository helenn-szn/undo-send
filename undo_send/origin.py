"""Which chat an action or an 'undo' came from, as "platform:chat_id"."""

from __future__ import annotations

import os


def _session_var(name: str) -> str:
    # Hermes exposes the current turn's chat as the HERMES_SESSION_* variables that tools and
    # terminal commands read; get_session_env is the reader that respects per-session values
    # when several chats run in one gateway, and falls back to the environment.
    try:
        from gateway.session_context import get_session_env  # type: ignore

        return str(get_session_env(name, "") or "")
    except Exception:
        return os.environ.get(name, "")


def _norm_platform(p) -> str:
    return str(getattr(p, "value", p) or "").strip().lower()


def current_origin() -> str:
    """Chat of the turn that's running this tool call, or "" outside a chat (CLI, Desktop, cron)."""
    platform = _norm_platform(_session_var("HERMES_SESSION_PLATFORM"))
    chat = _session_var("HERMES_SESSION_CHAT_ID")
    return f"{platform}:{chat}" if platform and chat else ""


def chat_of(source) -> str:
    """Chat an inbound gateway message came from."""
    platform = _norm_platform(getattr(source, "platform", ""))
    chat = str(getattr(source, "chat_id", "") or "")
    return f"{platform}:{chat}" if platform and chat else ""


def sender_of(source) -> str:
    """Who sent an inbound gateway message, as "platform:user_id"."""
    platform = _norm_platform(getattr(source, "platform", ""))
    user = str(getattr(source, "user_id", "") or "")
    return f"{platform}:{user}" if platform and user else ""


def parse_senders(value) -> set[str]:
    """undo_senders setting: a list (or comma-separated text) of "platform:user_id"."""
    if isinstance(value, str):
        value = value.split(",")
    out = set()
    for v in value or []:
        v = str(v).strip()
        if ":" in v:
            plat, _, uid = v.partition(":")
            out.add(f"{plat.strip().lower()}:{uid.strip()}")
    return out
