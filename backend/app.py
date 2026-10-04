"""Rasad REST API (Flask). Serves the React map UI from ./static and JSON under /api.

Run:  python app.py            (dev, http://localhost:5000)
      gunicorn -w 2 --threads 4 -b 0.0.0.0:8000 app:app
"""
import datetime
import hmac
import json
import math
import os
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory

import assistant
import forecast as fc
import optimizer
import predict
import scenarios
import store
from config import Config
from db import DB, jload
from seed import seed

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
cfg = Config
db = DB(cfg.DATABASE_URL)
with db.lock:
    if not db.has_schema():
        seed(db)
        predict.refresh_road_risk(db, include_manual=True)


# ------------------------------------------------------------------ helpers
def safe(o):
    if hasattr(o, "item") and not isinstance(o, (dict, list, tuple, str)):   # numpy scalars
        o = o.item()
    if isinstance(o, float):
        return None if math.isinf(o) or math.isnan(o) else o
    if isinstance(o, dict):
        return {k: safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [safe(v) for v in o]
    return o


def ok(o, code=200):
    return jsonify(safe(o)), code


def fail(msg, code=400):
    return jsonify({"error": msg}), code


def body():
    return request.get_json(silent=True) or {}


def authorised():
    return not cfg.API_KEY or hmac.compare_digest(request.headers.get("X-API-Key", ""), cfg.API_KEY)


def keyed(fn):
    """Needs X-API-Key when RASAD_API_KEY is set (for routes that do not write but are costly or sensitive)."""
    @wraps(fn)
    def inner(*a, **k):
        if not authorised():
            return fail("missing or wrong X-API-Key", 401)
        return fn(*a, **k)
    return inner


def write(fn):
    """Writes need X-API-Key when RASAD_API_KEY is set, and run one at a time."""
    @wraps(fn)
    def inner(*a, **k):
        if not authorised():
            return fail("missing or wrong X-API-Key", 401)
        with db.lock:
            try:
                return fn(*a, **k)
            except LookupError as e:
                db.rollback()
                return fail(str(e), 404)
            except ValueError as e:
                db.rollback()
                return fail(str(e), 409)
    return inner


@app.after_request
def cors(resp):
    origin = os.environ.get("RASAD_CORS_ORIGIN")      # the UI is served from this app, so CORS is off unless set
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, OPTIONS"
    return resp


def make_plan(weights=None, seed_value=0):
    snap = store.snapshot(db)
    res = optimizer.plan(snap, weights, cfg, seed=seed_value)
    res["id"] = store.save_plan(db, res)
    return res


# ------------------------------------------------------------------ pages
@app.get("/")
@app.get("/bases")
@app.get("/bases/<path:_id>")
@app.get("/plan")
@app.get("/movements")
@app.get("/roads")
@app.get("/assistant")
@app.get("/predictions")
@app.get("/whatif")
def index(_id=None):
    """React pages; the client-side router picks the page from the URL."""
    return send_from_directory(STATIC, "index.html")


# ------------------------------------------------------------------ system
@app.get("/api/health")
def health():
    """Database, forecasting engine and Qwen3 status."""
    return ok({"today": datetime.date.today().isoformat(), "db": db.kind, "forecast_engine": fc.ENGINE, "llm": assistant.status(cfg), "api_key_required": bool(cfg.API_KEY)})


@app.get("/api/map")
def map_data():
    """GeoJSON for the map: bases (with cover status) and roads (with status and risk)."""
    snap = store.snapshot(db)
    bases = [{"type": "Feature", "geometry": b["geom"], "properties": store.base_summary(b, snap["items"])} for b in snap["bases"].values()]
    roads = [{"type": "Feature", "geometry": r["geom"], "properties": {k: r[k] for k in r if k != "geom"}} for r in snap["roads"]]
    return ok({"bases": {"type": "FeatureCollection", "features": bases}, "roads": {"type": "FeatureCollection", "features": roads}})


# ------------------------------------------------------------------ bases and inventory
@app.get("/api/bases")
def bases():
    """All bases with worst-case days of cover."""
    snap = store.snapshot(db)
    return ok([store.base_summary(b, snap["items"]) for b in snap["bases"].values()])


@app.get("/api/bases/<bid>")
def base(bid):
    """Inventory, daily use, days of cover and inbound for one base."""
    snap = store.snapshot(db)
    if bid not in snap["bases"]:
        return fail("unknown base", 404)
    return ok(store.base_detail(snap, bid))


@app.get("/api/bases/nearby")
def nearby():
    """Bases within ?km of ?lat,?lon (PostGIS ST_DWithin; haversine on SQLite)."""
    try:
        lat, lon, km = float(request.args["lat"]), float(request.args["lon"]), float(request.args.get("km", 50))
    except (KeyError, ValueError):
        return fail("lat and lon are required numbers")
    return ok(db.nearby_bases(lon, lat, km))


@app.patch("/api/bases/<bid>")
@write
def base_update(bid):
    """Update strength, tempo (1, 1.5, 2.2) or temperature. Body: {"strength": 60}."""
    b = body()
    if bid not in store.bases_raw(db):
        return fail("unknown base", 404)
    store.set_base(db, bid, b.get("strength"), b.get("tempo"), b.get("temp_c"))
    return base(bid)


@app.put("/api/inventory/<bid>/<item>")
@write
def inventory_set(bid, item):
    """Set stock on hand. Body: {"qty": 640}."""
    try:
        qty = float(body()["qty"])
    except (KeyError, TypeError, ValueError):
        return fail("qty must be a number")
    if qty < 0:
        return fail("qty cannot be negative")
    if item not in store.items(db) or bid not in store.bases_raw(db):
        return fail("unknown base or item", 404)
    store.set_inventory(db, bid, item, qty)
    return base(bid)


@app.post("/api/consumption")
@write
def consumption():
    """Record consumption (reduces stock, retrains the model). Body: {"base_id":"P4","item_id":"fuel","qty":70}."""
    b = body()
    try:
        qty = float(b["qty"])
    except (KeyError, TypeError, ValueError):
        return fail("qty must be a number")
    if b.get("item_id") not in store.items(db) or b.get("base_id") not in store.bases_raw(db) or qty < 0:
        return fail("valid base_id, item_id and a non-negative qty are required")
    store.report_consumption(db, b["base_id"], b["item_id"], qty, b.get("day"))
    return ok({"ok": True}, 201)


# ------------------------------------------------------------------ forecasting
@app.get("/api/forecast/<bid>/<item>")
def forecast(bid, item):
    """30 days of history and a 14-day P10/P50/P90 forecast."""
    if bid not in store.bases_raw(db) or item not in store.items(db):
        return fail("unknown base or item", 404)
    return ok(store.forecast_view(db, bid, item))


@app.get("/api/forecast/metrics")
def forecast_metrics():
    """14-day hold-out error of each demand model, range coverage and feature importance."""
    return ok(fc.metrics(db))


# ------------------------------------------------------------------ advanced prediction
@app.get("/api/predict")
def predictions():
    """Chance of running out (Monte Carlo), 7-day road closure outlook (classifier), model accuracy."""
    snap = store.snapshot(db)
    return ok({"stockout": predict.stockout_risk(snap), "roads": predict.road_outlook(db, 7), "demand": fc.metrics(db)})


@app.post("/api/predict/roads/refresh")
@write
def predict_refresh():
    """Re-apply the closure model to every road's risk, replacing manual values."""
    o = predict.refresh_road_risk(db, include_manual=True)
    return ok({"updated": len(o["roads"])})


@app.get("/api/hazards")
def hazards():
    """Sector map layers for the next 7 days: closure chance per road, weather per zone, avalanche danger,
    enemy observation, bridge limits and high passes."""
    return ok(predict.hazards(db, 7))


@app.get("/api/weather")
def weather():
    """Observed weather for the last 7 days and the 14-day forecast, per zone."""
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    return ok(db.q("SELECT day, zone, snow_cm, temp_c, wind_kmh, kind FROM weather WHERE day >= ? ORDER BY zone, day", (since,)))


# ------------------------------------------------------------------ roads
@app.get("/api/roads")
def roads():
    """Road network with status and closure risk."""
    return ok([{k: r[k] for k in r if k != "geom"} for r in store.roads(db)])


@app.patch("/api/roads/<rid>")
@write
def road_update(rid):
    """Open/close a road or set its risk. Body: {"status": "closed"} or {"risk": 0.6}."""
    b = body()
    if b.get("status") not in (None, "open", "closed"):
        return fail("status must be open or closed")
    if not any(r["id"] == rid for r in store.roads(db)):
        return fail("unknown road", 404)
    store.set_road(db, rid, b.get("status"), b.get("risk"))
    return ok(next({k: r[k] for k in r if k != "geom"} for r in store.roads(db) if r["id"] == rid))


# ------------------------------------------------------------------ optimiser
@app.post("/api/plan")
@write
def plan():
    """Run GA + ACO. Body: {"weights": {"speed":1, "safety":1, "economy":1}}."""
    b = body()
    return ok(make_plan(b.get("weights"), int(b.get("seed", 0))), 201)


@app.get("/api/whatif")
def whatif_list():
    """The ready-made what-if scenarios."""
    return ok([{"id": k, "label": v["label"], "text": v["text"]} for k, v in scenarios.PRESETS.items()])


@app.post("/api/whatif")
@keyed
def whatif():
    """Disrupt a copy of the sector, plan the resupply and measure the stock-out risk before and after.
    Body: {"scenario": "pass_closed"} or {"close": ["s2"], "ground_helis": true, "surge": {"base": "P2", "pct": 60}}. Changes nothing."""
    try:
        return ok(scenarios.run(db, cfg, body()))
    except ValueError as e:
        return fail(str(e))


@app.get("/api/plan/latest")
def plan_latest():
    p = db.q("SELECT * FROM plans ORDER BY id DESC LIMIT 1", one=True)
    if not p:
        return jsonify(None)
    return ok({**jload(p["result"]), "id": p["id"], "status": p["status"]})


@app.post("/api/plan/<int:pid>/dispatch")
@write
def plan_dispatch(pid):
    """Dispatch trips (all, or {"trip_ids": [1, 3]}). Stock leaves the depots; vehicles become busy."""
    ids = store.dispatch(db, pid, body().get("trip_ids"))
    return ok({"shipments": ids})


@app.get("/api/shipments")
def shipments():
    """Shipments in transit (?all=1 for history)."""
    return ok(store.shipments(db, active=request.args.get("all") != "1"))


@app.post("/api/shipments/<int:sid>/deliver")
@write
def shipment_deliver(sid):
    """Confirm delivery: stock is added at each drop and the vehicle is free again."""
    store.deliver(db, sid)
    return ok({"ok": True})


# ------------------------------------------------------------------ alerts and assistant
@app.get("/api/alerts")
def alerts():
    """Low-cover and road alerts."""
    return ok(store.alerts(store.snapshot(db)))


@app.post("/api/alerts/brief")
@keyed
def alerts_brief():
    """Qwen3 alert briefing (template when offline)."""
    return ok(assistant.brief(db, cfg, store.alerts(store.snapshot(db))))


@app.post("/api/command")
@keyed
def command():
    """Natural-language command. Body: {"text": "close Tangla road", "history": [...]}.
    Returns a reply plus any proposed write actions for the user to confirm."""
    b = body()
    text = (b.get("text") or "").strip()
    if not text:
        return fail("text is empty")
    with db.lock:
        res = assistant.command(db, cfg, text[:1000], b.get("history") or [], lambda: make_plan())
    return ok(res)


@app.post("/api/command/execute")
@write
def command_execute():
    """Run a confirmed action returned by /api/command. Body: {"action": {...}}."""
    a = body().get("action")
    if not a or "tool" not in a:
        return fail("action is required")
    act, err = assistant.normalise(db, a["tool"], {k: v for k, v in a.get("args", {}).items()})
    if err:
        return fail(err)
    return ok({"result": assistant.execute(db, act), "done": assistant.describe(act, db)})


@app.post("/api/reset")
@write
def reset():
    """Re-seed the synthetic sector."""
    seed(db)
    predict.refresh_road_risk(db, include_manual=True)
    return ok({"ok": True})


@app.get("/api/docs")
def docs():
    """Endpoint index."""
    out = []
    for r in app.url_map.iter_rules():
        if r.rule.startswith("/api"):
            out.append({"path": r.rule, "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
                        "doc": (app.view_functions[r.endpoint].__doc__ or "").strip().split("\n")[0]})
    return ok(sorted(out, key=lambda x: x["path"]))


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), threaded=True)
