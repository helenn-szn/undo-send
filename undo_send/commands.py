"""/unsend, /sendnow and /undo-send list, plus the 'undo' chat reply."""

from __future__ import annotations

import time

from .store import Store

UNDO_WORDS = {"undo", "unsend", "/unsend", "stop sending", "cancel send", "don't send", "dont send"}


def parse_arg(name: str, args: tuple, kwargs: dict) -> str:
    """Pull the text after the command, however Hermes passed it."""
    parts: list[str] = []
    for v in list(args) + [kwargs.get(k) for k in ("raw", "raw_args", "args", "text", "argument")]:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
    words = " ".join(parts).split()
    if words and words[0].lstrip("/").lower() == name:
        words = words[1:]
    return " ".join(words)


def _fmt(row: dict) -> str:
    left = max(0, int(row["due"] - time.time()))
    return f"[{row['id']}] {row['summary']} ({left}s left)"


def undo(store: Store, raw: str = "") -> str:
    target = (raw or "").strip() or "last"
    if target == "all":
        rows = store.pending()
        n = sum(store.cancel(r["id"]) for r in rows)
        return f"Cancelled {n} pending action(s)." if n else "Nothing is waiting to send."
    row = store.latest_pending() if target == "last" else store.get(target)
    if not row:
        return "Nothing is waiting to send."
    if store.cancel(row["id"]):
        return f"Undone. It never ran: {row['summary']}"
    return f"Too late, that action already {row['status']}: {row['summary']}"


def send_now(store: Store, raw: str = "") -> str:
    target = (raw or "").strip() or "last"
    row = store.latest_pending() if target == "last" else store.get(target)
    if not row or not store.send_now(row["id"]):
        return "Nothing is waiting to send."
    return f"Sending now: {row['summary']}"


def listing(store: Store, raw: str = "", holder=None) -> str:
    if (raw or "").strip() == "debug":
        seen = list(holder.seen) if holder is not None else []
        head = f"store: {store.path}\n"
        return head + ("Tool calls seen by undo-send:\n" + "\n".join(seen) if seen
                       else "undo-send has not seen any tool calls in this process yet.")
    rows = store.pending()
    if not rows:
        recent = store.recent(5)
        if not recent:
            return "Nothing held yet."
        return "Nothing waiting. Recent:\n" + "\n".join(
            f"[{r['id']}] {r['status']}: {r['summary']}" for r in recent
        )
    return "Waiting to send:\n" + "\n".join(_fmt(r) for r in rows)


def _authorized(gateway, source) -> bool:
    """pre_gateway_dispatch runs before Hermes' own sender check, so check it
    here. Fail closed: if we can't tell, the message is left alone."""
    check = getattr(gateway, "_is_user_authorized", None)
    if source is None or not callable(check):
        return False
    try:
        return bool(check(source))
    except Exception:
        return False


def gateway_hook(store: Store):
    """pre_gateway_dispatch: a bare 'undo' from an authorized user in
    Telegram/WhatsApp/etc. cancels the newest waiting action, even while the
    agent is busy holding it, and replies with what happened."""

    async def hook(event=None, gateway=None, **_):
        text = str(getattr(event, "text", "") or "").strip().lower()
        if text not in UNDO_WORDS or not store.pending():
            return None  # normal message: dispatch as usual
        source = getattr(event, "source", None)
        if not _authorized(gateway, source):
            return None  # let Hermes' own auth handle (and refuse) it
        reply = undo(store, "last")
        try:
            adapter = (getattr(gateway, "adapters", None) or {}).get(source.platform)
            if adapter is not None:
                await adapter.send(source.chat_id, f"↩ {reply}",
                                   reply_to=getattr(event, "message_id", None))
        except Exception:
            pass  # the cancel already happened; a failed confirmation is cosmetic
        return {"action": "skip", "reason": "undo-send cancelled a held action"}

    return hook
