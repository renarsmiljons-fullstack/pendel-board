# Kallhäll → Odenplan departure board

A departure board for a 7-inch screen by the front door, running on a Raspberry Pi. It shows when to leave the apartment for the next city-bound commuter train from Kallhäll, how fast to walk, and whether you are still on time for work. Train times come live from SL's [Transport API](https://www.trafiklab.se/api/other-apis/sl/transport/), which needs no API key.

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

After the reboot, the board opens full screen. To check that the parts are running:

```bash
systemctl --user status pendel-web            # local web server
systemctl --user list-timers pendel-update    # next update check
journalctl --user -u pendel-update -n 20      # recent updates
```

The web server listens on `127.0.0.1:8080` only, so no other device on your network can reach it. The Pi makes outgoing requests to SL and GitHub and accepts no incoming connections.

## How changes reach the Pi

1. A commit lands on `main`.
2. The `CI` workflow runs every test. If all tests pass, it moves the `stable` branch to that commit.
3. Every 10 minutes, `pi/update.sh` checks `stable`. When `stable` has moved, the script pulls it and writes the new commit to `web/version.txt`.
4. The open page reads `web/version.txt` every 5 minutes and reloads when it changes.

A commit that fails any test never reaches `stable`, so it never reaches the screen.

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
| `tests/test_scenarios.py` | One test per situation: every departure state in SL's spec, delays, cancellations, replacement buses, skipped stops, station notices, feed errors, old data, sleep, and weekends. |

## Fixtures

Fixtures are real responses from `GET /v1/sites/{siteId}/departures?transport=TRAIN&forecast=120`, saved with the time they were recorded.

- `fixtures/recorded/2026-11-16T0706_kallhall.json` is a weekday morning at Kallhäll. The scenario tests start from this file and change only the fields each scenario is about.
- `fixtures/recorded/<date>/` holds responses saved by the `Record SL responses` workflow. It runs on weekday mornings and saves three Kallhäll snapshots, plus any response from 16 commuter rail stations that contains something unusual: a cancellation, a message, a delay, an unreliable prediction, or a station notice. It deletes routine snapshots after 30 days and keeps unusual ones.

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
| `walkMinutes` | `7` | Walk from the apartment to the platform at a normal pace. |
| `platformBufferMinutes` | `0.5` | Extra time to reach the platform and board. |
| `deadline` | `"07:10"` | Last departure that reaches work on time. |
| `deadlineDays` | `[1, 2, 3, 4, 5]` | Days the deadline applies, Monday to Friday. |
| `morningWindow` | `["06:15", "07:15"]` | When the work status band is active. |
| `awake` | weekdays `06:15`–`07:15` | When the screen shows the board. At other times it is black until tapped. |
| `wakeMinutes` | `5` | How long a tap keeps the screen on. |
| `refreshSeconds` | `30` | How often the board asks SL for new times. |
| `staleSeconds` | `90` | Data older than this is marked as possibly wrong. |
| `maxRows` | `4` | Most departures listed. |

## Test parameters

Add these to the page address to check a situation by eye, for example `index.html?at=2026-11-16T06:40:00&nosleep`.

| Parameter | Effect |
| --- | --- |
| `at=YYYY-MM-DDTHH:MM:SS` | Freezes the clock at this Stockholm time. |
| `now=HH:MM` | Starts the clock at this time today. The clock keeps running. |
| `day=N` | Treats today as weekday `N`, where `0` is Sunday. |
| `nosleep` | Keeps the screen awake at all hours. |
| `stale=N` | Pretends the last good data is `N` minutes old and SL is failing. |
