"""Screenshot tests: each screen in a few key states, compared with a saved picture.

They catch changes the other tests can't see, such as a wrong colour or a moved block.
To save new pictures after an intended change, run:

    UPDATE_SCREENSHOTS=1 python -m pytest tests/test_screens.py

To give the same pictures on any machine, the tests draw all text in DejaVu Sans from
tests/screenshots/fonts/ (the font the Pi uses), switch off animations, and stop the clock.
A picture passes when fewer than 0.1% of its pixels differ by more than a small amount.
"""
from __future__ import annotations

import base64
import copy
import io
import os
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from conftest import BASE_MORNING, WEATHER, load_fixture, shifted

SHOTS = Path(__file__).resolve().parent / "screenshots"
FONTS = SHOTS / "fonts"
FAILED = SHOTS / "failed"
UPDATE = os.environ.get("UPDATE_SCREENSHOTS") == "1"
PIXEL_TOLERANCE = 12      # a pixel differs when a colour channel moves by more than this (0-255)
MAX_DIFFERING = 0.001     # a picture fails when more than this share of its pixels differ

BASE = shifted(load_fixture(BASE_MORNING)["response"], -30)
MON = datetime(2026, 11, 16)
# The Pi's 7-inch panel is 1067×600; portrait is the board turned on its side
SIZES = {"landscape": "panel", "portrait": "portrait"}


def t(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return MON.replace(hour=h, minute=m)


def wx(name: str) -> dict:
    """A real Open-Meteo answer with feels-like temperature and sunrise/sunset added (see test_home.py)."""
    data = copy.deepcopy(load_fixture(WEATHER[name])["response"])
    m = data["minutely_15"]
    m["apparent_temperature"] = [None if v is None else v - 4 for v in m["temperature_2m"]]
    data["daily"] = {"sunrise": ["2026-11-16T08:03", "2026-11-17T08:05"], "sunset": ["2026-11-16T15:03", "2026-11-17T15:01"]}
    return data


# name: (open_board arguments, JavaScript to run once the board is open)
STATES = {
    "home_rain": (dict(response=BASE, when=t("05:50"), view="home", weather=wx("bergen_rain")), None),
    "home_dry": (dict(response=BASE, when=t("05:50"), view="home", weather=wx("kallhall_dry")), None),
    "home_stale_weather": (dict(response=BASE, when=t("05:50"), view="home", weather=wx("kallhall_dry")), "__test.weatherAge(45)"),
    "home_sl_down": (dict(response=None, when=t("05:50"), view="home", weather=wx("kallhall_dry"), mode="error"), None),
    "trains_leave": (dict(response=BASE, when=t("06:35"), weather=wx("kallhall_dry")), None),
    "trains_go_rain": (dict(response=BASE, when=t("06:50"), weather=wx("bergen_rain")), None),
    "trains_late": (dict(response=BASE, when=t("06:58"), weather=wx("kallhall_dry")), None),
    "trains_sl_down": (dict(response=None, when=t("06:35"), weather=wx("kallhall_dry"), mode="error"), None),
}


def _font_css() -> str:
    faces = []
    for file, weight in (("DejaVuSans.ttf", "normal"), ("DejaVuSans-Bold.ttf", "bold")):
        data = base64.b64encode((FONTS / file).read_bytes()).decode()
        faces.append(f'@font-face {{ font-family: "Board Test"; font-weight: {weight}; '
                     f'src: url(data:font/ttf;base64,{data}) format("truetype"); }}')
    return "\n".join(faces) + """
      *, *::before, *::after { font-family: "Board Test" !important; animation: none !important;
        transition: none !important; caret-color: transparent !important; }"""


FONT_CSS = _font_css()

# Stop the page's real clock: ages ("Live from SL · 0 s ago") then always read the same
FREEZE_JS = """() => {
  const T = Date.now(); Date.now = () => T;
  if (lastOk !== null) lastOk = T;
  if (weatherAt !== null) weatherAt = T;
  if (failingSince !== null) failingSince = T;
  render();
}"""

SETTLE_JS = """async () => {
  await document.fonts.load('normal 20px "Board Test"');
  await document.fonts.load('bold 20px "Board Test"');
  await document.fonts.ready;
  if (document.body.dataset.view === 'home') fitClock();
  render();
}"""


@pytest.fixture(scope="module")
def browser(browser):
    """A browser of its own, with text drawn the same way on every machine."""
    b = browser.browser_type.launch(args=["--font-render-hinting=none", "--disable-lcd-text", "--force-color-profile=srgb"])
    yield b
    b.close()


def differing_share(actual: Image.Image, expected: Image.Image) -> tuple[float, Image.Image]:
    diff = ImageChops.difference(actual, expected)
    r, g, b = diff.split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = worst.point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
    return mask.histogram()[255] / (actual.width * actual.height), mask


@pytest.mark.parametrize("orientation", list(SIZES))
@pytest.mark.parametrize("name", list(STATES))
def test_screen_looks_the_same(open_board, name, orientation):
    args, setup = STATES[name]
    board = open_board(**args, orientation=SIZES[orientation])
    board.page.evaluate(FREEZE_JS)
    if setup:
        board.page.evaluate(f"() => {setup}")
    board.page.add_style_tag(content=FONT_CSS)
    board.page.evaluate(SETTLE_JS)
    assert board.errors == []
    png = board.page.screenshot(animations="disabled", caret="hide")

    baseline = SHOTS / f"{name}_{orientation}.png"
    if UPDATE:
        baseline.write_bytes(png)
        return
    assert baseline.exists(), f"No saved picture {baseline.name}. Run with UPDATE_SCREENSHOTS=1 to save one."
    actual = Image.open(io.BytesIO(png)).convert("RGB")
    expected = Image.open(baseline).convert("RGB")
    assert actual.size == expected.size, f"{name} {orientation}: size {actual.size}, saved {expected.size}"
    share, mask = differing_share(actual, expected)
    if share > MAX_DIFFERING:
        FAILED.mkdir(exist_ok=True)
        actual.save(FAILED / f"{name}_{orientation}.png")
        mask.save(FAILED / f"{name}_{orientation}_diff.png")
        pytest.fail(f"{name} {orientation}: {share:.3%} of pixels differ (limit {MAX_DIFFERING:.1%}). "
                    f"See tests/screenshots/failed/.")
