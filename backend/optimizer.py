"""(3) Meta-heuristic engine: ant colony routing + genetic algorithm dispatch.

1. Requirements: each post's forecast, stock and lead time give supply lots
   (urgent top-ups split from routine stocking). Depots are refilled from the base.
2. ACO finds the best road route between any two bases. Closed roads are removed;
   cost = driving time + safety weight x (closure risk + hostile exposure).
3. GA assigns every lot to a vehicle (truck, helicopter or "defer") and orders the
   drops with random keys. Cost = 10 x lateness + speed x vehicle-days
   + safety x route risk + economy x vehicles/underfill + penalties
   (capacity, bridge load class, depot stock, unreachable).
The rule-based plan (one vehicle per destination, own depot first) seeds the GA
and is reported as the baseline.
"""
import json
import math
import random
from datetime import date, timedelta

from db import haversine, jload

DRIVE_HOURS = 10        # driving hours per day in the mountains
HELI_KMH = 180


def _day(offset):
    return (date.today() + timedelta(days=math.floor(offset))).isoformat()


# ------------------------------------------------------------------ ACO
class Router:
    def __init__(self, roads, w_safety, ants, iters, seed=1):
        self.roads = [r for r in roads if r["status"] != "closed"]
        self.adj = {}
        for r in self.roads:
            self.adj.setdefault(r["a"], []).append(r)
            self.adj.setdefault(r["b"], []).append(r)
        self.w, self.ants, self.iters = w_safety, ants, iters
        self.rng = random.Random(seed)
        self.cache = {}

    @staticmethod
    def days(r):
        return r["km"] / r["speed_kmh"] / DRIVE_HOURS + 0.1

    def cost(self, r):
        return self.days(r) + 0.5 * self.w * (r["risk"] + r["exposure"])

    def route(self, frm, to):
        if frm == to:
            return {"roads": [], "days": 0.0, "risk": 0.0, "pheromone": {}}
        key = (frm, to)
        if key not in self.cache:
            self.cache[key] = self._aco(frm, to)
        return self.cache[key]

    def _aco(self, frm, to):
        tau = {r["id"]: 1.0 for r in self.roads}
        best = None
        for _ in range(self.iters):
            sols = []
            for _a in range(self.ants):
                u, seen, path = frm, {frm}, []
                while u != to and len(path) < 10:
                    cand = [(r, r["b"] if r["a"] == u else r["a"]) for r in self.adj.get(u, [])]
                    cand = [(r, v) for r, v in cand if v not in seen]
                    if not cand:
                        break
                    wts = [tau[r["id"]] * (1 / self.cost(r)) ** 2.5 for r, _ in cand]
                    x = self.rng.random() * sum(wts)
                    for (r, v), wt in zip(cand, wts):
                        x -= wt
                        if x <= 0:
                            break
                    path.append(r)
                    u = v
                    seen.add(u)
                if u == to:
                    c = sum(self.cost(r) for r in path)
                    sols.append((c, path))
                    if best is None or c < best[0]:
                        best = (c, path)
            for k in tau:
                tau[k] = max(0.05, tau[k] * 0.7)
            for c, path in sols:
                for r in path:
                    tau[r["id"]] += 1 / c
            if best:
                for r in best[1]:
                    tau[r["id"]] += 2 / best[0]
        if not best:
            return None
        path = best[1]
        return {"roads": [r["id"] for r in path], "days": sum(self.days(r) for r in path),
                "risk": sum(r["risk"] + r["exposure"] for r in path), "max_kg": min([r["max_kg"] for r in path if r["max_kg"]] or [math.inf]),
                "mules": any(r["mode"] == "animal" for r in path), "pheromone": {k: round(v, 3) for k, v in tau.items()}}


# ------------------------------------------------------------------ requirements
def requirements(snap, router):
    lots = []

    def add(to, item, q, deadline, urgent, src, why, lead=1.0):
        kg = snap["items"][item]["kg_per_unit"]
        size = 900 if urgent else 2000
        n = max(1, math.ceil(q * kg / size))
        for k in range(n):
            qq = round(q / n, 1)
            lots.append({"id": len(lots), "to": to, "item": item, "q": qq, "kg": qq * kg, "deadline": deadline, "urgent": urgent,
                         "w": snap["items"][item]["criticality"], "srcs": src, "why": why, "lead": lead})

    for b in snap["bases"].values():
        if b["kind"] != "post":
            continue
        r = router.route(b["depot_id"], b["id"])
        lead = r["days"] if r else 15.0
        stocking = r and any(x["risk"] >= 0.4 for x in snap["roads"] if x["id"] in r["roads"])
        for item, fc in b["forecast"].items():
            m = sum(f["p50"] for f in fc[:7]) / 7
            if m <= 0:
                continue
            sig = sum(f["p90"] - f["p10"] for f in fc[:7]) / 7 / 2.56
            have = b["stock"][item] + b["inbound"].get(item, 0)
            L = min(lead, 12) + 7      # lead time + weekly review period
            rop = m * L + 1.65 * sig * math.sqrt(L)
            target = 25 if stocking else 20
            if have >= rop and not (stocking and have / m < 15):
                continue
            q = target * m + m * min(lead, 5) - have
            if q <= 0:
                continue
            cov = b["cover"][item]
            stockout = cov if cov is not None else 30
            srcs = list(dict.fromkeys([b["depot_id"], "FD1"]))
            label = f"{b['name']} has {b['stock'][item] / m:.1f} days of {snap['items'][item]['name'].split(' (')[0].lower()} left"
            if b["stock"][item] / m < lead + 0.5:
                qu = min(q, m * 10)
                add(b["id"], item, qu, stockout, True, srcs, label + f" and the road takes {lead:.1f} days", lead)
                if q - qu > 0:
                    add(b["id"], item, q - qu, stockout + 8, False, srcs, label, lead)
            else:
                add(b["id"], item, q, max(0.5, stockout - 1), False, srcs, label + ("; the route is risky, so stocking for 25 days" if stocking else ""), lead)
    for d in snap["bases"].values():
        if d["kind"] != "depot":
            continue
        served = [b for b in snap["bases"].values() if b.get("depot_id") == d["id"] and b["kind"] == "post"]
        for item in snap["items"]:
            m = sum(sum(f["p50"] for f in b["forecast"][item][:7]) / 7 for b in served)
            if m <= 0:
                continue
            have = d["stock"][item] + d["inbound"].get(item, 0)
            if have / m >= 15:
                continue
            add(d["id"], item, 20 * m - have, 6, False, ["BD"] if d["id"] == "FD1" else ["FD1", "BD"],
                f"{d['name']} holds {d['stock'][item] / m:.1f} days of {snap['items'][item]['name'].split(' (')[0].lower()} for its posts")
    return lots


# ------------------------------------------------------------------ evaluation
def evaluate(genes, ctx, build=False):
    lots, opts, V, router, snap, W = ctx["lots"], ctx["opts"], ctx["V"], ctx["router"], ctx["snap"], ctx["W"]
    late = transit = risk = econ = pen = 0.0
    by_v, deferred, use = {}, [], {}
    for i, (v, key) in enumerate(genes):
        lot = lots[i]
        if v < 0:
            deferred.append(lot)
            # holding a lot until tomorrow: late if tomorrow's road delivery misses the deadline,
            # plus a small charge for running a post below a week of cover
            late += lot["w"] * (max(0.0, 1 + lot["lead"] - lot["deadline"]) * (3 if lot["urgent"] else 1)
                                + 0.3 * max(0.0, 7 - lot["deadline"]) + 0.05)
            continue
        by_v.setdefault(opts[i][v], []).append((lot, key))
    trips = []
    for vid, lst in by_v.items():
        veh = V[vid]
        stops = {}
        for lot, key in lst:
            s = stops.setdefault(lot["to"], {"to": lot["to"], "key": key, "lots": []})
            s["key"] = min(s["key"], key)
            s["lots"].append(lot)
            use[(veh["home"], lot["item"])] = use.get((veh["home"], lot["item"]), 0) + lot["q"]
        stops = sorted(stops.values(), key=lambda s: s["key"])
        kg = sum(l["kg"] for l, _ in lst)
        pen += max(0.0, kg - veh["cap_kg"]) / 2
        t, here, rem, legs, rr = 0.0, veh["home"], kg, [], 0.0
        for s in stops:
            if veh["type"] == "heli":
                a, b = snap["bases"][here]["lonlat"], snap["bases"][s["to"]]["lonlat"]
                dt = haversine(*a, *b) / HELI_KMH / 24 + 0.05
                legs.append({"heli": True, "from": here, "to": s["to"]})
                rr += 0.1
            else:
                r = router.route(here, s["to"])
                if not r:
                    pen += 200
                    dt = 15
                else:
                    dt = r["days"]
                    rr += r["risk"]
                    if r["max_kg"] != math.inf and rem > r["max_kg"]:
                        pen += (rem - r["max_kg"]) / 2
                    legs.append({"from": here, "to": s["to"], "roads": r["roads"]})
            t += dt
            s["eta"] = t
            for lot in s["lots"]:
                late += lot["w"] * max(0.0, t - lot["deadline"]) * (3 if lot["urgent"] else 1)
            rem -= sum(l["kg"] for l in s["lots"])
            here = s["to"]
        if veh["type"] == "heli" and len(stops) > 2:
            pen += 40 * (len(stops) - 2)
        transit += t
        risk += rr
        econ += (2.5 if veh["type"] == "heli" else 1.0) + 0.8 * (1 - min(1.0, kg / veh["cap_kg"]))
        if build:
            trips.append({"vehicle": veh, "kg": kg, "days": t, "stops": stops, "legs": legs, "risk": rr})
    for (home, item), q in use.items():
        have = snap["bases"][home]["stock"][item]
        if q > have:
            pen += (q - have) * snap["items"][item]["kg_per_unit"] / 2
    cost = 10 * late + W["speed"] * transit + W["safety"] * risk + W["economy"] * econ + pen
    m = {"cost": round(cost, 2), "lateness": round(late, 2), "transit_days": round(transit, 2), "risk": round(risk, 2),
         "vehicles": len(by_v), "penalty": round(pen, 2), "deferred": len(deferred)}
    return (m, trips, deferred) if build else m


def baseline(ctx):
    lots, opts, V = ctx["lots"], ctx["opts"], ctx["V"]
    genes = [(-1, 0.0)] * len(lots)
    load, dest, used = {}, {}, {}
    order = sorted(range(len(lots)), key=lambda i: lots[i]["deadline"])
    for rank, i in enumerate(order):
        lot = lots[i]
        prefer = [v for v in opts[i] if V[v]["type"] == "heli"] if lot["urgent"] else []
        prefer += [v for s in lot["srcs"] for v in opts[i] if V[v]["type"] == "truck" and V[v]["home"] == s]
        for vid in prefer:
            veh = V[vid]
            r = ctx["router"].route(veh["home"], lot["to"]) if veh["type"] == "truck" else True
            cap = min(veh["cap_kg"], r["max_kg"]) if veh["type"] == "truck" and r else veh["cap_kg"]
            k = (veh["home"], lot["item"])
            if not r or load.get(vid, 0) + lot["kg"] > cap or dest.get(vid, lot["to"]) != lot["to"] or \
                    ctx["snap"]["bases"][veh["home"]]["stock"][lot["item"]] - used.get(k, 0) < lot["q"]:
                continue
            load[vid] = load.get(vid, 0) + lot["kg"]
            dest[vid] = lot["to"]
            used[k] = used.get(k, 0) + lot["q"]
            genes[i] = (opts[i].index(vid), rank / len(lots))
            break
    return genes


def genetic(ctx, seed_genes, pop_size, gens, rng):
    n = len(seed_genes)
    if not n:
        return seed_genes, []
    opts, lots = ctx["opts"], ctx["lots"]
    fit = lambda g: evaluate(g, ctx)["cost"]  # noqa: E731

    def mutate(g):
        g = list(g)
        for _ in range(max(1, round(n * 0.04))):
            i = rng.randrange(n)
            v, k = g[i]
            r = rng.random()
            if r < 0.45:      # reassign vehicle or defer
                v = rng.randrange(len(opts[i])) if opts[i] and rng.random() > 0.1 else -1
            elif r < 0.8:     # consolidate: ride with another lot for the same destination
                peers = [opts[i].index(opts[j][g[j][0]]) for j in range(n)
                         if j != i and g[j][0] >= 0 and lots[j]["to"] == lots[i]["to"] and opts[j][g[j][0]] in opts[i]]
                if peers:
                    v = rng.choice(peers)
            else:             # reorder drops
                k = min(1.0, max(0.0, k + rng.uniform(-0.25, 0.25)))
            g[i] = (v, k)
        return g

    pop = [(seed_genes, fit(seed_genes))] + [(g, fit(g)) for g in (mutate(seed_genes) for _ in range(5))]
    while len(pop) < pop_size:
        g = [((rng.randrange(len(opts[i])) if opts[i] and rng.random() > 0.1 else -1), rng.random()) for i in range(n)]
        pop.append((g, fit(g)))
    hist = []
    for _ in range(gens):
        pop.sort(key=lambda p: p[1])
        hist.append(round(pop[0][1], 2))
        nxt = pop[:2]
        while len(nxt) < pop_size:
            a = min(rng.sample(pop, 3), key=lambda p: p[1])
            b = min(rng.sample(pop, 3), key=lambda p: p[1])
            child = [a[0][i] if rng.random() < 0.5 else b[0][i] for i in range(n)]
            child = mutate(child)
            nxt.append((child, fit(child)))
        pop = nxt
    pop.sort(key=lambda p: p[1])
    hist.append(round(pop[0][1], 2))
    return pop[0][0], hist


# ------------------------------------------------------------------ public entry point
def plan(snap, weights, cfg, seed=0):
    W = {"speed": 1.0, "safety": 1.0, "economy": 1.0, **(weights or {})}
    router = Router(snap["roads"], W["safety"], cfg.ACO_ANTS, cfg.ACO_ITERS, seed=seed + 11)
    lots = requirements(snap, router)
    V = {v["id"]: v for v in snap["vehicles"] if v["status"] == "idle"}
    opts = [[vid for vid, v in V.items() if (v["type"] == "truck" and v["home"] in lot["srcs"]) or
             (v["type"] == "heli" and snap["bases"][lot["to"]]["kind"] == "post")] for lot in lots]
    ctx = {"lots": lots, "opts": opts, "V": V, "router": router, "snap": snap, "W": W}
    base_genes = baseline(ctx)
    base_m = evaluate(base_genes, ctx)
    best, hist = genetic(ctx, base_genes, cfg.GA_POP, cfg.GA_GENS, random.Random(seed + 101))
    m, trips, deferred = evaluate(best, ctx, build=True)

    names = {b["id"]: b["name"] for b in snap["bases"].values()}
    road_names = {r["id"]: r["name"] for r in snap["roads"]}
    out = []
    for tp in sorted(trips, key=lambda t: min(l["deadline"] for s in t["stops"] for l in s["lots"])):
        veh = tp["vehicle"]
        drops = []
        for s in tp["stops"]:
            agg = {}
            for l in s["lots"]:
                agg[l["item"]] = round(agg.get(l["item"], 0) + l["q"], 1)
            drops.append({"base_id": s["to"], "base": names[s["to"]], "eta_days": round(s["eta"], 2), "eta": _day(s["eta"]),
                          "lines": [{"item": k, "qty": v} for k, v in agg.items()]})
        allots = [l for s in tp["stops"] for l in s["lots"]]
        first = min(allots, key=lambda l: l["deadline"])
        urgent = any(l["urgent"] for l in allots)
        late = any(s["eta"] > l["deadline"] for s in tp["stops"] for l in s["lots"])
        why = first["why"] + "."
        if veh["type"] == "heli":
            why += " By road it would arrive after the stock runs out, so it goes by helicopter." if urgent else " A helicopter is faster and one was free."
        if len(drops) > 1:
            why += " One vehicle makes both drops." if len(drops) == 2 else f" One vehicle makes all {len(drops)} drops."
        if any(road_names.get(r) and next(x for x in snap["roads"] if x["id"] == r)["exposure"] >= 0.5 for l in tp["legs"] for r in l.get("roads", [])):
            why += " The route crosses a track under observation."
        out.append({"id": len(out) + 1, "vehicle_id": veh["id"], "vehicle": veh["name"], "type": veh["type"], "from": veh["home"],
                    "from_name": names[veh["home"]], "kg": round(tp["kg"]), "fill_pct": round(100 * tp["kg"] / veh["cap_kg"]),
                    "days": round(tp["days"], 2), "priority": "flash" if urgent or late else "routine", "late": late,
                    "legs": tp["legs"], "route": " → ".join(dict.fromkeys(road_names[r] for l in tp["legs"] for r in l.get("roads", []))) or "Direct flight",
                    "drops": drops, "why": why})
    pher = {}
    for (a, b), r in router.cache.items():
        if r:
            for k, v in r["pheromone"].items():
                pher[k] = max(pher.get(k, 0), v)
    deferred_out = {}
    for l in deferred:
        deferred_out.setdefault(names[l["to"]], {}).setdefault(l["item"], 0)
        deferred_out[names[l["to"]]][l["item"]] = round(deferred_out[names[l["to"]]][l["item"]] + l["q"], 1)
    gain = (base_m["cost"] - m["cost"]) / base_m["cost"] if base_m["cost"] > 0 else 0.0
    return {"weights": W, "trips": out, "deferred": deferred_out, "lots": len(lots), "vehicles_available": len(V),
            "metrics": m, "baseline": base_m, "gain": round(gain, 3), "convergence": hist, "pheromone": pher}
