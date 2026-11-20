"""Database pool and small helpers."""
import json
import os
from decimal import Decimal
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DSN = os.environ.get("RX_DATABASE_URL", "postgresql://rx:rx@localhost/rx")
pool = ConnectionPool(DSN, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=False)


def open_pool():
    pool.open(wait=True)


@contextmanager
def tx():
    """A connection in a transaction; commits on success."""
    with pool.connection() as conn:
        with conn.transaction():
            yield conn


def all(sql, params=None):
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def one(sql, params=None):
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def jsonb(v):
    return Jsonb(v)


def feature_collection(rows, geom_key="geom", id_key="id"):
    feats = []
    for r in rows:
        r = dict(r)
        g = r.pop(geom_key)
        if isinstance(g, str):
            g = json.loads(g)
        feats.append({"type": "Feature", "id": str(r.get(id_key, "")), "geometry": g, "properties": _plain(r)})
    return {"type": "FeatureCollection", "features": feats}


def _plain(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            v = float(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        elif hasattr(v, "lower") and hasattr(v, "upper") and not isinstance(v, str):  # psycopg Range
            v = {"from": v.lower.isoformat() if v.lower else None, "to": v.upper.isoformat() if v.upper else None}
        elif v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
            v = str(v)
        out[k] = v
    return out
