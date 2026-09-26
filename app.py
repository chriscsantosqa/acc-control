#!/usr/bin/env python3
"""COC Control — gerenciador multiusuário de vilas Clash of Clans."""
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
import zipfile
from pathlib import Path

from flask import Flask, g, jsonify, redirect, request, send_from_directory, session

from coc import auth, db, diff as diffmod, gamedata, labs, metrics, notify, parser, planner, supercell_api

app = Flask(__name__, static_folder="static", static_url_path="/static")


def _ensure_coc_assets():
    """Extrai o pacote versionado de assets uma única vez, sem depender de unrar/7z."""
    base = Path(app.root_path) / "static" / "assets"
    pack = base / "coc-pack.zip"
    target = base / "coc"
    marker = target / "assets-manifest.json"
    if marker.exists() or not pack.exists():
        return
    with zipfile.ZipFile(pack) as archive:
        members = archive.infolist()
        for member in members:
            rel = Path(member.filename)
            if not member.filename.startswith("coc/") or rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError("asset pack inválido")
        archive.extractall(base)


_ensure_coc_assets()
gamedata.load()

MAX_ACCOUNTS = int(os.environ.get("COC_MAX_ACCOUNTS", "20"))
MAX_SNAPSHOTS = int(os.environ.get("COC_MAX_SNAPSHOTS", "150"))
LABS_SYNC_S = int(os.environ.get("LABS_SYNC_INTERVAL", "900"))
RECHECK_LAPSED_S = 60

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

PUBLIC_PATHS = {
    "/api/health", "/api/login", "/login", "/entrar/clash-labs",
    "/api/labs/callback", "/api/labs/webhook", "/api/labs/info",
}
LAPSED_OK = {
    "/", "/api/me", "/api/status", "/api/logout", "/api/me/export", "/api/me/data",
}
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
    token = request.cookies.get("csrf") or ""
    header = request.headers.get("X-CSRF") or ""
    return bool(token and header and secrets.compare_digest(token, header))


@app.before_request
def _guard():
    g.user = None
    con = db.connect()
    try:
        if not auth.enabled(con):
            g.user = db.get_user(con, db.owner_id(con))
            return None
        path = request.path
        if path in PUBLIC_PATHS:
            return None
        user_id = auth.check_bearer(con, request.headers.get("Authorization"))
        if user_id is None:
            user_id = session.get("uid")
            if user_id is not None and request.method in MUTATING and not _csrf_ok():
                return jsonify({"error": "CSRF inválido — recarregue a página"}), 403
        user = db.get_user(con, user_id)
        if not user:
            session.pop("uid", None)
            if path.startswith("/api/"):
                return jsonify({"error": "não autenticado"}), 401
            return redirect("/login")
        if not labs.has_access(user) and (
            not user.get("checked_at") or time.time() - user["checked_at"] > RECHECK_LAPSED_S
        ):
            user = labs.refresh(con, user)
        if not labs.has_access(user) and path not in LAPSED_OK:
            if path.startswith("/api/"):
                return jsonify({
                    "error": "Seu passe do COC Control não está ativo. Renove na Clash Labs para voltar às suas vilas.",
                    "passe": "inativo",
                    "store": labs.store_url(),
                }), 402
            return redirect("/")
        g.user = user
        return None
    finally:
        con.close()


@app.errorhandler(Refused)
def _refused(error):
    return jsonify({"error": str(error)}), error.status


@app.after_request
def _headers(resp):
    for key, value in auth.SECURITY_HEADERS.items():
        resp.headers.setdefault(key, value)
    return resp


def _start_session(user_id, resp):
    session.clear()
    session.permanent = True
    session["uid"] = user_id
    resp.set_cookie(
        "csrf",
        secrets.token_urlsafe(24),
        samesite="Lax",
        secure=os.environ.get("COC_HTTPS") == "1",
    )
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
    body = request.get_json(force=True, silent=True) or {}
    ip = request.remote_addr or "?"
    con = db.connect()
    try:
        if not auth.enabled(con):
            return jsonify({"ok": True, "auth": False})
        ok, err = auth.verify_login(con, ip, body.get("username"), body.get("password"))
        if not ok:
            time.sleep(0.6)
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
    if not labs.enabled():
        return redirect("/login")
    state = request.args.get("state")
    if not state:
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
    if not labs.is_from_labs(
        request.headers.get("Authorization"), request.headers.get("X-Labs-Product")
    ):
        return jsonify({"error": "não autorizado"}), 401
    body = request.get_json(silent=True) or {}
    con = db.connect()
    try:
        labs.refresh_labs_user(con, body.get("userId"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except labs.LabsError:
        return jsonify({"error": "não foi possível confirmar a alteração de acesso"}), 502
    finally:
        con.close()
    return jsonify({"ok": True})


@app.get("/api/me")
def me():
    user = g.user
    return jsonify({
        "role": user["role"],
        "name": auth.admin_user() if user["role"] == "owner" else (user.get("name") or ""),
        "email": user.get("email") if user["role"] == "subscriber" else None,
        "access_until": user.get("access_until"),
        "active": labs.has_access(user),
        "suspended": bool(user.get("suspended_at")),
        "suspension_reason": user.get("suspension_reason"),
        "api_key_hint": user.get("api_key_hint"),
        "limits": None if user["role"] == "owner" else {
            "accounts": MAX_ACCOUNTS,
            "snapshots": MAX_SNAPSHOTS,
        },
        "labs": {
            "enabled": labs.enabled(),
            "store": labs.store_url(),
            "account": labs.account_url(),
        },
    })


@app.get("/api/me/export")
def me_export():
    con = db.connect()
    try:
        payload = db.export_user_data(con, uid())
    finally:
        con.close()
    if payload is None:
        return jsonify({"error": "conta não encontrada"}), 404
    resp = jsonify(payload)
    resp.headers["Content-Disposition"] = 'attachment; filename="coc-control-meus-dados.json"'
    return resp


@app.delete("/api/me/data")
def me_delete_data():
    if is_owner():
        return jsonify({"error": "a conta do dono não pode ser excluída por esta rota"}), 403
    user_id = uid()
    con = db.connect()
    try:
        ok = db.delete_subscriber_data(con, user_id)
    finally:
        con.close()
    if not ok:
        return jsonify({"error": "conta não encontrada"}), 404
    session.clear()
    resp = jsonify({"ok": True})
    resp.delete_cookie("csrf")
    return resp


@app.post("/api/apikey")
def apikey_new():
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


@app.post("/api/admin/subscribers/<int:user_id>/suspension")
def admin_subscriber_suspension(user_id):
    if not is_owner():
        return jsonify({"error": "só o dono pode alterar o acesso de assinantes"}), 403
    body = request.get_json(force=True, silent=True) or {}
    suspended = bool(body.get("suspended"))
    reason = body.get("reason") or ""
    if not isinstance(reason, str) or len(reason) > 500:
        return jsonify({"error": "motivo inválido"}), 422
    if reason.strip().lower().startswith("clash-labs:"):
        return jsonify({"error": "o prefixo clash-labs: é reservado para sincronização"}), 422
    con = db.connect()
    try:
        user = db.set_user_suspension(con, user_id, suspended, reason)
    finally:
        con.close()
    if not user:
        return jsonify({"error": "assinante não encontrado"}), 404
    return jsonify({
        "id": user["id"],
        "suspended": bool(user.get("suspended_at")),
        "suspended_at": user.get("suspended_at"),
        "suspension_reason": user.get("suspension_reason"),
    })


class ClipboardWatcher(threading.Thread):
    def __init__(self, interval=1.5):
        super().__init__(daemon=True)
        self.interval = interval
        self.enabled = False
        self.available = False
        self.last_hash = None
        self.last_event = None
        self.event_seq = 0
        try:
            import pyperclip
            self._pyperclip = pyperclip
            self.available = True
        except Exception:
            self._pyperclip = None

    def toggle(self, on):
        self.enabled = bool(on) and self.available

    def _emit(self, **event):
        self.event_seq += 1
        event["seq"] = self.event_seq
        event["ts"] = int(time.time())
        self.last_event = event

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
            digest = hashlib.sha1(text[:200000].encode("utf-8", "ignore")).hexdigest()
            if digest == self.last_hash:
                continue
            self.last_hash = digest
            if not parser.looks_like_village_export(text):
                continue
            try:
                con = db.connect()
                try:
                    owner = db.owner_id(con)
                finally:
                    con.close()
                result = import_export(text, owner, source="watcher")
                self._emit(
                    kind="import",
                    tag=result["tag"],
                    account=result["account"]["name"],
                    account_id=result["account"]["id"],
                    snapshot_id=result["snapshot_id"],
                )
            except Exception as exc:
                self._emit(kind="error", error=str(exc))


watcher = ClipboardWatcher()


class Notifier(threading.Thread):
    def __init__(self, interval=45):
        super().__init__(daemon=True)
        self.interval = interval
        self.last_run = None
        self.sent_total = 0
        self.last_labs_sync = 0

    def scan_user(self, con, user, now):
        settings = db.get_settings(con, user["id"])
        if not settings.get("notify_enabled"):
            return 0
        trusted = user["role"] == "owner"
        sent = 0
        pairs = []
        for account in db.list_accounts(con, user["id"]):
            snap = db.latest_snapshot(con, account["id"])
            if not snap:
                continue
            summary = metrics.compute(json.loads(snap["parsed_json"]), now_ts=now)
            pairs.append((account, summary))
            for event in notify.build_events(account, summary, settings, now):
                if db.was_notified(con, event["key"]):
                    continue
                if event.get("stale"):
                    db.mark_notified(con, event["key"])
                    continue
                channels = notify.dispatch(settings, event["title"], event["body"], trusted=trusted)
                if channels:
                    sent += 1
                    self.sent_total += 1
                db.mark_notified(con, event["key"])
        digest_time = settings.get("digest_time")
        if digest_time:
            today = time.strftime("%Y-%m-%d")
            key = f"digest:{today}" if trusted else f"digest:{user['id']}:{today}"
            if time.strftime("%H:%M") >= digest_time and not db.was_notified(con, key):
                text = notify.build_digest(pairs, now)
                if text:
                    notify.dispatch(settings, "📋 Resumo diário", text, trusted=trusted)
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
                except Exception as exc:
                    print(f"[notifier] u{user['id']} erro: {exc}")
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
            count = labs.sync_due(con, now)
        finally:
            con.close()
        return count

    def run(self):
        while True:
            try:
                self.scan_once()
            except Exception as exc:
                print(f"[notifier] erro: {exc}")
            try:
                self.sync_labs()
            except Exception as exc:
                print(f"[labs] erro: {exc}")
            self.last_run = int(time.time())
            time.sleep(self.interval)


notifier = Notifier()


def is_default_name(name, tag):
    if not name:
        return True
    value = name.strip().lower()
    return value in ("nova vila", f"vila {(tag or '').lower()}", (tag or "").lower())


def maybe_adopt_player_name(con, account, player):
    player_name = (player or {}).get("name")
    if player_name and is_default_name(account.get("name"), account.get("tag")):
        return db.update_account(con, account["user_id"], account["id"], name=str(player_name)[:80])
    return account


TAG = re.compile(r"^#[A-Z0-9]{3,15}$")


def norm_tag(tag):
    if tag is None:
        return None
    if not isinstance(tag, str):
        raise Refused(400, "tag inválida")
    value = tag.strip().upper().replace(" ", "")
    if not value:
        return None
    if not value.startswith("#"):
        value = "#" + value
    if not TAG.match(value):
        raise Refused(400, "tag inválida: use só letras e números, como #PJ9UURQYU")
    return value


def _text(value, field, limit, required=False):
    if value is None:
        if required:
            raise Refused(400, f"{field} é obrigatório")
        return None
    if not isinstance(value, str):
        raise Refused(400, f"{field} inválido")
    value = value.strip()
    if required and not value:
        raise Refused(400, f"{field} é obrigatório")
    if len(value) > limit:
        raise Refused(400, f"{field} passa de {limit} caracteres")
    return value


def import_export(text, user_id, source="manual", account_id=None):
    parsed = parser.parse(text)
    if not parsed["tag"] and account_id is None:
        raise ValueError("Export sem tag e nenhuma conta informada")
    con = db.connect()
    try:
        user = db.get_user(con, user_id)
        account = None
        if account_id is not None:
            account = db.get_account(con, user_id, account_id)
            if account is None:
                raise Refused(404, "conta não encontrada")
            if parsed["tag"] and not account.get("tag"):
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
        settings = db.get_settings(con, user_id)
        if settings.get("supercell_autosync") and settings.get("supercell_token") and account.get("tag"):
            try:
                player = supercell_api.fetch_player(account["tag"], settings["supercell_token"])
                db.add_player_stats(con, account["id"], player)
                account = maybe_adopt_player_name(con, account, player)
            except Exception:
                pass
        return {
            "tag": parsed["tag"],
            "account": account,
            "snapshot_id": snap_id,
            "source": source,
            "th_level": parsed["th_level"],
            "counts": parsed["counts"],
            "unknown_ids": parsed["unknown_ids"],
        }
    finally:
        con.close()


def summary_for(snapshot_row):
    return metrics.compute(json.loads(snapshot_row["parsed_json"]))


def _owned(con, account_id):
    account = db.get_account(con, uid(), account_id)
    if not account:
        raise Refused(404, "conta não encontrada")
    return account


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
        "gamedata": {
            key: gamedata.load().get(key)
            for key in ("generated_at", "entity_count", "source", "source_version")
        },
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
        for account in db.list_accounts(con, uid()):
            snap = db.latest_snapshot(con, account["id"])
            item = {**account, "snapshots": db.count_snapshots(con, account["id"])}
            player_stats = db.latest_player_stats(con, account["id"])
            if player_stats:
                item["player"] = json.loads(player_stats["json"])
                item["player"]["fetched_at"] = player_stats["fetched_at"]
            if snap:
                summary = summary_for(snap)
                item["latest"] = {
                    "snapshot_id": snap["id"],
                    "taken_at": snap["taken_at"],
                    "th_level": summary["th_level"],
                    "progress_total": summary["progress_total"],
                    "pending_total": summary["pending_total"],
                    "builders": summary["builders"],
                    "eta": summary["eta"],
                    "cost_left": summary["cost_left"],
                    "active_count": len(summary["active_upgrades"]),
                    "next_finish": summary["active_upgrades"][0] if summary["active_upgrades"] else None,
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
            account = db.create_account(con, uid(), name, tag=tag, notes=notes)
        except sqlite3.IntegrityError:
            raise Refused(409, "você já tem uma vila com essa tag")
        synced = False
        if tag:
            settings = db.get_settings(con, uid())
            if settings.get("supercell_token"):
                try:
                    player = supercell_api.fetch_player(tag, settings["supercell_token"])
                    db.add_player_stats(con, account["id"], player)
                    account = maybe_adopt_player_name(con, account, player)
                    synced = True
                except Exception:
                    pass
        return jsonify({**account, "synced": synced}), 201
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
            account = db.update_account(con, uid(), account_id, **fields)
        except sqlite3.IntegrityError:
            raise Refused(409, "você já tem uma vila com essa tag")
        return jsonify(account)
    finally:
        con.close()


@app.delete("/api/accounts/<int:account_id>")
def accounts_delete(account_id):
    con = db.connect()
    try:
        _owned(con, account_id)
        db.delete_account(con, uid(), account_id)
        return jsonify({"ok": True})
    finally:
        con.close()


@app.get("/api/accounts/<int:account_id>/detail")
def account_detail(account_id):
    con = db.connect()
    try:
        account = _owned(con, account_id)
        snap = db.latest_snapshot(con, account_id)
        history = db.list_snapshots(con, account_id)
        detail = {"account": account, "history": history, "summary": None}
        if snap:
            detail["summary"] = summary_for(snap)
            detail["summary"]["snapshot_id"] = snap["id"]
            detail["summary"]["taken_at"] = snap["taken_at"]
        series = []
        for item in reversed(history[:60]):
            row = db.get_snapshot(con, item["id"])
            summary = summary_for(row)
            series.append({
                "taken_at": row["taken_at"],
                "progress": summary["progress_total"],
                "pending": summary["pending_total"],
                "th": summary["th_level"],
            })
        detail["series"] = series
        detail["velocity"] = diffmod.velocity(series)
        if len(history) >= 2:
            prev = db.get_snapshot(con, history[1]["id"])
            current = db.get_snapshot(con, history[0]["id"])
            try:
                detail["diff"] = diffmod.compute_diff(
                    json.loads(prev["parsed_json"]), json.loads(current["parsed_json"])
                )
            except Exception as exc:
                detail["diff"] = {"error": str(exc)}
        player_stats = db.latest_player_stats(con, account_id)
        if player_stats:
            detail["player"] = json.loads(player_stats["json"])
            detail["player"]["fetched_at"] = player_stats["fetched_at"]
        detail["player_series"] = [
            {
                "fetched_at": row["fetched_at"],
                "trophies": json.loads(row["json"]).get("trophies"),
            }
            for row in db.player_stats_series(con, account_id)
        ]
        return jsonify(detail)
    finally:
        con.close()


@app.delete("/api/snapshots/<int:snapshot_id>")
def snapshot_delete(snapshot_id):
    con = db.connect()
    try:
        snap = db.get_snapshot(con, snapshot_id)
        if not snap or not db.get_account(con, uid(), snap["account_id"]):
            raise Refused(404, "snapshot não encontrado")
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
    except Exception as exc:
        return jsonify({"error": f"Import falhou: {exc}"}), 400


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
        summary = metrics.compute(parsed)
        return jsonify(planner.plan(parsed, summary, strategy))
    finally:
        con.close()


@app.post("/api/accounts/<int:account_id>/sync-supercell")
def account_sync(account_id):
    con = db.connect()
    try:
        account = _owned(con, account_id)
        settings = db.get_settings(con, uid())
        try:
            data = supercell_api.fetch_player(account.get("tag"), settings.get("supercell_token"))
        except supercell_api.ApiError as exc:
            return jsonify({"error": str(exc)}), 400
        db.add_player_stats(con, account_id, data)
        account = maybe_adopt_player_name(con, account, data)
        return jsonify({**data, "account": account})
    finally:
        con.close()


@app.post("/api/sync-all")
def sync_all():
    con = db.connect()
    try:
        settings = db.get_settings(con, uid())
        results = []
        for account in db.list_accounts(con, uid()):
            if not account.get("tag"):
                results.append({"id": account["id"], "name": account["name"], "ok": False, "error": "sem tag"})
                continue
            try:
                data = supercell_api.fetch_player(account["tag"], settings.get("supercell_token"))
                db.add_player_stats(con, account["id"], data)
                updated = maybe_adopt_player_name(con, account, data)
                results.append({
                    "id": account["id"],
                    "name": updated["name"],
                    "ok": True,
                    "trophies": data.get("trophies"),
                    "league": data.get("league"),
                })
            except Exception as exc:
                results.append({"id": account["id"], "name": account["name"], "ok": False, "error": str(exc)})
            time.sleep(0.25)
        return jsonify({
            "synced": sum(1 for result in results if result["ok"]),
            "total": len(results),
            "results": results,
        })
    finally:
        con.close()


@app.post("/api/accounts/<int:account_id>/verify")
def account_verify(account_id):
    body = request.get_json(force=True, silent=True) or {}
    con = db.connect()
    try:
        account = _owned(con, account_id)
        settings = db.get_settings(con, uid())
        try:
            ok = supercell_api.verify_token(
                account.get("tag"), settings.get("supercell_token"), body.get("token", "")
            )
        except supercell_api.ApiError as exc:
            return jsonify({"error": str(exc)}), 400
        if ok:
            db.set_verified(con, uid(), account_id, True)
            return jsonify({"verified": True, "account": db.get_account(con, uid(), account_id)})
        return jsonify({
            "verified": False,
            "error": "token inválido — copie um token novo no jogo (ele muda a cada uso)",
        }), 400
    finally:
        con.close()


SUBSCRIBER_HIDDEN = ("supercell_token", "toast_enabled")
DIGEST = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EVOLUTION_NUMBER = re.compile(r"^(\d{8,15}|[\d-]{10,40}@g\.us)$")


def _visible_settings(settings):
    out = dict(settings)
    out["supercell_configured"] = bool(settings.get("supercell_token"))
    if not is_owner():
        for key in SUBSCRIBER_HIDDEN:
            out.pop(key, None)
    return out


def _clean_subscriber_settings(body, current):
    updates = {}
    for key in ("notify_enabled", "supercell_autosync"):
        if key in body:
            updates[key] = bool(body[key])
    if "lead_minutes" in body:
        try:
            updates["lead_minutes"] = max(0, min(1440, int(body["lead_minutes"] or 0)))
        except (TypeError, ValueError):
            raise Refused(422, "minutos de antecedência inválidos")
    if "digest_time" in body:
        digest_time = _text(body["digest_time"], "horário do resumo", 5) or ""
        if digest_time and not DIGEST.match(digest_time):
            raise Refused(422, "horário do resumo no formato HH:MM")
        updates["digest_time"] = digest_time
    for key, limit in (
        ("telegram_token", 120),
        ("telegram_chat_id", 40),
        ("discord_webhook", 300),
        ("evolution_url", 300),
        ("evolution_apikey", 200),
        ("evolution_instance", 64),
        ("evolution_number", 60),
    ):
        if key in body:
            updates[key] = _text(body[key], key, limit) or ""
    number = updates.get("evolution_number")
    if number and not EVOLUTION_NUMBER.match(number):
        raise Refused(
            422,
            "WhatsApp: destino deve ser o número com DDI (5511999999999) ou o JID do grupo (...@g.us)",
        )
    problems = notify.channel_problems({**current, **updates})
    if problems:
        raise Refused(422, "; ".join(problems.values()))
    return updates


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
    con = db.connect()
    try:
        settings = db.get_settings(con, uid())
        channels = [
            channel
            for channel, enabled in (
                ("toast", is_owner() and settings.get("toast_enabled")),
                ("telegram", bool(settings.get("telegram_token") and settings.get("telegram_chat_id"))),
                ("discord", bool(settings.get("discord_webhook"))),
                (
                    "whatsapp",
                    bool(
                        settings.get("evolution_url")
                        and settings.get("evolution_apikey")
                        and settings.get("evolution_number")
                    ),
                ),
            )
            if enabled
        ]
        now = int(time.time())
        upcoming = []
        for account in db.list_accounts(con, uid()):
            snap = db.latest_snapshot(con, account["id"])
            if not snap:
                continue
            summary = metrics.compute(json.loads(snap["parsed_json"]), now_ts=now)
            for upgrade in summary["active_upgrades"]:
                if upgrade["finish_ts"] <= now:
                    continue
                upcoming.append({
                    "account": account["name"],
                    "name": upgrade["name"],
                    "to_lvl": upgrade["to_lvl"],
                    "queue": upgrade["queue"],
                    "finish_ts": upgrade["finish_ts"],
                    "already_notified": db.was_notified(
                        con,
                        notify.event_key(
                            "fin", account["id"], upgrade["data"], upgrade["finish_ts"]
                        ),
                    ),
                })
        upcoming.sort(key=lambda item: item["finish_ts"])
        return jsonify({
            "enabled": bool(settings.get("notify_enabled")),
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
        settings = db.get_settings(con, uid())
    finally:
        con.close()
    sent = notify.dispatch(
        settings,
        "🔔 COC Control",
        "Teste de notificação — canais funcionando!",
        trusted=is_owner(),
    )
    return jsonify({"sent": sent, "notify_enabled": bool(settings.get("notify_enabled"))})


def main():
    parser_cli = argparse.ArgumentParser()
    parser_cli.add_argument("--host", default="127.0.0.1")
    parser_cli.add_argument("--port", type=int, default=8420)
    parser_cli.add_argument("--no-watcher", action="store_true")
    parser_cli.add_argument("--no-browser", action="store_true")
    parser_cli.add_argument("--production", action="store_true")
    parser_cli.add_argument("--set-password", action="store_true")
    args = parser_cli.parse_args()

    if args.set_password:
        con = db.connect()
        try:
            password = getpass.getpass("Nova senha: ")
            if len(password) < 8:
                print("Use pelo menos 8 caracteres.")
                return
            if password != getpass.getpass("Confirme: "):
                print("Senhas não conferem.")
                return
            auth.set_password(con, password)
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
    print(
        f"COC Control em http://{args.host}:{args.port} | login: "
        f"{'ATIVO' if auth_on else 'desligado (local)'} | Clash Labs: "
        f"{'ligada' if labs.enabled() else 'desligada'} | watcher: "
        f"{'ativo' if watcher.enabled else 'desligado' if watcher.available else 'indisponível'}"
    )
    if production:
        from waitress import serve
        serve(app, host=args.host, port=args.port, threads=8)
    else:
        app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
