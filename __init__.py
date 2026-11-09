"""undo-send: an Undo Send grace window for outward-facing agent actions.

The code lives in the undo_send/ package so the dashboard route and the tests
can import it the ordinary way.
"""

from .undo_send import register

__all__ = ["register"]
