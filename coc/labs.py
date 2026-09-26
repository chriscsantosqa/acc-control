"""Integração do passe do COC Control com a Clash Labs.

Regras principais:
- vínculo exclusivamente por ``labs_user_id`` UUID;
- state de navegador com 10 minutos e uso único;
- segredo somente servidor a servidor;
- entitlement sempre validado para ``coc-control``;
- webhook relê o entitlement na origem em vez de confiar no payload.
"""
import datetime as _dt
import hashlib
import hmac
import os
import secrets
import time
import uuid

try:
    import requests
except ImportError:
    requests = None

from werkzeug.exceptions import BadGateway

from . import db

PRODUCT = "coc-control"
STATE_TTL_S = 600


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


class LabsError(BadGateway):
    """Falha de comunicação/contrato com a Clash Labs (HTTP 502 no webhook)."""

    description = "Não foi possível consultar a Clash Labs"


def valid_labs_user_id(value):
    """Aceita somente UUID canônico. Nunca usa e-mail como identidade."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value.lower()


def _hub(path, method="GET", body=None):
    if not requests:
        raise LabsError()
    _, api, secret = _env()
    if not api or len(secret) < 32:
        raise LabsError()
    try:
        r = requests.request(
            method,
            f"{api}{path}",
            json=body,
            timeout=8,
            allow_redirects=False,
            headers={
                "Authorization": f"Bearer {secret}",
                "X-Labs-Product": PRODUCT,
                "Accept": "application/json",
            },
        )
    except Exception as exc:
        raise LabsError() from exc
    if r.status_code != 200:
        raise LabsError()
    try:
        return r.json()
    except Exception as exc:
        raise LabsError() from exc


def access_until(ent, now=None):
    """Epoch até quando o passe vale ou ``None`` quando o entitlement não vale."""
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
    value = int(ts.timestamp())
    return value if value > now else None


def has_access(user, now=None):
    if not user:
        return False
    if user["role"] == "owner":
        return True
    if user.get("suspended_at"):
        return False
    return bool(user.get("access_until") and user["access_until"] > (now or time.time()))


# ---------------------------------------------------------------- entrada
def begin(session):
    """Cria o state e devolve a URL da vitrine. O state fica preso à sessão do navegador."""
    url, _, _ = _env()
    state = secrets.token_urlsafe(24)
    session["labs_state"] = state
    session["labs_state_at"] = int(time.time())
    return f"{url}/app/{PRODUCT}?state={state}&volta=%2F"


def take_state(session, state):
    """Confere state com tempo constante. O valor é consumido mesmo quando inválido."""
    expected = session.pop("labs_state", None)
    started = session.pop("labs_state_at", 0)
    if not (isinstance(state, str) and isinstance(expected, str)):
        return False
    if not isinstance(started, (int, float)) or time.time() - started > STATE_TTL_S:
        return False
    return hmac.compare_digest(state.encode(), expected.encode())


def redeem(con, code):
    """Troca código SSO e grava o assinante. Falhas de SSO não expõem detalhes ao navegador."""
    if not isinstance(code, str) or not 40 <= len(code) <= 64:
        return None
    try:
        out = _hub("/api/v1/sso/redeem", "POST", {"code": code})
    except LabsError:
        return None
    u = (out or {}).get("user") or {}
    ent = (out or {}).get("entitlement") or {}
    if not valid_labs_user_id(u.get("id")) or ent.get("product") != PRODUCT:
        return None
    user = db.upsert_labs_user(
        con,
        u["id"].lower(),
        str(u.get("email") or "")[:200],
        str(u.get("name") or "")[:120],
    )
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


# ---------------------------------------------------------------- mudanças no passe
def refresh(con, user, strict=False):
    """Relê o entitlement.

    Em navegação comum preserva o último estado se a central estiver indisponível.
    No webhook ``strict=True`` faz a exceção chegar ao Flask como 502.
    """
    if not enabled() or not user or user["role"] != "subscriber" or not user.get("labs_user_id"):
        return user
    try:
        ent = _hub(f"/api/v1/entitlements/{user['labs_user_id']}")
    except LabsError:
        if strict:
            raise
        return user
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


def refresh_labs_user(con, labs_user_id):
    """Webhook da vitrine: UUID inválido = 422; usuário desconhecido = 200 sem vazamento."""
    if not valid_labs_user_id(labs_user_id):
        raise ValueError("userId inválido")
    canonical = labs_user_id.lower()
    user = db.get_user_by_labs(con, canonical)
    if user:
        return refresh(con, user, strict=True)
    return None


def sync_due(con, now=None):
    now = int(now or time.time())
    n = 0
    for user in db.subscribers_due(con, now):
        refresh(con, user)
        n += 1
    return n


def is_from_labs(authorization, product):
    """Valida segredo do produto em tempo constante."""
    if not enabled() or product != PRODUCT or not isinstance(authorization, str):
        return False
    _, _, secret = _env()

    def digest(value):
        return hashlib.sha256(value.encode()).digest()

    return hmac.compare_digest(digest(authorization), digest(f"Bearer {secret}"))
