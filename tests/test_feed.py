"""Tests for odd answers from SL, and for which trains the morning list shows."""
import json
from datetime import datetime

from conftest import BASE_MORNING, load_fixture, shifted

# The same real Monday morning the scenario tests use
BASE = shifted(load_fixture(BASE_MORNING)["response"], -30)
MON = datetime(2026, 11, 16)


def t(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return MON.replace(hour=h, minute=m)


def times(state):
    return [r["time"] for r in state["rows"]]


def test_empty_answer_keeps_last_real_times(open_board):
    board = open_board(BASE, t("06:35"))
    board.feed({"departures": [], "stop_deviations": []})
    s = board.state()
    assert s["train"] == "06:48" and "06:48" in times(s)
    assert "No trains right now" not in s["heroText"] and not s["band"].startswith("Late for work")
    assert s["footer"].startswith("No new times from SL")
    board.feed(BASE)                                         # the next real answer clears the note
    assert board.state()["footer"].startswith("Live from SL")


def test_list_is_the_next_trains_with_yours_highlighted(open_board):
    # 07:01: the 07:03 can't be caught, the 07:10 is yours, and later trains still follow
    s = open_board(BASE, t("07:01"), plan=PLAN).state()
    assert times(s)[:2] == ["07:10", "07:18"] and len(times(s)) >= 3
    assert [r["time"] for r in s["rows"] if r["mine"]] == ["07:10"]
    # 06:35: the list starts at the next train, not at yours
    s = open_board(BASE, t("06:35"), plan=PLAN).state()
    assert times(s) == ["06:40", "06:48", "06:55", "07:03"]


def test_asleep_board_fetches_nothing_and_a_tap_fetches_at_once(open_board):
    board = open_board(BASE, t("12:00"), sleep=True)
    board.page.wait_for_timeout(500)
    assert board.state()["asleep"] and board.calls == {"sl": 0, "weather": 0, "plan": 0}
    board.tap()
    board.page.wait_for_function("() => (document.getElementById('hero').dataset.mode || 'loading') !== 'loading'", timeout=5000)
    assert board.calls["sl"] == 1 and board.calls["weather"] == 1 and board.calls["plan"] >= 1
    assert not board.state()["asleep"]


# ---------- Timetable trains the live feed leaves out ----------
# Real journey planner answers for the morning of 18 November, moved to the test Monday.
PLAN = {"journeys": [j for q in ("0630", "0656") for j in json.loads(
    json.dumps(load_fixture(f"fixtures/plan/2026-11-18T{q}_kallhall_odenplan.json")["response"]).replace("2026-11-18", "2026-11-16"))["journeys"]]}


def test_timetable_fills_trains_missing_from_the_live_feed(open_board):
    # The live feed has 06:40, 06:48, 06:55, then nothing until 07:18. The timetable has 07:03 and 07:10.
    without = open_board(BASE, t("06:35")).state()
    assert without["band"].startswith("On time for work") and "07:03" not in times(without)
    s = open_board(BASE, t("06:35"), plan=PLAN).state()
    assert "last 07:10" in s["band"]


def test_timetable_train_is_marked_and_live_train_wins(open_board):
    s = open_board(BASE, t("06:58"), plan=PLAN).state()
    rows = {r["time"]: r for r in s["rows"]}
    assert "Timetable" in rows["07:03"]["note"]
    assert s["band"].startswith("Last on-time train: 07:10") or s["band"].startswith("On time for work")
    live = open_board(BASE, t("06:50"), plan=PLAN).state()
    rows = {r["time"]: r for r in live["rows"]}
    assert "Timetable" not in rows["06:55"]["note"]           # 06:55 is in both: the live one is shown


def test_planner_down_changes_nothing(open_board):
    a = open_board(BASE, t("06:35")).state()
    b = open_board(BASE, t("06:35"), plan={"journeys": []}).state()
    assert a["band"] == b["band"] and times(a) == times(b)
