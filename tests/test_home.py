"""Tests for the home screen and for which screen the board shows."""
from __future__ import annotations

import copy
from datetime import datetime

from conftest import BASE_MORNING, WEATHER, load_fixture, shifted

BASE = shifted(load_fixture(BASE_MORNING)["response"], -30)
MON = datetime(2026, 11, 16)


def t(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return MON.replace(hour=h, minute=m)


def wx(name: str, feels_offset: float | None = None, sun: bool = False) -> dict:
    """A real Open-Meteo answer from the fixtures. The recorded answers predate the board asking for
    feels-like temperature and sunrise/sunset, so a test that needs them adds them here."""
    data = copy.deepcopy(load_fixture(WEATHER[name])["response"])
    m = data["minutely_15"]
    if feels_offset is not None:
        m["apparent_temperature"] = [None if v is None else v + feels_offset for v in m["temperature_2m"]]
    if sun:
        data["daily"] = {"sunrise": ["2026-11-16T08:03", "2026-11-17T08:05"], "sunset": ["2026-11-16T15:03", "2026-11-17T15:01"]}
    return data


# ---------- Which screen ----------

def test_home_is_the_default_outside_the_commute(open_board):
    assert open_board(BASE, t("12:00"), view=None).home()["view"] == "home"
    assert open_board(BASE, t("06:35"), view=None).home()["view"] == "trains"


def test_weekend_morning_opens_on_home(open_board):
    assert open_board(BASE, t("06:35"), view=None, extra="&day=6").home()["view"] == "home"


def test_train_screen_goes_back_home_after_five_minutes(open_board):
    board = open_board(BASE, t("12:00"), view=None)
    board.press("h-trains")
    assert board.home()["view"] == "trains"
    board.page.evaluate("() => __test.passMinutes(4)")
    assert board.home()["view"] == "trains"
    board.page.evaluate("() => __test.passMinutes(2)")
    assert board.home()["view"] == "home"


def test_home_chosen_during_the_commute_stays(open_board):
    board = open_board(BASE, t("06:35"), view=None)
    board.press("home-btn")
    assert board.home()["view"] == "home"
    board.page.evaluate("() => __test.passMinutes(10)")
    assert board.home()["view"] == "home"
    board.press("h-trains")
    assert board.home()["view"] == "trains"


# ---------- Clock, date and sun ----------

def test_clock_date_and_next_sun_event(open_board):
    h = open_board(BASE, t("05:50"), view="home", weather=wx("kallhall_dry", sun=True)).home()
    assert h["clock"] == "05:50"
    assert h["date"] == "Monday 16 November · Sunrise 08:03"
    h = open_board(BASE, t("12:00"), view="home", weather=wx("kallhall_dry", sun=True)).home()
    assert h["date"].endswith("Sunset 15:03")
    h = open_board(BASE, t("18:00"), view="home", weather=wx("kallhall_dry", sun=True)).home()
    assert h["date"].endswith("Sunrise 08:05 tomorrow")


# ---------- Weather ----------

def test_dry_weather_says_dry_and_draws_no_bars(open_board):
    board = open_board(BASE, t("05:50"), view="home", weather=wx("kallhall_dry", feels_offset=-4))
    h = board.home()
    assert h["wxState"] == "ok" and h["alert"] == "dry" and "Dry for the next 4 hours" in h["wxText"]
    assert h["hours"] == ["06:00", "07:00", "08:00", "09:00"] and h["bars"] == 0
    assert "Feels" in h["wxText"] and "umbrella" not in h["verdict"]
    assert board.errors == []


def test_rain_ahead_asks_for_an_umbrella(open_board):
    h = open_board(BASE, t("05:50"), view="home", weather=wx("bergen_rain")).home()
    assert h["alert"] == "rain" and "RAIN" in h["wxText"]
    assert h["verdict"].endswith("umbrella") and h["bars"] == 4


def test_snow_is_snow_not_rain(open_board):
    h = open_board(BASE, t("05:50"), view="home", weather=wx("kiruna_snow")).home()
    assert h["alert"] == "snow" and "SNOW" in h["wxText"] and "umbrella" not in h["verdict"]


def test_freezing_rain_asks_for_ice_grips(open_board):
    icy = wx("bergen_rain")
    icy["minutely_15"]["weather_code"] = [66 if c == 61 else c for c in icy["minutely_15"]["weather_code"]]
    h = open_board(BASE, t("05:50"), view="home", weather=icy).home()
    assert h["alert"] == "ice" and "ICY" in h["wxText"] and "ice grips" in h["verdict"]


def test_coat_follows_feels_like(open_board):
    cold = open_board(BASE, t("05:50"), view="home", weather=wx("kallhall_dry", feels_offset=-15)).home()
    assert cold["verdict"].startswith("Winter coat, gloves")
    mild = open_board(BASE, t("05:50"), view="home", weather=wx("kallhall_dry", feels_offset=10)).home()
    assert mild["verdict"].startswith(("Jacket", "Light jacket"))


def test_old_weather_is_marked_not_updating(open_board):
    board = open_board(BASE, t("05:50"), view="home", weather=wx("kallhall_dry"))
    board.page.evaluate("() => __test.weatherAge(45)")
    h = board.home()
    assert h["wxState"] == "stale" and "not updating" in h["wxText"]


def test_weather_down_says_so(open_board):
    h = open_board(BASE, t("05:50"), view="home", weather=None).home()
    assert h["wxState"] == "none" and "Weather unavailable" in h["wxText"]


# ---------- Train bar ----------

def test_train_bar_says_when_to_leave_like_the_train_screen(open_board):
    board = open_board(BASE, t("06:35"), view="home")
    h = board.home()
    trains = open_board(BASE, t("06:35")).state()
    assert h["train"] == trains["train"] == "06:48"
    assert "Leave in 4 min" in h["trains"] and "Walk" in h["trains"] and "then 06:55" in h["trains"]
    assert board.errors == []


def test_train_bar_go_now(open_board):
    h = open_board(BASE, t("06:50"), view="home").home()
    assert "Go now" in h["trains"] and h["train"] == "06:55"


def test_train_bar_without_sl(open_board):
    h = open_board(BASE, t("06:35"), view="home", mode="error").home()
    assert "No live train times" in h["trains"] and "SL not answering" in h["foot"]


def test_cancelled_train_is_named_in_the_bar(open_board):
    data = copy.deepcopy(BASE)
    for d in data["departures"]:
        if d["direction_code"] == 1 and d["scheduled"].endswith("06:48:00"):
            d["state"] = "CANCELLED"
    h = open_board(data, t("06:35"), view="home").home()
    assert "06:48 cancelled" in h["trains"] and h["trainWarn"] and h["train"] != "06:48"
