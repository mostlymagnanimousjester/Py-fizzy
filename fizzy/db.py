"""Connections that read and write a Fizzy SQLite file."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .codec import (
    BOOL_COLUMNS,
    JSON_COLUMNS,
    as_bool,
    base36_to_bytes,
    decode_uuid,
    dump_dt,
    is_fizzy_id,
    parse_dt,
)
from .schema import ensure

_TYPE_CACHE: dict[str, dict[str, dict[str, str]]] = {}
_PATHS: dict[int, str] = {}


def connect(path: str | Path) -> sqlite3.Connection:
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, detect_types=0)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    ensure(conn)
    path = str(database)
    _TYPE_CACHE[path] = _load_types(conn)
    _PATHS[id(conn)] = path
    return conn


def _load_types(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    types: dict[str, dict[str, str]] = {}
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for table in tables:
        name = table["name"] if isinstance(table, (sqlite3.Row, dict)) else table[0]
        info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        types[name] = {}
        for column in info:
            if isinstance(column, (sqlite3.Row, dict)):
                types[name][column["name"]] = column["type"] or ""
            else:
                types[name][column[1]] = column[2] or ""
    return types


def column_type(conn: sqlite3.Connection, table: str, column: str) -> str:
    path = _PATHS.get(id(conn), "")
    return _TYPE_CACHE.get(path, {}).get(table, {}).get(column, "")


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    path = _PATHS.get(id(conn), "")
    return column in _TYPE_CACHE.get(path, {}).get(table, {})


def _row_factory(cursor, row):
    record = {}
    for index, spec in enumerate(cursor.description):
        name = spec[0]
        value = row[index]
        if name == "id" or name.endswith("_id"):
            value = decode_uuid(value)
        elif name in BOOL_COLUMNS and not isinstance(value, bytes):
            value = as_bool(value)
        elif name in JSON_COLUMNS and isinstance(value, str) and value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        record[name] = value
    return record


def enc(conn: sqlite3.Connection, table: str, column: str, value):
    if value is None:
        return None
    declared = column_type(conn, table, column).lower()
    id_like = column == "id" or column.endswith("_id")
    if id_like and ("blob" in declared or declared == ""):
        if isinstance(value, memoryview):
            return value.tobytes()
        if isinstance(value, bytes):
            return value
        if isinstance(value, str) and is_fizzy_id(value):
            return base36_to_bytes(value)
        return value
    if "bool" in declared:
        return 1 if as_bool(value) else 0
    if "datetime" in declared or (column.endswith("_at") and "int" not in declared):
        if isinstance(value, str):
            parsed = parse_dt(value)
            return dump_dt(parsed) if parsed else value
        return dump_dt(value)
    if declared == "date" or column == "due_on":
        parsed = parse_dt(value) if not hasattr(value, "strftime") else value
        if parsed is None:
            return value
        return parsed.strftime("%Y-%m-%d")
    if "json" in declared or column in JSON_COLUMNS:
        if isinstance(value, (dict, list)):
            return json.dumps(value, separators=(",", ":"))
        return value
    return value


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def q1(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def insert(conn, table: str, **cols):
    from .codec import new_id, utcnow

    known = _TYPE_CACHE.get(_PATHS.get(id(conn), ""), {}).get(table, {})
    if "id" in known and "id" not in cols:
        cols["id"] = new_id()
    now = utcnow()
    if "created_at" in known and "created_at" not in cols:
        cols["created_at"] = now
    if "updated_at" in known and "updated_at" not in cols:
        cols["updated_at"] = now
    keys = list(cols)
    placeholders = ", ".join("?" for _ in keys)
    names = ", ".join(f'"{key}"' for key in keys)
    conn.execute(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
        [enc(conn, table, key, cols[key]) for key in keys],
    )
    return cols.get("id")


def update(conn, table: str, row_id: str, **cols):
    from .codec import utcnow

    known = _TYPE_CACHE.get(_PATHS.get(id(conn), ""), {}).get(table, {})
    if "updated_at" in known and "updated_at" not in cols:
        cols["updated_at"] = utcnow()
    keys = list(cols)
    assignments = ", ".join(f'"{key}"=?' for key in keys)
    conn.execute(
        f'UPDATE "{table}" SET {assignments} WHERE id=?',
        [enc(conn, table, key, cols[key]) for key in keys] + [enc(conn, table, "id", row_id)],
    )


def delete_where(conn, table: str, **where):
    keys = list(where)
    clause = " AND ".join(f'"{key}"=?' for key in keys)
    conn.execute(
        f'DELETE FROM "{table}" WHERE {clause}',
        [enc(conn, table, key, where[key]) for key in keys],
    )
