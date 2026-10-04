"""End-to-end API tests on a throwaway SQLite database.  Run from the repo root: pytest -q

To run them on PostgreSQL + PostGIS instead, point RASAD_TEST_DATABASE_URL at an empty database you can throw away:
    RASAD_TEST_DATABASE_URL=postgresql://user@localhost:5432/rasad_test pytest -q
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = os.environ.get("RASAD_TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db"
    os.environ["RASAD_GA_GENS"] = "30"
    import app as rasad_app
    return rasad_app.app.test_client()


def test_health_and_map(client):
    h = client.get("/api/health").get_json()
    assert h["db"] in ("sqlite", "postgis") and "llm" in h
    m = client.get("/api/map").get_json()
    assert len(m["bases"]["features"]) == 9 and len(m["roads"]["features"]) == 11
    trishul = next(f["properties"] for f in m["bases"]["features"] if f["properties"]["id"] == "P4")
    assert trishul["status"] == "crit"


def test_forecast_quantiles_ordered(client):
    f = client.get("/api/forecast/P4/fuel").get_json()
    assert len(f["forecast"]) == 14 and len(f["history"]) == 30
    assert all(x["p10"] <= x["p50"] <= x["p90"] for x in f["forecast"])
    m = client.get("/api/forecast/metrics").get_json()
    assert m["wape"] < m["naive_wape"]


def test_nearby_spatial_query(client):
    rows = client.get("/api/bases/nearby?lat=34.3&lon=78.4&km=30").get_json()
    assert rows and all(r["km"] <= 30 for r in rows)


def test_plan_dispatch_deliver(client):
    p = client.post("/api/plan", json={}).get_json()
    assert p["metrics"]["cost"] <= p["baseline"]["cost"] + 1e-6
    assert p["metrics"]["penalty"] == 0
    assert any(d["base_id"] == "P4" for t in p["trips"] for d in t["drops"])
    r = client.post(f"/api/plan/{p['id']}/dispatch", json={}).get_json()
    assert r["shipments"]
    assert client.post(f"/api/plan/{p['id']}/dispatch", json={}).status_code == 409
    sid = r["shipments"][0]
    assert client.post(f"/api/shipments/{sid}/deliver", json={}).status_code == 200
    assert client.post(f"/api/shipments/{sid}/deliver", json={}).status_code == 409


def test_closed_road_is_avoided(client):
    client.patch("/api/roads/s2", json={"status": "closed"})
    p = client.post("/api/plan", json={}).get_json()
    assert all("s2" not in l.get("roads", []) for t in p["trips"] for l in t["legs"])
    client.patch("/api/roads/s2", json={"status": "open"})


def test_inventory_and_consumption(client):
    assert client.put("/api/inventory/P4/fuel", json={"qty": 500}).get_json()["inventory"][1]["qty"] == 500
    assert client.put("/api/inventory/P4/fuel", json={"qty": -1}).status_code == 400
    assert client.post("/api/consumption", json={"base_id": "P4", "item_id": "fuel", "qty": 50}).status_code == 201
    assert client.get("/api/bases/P4").get_json()["inventory"][1]["qty"] == 450


def test_commands_need_confirmation(client):
    r = client.post("/api/command", json={"text": "close Tangla road"}).get_json()
    assert r["actions"] and r["actions"][0]["tool"] == "set_road"
    assert next(x for x in client.get("/api/roads").get_json() if x["id"] == "s2")["status"] == "open"   # not yet applied
    client.post("/api/command/execute", json={"action": r["actions"][0]})
    assert next(x for x in client.get("/api/roads").get_json() if x["id"] == "s2")["status"] == "closed"
    for text in ("set fuel at Trishul to 700", "used 40 L of fuel at Vajra", "strength at Kesari to 100", "status of Hima", "plan resupply", "alerts"):
        assert client.post("/api/command", json={"text": text}).get_json()["reply"]
    assert client.post("/api/alerts/brief", json={}).get_json()["text"]


def test_predictions(client):
    p = client.get("/api/predict").get_json()
    rows = p["stockout"]["rows"]
    assert rows and all(0 <= r["p3"] <= r["p7"] <= r["p14"] <= 1 for r in rows)
    roads = p["roads"]["roads"]
    assert len(roads) == 11 and all(len(r["days"]) == 7 for r in roads)
    assert p["roads"]["stats"]["auc"] > 0.75
    assert p["demand"]["by_model"]["ens"] < p["demand"]["by_model"]["naive"]


def test_road_risk_refresh_overrides_manual(client):
    client.patch("/api/roads/s10", json={"risk": 0.9})
    r = next(x for x in client.get("/api/roads").get_json() if x["id"] == "s10")
    assert r["risk_source"] == "manual"
    client.post("/api/predict/roads/refresh", json={})
    r = next(x for x in client.get("/api/roads").get_json() if x["id"] == "s10")
    assert r["risk_source"] == "model" and r["risk"] < 0.9


def test_hazards_for_map(client):
    h = client.get("/api/hazards").get_json()
    assert len(h["days"]) == 7 and {z["zone"] for z in h["zones"]} == {"valley", "tangla", "zarla", "high"}
    roads = {r["id"]: r for r in h["roads"]}
    assert len(roads) == 11 and all(len(r["days"]) == 7 for r in roads.values())
    assert any(f["kind"] == "bridge" for f in roads["s5"]["fixed"]) and any(f["kind"] == "observation" for f in roads["s11"]["fixed"])
    tangla = roads["s2"]["days"]
    assert max(d["p"] for d in tangla) > 0.9 and any(d["avalanche"] == "high" for d in tangla)   # the forecast storm
    assert all(d["avalanche"] is None for d in roads["s1"]["days"])                              # valley highway stays safe


def test_command_and_brief_need_key_when_set(client, monkeypatch):
    import app as rasad_app
    monkeypatch.setattr(rasad_app.cfg, "API_KEY", "secret")
    for path, js in (("/api/command", {"text": "alerts"}), ("/api/alerts/brief", {}), ("/api/reset", {})):
        assert client.post(path, json=js).status_code == 401
        assert client.post(path, json=js, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/command", json={"text": "alerts"}, headers={"X-API-Key": "secret"}).status_code == 200
    assert client.get("/api/bases").status_code == 200       # reads stay open


def test_cors_off_by_default(client):
    assert "Access-Control-Allow-Origin" not in client.get("/api/health").headers


def test_plan_respects_capacity_and_bridge_limit(client):
    import app as rasad_app
    client.post("/api/reset", json={})
    p = client.post("/api/plan", json={}).get_json()
    veh = {v["id"]: v for v in rasad_app.db.q("SELECT id, type, cap_kg FROM vehicles")}
    bridge = rasad_app.db.q("SELECT max_kg FROM roads WHERE id = 's5'", one=True)["max_kg"]
    assert p["trips"]
    on_bridge = 0
    for t in p["trips"]:
        assert t["kg"] <= veh[t["vehicle_id"]]["cap_kg"] + 1
        if veh[t["vehicle_id"]]["type"] == "truck" and any("s5" in l.get("roads", []) for l in t["legs"]):
            on_bridge += 1
            assert t["kg"] <= bridge + 1
    assert on_bridge, "no truck crosses the Kesari track, so the bridge limit is not exercised"


def test_partial_dispatch_keeps_unsent_trips(client):
    import app as rasad_app
    client.post("/api/reset", json={})
    p = client.post("/api/plan", json={}).get_json()
    vehicles = list(dict.fromkeys(t["vehicle_id"] for t in p["trips"]))
    if len(vehicles) < 2:
        pytest.skip("plan has a single vehicle")
    busy = vehicles[-1]
    rasad_app.db.x("UPDATE vehicles SET status = 'busy' WHERE id = ?", (busy,))
    rasad_app.db.commit()
    sent = client.post(f"/api/plan/{p['id']}/dispatch", json={}).get_json()["shipments"]
    waiting = [t for t in p["trips"] if t["vehicle_id"] == busy]
    assert len(sent) == len(p["trips"]) - len(waiting)
    assert client.get("/api/plan/latest").get_json()["status"] == "proposed"      # unsent trips can still go
    rasad_app.db.x("UPDATE vehicles SET status = 'idle' WHERE id = ?", (busy,))
    rasad_app.db.commit()
    later = client.post(f"/api/plan/{p['id']}/dispatch", json={}).get_json()["shipments"]
    assert len(later) == len(waiting)                                              # nothing is sent twice
    assert client.get("/api/plan/latest").get_json()["status"] == "dispatched"


def test_whatif_scenarios_change_nothing_and_measure_effect(client):
    client.post("/api/reset", json={})
    roads_before = client.get("/api/roads").get_json()
    plan_before = client.get("/api/plan/latest").get_json()
    listing = client.get("/api/whatif").get_json()
    assert {x["id"] for x in listing} >= {"today", "pass_closed", "air_grounded", "surge"}
    r = client.post("/api/whatif", json={"scenario": "air_grounded"}).get_json()
    assert r["changes"] and r["plan"]["helicopters"] == 0                      # no helicopter is planned once they are grounded
    assert r["old_plan"]["trips_lost"] >= 1                                    # grounded helicopters drop loads from the old plan
    assert r["after"]["expected_stockouts"] <= r["old_plan"]["expected_stockouts"] + 1e-9
    assert r["after"]["expected_stockouts"] < r["nothing"]["expected_stockouts"]
    assert r["verdict"]["id"] in ("replan", "reroute", "holds", "worse")
    assert client.get("/api/roads").get_json() == roads_before                  # the live sector is untouched
    assert client.get("/api/plan/latest").get_json() == plan_before              # no plan is saved either


def test_whatif_rejects_bad_input(client):
    assert client.post("/api/whatif", json={"scenario": "nope"}).status_code == 400
    assert client.post("/api/whatif", json={"close": ["zz"]}).status_code == 400
    assert client.post("/api/whatif", json={"surge": {"base": "BD", "pct": 50}}).status_code == 400
    assert client.post("/api/whatif", json={"close": ["s2"], "ground_helis": True}).status_code == 200


def test_walk_forward_error_is_out_of_sample(client):
    m = client.get("/api/forecast/metrics").get_json()["walk_forward"]
    assert len(m["folds"]) == 3 and all(f["from"] < f["to"] for f in m["folds"])
    assert 0 < m["wape"]["ens"] < m["wape"]["naive"]               # still beats last week's average without tuning on the window


def test_real_weather_replay_seeds_from_cache_or_download(tmp_path, monkeypatch):
    """Real-weather mode, with the Open-Meteo call replaced by a fake so no network is needed."""
    from datetime import date, timedelta
    import realdata
    import seed as seeder
    from db import DB

    def fake_get(url, **p):
        lo, hi = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
        days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        return {d.isoformat(): (7.0 if d.isoformat() == "2026-03-10" else 0.5, -3.0, 12.0) for d in days}

    monkeypatch.setenv("RASAD_REAL_DATA", "replay:2026-03-08")
    monkeypatch.setattr(realdata, "CACHE", str(tmp_path / "wx.json"))
    monkeypatch.setattr(realdata, "_get", fake_get)
    d = DB(f"sqlite:///{tmp_path}/real.db")
    seeder.seed(d)
    assert "replayed from 2025-11-08 to 2026-03-21" in d.q("SELECT value FROM meta WHERE key = 'weather_source'", one=True)["value"]
    assert d.q("SELECT COUNT(*) AS n FROM weather", one=True)["n"] == 4 * 134
    storm = d.q("SELECT snow_cm FROM weather WHERE zone = 'tangla' AND day = ?", ((date.today() + timedelta(days=2)).isoformat(),), one=True)
    assert storm["snow_cm"] == 7.0                                   # day 2 of the replay is 2026-03-10: the real weather, not random draws
    # a second seed reads the cache and does not call the service
    monkeypatch.setattr(realdata, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded again")))
    seeder.seed(DB(f"sqlite:///{tmp_path}/real2.db"))


def test_real_weather_failure_falls_back_to_synthetic(tmp_path, monkeypatch):
    import requests
    import realdata
    import seed as seeder
    from db import DB
    monkeypatch.setenv("RASAD_REAL_DATA", "live")
    monkeypatch.setattr(realdata, "CACHE", str(tmp_path / "none.json"))
    monkeypatch.setattr(realdata, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    d = DB(f"sqlite:///{tmp_path}/fb.db")
    seeder.seed(d)
    assert d.q("SELECT value FROM meta WHERE key = 'weather_source'", one=True)["value"] == "synthetic"


def test_helicopter_payload_falls_with_altitude(client, monkeypatch):
    import app as rasad_app
    from optimizer import heli_derate
    cfg = rasad_app.cfg
    assert heli_derate(3000, cfg) == 1.0 and heli_derate(4000, cfg) < 1.0 and heli_derate(9000, cfg) == cfg.HELI_DERATE_FLOOR
    client.post("/api/reset", json={})
    plan = client.post("/api/plan", json={}).get_json()
    helis = [t for t in plan["trips"] if t["type"] == "heli"]
    assert helis and plan["metrics"]["penalty"] == 0
    for t in helis:
        assert t["kg"] <= t["cap_kg"] + 1 and t["cap_kg"] < 1200                # thin air cuts the lift below the rating
        assert "thin air" in t["why"]
    monkeypatch.setattr(cfg, "HELI_DERATE_PER_KM", 0.0)                          # no derating: the full rating is available
    flat = client.post("/api/plan", json={}).get_json()
    assert all(t["cap_kg"] == 1200 for t in flat["trips"] if t["type"] == "heli")


def test_pyvrp_benchmark_plan_is_a_valid_rasad_plan(client):
    """The benchmark turns a PyVRP solution into a Rasad plan; with trucks capped at the bridge limit it must break no hard limit."""
    pytest.importorskip("pyvrp")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks"))
    import pyvrp_vs_ga as bench
    snap = bench.store.snapshot(bench.rasad.db)
    ctx = bench.opt.context(snap, None, bench.rasad.cfg, seed=0)
    genes, _ = bench.pyvrp_genes(ctx, seconds=1, cap_trucks=True)
    assert len(genes) == len(ctx["lots"])
    m = bench.opt.evaluate(genes, ctx)
    assert m["penalty"] == 0 and m["deferred"] < len(genes)


def test_requests_leave_no_open_transaction(client):
    """An open read transaction holds PostgreSQL table locks; a failed one breaks the connection for good."""
    import app as rasad_app
    for path in ("/api/bases", "/api/predict", "/api/hazards", "/api/plan/latest"):
        assert client.get(path).status_code == 200
        assert not rasad_app.db.in_transaction(), path


def _pg_only():
    url = os.environ.get("RASAD_TEST_DATABASE_URL", "")
    if not url.startswith(("postgres://", "postgresql://")):
        pytest.skip("needs RASAD_TEST_DATABASE_URL pointing at PostgreSQL")
    return url


def test_reset_is_not_blocked_by_another_threads_read(client):
    """Docker regression: a reader in another worker thread used to keep its transaction open, so DROP TABLE in
    /api/reset waited forever and every later request queued behind it."""
    _pg_only()
    import threading
    t = threading.Thread(target=lambda: client.get("/api/bases"))
    t.start()
    t.join(30)
    done = {}
    r = threading.Thread(target=lambda: done.setdefault("code", client.post("/api/reset", json={}).status_code))
    r.start()
    r.join(60)
    assert done.get("code") == 200, "reset did not finish within 60 s"


def test_workers_booting_together_seed_once(tmp_path):
    """Docker regression: gunicorn's workers each import app.py; on an empty database they used to seed at once and crash."""
    import subprocess
    import psycopg2
    url = _pg_only()
    base, name = url.rsplit("/", 1)
    fresh = f"{name}_boot"
    admin = psycopg2.connect(f"{base}/postgres")
    admin.autocommit = True
    admin.cursor().execute(f"DROP DATABASE IF EXISTS {fresh}")
    admin.cursor().execute(f"CREATE DATABASE {fresh}")
    try:
        env = {**os.environ, "DATABASE_URL": f"{base}/{fresh}"}
        backend = os.path.join(os.path.dirname(__file__), "..", "backend")
        procs = [subprocess.Popen([sys.executable, "-c", "import app"], cwd=backend, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        outs = [p.communicate(timeout=300) for p in procs]
        assert all(p.returncode == 0 for p in procs), [o[1].decode()[-500:] for o in outs]
        c = psycopg2.connect(f"{base}/{fresh}")
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM bases")
        assert cur.fetchone()[0] == 9
        c.close()
    finally:
        admin.cursor().execute(f"DROP DATABASE IF EXISTS {fresh} WITH (FORCE)")
        admin.close()


def test_readers_never_see_a_half_reset_sector(client):
    """Docker regression: readers in other threads used to hit an emptied database (500s) or deadlock with DROP TABLE
    while /api/reset ran. Now a reset swaps the data in one transaction, so every read succeeds."""
    _pg_only()
    import threading
    import time
    stop, errors = time.time() + 20, []

    def read():
        while time.time() < stop:
            for path in ("/api/predict", "/api/bases", "/api/hazards", "/api/alerts"):
                code = client.get(path).status_code
                if code != 200:
                    errors.append((path, code))

    readers = [threading.Thread(target=read) for _ in range(4)]
    for t in readers:
        t.start()
    resets = [client.post("/api/reset", json={}).status_code for _ in range(3)]
    for t in readers:
        t.join(120)
    assert resets == [200, 200, 200] and not errors, (resets, errors[:5])
