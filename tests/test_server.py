"""Tests for pi/server.py: serving the board and switching the screen's HDMI signal."""
import importlib.util
import json
import os
import struct
import threading
import time
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("board_server", ROOT / "pi" / "server.py")


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Starts the server with a fake wlr-randr that logs its arguments."""
    log = tmp_path / "randr.log"
    fake = tmp_path / "bin" / "wlr-randr"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\nif [ $# -eq 0 ]; then echo \'HDMI-A-1 "Panel"\'; echo \'  Enabled: yes\'; '
                    f'else echo "$*" >> {log}; fi\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:{os.environ['PATH']}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(mod.Handler, directory=str(ROOT / "web")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def calls():
        return log.read_text().split("\n")[:-1] if log.exists() else []

    yield mod, base, calls
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def test_serves_the_board(server):
    _, base, _ = server
    status, body = get(f"{base}/index.html")
    assert status == 200 and b"<html" in body


def test_signal_follows_the_page(server):
    _, base, calls = server
    _, body = get(f"{base}/screen?want=off")
    assert json.loads(body) == {"tap": 0}
    get(f"{base}/screen?want=off")              # no change: no second call
    get(f"{base}/screen?want=on")
    assert calls() == ["--output HDMI-A-1 --off", "--output HDMI-A-1 --on"]


def test_tap_turns_signal_on_and_is_reported(server, monkeypatch):
    mod, base, calls = server
    get(f"{base}/screen?want=off")
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(mod, "input_devices", lambda: [read_fd])
    threading.Thread(target=mod.watch_taps, daemon=True).start()
    # A touchscreen press: EV_ABS movement, then BTN_TOUCH (EV_KEY 330) down
    os.write(write_fd, mod.EVENT.pack(0, 0, 3, 0, 100) + mod.EVENT.pack(0, 0, 1, 330, 1))
    deadline = time.time() + 5
    while mod.state["tap"] == 0 and time.time() < deadline:
        time.sleep(0.05)
    assert calls() == ["--output HDMI-A-1 --off", "--output HDMI-A-1 --on"]
    _, body = get(f"{base}/screen?want=off")     # the page has not seen the tap yet
    assert json.loads(body)["tap"] > 0
    assert calls()[-1] == "--output HDMI-A-1 --on", "a tap keeps the signal on for a few seconds"


def test_release_does_not_count_as_tap(server, monkeypatch):
    mod, _, _ = server
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(mod, "input_devices", lambda: [read_fd])
    threading.Thread(target=mod.watch_taps, daemon=True).start()
    os.write(write_fd, mod.EVENT.pack(0, 0, 1, 330, 0))
    time.sleep(0.3)
    assert mod.state["tap"] == 0


def test_signal_comes_back_when_the_page_goes_quiet(server):
    mod, base, calls = server
    get(f"{base}/screen?want=off")
    mod.check_page()
    assert calls()[-1] == "--output HDMI-A-1 --off", "the page asked recently"
    mod.state["last_request"] -= mod.PAGE_TIMEOUT + 1
    mod.check_page()
    assert calls()[-1] == "--output HDMI-A-1 --on"
