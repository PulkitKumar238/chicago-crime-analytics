"""
Backend-agnostic database helpers.

Two access styles are exposed on purpose, because the brief asks for both:

  * get_engine()   -> SQLAlchemy engine, used for bulk DataFrame writes/reads
                      (Use Case 1: "Use SQLAlchemy or PyMySQL to write data")
  * get_connector() -> raw DB-API connection via PyMySQL / sqlite3, used for
                      DDL, stored views and hand-written SQL
                      (Use Case 4: "should be done thru python Mysql Connector")
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def get_engine(**kwargs):
    """SQLAlchemy engine for the configured backend."""
    return create_engine(config.sqlalchemy_url(), future=True, **kwargs)


def get_connector():
    """Raw DB-API connection (PyMySQL for MySQL, sqlite3 for SQLite)."""
    if config.DB_BACKEND == "mysql":
        import pymysql

        return pymysql.connect(
            host=config.MYSQL["host"],
            port=config.MYSQL["port"],
            user=config.MYSQL["user"],
            password=config.MYSQL["password"],
            database=config.MYSQL["database"],
            charset="utf8mb4",
            autocommit=False,
        )
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connector():
    """Context-managed raw connection that commits on success."""
    conn = get_connector()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def split_statements(script: str) -> list[str]:
    """Split a .sql file into individual executable statements."""
    out, buf = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            out.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    if buf:
        out.append("\n".join(buf))
    return [s for s in out if s.strip()]


def run_sql_file(path: Path, skip_prefixes: tuple[str, ...] = ()) -> int:
    """Execute every statement in a .sql file. Returns statements executed."""
    statements = split_statements(Path(path).read_text())
    executed = 0
    with connector() as conn:
        cur = conn.cursor()
        for stmt in statements:
            head = stmt.lstrip().upper()
            if any(head.startswith(p) for p in skip_prefixes):
                continue
            cur.execute(stmt)
            executed += 1
        cur.close()
    return executed


def create_schema() -> int:
    """Create all warehouse tables for the active backend."""
    if config.DB_BACKEND == "mysql":
        _ensure_mysql_database()
        return run_sql_file(config.SQL_DIR / "schema_mysql.sql",
                            skip_prefixes=("CREATE DATABASE", "USE "))
    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return run_sql_file(config.SQL_DIR / "schema_sqlite.sql")


def create_views() -> int:
    """(Re)create the analytical views."""
    return run_sql_file(config.SQL_DIR / "views.sql")


def _ensure_mysql_database() -> None:
    import pymysql

    conn = pymysql.connect(
        host=config.MYSQL["host"], port=config.MYSQL["port"],
        user=config.MYSQL["user"], password=config.MYSQL["password"],
    )
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL['database']}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()
    conn.close()


def read_sql(query: str, params=None):
    """Run a SELECT and return a DataFrame."""
    import pandas as pd

    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def table_exists(name: str) -> bool:
    if config.DB_BACKEND == "mysql":
        q = ("SELECT COUNT(*) FROM information_schema.tables "
             "WHERE table_schema = :db AND table_name = :t")
        params = {"db": config.MYSQL["database"], "t": name}
    else:
        q = "SELECT COUNT(*) FROM sqlite_master WHERE name = :t"
        params = {"t": name}
    with get_engine().connect() as conn:
        return conn.execute(text(q), params).scalar() > 0


def backend_label() -> str:
    if config.DB_BACKEND == "mysql":
        return f"MySQL @ {config.MYSQL['host']}/{config.MYSQL['database']}"
    return f"SQLite3 @ {config.SQLITE_PATH.name}"
