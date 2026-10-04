"""Real weather for the four weather zones, from Open-Meteo (free, no API key).

What is real and what is not:
  * Real: daily snowfall, mean temperature and peak wind at each zone, as observed (ERA5 reanalysis, then the
    forecast model's recent days) and as forecast for the next 14 days. Temperature is downscaled to the zone's
    own altitude by the service.
  * Not real: the sector, its posts and roads are fictional, and the road closures the model learns from are still
    generated from the weather by a hidden snow rule (no public closure record exists for these roads).

Modes (set RASAD_REAL_DATA before the first start or before POST /api/reset):
  * `live`   (or `1`): the real weather up to today and the real 14-day forecast.
  * `replay`: real observed weather from a past winter, replayed as if it were today. Day 0 is 2026-03-08, four
              days before a real snowfall peak on the passes, so the forecast week contains a real storm. Use
              `replay:YYYY-MM-DD` for another day. The "forecast" is then the weather that actually fell.
The download is cached in backend/data/weather_real.json, so later runs work offline. If the download fails the seed
falls back to the synthetic weather and says so in /api/health.
"""
import json
import os
from datetime import date, timedelta

import requests

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "weather_real.json")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
DAILY = "temperature_2m_mean,snowfall_sum,wind_speed_10m_max"
PAST, AHEAD, FORECAST_PAST = 120, 14, 7        # recent days come from the forecast service, older ones from the ERA5 archive
LAST_ARCHIVED_AGO = FORECAST_PAST + 1


REPLAY_DEFAULT = date(2026, 3, 8)


def mode():
    """(kind, anchor): ('live', None), ('replay', date) or (None, None) when real data is off."""
    v = os.environ.get("RASAD_REAL_DATA", "").strip().lower()
    if v.startswith("replay"):
        return "replay", (date.fromisoformat(v.split(":", 1)[1]) if ":" in v else REPLAY_DEFAULT)
    return ("live", None) if v in ("1", "true", "yes", "live") else (None, None)


def enabled():
    return mode()[0] is not None


def _get(url, **params):
    r = requests.get(url, params={"daily": DAILY, "timezone": "Asia/Kolkata", **params}, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    return {day: (s, t, w) for day, t, s, w in zip(d["time"], d["temperature_2m_mean"], d["snowfall_sum"], d["wind_speed_10m_max"])}


def fetch_zone(lat, lon, alt_m, anchor, replay=False):
    """{iso day: (snow_cm, temp_c, wind_kmh)} for anchor-PAST .. anchor+AHEAD-1."""
    where = {"latitude": round(lat, 4), "longitude": round(lon, 4), "elevation": alt_m}
    lo, hi = anchor - timedelta(days=PAST), anchor + timedelta(days=AHEAD - 1)
    if replay:      # everything has already happened, so the archive has it all
        return _get(ARCHIVE, **where, start_date=lo.isoformat(), end_date=hi.isoformat())
    days = _get(ARCHIVE, **where, start_date=lo.isoformat(), end_date=(anchor - timedelta(days=LAST_ARCHIVED_AGO)).isoformat())
    days.update(_get(FORECAST, **where, past_days=FORECAST_PAST, forecast_days=AHEAD))
    return days


def _complete(days, anchor):
    need = [(anchor + timedelta(days=d)).isoformat() for d in range(-PAST, AHEAD)]
    return all(d in days and None not in days[d] for d in need)


def zone_points(roads, road_zone, lonlat):
    """Centre of each zone: the mean position of the road points in it, as {zone: (lat, lon)}."""
    pts = {}
    for rid, *_r, line in roads:
        for p in line:
            lon, lat = lonlat(*p)
            pts.setdefault(road_zone[rid], []).append((lat, lon))
    return {z: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for z, v in pts.items()}


def weather(points, altitudes, today=None):
    """({(zone, day_offset): (snow, temp, wind)}, label) for offsets -PAST..AHEAD-1, or None if real data is unavailable."""
    kind, anchor = mode()
    replay = kind == "replay"
    anchor = anchor or today or date.today()
    key = f"{kind}:{anchor.isoformat()}"
    cache = None
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        pass
    zones = (cache or {}).get("zones", {}) if (cache or {}).get("key") == key else {}
    if not all(z in zones and _complete({k: tuple(v) for k, v in zones[z]["days"].items()}, anchor) for z in points):
        try:
            zones = {z: {"lat": lat, "lon": lon, "alt_m": altitudes[z], "days": fetch_zone(lat, lon, altitudes[z], anchor, replay)} for z, (lat, lon) in points.items()}
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"[rasad] real weather unavailable ({type(e).__name__}); using synthetic weather")
            return None
        if not all(_complete(z["days"], anchor) for z in zones.values()):
            print("[rasad] real weather incomplete; using synthetic weather")
            return None
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"key": key, "fetched": date.today().isoformat(), "source": "Open-Meteo (ERA5 archive + forecast)", "zones": zones}, f, separators=(",", ":"))
    out = {(z, d): tuple(info["days"][(anchor + timedelta(days=d)).isoformat()]) for z, info in zones.items() for d in range(-PAST, AHEAD)}
    label = (f"Open-Meteo: real weather replayed from {(anchor - timedelta(days=PAST)).isoformat()} to {(anchor + timedelta(days=AHEAD - 1)).isoformat()}"
             if replay else "Open-Meteo: real observed and forecast weather")
    return out, label


if __name__ == "__main__":     # python realdata.py  -> refresh the cache now
    import seed
    pts = zone_points(seed.ROADS, seed.ROAD_ZONE, seed.lonlat)
    w = weather(pts, seed.ZONES)
    print(w[1] if w else "failed", {z: tuple(round(x, 4) for x in p) for z, p in pts.items()})
