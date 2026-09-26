#!/usr/bin/env python3
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

tmp = tempfile.mkdtemp()
os.environ.update({
    'COC_DB': os.path.join(tmp, 'contract.db'),
    'ADMIN_USER': 'owner', 'ADMIN_PASSWORD': 'senha-segura-teste',
    'LABS_URL': 'https://labs.example', 'LABS_PRODUCT_SECRET': 's' * 48,
})
import app as A
from coc import db, labs

n = 0
def check(cond, msg):
    global n
    assert cond, 'FALHOU: ' + msg
    n += 1; print('  ✔', msg)

def as_user(client, uid):
    with client.session_transaction() as s: s['uid'] = uid
    client.set_cookie('csrf', 'csrf-test')

uid = '11111111-1111-4111-8111-111111111111'
check(labs.valid_labs_user_id(uid), 'UUID canônico aceito')
check(not labs.valid_labs_user_id('usuario_qualquer'), 'identificador não UUID recusado')

con = db.connect(); user = db.upsert_labs_user(con, uid, 'cliente@example.test', 'Cliente')
db.set_access(con, user['id'], int(time.time()) + 86400)
village = db.create_account(con, user['id'], 'Minha vila', '#TEST1'); user_id = user['id']; con.close()

original = labs._hub
labs._hub = lambda *a, **k: (_ for _ in ()).throw(labs.LabsError('offline'))
c = A.app.test_client()
r = c.post('/api/labs/webhook', json={'userId': uid}, headers={'Authorization':'Bearer '+'s'*48,'X-Labs-Product':'coc-control'})
check(r.status_code == 502, 'webhook retorna 502 quando não reconfirma entitlement')
labs._hub = original

con = db.connect(); db.set_user_suspension(con, user_id, True, 'revisão manual')
check(not labs.has_access(db.get_user(con, user_id)), 'suspensão manual bloqueia acesso')
db.set_access(con, user_id, int(time.time()) + 172800)
check(not labs.has_access(db.get_user(con, user_id)), 'sync não remove suspensão manual')
db.set_user_suspension(con, user_id, False)
check(labs.has_access(db.get_user(con, user_id)), 'reativação manual restaura acesso'); con.close()

c = A.app.test_client(); as_user(c, user_id)
exported = c.get('/api/me/export').get_json()
check(exported['user']['labs_user_id'] == uid, 'exporta dados do próprio usuário')
check('api_key_hash' not in exported['user'], 'export não revela hash da API key')
check('supercell_token' not in str(exported), 'export não revela token global Supercell')
r = c.delete('/api/me/data', headers={'X-CSRF':'csrf-test'})
check(r.status_code == 200, 'assinante exclui os próprios dados')
con = db.connect(); check(db.get_user(con, user_id) is None, 'usuário removido')
check(db.get_account(con, user_id, village['id']) is None, 'vila removida em cascade')
check(con.execute("SELECT 1 FROM access_audit WHERE user_id=? AND event='data-deleted'", (user_id,)).fetchone() is not None, 'auditoria de exclusão preservada')
con.close(); print(f'\n{n} verificações adicionais passaram ✔')
