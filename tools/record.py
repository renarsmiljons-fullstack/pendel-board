"""Records real responses from SL's departures API into fixtures/recorded/.

Run by .github/workflows/record.yml on weekday mornings. Saves:
  * Kallhäll at a few fixed moments each morning (routine fixtures, kept 30 days)
  * any station response with something unusual in it, such as a cancellation,
    a message, an unreliable prediction or a station notice (kept for good)
  * the Open-Meteo forecast for Kallhäll with each routine snapshot (kept with it)

Usage: python tools/record.py [--minutes 150] [--every 10]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://transport.integration.sl.se/v1"
WEATHER_PATH = ("/v1/forecast?latitude=59.4535&longitude=17.8058&minutely_15=precipitation,snowfall,temperature_2m,weather_code"
                "&timezone=Europe%2FStockholm&forecast_days=2&models=metno_seamless")
OUT = Path(__file__).resolve().parent.parent / "fixtures" / "recorded"
STOCKHOLM = ZoneInfo("Europe/Stockholm")
KALLHALL = 9701
ROUTINE_TIMES = {"06:30", "06:50", "07:05"}   # Kallhäll snapshots kept each weekday morning
KEEP_ROUTINE_DAYS = 30

# Commuter rail stations scanned for unusual responses (site ids from /v1/sites)
STATIONS = {
    9701: "kallhall", 9702: "jakobsberg", 9704: "spanga", 9325: "sundbyberg", 1080: "stockholm-city",
    1079: "odenplan", 9530: "stockholms-sodra", 9529: "alvsjo", 9527: "huddinge", 9524: "tumba",
    9520: "sodertalje-c", 9521: "sodertalje-hamn", 9728: "vasterhaninge", 9720: "nynashamn",
    9500: "marsta", 9502: "upplands-vasby",
}
USUAL_STATES = {"EXPECTED", "ATSTOP"}
USUAL_JOURNEYS = {"EXPECTED", "NORMALPROGRESS"}


def fetch(site_id: int) -> dict:
    url = f"{API}/sites/{site_id}/departures?transport=TRAIN&forecast=120"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def fetch_weather() -> dict:
    with urllib.request.urlopen("https://api.open-meteo.com" + WEATHER_PATH, timeout=20) as r:
        return json.load(r)


def save_weather(resp: dict) -> Path:
    now = datetime.now(timezone.utc)
    local = now.astimezone(STOCKHOLM)
    folder = OUT / local.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{local:%H%M}_kallhall_routine_weather.json"
    body = {"recorded_at": now.isoformat().replace("+00:00", "Z"), "place": "Kallhäll", "url": WEATHER_PATH, "response": resp}
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def unusual(resp: dict) -> list[str]:
    reasons = []
    if resp.get("stop_deviations"):
        reasons.append("station-notice")
    for d in resp.get("departures", []):
        j = d.get("journey") or {}
        if d.get("state") not in USUAL_STATES:
            reasons.append(f"state-{d.get('state')}")
        if j.get("state") not in USUAL_JOURNEYS:
            reasons.append(f"journey-{j.get('state')}")
        if j.get("prediction_state") not in (None, "NORMAL"):
            reasons.append(f"prediction-{j.get('prediction_state')}")
        if d.get("deviations"):
            reasons.append("message")
        if not d.get("expected"):
            reasons.append("no-expected")
        if d.get("expected") and d.get("scheduled") and d["expected"] != d["scheduled"]:
            reasons.append("delay")
    return sorted(set(reasons))


def save(resp: dict, site_id: int, name: str, kind: str, reasons: list[str]) -> Path | None:
    now = datetime.now(timezone.utc)
    local = now.astimezone(STOCKHOLM)
    body = {"recorded_at": now.isoformat().replace("+00:00", "Z"), "site_id": site_id, "site": name,
            "url": f"/v1/sites/{site_id}/departures?transport=TRAIN&forecast=120",
            "kind": kind, "reasons": reasons, "response": resp}
    # Skip a response identical to one already saved today (ignoring the "display" countdown text)
    digest = hashlib.sha1(json.dumps([{k: v for k, v in d.items() if k != "display"} for d in resp.get("departures", [])],
                                     sort_keys=True).encode()).hexdigest()[:10]
    folder = OUT / local.strftime("%Y-%m-%d")
    if any(digest in p.name for p in folder.glob("*.json")):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{local:%H%M}_{name}_{kind}_{digest}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def prune() -> None:
    """Delete routine snapshots older than KEEP_ROUTINE_DAYS. Unusual ones are kept."""
    cutoff = datetime.now(STOCKHOLM).date() - timedelta(days=KEEP_ROUTINE_DAYS)
    for folder in OUT.glob("20??-??-??"):
        if datetime.strptime(folder.name, "%Y-%m-%d").date() < cutoff:
            for p in folder.glob("*_routine_*.json"):
                p.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()


def round_once(saved: set[str]) -> None:
    local = datetime.now(STOCKHOLM)
    for site_id, name in STATIONS.items():
        try:
            resp = fetch(site_id)
        except Exception as e:  # one failing station must not stop the recording
            print(f"{name}: {e}")
            continue
        reasons = unusual(resp)
        path = None
        if reasons:
            path = save(resp, site_id, name, "unusual", reasons)
        elif site_id == KALLHALL and local.strftime("%H:%M") >= min(ROUTINE_TIMES):
            slot = max((t for t in ROUTINE_TIMES if t <= local.strftime("%H:%M")), default=None)
            if slot and slot not in saved:
                saved.add(slot)
                path = save(resp, site_id, name, "routine", [])
                try:
                    print(f"saved {save_weather(fetch_weather()).relative_to(OUT)}")
                except Exception as e:  # the weather service failing must not stop the recording
                    print(f"weather: {e}")
        if path:
            print(f"saved {path.relative_to(OUT)} {reasons}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=150, help="how long to keep recording")
    ap.add_argument("--every", type=int, default=10, help="minutes between rounds")
    args = ap.parse_args()
    prune()
    saved: set[str] = set()
    end = time.time() + args.minutes * 60
    while True:
        round_once(saved)
        if time.time() + args.every * 60 > end:
            break
        time.sleep(args.every * 60)


if __name__ == "__main__":
    main()
