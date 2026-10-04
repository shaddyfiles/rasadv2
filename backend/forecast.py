"""(2) Demand forecasting: XGBoost + per-capita regression ensemble with calibrated ranges.

For each supply item, two models learn daily use per person from every post's history:

* a gradient-boosted quantile model (XGBoost `reg:quantileerror`; scikit-learn
  gradient boosting if xgboost is not installed) on temperature, altitude,
  operational tempo and cold load;
* a per-capita linear model (base use + cold load + tempo), which extrapolates
  sensibly when a post gets colder or busier than anything in its history.

The two are blended with weights set by their accuracy on the last 14 days (held
out). The likely range (P10 to P90) is calibrated on those same held-out days
(split-conformal style), so it reflects how wrong the blend has actually been.
"""
import math
from datetime import date, timedelta

import numpy as np

try:
    import xgboost as xgb
    ENGINE = "xgboost"
except ImportError:  # pragma: no cover - depends on environment
    xgb = None
    ENGINE = "sklearn-gbr"

QUANTILES = (0.1, 0.5, 0.9)
HORIZON = 14
HOLDOUT = 14
FEATURES = ["Temperature", "Altitude", "Operational tempo", "Cold load"]
_cache = {}


def _x(temp, alt, tempo):
    return [temp, alt / 1000.0, tempo, max(0.0, 5 - temp)]


def _lin_x(temp, tempo):
    return [1.0, max(0.0, 5 - temp), tempo - 1]


class QuantileModel:
    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        if xgb is not None:
            self.m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array(QUANTILES),
                                      n_estimators=120, max_depth=3, learning_rate=0.12, subsample=0.9, n_jobs=1)
            self.m.fit(X, y)
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            self.m = [GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=90, max_depth=3,
                                                learning_rate=0.07, subsample=0.9, random_state=7).fit(X, y) for q in QUANTILES]
        return self

    def predict(self, X):
        X = np.asarray(X, float)
        P = np.asarray(self.m.predict(X)).reshape(len(X), -1) if xgb is not None else np.column_stack([m.predict(X) for m in self.m])
        return np.sort(np.maximum(P, 0), axis=1)

    def importance(self):
        imp = self.m.feature_importances_ if xgb is not None else self.m[1].feature_importances_
        imp = np.asarray(imp, float)
        return (imp / imp.sum()).tolist() if imp.sum() > 0 else imp.tolist()


class LinearModel:
    """Use per person = a + b * cold load + c * (tempo - 1), with b, c >= 0."""
    def fit(self, X, y):
        X, y = np.asarray(X, float), np.asarray(y, float)
        cols = [0, 1, 2]
        for _ in range(3):
            beta = np.zeros(3)
            beta[cols] = np.linalg.lstsq(X[:, cols], y, rcond=None)[0]
            neg = [c for c in cols if c > 0 and beta[c] < 0]
            if not neg:
                break
            cols = [c for c in cols if c not in neg]
        self.beta = np.maximum(beta, [-np.inf, 0, 0])
        return self

    def predict(self, X):
        return np.maximum(np.asarray(X, float) @ self.beta, 0)


def history(db, until=None):
    sql = ("SELECT c.base_id, c.item_id, c.day, c.qty, c.strength, c.temp_c, c.tempo, b.alt_m "
           "FROM consumption c JOIN bases b ON b.id = c.base_id")
    return db.q(sql + (" WHERE c.day < ?" if until else "") + " ORDER BY c.day", (until,) if until else ())


def _stamp(db):
    s = db.q("SELECT COUNT(*) AS n, MAX(id) AS m FROM consumption", one=True)
    return (s["n"], s["m"], date.today().isoformat())


def train(db, until=None):
    """Fit both models for every item on history before `until`. Cached until new data arrives."""
    key = ("train", _stamp(db), until)
    if key in _cache:
        return _cache[key]
    rows = history(db, until)
    out = {}
    for item in sorted({r["item_id"] for r in rows}):
        rs = [r for r in rows if r["item_id"] == item and r["strength"]]
        y = [r["qty"] / r["strength"] for r in rs]
        out[item] = {"ml": QuantileModel().fit([_x(r["temp_c"], r["alt_m"], r["tempo"]) for r in rs], y),
                     "lin": LinearModel().fit([_lin_x(r["temp_c"], r["tempo"]) for r in rs], y)}
    if len(_cache) > 12:
        _cache.clear()
    _cache[key] = out
    return out


def calibration(db):
    """Score both models on the held-out last 14 days; derive blend weights, the calibrated
    range and accuracy figures. Cached until new data arrives."""
    key = ("cal", _stamp(db))
    if key in _cache:
        return _cache[key]
    cut = (date.today() - timedelta(days=HOLDOUT)).isoformat()
    models = train(db, until=cut)
    rows = [r for r in history(db) if r["day"] >= cut and r["strength"]]
    before = history(db, until=cut)
    last7 = {}
    for r in reversed(before):
        last7.setdefault((r["base_id"], r["item_id"]), [])
        if len(last7[(r["base_id"], r["item_id"])]) < 7:
            last7[(r["base_id"], r["item_id"])].append(r["qty"])
    kg = {i["id"]: i["kg_per_unit"] for i in db.q("SELECT id, kg_per_unit FROM items")}
    per_item, totals = {}, {"ml": 0.0, "lin": 0.0, "ens": 0.0, "naive": 0.0, "y": 0.0, "in_band": 0, "n": 0}
    for item, m in models.items():
        rs = [r for r in rows if r["item_id"] == item]
        if not rs:
            continue
        S = np.array([r["strength"] for r in rs], float)
        y = np.array([r["qty"] for r in rs], float)
        q = m["ml"].predict([_x(r["temp_c"], r["alt_m"], r["tempo"]) for r in rs]) * S[:, None]
        lin = m["lin"].predict([_lin_x(r["temp_c"], r["tempo"]) for r in rs]) * S
        naive = np.array([np.mean(last7.get((r["base_id"], item), [0]) or [0]) for r in rs])
        e_ml, e_lin = np.abs(y - q[:, 1]).sum(), np.abs(y - lin).sum()
        w = (1 / max(e_ml, 1e-9)) / ((1 / max(e_ml, 1e-9)) + (1 / max(e_lin, 1e-9)))
        ens = w * q[:, 1] + (1 - w) * lin
        rel = (y - ens) / np.maximum(ens, 1e-6)
        r10, r90 = (float(np.quantile(rel, 0.1)), float(np.quantile(rel, 0.9))) if item != "spares" else (-1.0, 2.0)
        per_item[item] = {"w_ml": float(w), "r10": min(r10, -0.03), "r90": max(r90, 0.03),
                          "wape": {"ml": e_ml / max(y.sum(), 1e-9), "lin": e_lin / max(y.sum(), 1e-9),
                                   "ens": np.abs(y - ens).sum() / max(y.sum(), 1e-9), "naive": np.abs(y - naive).sum() / max(y.sum(), 1e-9)}}
        if item != "spares":   # intermittent spares would swamp a weighted error
            k = kg[item]
            totals["ml"] += e_ml * k
            totals["lin"] += e_lin * k
            totals["ens"] += np.abs(y - ens).sum() * k
            totals["naive"] += np.abs(y - naive).sum() * k
            totals["y"] += y.sum() * k
            totals["in_band"] += int(((y >= q[:, 0]) & (y <= q[:, 2])).sum())
            totals["n"] += len(y)
    full = train(db)
    imp = np.mean([full[i]["ml"].importance() for i in full if i != "spares"], axis=0).tolist()
    res = {"items": per_item, "engine": ENGINE, "holdout_days": HOLDOUT,
           "wape": {k: totals[k] / totals["y"] for k in ("ml", "lin", "ens", "naive")} if totals["y"] else {},
           "quantile_coverage": totals["in_band"] / totals["n"] if totals["n"] else None,
           "importance": [{"feature": f, "share": s} for f, s in sorted(zip(FEATURES, imp), key=lambda x: -x[1])]}
    _cache[key] = res
    return res


def forecast(db, base, item, days=HORIZON, models=None):
    """Daily blended forecast with a calibrated P10-P90 range. Temperature cools 0.2 °C a day (early winter)."""
    models = models or train(db)
    cal = calibration(db)["items"].get(item, {"w_ml": 0.5, "r10": -0.2, "r90": 0.2})
    today = date.today()
    temps = [base["temp_c"] - 0.2 * h for h in range(days)]
    q = models[item]["ml"].predict([_x(t, base["alt_m"], base["tempo"]) for t in temps]) * base["strength"]
    lin = models[item]["lin"].predict([_lin_x(t, base["tempo"]) for t in temps]) * base["strength"]
    out = []
    for h, t in enumerate(temps):
        p50 = cal["w_ml"] * q[h, 1] + (1 - cal["w_ml"]) * lin[h]
        widen = math.sqrt(1 + 0.03 * h)
        p10 = max(0.0, p50 * (1 + cal["r10"] * widen))
        p90 = max(p50, p50 * (1 + cal["r90"] * widen))
        out.append({"day": (today + timedelta(days=h)).isoformat(), "temp_c": round(t, 1),
                    "p10": round(p10, 3), "p50": round(p50, 3), "p90": round(p90, 3)})
    return out


def cover(stock, fc, inbound=()):
    """Days until stock runs out at P50, counting inbound loads on their ETA day. None = beyond horizon."""
    st = stock
    arrivals = {}
    for day, q in inbound:
        arrivals[day] = arrivals.get(day, 0) + q
    for h, f in enumerate(fc):
        st += arrivals.get(f["day"], 0)
        if f["p50"] > 0 and st < f["p50"]:
            return h + st / f["p50"]
        st -= f["p50"]
    rate = fc[-1]["p50"]
    return len(fc) + st / rate if rate > 0 and st / rate < 60 else None


def metrics(db):
    c = calibration(db)
    return {"engine": c["engine"], "holdout_days": c["holdout_days"], "wape": c["wape"].get("ens"),
            "naive_wape": c["wape"].get("naive"), "by_model": c["wape"], "quantile_coverage": c["quantile_coverage"],
            "importance": c["importance"]}
