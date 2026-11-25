"""Shared test setup: a headless browser and a helper that opens the board
with a given SL response at a given Stockholm time."""
from __future__ import annotations

import copy
import glob
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BOARD = (ROOT / "web" / "index.html").as_uri()
_ALL = sorted(glob.glob(str(ROOT / "fixtures" / "recorded" / "**" / "*.json"), recursive=True))
# SL departure responses, and the Kallhäll weather recorded the same morning (if any)
RECORDED = [p for p in _ALL if not p.endswith("_weather.json")]
RECORDED_WEATHER = [p for p in _ALL if p.endswith("_weather.json")]

STOCKHOLM = ZoneInfo("Europe/Stockholm")
# The real Kallhäll weekday-morning recording that scenarios are built from
BASE_MORNING = str(ROOT / "fixtures" / "recorded" / "2026-11-16T0706_kallhall.json")
# Real Open-Meteo responses for the morning of 2026-11-16 (see fixtures/weather/)
WEATHER = {name: str(ROOT / "fixtures" / "weather" / f"2026-11-16_{name}.json")
           for name in ("kallhall_dry", "bergen_rain", "gothenburg_drizzle", "kiruna_snow")}


def weather_for(path: str) -> str | None:
    """The weather recording from the same morning as an SL recording, closest in time before it."""
    folder, name = os.path.split(path)
    same_day = [w for w in RECORDED_WEATHER if os.path.dirname(w) == folder and os.path.basename(w)[:4] <= name[:4]]
    return same_day[-1] if same_day else None


# "panel" is the Pi's 7-inch screen (1067×600)
ORIENTATIONS = {"portrait": {"width": 600, "height": 1024}, "landscape": {"width": 1024, "height": 600},
                "panel": {"width": 1067, "height": 600}}

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
    wx: hero.dataset.wx || '', wxNow: document.getElementById('wx-now').innerText,
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

    def __init__(self, page, errors, calls):
        self.page, self.errors, self._calls = page, errors, calls

    def set_time(self, dt: datetime):
        self.page.evaluate("t => window.__test.setAt(t)", iso(dt))

    def feed(self, response: dict):
        self.page.evaluate("d => window.__test.feed(d)", response)

    def state(self) -> dict:
        return self.page.evaluate(STATE_JS)

    @property
    def calls(self) -> dict:
        """How many requests the page has sent to SL and to Open-Meteo."""
        return dict(self._calls)

    def home(self) -> dict:
        """What the home screen shows."""
        return self.page.evaluate(r"""() => {
          const wx = document.getElementById('h-wx'), tr = document.getElementById('h-trains');
          return { view: document.body.dataset.view, clock: document.getElementById('h-clock').innerText,
            date: document.getElementById('h-date').innerText.split('\n').join(' · '), wxState: wx.dataset.state || '', alert: wx.dataset.alert || '',
            wxText: wx.innerText, verdict: (document.getElementById('h-verdict') || {}).innerText || '',
            hours: [...wx.querySelectorAll('.h-hour .t')].map(e => e.innerText),
            bars: wx.querySelectorAll('.h-bars').length,
            trains: tr.innerText.replace(/\s+/g, ' ').trim(), train: tr.dataset.train || '', trainWarn: tr.classList.contains('warn'),
            foot: document.getElementById('h-foot').innerText };
        }""")

    def press(self, element_id: str):
        self.page.click(f"#{element_id}")

    def tap(self):
        self.page.mouse.click(50, 50)


@pytest.fixture
def open_board(browser):
    pages = []

    def _open(response=None, when: datetime | None = None, orientation="portrait", mode="ok", sleep=False, extra="",
              weather: dict | None = None, plan: dict | None = None, view: str | None = "trains"):
        """weather: an Open-Meteo response, or None for a weather service that is down.
        plan: journeys from real journey planner answers, or None for a planner that is down. Like the
        planner, each answer holds the first 3 journeys that leave at or after the asked time.
        view: "trains" or "home" keeps that screen; None lets the board choose, as on the Pi."""
        page = browser.new_page(viewport=ORIENTATIONS[orientation])
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        calls = {"sl": 0, "weather": 0, "plan": 0}

        def handler(route):
            calls["sl"] += 1
            if mode == "ok":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(response),
                              headers={"access-control-allow-origin": "*"})
            elif mode == "error":
                route.fulfill(status=503, body="down", headers={"access-control-allow-origin": "*"})
            # mode == "hang": never answer, like a slow network

        page.route("https://transport.integration.sl.se/**", handler)

        def weather_handler(route):
            calls["weather"] += 1
            if weather is None:
                route.fulfill(status=503, body="down", headers={"access-control-allow-origin": "*"})
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(weather),
                              headers={"access-control-allow-origin": "*"})

        page.route("https://api.open-meteo.com/**", weather_handler)

        def plan_handler(route):
            calls["plan"] += 1
            if plan is None:
                route.fulfill(status=503, body="down", headers={"access-control-allow-origin": "*"})
            else:
                q = parse_qs(urlparse(route.request.url).query)
                asked = datetime.strptime(q["itd_date"][0] + q["itd_time"][0], "%Y%m%d%H%M")
                def local(j):
                    utc = datetime.fromisoformat(j["legs"][0]["origin"]["departureTimePlanned"].replace("Z", "+00:00"))
                    return utc.astimezone(ZoneInfo("Europe/Stockholm")).replace(tzinfo=None)
                later = sorted((j for j in plan["journeys"] if local(j) >= asked), key=local)
                answer = {"journeys": later[:3]}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(answer),
                              headers={"access-control-allow-origin": "*"})

        page.route("https://journeyplanner.integration.sl.se/**", plan_handler)
        query = f"?at={iso(when)}" if when else "?"
        if not sleep:
            query += "&nosleep"
        if view:
            query += f"&view={view}"
        page.goto(f"{BOARD}{query}{extra}")
        page.wait_for_function("() => document.getElementById('hero').dataset.mode !== undefined", timeout=5000)
        # An asleep board fetches nothing, so there is nothing to wait for
        asleep = "document.body.classList.contains('asleep')"
        if mode == "ok":
            page.wait_for_function(f"() => {asleep} || (document.getElementById('hero').dataset.mode || '') !== 'loading'", timeout=5000)
        page.wait_for_function(f"() => {asleep} || !!document.body.dataset.weather", timeout=5000)
        page.wait_for_function(f"() => {asleep} || !!document.body.dataset.plan", timeout=5000)
        pages.append(page)
        return Board(page, errors, calls)

    yield _open
    for p in pages:
        p.close()
