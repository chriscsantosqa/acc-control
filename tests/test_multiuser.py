#!/usr/bin/env python3
"""Testes do multiusuário: migração do banco antigo, entrada pela Clash Labs, isolamento
entre assinantes, passe vencido, limites e canais de alerta dos assinantes.
Rodar da raiz: python tests/test_multiuser.py"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
HERE = os.path.dirname(__file__)
ok = 0


def check(cond, msg):
    global ok
    assert cond, "FALHOU: " + msg
    ok += 1
    print("  ✔", msg)


# ------------------------------------------------ vitrine falsa (confere o segredo como a real)
SECRET = "s" * 48
USERS = {"A": "11111111-1111-4111-8111-111111111111", "B": "22222222-2222-4222-8222-222222222222"}
hub = {"active": {USERS["A"]: True, USERS["B"]: True}, "redeemed": set(), "redeem_calls": 0}


def until(days=30):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).isoformat().replace("+00:00", "Z")


class Hub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        return (self.headers.get("Authorization") == f"Bearer {SECRET}"
                and self.headers.get("X-Labs-Product") == "coc-control")

    def _ent(self, uid):
        on = hub["active"].get(uid, False)
        return {"product": "coc-control", "active": on, "accessUntil": until() if on else None}

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/v1/sso/redeem":
            hub["redeem_calls"] += 1
            code = body.get("code", "")
            who = code[5] if code.startswith("good-") else None
            if who not in USERS or code in hub["redeemed"]:
                return self._send(400, {"error": "invalid_code"})
            hub["redeemed"].add(code)
            uid = USERS[who]
            return self._send(200, {"user": {"id": uid, "email": f"{who.lower()}@teste.dev", "name": f"Líder {who}"},
                                    "entitlement": self._ent(uid)})
        self._send(404, {})

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "unauthorized"})
        if self.path.startswith("/api/v1/entitlements/"):
            return self._send(200, self._ent(self.path.rsplit("/", 1)[1]))
        self._send(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Hub)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# ------------------------------------------------ banco no formato antigo (um usuário só)
tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, "legado.db")
os.environ.update({
    "COC_DB": DB, "ADMIN_USER": "dono", "ADMIN_PASSWORD": "senha-do-dono-1",
    "LABS_URL": "https://labs.example", "LABS_API_URL": f"http://127.0.0.1:{srv.server_address[1]}",
    "LABS_PRODUCT_SECRET": SECRET,
})
from coc import parser  # noqa: E402
RAW = open(os.path.join(HERE, "fixture_real_th18.json")).read()
PARSED = json.dumps(parser.parse(RAW))
OLD_KEY = "chave-antiga-da-automacao-0123456789"
legacy = sqlite3.connect(DB)
legacy.executescript("""
CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, tag TEXT UNIQUE, name TEXT NOT NULL,
  notes TEXT DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  verified INTEGER DEFAULT 0, verified_at INTEGER);
CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, taken_at INTEGER NOT NULL,
  imported_at INTEGER NOT NULL, th_level INTEGER, raw_json TEXT NOT NULL, parsed_json TEXT NOT NULL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE player_stats (id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, fetched_at INTEGER NOT NULL, json TEXT NOT NULL);
INSERT INTO accounts VALUES (7, '#OLD1', 'Main do dono', '', 1, 1, 1, 5);
INSERT INTO accounts VALUES (9, '#OLD2', 'Alt do dono', '', 1, 1, 0, NULL);
INSERT INTO player_stats VALUES (1, 7, 100, '{"trophies": 5000}');
""")
for sid, acc, ts in ((1, 7, 100), (2, 7, 200), (3, 9, 300)):
    legacy.execute("INSERT INTO snapshots VALUES (?, ?, ?, ?, 18, ?, ?)", (sid, acc, ts, ts, RAW, PARSED))
legacy.execute("INSERT INTO settings VALUES ('telegram_chat_id', ?)", (json.dumps("999"),))
legacy.execute("INSERT INTO settings VALUES ('notify_enabled', 'true')")
legacy.execute("INSERT INTO settings VALUES ('supercell_token', ?)", (json.dumps("tok-do-dono"),))
legacy.execute("INSERT INTO settings VALUES ('api_key', ?)", (json.dumps(OLD_KEY),))
legacy.commit()
legacy.close()

import app as A  # noqa: E402  (migra o banco ao importar)
from coc import db, labs, netguard, notify  # noqa: E402

print("[1] migração do banco de um usuário só")
con = db.connect()
owner = db.owner_id(con)
rows = con.execute("SELECT id, user_id, tag, verified FROM accounts ORDER BY id").fetchall()
check([(r["id"], r["user_id"]) for r in rows] == [(7, owner), (9, owner)], "vilas antigas passam a ser do dono, com os mesmos ids")
check(rows[0]["verified"] == 1, "selo de verificação preservado")
check(con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 3, "nenhum snapshot perdido na migração")
check(con.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0] == 1, "estatísticas preservadas")
st = db.get_settings(con, owner)
check(st["telegram_chat_id"] == "999" and st["notify_enabled"] is True, "alertas antigos viram do dono")
check(st["supercell_token"] == "tok-do-dono", "chave da Supercell continua do servidor")
check(con.execute("SELECT 1 FROM settings WHERE key='api_key'").fetchone() is None, "API key antiga não fica mais em texto")
check(not con.execute("PRAGMA foreign_key_check").fetchall(), "referências íntegras")
new = db.create_account(con, owner, "Nova", tag="#NEW1")
check(new["id"] > 9, "ids novos continuam depois dos antigos")
db.delete_account(con, owner, new["id"])
con.close()
db._ready.discard(db.DB_PATH)
con = db.connect()           # rodar de novo não migra de novo
check(con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 2, "migração idempotente")
con.close()

print("[2] entrada pela Clash Labs")
state_of = lambda r: parse_qs(urlsplit(r.headers["Location"]).query)["state"][0]  # noqa: E731


def csrf_of(resp):
    for k, v in resp.headers:
        if k == "Set-Cookie" and v.startswith("csrf="):
            return v.split("=", 1)[1].split(";")[0]
    return None


def enter(client, who, n):
    r = client.get("/entrar/clash-labs")
    assert r.status_code == 302 and r.headers["Location"].startswith("https://labs.example/app/coc-control?state=")
    r = client.get(f"/api/labs/callback?code=good-{who}-{str(n).ljust(40, 'x')}&state={state_of(r)}")
    return r


ca, cb, cx = A.app.test_client(), A.app.test_client(), A.app.test_client()
calls = hub["redeem_calls"]
r = ca.get(f"/api/labs/callback?code=good-A-{'z' * 40}")
check(r.status_code == 302 and r.headers["Location"].endswith("/entrar/clash-labs") and hub["redeem_calls"] == calls,
      "sem state (botão Abrir da vitrine): recomeça daqui e o código recebido não é trocado")
r1 = cx.get("/entrar/clash-labs")
r = ca.get(f"/api/labs/callback?code=good-A-{'y' * 40}&state={state_of(r1)}")
check("passe=expirou" in r.headers["Location"] and hub["redeem_calls"] == calls,
      "state de outro navegador é recusado antes de trocar o código")
r = enter(ca, "A", 1)
check(r.status_code == 302 and r.headers["Location"].endswith("/"), "assinante entra e cai no painel")
csrf_a = csrf_of(r)
me = ca.get("/api/me").json
check(me["role"] == "subscriber" and me["email"] == "a@teste.dev" and me["active"], "conta do assinante criada com o passe ativo")
r = enter(cb, "B", 1)
csrf_b = csrf_of(r)
check(cb.get("/api/me").json["email"] == "b@teste.dev", "segundo assinante com conta própria")
cz = A.app.test_client()
st = state_of(cz.get("/entrar/clash-labs"))
r = cz.get(f"/api/labs/callback?code=good-A-{'1'.ljust(40, 'x')}&state={st}")
check("passe=erro" in r.headers["Location"], "código usado de novo é recusado pela vitrine")
r = ca.get("/api/labs/callback?code=x&state=qualquer-coisa-1234")
check("passe=expirou" in r.headers["Location"], "state já usado não vale de novo")
con = db.connect()
check(con.execute("SELECT COUNT(*) FROM users WHERE role='subscriber'").fetchone()[0] == 2, "entrar de novo não duplica o assinante")
con.close()

print("[3] cada assinante só vê as próprias vilas")
H = lambda tok: {"X-CSRF": tok}  # noqa: E731
raw = open(os.path.join(HERE, "fixture_real_th18.json")).read()
ra = ca.post("/api/import", data=raw, content_type="application/json", headers=H(csrf_a))
check(ra.status_code == 201, "assinante A importa a vila")
aid = ra.json["account"]["id"]
rb = cb.post("/api/import", data=raw, content_type="application/json", headers=H(csrf_b))
check(rb.status_code == 201 and rb.json["account"]["id"] != aid, "a mesma tag vira uma vila separada para B")
bid = rb.json["account"]["id"]
check([a["id"] for a in cb.get("/api/accounts").json] == [bid], "B lista só a vila dele (nem as do dono)")
check([a["id"] for a in ca.get("/api/accounts").json] == [aid], "A lista só a vila dele")
check(cb.get(f"/api/accounts/{aid}/detail").status_code == 404, "B não abre o detalhe da vila de A")
check(cb.get(f"/api/accounts/{aid}/plan").status_code == 404, "B não vê o planner de A")
check(cb.get("/api/accounts/7/detail").status_code == 404, "assinante não vê vila do dono")
check(cb.patch(f"/api/accounts/{aid}", json={"name": "hackeada"}, headers=H(csrf_b)).status_code == 404, "B não renomeia a vila de A")
check(cb.post(f"/api/accounts/{aid}/sync-supercell", headers=H(csrf_b)).status_code == 404, "B não sincroniza a vila de A")
check(cb.post(f"/api/accounts/{aid}/verify", json={"token": "x"}, headers=H(csrf_b)).status_code == 404, "B não verifica a vila de A")
sid = ca.get(f"/api/accounts/{aid}/detail").json["summary"]["snapshot_id"]
check(cb.delete(f"/api/snapshots/{sid}", headers=H(csrf_b)).status_code == 404, "snapshot de outro usuário responde 404")
check(cb.delete(f"/api/accounts/{aid}", headers=H(csrf_b)).status_code == 404, "vila de outro usuário responde 404")
d = ca.get(f"/api/accounts/{aid}/detail").json
check(d["account"]["name"] != "hackeada" and d["summary"]["snapshot_id"] == sid, "exclusões de B não alcançam os dados de A")
r = cb.post(f"/api/import?account_id={aid}", data=raw, content_type="application/json", headers=H(csrf_b))
check(r.status_code == 404, "import com id de vila de outro usuário responde 404")
check(len(ca.get(f"/api/accounts/{aid}/detail").json["history"]) == 1, "vila de A continua com 1 snapshot")
check(ca.post("/api/import", data=raw, content_type="application/json").status_code == 403, "sessão sem X-CSRF é bloqueada")

print("[4] recursos do dono")
check(ca.post("/api/watcher", json={"enabled": True}, headers=H(csrf_a)).status_code == 403, "watcher do servidor é só do dono")
check(ca.get("/api/status").json["watcher"]["available"] is False, "assinante usa o watcher do navegador")
check(ca.get("/api/admin/subscribers").status_code == 403, "assinante não lista assinantes")
sa = ca.get("/api/settings").json
check("supercell_token" not in sa and sa["supercell_configured"] is True, "chave da Supercell não chega ao assinante")
ca.put("/api/settings", json={"supercell_token": "roubada", "lead_minutes": 10}, headers=H(csrf_a))
con = db.connect()
check(db.get_settings(con, owner)["supercell_token"] == "tok-do-dono", "assinante não troca a chave da Supercell")
con.close()
co = A.app.test_client()
r = co.post("/api/login", json={"username": "dono", "password": "senha-do-dono-1"})
csrf_o = csrf_of(r)
check(r.status_code == 200 and {a["id"] for a in co.get("/api/accounts").json} == {7, 9}, "dono entra com a senha e vê as vilas antigas")
subs = co.get("/api/admin/subscribers").json
check(sorted(s["email"] for s in subs) == ["a@teste.dev", "b@teste.dev"], "dono lista os assinantes")
check(all("labs_user_id" not in s and "api_key_hash" not in s for s in subs), "lista sem ids internos nem hashes")
check(co.post("/api/import", data=raw, content_type="application/json",
              headers={"Authorization": "Bearer " + OLD_KEY}).json["account"]["user_id"] == owner,
      "API key antiga da automação continua valendo, para o dono")

print("[5] API key por assinante")
key_a = ca.post("/api/apikey", headers=H(csrf_a)).json["api_key"]
bot = A.app.test_client()
r = bot.post("/api/import", data=raw, content_type="application/json", headers={"Authorization": "Bearer " + key_a})
check(r.status_code == 201 and r.json["account"]["id"] == aid, "a chave de A importa na vila de A")
key_a2 = ca.post("/api/apikey", headers=H(csrf_a)).json["api_key"]
check(bot.get("/api/accounts", headers={"Authorization": "Bearer " + key_a}).status_code == 401, "chave trocada deixa de valer")
check(bot.get("/api/accounts", headers={"Authorization": "Bearer " + key_a2}).status_code == 200, "chave nova vale")
check(ca.get("/api/me").json["api_key_hint"] == key_a2[-4:], "só o final da chave fica visível")

print("[6] passe encerrado e renovado")
wh = A.app.test_client()
body = {"userId": USERS["A"]}
check(wh.post("/api/labs/webhook", json=body).status_code == 401, "aviso sem segredo é recusado")
check(wh.post("/api/labs/webhook", json=body, headers={"Authorization": "Bearer " + "x" * 48,
                                                        "X-Labs-Product": "coc-control"}).status_code == 401, "aviso com segredo errado é recusado")
check(wh.post("/api/labs/webhook", json=body, headers={"Authorization": "Bearer " + SECRET,
                                                        "X-Labs-Product": "cla-command"}).status_code == 401, "aviso de outro produto é recusado")
LH = {"Authorization": "Bearer " + SECRET, "X-Labs-Product": "coc-control"}
hub["active"][USERS["A"]] = False
check(wh.post("/api/labs/webhook", json=body, headers=LH).status_code == 200, "aviso da vitrine aceito")
r = ca.get("/api/accounts")
check(r.status_code == 402 and r.json["passe"] == "inativo" and r.json["store"].startswith("https://labs.example"),
      "passe encerrado: 402 com o caminho da renovação")
check(bot.get("/api/accounts", headers={"Authorization": "Bearer " + key_a2}).status_code == 402, "API key do assinante também para")
check(ca.get("/api/me").status_code == 200 and ca.get("/api/me").json["active"] is False, "ainda vê a própria conta para renovar")
check(cb.get("/api/accounts").status_code == 200, "o passe de A não afeta B")
con = db.connect()
check(USERS["A"] not in [u.get("labs_user_id") for u in db.users_to_notify(con, int(A.time.time()))], "sem passe, sem alertas")
con.close()
hub["active"][USERS["A"]] = True
wh.post("/api/labs/webhook", json=body, headers=LH)
check(ca.get("/api/accounts").status_code == 200 and len(ca.get(f"/api/accounts/{aid}/detail").json["history"]) == 2,
      "renovou: volta com as vilas e o histórico intactos")
# renovação cujo aviso se perdeu: o próprio pedido relê o passe
hub["active"][USERS["A"]] = False
wh.post("/api/labs/webhook", json=body, headers=LH)
hub["active"][USERS["A"]] = True
con = db.connect()
con.execute("UPDATE users SET checked_at = checked_at - 3600 WHERE labs_user_id = ?", (USERS["A"],))
con.commit()
con.close()
check(ca.get("/api/accounts").status_code == 200, "aviso perdido: o acesso volta ao abrir o painel")
check(wh.post("/api/labs/webhook", json={"userId": "../../etc"}, headers=LH).status_code == 422, "userId inválido é recusado")
check(wh.post("/api/labs/webhook", json={"userId": "33333333-3333-4333-8333-333333333333"}, headers=LH).json == {"ok": True},
      "aviso de quem não tem conta aqui é aceito sem revelar nada")
check(labs.access_until({"product": "coc-control", "active": True, "accessUntil": "2020-01-01T00:00:00Z"}) is None, "data passada não libera")
check(labs.access_until({"product": "clashnato", "active": True, "accessUntil": until()}) is None, "passe de outro produto não libera")
check(labs.access_until({"product": "coc-control", "active": True, "accessUntil": "amanhã"}) is None, "data inválida não libera")

print("[7] limites do assinante")
A.MAX_ACCOUNTS = 2
check(ca.post("/api/accounts", json={"name": "Alt 1"}, headers=H(csrf_a)).status_code == 201, "cria vila dentro do limite")
r = ca.post("/api/accounts", json={"name": "Alt 2"}, headers=H(csrf_a))
check(r.status_code == 403 and "Limite" in r.json["error"], "limite de vilas por assinatura")
check(co.post("/api/accounts", json={"name": "Dono sem limite"}, headers=H(csrf_o)).status_code == 201, "dono não tem limite")
A.MAX_SNAPSHOTS = 2
for _ in range(3):
    ca.post("/api/import", data=raw, content_type="application/json", headers=H(csrf_a))
check(len(ca.get(f"/api/accounts/{aid}/detail").json["history"]) == 2, "histórico do assinante guarda os mais recentes")
check(ca.post("/api/accounts", json={"name": "x", "tag": "../../clans"}, headers=H(csrf_a)).status_code == 400, "tag fora do formato é recusada")

print("[8] canais de alerta dos assinantes")
bad = [("https://127.0.0.1", "interna"), ("https://10.0.0.5", "interna"), ("https://169.254.169.254", "interna"),
       ("https://[::1]", "interna"), ("http://8.8.8.8", "https"), ("https://user@8.8.8.8", "inválido")]
for url, why in bad:
    check(why in (netguard.public_https_problem(url) or ""), f"netguard recusa {url}")
check(netguard.public_https_problem("https://8.8.8.8") is None, "netguard aceita IP público")
check(netguard.discord_problem("https://discord.com/api/webhooks/123456789/" + "a" * 60) is None, "webhook do Discord aceito")
check(netguard.discord_problem("https://evil.example/api/webhooks/1/x") is not None, "outro host no lugar do Discord é recusado")
r = ca.put("/api/settings", json={"evolution_url": "https://127.0.0.1:8080"}, headers=H(csrf_a))
check(r.status_code == 422 and "interna" in r.json["error"], "assinante não aponta o WhatsApp para dentro do servidor")
r = ca.put("/api/settings", json={"discord_webhook": "http://localhost:5678/webhook"}, headers=H(csrf_a))
check(r.status_code == 422, "assinante não aponta o Discord para outro lugar")
r = ca.put("/api/settings", json={"telegram_token": "123456:" + "A" * 35, "telegram_chat_id": "42", "digest_time": "08:00"}, headers=H(csrf_a))
check(r.status_code == 200 and r.json["telegram_chat_id"] == "42", "canal válido é salvo")
check(ca.put("/api/settings", json={"digest_time": "25:99"}, headers=H(csrf_a)).status_code == 422, "horário inválido é recusado")
check(cb.get("/api/settings").json["telegram_chat_id"] == "", "configurações de A não aparecem para B")
check(co.put("/api/settings", json={"evolution_url": "http://evolution:8080"}, headers=H(csrf_o)).status_code == 200,
      "dono continua podendo usar a Evolution interna")
sent = []
notify.send_toast = lambda t, b: sent.append("toast") or True
notify.send_evolution = lambda *a: sent.append("evolution") or True
notify.dispatch({"toast_enabled": True, "evolution_url": "https://127.0.0.1", "evolution_apikey": "k",
                 "evolution_number": "5511999999999"}, "t", "b", trusted=False)
check(sent == [], "no envio, assinante não recebe toast nem chega a endereço interno")
notify.dispatch({"toast_enabled": True, "evolution_url": "https://127.0.0.1", "evolution_apikey": "k",
                 "evolution_number": "5511999999999"}, "t", "b", trusted=True)
check(sent == ["toast", "evolution"], "o dono segue sem restrição")

print("[9] alertas por usuário")
seen = []
A.notify.dispatch = lambda st, title, body, trusted=True: seen.append((st.get("telegram_chat_id"), trusted)) or ["x"]
con = db.connect()
db.set_settings(con, db.get_user_by_labs(con, USERS["A"])["id"], {"notify_enabled": True, "digest_time": "00:00"})
con.close()
A.notifier.scan_once()
check(("42", False) in seen, "resumo diário de A sai pelos canais de A, sem os privilégios do dono")
check(all(chat != "42" or trusted is False for chat, trusted in seen), "canais de A nunca recebem alertas como dono")

print("[10] sair")
check(ca.post("/api/logout", headers=H(csrf_a)).status_code == 200 and ca.get("/api/accounts").status_code == 401, "logout encerra a sessão do assinante")

srv.shutdown()
print(f"\n{ok} verificações passaram ✔")
