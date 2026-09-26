"""
Autenticação e proteção do COC Control em rede/VPS.

Camadas:
  * login com senha (hash scrypt via werkzeug) — usuário/senha vêm de env
    (ADMIN_USER / ADMIN_PASSWORD ou ADMIN_PASSWORD_HASH) ou do banco
    (--set-password);
  * sessão em cookie assinado HttpOnly + SameSite=Lax (Secure com COC_HTTPS=1);
  * CSRF por double-submit cookie (header X-CSRF em métodos mutantes);
  * bloqueio progressivo por IP após falhas de login (anti brute-force);
  * API key (Bearer) por usuário para acessos programáticos (watcher remoto /
    automação); o banco guarda só o hash, e a chave identifica o dono dela;
  * headers de segurança (CSP, nosniff, frame-deny, referrer).

A autenticação LIGA automaticamente quando há senha configurada (env ou banco),
COC_AUTH=1 ou a Clash Labs configurada (assinantes precisam de login). Uso local
no Windows sem senha continua funcionando sem login.

O usuário/senha do .env é o DONO. Assinantes não têm senha aqui: entram pela
Clash Labs (coc/labs.py).
"""
import hmac
import json
import os
import secrets
import time

from werkzeug.security import check_password_hash, generate_password_hash

from . import db, labs

LOCK_BASE_FAILS = 5          # a partir da 5ª falha começa a bloquear
LOCK_MAX_MIN = 60


def admin_user():
    return os.environ.get("ADMIN_USER", "admin")


def _db_hash(con):
    r = con.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
    return json.loads(r["value"]) if r else None


def password_hash(con):
    """Hash da senha: env ADMIN_PASSWORD_HASH > env ADMIN_PASSWORD > banco."""
    h = os.environ.get("ADMIN_PASSWORD_HASH")
    if h:
        return h
    pw = os.environ.get("ADMIN_PASSWORD")
    if pw:
        return generate_password_hash(pw)
    return _db_hash(con)


def set_password(con, password):
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('admin_password_hash', ?)",
                (json.dumps(generate_password_hash(password)),))
    con.commit()


def enabled(con):
    if labs.enabled():
        return True             # com assinantes, nunca há modo aberto
    if os.environ.get("COC_AUTH") == "0":
        return False
    return bool(password_hash(con)) or os.environ.get("COC_AUTH") == "1"


def secret_key(con):
    """Chave de sessão: env SECRET_KEY ou gerada e persistida no banco."""
    k = os.environ.get("SECRET_KEY")
    if k:
        return k
    r = con.execute("SELECT value FROM settings WHERE key='secret_key'").fetchone()
    if r:
        return json.loads(r["value"])
    k = secrets.token_hex(32)
    con.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('secret_key', ?)",
                (json.dumps(k),))
    con.commit()
    return k


# ------------------------------------------------ brute force por IP
def check_locked(con, ip):
    """Retorna segundos restantes de bloqueio (0 = liberado)."""
    r = con.execute("SELECT locked_until FROM login_attempts WHERE ip=?", (ip,)).fetchone()
    if not r:
        return 0
    return max(0, r["locked_until"] - int(time.time()))


def register_fail(con, ip):
    r = con.execute("SELECT fails FROM login_attempts WHERE ip=?", (ip,)).fetchone()
    fails = (r["fails"] if r else 0) + 1
    locked_until = 0
    if fails >= LOCK_BASE_FAILS:
        minutes = min(LOCK_MAX_MIN, 2 ** (fails - LOCK_BASE_FAILS))
        locked_until = int(time.time()) + minutes * 60
    con.execute("INSERT OR REPLACE INTO login_attempts(ip, fails, locked_until) VALUES(?,?,?)",
                (ip, fails, locked_until))
    con.commit()
    return fails, locked_until


def register_success(con, ip):
    con.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
    con.commit()


def verify_login(con, ip, username, password):
    """(ok, erro). Compara com tempo constante e aplica lockout."""
    wait = check_locked(con, ip)
    if wait:
        return False, f"muitas tentativas — aguarde {max(1, wait // 60)} min"
    h = password_hash(con)
    user_ok = hmac.compare_digest((username or "").encode(), admin_user().encode())
    pass_ok = bool(h) and check_password_hash(h, password or "")
    if user_ok and pass_ok:
        register_success(con, ip)
        return True, None
    fails, locked = register_fail(con, ip)
    if locked:
        return False, "credenciais inválidas — acesso bloqueado temporariamente"
    return False, "usuário ou senha inválidos"


def check_bearer(con, auth_header):
    """'Authorization: Bearer <api_key>' -> id do usuário dono da chave, ou None.
    A busca é pelo sha256 da chave (índice único), então não há comparação a cronometrar."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    if not 20 <= len(token) <= 200:
        return None
    user = db.user_by_api_key(con, token)
    return user["id"] if user else None


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; "
                                "style-src 'self' 'unsafe-inline'; "
                                "script-src 'self' 'unsafe-inline'; "
                                "connect-src 'self'; frame-ancestors 'none'"),
}
