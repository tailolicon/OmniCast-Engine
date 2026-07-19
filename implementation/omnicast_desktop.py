"""OmniCast Engine — desktop app launcher.

Double-click (via OmniCast.bat) or run `pythonw omnicast_desktop.py` to open
OmniCast as a native desktop window. It:
  1. starts the FastAPI backend (uvicorn) on 127.0.0.1:8767 in a background thread,
  2. waits for the port to come up,
  3. opens the dashboard in a native window (Edge WebView2 on Windows) — no browser.

Closing the window stops the server.

Requirements (one-time):
    pip install pywebview
Windows uses the built-in Edge WebView2 runtime (present on Win10/11).
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# pythonw.exe (no console) gives sys.stdout/stderr = None. uvicorn's logging and
# any print() then crash on the missing stream, so the window never opens. Redirect
# to a log file (useful for debugging) — fall back to devnull if that fails.
if sys.stdout is None or sys.stderr is None:
    import os as _os
    try:
        (ROOT / "output").mkdir(parents=True, exist_ok=True)
        _logf = open(ROOT / "output" / "_desktop.log", "a", buffering=1, encoding="utf-8")
    except Exception:
        _logf = open(_os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

HOST = "127.0.0.1"
PORT = 8767
URL = f"http://{HOST}:{PORT}"
_LOCK_PATH = ROOT / "output" / "_desktop.lock"
_lock_handle = None  # kept open for the process lifetime; GC/exit releases it


def _acquire_single_instance_lock() -> bool:
    """True iff this is the only OmniCast desktop process running.

    If the shortcut/launcher gets triggered repeatedly (double-click storm,
    a stuck retry, antivirus re-scan re-launch, etc.) while a previous
    instance's WebView2 shell is crashing on startup, every extra launch used
    to open (and immediately crash) ANOTHER window — that's the rapid
    open/close "flashing CMD" loop. Holding an exclusive OS lock on a file in
    output/ means every launch after the first exits instantly and silently
    (no window attempt, no crash, no flash) instead of piling on.
    """
    global _lock_handle
    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        _lock_handle = open(_LOCK_PATH, "a+")
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                _lock_handle.close()
                _lock_handle = None
                return False
        else:
            import fcntl
            try:
                fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                _lock_handle.close()
                _lock_handle = None
                return False
        return True
    except Exception:
        # If locking itself is broken for some reason, fail open (don't block
        # the app from ever starting) rather than fail closed.
        return True


def _port_open() -> bool:
    """True once the backend is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((HOST, PORT)) == 0


def _backend_healthy(timeout: float = 2.0) -> bool:
    """True only if the backend actually responds on /api/status. A raw TCP-open
    check (`_port_open`) can pass for a DYING zombie that still holds the port but
    no longer serves — opening the window against it shows 'Mất kết nối' (BUG-3)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{URL}/api/status", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


class _ServerThread(threading.Thread):
    """Runs uvicorn in-process so we can shut it down cleanly on window close."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        import uvicorn

        self._config = uvicorn.Config(
            "omnicast.api.server:app",
            host=HOST,
            port=PORT,
            reload=False,
            log_level="info",
        )
        self._server = uvicorn.Server(self._config)

    def run(self) -> None:
        self._server.run()

    def stop(self) -> None:
        self._server.should_exit = True


def main() -> None:
    if not _acquire_single_instance_lock():
        # Another instance already owns the window/server. Exit quietly —
        # this is what stops a launch storm from turning into a crash-flash loop.
        print(f"[desktop] {time.strftime('%Y-%m-%d %H:%M:%S')} another instance "
              "already running — exiting without opening a new window.")
        return

    # If something is already serving on the port, just open the window against it
    # (avoids a second backend fighting for the same port / vault.db). But verify it
    # is a HEALTHY backend, not a dying zombie still holding the port (BUG-3).
    already_up = _port_open() and _backend_healthy()
    if _port_open() and not already_up:
        # Port held but not answering: a zombie mid-shutdown or still importing.
        # Give it a few seconds to either recover or release the port before we act.
        for _ in range(20):  # ~10s
            time.sleep(0.5)
            if _backend_healthy():
                already_up = True
                break
            if not _port_open():  # zombie died → free to start our own
                break
        if _port_open() and not already_up:
            print(f"[desktop] {time.strftime('%Y-%m-%d %H:%M:%S')} port {PORT} held by "
                  "an unresponsive backend; starting fresh may fail to bind. "
                  "Close stale OmniCast/pythonw processes if the window shows 'Mất kết nối'.",
                  file=sys.stderr)
    server: _ServerThread | None = None
    if not already_up:
        server = _ServerThread()
        server.start()
        # Wait up to ~40s for the backend (model/agent imports can be slow).
        for _ in range(160):
            if _port_open():
                break
            time.sleep(0.25)
        else:
            print(f"[desktop] backend did not come up on {URL} in time", file=sys.stderr)

    try:
        import webview

        webview.create_window(
            "OmniCast Engine",
            URL,
            width=1480,
            height=940,
            min_size=(1100, 720),
            text_select=True,
        )
        # Explicit backend (edgechromium) instead of relying on autodetection —
        # some Windows setups pick the wrong one and crash silently under pythonw.
        webview.start(gui="edgechromium", debug=False)
    except Exception:
        import traceback
        print(f"[desktop] {time.strftime('%Y-%m-%d %H:%M:%S')} WebView crashed:",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":
    main()
