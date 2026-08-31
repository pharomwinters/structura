"""Watching the workspace so the index follows external edits.

A watcher is what makes "both editors may be open on the same workspace at
once" true rather than aspirational: a note changed by anything else shows up
without a keystroke.

Two things it must get right, and they pull in opposite directions:

- **Coalescing.** Editors do not write once. They write a temp file, rename it,
  touch the mtime, and sometimes write the same bytes twice. Syncing on every
  raw event would reparse a document three times per save. Events are
  therefore collected and drained after a quiet interval.
- **Not missing the last event.** A debounce that resets on every event can
  starve under a rename storm, so the drain also fires once a maximum wait has
  elapsed since the first pending event.

Structura's own writes are handled a layer down, in `Indexer.expect`: the save
records the hash it wrote, and the event it provokes is recognised and skipped
rather than bouncing back through the parser.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .sync import Indexer, SyncReport

DEBOUNCE_S = 0.15
MAX_WAIT_S = 1.0


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher) -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        for attr in ("src_path", "dest_path"):
            raw = getattr(event, attr, None)
            if raw:
                self.watcher.enqueue(Path(str(raw)))


class Watcher:
    """Feeds filesystem events into an `Indexer`."""

    def __init__(
        self,
        indexer: Indexer,
        *,
        on_sync: Callable[[SyncReport], None] | None = None,
        debounce_s: float = DEBOUNCE_S,
        max_wait_s: float = MAX_WAIT_S,
    ) -> None:
        self.indexer = indexer
        self.on_sync = on_sync
        self.debounce_s = debounce_s
        self.max_wait_s = max_wait_s

        self._pending: set[Path] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._first_pending_at: float | None = None
        self._observer: Observer | None = None
        self._thread: threading.Thread | None = None

    # --- event intake -------------------------------------------------

    def enqueue(self, path: Path) -> None:
        """Record a path to sync. Safe to call from the watchdog thread."""
        if path.suffix.lower() != ".md":
            return
        with self._lock:
            self._pending.add(path.resolve())
            if self._first_pending_at is None:
                self._first_pending_at = time.monotonic()
        self._wake.set()

    def take_pending(self) -> set[Path]:
        with self._lock:
            pending, self._pending = self._pending, set()
            self._first_pending_at = None
        return pending

    def drain(self) -> SyncReport | None:
        """Sync whatever is pending. Returns None when nothing was."""
        pending = self.take_pending()
        if not pending:
            return None
        report = self.indexer.sync_paths(pending)
        if self.on_sync is not None:
            self.on_sync(report)
        return report

    # --- lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._observer is not None:
            return
        observer = Observer()
        observer.schedule(_Handler(self), str(self.indexer.store.root), recursive=True)
        observer.start()
        self._observer = observer

        self._thread = threading.Thread(target=self._run, name="structura-watch", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self.debounce_s)
            self._wake.clear()
            if self._stop.is_set():
                break
            with self._lock:
                if not self._pending:
                    continue
                first = self._first_pending_at or time.monotonic()
            waited = time.monotonic() - first
            # Settle: keep waiting while events are still arriving, but never
            # longer than max_wait_s since the first pending event.
            if waited < self.max_wait_s:
                time.sleep(self.debounce_s)
                if self._wake.is_set() and waited + self.debounce_s < self.max_wait_s:
                    continue
            self.drain()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> Watcher:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
