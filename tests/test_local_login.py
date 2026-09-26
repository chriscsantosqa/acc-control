#!/usr/bin/env python3
"""Regressão do fluxo visual de logout quando a autenticação local está desligada."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COC_DB"] = os.path.join(tempfile.mkdtemp(), "local-login.db")
os.environ["COC_AUTH"] = "0"
os.environ.pop("ADMIN_PASSWORD", None)
os.environ.pop("ADMIN_PASSWORD_HASH", None)
os.environ.pop("LABS_URL", None)
os.environ.pop("LABS_PRODUCT_SECRET", None)

import app as A

c = A.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    assert cond, "FALHOU: " + msg
    ok += 1
    print("  ✔", msg)


check(c.get("/").status_code == 200, "modo local aberto acessa dashboard")
login = c.get("/login", follow_redirects=False)
check(login.status_code == 302 and login.location.endswith("/"),
      "rota /login continua redirecionando no modo aberto")
check(c.post("/api/logout").status_code == 200, "logout local responde 200")
landing = c.get("/static/login.html?local=1&logout=1")
check(landing.status_code == 200, "landing local de login é acessível")
html = landing.get_data(as_text=True)
check("Entrar localmente" in html and "Modo local" in html,
      "landing explica autenticação local desabilitada")
fixes = c.get("/static/fantasy-fixes.js").get_data(as_text=True)
check("/static/login.html?local=1&logout=1" in fixes,
      "logout frontend direciona modo aberto para landing local")

print(f"\n{ok} verificações passaram ✔")
