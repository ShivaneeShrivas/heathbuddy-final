"""Data layer — speaks SQLite (local dev) and Postgres (production).

Why both: Render's free web services have a temporary filesystem, so a
SQLite file there is wiped on every restart and every deploy — real accounts
would silently vanish. Postgres (Neon/Render/Supabase) keeps data forever.

Set HB_DATABASE_URL (postgres://…) and the app uses Postgres; leave it unset
and it uses a local SQLite file exactly as before. Nothing else in the app
changes, because the queries stay written in the SQLite dialect and this
module translates them on the way out:

    ?                       → %s
    datetime('now')         → to_char(now() at time zone 'utc', …)
    datetime('now','-1 h')  → same, minus an interval
    date(col)               → to_char(col::timestamp, 'YYYY-MM-DD')
    INSERT OR IGNORE        → INSERT … ON CONFLICT DO NOTHING
    AUTOINCREMENT           → SERIAL

Timestamps stay TEXT in both engines, so string comparisons, ISO parsing in
Python, and every existing query behave identically. That symmetry is the
whole point: the 49-test suite that passes on SQLite is meaningful for
Postgres too.
"""
import os
import re
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    buddy_code TEXT UNIQUE NOT NULL,
    occupation TEXT, gender TEXT, activity_level TEXT, health_goal TEXT,
    onboarded INTEGER NOT NULL DEFAULT 0,
    quiet_start TEXT NOT NULL DEFAULT '23:00',
    quiet_end TEXT NOT NULL DEFAULT '07:00',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notification_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    tone TEXT NOT NULL DEFAULT 'friendly',
    emoji TEXT NOT NULL DEFAULT '✨',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    action_label TEXT NOT NULL DEFAULT 'Done',
    audience TEXT NOT NULL DEFAULT 'all',
    deep_dive TEXT
);
CREATE TABLE IF NOT EXISTS bandit_states (
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    alpha REAL NOT NULL,
    beta REAL NOT NULL,
    pref_multiplier REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (user_id, category)
);
CREATE TABLE IF NOT EXISTS interaction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    card_id INTEGER NOT NULL REFERENCES notification_cards(id),
    category TEXT NOT NULL,
    action TEXT NOT NULL,            -- sent | opened | dismissed | acted | snoozed
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_interactions_user ON interaction_logs(user_id, created_at);
CREATE TABLE IF NOT EXISTS habit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,              -- water | meal | sleep | mood
    value REAL NOT NULL DEFAULT 1,
    note TEXT,
    logged_on TEXT NOT NULL DEFAULT (date('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_habits_user_day ON habit_logs(user_id, type, logged_on);
CREATE TABLE IF NOT EXISTS xp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS user_badges (
    user_id INTEGER NOT NULL REFERENCES users(id),
    badge_code TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, badge_code)
);
CREATE TABLE IF NOT EXISTS challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🏆',
    metric_type TEXT NOT NULL,       -- habit type or 'nudge_acted'
    target INTEGER NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenge_members (
    challenge_id INTEGER NOT NULL REFERENCES challenges(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (challenge_id, user_id)
);
CREATE TABLE IF NOT EXISTS buddies (
    user_id INTEGER NOT NULL REFERENCES users(id),
    buddy_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, buddy_id)
);
CREATE TABLE IF NOT EXISTS cycle_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0,
    last_period_start TEXT,
    avg_cycle_len REAL NOT NULL DEFAULT 28,
    avg_period_len REAL NOT NULL DEFAULT 5,
    remind INTEGER NOT NULL DEFAULT 1,
    gcal_export INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cycle_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    start_date TEXT NOT NULL,
    UNIQUE (user_id, start_date)
);
CREATE TABLE IF NOT EXISTS activity_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    steps INTEGER NOT NULL DEFAULT 0,
    active_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS device_wellbeing_daily (
    user_id INTEGER NOT NULL REFERENCES users(id),
    date TEXT NOT NULL,
    screen_time_minutes INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS integrations (
    user_id INTEGER NOT NULL REFERENCES users(id),
    integration_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_connected',
    granted_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (user_id, integration_type)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT UNIQUE NOT NULL,   -- sha256 of the refresh token; raw token never stored
    device_label TEXT,                 -- best-effort User-Agent snippet, for a future "manage devices" screen
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT UNIQUE NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_subs_user ON push_subscriptions(user_id);
CREATE TABLE IF NOT EXISTS push_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    template_id TEXT NOT NULL,
    slot TEXT,
    sent_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_push_history_user ON push_history(user_id, sent_at);
CREATE TABLE IF NOT EXISTS push_snoozes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    template_id TEXT NOT NULL,
    remind_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_snoozes_user ON push_snoozes(user_id, remind_at);
CREATE TABLE IF NOT EXISTS pending_signups (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS email_otps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    purpose TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_email_otps_lookup ON email_otps(email, purpose, used_at);
CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT UNIQUE NOT NULL,   -- sha256 of the raw token; raw token never stored
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets(user_id);
CREATE TABLE IF NOT EXISTS game_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    game TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'easy',
    score REAL NOT NULL,
    is_daily INTEGER NOT NULL DEFAULT 0,
    played_on TEXT NOT NULL DEFAULT (date('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _pg_url():
    """Production database URL, if one is configured."""
    try:
        return current_app.config.get("DATABASE_URL")
    except RuntimeError:                      # outside an app context
        return os.environ.get("HB_DATABASE_URL")


def is_postgres():
    return bool(_pg_url())


# ---------------------------------------------------------------- translation
_DT_MOD = re.compile(r"datetime\(\s*'now'\s*,\s*'([^']+)'\s*\)", re.I)
_DT_PARAM = re.compile(r"datetime\(\s*'now'\s*,\s*\?\s*\)", re.I)
_DT_NOW = re.compile(r"datetime\(\s*'now'\s*\)", re.I)
_DATE_NOW = re.compile(r"date\(\s*'now'\s*\)", re.I)
_DATE_COL = re.compile(r"\bdate\(\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\)")

_UTC = "(now() at time zone 'utc')"
_TS_FMT = "'YYYY-MM-DD HH24:MI:SS'"


def translate(sql):
    """Rewrite one SQLite statement into its Postgres equivalent."""
    out = sql
    out = _DT_PARAM.sub(f"to_char({_UTC} + (%s)::interval, {_TS_FMT})", out)
    out = _DT_MOD.sub(lambda m: f"to_char({_UTC} + interval '{m.group(1)}', {_TS_FMT})", out)
    out = _DT_NOW.sub(f"to_char({_UTC}, {_TS_FMT})", out)
    out = _DATE_NOW.sub(f"to_char({_UTC}, 'YYYY-MM-DD')", out)
    out = _DATE_COL.sub(lambda m: f"to_char({m.group(1)}::timestamp, 'YYYY-MM-DD')", out)

    ignore = re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO", out, re.I)
    if ignore:
        out = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", out, flags=re.I)

    # ? → %s, but never inside quoted strings
    pieces, in_str, buf = [], False, []
    for ch in out:
        if ch == "'":
            in_str = not in_str
        buf.append("%s" if (ch == "?" and not in_str) else ch)
    out = "".join(buf)
    out = out.replace("%s%s", "%s%s")             # no-op, kept explicit for clarity

    if ignore:
        out = out.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return out


def translate_ddl(script):
    """Schema DDL → Postgres types."""
    out = script
    out = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", out, flags=re.I)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out, flags=re.I)
    out = _DT_NOW.sub(f"to_char({_UTC}, {_TS_FMT})", out)
    out = _DATE_NOW.sub(f"to_char({_UTC}, 'YYYY-MM-DD')", out)
    return out


# ---------------------------------------------------------------- connections
def _connect_pg():
    import psycopg
    from psycopg.rows import dict_row
    conn = psycopg.connect(_pg_url(), row_factory=dict_row, autocommit=False)
    return conn


def get_db():
    if "db" not in g:
        if is_postgres():
            g.db = _connect_pg()
            g.is_pg = True
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.is_pg = False
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    g.pop("is_pg", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------- query/exec
def query(sql, args=(), one=False):
    db = get_db()
    if is_postgres():
        with db.cursor() as cur:
            cur.execute(translate(sql), tuple(args))
            rows = [_clean(r) for r in cur.fetchall()]
    else:
        rows = db.execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def _tables_with_id():
    """Tables that actually have an `id` column, so INSERTs only ask for
    RETURNING id where it exists (no wasted failed statement + rollback)."""
    out = set()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", SCHEMA, re.S):
        if re.search(r"\bid\s+INTEGER\s+PRIMARY\s+KEY", m.group(2), re.I):
            out.add(m.group(1).lower())
    return out


_ID_TABLES = None


def _has_id(stmt):
    global _ID_TABLES
    if _ID_TABLES is None:
        _ID_TABLES = _tables_with_id()
    m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", stmt, re.I)
    return bool(m) and m.group(1).lower() in _ID_TABLES


def execute(sql, args=()):
    """Run a write. Returns the new row id for INSERTs (like sqlite lastrowid)."""
    db = get_db()
    if not is_postgres():
        cur = db.execute(sql, args)
        db.commit()
        return cur.lastrowid

    stmt = translate(sql)
    is_insert = _has_id(stmt) and " RETURNING " not in stmt.upper()
    with db.cursor() as cur:
        if is_insert:
            try:
                cur.execute(stmt + " RETURNING id", tuple(args))
                row = cur.fetchone()
                db.commit()
                return row["id"] if row else None
            except Exception as exc:                  # table has no id column
                if getattr(exc, "sqlstate", "") not in ("42703",):
                    db.rollback()
                    raise
                db.rollback()
        cur.execute(stmt, tuple(args))
        db.commit()
    return None


def _clean(row):
    """Postgres may hand back date/datetime objects; the app expects the ISO
    strings SQLite produces, so normalize once, here."""
    import datetime as _dt
    out = {}
    for k, v in row.items():
        if isinstance(v, _dt.datetime):
            out[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, _dt.date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------- migrations
MIGRATIONS = [
    # (table, column, ALTER statement) — applied only when the column is missing,
    # so existing production data is never touched or lost.
    ("users", "avatar",        "ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT '🙂'"),
    ("users", "age_range",     "ALTER TABLE users ADD COLUMN age_range TEXT"),
    ("users", "step_goal",     "ALTER TABLE users ADD COLUMN step_goal INTEGER NOT NULL DEFAULT 8000"),
    ("users", "health_goals",  "ALTER TABLE users ADD COLUMN health_goals TEXT"),
    ("users", "notif_enabled", "ALTER TABLE users ADD COLUMN notif_enabled INTEGER NOT NULL DEFAULT 1"),
    # Existing accounts default to verified so nobody already using the app
    # gets locked out; only NEW signups go through the OTP gate.
    ("users", "email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1"),
]


def _columns(db, table):
    if is_postgres():
        with db.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                        (table,))
            return {r["column_name"] for r in cur.fetchall()}
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def init_db(app):
    """Create tables, then apply additive column migrations (safe on live DBs)."""
    with app.app_context():
        db = get_db()
        if is_postgres():
            with db.cursor() as cur:
                cur.execute(translate_ddl(SCHEMA))
            db.commit()
        else:
            db.executescript(SCHEMA)
        for table, col, stmt in MIGRATIONS:
            if col not in _columns(db, table):
                if is_postgres():
                    with db.cursor() as cur:
                        cur.execute(stmt)
                else:
                    db.execute(stmt)
        db.commit()
        app.logger.info("[db] using %s", "postgres" if is_postgres() else "sqlite")
