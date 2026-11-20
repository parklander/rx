"""Burn-day forecast: fetch hourly weather at the unit and check it against the prescription
and the ignition variants (by wind direction)."""
import os
from datetime import date

import httpx

SOURCE = "Open-Meteo gem_seamless (HRDPS/RDPS/GDPS)"
TZ = os.environ.get("RX_TZ", "America/Winnipeg")
HOURLY_MAP = {"temperature_2m": "temp_c", "relative_humidity_2m": "rh_pct", "wind_speed_10m": "wind_kmh",
              "wind_direction_10m": "wind_dir_deg", "wind_gusts_10m": "gust_kmh", "precipitation": "precip_mm"}
WEATHER_PARAMS = {"temp_c", "rh_pct", "wind_kmh", "gust_kmh", "precip_mm"}
IGNITION_HOURS = (11, 17)  # ignition period, local time, inclusive start / exclusive end


def fetch_hourly(lat, lon, day):
    d = day.isoformat() if isinstance(day, date) else str(day)
    r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
        "latitude": lat, "longitude": lon, "models": "gem_seamless", "timezone": TZ,
        "hourly": ",".join(HOURLY_MAP), "start_date": d, "end_date": d, "wind_speed_unit": "kmh"})
    r.raise_for_status()
    h = r.json()["hourly"]
    out = []
    for i, t in enumerate(h["time"]):
        row = {"time": t}
        for k, name in HOURLY_MAP.items():
            row[name] = h[k][i]
        out.append(row)
    return out


def _in_sector(d, lo, hi):
    if d is None:
        return False
    d, lo, hi = d % 360, lo % 360, hi % 360
    return lo <= d <= hi if lo <= hi else (d >= lo or d <= hi)


def evaluate(hourly, params, variants):
    """Each hour from 06:00 to 21:00: GO when every weather limit that the forecast carries is met
    and the wind direction falls in an approved variant. Indices (FFMC, ISI, BUI...) are not in
    the forecast and are listed as unchecked."""
    limits = {p["param"]: (p["low"], p["high"]) for p in params}
    unchecked = sorted(k for k in limits if k not in WEATHER_PARAMS)
    hours = []
    for h in hourly:
        hr = int(str(h["time"])[11:13])
        if hr < 6 or hr > 21:
            continue
        fails = []
        for k, (lo, hi) in limits.items():
            if k not in WEATHER_PARAMS or h.get(k) is None:
                continue
            v = float(h[k])
            if lo is not None and v < float(lo):
                fails.append(f"{k} {v:g} < {float(lo):g}")
            if hi is not None and v > float(hi):
                fails.append(f"{k} {v:g} > {float(hi):g}")
        match = [v for v in variants if _in_sector(h.get("wind_dir_deg"), float(v["wind_dir_min"]), float(v["wind_dir_max"]))]
        if variants and not match:
            fails.append(f"wind from {h.get('wind_dir_deg')}° matches no approved variant")
        hours.append({**h, "hour": hr, "ok": not fails, "fails": fails,
                      "variant_ids": [v["id"] for v in match], "variant": match[0]["name"] if match else None,
                      "ignition_period": IGNITION_HOURS[0] <= hr < IGNITION_HOURS[1]})
    ign = [h for h in hours if h["ignition_period"]]
    weather_ok = lambda h: not [f for f in h["fails"] if "variant" not in f]
    # One variant has to hold for the whole ignition period: pick the one that covers the most hours.
    cover = {v["id"]: sum(1 for h in ign if weather_ok(h) and v["id"] in h["variant_ids"]) for v in variants}
    best = max(cover, key=cover.get) if cover and max(cover.values()) > 0 else None
    best_name = next((v["name"] for v in variants if v["id"] == best), None)
    for h in hours:
        h["ok_for_variant"] = weather_ok(h) and (best is None and not variants or best in h["variant_ids"])
    go = [h for h in ign if h["ok_for_variant"]]
    shifts = [h["hour"] for h in ign if weather_ok(h) and best is not None and best not in h["variant_ids"]]
    windows, start = [], None
    for h in hours + [{"ok_for_variant": False, "hour": 22}]:
        if h["ok_for_variant"] and start is None:
            start = h["hour"]
        if not h["ok_for_variant"] and start is not None:
            windows.append(f"{start:02d}:00–{h['hour']:02d}:00")
            start = None
    if not ign:
        verdict = "no forecast for the ignition period"
    elif len(go) == len(ign):
        verdict = f"GO through the ignition period on the {best_name} variant" if best_name else "GO through the ignition period"
    elif go:
        verdict = f"PARTIAL: {len(go)} of {len(ign)} ignition hours fit the {best_name} variant"
        if shifts:
            verdict += f"; the wind leaves its sector at {shifts[0]:02d}:00"
    else:
        verdict = "NO-GO: no ignition hour within prescription"
    return {"verdict": verdict, "suggested_variant": best_name, "suggested_variant_id": best, "go_windows": windows,
            "wind_shift_hours": shifts, "unchecked_params": unchecked, "hours": hours}
