"""What-if scenarios: disrupt a copy of the live sector, plan the resupply, and measure what the plan buys.

For each scenario the engine
  1. copies the live snapshot and applies the disruption (roads closed, helicopters grounded, troop surge);
  2. measures the chance of stock-outs over 7 days with nothing new sent (Monte Carlo, predict.stockout_risk);
  3. runs the GA + ACO planner on the disrupted sector;
  4. adds the new plan's loads to the copy on their arrival dates and measures the chance again.

Between those two sits the plan made *before* the disruption: its loads that can still run (no closed road on the
route, helicopter not grounded) are added instead, which shows what the disruption does to a plan already made.
Nothing is written to the database.
"""
import copy

import forecast as fc
import optimizer
import predict
import store

PRESETS = {
    "today": {"label": "Today, as forecast", "text": "No disruption: the plan for the sector as it stands.", "close": []},
    "pass_closed": {"label": "Tangla La closes", "text": "The Tangla La road between the two forward depots shuts under snow.", "close": ["s2"]},
    "both_passes": {"label": "Both passes close", "text": "Tangla La and Zarla La both shut, so the Dhruv posts can only be reached by air.", "close": ["s2", "s3"]},
    "air_grounded": {"label": "Passes shut, helicopters grounded", "text": "Both passes are closed and weather grounds every helicopter.", "close": ["s2", "s3"], "ground_helis": True},
    "surge": {"label": "Troop surge at Kesari (+60%)", "text": "Post Kesari's strength rises by 60%, so its daily use rises with it.", "close": [], "surge": {"base": "P2", "pct": 60}},
}


def _apply(db, snap, params):
    """Disrupt `snap` in place. Returns the list of things changed, in words."""
    done = []
    names = {r["id"]: r["name"] for r in snap["roads"]}
    for rid in params.get("close", []):
        for r in snap["roads"]:
            if r["id"] == rid:
                r["status"] = "closed"
        done.append(f"{names[rid]} closed")
    if params.get("ground_helis"):
        snap["vehicles"] = [v for v in snap["vehicles"] if v["type"] != "heli"]
        done.append("helicopters grounded")
    s = params.get("surge")
    if s:
        b = snap["bases"][s["base"]]
        b["strength"] = round(b["strength"] * (1 + s["pct"] / 100))
        models = fc.train(db)
        for it in snap["items"]:
            b["forecast"][it] = fc.forecast(db, b, it, models=models)
            b["cover"][it] = fc.cover(b["stock"][it], b["forecast"][it], b["inbound_days"].get(it, []))
        done.append(f"{b['name']} strength {b['strength']}")
    return done


def _load(snap, trips):
    """A copy of `snap` with these trips' loads added on their arrival dates."""
    out = copy.deepcopy(snap)
    for t in trips:
        for d in t["drops"]:
            for line in d["lines"]:
                out["bases"][d["base_id"]]["inbound_days"].setdefault(line["item"], []).append((d["eta"], line["qty"]))
    return out


def _survives(trip, snap):
    closed = {r["id"] for r in snap["roads"] if r["status"] == "closed"}
    flying = {v["id"] for v in snap["vehicles"]}
    return trip["vehicle_id"] in flying and not any(r in closed for l in trip["legs"] for r in l.get("roads", []))


def _risk(snap):
    rows = predict.stockout_risk(snap)["rows"]
    at_risk = {r["base_id"] for r in rows if r["p7"] >= 0.5}
    return {"expected_stockouts": round(sum(r["p7"] for r in rows), 2), "posts_at_risk": len(at_risk),
            "worst": [{"base": r["base"], "item": r["item"], "p7": round(r["p7"], 3)} for r in rows[:5]]}


def verdict(nothing, old, lost, after):
    """One plain-words reading of the three numbers (expected stock-outs in 7 days)."""
    if after["expected_stockouts"] > old["expected_stockouts"] + 0.05:
        return {"id": "worse", "text": "The new plan leaves more stock-outs than the old one. Review it before sending."}
    n = f"{lost} load{'s' if lost != 1 else ''}"
    if old["expected_stockouts"] - after["expected_stockouts"] > 0.05:
        why = f"The old plan loses {n}" if lost else "Demand has risen"
        return {"id": "replan", "text": f"Plan again. {why}, and a new plan cuts expected stock-outs from {old['expected_stockouts']:.1f} to {after['expected_stockouts']:.1f}."}
    if lost:
        return {"id": "reroute", "text": f"The old plan loses {n}, but a new plan covers {'it' if lost == 1 else 'them'} as well."}
    return {"id": "holds", "text": "The plan you already have still works."}


def clean(params):
    """Check a scenario request. Returns (params, label, text) or raises ValueError."""
    if "scenario" in params:
        p = PRESETS.get(params["scenario"])
        if not p:
            raise ValueError("unknown scenario")
        return p, p["label"], p["text"]
    p = {"close": list(params.get("close", [])), "ground_helis": bool(params.get("ground_helis")), "surge": params.get("surge")}
    return p, "Custom scenario", "Custom disruption."


def run(db, cfg, params, seed=0):
    p, label, text = clean(params)
    live = store.snapshot(db)
    ids = {r["id"] for r in live["roads"]}
    if any(r not in ids for r in p.get("close", [])):
        raise ValueError("unknown road in scenario")
    if p.get("surge") and (p["surge"].get("base") not in live["bases"] or live["bases"][p["surge"]["base"]]["kind"] != "post"):
        raise ValueError("surge needs a forward post")
    original = optimizer.plan(copy.deepcopy(live), None, cfg, seed=seed)       # the plan made before the disruption
    snap = copy.deepcopy(live)
    changes = _apply(db, snap, p)
    nothing = _risk(snap)
    kept = [t for t in original["trips"] if _survives(t, snap)]
    old = _risk(_load(snap, kept))
    plan = optimizer.plan(snap, None, cfg, seed=seed)
    after = _risk(_load(snap, plan["trips"]))
    trips = plan["trips"]
    return {
        "label": label, "text": text, "changes": changes,
        "nothing": nothing, "old_plan": {**old, "trips_kept": len(kept), "trips_lost": len(original["trips"]) - len(kept)}, "after": after,
        "verdict": verdict(nothing, old, len(original["trips"]) - len(kept), after),
        "plan": {"trips": len(trips), "trucks": sum(t["type"] == "truck" for t in trips), "helicopters": sum(t["type"] == "heli" for t in trips),
                 "tonnes": round(sum(t["kg"] for t in trips) / 1000, 1), "late": sum(bool(t["late"]) for t in trips),
                 "held": sum(len(v) for v in plan["deferred"].values()), "cost": round(plan["metrics"]["cost"], 1),
                 "gain_over_rules": plan["gain"]},
    }
