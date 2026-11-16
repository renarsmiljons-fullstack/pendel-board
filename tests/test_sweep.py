"""Sweep tests: step the clock minute by minute through real recorded responses
and check every rule the board must keep, in both orientations.

Each recorded fixture is swept from the moment it was recorded. The real
Kallhäll morning recording is also shifted in time (all other fields kept),
so the sweep covers the whole 06:00-07:30 window, including the 07:10 cutoff.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from conftest import BASE_MORNING, ORIENTATIONS, RECORDED, load_fixture, recorded_local_time, shifted
from reference import at, expected_view, is_morning, minutes_shown



def hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def sweep_cases():
    """(id, response, start, minutes to sweep)"""
    cases = []
    for path in RECORDED:
        fx = load_fixture(path)
        start = recorded_local_time(fx)
        cases.append((path.split("/")[-1], fx["response"], start, 75))
    # The real morning, shifted so the sweep crosses every part of the morning window
    base = load_fixture(BASE_MORNING)
    rec = recorded_local_time(base)
    for shift in (-60, -45, -30, -15):
        cases.append((f"kallhall_shift{shift}", shifted(base["response"], shift), rec + timedelta(minutes=shift - 20), 100))
    return cases


CASES = sweep_cases()


def check(state: dict, response: dict, now: datetime, errors: list[str]) -> list[str]:
    """Every rule the board must keep at this moment. Returns the broken ones."""
    bad = []
    ref = expected_view(response, now)
    if errors:
        bad.append(f"page errors: {errors}")
    if state["pageOverflowX"] or state["pageOverflowY"]:
        bad.append("page content overflows the screen")
    if state["listClipped"]:
        bad.append("departures list is clipped")

    live_times = {hhmm(t.expected) for t in ref["live"]}
    for r in state["rows"]:
        if r["time"] not in live_times:
            bad.append(f"row {r['time']} is not a live city-bound train")
        if not r["cancelled"]:
            t = next(t for t in ref["live"] if hhmm(t.expected) == r["time"])
            want = minutes_shown(now, t.expected) + " min"
            if r["min"].replace("≈", "") != want:
                bad.append(f"row {r['time']} shows {r['min']!r}, expected {want!r}")

    if not ref["catchable"]:
        if state["mode"] != "empty":
            bad.append(f"no catchable train, but mode is {state['mode']!r}")
        return bad

    f = ref["featured"]
    if state["mode"] != ref["mode"]:
        bad.append(f"mode {state['mode']!r}, expected {ref['mode']!r}")
    if state["train"] != hhmm(f.expected):
        bad.append(f"featured {state['train']}, expected {hhmm(f.expected)}")
    if state["left"] != ref["left"]:
        bad.append(f"train-leaves-in {state['left']}, expected {ref['left']}")
    if ref["mode"] == "leave" and state["big"] != ref["big"]:
        bad.append(f"leave-in {state['big']}, expected {ref['big']}")
    if state["pace"] != ref["pace"]:
        bad.append(f"pace {state['pace']!r}, expected {ref['pace']!r}")
    mine = [r for r in state["rows"] if r["mine"]]
    if len(mine) != 1 or mine[0]["time"] != state["train"]:
        bad.append(f"your train {state['train']} is not exactly once in the list: {[r['time'] for r in mine]}")
    if any(r["cancelled"] and r["mine"] for r in state["rows"]):
        bad.append("a cancelled train is featured")

    if ref["morning"]:
        m = re.search(r"last (\d\d:\d\d)", state["band"])
        if m and m.group(1) not in {r["time"] for r in state["rows"]}:
            bad.append(f"band names the {m.group(1)} train, but the list doesn't show it")
        if "Last on-time train" in state["band"]:
            t = re.search(r"Last on-time train: (\d\d:\d\d)", state["band"]).group(1)
            if t not in {r["time"] for r in state["rows"]}:
                bad.append(f"band's last on-time train {t} is not in the list")
    if "Track change" in state["heroText"] + " ".join(r["note"] for r in state["rows"]):
        bad.append("shows a track change that no SL message reported")
    return bad


@pytest.mark.parametrize("orientation", list(ORIENTATIONS))
@pytest.mark.parametrize("case_id,response,start,span", CASES, ids=[c[0] for c in CASES])
def test_sweep(open_board, case_id, response, start, span, orientation):
    board = open_board(response, start, orientation)
    failures = []
    for minute in range(span):
        for second in (0, 31):   # on the minute and mid-minute, to catch rounding
            now = start.replace(second=0) + timedelta(minutes=minute, seconds=second)
            board.set_time(now)
            for problem in check(board.state(), response, now, board.errors):
                failures.append(f"{now:%a %H:%M:%S}: {problem}")
    assert not failures, f"{len(failures)} problems, first 15:\n" + "\n".join(failures[:15])
