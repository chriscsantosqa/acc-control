"""
Passe do COC Control vendido na Clash Labs.

Cada assinante tem a própria conta aqui, com as próprias vilas e alertas. Ninguém
cria senha no COC Control: o assinante entra pela Clash Labs.

Entrada (parecido com OAuth):
  1. GET /entrar/clash-labs     -> guarda um `state` na sessão deste navegador e manda
                                   para <LABS_URL>/app/coc-control?state=...
  2. a vitrine confere login e passe e volta para /api/labs/callback?code=...&state=...
  3. o servidor confere o `state` com a sessão e troca o código com LABS_PRODUCT_SECRET.
Quem chega da vitrine sem `state` (botão Abrir) volta para o passo 1: o código dele nunca
é trocado, então um link com o código de outra pessoa não faz ninguém entrar na conta errada.

O passe muda (pagamento, renovação, cancelamento, reembolso): a vitrine avisa em
POST /api/labs/webhook {userId}; o aviso só diz quem mudou, e o passe é relido aqui.
O Notifier também relê periodicamente quem está sem conferência recente.

Desligado enquanto LABS_URL e LABS_PRODUCT_SECRET (32+ caracteres) não estão no .env.
"""
import datetime as _dt
import hashlib
import hmac
import os
import re
import secrets
import time

try:
    import requests
except ImportError:
    requests = None

from . import db

PRODUCT = "coc-control"
STATE_TTL_S = 600
LABS_USER_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _env():
    url = (os.environ.get("LABS_URL") or "").rstrip("/")
    api = (os.environ.get("LABS_API_URL") or url).rstrip("/")
    return url, api, os.environ.get("LABS_PRODUCT_SECRET") or ""


def enabled():
    url, _, secret = _env()
    return bool(url and len(secret) >= 32)


def store_url():
    url, _, _ = _env()
    return f"{url}/?produto={PRODUCT}#planos" if url else None


def account_url():
    url, _, _ = _env()
    return f"{url}/conta" if url else None


class LabsError(Exception):
    pass


def _hub(path, method="GET", body=None):
    if not requests:
        raise LabsError("pacote 'requests' não instalado")
    _, api, secret = _env()
    r = requests.request(method, f"{api}{path}", json=body, timeout=8, allow_redirects=False,
                         headers={"Authorization": f"Bearer {secret}", "X-Labs-Product": PRODUCT,
                                  "Accept": "application/json"})
    if r.status_code != 200:
        raise LabsError(f"Clash Labs respondeu {r.status_code}")
    return r.json()


def access_until(ent, now=None):
    """Epoch até quando o passe vale, ou None se não vale (outro produto, inativo, data inválida ou passada)."""
    now = now or time.time()
    if not isinstance(ent, dict) or ent.get("product") != PRODUCT or ent.get("active") is not True:
        return None
    raw = ent.get("accessUntil")
    if not isinstance(raw, str):
        return None
    try:
        ts = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        return None
    ts = int(ts.timestamp())
    return ts if ts > now else None


def has_access(user, now=None):
    if not user:
        return False
    if user["role"] == "owner":
        return True
    return bool(user.get("access_until") and user["access_until"] > (now or time.time()))


# ---------------------------------------------------------------- entrada
def begin(session):
    """Passo 1: cria o state, guarda na sessão deste navegador e devolve a URL da vitrine."""
    url, _, _ = _env()
    state = secrets.token_urlsafe(24)
    session["labs_state"] = state
    session["labs_state_at"] = int(time.time())
    return f"{url}/app/{PRODUCT}?state={state}&volta=%2F"


def take_state(session, state):
    """Passo 3: o state confere com o deste navegador? Uso único."""
    expected = session.pop("labs_state", None)
    started = session.pop("labs_state_at", 0)
    if not (isinstance(state, str) and isinstance(expected, str)):
        return False
    if time.time() - started > STATE_TTL_S:
        return False
    return hmac.compare_digest(state.encode(), expected.encode())


def redeem(con, code):
    """Troca o código e grava o assinante. Devolve o usuário (com access_until atualizado) ou None."""
    if not isinstance(code, str) or not 40 <= len(code) <= 64:
        return None
    try:
        out = _hub("/api/v1/sso/redeem", "POST", {"code": code})
    except Exception:
        return None
    u = (out or {}).get("user") or {}
    ent = (out or {}).get("entitlement") or {}
    if not isinstance(u.get("id"), str) or not LABS_USER_ID.match(u["id"]) or ent.get("product") != PRODUCT:
        return None
    user = db.upsert_labs_user(con, u["id"], str(u.get("email") or "")[:200], str(u.get("name") or "")[:120])
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


# ---------------------------------------------------------------- mudanças no passe
def refresh(con, user):
    """Relê o passe na vitrine. Devolve o usuário atualizado; em falha de rede, o de antes."""
    if not enabled() or not user or user["role"] != "subscriber" or not user.get("labs_user_id"):
        return user
    try:
        ent = _hub(f"/api/v1/entitlements/{user['labs_user_id']}")
    except Exception:
        return user
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


def refresh_labs_user(con, labs_user_id):
    """Aviso da vitrine. Quem não tem conta aqui é ignorado, sem dizer isso a quem chamou."""
    if not isinstance(labs_user_id, str) or not LABS_USER_ID.match(labs_user_id):
        raise ValueError("userId inválido")
    user = db.get_user_by_labs(con, labs_user_id)
    if user:
        refresh(con, user)


def sync_due(con, now=None):
    now = int(now or time.time())
    n = 0
    for user in db.subscribers_due(con, now):
        refresh(con, user)
        n += 1
    return n


def is_from_labs(authorization, product):
    """Pedido com o segredo deste produto? Comparação em tempo constante (sobre os hashes, que têm o mesmo tamanho)."""
    if not enabled() or product != PRODUCT or not isinstance(authorization, str):
        return False
    _, _, secret = _env()
    digest = lambda v: hashlib.sha256(v.encode()).digest()  # noqa: E731
    return hmac.compare_digest(digest(authorization), digest(f"Bearer {secret}"))
