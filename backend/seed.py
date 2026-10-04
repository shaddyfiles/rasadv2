"""Seed a fictional sector (Sector Himgiri): bases, road network geometry, fleet,
60 days of consumption history and current inventory. All data is synthetic, except the weather when
RASAD_REAL_DATA=1 (see realdata.py)."""
import json
import math
import random
from datetime import date, timedelta

import realdata

ITEMS = [  # id, name, unit, kg per unit, criticality
    ("ration", "Rations", "kg", 1.0, 0.8),
    ("fuel", "Fuel (SKO/HSD)", "L", 0.85, 0.9),
    ("ammo", "Ammunition", "box", 25.0, 1.0),
    ("med", "Medical stores", "kit", 6.0, 1.0),
    ("spares", "Spares", "part", 12.0, 0.5),
]

# id, name, kind, depot, strength, altitude, schematic x, y
BASES = [
    ("BD", "Base Depot Shakti", "base", None, 0, 3500, 110, 540),
    ("FD1", "Forward Depot Neel", "depot", "BD", 0, 3900, 420, 430),
    ("FD2", "Forward Depot Dhruv", "depot", "BD", 0, 4200, 560, 200),
    ("P1", "Post Garud", "post", "FD1", 120, 4700, 690, 500),
    ("P2", "Post Kesari", "post", "FD1", 80, 5100, 850, 400),
    ("P3", "Post Vajra", "post", "FD2", 90, 5300, 760, 190),
    ("P4", "Post Trishul", "post", "FD2", 45, 5650, 900, 90),
    ("P5", "Post Agni", "post", "FD1", 140, 4300, 600, 600),
    ("P6", "Post Hima", "post", "FD2", 70, 5000, 330, 120),
]

# id, name, a, b, km, speed, alt, mode, exposure, max_kg, risk, schematic points
ROADS = [
    ("s1", "Highway 1", "BD", "FD1", 180, 30, 3900, "road", 0.0, None, 0.05, [[110, 540], [190, 522], [300, 472], [420, 430]]),
    ("s2", "Tangla La road", "FD1", "FD2", 95, 16, 5350, "road", 0.0, None, 0.45, [[420, 430], [440, 370], [478, 322], [515, 268], [560, 200]]),
    ("s3", "Zarla La road", "BD", "FD2", 260, 20, 5100, "road", 0.0, None, 0.20, [[110, 540], [140, 430], [205, 345], [252, 300], [330, 268], [440, 232], [560, 200]]),
    ("s4", "Garud road", "FD1", "P1", 70, 20, 4700, "road", 0.1, None, 0.05, [[420, 430], [515, 470], [600, 505], [690, 500]]),
    ("s5", "Kesari track", "P1", "P2", 55, 12, 5100, "road", 0.5, 2500, 0.25, [[690, 500], [765, 470], [850, 400]]),
    ("s6", "Agni road", "FD1", "P5", 60, 22, 4300, "road", 0.0, None, 0.05, [[420, 430], [470, 520], [530, 580], [600, 600]]),
    ("s7", "Vajra track", "FD2", "P3", 50, 12, 5300, "road", 0.0, None, 0.30, [[560, 200], [650, 222], [760, 190]]),
    ("s8", "Trishul mule track", "P3", "P4", 18, 2.4, 5650, "animal", 0.2, None, 0.35, [[760, 190], [815, 150], [862, 120], [900, 90]]),
    ("s9", "Hima track", "FD2", "P6", 75, 14, 5000, "road", 0.0, None, 0.25, [[560, 200], [470, 170], [400, 130], [330, 120]]),
    ("s10", "Agni-Garud link", "P5", "P1", 40, 15, 4400, "road", 0.35, None, 0.10, [[600, 600], [655, 575], [690, 500]]),
    ("s11", "Kesari ridge track", "P2", "P3", 48, 10, 5500, "road", 0.7, None, 0.35, [[850, 400], [882, 330], [842, 262], [792, 216], [760, 190]]),
]

# Weather zone of each road (snowfall differs between the valley, the two passes and the high posts)
ROAD_ZONE = {"s1": "valley", "s2": "tangla", "s3": "zarla", "s4": "valley", "s5": "high", "s6": "valley",
             "s7": "high", "s8": "high", "s9": "high", "s10": "valley", "s11": "high"}
ZONES = {"valley": 3900, "tangla": 5350, "zarla": 5100, "high": 5300}   # representative altitude

FLEET = [("BD", "truck", 4), ("FD1", "truck", 4), ("FD2", "truck", 3), ("FD1", "heli", 2)]
DEPOT_STOCK = {"FD1": dict(ration=30000, fuel=40000, ammo=900, med=400, spares=120),
               "FD2": dict(ration=5200, fuel=3800, ammo=260, med=90, spares=24)}
UNLIMITED = 1e9
DAYS_OF_SUPPLY = {"P4": {"fuel": 1.2, "ration": 6}, "P6": {"med": 4.5}, "P2": {"ammo": 6, "fuel": 8}, "P3": {"fuel": 7}, "P1": {"ration": 9}}


def lonlat(x, y):
    """Schematic sector coordinates -> WGS84 (a fictional box in the high Himalaya)."""
    return [round(77.30 + x / 1000 * 1.4, 5), round(34.90 - y / 640 * 0.85, 5)]


def temp_now(alt):
    return 7 - (alt - 3500) * 0.0062


def true_demand(item, s, temp, tempo):
    cold = max(0.0, 5 - temp)
    tp = tempo - 1
    return {"ration": s * 1.6 * (1 + 0.006 * cold) * (1 + 0.05 * tp),
            "fuel": s * (0.5 + 0.085 * cold) * (1 + 0.12 * tp),
            "ammo": s * 0.02 * (1 + 2.2 * tp),
            "med": s * 0.004 * (1 + 0.012 * cold) * (1 + 0.6 * tp),
            "spares": s * 0.0025 * (1 + 0.015 * cold)}[item]


def seed(db, seed_value=26251):
    rng = random.Random(seed_value)
    today = date.today()
    with db.lock:
        db.create_schema(drop=True)
        g = db.geom_in()
        db.many("INSERT INTO items(id, name, unit, kg_per_unit, criticality) VALUES (?,?,?,?,?)", ITEMS)
        db.many(f"INSERT INTO bases(id, name, kind, depot_id, strength, alt_m, temp_c, tempo, geom) VALUES (?,?,?,?,?,?,?,?,{g})",
                [(i, n, k, d, s, a, round(temp_now(a), 1), 1.0, json.dumps({"type": "Point", "coordinates": lonlat(x, y)}))
                 for i, n, k, d, s, a, x, y in BASES])
        db.many(f"INSERT INTO roads(id, name, a, b, km, speed_kmh, alt_m, mode, exposure, max_kg, status, risk, zone, risk_source, geom) VALUES (?,?,?,?,?,?,?,?,?,?,'open',?,?,'model',{g})",
                [(i, n, a, b, km, sp, alt, m, e, mk, r, ROAD_ZONE[i], json.dumps({"type": "LineString", "coordinates": [lonlat(*p) for p in pts]}))
                 for i, n, a, b, km, sp, alt, m, e, mk, r, pts in ROADS])
        seed_weather(db, rng, today)
        vrows = []
        for home, typ, n in FLEET:
            short = next(b[1] for b in BASES if b[0] == home).split()[-1]
            for k in range(1, n + 1):
                vrows.append((f"{home}-{'H' if typ == 'heli' else 'T'}{k}", f"{short} {'helicopter' if typ == 'heli' else 'truck'} {k}", typ, home, 1200 if typ == "heli" else 4500))
        db.many("INSERT INTO vehicles(id, name, type, home, cap_kg, status) VALUES (?,?,?,?,?,'idle')", vrows)

        # 60 days of history with seasonal cooling, strength changes and patrol surges
        rows = []
        for bid, _, kind, _, strength, alt, x, _y in BASES:
            if kind != "post":
                continue
            surges = []
            for _ in range(3):
                st = -58 + int(rng.random() * 52)
                surges.append((st, st + 2 + int(rng.random() * 4), 1.5 if rng.random() < 0.5 else 2.2))
            for d in range(-60, 0):
                s = round(strength * (0.8 if bid in ("P2", "P5") and d < -30 else 1.0) * (1 + 0.04 * rng.gauss(0, 1)))
                temp = temp_now(alt) - 0.2 * d + 2.2 * math.sin((d + x / 50) / 3.1) + rng.uniform(-1, 1)
                tempo = next((v for a, b, v in surges if a <= d <= b), 1.0)
                for item, *_ in ITEMS:
                    mu = true_demand(item, s, temp, tempo)
                    if item == "spares":
                        q = float(1 + int(rng.random() * 3)) if rng.random() < 0.12 * (1 + 0.015 * max(0, 5 - temp)) else 0.0
                    else:
                        sd = {"ration": 0.10, "fuel": 0.12, "ammo": 0.28, "med": 0.22}[item]
                        q = mu * math.exp(sd * rng.gauss(0, 1) - sd * sd / 2)
                    rows.append((bid, item, (today + timedelta(days=d)).isoformat(), round(q, 3), s, round(temp, 2), tempo))
        db.many("INSERT INTO consumption(base_id, item_id, day, qty, strength, temp_c, tempo) VALUES (?,?,?,?,?,?,?)", rows)

        inv = []
        now = today.isoformat()
        for bid, _, kind, _, strength, alt, _x, _y in BASES:
            for item, *_ in ITEMS:
                if kind == "base":
                    q = UNLIMITED
                elif kind == "depot":
                    q = DEPOT_STOCK[bid][item]
                elif item == "spares":
                    q = 1 if bid == "P4" else 3 + int(rng.random() * 5)
                else:
                    dos = DAYS_OF_SUPPLY.get(bid, {}).get(item, 12 + rng.random() * 14)
                    q = round(true_demand(item, strength, temp_now(alt), 1.0) * dos)
                inv.append((bid, item, q, now))
        db.many("INSERT INTO inventory(base_id, item_id, qty, updated_at) VALUES (?,?,?,?)", inv)
        db.commit()


# ERA5 snowfall in this cold desert is light (3-day totals of about 10 cm are a big event), so with real weather
# the hidden closure rule reads snow on a scale where 10 cm counts like 40 cm of the synthetic storms.
# The closures themselves are still simulated: no public record exists for these fictional roads.
REAL_SNOW_SCALE = 0.25


def closure_truth(snow3, wind, temp, alt, mule, rng, snow_scale=1.0):
    """Hidden rule that generates the historical closures the model learns from."""
    snow3 = snow3 / snow_scale
    x = snow3 * (1 + (alt - 4500) / 1800) + 0.35 * max(0.0, wind - 35) + 6 * mule + 0.8 * max(0.0, temp - 2) * (snow3 > 15)
    p = 1 / (1 + math.exp(-(x - 34) / 6))
    return int(rng.random() < p)


def seed_weather(db, rng, today):
    """120 days of past weather and closures, plus a 14-day forecast with a storm crossing the passes."""
    rows, wx = [], {}
    storms = []
    d = -120
    while True:
        d += 7 + int(rng.random() * 10)
        if d >= -2:
            break
        storms.append((d, 0.8 + rng.random() * 0.8, 10 + rng.random() * 26))
    storms.append((3.5, 1.2, 40))   # the storm in the current forecast
    got = realdata.weather(realdata.zone_points(ROADS, ROAD_ZONE, lonlat), ZONES, today) if realdata.enabled() else None
    real, label = got if got else (None, "synthetic")
    db.x("INSERT INTO meta(key, value) VALUES ('weather_source', ?)", (label,))
    for zone, alt in ZONES.items():
        zf = {"valley": 0.2, "tangla": 0.85, "zarla": 0.7, "high": 0.55}[zone]
        for day in range(-120, 14):
            if real:
                snow, temp, wind = real[(zone, day)]
            else:
                snow = max(0.0, rng.gauss(1.5, 1.2)) * zf
                for c, w, a in storms:
                    snow += zf * a * math.exp(-((day - c) ** 2) / (2 * w * w))
                temp = 9 - (alt - 3500) * 0.0062 - 0.12 * day - 0.15 * snow + rng.gauss(0, 1.5)
                wind = max(0.0, rng.gauss(18, 7) + 0.6 * snow)
            wx[(zone, day)] = (snow, temp, wind)
            rows.append(((today + timedelta(days=day)).isoformat(), zone, round(snow, 1), round(temp, 1), round(wind, 1), "forecast" if day >= 0 else "observed"))
    db.many("INSERT INTO weather(day, zone, snow_cm, temp_c, wind_kmh, kind) VALUES (?,?,?,?,?,?)", rows)
    hist = []
    for rid, *_r in ROADS:
        road = next(r for r in ROADS if r[0] == rid)
        alt, mule, zone = road[6], 1 if road[7] == "animal" else 0, ROAD_ZONE[rid]
        for day in range(-120, 0):
            snow3 = sum(wx[(zone, day - k)][0] for k in range(3) if (zone, day - k) in wx)
            _, temp, wind = wx[(zone, day)]
            hist.append((rid, (today + timedelta(days=day)).isoformat(), closure_truth(snow3, wind, temp, alt, mule, rng, REAL_SNOW_SCALE if real else 1.0)))
    db.many("INSERT INTO road_history(road_id, day, closed) VALUES (?,?,?)", hist)
