"""Application services: what the window does, minus the window.

The rule this layer exists to keep is that the UI holds no logic worth
testing. Opening a document, deciding whether it is dirty, detecting that it
changed underneath you, and writing it back are all here, headless; the panes
above are wiring.

Having two consumers -- the window and the CLI -- is what keeps that honest.
"""

from .buffer import ConflictError, DocumentBuffer

__all__ = ["ConflictError", "DocumentBuffer"]
