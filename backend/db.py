"""Database access: PostgreSQL + PostGIS in production, SQLite for zero-setup local runs.

Geometry is exchanged as GeoJSON. On PostGIS it lives in geometry(…, 4326) columns
with GiST indexes; on SQLite it is stored as GeoJSON text.
"""
import json
import math
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL, kg_per_unit {REAL} NOT NULL, criticality {REAL} NOT NULL
);
CREATE TABLE IF NOT EXISTS bases (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,           -- base | depot | post
  depot_id TEXT, strength INTEGER DEFAULT 0, alt_m INTEGER, temp_c {REAL}, tempo {REAL} DEFAULT 1.0,
  geom {POINT} NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
  base_id TEXT NOT NULL REFERENCES bases(id), item_id TEXT NOT NULL REFERENCES items(id),
  qty {REAL} NOT NULL, updated_at TEXT, PRIMARY KEY (base_id, item_id)
);
CREATE TABLE IF NOT EXISTS consumption (
  id {AUTO}, base_id TEXT NOT NULL, item_id TEXT NOT NULL, day TEXT NOT NULL,
  qty {REAL} NOT NULL, strength INTEGER, temp_c {REAL}, tempo {REAL}
);
CREATE INDEX IF NOT EXISTS ix_consumption ON consumption(base_id, item_id, day);
CREATE TABLE IF NOT EXISTS roads (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  km {REAL} NOT NULL, speed_kmh {REAL} NOT NULL, alt_m INTEGER, mode TEXT DEFAULT 'road',
  exposure {REAL} DEFAULT 0, max_kg {REAL}, status TEXT DEFAULT 'open', risk {REAL} DEFAULT 0,
  zone TEXT, risk_source TEXT DEFAULT 'model', geom {LINE} NOT NULL
);
CREATE TABLE IF NOT EXISTS weather (
  day TEXT NOT NULL, zone TEXT NOT NULL, snow_cm {REAL}, temp_c {REAL}, wind_kmh {REAL}, kind TEXT,
  PRIMARY KEY (day, zone)
);
CREATE TABLE IF NOT EXISTS road_history (
  road_id TEXT NOT NULL, day TEXT NOT NULL, closed INTEGER NOT NULL, PRIMARY KEY (road_id, day)
);
CREATE TABLE IF NOT EXISTS vehicles (
  id TEXT PRIMARY KEY, name TEXT, type TEXT, home TEXT, cap_kg {REAL}, status TEXT DEFAULT 'idle'
);
CREATE TABLE IF NOT EXISTS plans (
  id {AUTO}, created_at TEXT, status TEXT DEFAULT 'proposed', result TEXT
);
CREATE TABLE IF NOT EXISTS shipments (
  id {AUTO}, plan_id INTEGER, vehicle_id TEXT, status TEXT, created_at TEXT, eta TEXT, trip TEXT
)
"""

POSTGIS_EXTRA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE INDEX IF NOT EXISTS ix_bases_geom ON bases USING GIST (geom);
CREATE INDEX IF NOT EXISTS ix_roads_geom ON roads USING GIST (geom)
"""


class DB:
    def __init__(self, url):
        self.url = url
        self.pg = url.startswith(("postgres://", "postgresql://"))
        self.lock = threading.RLock()
        self._local = threading.local()

    @property
    def kind(self):
        return "postgis" if self.pg else "sqlite"

    @property
    def con(self):
        c = getattr(self._local, "c", None)
        if c is None:
            if self.pg:
                import psycopg2
                import psycopg2.extras
                c = psycopg2.connect(self.url, cursor_factory=psycopg2.extras.RealDictCursor)
            else:
                c = sqlite3.connect(self.url.replace("sqlite:///", "", 1), check_same_thread=False)
                c.row_factory = sqlite3.Row
            self._local.c = c
        return c

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def q(self, sql, params=(), one=False):
        cur = self.con.cursor()
        cur.execute(self._sql(sql), tuple(params))
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        cur.close()
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, params=()):
        cur = self.con.cursor()
        cur.execute(self._sql(sql), tuple(params))
        row = cur.fetchone() if cur.description else None
        cur.close()
        return dict(row) if row is not None else None

    def many(self, sql, rows):
        if rows:
            cur = self.con.cursor()
            cur.executemany(self._sql(sql), [tuple(r) for r in rows])
            cur.close()

    def commit(self):
        self.con.commit()

    def rollback(self):
        self.con.rollback()

    # ---------------------------------------------------------- schema
    def create_schema(self, drop=False):
        tables = ["road_history", "weather", "shipments", "plans", "vehicles", "roads", "consumption", "inventory", "bases", "items"]
        cur = self.con.cursor()
        if drop:
            for t in tables:
                cur.execute(f"DROP TABLE IF EXISTS {t}" + (" CASCADE" if self.pg else ""))
        if self.pg:
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        ddl = SCHEMA.replace("{AUTO}", "SERIAL PRIMARY KEY" if self.pg else "INTEGER PRIMARY KEY AUTOINCREMENT")
        ddl = ddl.replace("{REAL}", "DOUBLE PRECISION" if self.pg else "REAL")
        ddl = ddl.replace("{POINT}", "geometry(Point, 4326)" if self.pg else "TEXT")
        ddl = ddl.replace("{LINE}", "geometry(LineString, 4326)" if self.pg else "TEXT")
        for stmt in [s for s in ddl.split(";") if s.strip()]:
            cur.execute(stmt)
        if self.pg:
            for stmt in [s for s in POSTGIS_EXTRA.split(";") if s.strip()]:
                cur.execute(stmt)
        cur.close()
        self.commit()

    def has_schema(self):
        try:
            return (self.q("SELECT COUNT(*) AS n FROM bases", one=True) or {}).get("n", 0) > 0
        except Exception:  # noqa: BLE001
            self.rollback()
            return False

    # ---------------------------------------------------------- geometry
    def geom_in(self):
        """SQL placeholder for a GeoJSON geometry parameter."""
        return "ST_SetSRID(ST_GeomFromGeoJSON(?), 4326)" if self.pg else "?"

    def geom_out(self, col="geom"):
        return f"ST_AsGeoJSON({col}) AS {col}" if self.pg else col

    @staticmethod
    def as_geojson(v):
        return json.loads(v) if isinstance(v, str) else v

    def nearby_bases(self, lon, lat, km):
        """Bases within `km` of a point. PostGIS: ST_DWithin on geography; SQLite: haversine."""
        if self.pg:
            return self.q(
                "SELECT id, name, kind, ST_Distance(geom::geography, ST_MakePoint(?, ?)::geography) / 1000 AS km "
                "FROM bases WHERE ST_DWithin(geom::geography, ST_MakePoint(?, ?)::geography, ?) ORDER BY km",
                (lon, lat, lon, lat, km * 1000))
        out = []
        for b in self.q("SELECT id, name, kind, geom FROM bases"):
            x, y = json.loads(b["geom"])["coordinates"]
            d = haversine(lon, lat, x, y)
            if d <= km:
                out.append({"id": b["id"], "name": b["name"], "kind": b["kind"], "km": d})
        return sorted(out, key=lambda r: r["km"])


def haversine(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    return 2 * r * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def jload(v):
    return json.loads(v) if isinstance(v, str) else v
