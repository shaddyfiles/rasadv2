"""Record real API responses from a fresh seeded sector, for the clickable demo.

Run from the repo root:  python frontend/demo/capture.py   (writes frontend/demo/demo-data.json)
The demo page replays these responses in the browser, so it needs no server.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend"))
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/demo.db"

import app as rasad  # noqa: E402

c = rasad.app.test_client()


def get(path):
    r = c.get("/api" + path)
    assert r.status_code == 200, (path, r.status_code)
    return r.get_json()


def post(path, body=None):
    r = c.post("/api" + path, json=body or {})
    assert r.status_code in (200, 201), (path, r.status_code, r.get_data(as_text=True)[:200])
    return r.get_json()


def views():
    """Every GET the website makes that can change when stock or shipments change."""
    out = {p: get(p) for p in ["/health", "/map", "/bases", "/roads", "/shipments", "/shipments?all=1", "/predict", "/plan/latest", "/alerts", "/hazards"]}
    for b in out["/bases"]:
        out[f"/bases/{b['id']}"] = get(f"/bases/{b['id']}")
    return out


post("/reset")
state = views()
forecasts = {}
for b in state["/bases"]:
    if b["kind"] == "post":
        for item in ["ration", "fuel", "ammo", "med", "spares"]:
            forecasts[f"/forecast/{b['id']}/{item}"] = get(f"/forecast/{b['id']}/{item}")
brief = post("/alerts/brief")

PHRASES = ["Which posts are short?", "Status of Trishul", "Status of Hima", "Status of Kesari", "Status of Vajra", "Status of Garud", "Status of Agni", "Fuel forecast for Garud",
           "Fuel forecast for Trishul", "Alerts", "Close Tangla road", "Open Tangla road", "Set fuel at Trishul to 500",
           "Used 80 L of fuel at Vajra", "Strength at Kesari to 120", "Risk on Kesari ridge to 70%", "Plan resupply", "Dispatch",
           "what is the weather"]
commands = {}
for ph in PHRASES:
    r = post("/command", {"text": ph, "history": []})
    commands[ph] = {k: r[k] for k in ("reply", "actions", "tools", "mode")}

VARIANTS = {"normal": {"speed": 1, "safety": 1, "economy": 1}, "speed": {"speed": 3, "safety": 1, "economy": 1},
            "safety": {"speed": 1, "safety": 3, "economy": 1}, "economy": {"speed": 1, "safety": 1, "economy": 3}}
plans = {}
for name, w in VARIANTS.items():
    post("/reset")
    p = post("/plan", {"weights": w, "seed": 7})
    d = post(f"/plan/{p['id']}/dispatch")
    plans[name] = {"plan": {**p, "status": "proposed"}, "dispatch": d, "after": views()}

post("/reset")
whatif = {"list": get("/whatif"), "results": {x["id"]: post("/whatif", {"scenario": x["id"]}) for x in get("/whatif")}}

data = {"recorded": state["/health"]["today"], "state": state, "forecasts": forecasts, "brief": brief,
        "commands": commands, "plans": plans, "whatif": whatif}
path = os.path.join(HERE, "demo-data.json")
with open(path, "w") as f:
    json.dump(data, f, separators=(",", ":"))
print(path, os.path.getsize(path) // 1024, "KB")
