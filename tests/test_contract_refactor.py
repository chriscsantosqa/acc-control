#!/usr/bin/env python3
"""Contrato adicional da integração Clash Labs e suspensão manual."""
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

from coc import db, labs  # noqa: E402

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

print(f"\n{checks} verificações adicionais passaram ✔")
