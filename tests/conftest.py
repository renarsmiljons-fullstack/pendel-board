"""Shared test setup: a headless browser and a helper that opens the board
with a given SL response at a given Stockholm time."""
from __future__ import annotations

import copy
import glob
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BOARD = (ROOT / "web" / "index.html").as_uri()
RECORDED = sorted(glob.glob(str(ROOT / "fixtures" / "recorded" / "**" / "*.json"), recursive=True))
STOCKHOLM = ZoneInfo("Europe/Stockholm")
# The real Kallhäll weekday-morning recording that scenarios are built from
BASE_MORNING = str(ROOT / "fixtures" / "recorded" / "2026-11-16T0706_kallhall.json")

ORIENTATIONS = {"portrait": {"width": 600, "height": 1024}, "landscape": {"width": 1024, "height": 600}}

# Reads everything the tests check from the page in one call
STATE_JS = """() => {
  const hero = document.getElementById('hero');
  const list = document.getElementById('list');
  const rows = [...document.querySelectorAll('#list .row')].map(r => ({
    time: r.dataset.time, sched: r.dataset.sched, cancelled: r.dataset.cancelled === 'true',
    mine: r.classList.contains('mine'), min: (r.querySelector('.in') || {}).innerText || '',
    tag: (r.querySelector('.tag') || {}).innerText || '', note: (r.querySelector('.note') || {}).innerText || '',
    was: (r.querySelector('.was') || {}).innerText || '' }));
  return {
    mode: hero.dataset.mode || '', train: hero.dataset.train || '', big: hero.dataset.big || '',
    left: hero.dataset.left || '', pace: hero.dataset.pace || '', heroText: hero.innerText,
    band: document.getElementById('band').innerText, bandClass: document.getElementById('band').className,
    footer: document.getElementById('status').innerText, asleep: document.body.classList.contains('asleep'),
    rows, siteNote: (document.querySelector('.site-note') || {}).innerText || '',
    pageOverflowX: document.documentElement.scrollWidth > innerWidth,
    pageOverflowY: document.documentElement.scrollHeight > innerHeight,
    listClipped: list.scrollHeight > list.clientHeight + 1,
  };
}"""


def load_fixture(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def recorded_local_time(fx: dict) -> datetime:
    """The Stockholm wall-clock time the fixture was recorded, as a naive datetime."""
    utc = datetime.fromisoformat(fx["recorded_at"].replace("Z", "+00:00"))
    return utc.astimezone(STOCKHOLM).replace(tzinfo=None)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def shifted(response: dict, minutes: float) -> dict:
    """Move every time in a recorded response by `minutes` (keeps all other real fields)."""
    out = copy.deepcopy(response)
    for d in out.get("departures", []):
        for key in ("scheduled", "expected"):
            if d.get(key):
                d[key] = iso(datetime.fromisoformat(d[key]) + timedelta(minutes=minutes))
    return out


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            b = p.chromium.launch(channel="chrome")
        yield b
        b.close()


class Board:
    """An open board page with a fixed response and a controllable clock."""

    def __init__(self, page, errors):
        self.page, self.errors = page, errors

    def set_time(self, dt: datetime):
        self.page.evaluate("t => window.__test.setAt(t)", iso(dt))

    def feed(self, response: dict):
        self.page.evaluate("d => window.__test.feed(d)", response)

    def state(self) -> dict:
        return self.page.evaluate(STATE_JS)

    def tap(self):
        self.page.mouse.click(50, 50)


@pytest.fixture
def open_board(browser):
    pages = []

    def _open(response=None, when: datetime | None = None, orientation="portrait", mode="ok", sleep=False, extra=""):
        page = browser.new_page(viewport=ORIENTATIONS[orientation])
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def handler(route):
            if mode == "ok":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(response),
                              headers={"access-control-allow-origin": "*"})
            elif mode == "error":
                route.fulfill(status=503, body="down", headers={"access-control-allow-origin": "*"})
            # mode == "hang": never answer, like a slow network

        page.route("https://transport.integration.sl.se/**", handler)
        query = f"?at={iso(when)}" if when else "?"
        if not sleep:
            query += "&nosleep"
        page.goto(f"{BOARD}{query}{extra}")
        page.wait_for_function("() => document.getElementById('hero').dataset.mode !== undefined", timeout=5000)
        if mode == "ok":
            page.wait_for_function("() => (document.getElementById('hero').dataset.mode || '') !== 'loading'", timeout=5000)
        pages.append(page)
        return Board(page, errors)

    yield _open
    for p in pages:
        p.close()
