"""Integração do passe COC Control com a Clash Labs."""
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

from . import db

PRODUCT = "coc-control"
STATE_TTL_S = 600


def valid_labs_user_id(value):
    """Aceita somente UUID canônico; e-mail/nome nunca vinculam contas."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return str(parsed) == value.lower()


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
    if r.status_code != 200:
        raise LabsError(f"Clash Labs respondeu {r.status_code}")
    return r.json()


def access_until(ent, now=None):
    """Epoch até quando o passe vale; datas sem timezone e passe inválido são recusados."""
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
    return bool(
        not user.get("suspended_at")
        and user.get("access_until")
        and user["access_until"] > (now or time.time())
    )


def begin(session):
    """Cria um state preso à sessão deste navegador e inicia SSO na vitrine."""
    url, _, _ = _env()
    state = secrets.token_urlsafe(24)
    session["labs_state"] = state
    session["labs_state_at"] = int(time.time())
    return f"{url}/app/{PRODUCT}?state={state}&volta=%2F"


def take_state(session, state):
    """Valida state em uso único e com TTL de 10 minutos."""
    expected = session.pop("labs_state", None)
    started = session.pop("labs_state_at", 0)
    if not (isinstance(state, str) and isinstance(expected, str)):
        return False
    if time.time() - started > STATE_TTL_S:
        return False
    return hmac.compare_digest(state.encode(), expected.encode())


def redeem(con, code):
    """Troca o código de uso único e atualiza o entitlement do assinante."""
    if not isinstance(code, str) or not 40 <= len(code) <= 64:
        return None
    try:
        out = _hub("/api/v1/sso/redeem", "POST", {"code": code})
    except Exception:
        return None
    user_data = (out or {}).get("user") or {}
    ent = (out or {}).get("entitlement") or {}
    if not valid_labs_user_id(user_data.get("id")) or ent.get("product") != PRODUCT:
        return None
    user = db.upsert_labs_user(
        con,
        user_data["id"],
        str(user_data.get("email") or "")[:200],
        str(user_data.get("name") or "")[:120],
    )
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


def refresh(con, user, strict=False):
    """Relê o passe. Em webhook, strict=True transforma falha da vitrine em 502."""
    if not enabled() or not user or user["role"] != "subscriber" or not user.get("labs_user_id"):
        return user
    try:
        ent = _hub(f"/api/v1/entitlements/{user['labs_user_id']}")
    except Exception as exc:
        if strict:
            raise LabsError("não foi possível reconferir o passe na Clash Labs") from exc
        return user
    db.set_access(con, user["id"], access_until(ent))
    return db.get_user(con, user["id"])


def refresh_labs_user(con, labs_user_id):
    """Webhook: UUID malformado é 422; usuário ainda inexistente é ignorado."""
    if not valid_labs_user_id(labs_user_id):
        raise ValueError("userId inválido")
    user = db.get_user_by_labs(con, labs_user_id)
    if user:
        refresh(con, user, strict=True)


def sync_due(con, now=None):
    now = int(now or time.time())
    count = 0
    for user in db.subscribers_due(con, now):
        refresh(con, user)
        count += 1
    return count


def is_from_labs(authorization, product):
    """Validação servidor-servidor com comparação em tempo constante."""
    if not enabled() or product != PRODUCT or not isinstance(authorization, str):
        return False
    _, _, secret = _env()
    digest = lambda value: hashlib.sha256(value.encode()).digest()  # noqa: E731
    return hmac.compare_digest(digest(authorization), digest(f"Bearer {secret}"))
