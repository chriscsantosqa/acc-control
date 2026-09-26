#!/usr/bin/env python3
"""Testes de segurança (login, CSRF, lockout, Bearer) e canal WhatsApp.
Rodar da raiz: python tests/test_auth.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COC_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["ADMIN_PASSWORD"] = "senha-super-8"
import app as A
from coc import db, notify
HERE = os.path.dirname(__file__)
c = A.app.test_client()
ok = 0
def check(cond, msg):
    global ok; assert cond, "FALHOU: " + msg; ok += 1; print("  ✔", msg)

check(c.get("/api/accounts").status_code == 401, "API bloqueada sem login")
r = c.get("/", follow_redirects=False)
check(r.status_code == 302 and "/login" in r.location, "raiz redireciona p/ /login")
check(c.get("/api/health").status_code == 200, "/api/health público")
check(c.post("/api/login", json={"username": "admin", "password": "x"}).status_code == 401, "senha errada rejeitada")
for _ in range(4):
    c.post("/api/login", json={"username": "admin", "password": "x"})
r = c.post("/api/login", json={"username": "admin", "password": "senha-super-8"})
check(r.status_code == 401, "lockout após 5 falhas")
con = db.connect(); con.execute("DELETE FROM login_attempts"); con.commit(); con.close()
r = c.post("/api/login", json={"username": "admin", "password": "senha-super-8"})
check(r.status_code == 200, "login correto aceito")
csrf = next(v.split("=")[1].split(";")[0] for k, v in r.headers if k == "Set-Cookie" and v.startswith("csrf="))
check(c.get("/api/accounts").status_code == 200, "API liberada com sessão")
check(c.post("/api/accounts", json={"name": "X"}).status_code == 403, "POST sem X-CSRF bloqueado")
check(c.post("/api/accounts", json={"name": "X"}, headers={"X-CSRF": csrf}).status_code == 201, "POST com X-CSRF ok")
con = db.connect(); key = db.new_api_key(con, db.owner_id(con)); con.close()
c2 = A.app.test_client()
raw = open(os.path.join(HERE, "fixture_real_th18.json")).read()
check(c2.post("/api/import", data=raw, content_type="application/json").status_code == 401, "import sem credencial bloqueado")
check(c2.post("/api/import", data=raw, content_type="application/json",
              headers={"Authorization": "Bearer " + key}).status_code == 201, "import com Bearer ok")
check(c2.post("/api/import", data=raw, content_type="application/json",
              headers={"Authorization": "Bearer nope"}).status_code == 401, "Bearer inválido rejeitado")
h = c.get("/").headers
check("Content-Security-Policy" in h and h["X-Frame-Options"] == "DENY", "headers de segurança")
check(c.post("/api/logout", headers={"X-CSRF": csrf}).status_code == 200, "logout")
check(c.get("/api/accounts").status_code == 401, "sessão encerrada")

class FakeResp: status_code = 201
class FakeReq:
    def post(self, url, json=None, headers=None, timeout=None, **kw):
        assert kw.get("allow_redirects") is False
        assert url.endswith("/message/sendText/principal") and headers["apikey"] == "KEY"
        assert json["number"] == "5511999999999" and json["text"].startswith("*")
        return FakeResp()
notify.requests = FakeReq()
sent = notify.dispatch({"toast_enabled": False, "evolution_url": "https://ev.x",
                        "evolution_apikey": "KEY", "evolution_instance": "principal",
                        "evolution_number": "5511999999999"}, "T", "b")
check(sent == ["whatsapp"], "canal WhatsApp (Evolution API)")
print(f"\n{ok} verificações passaram ✔")
