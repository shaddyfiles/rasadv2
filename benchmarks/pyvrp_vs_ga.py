"""Benchmark: Rasad's GA + ACO planner against PyVRP (hybrid genetic search), on the same resupply problems.

    python benchmarks/pyvrp_vs_ga.py            # writes benchmarks/results.md and results.json

Every method's answer is scored by Rasad's own cost function (optimizer.evaluate), so the numbers are comparable:
10 x lateness + speed x transit days + safety x route risk + economy x vehicles + penalties (capacity, bridge limit,
depot stock). Lower is better.

Methods
  rules      the rule-based plan (one vehicle per destination, own depot first)
  GA+ACO     Rasad's planner (seeded with the rule-based plan)
  PyVRP      PyVRP on the same lots and vehicles, then converted to a Rasad plan
  PyVRP cap  the same, with every truck's capacity cut to the lowest bridge limit on the open roads, which makes the
             bridge limit hold at the price of wasted truck space
  PyVRP+GA   Rasad's genetic algorithm started from the capped PyVRP answer

How the problem is given to PyVRP (and where it does not fit):
  * each supply lot is an optional delivery whose prize is Rasad's cost of holding it back;
  * each vehicle is a vehicle type that starts at its home depot and ends at a dummy depot, so no return trip is charged
    (Rasad does not charge one either); trucks and helicopters use different travel costs (road routes found by the ant
    colony, or straight flights), and a truck from one depot is barred from lots it may not serve;
  * a helicopter's capacity is derated at the highest post it could serve, which is stricter than Rasad's per-sortie rule;
  * PyVRP cannot express the 2.5 t bridge limit or depot stock, and has no soft lateness term. Rasad's cost function
    penalises both when it scores PyVRP's answer. Deadlines enter as time windows that are never tighter than the
    fastest possible arrival.
"""
import copy
import json
import math
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/bench.db")
os.environ.pop("RASAD_REAL_DATA", None)

import app as rasad                      # noqa: E402
import optimizer as opt                  # noqa: E402
import scenarios                         # noqa: E402
import store                             # noqa: E402
from db import haversine                 # noqa: E402
from pyvrp import Model                  # noqa: E402
from pyvrp.stop import MaxRuntime        # noqa: E402

SCALE = 100            # PyVRP wants integers: costs and days are in hundredths
BIG = 10 ** 7
PYVRP_SECONDS = 3
NAMES = ["rules", "GA+ACO", "PyVRP", "PyVRP cap", "PyVRP+GA"]


def deferral_cost(lot):
    """What Rasad charges for holding a lot back until tomorrow (see optimizer.evaluate)."""
    return 10 * lot["w"] * (max(0.0, 1 + lot["lead"] - lot["deadline"]) * (3 if lot["urgent"] else 1) + 0.3 * max(0.0, 7 - lot["deadline"]) + 0.05)


def pyvrp_genes(ctx, seconds=PYVRP_SECONDS, seed=0, cap_trucks=False):
    lots, V, router, snap, W, cfg = ctx["lots"], ctx["V"], ctx["router"], ctx["snap"], ctx["W"], ctx["cfg"]
    if not lots:
        return [], 0.0
    vids = list(V)
    homes = sorted({V[v]["home"] for v in vids})
    top = max(snap["bases"][l["to"]]["alt_m"] for l in lots)
    bridge = min([r["max_kg"] for r in snap["roads"] if r["max_kg"] and r["status"] != "closed"] or [math.inf])
    m = Model()
    depot_loc = {h: m.add_location(0, 0, name=f"depot {h}") for h in homes}
    end_loc = m.add_location(0, 0, name="end")
    lot_loc = [m.add_location(0, 0, name=f"lot {i}") for i in range(len(lots))]
    for h in homes:
        m.add_depot(depot_loc[h])
    m.add_depot(end_loc)

    def leg(vehicle, a, b):
        """(cost, duration) in hundredths for a vehicle going from base a to base b, or None if it cannot."""
        if a == b:
            return 0, 0
        if vehicle["type"] == "heli":
            days = haversine(*snap["bases"][a]["lonlat"], *snap["bases"][b]["lonlat"]) / opt.HELI_KMH / 24 + 0.05
            return round(SCALE * (W["speed"] * days + W["safety"] * 0.1)), round(SCALE * days)
        r = router.route(a, b)
        if not r:
            return None
        return round(SCALE * (W["speed"] * r["days"] + W["safety"] * r["risk"])), round(SCALE * r["days"])

    profiles = {}
    for vid in vids:
        veh = V[vid]
        prof = m.add_profile(name=vid)
        profiles[vid] = prof
        nodes = [("depot", h, depot_loc[h]) for h in homes] + [("lot", i, lot_loc[i]) for i in range(len(lots))]
        for ka, ia, la in nodes:
            m.add_edge(la, end_loc, 0, 0, profile=prof)
            for kb, ib, lb in nodes:
                if kb == "depot":
                    continue                                   # nothing returns to a depot
                if ka == "lot" and ia == ib:
                    continue
                base_a = ia if ka == "depot" else lots[ia]["to"]
                cost = leg(veh, base_a, lots[ib]["to"]) if vid in ctx["opts"][ib] else None
                m.add_edge(la, lb, *(cost if cost else (BIG, BIG)), profile=prof)
    for i, lot in enumerate(lots):
        direct = [leg(V[v], V[v]["home"], lot["to"]) for v in ctx["opts"][i]]
        direct = [d[1] for d in direct if d]
        horizon = max(round(SCALE * lot["deadline"]), (min(direct) if direct else 0) + 5)
        m.add_client(lot_loc[i], delivery=[math.ceil(lot["kg"])], required=False, prize=round(SCALE * deferral_cost(lot)),
                     tw_late=min(horizon, 10 ** 6), name=f"lot {i}")
    for vid in vids:
        veh = V[vid]
        cap = veh["cap_kg"] * (opt.heli_derate(max(top, snap["bases"][veh["home"]]["alt_m"]), cfg) if veh["type"] == "heli" else 1)
        if cap_trucks and veh["type"] == "truck":
            cap = min(cap, bridge)
        m.add_vehicle_type(1, capacity=[int(cap)], start_depot=m.depots[homes.index(veh["home"])], end_depot=m.depots[-1],
                           fixed_cost=round(SCALE * W["economy"] * (2.5 if veh["type"] == "heli" else 1.0)), profile=profiles[vid], name=vid)
    t = time.time()
    res = m.solve(stop=MaxRuntime(seconds), seed=seed, display=False)
    took = time.time() - t
    genes = [(-1, 0.0)] * len(lots)
    for route in res.best.routes():
        vid = vids[route.vehicle_type()]
        stops = [a.idx for a in route.schedule() if a.is_client()]          # a client's idx is its position among the clients, i.e. its lot number
        for pos, i in enumerate(stops):
            if vid in ctx["opts"][i]:
                genes[i] = (ctx["opts"][i].index(vid), (pos + 1) / (len(lots) + 1))
    return genes, took


def instance(snap, params):
    s = copy.deepcopy(snap)
    scenarios._apply(rasad.db, s, params)
    return s


def run(seeds=(0, 1, 2)):
    live = store.snapshot(rasad.db)
    rows = []
    for key, p in scenarios.PRESETS.items():
        for sd in seeds:
            snap = instance(live, p)
            ctx = opt.context(snap, None, rasad.cfg, seed=sd)
            if not ctx["lots"]:
                continue
            t = time.time()
            base_g = opt.baseline(ctx)
            ga_g, _ = opt.genetic(ctx, base_g, rasad.cfg.GA_POP, rasad.cfg.GA_GENS, random.Random(sd + 101))
            ga_t = time.time() - t
            pv_g, pv_t = pyvrp_genes(ctx, seed=sd)
            pc_g, _ = pyvrp_genes(ctx, seed=sd, cap_trucks=True)
            hy_g, _ = opt.genetic(ctx, pc_g, rasad.cfg.GA_POP, rasad.cfg.GA_GENS, random.Random(sd + 101))
            row = {"scenario": p["label"], "seed": sd, "lots": len(ctx["lots"]), "seconds": {"GA+ACO": round(ga_t, 2), "PyVRP": round(pv_t, 2)}}
            for name, g in (("rules", base_g), ("GA+ACO", ga_g), ("PyVRP", pv_g), ("PyVRP cap", pc_g), ("PyVRP+GA", hy_g)):
                row[name] = opt.evaluate(g, ctx)
            rows.append(row)
            print(f"{p['label'][:34]:34} seed {sd}: " + "  ".join(f"{n} {row[n]['cost']:7.1f}" for n in NAMES), flush=True)
    return rows


def report(rows):
    names = NAMES
    mean = {n: sum(r[n]["cost"] for r in rows) / len(rows) for n in names}
    wins = {n: sum(r[n]["cost"] <= min(r[x]["cost"] for x in names) + 1e-9 for r in rows) for n in names}
    pen = {n: sum(r[n]["penalty"] > 0 for r in rows) for n in names}
    out = ["# PyVRP vs Rasad's GA + ACO", "",
           f"{len(rows)} problems: {len(scenarios.PRESETS)} scenarios x {len(rows) // len(scenarios.PRESETS)} random seeds, on the seeded synthetic sector. "
           "Cost is Rasad's own (lower is better), applied to every method's plan. See the top of `pyvrp_vs_ga.py` for how the problem is given to PyVRP.", "",
           "| Method | Mean cost | Best on (of N) | Plans with a hard-limit penalty |", "|---|---:|---:|---:|"]
    out += [f"| {n} | {mean[n]:.2f} | {wins[n]} | {pen[n]} |" for n in names]
    out += ["", f"Run time per problem: GA+ACO about {sum(r['seconds']['GA+ACO'] for r in rows) / len(rows):.1f} s (including the rules), PyVRP {PYVRP_SECONDS} s (its time budget).", "",
            "| Scenario | Seed | Lots | " + " | ".join(names) + " |", "|---|---:|---:|" + "---:|" * len(names)]
    out += [f"| {r['scenario']} | {r['seed']} | {r['lots']} | " + " | ".join(f"{r[n]['cost']:.1f}" + ("*" if r[n]["penalty"] > 0 else "") for n in names) + " |" for r in rows]
    out += ["", "`*` = the plan breaks a hard limit (vehicle capacity, bridge limit or depot stock) and is charged a penalty."]
    return "\n".join(out) + "\n", mean


if __name__ == "__main__":
    rows = run()
    text, mean = report(rows)
    with open(os.path.join(HERE, "results.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print("\n" + text)
