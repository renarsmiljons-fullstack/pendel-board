# Kallhäll → Odenplan departure board

A departure board for a 7-inch screen by the front door, running on a Raspberry Pi. It shows when to leave the apartment for the next city-bound commuter train from Kallhäll, how fast to walk, and whether you are still on time for work. Train times come live from SL's [Transport API](https://www.trafiklab.se/api/other-apis/sl/transport/), with gaps filled from SL's journey planner, and weather from [Open-Meteo](https://open-meteo.com/). None of them needs an API key.

The whole board is one file: `web/index.html`.

## Set up the Raspberry Pi

You need Raspberry Pi OS with the desktop, connected to Wi-Fi, and the touchscreen attached.

1. Open a terminal on the Pi as your normal user.
2. Run the setup script:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/renarsmiljons-fullstack/pendel-board/stable/pi/setup.sh | bash
   ```

3. Reboot:

   ```bash
   sudo reboot
   ```

After the reboot, the board opens full screen. If Chromium exits or crashes, the `pendel-kiosk` service starts it again within 5 seconds. To check that the parts are running:

```bash
systemctl --user status pendel-kiosk          # full-screen board
systemctl --user status pendel-web            # local web server and screen power
systemctl --user status pendel-listen         # updates from GitHub
systemctl --user list-timers pendel-update    # next backup check
journalctl --user -u pendel-listen -n 20      # recent updates
```

The web server listens on `127.0.0.1:8080` only, so no other device on your network can reach it. The Pi makes outgoing requests to SL, Open-Meteo, and GitHub, and accepts no incoming connections.

## The screen at night

Outside the awake hours (weekdays 06:15–07:15), the board turns the HDMI signal off. Without a signal, the 7-inch panel turns its backlight off too, so the screen is fully dark instead of glowing black.

Tap the screen to wake it for 5 minutes. With the signal off, the tap may not reach the browser, so the web server (`pi/server.py`) reads the touchscreen itself. It turns the signal back on, and the page wakes when it next asks the server, within 2 seconds.

If the page stops asking for 60 seconds, for example while Chromium restarts, the server turns the signal back on, so the screen never stays dark by mistake.

While the screen is off, the Pi sends no requests to SL, Open-Meteo, or GitHub. Waking the screen fetches train times, the timetable, and weather at once, and the board refreshes as usual while it stays on.

## Trains missing from SL's live feed

SL's live feed sometimes leaves out trains 20 to 60 minutes ahead. On the morning of 17 November 2026, at 06:34, it listed the 06:40 and the 06:48, then nothing until 07:48, although trains left at 06:55, 07:03, and 07:10. The board then called the 06:48 your last on-time train.

The board therefore also asks SL's [journey planner](https://www.trafiklab.se/api/other-apis/sl/journey-planner-2/) (no API key) for the timetable from Kallhäll to Odenplan, an hour ahead, every 5 minutes. It adds the trains that the live feed doesn't list yet and marks them **Timetable · not live yet**. When a train is in both, the live one is shown. If the planner doesn't answer, or its last answer is more than 30 minutes old, the board uses the live feed alone.

A timetable train has no live data: if SL cancels it before it reaches the live feed, the board doesn't know.

## Weather

The board asks Open-Meteo for the Kallhäll forecast every 10 minutes, in 15-minute steps. For each departure it looks at the forecast for the walk to it: the 15-minute steps that overlap the 10.5 minutes before the train leaves.

| Weather on the walk | What the board does |
| --- | --- |
| Rain or drizzle | Shows **RAIN · Take an umbrella**. The leave time does not change. |
| Snow | Adds 2 minutes to the walk. The leave time moves earlier, and the pace for that train goes up. |
| Freezing rain | Same as snow, labelled **ICY**. |

The header shows the temperature and the weather right now, after the route name. If Open-Meteo does not answer, or its last answer is more than 3 hours old, the board ignores weather and works as before.

## How changes reach the Pi

1. A commit lands on `main`.
2. The `CI` workflow runs every test. If all tests pass, it moves the `stable` branch to that commit.
3. While the screen is on, `pi/listen.sh` on the Pi asks GitHub every 30 seconds which commit `stable` points to. It uses `git ls-remote`, which is one small request and needs no account or secret.
4. When that commit is new, `pi/update.sh` pulls `stable` and writes the commit to `web/version.txt`. If `pi/server.py` or `pi/listen.sh` changed, it also restarts their services.
5. The open page reads `web/version.txt` every 30 seconds and reloads when it changes.

A merge reaches the screen about 3 minutes later, most of it CI. A commit that fails any test never reaches `stable`, so it never reaches the screen.

As a backup, `pendel-update.timer` also runs `pi/update.sh` every 10 minutes while the screen is on. To update while the screen is off, run `FORCE=1 bash ~/pendel-board/pi/update.sh ~/pendel-board`.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
```

The suite opens `web/index.html` in headless Chromium, serves it recorded SL responses, and sets the clock to fixed times.

| File | What it checks |
| --- | --- |
| `tests/test_sweep.py` | Steps through each recorded response minute by minute, on the minute and at 31 seconds past, in portrait and landscape. At each step it compares the board with `tests/reference.py`, a separate implementation of the rules. |
| `tests/test_feed.py` | Odd answers from SL: an empty answer while trains are still due keeps the last real times and says so in the footer, and timetable trains fill gaps in the live feed. Also checks that the morning list shows only on-time trains, and that an asleep board sends no requests until a tap wakes it. |
| `tests/test_server.py` | The Pi's web server: it serves the board, switches the HDMI signal when the page asks, turns it back on after a tap, and turns it on if the page goes quiet. |
| `tests/test_scenarios.py` | One test per situation: every departure state in SL's spec, delays, cancellations, replacement buses, skipped stops, station notices, feed errors, old data, sleep, weekends, and each kind of weather. |

## Fixtures

Fixtures are real responses from SL (`GET /v1/sites/{siteId}/departures?transport=TRAIN&forecast=120`) and from Open-Meteo, saved with the time they were recorded.

- `fixtures/recorded/2026-11-16T0706_kallhall.json` is a weekday morning at Kallhäll. The scenario tests start from this file and change only the fields each scenario is about.
- `fixtures/recorded/<date>/` holds responses saved by the `Record SL responses` workflow. It runs on weekday mornings and saves three Kallhäll snapshots, plus any response from 16 commuter rail stations that contains something unusual: a cancellation, a message, a delay, an unreliable prediction, or a station notice. It deletes routine snapshots after 30 days and keeps unusual ones.
- `fixtures/weather/` holds real Open-Meteo responses from the morning of 16 November 2026: dry in Kallhäll, rain in Bergen, drizzle in Gothenburg, and snow in Kiruna. The weather tests pair them with the Kallhäll train recording. Each file keeps the 15-minute steps from 05:00 to 09:45.
- `fixtures/plan/` holds real answers from SL's journey planner for the morning of 18 November, trimmed to the fields the board reads. The timetable tests move them to the test Monday.
- The recording workflow also saves the Kallhäll forecast with each routine snapshot, as `<time>_kallhall_routine_weather.json`. The sweep tests use it with the train recordings from the same morning.

The recording workflow runs the full test suite against everything it saved. If real data breaks a rule, the workflow fails and GitHub emails the repository owner.

To record by hand:

```bash
python tools/record.py --minutes 1 --every 1
```

## Settings

Settings are the `CONFIG` object at the top of the script in `web/index.html`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `siteId` | `9701` | SL site to show (Kallhäll). |
| `directionCode` | `1` | Direction to show. `1` is toward Stockholm City and Odenplan. |
| `walkMinutes` | `8` | Walk from the apartment to the platform at a normal pace. |
| `platformBufferMinutes` | `0.5` | Extra time to reach the platform and board. |
| `deadline` | `"07:10"` | Last departure that reaches work on time. |
| `deadlineDays` | `[1, 2, 3, 4, 5]` | Days the deadline applies, Monday to Friday. |
| `morningWindow` | `["06:15", "07:15"]` | When the work status band is active. |
| `awake` | weekdays `06:15`–`07:15` | When the screen shows the board. At other times the screen is off until tapped. |
| `wakeMinutes` | `5` | How long a tap keeps the screen on. |
| `refreshSeconds` | `30` | How often the board asks SL for new times. |
| `staleSeconds` | `90` | Data older than this is marked as possibly wrong. |
| `maxRows` | `4` | Most departures listed. |
| `weather.lat`, `weather.lon` | Kallhäll | Where the forecast is for. |
| `weather.slipperyExtraMinutes` | `2` | Minutes added to the walk in snow or freezing rain. |
| `weather.maxAgeMinutes` | `180` | Forecasts older than this are ignored. |

## Test parameters

Add these to the page address to check a situation by eye, for example `index.html?at=2026-11-16T06:40:00&nosleep`.

| Parameter | Effect |
| --- | --- |
| `at=YYYY-MM-DDTHH:MM:SS` | Freezes the clock at this Stockholm time. |
| `now=HH:MM` | Starts the clock at this time today. The clock keeps running. |
| `day=N` | Treats today as weekday `N`, where `0` is Sunday. |
| `nosleep` | Keeps the screen awake at all hours. |
| `stale=N` | Pretends the last good data is `N` minutes old and SL is failing. |
