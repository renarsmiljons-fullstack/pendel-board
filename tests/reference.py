"""Independent reference for what the board should show.

Written separately from web/index.html so that the tests check the board
against a second implementation of the same rules, not against itself.
All times are Stockholm wall-clock times as naive datetimes, like the SL API.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

WALK_MIN = 7
BUFFER_MIN = 0.5
DEADLINE = "07:10"
MORNING = ("06:15", "07:15")
WEEKDAYS = {0, 1, 2, 3, 4}          # Python: Monday = 0
CITY_BOUND = 1
SLIPPERY_EXTRA = 2              # minutes added to the walk in snow or freezing rain

GONE_STATES = {"DEPARTED", "PASSED", "MISSED", "ASSUMEDDEPARTED", "NOTEXPECTED", "NOTCALLED", "BOARDINGCLOSED"}
CANCELLED_STATES = {"CANCELLED", "INHIBITED", "REPLACED"}
GONE_JOURNEYS = {"NOTEXPECTED", "NOTRUN", "ABORTED", "COMPLETED", "ASSUMEDFINISHED"}

# Pace levels: (minimum ratio of usable minutes to walk minutes, level, name)
PACES = [(1.6, 1, "Easy walk"), (1.0, 2, "Walk"), (0.82, 3, "Fast walk"),
         (0.6, 4, "Jog"), (0.42, 5, "Run"), (0.3, 6, "Usain Bolt")]


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def at(day: datetime, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def pace_level(minutes_left: float, extra: float = 0) -> int:
    ratio = (minutes_left - BUFFER_MIN) / (WALK_MIN + extra)
    for threshold, level, _ in PACES:
        if ratio >= threshold:
            return level
    return 0  # too late


def pace_name(level: int) -> str:
    return next(name for _, lv, name in PACES if lv == level)


def minutes_shown(now: datetime, when: datetime) -> str:
    """Minutes as the board shows them: counted from the start of the displayed clock minute."""
    start = now.replace(second=0, microsecond=0)
    v = (when - start).total_seconds() / 60
    return "<1" if v < 1 else str(math.floor(v))


@dataclass
class Train:
    expected: datetime
    scheduled: datetime
    cancelled: bool


def trains(response: dict) -> list[Train]:
    out = []
    for d in response.get("departures", []):
        if d.get("direction_code") != CITY_BOUND or not d.get("scheduled"):
            continue
        if d.get("state") in GONE_STATES or (d.get("journey") or {}).get("state") in GONE_JOURNEYS:
            continue
        cancelled = d.get("state") in CANCELLED_STATES or (d.get("journey") or {}).get("state") == "CANCELLED"
        out.append(Train(parse(d.get("expected") or d["scheduled"]), parse(d["scheduled"]), cancelled))
    return sorted(out, key=lambda t: t.expected)


def walk_weather(weather: dict | None, departure: datetime) -> str | None:
    """'ice', 'snow', 'rain' or 'dry' on the walk to a departure; None when no forecast covers it.

    The walk is the 15-minute forecast slots that overlap the
    WALK_MIN + BUFFER_MIN + SLIPPERY_EXTRA minutes before the departure.
    """
    if not weather:
        return None
    m = weather["minutely_15"]
    start_walk = departure - timedelta(minutes=WALK_MIN + BUFFER_MIN + SLIPPERY_EXTRA)
    found = []
    for i, t in enumerate(m["time"]):
        a = datetime.fromisoformat(t)
        if a < departure and a + timedelta(minutes=15) > start_walk:
            found.append(i)
    if not found:
        return None
    codes = [m["weather_code"][i] for i in found]
    if any(c in (56, 57, 66, 67) for c in codes):
        return "ice"
    if any(71 <= c <= 77 or c in (85, 86) for c in codes) or any(m["snowfall"][i] > 0 for i in found):
        return "snow"
    if any(51 <= c <= 67 or 80 <= c <= 82 or c >= 95 for c in codes) or any(m["precipitation"][i] >= 0.1 for i in found):
        return "rain"
    return "dry"


def extra_minutes(weather: dict | None, departure: datetime) -> int:
    return SLIPPERY_EXTRA if walk_weather(weather, departure) in ("ice", "snow") else 0


def is_morning(now: datetime) -> bool:
    return now.weekday() in WEEKDAYS and at(now, MORNING[0]) <= now <= at(now, MORNING[1])


def minutes(now: datetime, when: datetime) -> float:
    return (when - now).total_seconds() / 60


def expected_view(response: dict, now: datetime, weather: dict | None = None) -> dict:
    """What the top card should feature at `now`."""
    live = [t for t in trains(response) if minutes(now, t.expected) > -0.5]

    def level(t: Train) -> int:
        return pace_level(minutes(now, t.expected), extra_minutes(weather, t.expected))

    catchable = [t for t in live if not t.cancelled and level(t) > 0]
    if not catchable:
        return {"mode": "empty" if not live else "empty-or-none", "catchable": [], "live": live}
    deadline = at(now, DEADLINE)
    morning = is_morning(now)
    ontime = [t for t in catchable if t.expected <= deadline]
    if morning and ontime:
        pool = ontime
    else:
        first = catchable[0].expected
        pool = [t for t in catchable if (t.expected - first) <= timedelta(minutes=15)]

    def effort(t: Train) -> int:
        return max(2, level(t))

    featured = min(pool, key=lambda t: (effort(t), t.expected))
    left = minutes(now, featured.expected)
    extra = extra_minutes(weather, featured.expected)
    leave_in = left - WALK_MIN - extra - BUFFER_MIN
    mode = "leave" if leave_in >= 1 else "go"
    return {
        "mode": mode,
        "featured": featured,
        "left": minutes_shown(now, featured.expected),
        "big": minutes_shown(now, featured.expected - timedelta(minutes=WALK_MIN + extra + BUFFER_MIN)) if mode == "leave" else "",
        "pace": "Walk" if mode == "leave" else pace_name(level(featured)),
        "weather": walk_weather(weather, featured.expected),
        "catchable": catchable,
        "live": live,
        "morning": morning,
    }
