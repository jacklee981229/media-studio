"""Start Media Studio: the server on 127.0.0.1, then its window in Chrome. A second start just opens the window,
unless the copy running is older than the code here: then it's asked to stop and a fresh one starts.

    main.py              Jack's copy (port 4710), opens the window
    main.py --no-window  for tests and probes; set MEDIA_STUDIO_PORT for a spare port
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def running(port: int):
    """The build of the Studio answering on the port ('' for one too old to say), or None when nothing answers."""
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/hello', timeout=1) as answer:
            hello = json.load(answer)
            return hello.get('build', '') if hello.get('app') == 'media-studio' else None
    except OSError:
        return None


def stop_old(port: int) -> bool:
    """Ask a copy running older code to stop, and wait until it has. False if it won't (it predates /api/quit)."""
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/quit', data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(request, timeout=2).close()
    except OSError:
        return False
    for _ in range(50):
        if running(port) is None:
            return True
        time.sleep(0.1)
    return False


def open_window(port: int) -> None:
    """Chrome in app mode: its own window with no tabs or address bar. Any other browser if Chrome isn't there."""
    url = f'http://127.0.0.1:{port}/'
    for base in (os.environ.get('LOCALAPPDATA'), os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        chrome = Path(base or '') / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'
        if base and chrome.exists():
            subprocess.Popen([str(chrome), f'--app={url}'])
            # Not a daemon: a second start waits for the window before it exits.
            threading.Thread(target=maximize, args=('Media Studio',)).start()
            return
    webbrowser.open(url)


def maximize(title: str, seconds: float = 10) -> None:
    """Fill the screen with the window once it shows. Chrome ignores window flags when it's already running, so the
    window is found by its title (the page's) and maximized through Windows."""
    user32 = ctypes.windll.user32
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        window = user32.FindWindowW('Chrome_WidgetWin_1', title)
        if window:
            user32.ShowWindow(window, 3)  # SW_MAXIMIZE
            return
        time.sleep(0.2)


def main() -> None:
    from studio import config

    # pythonw has nowhere to print to; keep anything printed in a log beside the cache.
    if sys.stdout is None or sys.stderr is None:
        config.CACHE.mkdir(parents=True, exist_ok=True)
        log = open(config.CACHE / 'studio.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    from studio.server import build_id, serve

    window = '--no-window' not in sys.argv
    build = running(config.PORT)
    if build is not None and (build == build_id() or not stop_old(config.PORT)):
        if window:
            open_window(config.PORT)
        return

    serve(config.PORT, on_ready=(lambda: open_window(config.PORT)) if window else None)


if __name__ == '__main__':
    main()
