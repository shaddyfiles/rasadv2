"""Reads and writes against the database, shared by the REST API and the assistant."""
import json
from datetime import date, datetime, timedelta

import forecast as fc
from db import jload

COVER_CRIT, COVER_WARN = 3, 7


def now():
    return datetime.now().isoformat(timespec="seconds")


def status_of(days):
    if days is None:
        return "ok"
    return "crit" if days < COVER_CRIT else "warn" if days < COVER_WARN else "ok"


def items(db):
    return {i["id"]: i for i in db.q("SELECT * FROM items")}


def bases_raw(db):
    rows = db.q(f"SELECT id, name, kind, depot_id, strength, alt_m, temp_c, tempo, {db.geom_out()} FROM bases ORDER BY id")
    for r in rows:
        r["geom"] = jload(r["geom"])
        r["lonlat"] = r["geom"]["coordinates"]
    return {r["id"]: r for r in rows}


def roads(db):
    rows = db.q(f"SELECT id, name, a, b, km, speed_kmh, alt_m, mode, exposure, max_kg, status, risk, zone, risk_source, {db.geom_out()} FROM roads ORDER BY id")
    for r in rows:
        r["geom"] = jload(r["geom"])
    return rows


def inbound(db):
    """{base_id: {item: [(eta_day, qty)]}} from shipments in transit."""
    out = {}
    for s in db.q("SELECT trip FROM shipments WHERE status = 'in_transit'"):
        trip = jload(s["trip"])
        for d in trip["drops"]:
            for l in d["lines"]:
                out.setdefault(d["base_id"], {}).setdefault(l["item"], []).append((d["eta"], l["qty"]))
    return out


def snapshot(db):
    """Everything the optimiser and the UI need, with forecasts and cover per base and item."""
    its = items(db)
    bs = bases_raw(db)
    inv = {}
    for r in db.q("SELECT base_id, item_id, qty FROM inventory"):
        inv.setdefault(r["base_id"], {})[r["item_id"]] = r["qty"]
    inb = inbound(db)
    models = fc.train(db)
    for b in bs.values():
        b["stock"] = inv.get(b["id"], {})
        b["inbound"] = {k: sum(q for _, q in v) for k, v in inb.get(b["id"], {}).items()}
        b["inbound_days"] = inb.get(b["id"], {})
        b["forecast"], b["cover"] = {}, {}
        if b["kind"] == "post":
            for it in its:
                f = fc.forecast(db, b, it, models=models)
                b["forecast"][it] = f
                b["cover"][it] = fc.cover(b["stock"][it], f, inb.get(b["id"], {}).get(it, []))
    for d in bs.values():
        if d["kind"] == "depot":
            served = [b for b in bs.values() if b.get("depot_id") == d["id"] and b["kind"] == "post"]
            for it in its:
                m = sum(sum(x["p50"] for x in b["forecast"][it][:7]) / 7 for b in served)
                d["cover"][it] = d["stock"][it] / m if m > 0 else None
    return {"items": its, "bases": bs, "roads": roads(db), "vehicles": db.q("SELECT * FROM vehicles ORDER BY id")}


def worst(b):
    vals = [(v, k) for k, v in b["cover"].items() if k != "spares"]
    if not vals:
        return None, None
    known = [x for x in vals if x[0] is not None]
    return min(known) if known else (None, vals[0][1])


def base_summary(b, its):
    w, wi = worst(b)
    return {"id": b["id"], "name": b["name"], "kind": b["kind"], "depot_id": b["depot_id"], "strength": b["strength"], "alt_m": b["alt_m"],
            "temp_c": b["temp_c"], "tempo": b["tempo"], "lonlat": b["lonlat"], "worst_days": None if w is None else round(w, 2),
            "worst_item": its[wi]["name"] if wi else None, "status": "ok" if b["kind"] == "base" else status_of(w)}


def base_detail(snap, bid):
    b, its = snap["bases"][bid], snap["items"]
    rows = []
    for it, meta in its.items():
        f = b["forecast"].get(it)
        p50 = sum(x["p50"] for x in f[:7]) / 7 if f else None
        if b["kind"] == "depot":
            served = [x for x in snap["bases"].values() if x.get("depot_id") == bid and x["kind"] == "post"]
            p50 = sum(sum(y["p50"] for y in x["forecast"][it][:7]) / 7 for x in served)
        c = b["cover"].get(it)
        rows.append({"item": it, "name": meta["name"], "unit": meta["unit"], "qty": None if b["kind"] == "base" else round(b["stock"][it], 1),
                     "per_day": None if p50 is None else round(p50, 2), "cover_days": None if c is None else round(c, 2),
                     "runs_out": None if c is None else (date.today() + timedelta(days=c)).isoformat(),
                     "status": "ok" if b["kind"] == "base" else status_of(c), "inbound": round(b["inbound"].get(it, 0), 1)})
    return {**base_summary(b, its), "inventory": rows}


def forecast_view(db, bid, item):
    b = bases_raw(db)[bid]
    hist = db.q("SELECT day, qty FROM consumption WHERE base_id = ? AND item_id = ? ORDER BY day DESC LIMIT 30", (bid, item))[::-1]
    return {"base": bid, "item": item, "engine": fc.ENGINE, "history": hist, "forecast": fc.forecast(db, b, item)}


def alerts(snap):
    out = []
    its = snap["items"]
    for b in snap["bases"].values():
        if b["kind"] == "base":
            continue
        for it, c in b["cover"].items():
            if it == "spares" or c is None or c >= COVER_WARN:
                continue
            who = b["name"] if b["kind"] == "post" else f"{b['name']} (stock for its posts)"
            inb = b["inbound"].get(it, 0)
            out.append({"level": status_of(c), "kind": "stock", "base_id": b["id"], "days": round(c, 1),
                        "text": f"{who}: {its[it]['name'].split(' (')[0].lower()} {'last' if it in ('ration', 'med') else 'lasts'} {c:.1f} days" + (f", with {inb:,.0f} {its[it]['unit']} on the way." if inb else ", nothing on the way.")})
    for r in snap["roads"]:
        if r["status"] == "closed":
            out.append({"level": "crit", "kind": "road", "road_id": r["id"], "text": f"{r['name']} is closed."})
        elif r["risk"] >= 0.4:
            out.append({"level": "warn", "kind": "road", "road_id": r["id"], "text": f"{r['name']} has a {r['risk'] * 100:.0f}% chance of closing."})
    out.sort(key=lambda a: (a["level"] != "crit", a.get("days", 99)))
    return out


# ------------------------------------------------------------------ writes
def resolve_base(db, name):
    s = str(name or "").strip().lower()
    for b in db.q("SELECT id, name FROM bases"):
        if s in (b["id"].lower(), b["name"].lower()) or b["name"].lower().split()[-1] == s or b["name"].split()[-1].lower() in s.split():
            return b["id"]
    return None


def resolve_road(db, name):
    """Best road match by id, exact name, or the most shared words ("tangla", "kesari ridge")."""
    s = str(name or "").strip().lower()
    words = set(s.replace("-", " ").split()) - {"road", "track", "la", "the"}
    best, score = None, 0
    for r in db.q("SELECT id, name FROM roads"):
        n = r["name"].lower()
        if s in (r["id"], n):
            return r["id"]
        sc = len(words & (set(n.replace("-", " ").split()) - {"road", "track", "la"}))
        if sc > score:
            best, score = r["id"], sc
    return best


ITEM_WORDS = {"ration": "ration", "rations": "ration", "food": "ration", "fuel": "fuel", "kerosene": "fuel", "diesel": "fuel",
              "ammo": "ammo", "ammunition": "ammo", "med": "med", "medical": "med", "medicine": "med", "spares": "spares", "parts": "spares"}


def resolve_item(name):
    return ITEM_WORDS.get(str(name or "").strip().lower(), name if name in ITEM_WORDS.values() else None)


def set_inventory(db, base, item, qty):
    db.x("UPDATE inventory SET qty = ?, updated_at = ? WHERE base_id = ? AND item_id = ?", (float(qty), now(), base, item))
    db.commit()


def report_consumption(db, base, item, qty, day=None):
    b = db.q("SELECT strength, temp_c, tempo FROM bases WHERE id = ?", (base,), one=True)
    db.x("INSERT INTO consumption(base_id, item_id, day, qty, strength, temp_c, tempo) VALUES (?,?,?,?,?,?,?)",
         (base, item, day or date.today().isoformat(), float(qty), b["strength"], b["temp_c"], b["tempo"]))
    db.x("UPDATE inventory SET qty = CASE WHEN qty > ? THEN qty - ? ELSE 0 END, updated_at = ? WHERE base_id = ? AND item_id = ?",
         (float(qty), float(qty), now(), base, item))
    db.commit()


def set_road(db, road, status=None, risk=None):
    if status is not None:
        db.x("UPDATE roads SET status = ? WHERE id = ?", (status, road))
    if risk is not None:
        db.x("UPDATE roads SET risk = ?, risk_source = 'manual' WHERE id = ?", (max(0.0, min(1.0, float(risk))), road))
    db.commit()


def set_base(db, base, strength=None, tempo=None, temp_c=None):
    for col, v in (("strength", strength), ("tempo", tempo), ("temp_c", temp_c)):
        if v is not None:
            db.x(f"UPDATE bases SET {col} = ? WHERE id = ?", (float(v) if col != "strength" else int(v), base))
    db.commit()


def save_plan(db, result):
    row = db.x("INSERT INTO plans(created_at, status, result) VALUES (?, 'proposed', ?) RETURNING id", (now(), json.dumps(result)))
    db.commit()
    return row["id"]


def dispatch(db, plan_id, trip_ids=None):
    p = db.q("SELECT * FROM plans WHERE id = ?", (plan_id,), one=True)
    if not p:
        raise LookupError("unknown plan")
    if p["status"] != "proposed":
        raise ValueError(f"plan already {p['status']}")
    res = jload(p["result"])
    sent = set(res.get("dispatched_trips", []))
    created, skipped = [], []
    for t in res["trips"]:
        if (trip_ids and t["id"] not in trip_ids) or t["id"] in sent:
            continue
        v = db.q("SELECT status FROM vehicles WHERE id = ?", (t["vehicle_id"],), one=True)
        if not v or v["status"] != "idle":
            skipped.append(t["id"])
            continue
        sent.add(t["id"])
        for d in t["drops"]:
            for l in d["lines"]:
                db.x("UPDATE inventory SET qty = CASE WHEN qty > ? THEN qty - ? ELSE 0 END, updated_at = ? WHERE base_id = ? AND item_id = ?",
                     (l["qty"], l["qty"], now(), t["from"], l["item"]))
        db.x("UPDATE vehicles SET status = 'busy' WHERE id = ?", (t["vehicle_id"],))
        row = db.x("INSERT INTO shipments(plan_id, vehicle_id, status, created_at, eta, trip) VALUES (?,?, 'in_transit', ?,?,?) RETURNING id",
                   (plan_id, t["vehicle_id"], now(), t["drops"][-1]["eta"], json.dumps(t)))
        created.append(row["id"])
    if skipped and not created:
        db.rollback()
        raise ValueError(f"vehicles are busy for trips {skipped}")
    res["dispatched_trips"] = sorted(sent)
    # a plan stays open while trips with busy vehicles are still unsent, so they can be dispatched later
    db.x("UPDATE plans SET status = ?, result = ? WHERE id = ?", ("proposed" if skipped else "dispatched", json.dumps(res), plan_id))
    db.commit()
    return created


def deliver(db, shipment_id):
    s = db.q("SELECT * FROM shipments WHERE id = ?", (shipment_id,), one=True)
    if not s:
        raise LookupError("unknown shipment")
    if s["status"] != "in_transit":
        raise ValueError("shipment is not in transit")
    trip = jload(s["trip"])
    for d in trip["drops"]:
        for l in d["lines"]:
            db.x("UPDATE inventory SET qty = qty + ?, updated_at = ? WHERE base_id = ? AND item_id = ?", (l["qty"], now(), d["base_id"], l["item"]))
    db.x("UPDATE shipments SET status = 'delivered' WHERE id = ?", (shipment_id,))
    db.x("UPDATE vehicles SET status = 'idle' WHERE id = ?", (s["vehicle_id"],))
    db.commit()


def shipments(db, active=True):
    rows = db.q("SELECT * FROM shipments" + (" WHERE status = 'in_transit'" if active else "") + " ORDER BY id DESC LIMIT 50")
    for r in rows:
        r["trip"] = jload(r["trip"])
    return rows
