"""undo-send: an Undo Send grace window for outward-facing agent actions."""

from __future__ import annotations

import logging

from . import commands
from .classify import Rules
from .hold import Holder
from .store import Store

logger = logging.getLogger(__name__)


def register(ctx):
    store = Store()

    def rules() -> Rules:
        return Rules(
            hold_mcp_writes=bool(ctx.get_config("hold_mcp_writes", default=True)),
            hold_terminal_publishes=bool(ctx.get_config("hold_terminal_publishes", default=True)),
            always_hold=set(ctx.get_config("always_hold", default=[]) or []),
            never_hold=set(ctx.get_config("never_hold", default=[]) or []),
        )

    def window() -> float:
        return float(ctx.get_config("window_seconds", default=20))

    holder = Holder(store, rules, window)
    ctx.register_middleware("tool_execution", holder)

    def handler(name, fn):
        # Hermes may hand us "debug", "/undo-send debug", a list, or keywords.
        def run(*a, **kw):
            raw = commands.parse_arg(name, a, kw)
            holder.seen.append(f"/{name} called with a={a!r} kw={sorted(kw)} -> {raw!r}")
            return fn(raw)
        return run

    ctx.register_command(
        "unsend", handler("unsend", lambda raw: commands.undo(store, raw)),
        description="Cancel the action waiting to send (/unsend, /unsend <id>, /unsend all)",
    )
    ctx.register_command(
        "sendnow", handler("sendnow", lambda raw: commands.send_now(store, raw)),
        description="Skip the grace window and send the waiting action now",
    )
    ctx.register_command(
        "undo-send", handler("undo-send", lambda raw: commands.listing(store, raw, holder)),
        description="List actions waiting to send and recent outcomes (/undo-send debug)",
    )

    ctx.register_hook("pre_gateway_dispatch", commands.gateway_hook(store))
    logger.debug("undo-send registered (store: %s)", store.path)
