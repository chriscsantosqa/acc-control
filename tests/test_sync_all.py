#!/usr/bin/env python3
"""Testes: sync de todas as contas, sync ao criar, não-destrutividade.
Rodar da raiz: python tests/test_sync_all.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COC_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app as A
from coc import supercell_api
HERE = os.path.dirname(__file__)
c = A.app.test_client()
ok = 0
def check(cond, msg):
    global ok; assert cond, "FALHOU: " + msg; ok += 1; print("  ✔", msg)

raw = open(os.path.join(HERE, "fixture_real_th18.json")).read()
c.post("/api/import", data=raw, content_type="application/json")
r = c.post("/api/accounts", json={"name": "Sem tag"})
check(r.status_code == 201 and r.json["synced"] is False, "criação sem tag não tenta sync")
r = c.post("/api/accounts", json={"name": "Alt com tag", "tag": "#ABC123"})
check(r.status_code == 201, "criação com tag sem token não bloqueia")
r = c.post("/api/sync-all")
check(r.status_code == 200 and r.json["total"] == 3 and r.json["synced"] == 0,
      "sync-all resiliente sem token")
def fake_fetch(tag, token):
    if tag == "#ABC123":
        raise supercell_api.ApiError("jogador não encontrado")
    return {"tag": tag, "name": "EL.BR_NbsK", "trophies": 860, "league": "Lenda II"}
A.supercell_api.fetch_player = fake_fetch
con = A.db.connect(); A.db.set_settings(con, A.db.owner_id(con), {"supercell_token": "tok"}); con.close()
r = c.post("/api/sync-all")
check(r.json["synced"] == 1 and r.json["total"] == 3, "falha isolada não interrompe o lote")
accs = c.get("/api/accounts").json
names = [a["name"] for a in accs]
check("EL.BR_NbsK" in names and "Alt com tag" in names, "adoção de nome só em nomes automáticos")
main = next(a for a in accs if a["name"] == "EL.BR_NbsK")
check(main["snapshots"] == 1 and main["latest"]["th_level"] == 18,
      "dados pré-existentes intactos (não destrutivo)")
print(f"\n{ok} verificações passaram ✔")
