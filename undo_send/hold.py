"""The grace-window middleware.

Registered as Hermes `tool_execution` middleware. Hermes has already run its
own availability checks, guardrails and approvals by the time this runs; we
only decide *when* (or whether) to call next_call.
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Callable

from .classify import Rules, classify, summarize
from .store import Store

POLL_SECONDS = 0.25


def cancelled_result(summary: str) -> str:
    return json.dumps({
        "status": "cancelled_by_user",
        "action": summary,
        "message": (
            "The user pressed Undo during the grace window, so this action never ran. "
            "Do not retry it or work around it unless the user asks you to."
        ),
    })


class Holder:
    def __init__(
        self,
        store: Store,
        rules_fn: Callable[[], Rules],
        window_fn: Callable[[], float],
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        self.store = store
        self.rules_fn = rules_fn
        self.window_fn = window_fn
        self.sleep = sleep
        self.clock = clock
        self.seen = deque(maxlen=15)  # diagnostics for /undo-send debug

    def __call__(self, **kwargs):
        next_call = kwargs["next_call"]
        tool_name = kwargs.get("tool_name", "")
        args = kwargs.get("args") or {}

        try:
            decision = classify(tool_name, args, self.rules_fn())
            window = max(0.0, float(self.window_fn()))
        except Exception as exc:
            self.seen.append(f"{tool_name}: classifier error {exc!r}, ran immediately")
            return next_call(args)  # fail open: never break a tool call
        self.seen.append(
            f"{tool_name}: {'HELD ' + str(int(window)) + 's' if decision.hold and window else 'passed'}"
            f" | args={sorted(args)} | kwargs={sorted(k for k in kwargs if k != 'next_call')}"
        )
        if not decision.hold or window == 0:
            return next_call(args)

        summary = summarize(tool_name, args, decision.label)
        session = str(kwargs.get("session_id") or kwargs.get("conversation_id") or "")
        aid = self.store.add(tool_name, summary, window, session)

        while True:
            row = self.store.get(aid)
            if row is None or row["status"] != "pending":
                return cancelled_result(summary)
            if self.clock() >= row["due"]:
                break
            self.sleep(POLL_SECONDS)

        if not self.store.claim(aid):  # lost the race to an Undo
            return cancelled_result(summary)
        try:
            result = next_call(args)
        except Exception as exc:
            self.store.finish(aid, ok=False, detail=str(exc)[:300])
            raise
        self.store.finish(aid, ok=True)
        return result
