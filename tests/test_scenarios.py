"""Named scenarios: one test per state or disruption the board must handle.

Each scenario starts from the real Kallhäll morning recording, shifted 30
minutes earlier, and changes only the fields the scenario is about. The
values used (states, prediction states, message texts) are the ones SL
documents in its OpenAPI spec and uses in its messages.

After the shift, the city-bound trains are 06:40, 06:48, 06:55, 07:18, 07:33, ...
(tracks 2, 2, 2, 4, 3), and 16 November 2026 is a Monday.
"""
from __future__ import annotations

import copy
from datetime import datetime

import pytest

from conftest import BASE_MORNING, load_fixture, shifted

BASE = shifted(load_fixture(BASE_MORNING)["response"], -30)
MON = datetime(2026, 11, 16)


def t(hhmm: str, day: datetime = MON) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return day.replace(hour=h, minute=m)


def with_change(hhmm: str, **fields) -> dict:
    """The base response with one city-bound departure changed."""
    r = copy.deepcopy(BASE)
    d = next(d for d in r["departures"] if d["direction_code"] == 1 and d["scheduled"].endswith(f"T{hhmm}:00"))
    for k, v in fields.items():
        if k == "journey_state":
            d["journey"]["state"] = v
        elif k == "prediction_state":
            d["journey"]["prediction_state"] = v
        elif k == "message":
            d["deviations"] = [{"importance_level": 5, "consequence": "INFORMATION", "message": v}]
        else:
            d[k] = v
    return r


def rows(state):
    return {r["time"]: r for r in state["rows"]}


# ---------- Normal morning ----------

def test_features_easiest_on_time_train_and_offers_faster_one(open_board):
    s = open_board(BASE, t("06:35")).state()
    assert s["mode"] == "leave" and s["train"] == "06:48"
    assert s["big"] == "5" and s["pace"] == "Walk"            # 06:48 - 7.5 min walk = 06:40:30
    assert "Or the 06:40 if you go now" in s["heroText"]     # faster, earlier train at a jog
    assert rows(s)["06:48"]["mine"]
    assert s["band"].startswith("On time for work")


def test_go_mode_when_it_is_time_to_leave(open_board):
    s = open_board(BASE, t("06:50")).state()
    assert s["mode"] == "go" and s["train"] == "06:55" and s["pace"] == "Jog"
    assert "GO" in s["heroText"] and "5 MIN" in s["heroText"].upper()
    assert "Last on-time train: 06:55" in s["band"]


def test_only_a_sprint_left_says_you_will_likely_miss_it(open_board):
    s = open_board(BASE, t("06:52")).state()
    assert s["train"] == "06:55" and s["pace"] == "Usain Bolt"
    assert "likely miss it" in s["heroText"] and "07:18" in s["heroText"]


def test_late_for_work(open_board):
    s = open_board(BASE, t("06:58")).state()
    assert s["band"].startswith("Late for work")
    assert s["train"] == "07:18" and "Text work, then take the 07:18" in s["heroText"]


def test_real_tracks_are_shown_plainly_never_as_track_change(open_board):
    s = open_board(BASE, t("06:35")).state()
    notes = " ".join(r["note"] for r in s["rows"])
    assert "track 2" in notes
    assert "Track change" not in notes


def test_weekend_has_no_work_cutoff(open_board):
    sat = datetime(2026, 11, 21)
    sat_base = copy.deepcopy(BASE)
    for d in sat_base["departures"]:
        for k in ("scheduled", "expected"):
            d[k] = d[k].replace("2026-11-16", "2026-11-21")
    s = open_board(sat_base, t("06:35", sat)).state()
    assert "no work cutoff" in s["band"]
    assert "LATE FOR WORK" not in " ".join(r["note"] for r in s["rows"]).upper()


# ---------- Departure states from SL's spec ----------

@pytest.mark.parametrize("state", ["CANCELLED", "INHIBITED", "REPLACED"])
def test_cancelled_like_states_are_never_featured(open_board, state):
    s = open_board(with_change("06:48", state=state), t("06:35")).state()
    assert s["train"] == "06:55"
    assert rows(s)["06:48"]["cancelled"] and "CANCELLED" in rows(s)["06:48"]["note"]
    assert "06:48 cancelled" in s["band"]


def test_cancelled_journey_is_never_featured(open_board):
    s = open_board(with_change("06:48", journey_state="CANCELLED"), t("06:35")).state()
    assert s["train"] == "06:55" and rows(s)["06:48"]["cancelled"]


@pytest.mark.parametrize("state", ["DEPARTED", "PASSED", "MISSED", "ASSUMEDDEPARTED", "NOTEXPECTED", "NOTCALLED", "BOARDINGCLOSED"])
def test_gone_states_are_not_listed(open_board, state):
    s = open_board(with_change("06:48", state=state), t("06:35")).state()
    assert "06:48" not in rows(s) and s["train"] != "06:48"


@pytest.mark.parametrize("journey_state", ["NOTEXPECTED", "NOTRUN", "ABORTED", "COMPLETED", "ASSUMEDFINISHED"])
def test_journeys_that_will_not_run_are_not_listed(open_board, journey_state):
    s = open_board(with_change("06:48", journey_state=journey_state), t("06:35")).state()
    assert "06:48" not in rows(s)


@pytest.mark.parametrize("prediction", ["LOSTCONTACT", "UNRELIABLE"])
def test_unreliable_predictions_are_flagged(open_board, prediction):
    s = open_board(with_change("06:48", prediction_state=prediction), t("06:35")).state()
    assert "Time uncertain" in rows(s)["06:48"]["note"]


def test_departure_at_platform_is_still_listed(open_board):
    s = open_board(with_change("06:48", state="ATSTOP"), t("06:35")).state()
    assert "06:48" in rows(s)


def test_missing_expected_time_falls_back_to_scheduled(open_board):
    s = open_board(with_change("06:48", expected=None), t("06:35")).state()
    assert rows(s)["06:48"]["min"] == "13 min"


# ---------- Delays ----------

def test_delay_shows_new_time_with_original_crossed_out(open_board):
    s = open_board(with_change("06:48", expected="2026-11-16T06:52:00"), t("06:35")).state()
    r = rows(s)["06:52"]
    assert r["was"] == "06:48" and r["min"] == "17 min"


def test_delay_past_the_cutoff_makes_you_late(open_board):
    r = with_change("06:55", scheduled="2026-11-16T07:08:00", expected="2026-11-16T07:13:00")
    s = open_board(r, t("07:00")).state()
    assert s["band"].startswith("Late for work")


# ---------- Messages ----------

def test_replacement_bus_is_announced_in_the_top_card(open_board):
    r = with_change("06:48", destination="Stockholms södra ersättningsbuss mot Nynäshamn")
    s = open_board(r, t("06:35")).state()
    assert "BUS replaces your train" in s["heroText"] and "bus in" in s["heroText"]
    assert "Nynäshamn" in rows(s)["06:48"]["note"] and "ersättning" not in rows(s)["06:48"]["note"]


def test_train_that_skips_odenplan_is_flagged(open_board):
    s = open_board(with_change("06:48", message="Stannar ej vid Odenplan."), t("06:35")).state()
    assert "Does NOT stop at Odenplan" in rows(s)["06:48"]["note"]


def test_train_that_skips_other_stops_still_serves_odenplan(open_board):
    s = open_board(with_change("06:48", message="Stannar ej vid Ulriksdal, Solna."), t("06:35")).state()
    assert "Skips Ulriksdal, Solna · still stops at Odenplan" in rows(s)["06:48"]["note"]


def test_reported_track_change_is_flagged(open_board):
    s = open_board(with_change("06:48", message="Spårändring, tåget avgår från spår 3."), t("06:35")).state()
    assert "Track change" in rows(s)["06:48"]["note"]


def test_station_notice_is_shown(open_board):
    r = copy.deepcopy(BASE)
    r["stop_deviations"] = [{"id": 1, "importance_level": 5, "message": "Signalfel mellan Barkarby och Spånga. Räkna med förseningar.", "scope": {}}]
    s = open_board(r, t("06:35")).state()
    assert "Signal fault" in s["siteNote"]


def test_unknown_message_is_shown_as_is(open_board):
    s = open_board(with_change("06:48", message="Något helt nytt händer."), t("06:35")).state()
    assert "Något helt nytt händer." in rows(s)["06:48"]["note"]


# ---------- Feed problems ----------

def test_feed_error_says_no_live_times(open_board):
    s = open_board(None, t("06:35"), mode="error").state()
    assert s["mode"] == "error" and "No live times" in s["band"]


def test_slow_feed_shows_loading(open_board):
    s = open_board(None, t("06:35"), mode="hang").state()
    assert s["mode"] == "loading"


def test_old_data_is_marked(open_board):
    s = open_board(BASE, t("06:35"), extra="&stale=4").state()
    assert "Old data" in s["band"] and "≈" in s["heroText"]


def test_no_departures_at_all(open_board):
    s = open_board({"departures": [], "stop_deviations": []}, t("06:35")).state()
    assert s["mode"] == "empty" and "No trains right now" in s["heroText"]


def test_only_trains_in_the_other_direction(open_board):
    r = copy.deepcopy(BASE)
    r["departures"] = [d for d in r["departures"] if d["direction_code"] == 2]
    s = open_board(r, t("06:35")).state()
    assert s["mode"] == "empty" and s["rows"] == []


def test_new_data_replaces_old(open_board):
    board = open_board(BASE, t("06:35"))
    board.feed(with_change("06:48", state="CANCELLED"))
    assert board.state()["train"] == "06:55"


# ---------- Sleep ----------

def test_awake_on_weekday_mornings(open_board):
    assert not open_board(BASE, t("06:35"), sleep=True).state()["asleep"]


def test_asleep_outside_the_morning_and_a_tap_wakes_it(open_board):
    board = open_board(BASE, t("12:00"), sleep=True)
    assert board.state()["asleep"]
    board.tap()
    assert not board.state()["asleep"]
