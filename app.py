#!/usr/bin/env python3
"""
COC Control — gerenciador de contas do Clash of Clans.

Roda um servidor web (padrão http://127.0.0.1:8420) com:
  * dashboard multi-contas (static/index.html)
  * API REST (/api/...)
  * watcher de clipboard: detecta o export da vila copiado no jogo e importa sozinho

Usuários:
  * dono: o login ADMIN_USER de sempre (ou ninguém, no uso local sem senha).
    Vê as vilas que já existiam, configura a chave da Supercell e o watcher do servidor.
  * assinantes: entram pela Clash Labs (coc/labs.py), cada um com as próprias vilas,
    alertas e API key. Com o passe vencido, os dados ficam guardados e a API responde 402.

Uso:
    pip install -r requirements.txt
    python app.py            # abre em http://127.0.0.1:8420
    python app.py --no-watcher
"""
import argparse
import datetime as _dt
import getpass
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import webbrowser

from flask import Flask, g, jsonify, redirect, request, send_from_directory, session

from coc import auth, db, diff as diffmod, gamedata, labs, metrics, notify, parser, planner, supercell_api

app = Flask(__name__, static_folder="static", static_url_path="/static")
gamedata.load()

# limites de cada assinante (o dono não tem): protegem o disco da VPS
MAX_ACCOUNTS = int(os.environ.get("COC_MAX_ACCOUNTS", "20"))
MAX_SNAPSHOTS = int(os.environ.get("COC_MAX_SNAPSHOTS", "150"))
LABS_SYNC_S = int(os.environ.get("LABS_SYNC_INTERVAL", "900"))
RECHECK_LAPSED_S = 60

# ---------- sessão / segurança ----------
with db.connect() as _c:
    app.secret_key = auth.secret_key(_c)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COC_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=_dt.timedelta(days=7),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
if os.environ.get("COC_BEHIND_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

PUBLIC_PATHS = {"/api/health", "/api/login", "/login",
                "/entrar/clash-labs", "/api/labs/callback", "/api/labs/webhook", "/api/labs/info"}
# com o passe vencido o assinante ainda abre a página, vê quem é, acha onde renovar e sai
LAPSED_OK = {"/", "/api/me", "/api/status", "/api/logout"}
MUTATING = ("POST", "PUT", "PATCH", "DELETE")


class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def uid():
    return g.user["id"]


def is_owner():
    return g.user["role"] == "owner"


def _csrf_ok():
    tok = request.cookies.get("csrf") or ""
    hdr = request.headers.get("X-CSRF") or ""
    return bool(tok and hdr and secrets.compare_digest(tok, hdr))


@app.before_request
def _guard():
    g.user = None
    con = db.connect()
    try:
        if not auth.enabled(con):
            g.user = db.get_user(con, db.owner_id(con))      # uso local, sem login
            return None
        p = request.path
        if p in PUBLIC_PATHS:
            return None
        # API key (automação / integrações): identifica o usuário dono da chave
        user_id = auth.check_bearer(con, request.headers.get("Authorization"))
        if user_id is None:
            user_id = session.get("uid")
            if user_id is not None and request.method in MUTATING and not _csrf_ok():
                return jsonify({"error": "CSRF inválido — recarregue a página"}), 403
        user = db.get_user(con, user_id)
        if not user:
            session.pop("uid", None)
            if p.startswith("/api/"):
                return jsonify({"error": "não autenticado"}), 401
            return redirect("/login")
        if not labs.has_access(user) and (not user.get("checked_at")
                                          or time.time() - user["checked_at"] > RECHECK_LAPSED_S):
            user = labs.refresh(con, user)      # renovou e o aviso da vitrine se perdeu?
        if not labs.has_access(user) and p not in LAPSED_OK:
            if p.startswith("/api/"):
                return jsonify({"error": "Seu passe do COC Control não está ativo. Renove na Clash Labs para voltar às suas vilas.",
                                "passe": "inativo", "store": labs.store_url()}), 402
            return redirect("/")
        g.user = user
        return None
    finally:
        con.close()


@app.errorhandler(Refused)
def _refused(e):
    return jsonify({"error": str(e)}), e.status


@app.after_request
def _headers(resp):
    for k, v in auth.SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


def _start_session(user_id, resp):
    """Sessão nova a cada login (nada da anterior sobrevive) + cookie do CSRF."""
    session.clear()
    session.permanent = True
    session["uid"] = user_id
    resp.set_cookie("csrf", secrets.token_urlsafe(24), samesite="Lax",
                    secure=os.environ.get("COC_HTTPS") == "1")
    return resp


@app.get("/login")
def login_page():
    con = db.connect()
    try:
        if not auth.enabled(con) or db.get_user(con, session.get("uid")):
            return redirect("/")
    finally:
        con.close()
    return send_from_directory("static", "login.html")


@app.post("/api/login")
def api_login():
    """Login do dono (usuário e senha do .env). Assinantes entram pela Clash Labs."""
    body = request.get_json(force=True, silent=True) or {}
    ip = request.remote_addr or "?"
    con = db.connect()
    try:
        if not auth.enabled(con):
            return jsonify({"ok": True, "auth": False})
        ok, err = auth.verify_login(con, ip, body.get("username"), body.get("password"))
        if not ok:
            time.sleep(0.6)  # desacelera brute force
            return jsonify({"error": err}), 401
        owner = db.owner_id(con)
        db.touch_login(con, owner)
    finally:
        con.close()
    return _start_session(owner, jsonify({"ok": True}))


@app.post("/api/logout")
def api_logout():
    session.clear()
    resp = jsonify({"ok": True})
    resp.delete_cookie("csrf")
    return resp


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


# ------------------------------------------------------------------ Clash Labs
@app.get("/api/labs/info")
def labs_info():
    return jsonify({"enabled": labs.enabled(), "store": labs.store_url()})


@app.get("/entrar/clash-labs")
def labs_begin():
    if not labs.enabled():
        return redirect("/login")
    resp = redirect(labs.begin(session))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/labs/callback")
def labs_callback():
    """A vitrine devolve o navegador aqui com um código de uso único."""
    if not labs.enabled():
        return redirect("/login")
    state = request.args.get("state")
    if not state:
        # veio direto do botão Abrir da vitrine: começa uma rodada nossa, amarrada a este
        # navegador. O código recebido aqui nunca é trocado.
        return redirect("/entrar/clash-labs")
    if not labs.take_state(session, state):
        return redirect("/login?passe=expirou")
    con = db.connect()
    try:
        user = labs.redeem(con, request.args.get("code"))
    finally:
        con.close()
    if not user:
        return redirect("/login?passe=erro")
    if not labs.has_access(user):
        return redirect("/login?passe=inativo")
    resp = _start_session(user["id"], redirect("/"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/labs/webhook")
def labs_webhook():
    """Aviso servidor a servidor: o passe de alguém mudou. Só diz quem; o passe é relido."""
    if not labs.is_from_labs(request.headers.get("Authorization"), request.headers.get("X-Labs-Product")):
        return jsonify({"error": "não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    con = db.connect()
    try:
        labs.refresh_labs_user(con, body.get("userId"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    finally:
        con.close()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    u = g.user
    return jsonify({
        "role": u["role"],
        "name": auth.admin_user() if u["role"] == "owner" else (u.get("name") or ""),
        "email": u.get("email") if u["role"] == "subscriber" else None,
        "access_until": u.get("access_until"),
        "active": labs.has_access(u),
        "api_key_hint": u.get("api_key_hint"),
        "limits": None if u["role"] == "owner" else {"accounts": MAX_ACCOUNTS, "snapshots": MAX_SNAPSHOTS},
        "labs": {"enabled": labs.enabled(), "store": labs.store_url(), "account": labs.account_url()},
    })


@app.post("/api/apikey")
def apikey_new():
    """Gera outra API key (a anterior para de funcionar). A chave aparece só nesta resposta."""
    con = db.connect()
    try:
        key = db.new_api_key(con, uid())
    finally:
        con.close()
    return jsonify({"api_key": key, "hint": key[-4:]})


@app.get("/api/admin/subscribers")
def admin_subscribers():
    if not is_owner():
        return jsonify({"error": "só o dono vê os assinantes"}), 403
    con = db.connect()
    try:
        return jsonify(db.list_subscribers(con))
    finally:
        con.close()


# ------------------------------------------------------------------ watcher
class ClipboardWatcher(threading.Thread):
    """Observa o clipboard do servidor (uso local do dono); ao detectar um export de vila,
    importa automaticamente nas vilas do dono."""

    def __init__(self, interval=1.5):
        super().__init__(daemon=True)
        self.interval = interval
        self.enabled = False
        self.available = False
        self.last_hash = None
        self.last_event = None   # {ts, tag, account, snapshot_id, error}
        self.event_seq = 0
        try:
            import pyperclip  # noqa
            self._pyperclip = pyperclip
            self.available = True
        except Exception:
            self._pyperclip = None

    def toggle(self, on):
        self.enabled = bool(on) and self.available

    def _emit(self, **ev):
        self.event_seq += 1
        ev["seq"] = self.event_seq
        ev["ts"] = int(time.time())
        self.last_event = ev

    def run(self):
        while True:
            time.sleep(self.interval)
            if not self.enabled or not self._pyperclip:
                continue
            try:
                text = self._pyperclip.paste()
            except Exception:
                continue
            if not text:
                continue
            h = hashlib.sha1(text[:200000].encode("utf-8", "ignore")).hexdigest()
            if h == self.last_hash:
                continue
            self.last_hash = h
            if not parser.looks_like_village_export(text):
                continue
            try:
                con = db.connect()
                try:
                    owner = db.owner_id(con)
                finally:
                    con.close()
                result = import_export(text, owner, source="watcher")
                self._emit(kind="import", tag=result["tag"],
                           account=result["account"]["name"],
                           account_id=result["account"]["id"],
                           snapshot_id=result["snapshot_id"])
            except Exception as e:
                self._emit(kind="error", error=str(e))


watcher = ClipboardWatcher()


class Notifier(threading.Thread):
    """Verifica términos de upgrades e envia alertas, usuário por usuário, com os canais
    de cada um. Também relê na Clash Labs os passes sem conferência recente."""

    def __init__(self, interval=45):
        super().__init__(daemon=True)
        self.interval = interval
        self.last_run = None
        self.sent_total = 0
        self.last_labs_sync = 0

    def scan_user(self, con, user, now):
        st = db.get_settings(con, user["id"])
        if not st.get("notify_enabled"):
            return 0
        trusted = user["role"] == "owner"
        sent = 0
        pairs = []
        for acc in db.list_accounts(con, user["id"]):
            snap = db.latest_snapshot(con, acc["id"])
            if not snap:
                continue
            summ = metrics.compute(json.loads(snap["parsed_json"]), now_ts=now)
            pairs.append((acc, summ))
            for ev in notify.build_events(acc, summ, st, now):
                if db.was_notified(con, ev["key"]):
                    continue
                if ev.get("stale"):
                    db.mark_notified(con, ev["key"])  # velho: registra sem disparar
                    continue
                channels = notify.dispatch(st, ev["title"], ev["body"], trusted=trusted)
                if channels:
                    sent += 1
                    self.sent_total += 1
                print(f"[notifier] u{user['id']} {ev['title']} -> {', '.join(channels) or 'nenhum canal aceitou'}")
                db.mark_notified(con, ev["key"])
        dt = st.get("digest_time")
        if dt:
            today = time.strftime("%Y-%m-%d")
            # o dono mantém a chave antiga: atualizar não repete o resumo do dia
            key = f"digest:{today}" if trusted else f"digest:{user['id']}:{today}"
            if time.strftime("%H:%M") >= dt and not db.was_notified(con, key):
                text = notify.build_digest(pairs, now)
                if text:
                    notify.dispatch(st, "📋 Resumo diário", text, trusted=trusted)
                db.mark_notified(con, key)
        return sent

    def scan_once(self, now=None):
        now = now or int(time.time())
        con = db.connect()
        try:
            sent = 0
            for user in db.users_to_notify(con, now):
                try:
                    sent += self.scan_user(con, user, now)
                except Exception as e:           # um usuário com problema não para os outros
                    print(f"[notifier] u{user['id']} erro: {e}")
            return sent
        finally:
            con.close()

    def sync_labs(self, now=None):
        now = now or time.time()
        if not labs.enabled() or now - self.last_labs_sync < LABS_SYNC_S:
            return 0
        self.last_labs_sync = now
        con = db.connect()
        try:
            n = labs.sync_due(con, now)
        finally:
            con.close()
        if n:
            print(f"[labs] {n} passe(s) relido(s)")
        return n

    def run(self):
        while True:
            try:
                self.scan_once()
            except Exception as e:
                print(f"[notifier] erro: {e}")
            try:
                self.sync_labs()
            except Exception as e:
                print(f"[labs] erro: {e}")
            self.last_run = int(time.time())
            time.sleep(self.interval)


notifier = Notifier()


def is_default_name(name, tag):
    """Nome gerado automaticamente (pode ser trocado pelo nome real do jogador)."""
    if not name:
        return True
    n = name.strip().lower()
    return n in ("nova vila", f"vila {(tag or '').lower()}", (tag or "").lower())


def maybe_adopt_player_name(con, account, player):
    """No sync: se a conta ainda tem nome automático, usa o nome real do jogador."""
    pname = (player or {}).get("name")
    if pname and is_default_name(account.get("name"), account.get("tag")):
        return db.update_account(con, account["user_id"], account["id"], name=str(pname)[:80])
    return account


TAG = re.compile(r"^#[A-Z0-9]{3,15}$")


def norm_tag(tag):
    """'pj9 uurqyu' -> '#PJ9UURQYU'. Vazio vira None. Tag fora do formato é recusada."""
    if tag is None:
        return None
    if not isinstance(tag, str):
        raise Refused(400, "tag inválida")
    t = tag.strip().upper().replace(" ", "")
    if not t:
        return None
    if not t.startswith("#"):
        t = "#" + t
    if not TAG.match(t):
        raise Refused(400, "tag inválida: use só letras e números, como #PJ9UURQYU")
    return t


def _text(v, field, limit, required=False):
    if v is None:
        if required:
            raise Refused(400, f"{field} é obrigatório")
        return None
    if not isinstance(v, str):
        raise Refused(400, f"{field} inválido")
    v = v.strip()
    if required and not v:
        raise Refused(400, f"{field} é obrigatório")
    if len(v) > limit:
        raise Refused(400, f"{field} passa de {limit} caracteres")
    return v


# ------------------------------------------------------------------ import
def import_export(text, user_id, source="manual", account_id=None):
    """Pipeline único de import (watcher, colar manual e automação usam o mesmo).
    Tudo acontece dentro das vilas de `user_id`."""
    parsed = parser.parse(text)
    if not parsed["tag"] and account_id is None:
        raise ValueError("Export sem tag e nenhuma conta informada")
    con = db.connect()
    try:
        user = db.get_user(con, user_id)
        account = None
        if account_id is not None:
            account = db.get_account(con, user_id, account_id)
            if account and parsed["tag"] and not account.get("tag"):
                account = db.update_account(con, user_id, account["id"], tag=parsed["tag"])
        if account is None and parsed["tag"]:
            account = db.get_account_by_tag(con, user_id, parsed["tag"])
        if account is None:
            if user["role"] != "owner" and db.count_accounts(con, user_id) >= MAX_ACCOUNTS:
                raise Refused(403, f"Limite de {MAX_ACCOUNTS} vilas por assinatura atingido.")
            name = f"Vila {parsed['tag']}" if parsed["tag"] else "Nova vila"
            account = db.create_account(con, user_id, name, tag=parsed["tag"] or None)
        raw = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
        snap_id = db.add_snapshot(con, account["id"], parsed.get("timestamp"), raw, parsed)
        if user["role"] != "owner":
            db.prune_snapshots(con, account["id"], MAX_SNAPSHOTS)
        st = db.get_settings(con, user_id)
        if st.get("supercell_autosync") and st.get("supercell_token") and account.get("tag"):
            try:
                player = supercell_api.fetch_player(account["tag"], st["supercell_token"])
                db.add_player_stats(con, account["id"], player)
                account = maybe_adopt_player_name(con, account, player)
            except Exception:
                pass  # sync é best-effort no import
        return {"tag": parsed["tag"], "account": account, "snapshot_id": snap_id,
                "source": source, "th_level": parsed["th_level"],
                "counts": parsed["counts"], "unknown_ids": parsed["unknown_ids"]}
    finally:
        con.close()


def summary_for(snapshot_row):
    parsed = json.loads(snapshot_row["parsed_json"])
    return metrics.compute(parsed)


def _owned(con, account_id):
    acc = db.get_account(con, uid(), account_id)
    if not acc:
        raise Refused(404, "conta não encontrada")
    return acc


# ------------------------------------------------------------------ rotas
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/status")
def status():
    con = db.connect()
    try:
        auth_on = auth.enabled(con)
    finally:
        con.close()
    owner = is_owner()
    return jsonify({
        "auth": {"enabled": auth_on, "role": g.user["role"]},
        "ok": True,
        "gamedata": {k: gamedata.load().get(k) for k in
                     ("generated_at", "entity_count", "source", "source_version")},
        # o clipboard é o da máquina do servidor: só faz sentido para o dono
        "watcher": {
            "available": watcher.available if owner else False,
            "enabled": watcher.enabled if owner else False,
            "last_event": watcher.last_event if owner else None,
        },
        "now": int(time.time()),
    })


@app.post("/api/watcher")
def watcher_toggle():
    if not is_owner():
        return jsonify({"error": "o watcher do servidor é só do dono"}), 403
    body = request.get_json(force=True, silent=True) or {}
    watcher.toggle(body.get("enabled", True))
    return jsonify({"enabled": watcher.enabled, "available": watcher.available})


@app.get("/api/accounts")
def accounts_list():
    con = db.connect()
    try:
        out = []
        for acc in db.list_accounts(con, uid()):
            snap = db.latest_snapshot(con, acc["id"])
            item = {**acc, "snapshots": db.count_snapshots(con, acc["id"])}
            ps = db.latest_player_stats(con, acc["id"])
            if ps:
                item["player"] = json.loads(ps["json"])
                item["player"]["fetched_at"] = ps["fetched_at"]
            if snap:
                s = summary_for(snap)
                item["latest"] = {
                    "snapshot_id": snap["id"],
                    "taken_at": snap["taken_at"],
                    "th_level": s["th_level"],
                    "progress_total": s["progress_total"],
                    "pending_total": s["pending_total"],
                    "builders": s["builders"],
                    "eta": s["eta"],
                    "cost_left": s["cost_left"],
                    "active_count": len(s["active_upgrades"]),
                    "next_finish": s["active_upgrades"][0] if s["active_upgrades"] else None,
                }
            out.append(item)
        return jsonify(out)
    finally:
        con.close()


@app.post("/api/accounts")
def accounts_create():
    body = request.get_json(force=True, silent=True) or {}
    name = _text(body.get("name"), "nome", 80, required=True)
    notes = _text(body.get("notes"), "notas", 500) or ""
    tag = norm_tag(body.get("tag"))
    con = db.connect()
    try:
        if not is_owner() and db.count_accounts(con, uid()) >= MAX_ACCOUNTS:
            raise Refused(403, f"Limite de {MAX_ACCOUNTS} vilas por assinatura atingido.")
        try:
            acc = db.create_account(con, uid(), name, tag=tag, notes=notes)
        except sqlite3.IntegrityError:
            raise Refused(409, "você já tem uma vila com essa tag")
        # 1º sync automático (best-effort: nunca impede a criação da conta)
        synced = False
        if tag:
            st = db.get_settings(con, uid())
            if st.get("supercell_token"):
                try:
                    player = supercell_api.fetch_player(tag, st["supercell_token"])
                    db.add_player_stats(con, acc["id"], player)
                    acc = maybe_adopt_player_name(con, acc, player)
                    synced = True
                except Exception:
                    pass
        return jsonify({**acc, "synced": synced}), 201
    finally:
        con.close()


@app.patch("/api/accounts/<int:account_id>")
def accounts_update(account_id):
    body = request.get_json(force=True, silent=True) or {}
    fields = {
        "name": _text(body.get("name"), "nome", 80),
        "notes": _text(body.get("notes"), "notas", 500),
    }
    if fields["name"] == "":
        raise Refused(400, "nome é obrigatório")
    if "tag" in body:
        fields["tag"] = norm_tag(body.get("tag"))
    con = db.connect()
    try:
        _owned(con, account_id)
        try:
            acc = db.update_account(con, uid(), account_id, **fields)
        except sqlite3.IntegrityError:
            raise Refused(409, "você já tem uma vila com essa tag")
        return jsonify(acc)
    finally:
        con.close()


@app.delete("/api/accounts/<int:account_id>")
def accounts_delete(account_id):
    con = db.connect()
    try:
        db.delete_account(con, uid(), account_id)
        return jsonify({"ok": True})
    finally:
        con.close()


@app.get("/api/accounts/<int:account_id>/detail")
def account_detail(account_id):
    con = db.connect()
    try:
        acc = _owned(con, account_id)
        snap = db.latest_snapshot(con, account_id)
        history = db.list_snapshots(con, account_id)
        detail = {"account": acc, "history": history, "summary": None}
        if snap:
            detail["summary"] = summary_for(snap)
            detail["summary"]["snapshot_id"] = snap["id"]
            detail["summary"]["taken_at"] = snap["taken_at"]
        # série de evolução (progresso por snapshot)
        series = []
        for h in reversed(history[:60]):
            row = db.get_snapshot(con, h["id"])
            s = summary_for(row)
            series.append({"taken_at": row["taken_at"], "progress": s["progress_total"],
                           "pending": s["pending_total"], "th": s["th_level"]})
        detail["series"] = series
        detail["velocity"] = diffmod.velocity(series)
        # diff: último snapshot vs anterior
        if len(history) >= 2:
            prev = db.get_snapshot(con, history[1]["id"])
            cur = db.get_snapshot(con, history[0]["id"])
            try:
                detail["diff"] = diffmod.compute_diff(
                    json.loads(prev["parsed_json"]), json.loads(cur["parsed_json"]))
            except Exception as e:
                detail["diff"] = {"error": str(e)}
        ps = db.latest_player_stats(con, account_id)
        if ps:
            detail["player"] = json.loads(ps["json"])
            detail["player"]["fetched_at"] = ps["fetched_at"]
        detail["player_series"] = [
            {"fetched_at": r["fetched_at"], "trophies": json.loads(r["json"]).get("trophies")}
            for r in db.player_stats_series(con, account_id)]
        return jsonify(detail)
    finally:
        con.close()


@app.delete("/api/snapshots/<int:snapshot_id>")
def snapshot_delete(snapshot_id):
    con = db.connect()
    try:
        db.delete_snapshot(con, uid(), snapshot_id)
        return jsonify({"ok": True})
    finally:
        con.close()


@app.post("/api/import")
def api_import():
    body = request.get_json(force=True, silent=True)
    if body is None:
        text = request.get_data(as_text=True)
    elif isinstance(body, dict) and "json" in body:
        text = body["json"] if isinstance(body["json"], str) else json.dumps(body["json"])
    else:
        text = json.dumps(body)
    account_id = request.args.get("account_id", type=int)
    try:
        result = import_export(text, uid(), source="api", account_id=account_id)
        return jsonify(result), 201
    except Refused:
        raise
    except Exception as e:
        return jsonify({"error": f"Import falhou: {e}"}), 400


@app.get("/api/accounts/<int:account_id>/plan")
def account_plan(account_id):
    strategy = request.args.get("strategy", "balanced")
    con = db.connect()
    try:
        _owned(con, account_id)
        snap = db.latest_snapshot(con, account_id)
        if not snap:
            return jsonify({"error": "sem snapshots"}), 404
        parsed = json.loads(snap["parsed_json"])
        summ = metrics.compute(parsed)
        return jsonify(planner.plan(parsed, summ, strategy))
    finally:
        con.close()


@app.post("/api/accounts/<int:account_id>/sync-supercell")
def account_sync(account_id):
    con = db.connect()
    try:
        acc = _owned(con, account_id)
        st = db.get_settings(con, uid())
        try:
            data = supercell_api.fetch_player(acc.get("tag"), st.get("supercell_token"))
        except supercell_api.ApiError as e:
            return jsonify({"error": str(e)}), 400
        db.add_player_stats(con, account_id, data)
        acc = maybe_adopt_player_name(con, acc, data)
        return jsonify({**data, "account": acc})
    finally:
        con.close()


@app.post("/api/sync-all")
def sync_all():
    """Sincroniza todas as contas (do usuário) com tag na API da Supercell (resiliente:
    falha de uma conta não interrompe as demais)."""
    con = db.connect()
    try:
        st = db.get_settings(con, uid())
        results = []
        for acc in db.list_accounts(con, uid()):
            if not acc.get("tag"):
                results.append({"id": acc["id"], "name": acc["name"], "ok": False, "error": "sem tag"})
                continue
            try:
                data = supercell_api.fetch_player(acc["tag"], st.get("supercell_token"))
                db.add_player_stats(con, acc["id"], data)
                acc2 = maybe_adopt_player_name(con, acc, data)
                results.append({"id": acc["id"], "name": acc2["name"], "ok": True,
                                "trophies": data.get("trophies"), "league": data.get("league")})
            except Exception as e:
                results.append({"id": acc["id"], "name": acc["name"], "ok": False, "error": str(e)})
            time.sleep(0.25)  # gentil com o rate-limit da API
        return jsonify({"synced": sum(1 for r in results if r["ok"]),
                        "total": len(results), "results": results})
    finally:
        con.close()


@app.post("/api/accounts/<int:account_id>/verify")
def account_verify(account_id):
    """Verifica a POSSE da conta com o Token de API copiado dentro do jogo."""
    body = request.get_json(force=True, silent=True) or {}
    con = db.connect()
    try:
        acc = _owned(con, account_id)
        st = db.get_settings(con, uid())
        try:
            ok = supercell_api.verify_token(acc.get("tag"), st.get("supercell_token"),
                                            body.get("token", ""))
        except supercell_api.ApiError as e:
            return jsonify({"error": str(e)}), 400
        if ok:
            db.set_verified(con, uid(), account_id, True)
            return jsonify({"verified": True, "account": db.get_account(con, uid(), account_id)})
        return jsonify({"verified": False,
                        "error": "token inválido — copie um token novo no jogo (ele muda a cada uso)"}), 400
    finally:
        con.close()


# ------------------------------------------------------------------ settings
SUBSCRIBER_HIDDEN = ("supercell_token", "toast_enabled")
DIGEST = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EVOLUTION_NUMBER = re.compile(r"^(\d{8,15}|[\d-]{10,40}@g\.us)$")


def _visible_settings(st):
    out = dict(st)
    out["supercell_configured"] = bool(st.get("supercell_token"))
    if not is_owner():
        for k in SUBSCRIBER_HIDDEN:
            out.pop(k, None)
    return out


def _clean_subscriber_settings(body, current):
    """Assinante: tipos conferidos e canais só para endereços públicos. Devolve o que gravar."""
    upd = {}
    for k in ("notify_enabled", "supercell_autosync"):
        if k in body:
            upd[k] = bool(body[k])
    if "lead_minutes" in body:
        try:
            upd["lead_minutes"] = max(0, min(1440, int(body["lead_minutes"] or 0)))
        except (TypeError, ValueError):
            raise Refused(422, "minutos de antecedência inválidos")
    if "digest_time" in body:
        dt = _text(body["digest_time"], "horário do resumo", 5) or ""
        if dt and not DIGEST.match(dt):
            raise Refused(422, "horário do resumo no formato HH:MM")
        upd["digest_time"] = dt
    for k, limit in (("telegram_token", 120), ("telegram_chat_id", 40), ("discord_webhook", 300),
                     ("evolution_url", 300), ("evolution_apikey", 200), ("evolution_instance", 64),
                     ("evolution_number", 60)):
        if k in body:
            upd[k] = _text(body[k], k, limit) or ""
    num = upd.get("evolution_number")
    if num and not EVOLUTION_NUMBER.match(num):
        raise Refused(422, "WhatsApp: destino deve ser o número com DDI (5511999999999) ou o JID do grupo (...@g.us)")
    problems = notify.channel_problems({**current, **upd})
    if problems:
        raise Refused(422, "; ".join(problems.values()))
    return upd


@app.get("/api/settings")
def settings_get():
    con = db.connect()
    try:
        return jsonify(_visible_settings(db.get_settings(con, uid())))
    finally:
        con.close()


@app.put("/api/settings")
def settings_put():
    body = request.get_json(force=True, silent=True) or {}
    if not isinstance(body, dict):
        raise Refused(400, "envie um objeto JSON")
    con = db.connect()
    try:
        if not is_owner():
            body = _clean_subscriber_settings(body, db.get_settings(con, uid()))
        return jsonify(_visible_settings(db.set_settings(con, uid(), body)))
    finally:
        con.close()


@app.get("/api/notify/status")
def notify_status():
    """Diagnóstico dos alertas: master, última varredura e próximos disparos."""
    con = db.connect()
    try:
        st = db.get_settings(con, uid())
        channels = [c for c, on in (
            ("toast", is_owner() and st.get("toast_enabled")),
            ("telegram", bool(st.get("telegram_token") and st.get("telegram_chat_id"))),
            ("discord", bool(st.get("discord_webhook"))),
            ("whatsapp", bool(st.get("evolution_url") and st.get("evolution_apikey")
                              and st.get("evolution_number"))),
        ) if on]
        now = int(time.time())
        upcoming = []
        for acc in db.list_accounts(con, uid()):
            snap = db.latest_snapshot(con, acc["id"])
            if not snap:
                continue
            summ = metrics.compute(json.loads(snap["parsed_json"]), now_ts=now)
            for up in summ["active_upgrades"]:
                if up["finish_ts"] <= now:
                    continue
                upcoming.append({
                    "account": acc["name"], "name": up["name"],
                    "to_lvl": up["to_lvl"], "queue": up["queue"],
                    "finish_ts": up["finish_ts"],
                    "already_notified": db.was_notified(
                        con, notify.event_key("fin", acc["id"], up["data"], up["finish_ts"])),
                })
        upcoming.sort(key=lambda x: x["finish_ts"])
        return jsonify({
            "enabled": bool(st.get("notify_enabled")),
            "channels": channels,
            "last_scan": notifier.last_run,
            "scan_interval_s": notifier.interval,
            "sent_since_boot": notifier.sent_total if is_owner() else None,
            "upcoming": upcoming[:15],
        })
    finally:
        con.close()


@app.post("/api/notify/test")
def notify_test():
    con = db.connect()
    try:
        st = db.get_settings(con, uid())
    finally:
        con.close()
    sent = notify.dispatch(st, "🔔 COC Control", "Teste de notificação — canais funcionando!", trusted=is_owner())
    return jsonify({"sent": sent, "notify_enabled": bool(st.get("notify_enabled"))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--no-watcher", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--production", action="store_true",
                    help="usa waitress (WSGI de produção) em vez do server de dev")
    ap.add_argument("--set-password", action="store_true",
                    help="define/troca a senha de acesso e sai")
    args = ap.parse_args()

    if args.set_password:
        con = db.connect()
        try:
            pw = getpass.getpass("Nova senha: ")
            if len(pw) < 8:
                print("Use pelo menos 8 caracteres.")
                return
            if pw != getpass.getpass("Confirme: "):
                print("Senhas não conferem.")
                return
            auth.set_password(con, pw)
            print(f"Senha definida. Login habilitado (usuário: {auth.admin_user()}).")
        finally:
            con.close()
        return

    con = db.connect()
    auth_on = auth.enabled(con)
    con.close()
    watcher.start()
    watcher.toggle(not args.no_watcher)
    notifier.start()
    production = args.production or os.environ.get("COC_PRODUCTION") == "1"
    if not args.no_browser and not production:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    print(f"COC Control em http://{args.host}:{args.port} | login: "
          f"{'ATIVO' if auth_on else 'desligado (local)'} | Clash Labs: "
          f"{'ligada' if labs.enabled() else 'desligada'} | watcher: "
          f"{'ativo' if watcher.enabled else 'desligado' if watcher.available else 'indisponível'}")
    if production:
        from waitress import serve
        serve(app, host=args.host, port=args.port, threads=8)
    else:
        app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
