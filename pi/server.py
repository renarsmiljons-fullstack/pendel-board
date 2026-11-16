#!/usr/bin/env python3
"""Local web server for the board, plus control of the screen's power.

Serves web/ on 127.0.0.1 only, so no other device can reach it.

The page decides when the board sleeps. While it sleeps, the page asks for the HDMI signal
to be off, which turns this screen's backlight off. With the signal off, the page may not
see taps, so this server reads the touchscreen directly: a tap turns the signal back on, and
the page learns about the tap from its next /screen request.

GET /screen?want=on|off
    Sets the HDMI signal and returns {"tap": <time of the last tap, in ms>}.

If the page stops asking for 60 seconds (Chromium crashed or is starting), the signal goes
back on, so the screen never stays dark by mistake.

Usage: server.py <web dir> <port>
"""
import glob
import json
import os
import select
import struct
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EV_KEY = 1
EVENT = struct.Struct("llHHi")    # struct input_event on 64-bit Linux
TAP_GRACE = 10                    # seconds to ignore want=off after a tap
PAGE_TIMEOUT = 60                 # seconds without a request before the signal goes back on

lock = threading.Lock()
state = {"on": True, "tap": 0, "last_request": time.time()}


def output_name():
    try:
        out = subprocess.run(["wlr-randr"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line and not line[0].isspace():
            return line.split()[0]
    return None


def set_signal(on):
    """Turns the HDMI signal on or off. Call with the lock held."""
    if state["on"] == on:
        return
    name = output_name()
    if not name:
        return
    try:
        subprocess.run(["wlr-randr", "--output", name, "--on" if on else "--off"], timeout=5)
        state["on"] = on
    except (OSError, subprocess.SubprocessError):
        pass


def input_devices():
    """Opens every input device except the HDMI ports' own remote-control inputs."""
    devices = []
    for path in sorted(glob.glob("/dev/input/event*")):
        name_file = f"/sys/class/input/{os.path.basename(path)}/device/name"
        try:
            with open(name_file) as f:
                if f.read().startswith("vc4-hdmi"):
                    continue
            devices.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass
    return devices


def watch_taps():
    while True:
        devices = input_devices()
        if not devices:
            time.sleep(10)
            continue
        try:
            while True:
                ready, _, _ = select.select(devices, [], [], 60)
                for fd in ready:
                    data = os.read(fd, EVENT.size * 64)
                    for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                        _, _, etype, _, value = EVENT.unpack_from(data, i)
                        if etype == EV_KEY and value == 1:
                            with lock:
                                state["tap"] = int(time.time() * 1000)
                                set_signal(True)
        except OSError:
            # A device went away (unplugged): open the list again
            for fd in devices:
                try:
                    os.close(fd)
                except OSError:
                    pass
            time.sleep(2)


def check_page():
    with lock:
        if time.time() - state["last_request"] > PAGE_TIMEOUT:
            set_signal(True)


def watchdog():
    while True:
        time.sleep(10)
        check_page()


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/screen":
            return super().do_GET()
        want = parse_qs(url.query).get("want", [""])[0]
        with lock:
            state["last_request"] = time.time()
            if want == "on":
                set_signal(True)
            elif want == "off" and time.time() * 1000 - state["tap"] > TAP_GRACE * 1000:
                set_signal(False)
            body = json.dumps({"tap": state["tap"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # the page polls every 2 seconds; don't fill the journal


def main():
    web_dir, port = sys.argv[1], int(sys.argv[2])
    threading.Thread(target=watch_taps, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=web_dir))
    server.serve_forever()


if __name__ == "__main__":
    main()
