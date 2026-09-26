#!/usr/bin/env python3
"""Smoke tests do COC Control. Rodar da raiz: python tests/test_basic.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COC_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from coc import parser, metrics, gamedata  # noqa: E402
HERE = os.path.dirname(__file__)
ok = 0

def check(cond, msg):
    global ok
    assert cond, f"FALHOU: {msg}"
    ok += 1
    print(f"  ✔ {msg}")

print("[1] parser — export real TH18")
raw = open(os.path.join(HERE, "fixture_real_th18.json")).read()
snap = parser.parse(raw)
check(snap["tag"] == "#PJ9UURQYU", "tag extraída")
check(snap["th_level"] == 18, "TH detectado = 18")
check(snap["level_offset"] == 0, "níveis 1-based detectados")
check(snap["counts"]["unknown"] == 0, "todos os IDs conhecidos (com overrides)")
check(any(i["data"] == 102000024 for i in snap["items"]), "módulos aninhados da Estação de Criação")
check(parser.looks_like_village_export(raw), "heurística do watcher aceita export real")
check(not parser.looks_like_village_export('{"foo": 1}'), "heurística rejeita JSON qualquer")

print("[2] métricas — export real TH18")
s = metrics.compute(snap)
check(s["builders"]["total"] == 6, "6 construtores (5 cabanas + B.O.B)")
check(len(s["active_upgrades"]) == 6, "6 upgrades em andamento")
check(all(a["finish_ts"] > snap["timestamp"] for a in s["active_upgrades"]), "términos no futuro")
check(s["ores_needed"]["shiny"] > 0, "minérios p/ equipamentos calculados")
check(s["categories"]["defense"]["supercharged"] > 0, "supercharge contabilizado")
check(0 < s["progress_total"] <= 100, "progresso em range")
check(s["data_warnings"]["clamped_items"] > 0, "aviso de base desatualizada presente")

print("[3] métricas — export sintético TH16")
snap2 = parser.parse(open(os.path.join(HERE, "sample_export_th16.json")).read())
s2 = metrics.compute(snap2)
check(snap2["th_level"] == 16, "TH 16")
check(s2["pending_total"] > 0, "pendências calculadas")
check(s2["cost_left"].get("Gold", 0) > 0, "custo restante em ouro")
check(s2["next_th"] and s2["next_th"]["to_lvl"] == 17, "próximo CV = 17")
check(s2["eta"]["critical_secs"] >= s2["eta"]["lab_secs"], "caminho crítico >= lab")

print("[4] API end-to-end")
import app as A
c = A.app.test_client()
r = c.post("/api/import", data=raw, content_type="application/json")
check(r.status_code == 201, "import via API")
aid = r.json["account"]["id"]
check(c.post("/api/import", data=raw, content_type="application/json").status_code == 201, "2º snapshot")
r = c.get("/api/accounts")
check(len(r.json) == 1 and r.json[0]["latest"]["th_level"] == 18, "lista de contas com resumo")
r = c.patch(f"/api/accounts/{aid}", json={"name": "Main"})
check(r.json["name"] == "Main", "renomear conta")
r = c.get(f"/api/accounts/{aid}/detail")
check(len(r.json["history"]) == 2 and len(r.json["series"]) == 2, "histórico + série")
sid = r.json["summary"]["snapshot_id"]
check(c.delete(f"/api/snapshots/{sid}").status_code == 200, "excluir snapshot")
r = c.post("/api/accounts", json={"name": "Alt sem tag"})
check(r.status_code == 201, "criar conta manual")
check(c.delete(f"/api/accounts/{r.json['id']}").status_code == 200, "excluir conta")
check(c.get("/api/status").json["ok"], "status ok")

print(f"\n{ok} verificações passaram ✔")
