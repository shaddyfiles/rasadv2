# Rasad: predictive logistics for forward posts

SIH 26251 (Indian Army, DSSC): assured logistics to forward formations. A eight-page React website on a Flask API, with demand forecasting, road-closure prediction, stock-out simulation, a GA + ACO planner and a Qwen3-8B assistant.

```
[ React website ]  seven pages: Home, Bases, Predictions, Plan, Movements, Roads, Ask Rasad
        │  HTTP / JSON
        ▼
[ Flask REST API ]  backend/app.py
        ├──► (1) Qwen3-8B          backend/assistant.py   natural-language commands and alert briefings
        ├──► (2) XGBoost + ML      backend/forecast.py    14-day demand: XGBoost + regression ensemble, conformal P10 / P50 / P90
        │                          backend/predict.py     road-closure classifier (weather), Monte Carlo stock-out risk
        └──► (3) GA + ACO engine   backend/optimizer.py   route and load optimisation
        ▼
[ PostgreSQL + PostGIS ]  bases (points), live inventory, road network (linestrings), weather, closure history, plans, shipments
```

## The website

Eight pages, each with its own address, so they can be bookmarked and shared:

| Page | Address | What it is for |
|---|---|---|
| Home | `/` | One sentence on the most urgent shortage, links to every service, then the sector map (click a base to open it), the bases that need supply this week, the loads on the move and the roads to watch. |
| Bases | `/bases` | Every post and depot, shortest stock first. |
| Base | `/bases/P4` | Stock register: on hand, daily use, how long it lasts, run-out date, loads on the way. Correct a figure in place, record today's usage, change troop strength. Shows a chart of the last month and the next two weeks for the chosen item. |
| Predictions | `/predictions` | Chance each post runs out of each item within 3 days and a week, with the likely run-out window (500 simulations each). A seven-day grid of each road's chance of closing. How far to trust both models: hold-out error against simpler models, and what drives each prediction. |
| Plan | `/plan` | Choose what matters (arrive sooner, avoid risky roads, use fewer vehicles) and work out a plan. Each trip shows its drops, dates and the reason in plain words; the map shows the route. Send all trips. "How this plan was found" shows the genetic algorithm's progress against the rule-based plan. |
| What if | `/whatif` | Pick a disruption (a pass closes, both passes close, helicopters grounded, a troop surge) and see what it does. For each one Rasad shows the expected stock-outs in the next 7 days if nothing is sent, if the plan you already had is run with the loads that can no longer go removed, and if Rasad plans again. It works on a copy, so nothing real changes. |
| Movements | `/movements` | Loads on the way, with Mark delivered, and the delivery history. |
| Roads | `/roads` | The road register: close or reopen a road. Chances of closure come from the road model; overwrite one from an engineer report, or take them from the model again. Click a road on the map to find it in the table. |
| Ask Rasad | `/assistant` | Ask questions or give instructions in plain words. Changes wait for your Confirm. Also writes a short alert briefing. |

Design notes:
- The layout follows the Government of India web guidelines (GIGW) pattern used on portals such as india.gov.in:
  - an accessibility strip with skip link, A- / A / A+ text size and a high-contrast mode (remembered per browser);
  - a header with the bilingual name रसद Rasad and a search box for posts, depots and roads;
  - a tricolour band, a navy menu bar and a scrolling alerts ticker (pauses on hover, and stays still for reduced motion);
  - breadcrumbs, white panels and register-style tables;
  - a navy footer with the last-updated date.
- It uses Rasad's own mark, not the State Emblem or any Army insignia, and the footer says it is not an official government site. Add official marks only with authorisation.
- Type has three roles, all under the SIL Open Font License and bundled in `frontend/public/fonts`, so nothing loads from the internet:
  - **Tektur** for headings and the site name: squared and technical;
  - **Outfit** for reading text;
  - **Geist Mono** for every number, percentage, table header and assistant reply, so the site reads like an AI operations console.
  Poppins (Devanagari subset) sets the Hindi name रसद.
- The map is a survey-style vector map drawn from PostGIS geometry, so it needs no tile server and works offline. There is a dark theme as well.

**Sector map** (Home and Roads pages):
- **Day picker:** "Next 3 days" (what the planner uses), then each of the next 7 days. "Play the week" steps through them, so you can watch the forecast storm close the passes.
- **Chance of closure:** a percentage label on every road. Roads are coloured under 20%, 20–50% and likely to close, and roads closed now are dashed.
- **Weather:** snow lying along each road, shaded by depth, and a card for each zone (Valley floor, Tangla La, Zarla La, High ground) with snow, temperature and wind. On phones the cards become a list under the map.
- **Dangers:**
  - avalanche danger, high or considerable, from snow over 3 days at altitude (a field rule, stated on the map);
  - roads under enemy observation (hatched, with an eye marker);
  - bridge weight limits, as a road-sign roundel;
  - high passes, with their height.
- **Road details:** click or hover over a road for its 7-day closure strip, weather and dangers.
- **Layers:** closure, weather, dangers and stock at posts can each be switched on or off.
- The Plan page map shows each road's 3-day chance and the fixed dangers next to the chosen trip.

| You type in Ask Rasad | What happens |
|---|---|
| `close Tangla road` / `open tangla` | Proposes a road status change → Confirm |
| `set fuel at Trishul to 500` | Proposes a stock correction → Confirm |
| `used 80 L of fuel at Vajra` | Proposes a usage record; stock drops and the model retrains → Confirm |
| `strength at Kesari to 120` | Proposes a troop-strength change; forecasts scale with it → Confirm |
| `risk on Kesari ridge to 70%` | Proposes a closure-risk change → Confirm |
| `plan resupply`, then `dispatch` | Works out a plan, then proposes sending it → Confirm |
| `status of Hima`, `fuel forecast for Garud`, `alerts` | Answers from live data |

## Clickable demo (no server)

`frontend/dist-demo/rasad-demo.html` is the same website as one file, replaying API responses recorded from a fresh sector. Open it in any browser. Working out a plan (four priority settings are recorded), sending it, and the example questions in Ask Rasad all work; other edits show a message that the demo does not save changes.

To rebuild it after changing the code:

```bash
python frontend/demo/capture.py                  # records every page's data into frontend/demo/demo-data.json
cd frontend && node build-demo.mjs               # writes dist-demo/rasad-demo.html (fonts and data inlined)
```

## Run locally

```bash
cd backend
pip install -r requirements.txt
python app.py                      # http://localhost:5000  (SQLite, seeded on first start)
```

The built UI is already in `backend/static`. To change the UI:

```bash
cd frontend && npm install && npm run build      # writes backend/static (app.js, app.css, fonts)
```

Tests (from the repo root): `pip install -r backend/requirements-dev.txt && pytest -q`. There are 21 end-to-end API tests.

## Run with PostgreSQL + PostGIS

```bash
export POSTGRES_PASSWORD=choose-one              # required; compose refuses to start without it
docker compose up -d --build                     # PostGIS 16-3.4 + API/UI on http://localhost:8000
docker compose --profile llm up -d               # adds Qwen3-8B on vLLM (GPU host)
```

Or point at an existing server: `DATABASE_URL=postgresql://user:pass@host:5432/rasad python app.py`.

The app runs `CREATE EXTENSION postgis`, creates the tables with `geometry(Point,4326)` and `geometry(LineString,4326)` columns and GiST indexes, and seeds the sector. Spatial SQL in use:
- `ST_AsGeoJSON` feeds the map.
- `ST_GeomFromGeoJSON` writes geometry.
- `ST_DWithin` and `ST_Distance` on geography answer `GET /api/bases/nearby?lat=&lon=&km=`.

## Real weather

The weather that drives road closures can be real, from [Open-Meteo](https://open-meteo.com/) (free, no key): daily snowfall, mean temperature (downscaled to each zone's altitude) and peak wind at each of the four weather zones, taken at the zones' real coordinates.

```bash
RASAD_REAL_DATA=live   python app.py    # real weather up to today and the real 14-day forecast
RASAD_REAL_DATA=replay python app.py    # a real winter replayed as if it were today (day 0 = 2026-03-08, four days before a real snowfall peak)
RASAD_REAL_DATA=replay:2026-01-15 python app.py   # another start day
```

Set it before the first start, or call `POST /api/reset` afterwards. The download is cached in `backend/data/weather_real.json` (the committed copy is the 2026-03-08 replay, so that mode works offline). If the download fails, Rasad falls back to synthetic weather and `/api/health` says so (`weather_source`).

What is real and what is not:
- Real: the weather. The Predictions page shows which source is in use.
- Not real: the sector, posts, roads and consumption, and the road closures the model learns from. Those are still generated from the weather by a hidden snow rule. In real-weather mode the rule reads snow on a scale where 10 cm counts like 40 cm of the synthetic storms, because ERA5 snowfall in this cold desert is light. That scale is an assumption, so the closure model's accuracy there measures how well it learns the rule, not how well it predicts real closures.
- `live` mode in summer or autumn is calm, so almost no roads close. Use `replay` for a demo.

## Helicopter payload at altitude

A helicopter's lift falls with altitude. The planner uses the highest of its take-off and landing points: full rating up to 3,000 m, then 18% of the rating lost per 1,000 m, never below 30%. At a 5,000 m post a 1,200 kg helicopter lifts about 770 kg. This is a planning assumption, not an aircraft rating: change it with `RASAD_HELI_DERATE_FROM_M`, `RASAD_HELI_DERATE_PER_KM` and `RASAD_HELI_DERATE_FLOOR`. Each helicopter trip shows its derated limit and says so in its reason.

## Benchmark against PyVRP

`python benchmarks/pyvrp_vs_ga.py` (needs `pip install -r backend/requirements-dev.txt`) compares Rasad's GA + ACO with [PyVRP](https://github.com/PyVRP/PyVRP), a state-of-the-art vehicle routing solver, on the same resupply problems. Every plan is scored with Rasad's own cost. Full table: [`benchmarks/results.md`](benchmarks/results.md).

| Method | Mean cost (lower is better) | Notes |
|---|---:|---|
| Rule-based plan | 22.1 | the baseline |
| **Rasad GA + ACO** | **16.4** | 0.3 s per problem, no hard-limit penalty |
| PyVRP alone | 383 | equal or slightly better on the easy problems, but it cannot express the 2.5 t bridge limit, so 9 of 15 plans carry 3.4 to 3.9 t over the Kesari track |
| PyVRP, trucks capped at the bridge limit | 20.0 | always valid, but wastes truck space |
| **PyVRP, then Rasad's GA** | **15.6** | best or tied on all 15 problems; 4.5% lower than the GA alone |

What this does and does not show: Rasad's GA is already competitive, and PyVRP does better only as a starting point for it (PyVRP takes 3 s to the GA's 0.3 s). The 15 problems are 5 scenarios with 3 random seeds each on one seeded synthetic sector, so treat the 4.5% as encouraging, not proven. PyVRP's own search is strong where its model fits; the gap above is its modelling limits, not its search. The benchmark is not wired into the planner.

## Connect Qwen3-8B

```bash
vllm serve Qwen/Qwen3-8B --enable-auto-tool-choice --tool-call-parser hermes
export QWEN_BASE_URL=http://localhost:8000/v1 QWEN_MODEL=Qwen/Qwen3-8B
# or: ollama pull qwen3:8b ; QWEN_BASE_URL=http://localhost:11434/v1 QWEN_MODEL=qwen3:8b
```

- **Tools:** the model gets nine tools. Four read data: `get_status`, `get_alerts`, `get_forecast` and `plan_resupply`. Five change data: `set_stock`, `report_usage`, `set_road`, `set_strength` and `dispatch_plan`.
- **Confirmation:** write tools never run directly. They come back as proposed actions that the officer confirms, which then call `POST /api/command/execute`.
- **Thinking mode:** off, for fast replies.
- **Offline fallback:** without a model server, a rule-based parser handles the same commands, so the demo always works.

## How the engines work

**Demand forecasting (ensemble):**
- Two models per supply item, pooled across every post's history. Features: temperature, altitude, operational tempo and cold load. The target is consumption per person per day, so a troop-strength change scales the forecast directly.
  - XGBoost with the `reg:quantileerror` objective (scikit-learn gradient-boosted quantile regressors if xgboost is missing).
  - A per-person linear regression with non-negative cold and tempo effects.
- The two are blended with weights set by each model's error on the last 14 days, which it was not trained on.
- **Conformal range:** the trees' own 10–90% band covered only about 61–68% of hold-out days, so Rasad replaces it with the 10th and 90th percentiles of the blend's hold-out errors, widening slowly with horizon.
- Models retrain automatically when new consumption arrives.
- A stricter check (`walk_forward` in `/api/forecast/metrics`): three earlier 14-day windows, each trained only on days before it and blended 50/50 with no tuning on the window. Blend error about 12.6% against 25.3% for last week's average.
- Hold-out error (WAPE) in the seeded sector: blend about 12%, trees about 13%, regression about 12%, last week's average about 23–26%.

**Road-closure prediction:**
- A `weather` table holds 120 days of history and a 14-day forecast per zone (valley, Tangla, Zarla, high ground): snow, temperature and wind. `road_history` holds whether each road was closed on each day.
- A gradient-boosted classifier (XGBoost or scikit-learn `HistGradientBoostingClassifier`) predicts closure from today's snow, three-day snow, wind, temperature, the road's altitude and whether it is a mule track. It is constrained to be monotonic, so more snow never lowers the chance.
- Tested on the last 20 days it never saw: AUC about 0.95, Brier score 0.056 against 0.073 for guessing the usual rate. Three-day snowfall drives most of it.
- Each road's planning risk is its highest chance over the next three days. A value typed by hand stays until someone takes the model's chances again.

**Stock-out risk (Monte Carlo):**
- For every post and item, the next 14 days are played out 500 times. Daily use is drawn from a two-piece log-normal fitted to the forecast's P10 / P50 / P90, correlated day to day, and loads already on the way arrive on their dates.
- The result is the chance of running out within 3, 7 and 14 days, and the window in which the middle 80% of runs ran out.

**Optimisation (meta-heuristic):**
1. **Requirements:** each post's forecast, stock, inbound loads and lead time produce supply lots. Lots are urgent top-ups when stock runs out before a truck could arrive.
2. **Ant colony:** finds the route between any two bases on the open road graph. Cost is driving time plus the safety weight times (closure risk + hostile exposure).
3. **Genetic algorithm:** assigns every lot to a truck, a helicopter or "hold until tomorrow", and orders the drops.
   - Cost: 10 × lateness + speed × vehicle-days + safety × route risk + economy × vehicles and empty space.
   - Hard limits: vehicle capacity, the 2.5 t bridge limit on Kesari track, and depot stock.
   - The rule-based plan seeds the GA, so the result is never worse, and it is reported as the baseline.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Database (postgis/sqlite), forecast engine, Qwen3 status |
| GET | `/api/map` | GeoJSON bases + roads for the map |
| GET | `/api/bases`, `/api/bases/<id>` | Cover summary; stock, daily use, cover, inbound |
| GET | `/api/bases/nearby?lat&lon&km` | Spatial search (PostGIS `ST_DWithin`) |
| PATCH | `/api/bases/<id>` | Strength, tempo, temperature |
| PUT | `/api/inventory/<base>/<item>` | Set stock on hand |
| POST | `/api/consumption` | Record usage (reduces stock, retrains model) |
| GET | `/api/forecast/<base>/<item>`, `/api/forecast/metrics` | Forecast; hold-out accuracy |
| GET / PATCH | `/api/roads`, `/api/roads/<id>` | Road network; open/close, risk |
| GET | `/api/predict` | Stock-out chances, 7-day road outlook, model accuracy |
| POST | `/api/predict/roads/refresh` | Reset every road's risk from the closure model |
| GET | `/api/hazards` | Map layers for 7 days: closure chance per road, weather per zone, avalanche danger, observation, bridge limits, passes |
| GET | `/api/weather` | Last 7 days of weather and the 14-day forecast, by zone |
| GET / POST | `/api/whatif` | Ready-made scenarios; run one on a copy of the sector (`{"scenario": "pass_closed"}` or `{"close": [...], "ground_helis": true, "surge": {"base": "P2", "pct": 60}}`). Changes nothing. |
| POST | `/api/plan` | Run GA + ACO with `{"weights": {...}}` |
| POST | `/api/plan/<id>/dispatch` | Dispatch trips |
| GET / POST | `/api/shipments`, `/api/shipments/<id>/deliver` | In transit; confirm delivery |
| GET / POST | `/api/alerts`, `/api/alerts/brief` | Alerts; Qwen3 briefing |
| POST | `/api/command`, `/api/command/execute` | Natural-language command; run a confirmed action |
| POST | `/api/reset` | Re-seed the synthetic sector |

When `RASAD_API_KEY` is set, every write, `/api/command`, `/api/alerts/brief` and `/api/whatif` need the header `X-API-Key`. Set it for any shared deployment: with no key, anyone who can reach the server can edit data or call `/api/reset`. CORS is off unless `RASAD_CORS_ORIGIN` is set.

## Files

```
backend/   app.py  scenarios.py  realdata.py  assistant.py  forecast.py  predict.py  optimizer.py  store.py  db.py  seed.py  config.py  static/ (built UI)
frontend/  package.json  build.mjs  build-demo.mjs  demo/capture.py  dist-demo/rasad-demo.html  index.html  public/fonts/  src/{main,App,lib,MapView,Chart}.jsx  src/demo.js  src/pages/*.jsx  src/styles.css
tests/     test_api.py
benchmarks/ pyvrp_vs_ga.py  results.md  results.json
docs/      screenshots of every page
Dockerfile  docker-compose.yml
```

All data is synthetic unless real weather is switched on (below). Sector Himgiri, its posts, depots and passes are fictional.

## Verified here, and what isn't

Verified:
- All 21 API tests pass on SQLite with the scikit-learn fallback.
- The React website was built with esbuild and every page was clicked through in a headless browser at desktop and phone widths, with no script errors, including the Predictions page.

Not reachable from the build environment, so test before a demo:
- The PostGIS path, though the code and Docker files are written for it.
- XGBoost itself.
- A live Qwen3-8B server.
