#!/usr/bin/env python3
"""Contrato adicional da integração Clash Labs, bases e suspensão manual."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
os.environ.update({
    "COC_DB": os.path.join(tmp, "contract.db"),
    "ADMIN_USER": "owner",
    "ADMIN_PASSWORD": "senha-segura-teste",
    "LABS_URL": "https://labs.example",
    "LABS_PRODUCT_SECRET": "s" * 48,
})

from coc import db, gamedata, labs, metrics, planner  # noqa: E402

checks = 0


def check(value, message):
    global checks
    assert value, "FALHOU: " + message
    checks += 1
    print("  ✔", message)


valid = "11111111-1111-4111-8111-111111111111"
check(labs.valid_labs_user_id(valid), "UUID canônico é aceito")
check(not labs.valid_labs_user_id("usuario_qualquer"), "identificador não UUID é recusado")
check(not labs.valid_labs_user_id("../../etc"), "entrada malformada é recusada")

con = db.connect()
user = db.upsert_labs_user(con, valid, "cliente@example.test", "Cliente")
db.set_access(con, user["id"], int(time.time()) + 86400)
check(labs.has_access(db.get_user(con, user["id"])), "entitlement futuro libera acesso")

db.set_user_suspension(con, user["id"], True, "suporte: revisão manual")
check(not labs.has_access(db.get_user(con, user["id"])), "suspensão manual bloqueia acesso")
db.set_access(con, user["id"], int(time.time()) + 172800)
check(not labs.has_access(db.get_user(con, user["id"])), "sincronização não remove suspensão manual")
db.set_user_suspension(con, user["id"], False)
check(labs.has_access(db.get_user(con, user["id"])), "reativação manual restaura acesso")

exported = db.export_user_data(con, user["id"])
check("api_key_hash" not in exported["user"], "exportação não inclui hash da API key")
check("supercell_token" not in str(exported), "exportação não inclui token global da Supercell")
check(con.execute("SELECT COUNT(*) FROM access_audit WHERE user_id=?", (user["id"],)).fetchone()[0] >= 3,
      "alterações de acesso ficam auditadas")
con.close()

# Contrato Vila Principal x Base do Construtor.
def data_id(entity_id):
    for raw, entity in gamedata.load()["entities"].items():
        if entity.get("id") == entity_id:
            return int(raw)
    raise AssertionError(f"entidade ausente no game_data: {entity_id}")


def data_id_by_name(name, base):
    for raw, entity in gamedata.load()["entities"].items():
        if entity.get("name") == name and entity.get("base", "home") == base:
            return int(raw)
    raise AssertionError(f"entidade ausente no game_data: {name} ({base})")


snapshot = {
    "timestamp": int(time.time()),
    "th_level": 18,
    "level_offset": 0,
    "counts": {"unknown": 0},
    "unknown_ids": [],
    "items": [
        {"data": data_id("town-hall"), "lvl": 18, "cnt": 1, "timer": None, "known": True, "ignored": False},
        {"data": data_id("builders-apprentice"), "lvl": 1, "cnt": 1, "timer": None, "known": True, "ignored": False},
        {"data": data_id("lab-assistant"), "lvl": 1, "cnt": 1, "timer": None, "known": True, "ignored": False},
        {"data": data_id_by_name("Builder Hall", "builder"), "lvl": 6, "cnt": 1, "timer": None, "known": True, "ignored": False},
        {"data": data_id_by_name("Cannon", "builder"), "lvl": 1, "cnt": 1, "timer": None, "known": True, "ignored": False},
    ],
}
summary = metrics.compute(snapshot)
check("builder_base" in summary, "métricas expõem Base do Construtor separadamente")
check(summary["builder_base"]["builder_hall_level"] == 6, "nível do Centro do Construtor é identificado")
check("bb-defense" in summary["builder_base"]["categories"], "defesas da Base do Construtor não entram na Vila Principal")
check(any(item["base"] == "builder" for item in summary["inventory"]), "inventário preserva a base de cada entidade")

plan = planner.plan(snapshot, summary, "balanced", now_ts=int(time.time()))
home_names = {row["name"] for row in plan["builders"]["schedule"]}
check("Builder's Apprentice" not in home_names and "Lab Assistant" not in home_names,
      "ajudantes não ocupam fila de construtor")
check("builder_base" in plan, "planejador devolve cronograma próprio da Base do Construtor")
check(all(row.get("base") == "builder" for row in plan["builder_base"]["builders"]["schedule"]),
      "cronograma da Base do Construtor não mistura entidades da Vila Principal")

print(f"\n{checks} verificações adicionais passaram ✔")
