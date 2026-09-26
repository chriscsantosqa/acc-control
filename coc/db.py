"""Persistência SQLite multiusuário do COC Control."""
import hashlib
import json
import os
import secrets
import sqlite3
import time

DB_PATH = os.environ.get("COC_DB", os.path.join(os.path.dirname(__file__), "..", "coc_control.db"))

ACCOUNTS_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tag TEXT,
    name TEXT NOT NULL,
    notes TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    verified INTEGER DEFAULT 0,
    verified_at INTEGER,
    UNIQUE(user_id, tag)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'subscriber')),
    labs_user_id TEXT UNIQUE,
    email TEXT,
    name TEXT,
    access_until INTEGER,
    checked_at INTEGER,
    suspended_at INTEGER,
    suspension_reason TEXT,
    api_key_hash TEXT UNIQUE,
    api_key_hint TEXT,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (user_id, key)
);
""" + ACCOUNTS_TABLE.format(name="accounts") + """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    taken_at INTEGER NOT NULL,
    imported_at INTEGER NOT NULL,
    th_level INTEGER,
    raw_json TEXT NOT NULL,
    parsed_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_account ON snapshots(account_id, taken_at DESC);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    ip TEXT PRIMARY KEY,
    fails INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS access_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event TEXT NOT NULL,
    source TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_access_audit_user ON access_audit(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS notified (
    key TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    fetched_at INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stats_account ON player_stats(account_id, fetched_at DESC);
"""

POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
"""

_ready = set()


def _table_columns(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")} if table else set()


def _migration_required(con):
    tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables:
        return False
    if "accounts" in tables and "user_id" not in _table_columns(con, "accounts"):
        return True
    if "users" not in tables:
        return True
    if not {"suspended_at", "suspension_reason"}.issubset(_table_columns(con, "users")):
        return True
    return "access_audit" not in tables


def _backup_before_migration(con):
    """Faz backup consistente antes de alterar schema de banco existente."""
    if DB_PATH == ":memory:" or not os.path.isfile(DB_PATH) or not _migration_required(con):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = f"{DB_PATH}.pre-migration-{stamp}.bak"
    if os.path.exists(dest):
        dest += f".{os.getpid()}"
    out = sqlite3.connect(dest)
    try:
        con.backup(out)
    finally:
        out.close()
    return dest


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if DB_PATH not in _ready:
        _backup_before_migration(con)
        con.executescript(SCHEMA)
        _migrate(con)
        con.executescript(POST_MIGRATION)
        _ready.add(DB_PATH)
    return con


def _cols(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def _locked(con, fn):
    iso = con.isolation_level
    con.isolation_level = None
    con.execute("PRAGMA foreign_keys = OFF")
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            fn()
            bad = con.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise RuntimeError(f"migração deixaria referências quebradas: {len(bad)}")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.execute("PRAGMA foreign_keys = ON")
        con.isolation_level = iso


def _owner_in_tx(con):
    row = con.execute("SELECT id FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    return con.execute(
        "INSERT INTO users(role, name, created_at) VALUES('owner', 'Dono', ?)",
        (int(time.time()),),
    ).lastrowid


def _migrate(con):
    user_cols = _cols(con, "users")
    if "suspended_at" not in user_cols:
        con.execute("ALTER TABLE users ADD COLUMN suspended_at INTEGER")
    if "suspension_reason" not in user_cols:
        con.execute("ALTER TABLE users ADD COLUMN suspension_reason TEXT")

    if "user_id" not in _cols(con, "accounts"):
        def rebuild():
            cols = _cols(con, "accounts")
            if "user_id" in cols:
                return
            owner = _owner_in_tx(con)
            verified = "verified, verified_at" if "verified" in cols else "0, NULL"
            con.execute(ACCOUNTS_TABLE.format(name="accounts_v2"))
            con.execute(
                "INSERT INTO accounts_v2(id, user_id, tag, name, notes, created_at, updated_at, verified, verified_at) "
                f"SELECT id, ?, tag, name, notes, created_at, updated_at, {verified} FROM accounts",
                (owner,),
            )
            con.execute("DROP TABLE accounts")
            con.execute("ALTER TABLE accounts_v2 RENAME TO accounts")
        _locked(con, rebuild)

    if not con.execute("SELECT 1 FROM settings WHERE key='schema_multiuser'").fetchone():
        def move_settings():
            if con.execute("SELECT 1 FROM settings WHERE key='schema_multiuser'").fetchone():
                return
            owner = _owner_in_tx(con)
            for key in USER_DEFAULTS:
                row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if row:
                    con.execute(
                        "INSERT OR IGNORE INTO user_settings(user_id, key, value) VALUES(?,?,?)",
                        (owner, key, row["value"]),
                    )
                    con.execute("DELETE FROM settings WHERE key=?", (key,))
            row = con.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
            if row:
                key = json.loads(row["value"]) or ""
                if key:
                    con.execute(
                        "UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?",
                        (_hash_key(key), key[-4:], owner),
                    )
                con.execute("DELETE FROM settings WHERE key='api_key'")
            con.execute("INSERT INTO settings(key, value) VALUES('schema_multiuser', '1')")
        _locked(con, move_settings)


def audit_access(con, user_id, event, source, detail=""):
    con.execute(
        "INSERT INTO access_audit(user_id, event, source, detail, created_at) VALUES(?,?,?,?,?)",
        (user_id, event, source, str(detail or "")[:1000], int(time.time())),
    )
    con.commit()


def _hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def owner_id(con):
    row = con.execute("SELECT id FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    uid = con.execute(
        "INSERT INTO users(role, name, created_at) VALUES('owner', 'Dono', ?)",
        (int(time.time()),),
    ).lastrowid
    con.commit()
    return uid


def get_user(con, user_id):
    if user_id is None:
        return None
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_labs(con, labs_user_id):
    row = con.execute("SELECT * FROM users WHERE labs_user_id=?", (labs_user_id,)).fetchone()
    return dict(row) if row else None


def upsert_labs_user(con, labs_user_id, email, name):
    """Vínculo sempre por labs_user_id. E-mail e nome são apenas apresentação."""
    now = int(time.time())
    user = get_user_by_labs(con, labs_user_id)
    created = False
    if user:
        con.execute(
            "UPDATE users SET email=?, name=?, last_login_at=? WHERE id=?",
            (email, name, now, user["id"]),
        )
    else:
        con.execute(
            "INSERT INTO users(role, labs_user_id, email, name, created_at, last_login_at) "
            "VALUES('subscriber', ?, ?, ?, ?, ?)",
            (labs_user_id, email, name, now, now),
        )
        created = True
    con.commit()
    user = get_user_by_labs(con, labs_user_id)
    if created:
        audit_access(con, user["id"], "labs-linked", "clash-labs", labs_user_id)
    return user


def set_access(con, user_id, access_until, checked_at=None):
    before = get_user(con, user_id)
    con.execute(
        "UPDATE users SET access_until=?, checked_at=? WHERE id=?",
        (access_until, checked_at or int(time.time()), user_id),
    )
    con.commit()
    if before and before.get("access_until") != access_until:
        audit_access(
            con,
            user_id,
            "entitlement-updated",
            "clash-labs",
            json.dumps({"before": before.get("access_until"), "after": access_until}),
        )


def touch_login(con, user_id):
    con.execute("UPDATE users SET last_login_at=? WHERE id=?", (int(time.time()), user_id))
    con.commit()


def user_by_api_key(con, key):
    if not key:
        return None
    row = con.execute("SELECT * FROM users WHERE api_key_hash=?", (_hash_key(key),)).fetchone()
    return dict(row) if row else None


def new_api_key(con, user_id):
    key = secrets.token_urlsafe(32)
    con.execute(
        "UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?",
        (_hash_key(key), key[-4:], user_id),
    )
    con.commit()
    return key


def users_to_notify(con, now):
    rows = con.execute(
        "SELECT * FROM users WHERE role='owner' OR (suspended_at IS NULL AND access_until > ?) ORDER BY id",
        (now,),
    )
    return [dict(r) for r in rows]


def subscribers_due(con, now, stale_s=6 * 3600, soon_s=86400, min_gap_s=3600, limit=50):
    rows = con.execute(
        "SELECT * FROM users WHERE role='subscriber' AND labs_user_id IS NOT NULL AND ("
        " checked_at IS NULL OR checked_at < ? OR (access_until IS NOT NULL AND access_until < ? AND checked_at < ?)"
        ") ORDER BY COALESCE(checked_at, 0) LIMIT ?",
        (now - stale_s, now + soon_s, now - min_gap_s, limit),
    )
    return [dict(r) for r in rows]


def list_subscribers(con):
    rows = con.execute(
        "SELECT u.id, u.labs_user_id, u.email, u.name, u.access_until, u.checked_at, "
        "u.suspended_at, u.suspension_reason, u.created_at, u.last_login_at, "
        "(SELECT COUNT(*) FROM accounts a WHERE a.user_id = u.id) AS villages "
        "FROM users u WHERE u.role='subscriber' ORDER BY u.created_at DESC"
    )
    return [dict(r) for r in rows]


def set_user_suspension(con, user_id, suspended, reason=""):
    user = get_user(con, user_id)
    if not user or user["role"] != "subscriber":
        return None
    now = int(time.time()) if suspended else None
    clean_reason = str(reason or "").strip()[:500] if suspended else None
    con.execute(
        "UPDATE users SET suspended_at=?, suspension_reason=? WHERE id=?",
        (now, clean_reason, user_id),
    )
    con.commit()
    audit_access(
        con,
        user_id,
        "manual-suspended" if suspended else "manual-reactivated",
        "owner",
        clean_reason or "",
    )
    return get_user(con, user_id)


def _json_or_text(value):
    try:
        return json.loads(value)
    except Exception:
        return value


def export_user_data(con, user_id):
    user = get_user(con, user_id)
    if not user:
        return None
    safe_user = {
        key: user.get(key)
        for key in (
            "id", "role", "labs_user_id", "email", "name", "access_until", "checked_at",
            "suspended_at", "suspension_reason", "created_at", "last_login_at", "api_key_hint",
        )
    }
    settings = {}
    for row in con.execute("SELECT key, value FROM user_settings WHERE user_id=? ORDER BY key", (user_id,)):
        settings[row["key"]] = _json_or_text(row["value"])
    accounts = []
    for acc in list_accounts(con, user_id):
        item = dict(acc)
        item["snapshots"] = []
        for snap in con.execute(
            "SELECT id, taken_at, imported_at, th_level, raw_json, parsed_json FROM snapshots "
            "WHERE account_id=? ORDER BY taken_at, id",
            (acc["id"],),
        ):
            value = dict(snap)
            value["raw_json"] = _json_or_text(value["raw_json"])
            value["parsed_json"] = _json_or_text(value["parsed_json"])
            item["snapshots"].append(value)
        item["player_stats"] = []
        for stats in con.execute(
            "SELECT id, fetched_at, json FROM player_stats WHERE account_id=? ORDER BY fetched_at, id",
            (acc["id"],),
        ):
            value = dict(stats)
            value["json"] = _json_or_text(value["json"])
            item["player_stats"].append(value)
        accounts.append(item)
    audit = [
        dict(r)
        for r in con.execute(
            "SELECT event, source, detail, created_at FROM access_audit WHERE user_id=? ORDER BY id",
            (user_id,),
        )
    ]
    return {"user": safe_user, "settings": settings, "accounts": accounts, "access_audit": audit}


def delete_subscriber_data(con, user_id):
    user = get_user(con, user_id)
    if not user or user["role"] != "subscriber":
        return False
    audit_access(con, user_id, "data-deleted", "self-service", "LGPD")
    con.execute("DELETE FROM users WHERE id=?", (user_id,))
    con.commit()
    return True


def set_verified(con, user_id, account_id, ok=True):
    con.execute(
        "UPDATE accounts SET verified=?, verified_at=? WHERE id=? AND user_id=?",
        (1 if ok else 0, int(time.time()), account_id, user_id),
    )
    con.commit()


def list_accounts(con, user_id):
    return [dict(r) for r in con.execute("SELECT * FROM accounts WHERE user_id=? ORDER BY name", (user_id,)).fetchall()]


def count_accounts(con, user_id):
    return con.execute("SELECT COUNT(*) FROM accounts WHERE user_id=?", (user_id,)).fetchone()[0]


def get_account(con, user_id, account_id):
    row = con.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, user_id)).fetchone()
    return dict(row) if row else None


def get_account_by_tag(con, user_id, tag):
    row = con.execute("SELECT * FROM accounts WHERE tag=? AND user_id=?", (tag, user_id)).fetchone()
    return dict(row) if row else None


def create_account(con, user_id, name, tag=None, notes=""):
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO accounts(user_id, tag, name, notes, created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (user_id, tag, name, notes, now, now),
    )
    con.commit()
    return get_account(con, user_id, cur.lastrowid)


def update_account(con, user_id, account_id, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("name", "tag", "notes") and v is not None}
    if not allowed:
        return get_account(con, user_id, account_id)
    sets = ", ".join(f"{k}=?" for k in allowed)
    con.execute(
        f"UPDATE accounts SET {sets}, updated_at=? WHERE id=? AND user_id=?",
        (*allowed.values(), int(time.time()), account_id, user_id),
    )
    con.commit()
    return get_account(con, user_id, account_id)


def delete_account(con, user_id, account_id):
    con.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (account_id, user_id))
    con.commit()


def add_snapshot(con, account_id, taken_at, raw_json, parsed):
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO snapshots(account_id, taken_at, imported_at, th_level, raw_json, parsed_json) VALUES(?,?,?,?,?,?)",
        (account_id, taken_at or now, now, parsed.get("th_level"), raw_json, json.dumps(parsed, ensure_ascii=False)),
    )
    con.execute("UPDATE accounts SET updated_at=? WHERE id=?", (now, account_id))
    con.commit()
    return cur.lastrowid


def prune_snapshots(con, account_id, keep):
    con.execute(
        "DELETE FROM snapshots WHERE account_id=? AND id NOT IN ("
        " SELECT id FROM snapshots WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT ?)",
        (account_id, account_id, keep),
    )
    con.commit()


def latest_snapshot(con, account_id):
    row = con.execute(
        "SELECT * FROM snapshots WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def list_snapshots(con, account_id, limit=200):
    rows = con.execute(
        "SELECT id, account_id, taken_at, imported_at, th_level FROM snapshots "
        "WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def count_snapshots(con, account_id):
    return con.execute("SELECT COUNT(*) FROM snapshots WHERE account_id=?", (account_id,)).fetchone()[0]


def get_snapshot(con, snapshot_id):
    row = con.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    return dict(row) if row else None


def delete_snapshot(con, user_id, snapshot_id):
    con.execute(
        "DELETE FROM snapshots WHERE id=? AND account_id IN (SELECT id FROM accounts WHERE user_id=?)",
        (snapshot_id, user_id),
    )
    con.commit()


USER_DEFAULTS = {
    "notify_enabled": False,
    "toast_enabled": True,
    "telegram_token": "",
    "telegram_chat_id": "",
    "discord_webhook": "",
    "lead_minutes": 30,
    "digest_time": "",
    "supercell_autosync": True,
    "evolution_url": "",
    "evolution_apikey": "",
    "evolution_instance": "principal",
    "evolution_number": "",
}
GLOBAL_DEFAULTS = {"supercell_token": ""}
DEFAULT_SETTINGS = {**USER_DEFAULTS, **GLOBAL_DEFAULTS}


def _get_global(con, key):
    row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return GLOBAL_DEFAULTS.get(key)
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def get_settings(con, user_id):
    out = dict(USER_DEFAULTS)
    for row in con.execute("SELECT key, value FROM user_settings WHERE user_id=?", (user_id,)):
        try:
            out[row["key"]] = json.loads(row["value"])
        except Exception:
            out[row["key"]] = row["value"]
    for key in GLOBAL_DEFAULTS:
        out[key] = _get_global(con, key)
    return out


def set_settings(con, user_id, updates):
    user = get_user(con, user_id)
    is_owner = bool(user and user["role"] == "owner")
    for key, value in updates.items():
        if key in USER_DEFAULTS:
            con.execute(
                "INSERT INTO user_settings(user_id, key, value) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value",
                (user_id, key, json.dumps(value)),
            )
        elif key in GLOBAL_DEFAULTS and is_owner:
            con.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
    con.commit()
    return get_settings(con, user_id)


def was_notified(con, key):
    return con.execute("SELECT 1 FROM notified WHERE key=?", (key,)).fetchone() is not None


def mark_notified(con, key):
    con.execute("INSERT OR IGNORE INTO notified(key, sent_at) VALUES(?, ?)", (key, int(time.time())))
    con.commit()


def add_player_stats(con, account_id, payload):
    con.execute(
        "INSERT INTO player_stats(account_id, fetched_at, json) VALUES(?,?,?)",
        (account_id, int(time.time()), json.dumps(payload, ensure_ascii=False)),
    )
    con.commit()


def latest_player_stats(con, account_id):
    row = con.execute(
        "SELECT * FROM player_stats WHERE account_id=? ORDER BY fetched_at DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return dict(row) if row else None


def player_stats_series(con, account_id, limit=120):
    rows = con.execute(
        "SELECT fetched_at, json FROM player_stats WHERE account_id=? ORDER BY fetched_at DESC LIMIT ?",
        (account_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
