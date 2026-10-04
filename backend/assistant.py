"""(1) Qwen3-8B: natural-language commands and alerts.

The model sees the live system only through tools. Read tools run immediately.
Write tools (change stock, close a road, dispatch) come back as proposed actions
that a person confirms in the UI before they run (POST /api/command/execute).
Without a model server, a small rule-based parser handles the same commands.
"""
import json
import re
import time

import requests

import store

SYSTEM = ("You are Rasad, a logistics assistant for forward posts in high mountains. "
          "Use tools for every figure; never invent numbers. For changes (stock, consumption, roads, troop strength, dispatch) "
          "call the matching tool: it is queued for the officer to confirm, so say what will change. Answer in two to five short lines. /no_think")

READ_TOOLS = {"get_status", "get_alerts", "get_forecast", "plan_resupply"}
TOOLS = [
    {"name": "get_status", "description": "Stock, daily use and days of cover for one base, or every post if base is omitted.", "params": {"base": "string"}},
    {"name": "get_alerts", "description": "Current low-stock and road alerts.", "params": {}},
    {"name": "get_forecast", "description": "14-day demand forecast (P10/P50/P90) for one base and item.", "params": {"base": "string", "item": "string"}},
    {"name": "plan_resupply", "description": "Run the route optimiser and summarise the proposed trips.", "params": {}},
    {"name": "set_stock", "description": "Set the stock on hand of an item at a base.", "params": {"base": "string", "item": "string", "qty": "number"}},
    {"name": "report_usage", "description": "Record today's consumption of an item at a base.", "params": {"base": "string", "item": "string", "qty": "number"}},
    {"name": "set_road", "description": "Open or close a road, or set its closure risk (0-1).", "params": {"road": "string", "status": "string", "risk": "number"}},
    {"name": "set_strength", "description": "Change the troop strength at a post.", "params": {"base": "string", "strength": "number"}},
    {"name": "dispatch_plan", "description": "Dispatch every trip of the latest proposed plan.", "params": {}},
]


def _schema():
    out = []
    for t in TOOLS:
        props = {k: {"type": v} for k, v in t["params"].items()}
        out.append({"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                     "parameters": {"type": "object", "properties": props}}})
    return out


_status = {"t": 0, "v": None}


def status(cfg):
    if not cfg.QWEN_BASE_URL:
        return {"online": False, "model": cfg.QWEN_MODEL, "reason": "QWEN_BASE_URL not set"}
    if time.time() - _status["t"] < 30 and _status["v"]:
        return _status["v"]
    try:
        ok = requests.get(cfg.QWEN_BASE_URL.rstrip("/") + "/models", timeout=3,
                          headers={"Authorization": f"Bearer {cfg.QWEN_API_KEY}"}).status_code < 400
        v = {"online": ok, "model": cfg.QWEN_MODEL, "reason": None if ok else "server error"}
    except requests.RequestException as e:
        v = {"online": False, "model": cfg.QWEN_MODEL, "reason": type(e).__name__}
    _status.update(t=time.time(), v=v)
    return v


# ------------------------------------------------------------------ tools
def describe(action, db):
    a, t = action["args"], action["tool"]
    its = store.items(db)
    if t == "set_stock":
        return f"Set {its[a['item']]['name'].split(' (')[0].lower()} at {a['base_name']} to {a['qty']:,.0f} {its[a['item']]['unit']}"
    if t == "report_usage":
        return f"Record {a['qty']:,.0f} {its[a['item']]['unit']} of {its[a['item']]['name'].split(' (')[0].lower()} used at {a['base_name']} today"
    if t == "set_road":
        parts = []
        if a.get("status"):
            parts.append(a["status"])
        if a.get("risk") is not None:
            parts.append(f"risk {a['risk'] * 100:.0f}%")
        return f"Mark {a['road_name']} {' and '.join(parts)}"
    if t == "set_strength":
        return f"Set strength at {a['base_name']} to {a['strength']:,.0f}"
    if t == "dispatch_plan":
        return f"Dispatch plan #{a['plan_id']} ({a['trips']} trips)"
    return t


def normalise(db, tool, args):
    """Resolve names to ids and validate; returns (action, error)."""
    a = dict(args or {})
    if "base" in a and tool != "get_status" or tool in ("set_stock", "report_usage", "set_strength", "get_forecast"):
        bid = store.resolve_base(db, a.get("base"))
        if not bid:
            return None, f"I don't know a base called '{a.get('base')}'."
        a["base"] = bid
        a["base_name"] = db.q("SELECT name FROM bases WHERE id = ?", (bid,), one=True)["name"]
    if tool in ("set_stock", "report_usage", "get_forecast"):
        it = store.resolve_item(a.get("item"))
        if not it:
            return None, f"I don't know the item '{a.get('item')}'."
        a["item"] = it
    if tool in ("set_stock", "report_usage"):
        try:
            a["qty"] = float(a["qty"])
        except (KeyError, TypeError, ValueError):
            return None, "Give a quantity."
        if a["qty"] < 0:
            return None, "Quantity cannot be negative."
    if tool == "set_strength":
        try:
            a["strength"] = int(a["strength"])
        except (KeyError, TypeError, ValueError):
            return None, "Give a troop strength."
    if tool == "set_road":
        rid = store.resolve_road(db, a.get("road"))
        if not rid:
            return None, f"I don't know a road called '{a.get('road')}'."
        a["road"] = rid
        a["road_name"] = db.q("SELECT name FROM roads WHERE id = ?", (rid,), one=True)["name"]
        if a.get("status") not in (None, "open", "closed"):
            a["status"] = "closed" if "clos" in str(a["status"]) else "open"
        if a.get("risk") is not None:
            a["risk"] = float(a["risk"])
            if a["risk"] > 1:
                a["risk"] /= 100
    if tool == "dispatch_plan":
        p = db.q("SELECT id, result FROM plans WHERE status = 'proposed' ORDER BY id DESC LIMIT 1", one=True)
        if not p:
            return None, "There is no proposed plan. Ask me to plan resupply first."
        a["plan_id"] = p["id"]
        a["trips"] = len(store.jload(p["result"])["trips"])
        if not a["trips"]:
            return None, "The latest plan has no trips to dispatch."
    return {"tool": tool, "args": a}, None


def execute(db, action):
    """Run a confirmed write action."""
    t, a = action["tool"], action["args"]
    if t == "set_stock":
        store.set_inventory(db, a["base"], a["item"], a["qty"])
    elif t == "report_usage":
        store.report_consumption(db, a["base"], a["item"], a["qty"])
    elif t == "set_road":
        store.set_road(db, a["road"], a.get("status"), a.get("risk"))
    elif t == "set_strength":
        store.set_base(db, a["base"], strength=a["strength"])
    elif t == "dispatch_plan":
        return {"shipments": store.dispatch(db, a["plan_id"])}
    else:
        raise ValueError(f"not an executable action: {t}")
    return {"ok": True}


def run_read(db, cfg, tool, args, planner):
    snap = store.snapshot(db)
    if tool == "get_status":
        bid = store.resolve_base(db, (args or {}).get("base")) if (args or {}).get("base") else None
        if bid:
            return store.base_detail(snap, bid)
        return [store.base_summary(b, snap["items"]) for b in snap["bases"].values() if b["kind"] == "post"]
    if tool == "get_alerts":
        return store.alerts(snap)
    if tool == "get_forecast":
        f = store.forecast_view(db, args["base"], args["item"])
        return {"engine": f["engine"], "next_7_days": f["forecast"][:7]}
    if tool == "plan_resupply":
        p = planner()
        return {"plan_id": p["id"], "gain_vs_rule_based": p["gain"], "trips": [
            {"vehicle": t["vehicle"], "priority": t["priority"], "to": [d["base"] for d in t["drops"]], "route": t["route"], "why": t["why"]} for t in p["trips"]],
            "deferred": p["deferred"]}
    return {"error": "unknown tool"}


# ------------------------------------------------------------------ Qwen
def _chat(cfg, messages, tools=True):
    body = {"model": cfg.QWEN_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 700,
            "chat_template_kwargs": {"enable_thinking": False}}
    if tools:
        body.update(tools=_schema(), tool_choice="auto")
    r = requests.post(cfg.QWEN_BASE_URL.rstrip("/") + "/chat/completions", json=body, timeout=cfg.QWEN_TIMEOUT,
                      headers={"Authorization": f"Bearer {cfg.QWEN_API_KEY}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _clean(s):
    return re.sub(r"<think>.*?</think>", "", s or "", flags=re.S).strip()


def command_llm(db, cfg, text, history, planner):
    msgs = [{"role": "system", "content": SYSTEM}] + history[-6:] + [{"role": "user", "content": text}]
    actions, used = [], []
    for _ in range(4):
        m = _chat(cfg, msgs)
        calls = m.get("tool_calls") or []
        if not calls:
            return {"reply": _clean(m.get("content")), "actions": actions, "tools": used}
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            used.append(name)
            if name in READ_TOOLS:
                if name == "get_forecast":
                    act, err = normalise(db, name, args)
                    res = {"error": err} if err else run_read(db, cfg, name, act["args"], planner)
                else:
                    res = run_read(db, cfg, name, args, planner)
            else:
                act, err = normalise(db, name, args)
                if err:
                    res = {"error": err}
                else:
                    act["label"] = describe(act, db)
                    actions.append(act)
                    res = {"queued_for_confirmation": act["label"]}
            msgs.append({"role": "tool", "tool_call_id": c.get("id", name), "content": json.dumps(res, default=str)[:8000]})
    return {"reply": _clean(_chat(cfg, msgs, tools=False).get("content")), "actions": actions, "tools": used}


# ------------------------------------------------------------------ offline parser
NUM = r"(\d[\d,]*(?:\.\d+)?)"


def command_offline(db, text, planner):
    t = text.lower().strip()
    item_re = "|".join(sorted(store.ITEM_WORDS, key=len, reverse=True))

    def act(tool, args):
        a, err = normalise(db, tool, args)
        if err:
            return {"reply": err, "actions": [], "tools": []}
        a["label"] = describe(a, db)
        return {"reply": f"Ready to {a['label'][0].lower() + a['label'][1:]}. Confirm below to go ahead.", "actions": [a], "tools": [tool]}

    if m := re.search(r"\b(close|shut|block|open|reopen)\b\s+(?:the\s+)?(.+?)(?:\s+road|\s+track)?$", t):
        return act("set_road", {"road": m.group(2), "status": "open" if "open" in m.group(1) else "closed"})
    if m := re.search(r"risk\s+(?:on|of|for)?\s*(.+?)\s+(?:to|at|=)\s*" + NUM + r"\s*%?", t):
        return act("set_road", {"road": m.group(1), "risk": float(m.group(2).replace(",", "")) / 100})
    if m := re.search(rf"(?:set|update)\s+({item_re})\s+(?:at|for|in)\s+(\w+)\s+(?:to|=)\s*{NUM}", t):
        return act("set_stock", {"item": m.group(1), "base": m.group(2), "qty": m.group(3).replace(",", "")})
    if m := re.search(rf"(?:used|consumed|issued)\s+{NUM}\s*\w*\s+(?:of\s+)?({item_re})\s+(?:at|in)\s+(\w+)", t):
        return act("report_usage", {"qty": m.group(1).replace(",", ""), "item": m.group(2), "base": m.group(3)})
    if m := re.search(rf"strength\s+(?:at|of|for)\s+(\w+)\s+(?:to|=)\s*{NUM}", t):
        return act("set_strength", {"base": m.group(1), "strength": m.group(2).replace(",", "")})
    if re.search(r"\bdispatch\b", t):
        return act("dispatch_plan", {})
    if re.search(r"\b(plan|optimi[sz]e|resupply|route)\b", t):
        r = run_read(db, None, "plan_resupply", {}, planner)
        lines = [f"Plan {r['plan_id']} has {len(r['trips'])} trips and scores {r['gain_vs_rule_based'] * 100:.0f}% better than one vehicle per post."]
        lines += [f"- {x['vehicle']} to {' and '.join(x['to'])}" + (" (urgent)" if x["priority"] == "flash" else "") for x in r["trips"][:6]]
        return {"reply": "\n".join(lines) + "\nSay 'dispatch' to send it, or open the Plan page.", "actions": [], "tools": ["plan_resupply"], "plan_id": r["plan_id"]}
    if m := re.search(rf"({item_re}).*?(?:forecast|demand)|(?:forecast|demand).*?({item_re})", t):
        item = store.resolve_item(m.group(1) or m.group(2))
        bid = next((b for b in (store.resolve_base(db, w) for w in re.findall(r"\w+", t)) if b), None)
        if bid:
            f = run_read(db, None, "get_forecast", {"base": bid, "item": item}, planner)
            avg = sum(x["p50"] for x in f["next_7_days"]) / 7
            lo = sum(x["p10"] for x in f["next_7_days"]) / 7
            hi = sum(x["p90"] for x in f["next_7_days"]) / 7
            its = {i["id"]: i for i in db.q("SELECT id, name, unit FROM items")}
            bname = db.q("SELECT name FROM bases WHERE id=?", (bid,), one=True)["name"]
            iname, u = its[item]["name"].split(" (")[0].lower(), its[item]["unit"]
            u = {"box": "boxes", "kit": "kits", "part": "parts"}.get(u, u) if round(avg) != 1 else u
            return {"reply": f"{bname} should use about {avg:,.0f} {u} of {iname} a day over the next week, "
                             f"most likely between {lo:,.0f} and {hi:,.0f}.", "actions": [], "tools": ["get_forecast"]}
    bid = next((b for b in (store.resolve_base(db, w) for w in re.findall(r"\w+", t)) if b), None)
    if bid:
        d = run_read(db, None, "get_status", {"base": bid}, planner)
        lines = [f"{d['name']}, {d['alt_m']:,} m, {d['strength']} troops:"]
        plural = {"kg": "kg", "L": "litres", "box": "boxes", "kit": "kits", "part": "parts"}
        for r in d["inventory"]:
            if r["qty"] is None:
                continue
            cov = "over 60 days" if r["cover_days"] is None else f"{r['cover_days']:.1f} days"
            u = r["unit"] if round(r["qty"]) == 1 else plural.get(r["unit"], r["unit"])
            lines.append(f"- {r['name'].split(' (')[0]}: {r['qty']:,.0f} {u}, lasts {cov}" + (f", {r['inbound']:,.0f} on the way" if r["inbound"] else ""))
        return {"reply": "\n".join(lines), "actions": [], "tools": ["get_status"]}
    a = run_read(db, None, "get_alerts", {}, planner)
    if not a:
        return {"reply": "No alerts. Every post has at least 7 days of cover and all roads are open.", "actions": [], "tools": ["get_alerts"]}
    return {"reply": "Current alerts:\n" + "\n".join(f"- {x['text']}" for x in a[:8]), "actions": [], "tools": ["get_alerts"]}


def command(db, cfg, text, history, planner):
    st = status(cfg)
    if st["online"]:
        try:
            return {**command_llm(db, cfg, text, history, planner), "mode": "qwen3"}
        except Exception:  # noqa: BLE001
            _status.update(t=0, v=None)
    return {**command_offline(db, text, planner), "mode": "offline"}


def brief(db, cfg, alerts):
    """Short alert briefing for the commander."""
    if not alerts:
        return {"text": "All clear: every post has at least 7 days of cover and no road is closed or high-risk.", "mode": "template"}
    if status(cfg)["online"]:
        try:
            m = _chat(cfg, [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": "Write a 3-line alert briefing for the logistics commander from these alerts. "
                                                        "Lead with the most urgent, give one recommended action. Keep every number.\n" + json.dumps(alerts)}], tools=False)
            return {"text": _clean(m.get("content")), "mode": "qwen3"}
        except Exception:  # noqa: BLE001
            pass
    crit = [a for a in alerts if a["level"] == "crit"]
    words = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    n, m = len(crit), len(alerts) - len(crit)
    head = f"{words[n] if n < 10 else n} urgent {'issue' if n == 1 else 'issues'}"
    head += f" and {words[m].lower() if m < 10 else m} to watch." if m else "."
    lines = [head] + [a["text"] for a in alerts[:3]]
    lines.append("Suggested action: work out a resupply plan and send the urgent trips first.")
    return {"text": "\n".join(lines), "mode": "template"}
