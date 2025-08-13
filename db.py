# db.py  — free-hosting friendly (Postgres if DB_URL set, else SQLite file)
import os
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

DB_URL = os.environ.get("DB_URL")

if DB_URL:
    # Use Postgres/MySQL/etc if provided
    engine = create_engine(
        DB_URL,
        poolclass=QueuePool, pool_size=5, max_overflow=10, pool_pre_ping=True,
    )
else:
    # Fallback to a local SQLite file (works on Streamlit free hosting)
    DB_URL = "sqlite:///ro.db"
    engine = create_engine(
        DB_URL,
        connect_args={"check_same_thread": False}  # needed for SQLite in web apps
    )

def fetchone(q, p=()):
    with engine.connect() as c:
        return c.execute(text(q), p).mappings().first()

def fetchall(q, p=()):
    with engine.connect() as c:
        return list(c.execute(text(q), p).mappings().all())

def execute(q, p=()):
    with engine.begin() as c:
        c.execute(text(q), p)

def migrate():
    # Works for both Postgres and SQLite (SQLite is lenient with types)
    stmts = [
        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            capacity_limit INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS capacity_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            requested_capacity INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        """CREATE TABLE IF NOT EXISTS runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            user_id INTEGER,
            plant_name TEXT, site_name TEXT,
            capacity REAL, temperature REAL,
            feed_tds REAL, product_tds REAL,
            feed_flow REAL, product_flow REAL, reject_flow REAL,
            hp REAL, brine REAL, perm_bp REAL,
            stage_type TEXT,
            recovery REAL, rejection REAL, salt_pass REAL,
            reject_tds REAL, cf REAL, mb_error REAL,
            dP REAL, pi_feed REAL, pi_perm REAL, d_pi REAL, ndp REAL,
            prod_m3d REAL
        )"""
    ]
    with engine.begin() as c:
        for s in stmts:
            c.execute(text(s))