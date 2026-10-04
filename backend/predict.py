"""Advanced prediction on top of the demand forecasts.

1. Road closures. A gradient-boosted classifier with monotonic constraints
   (XGBoost when installed, else scikit-learn histogram boosting) learns from
   120 days of weather and recorded closures which conditions shut each road:
   fresh and 3-day snowfall, wind, temperature, altitude and whether it is a mule
   track. Fed the 7-day weather forecast, it predicts each road's chance of closing
   each day. The optimiser routes on these predicted risks.
2. Running out. Monte Carlo simulation of 500 possible futures per post and item,
   drawing daily use from the forecast's P10/P50/P90 range with day-to-day
   correlation and counting loads already on the way. Gives the chance of running
   out within 3, 7 and 14 days and the likely run-out window.
"""
import math
import random
from datetime import date, timedelta

import numpy as np

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None

ROAD_FEATURES = ["Snow today", "Snow over 3 days", "Wind", "Temperature", "Altitude", "Mule track"]
HOLDOUT_DAYS = 20
_cache = {}


# ------------------------------------------------------------------ road closures
def _weather(db):
    wx = {}
    for r in db.q("SELECT day, zone, snow_cm, temp_c, wind_kmh, kind FROM weather"):
        wx[(r["zone"], r["day"])] = r
    return wx


def _feat(wx, road, day):
    d0 = date.fromisoformat(day)
    w = wx.get((road["zone"], day))
    if not w:
        return None
    snow3 = sum((wx.get((road["zone"], (d0 - timedelta(days=k)).isoformat())) or {"snow_cm": 0})["snow_cm"] for k in range(3))
    return [w["snow_cm"], snow3, w["wind_kmh"], w["temp_c"], road["alt_m"] / 1000, 1.0 if road["mode"] == "animal" else 0.0]


MONOTONE = [1, 1, 1, 0, 1, 1]   # more snow, wind, height or a mule track never makes a road safer


def _classifier():
    if xgb is not None:
        return xgb.XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.08, subsample=0.9, eval_metric="logloss",
                                 monotone_constraints="(" + ",".join(map(str, MONOTONE)) + ")")
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=200, max_depth=3, learning_rate=0.08, monotonic_cst=MONOTONE, random_state=7)


def _importance(model, X, y):
    if hasattr(model, "feature_importances_"):
        imp = np.asarray(model.feature_importances_, float)
    else:
        from sklearn.inspection import permutation_importance
        imp = np.maximum(permutation_importance(model, X, y, n_repeats=5, random_state=7, scoring="neg_log_loss").importances_mean, 0)
    return imp / max(imp.sum(), 1e-9)


def _auc(y, p):
    y, p = np.asarray(y), np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def closure_model(db):
    n = db.q("SELECT COUNT(*) AS n FROM road_history", one=True)["n"]
    key = ("closure", n, date.today().isoformat())
    if key in _cache:
        return _cache[key]
    wx = _weather(db)
    roads = {r["id"]: r for r in db.q("SELECT id, name, alt_m, mode, zone FROM roads")}
    rows = db.q("SELECT road_id, day, closed FROM road_history ORDER BY day")
    cut = (date.today() - timedelta(days=HOLDOUT_DAYS)).isoformat()
    X, y, test = [], [], []
    for r in rows:
        f = _feat(wx, roads[r["road_id"]], r["day"])
        if f is None:
            continue
        X.append(f)
        y.append(r["closed"])
        test.append(r["day"] >= cut)
    X, y, test = np.array(X, dtype=float).reshape(-1, len(ROAD_FEATURES)), np.array(y, dtype=int), np.array(test, dtype=bool)
    stats = {"trained_on_days": int(len(set(r["day"] for r in rows))), "closure_rate": float(y.mean()) if len(y) else 0.0}
    if len(set(y[~test])) == 2:
        m = _classifier().fit(X[~test], y[~test])
        p = m.predict_proba(X[test])[:, 1]
        stats.update(auc=_auc(y[test], p), brier=float(np.mean((p - y[test]) ** 2)),
                     brier_baseline=float(np.mean((y[~test].mean() - y[test]) ** 2)), holdout_days=HOLDOUT_DAYS)
    model = _classifier().fit(X, y)
    imp = _importance(model, X, y)
    stats["importance"] = [{"feature": f, "share": float(s)} for f, s in sorted(zip(ROAD_FEATURES, imp), key=lambda x: -x[1])]
    res = {"model": model, "stats": stats, "engine": "xgboost" if xgb is not None else "sklearn-hgb"}
    _cache[key] = res
    return res


def road_outlook(db, days=7):
    cm = closure_model(db)
    wx = _weather(db)
    out = []
    today = date.today()
    for r in db.q("SELECT id, name, alt_m, mode, zone, status, risk, risk_source FROM roads ORDER BY id"):
        feats, dd = [], []
        for h in range(days):
            d = (today + timedelta(days=h)).isoformat()
            f = _feat(wx, r, d)
            if f:
                feats.append(f)
                dd.append(d)
        probs = cm["model"].predict_proba(np.array(feats))[:, 1] if feats else []
        snow = [wx[(r["zone"], d)]["snow_cm"] for d in dd]
        out.append({"id": r["id"], "name": r["name"], "status": r["status"], "risk": r["risk"], "risk_source": r["risk_source"],
                    "days": [{"day": d, "p": round(float(p), 3), "snow_cm": s} for d, p, s in zip(dd, probs, snow)]})
    return {"roads": out, "engine": cm["engine"], "stats": cm["stats"]}


ZONE_NAMES = {"valley": "Valley floor", "tangla": "Tangla La", "zarla": "Zarla La", "high": "High ground"}


def avalanche(snow3, alt_m):
    """Avalanche danger from fresh snow load at altitude (a simple field rule, not a model):
    40 cm or more over three days above 5,000 m is high; 20 cm or more above 4,800 m is considerable."""
    if alt_m >= 5000 and snow3 >= 40:
        return "high"
    if alt_m >= 4800 and snow3 >= 20:
        return "considerable"
    return None


def hazards(db, days=7):
    """Everything the sector map shows for each forecast day: closure chance per road (classifier),
    weather per zone, avalanche danger, and fixed dangers (enemy observation, bridge limits, high passes)."""
    o = road_outlook(db, days)
    wx = _weather(db)
    today = date.today()
    dd = [(today + timedelta(days=h)).isoformat() for h in range(days)]

    def snow3(zone, d):
        d0 = date.fromisoformat(d)
        return round(sum((wx.get((zone, (d0 - timedelta(days=k)).isoformat())) or {"snow_cm": 0})["snow_cm"] for k in range(3)), 1)

    zones = []
    for z, name in ZONE_NAMES.items():
        zones.append({"zone": z, "name": name, "days": [
            {"day": d, "snow_cm": round(wx[(z, d)]["snow_cm"], 1), "snow3_cm": snow3(z, d), "temp_c": round(wx[(z, d)]["temp_c"], 1),
             "wind_kmh": round(wx[(z, d)]["wind_kmh"]), "kind": wx[(z, d)]["kind"]} for d in dd if (z, d) in wx]})
    by_id = {r["id"]: r for r in o["roads"]}
    roads = []
    for r in db.q("SELECT id, name, alt_m, mode, zone, exposure, max_kg FROM roads ORDER BY id"):
        fixed = []
        if r["exposure"] >= 0.3:
            fixed.append({"kind": "observation", "level": "high" if r["exposure"] >= 0.6 else "moderate",
                          "text": f"Under enemy observation ({'high' if r['exposure'] >= 0.6 else 'moderate'})"})
        if r["max_kg"]:
            fixed.append({"kind": "bridge", "limit_t": r["max_kg"] / 1000, "text": f"Bridge limit {r['max_kg'] / 1000:g} t"})
        if " La " in f" {r['name']} ":
            fixed.append({"kind": "pass", "text": f"{r['name'].replace(' road', '')} pass, {r['alt_m']:,} m"})
        days_out = []
        for x in by_id[r["id"]]["days"]:
            s3 = snow3(r["zone"], x["day"])
            days_out.append({**x, "snow3_cm": s3, "avalanche": avalanche(s3, r["alt_m"])})
        roads.append({"id": r["id"], "zone": r["zone"], "alt_m": r["alt_m"], "days": days_out, "fixed": fixed})
    return {"days": dd, "zones": zones, "roads": roads, "engine": o["engine"],
            "rules": {"avalanche": "High: 40 cm or more of snow over 3 days above 5,000 m. Considerable: 20 cm or more above 4,800 m."}}


def refresh_road_risk(db, include_manual=False):
    """Set each road's risk to its highest predicted chance of closing over the next 3 days."""
    o = road_outlook(db, 3)
    for r in o["roads"]:
        if r["risk_source"] == "manual" and not include_manual:
            continue
        p = max((d["p"] for d in r["days"]), default=0.0)
        db.x("UPDATE roads SET risk = ?, risk_source = 'model' WHERE id = ?", (round(p, 3), r["id"]))
    db.commit()
    return o


# ------------------------------------------------------------------ running out
def _draws(fc, n, rng):
    """Correlated daily demand paths from P10/P50/P90 (two-piece lognormal, AR(1) shocks)."""
    H = len(fc)
    p50 = np.array([max(f["p50"], 1e-9) for f in fc])
    lo = np.log(np.maximum(np.array([f["p10"] for f in fc]), 1e-9) / p50) / -1.2816
    hi = np.log(np.maximum(np.array([f["p90"] for f in fc]), 1e-9) / p50) / 1.2816
    z = np.zeros((n, H))
    e = rng.standard_normal((n, H))
    z[:, 0] = e[:, 0]
    for h in range(1, H):
        z[:, h] = 0.6 * z[:, h - 1] + 0.8 * e[:, h]
    sig = np.where(z < 0, lo, hi)
    return p50 * np.exp(sig * z)


def stockout_risk(snap, n=500, seed=7):
    rng = np.random.default_rng(seed)
    today = date.today()
    out = []
    for b in snap["bases"].values():
        if b["kind"] != "post":
            continue
        for item, fc in b["forecast"].items():
            if item == "spares":
                continue
            D = _draws(fc, n, rng)
            arrivals = np.zeros(len(fc))
            for day, q in b.get("inbound_days", {}).get(item, []):
                h = (date.fromisoformat(day) - today).days
                if 0 <= h < len(fc):
                    arrivals[h] += q
            stock = b["stock"][item] + np.cumsum(arrivals)[None, :] - np.cumsum(D, axis=1)
            out_day = np.where((stock < 0).any(axis=1), (stock < 0).argmax(axis=1), len(fc))
            pr = lambda k: float((out_day < k).mean())  # noqa: E731
            q10, q50, q90 = np.percentile(out_day, [10, 50, 90])
            win = None if q50 >= len(fc) else [(today + timedelta(days=int(q10))).isoformat(), (today + timedelta(days=int(min(q90, len(fc) - 1)))).isoformat()]
            out.append({"base_id": b["id"], "base": b["name"], "item": item, "p3": pr(3), "p7": pr(7), "p14": pr(len(fc)),
                        "window": win, "beyond_horizon": bool(q90 >= len(fc))})
    out.sort(key=lambda r: -r["p7"])
    return {"rows": out, "simulations": n}
