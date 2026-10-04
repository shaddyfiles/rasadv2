"""End-to-end API tests on a throwaway SQLite database.  Run from the repo root: pytest -q"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
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
