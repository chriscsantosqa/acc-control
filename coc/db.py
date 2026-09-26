"""Persistência em SQLite (arquivo local coc_control.db).

Multiusuário: cada vila (`accounts`) pertence a um usuário (`users`). Há um único
dono (`owner`, o login ADMIN_USER de sempre, dono das vilas que já existiam) e os
assinantes (`subscriber`), que entram pela Clash Labs. Toda leitura de vila recebe
o `user_id` de quem pede: sem ele não há consulta, então um assinante nunca
alcança a vila de outro. Snapshots e estatísticas são alcançados só depois que a
vila foi conferida.
"""
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

# criados depois da migração: em bancos antigos a coluna user_id só existe após ela
POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
"""

_ready = set()


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if DB_PATH not in _ready:
        con.executescript(SCHEMA)
        _migrate(con)
        con.executescript(POST_MIGRATION)
        _ready.add(DB_PATH)
    return con


# ------------------------------------------------------------ migração multiusuário
def _cols(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def _locked(con, fn):
    """Roda `fn` numa transação exclusiva, com as chaves estrangeiras desligadas.

    Desligadas porque recriar `accounts` passa por um DROP TABLE, e com elas
    ligadas o DROP apagaria em cascata todos os snapshots (receita oficial do
    SQLite para alterar tabela: https://sqlite.org/lang_altertable.html#otheralter).
    """
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
    r = con.execute("SELECT id FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    if r:
        return r["id"]
    return con.execute("INSERT INTO users(role, name, created_at) VALUES('owner', 'Dono', ?)",
                       (int(time.time()),)).lastrowid


def _migrate(con):
    if "user_id" not in _cols(con, "accounts"):
        def rebuild():
            cols = _cols(con, "accounts")
            if "user_id" in cols:          # outra conexão migrou enquanto esperávamos
                return
            owner = _owner_in_tx(con)
            verified = "verified, verified_at" if "verified" in cols else "0, NULL"
            con.execute(ACCOUNTS_TABLE.format(name="accounts_v2"))
            con.execute(
                "INSERT INTO accounts_v2(id, user_id, tag, name, notes, created_at, updated_at, verified, verified_at) "
                f"SELECT id, ?, tag, name, notes, created_at, updated_at, {verified} FROM accounts", (owner,))
            con.execute("DROP TABLE accounts")
            con.execute("ALTER TABLE accounts_v2 RENAME TO accounts")
        _locked(con, rebuild)

    if not con.execute("SELECT 1 FROM settings WHERE key='schema_multiuser'").fetchone():
        def move_settings():
            if con.execute("SELECT 1 FROM settings WHERE key='schema_multiuser'").fetchone():
                return
            owner = _owner_in_tx(con)
            # alertas e preferências eram do único usuário: passam a ser do dono
            for key in USER_DEFAULTS:
                r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if r:
                    con.execute("INSERT OR IGNORE INTO user_settings(user_id, key, value) VALUES(?,?,?)",
                                (owner, key, r["value"]))
                    con.execute("DELETE FROM settings WHERE key=?", (key,))
            # a API key antiga continua valendo (automação já configurada), agora guardada só como hash
            r = con.execute("SELECT value FROM settings WHERE key='api_key'").fetchone()
            if r:
                key = json.loads(r["value"]) or ""
                if key:
                    con.execute("UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?",
                                (_hash_key(key), key[-4:], owner))
                con.execute("DELETE FROM settings WHERE key='api_key'")
            con.execute("INSERT INTO settings(key, value) VALUES('schema_multiuser', '1')")
        _locked(con, move_settings)


# ------------------------------------------------------------ usuários
def _hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def owner_id(con):
    r = con.execute("SELECT id FROM users WHERE role='owner' ORDER BY id LIMIT 1").fetchone()
    if r:
        return r["id"]
    uid = con.execute("INSERT INTO users(role, name, created_at) VALUES('owner', 'Dono', ?)",
                      (int(time.time()),)).lastrowid
    con.commit()
    return uid


def get_user(con, user_id):
    if user_id is None:
        return None
    r = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def get_user_by_labs(con, labs_user_id):
    r = con.execute("SELECT * FROM users WHERE labs_user_id=?", (labs_user_id,)).fetchone()
    return dict(r) if r else None


def upsert_labs_user(con, labs_user_id, email, name):
    """Assinante que entrou pela Clash Labs. A ligação é pelo id da Clash Labs, nunca pelo e-mail."""
    now = int(time.time())
    u = get_user_by_labs(con, labs_user_id)
    if u:
        con.execute("UPDATE users SET email=?, name=?, last_login_at=? WHERE id=?",
                    (email, name, now, u["id"]))
    else:
        con.execute("INSERT INTO users(role, labs_user_id, email, name, created_at, last_login_at) "
                    "VALUES('subscriber', ?, ?, ?, ?, ?)", (labs_user_id, email, name, now, now))
    con.commit()
    return get_user_by_labs(con, labs_user_id)


def set_access(con, user_id, access_until, checked_at=None):
    con.execute("UPDATE users SET access_until=?, checked_at=? WHERE id=?",
                (access_until, checked_at or int(time.time()), user_id))
    con.commit()


def touch_login(con, user_id):
    con.execute("UPDATE users SET last_login_at=? WHERE id=?", (int(time.time()), user_id))
    con.commit()


def user_by_api_key(con, key):
    if not key:
        return None
    r = con.execute("SELECT * FROM users WHERE api_key_hash=?", (_hash_key(key),)).fetchone()
    return dict(r) if r else None


def new_api_key(con, user_id):
    """Gera (ou troca) a API key do usuário. Só o hash fica no banco: a chave aparece uma vez."""
    key = secrets.token_urlsafe(32)
    con.execute("UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?",
                (_hash_key(key), key[-4:], user_id))
    con.commit()
    return key


def users_to_notify(con, now):
    """Dono sempre; assinante só com o passe em dia."""
    rows = con.execute("SELECT * FROM users WHERE role='owner' OR access_until > ? ORDER BY id", (now,))
    return [dict(r) for r in rows]


def subscribers_due(con, now, stale_s=6 * 3600, soon_s=86400, min_gap_s=3600, limit=50):
    """Assinantes cujo passe convém reler na Clash Labs: nunca conferidos, conferidos há muito
    tempo ou vencendo logo. Quem foi conferido há menos de `min_gap_s` fica para a próxima."""
    rows = con.execute(
        "SELECT * FROM users WHERE role='subscriber' AND labs_user_id IS NOT NULL AND ("
        " checked_at IS NULL OR checked_at < ? OR (access_until IS NOT NULL AND access_until < ? AND checked_at < ?)"
        ") ORDER BY COALESCE(checked_at, 0) LIMIT ?",
        (now - stale_s, now + soon_s, now - min_gap_s, limit))
    return [dict(r) for r in rows]


def list_subscribers(con):
    rows = con.execute(
        "SELECT u.id, u.email, u.name, u.access_until, u.checked_at, u.created_at, u.last_login_at, "
        "(SELECT COUNT(*) FROM accounts a WHERE a.user_id = u.id) AS villages "
        "FROM users u WHERE u.role='subscriber' ORDER BY u.created_at DESC")
    return [dict(r) for r in rows]


# ------------------------------------------------------------ vilas (sempre de um usuário)
def set_verified(con, user_id, account_id, ok=True):
    con.execute("UPDATE accounts SET verified=?, verified_at=? WHERE id=? AND user_id=?",
                (1 if ok else 0, int(time.time()), account_id, user_id))
    con.commit()


def list_accounts(con, user_id):
    return [dict(r) for r in con.execute(
        "SELECT * FROM accounts WHERE user_id=? ORDER BY name", (user_id,)).fetchall()]


def count_accounts(con, user_id):
    return con.execute("SELECT COUNT(*) FROM accounts WHERE user_id=?", (user_id,)).fetchone()[0]


def get_account(con, user_id, account_id):
    r = con.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, user_id)).fetchone()
    return dict(r) if r else None


def get_account_by_tag(con, user_id, tag):
    r = con.execute("SELECT * FROM accounts WHERE tag=? AND user_id=?", (tag, user_id)).fetchone()
    return dict(r) if r else None


def create_account(con, user_id, name, tag=None, notes=""):
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO accounts(user_id, tag, name, notes, created_at, updated_at) VALUES(?,?,?,?,?,?)",
        (user_id, tag, name, notes, now, now))
    con.commit()
    return get_account(con, user_id, cur.lastrowid)


def update_account(con, user_id, account_id, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("name", "tag", "notes") and v is not None}
    if not allowed:
        return get_account(con, user_id, account_id)
    sets = ", ".join(f"{k}=?" for k in allowed)
    con.execute(f"UPDATE accounts SET {sets}, updated_at=? WHERE id=? AND user_id=?",
                (*allowed.values(), int(time.time()), account_id, user_id))
    con.commit()
    return get_account(con, user_id, account_id)


def delete_account(con, user_id, account_id):
    con.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (account_id, user_id))
    con.commit()


# ------------------------------------------------------------ snapshots
# Recebem um account_id que o chamador já conferiu com get_account(user_id, ...).
def add_snapshot(con, account_id, taken_at, raw_json, parsed):
    now = int(time.time())
    cur = con.execute(
        "INSERT INTO snapshots(account_id, taken_at, imported_at, th_level, raw_json, parsed_json) "
        "VALUES(?,?,?,?,?,?)",
        (account_id, taken_at or now, now, parsed.get("th_level"),
         raw_json, json.dumps(parsed, ensure_ascii=False)))
    con.execute("UPDATE accounts SET updated_at=? WHERE id=?", (now, account_id))
    con.commit()
    return cur.lastrowid


def prune_snapshots(con, account_id, keep):
    """Mantém só os `keep` snapshots mais recentes da vila."""
    con.execute(
        "DELETE FROM snapshots WHERE account_id=? AND id NOT IN ("
        " SELECT id FROM snapshots WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT ?)",
        (account_id, account_id, keep))
    con.commit()


def latest_snapshot(con, account_id):
    r = con.execute(
        "SELECT * FROM snapshots WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT 1",
        (account_id,)).fetchone()
    return dict(r) if r else None


def list_snapshots(con, account_id, limit=200):
    rows = con.execute(
        "SELECT id, account_id, taken_at, imported_at, th_level FROM snapshots "
        "WHERE account_id=? ORDER BY taken_at DESC, id DESC LIMIT ?",
        (account_id, limit)).fetchall()
    return [dict(r) for r in rows]


def count_snapshots(con, account_id):
    return con.execute("SELECT COUNT(*) FROM snapshots WHERE account_id=?", (account_id,)).fetchone()[0]


def get_snapshot(con, snapshot_id):
    r = con.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
    return dict(r) if r else None


def delete_snapshot(con, user_id, snapshot_id):
    con.execute("DELETE FROM snapshots WHERE id=? AND account_id IN (SELECT id FROM accounts WHERE user_id=?)",
                (snapshot_id, user_id))
    con.commit()


# ------------------------------------------------------------ settings
# Preferências de cada usuário (alertas e canais).
USER_DEFAULTS = {
    "notify_enabled": False,
    "toast_enabled": True,
    "telegram_token": "",
    "telegram_chat_id": "",
    "discord_webhook": "",
    "lead_minutes": 30,
    "digest_time": "",          # "08:00" ou vazio p/ desligar
    "supercell_autosync": True,
    "evolution_url": "",
    "evolution_apikey": "",
    "evolution_instance": "principal",
    "evolution_number": "",
}
# Do servidor, só o dono altera: a chave da Supercell é presa ao IP da máquina.
GLOBAL_DEFAULTS = {
    "supercell_token": "",
}
# Mantido para quem importava o nome antigo.
DEFAULT_SETTINGS = {**USER_DEFAULTS, **GLOBAL_DEFAULTS}


def _get_global(con, key):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not r:
        return GLOBAL_DEFAULTS.get(key)
    try:
        return json.loads(r["value"])
    except Exception:
        return r["value"]


def get_settings(con, user_id):
    """Preferências do usuário + valores do servidor usados por ele (supercell_token).
    Quem responde a um navegador filtra o que o papel do usuário pode ver."""
    out = dict(USER_DEFAULTS)
    for r in con.execute("SELECT key, value FROM user_settings WHERE user_id=?", (user_id,)):
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            out[r["key"]] = r["value"]
    for k in GLOBAL_DEFAULTS:
        out[k] = _get_global(con, k)
    return out


def set_settings(con, user_id, updates):
    """Grava só chaves conhecidas. As do servidor, só para o dono."""
    user = get_user(con, user_id)
    is_owner = bool(user and user["role"] == "owner")
    for k, v in updates.items():
        if k in USER_DEFAULTS:
            con.execute("INSERT INTO user_settings(user_id, key, value) VALUES(?, ?, ?) "
                        "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value",
                        (user_id, k, json.dumps(v)))
        elif k in GLOBAL_DEFAULTS and is_owner:
            con.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, json.dumps(v)))
    con.commit()
    return get_settings(con, user_id)


# ------------------------------------------------------------ notified (dedupe)
def was_notified(con, key):
    return con.execute("SELECT 1 FROM notified WHERE key=?", (key,)).fetchone() is not None


def mark_notified(con, key):
    con.execute("INSERT OR IGNORE INTO notified(key, sent_at) VALUES(?, ?)",
                (key, int(time.time())))
    con.commit()


# ------------------------------------------------------------ player stats (Supercell API)
def add_player_stats(con, account_id, payload):
    con.execute("INSERT INTO player_stats(account_id, fetched_at, json) VALUES(?,?,?)",
                (account_id, int(time.time()), json.dumps(payload, ensure_ascii=False)))
    con.commit()


def latest_player_stats(con, account_id):
    r = con.execute("SELECT * FROM player_stats WHERE account_id=? ORDER BY fetched_at DESC LIMIT 1",
                    (account_id,)).fetchone()
    return dict(r) if r else None


def player_stats_series(con, account_id, limit=120):
    rows = con.execute("SELECT fetched_at, json FROM player_stats WHERE account_id=? "
                       "ORDER BY fetched_at DESC LIMIT ?", (account_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]
