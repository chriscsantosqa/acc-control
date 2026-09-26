#!/usr/bin/env python3
"""Testes das funcionalidades v3: diff, velocidade, planner, alertas, settings, Supercell."""
import copy, json, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["COC_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from coc import parser, metrics, diff as diffmod, planner, notify, supercell_api  # noqa
HERE = os.path.dirname(__file__)
ok = 0
def check(cond, msg):
    global ok
    assert cond, f"FALHOU: {msg}"
    ok += 1; print(f"  ✔ {msg}")

raw = json.load(open(os.path.join(HERE, "sample_export_th16.json")))
snap_a = parser.parse(json.dumps(raw))

print("[1] diff entre snapshots")
raw_b = copy.deepcopy(raw)
raw_b["timestamp"] += 3 * 86400
for b in raw_b["buildings"]:
    if b["data"] == 1000009 and "cnt" not in b:      # sobe uma archer tower
        b["lvl"] += 1; b.pop("timer", None); break
raw_b["buildings"].append({"data": 1000032, "lvl": 1})   # constrói bomb tower
for u in raw_b["units"]:
    if u["data"] == 4000000: u["timer"] = 3600            # inicia pesquisa barbaro
snap_b = parser.parse(json.dumps(raw_b))
df = diffmod.compute_diff(snap_a, snap_b)
check(df["days"] == 3.0, "janela de 3 dias")
check(df["totals"]["upgraded_levels"] >= 1, "níveis concluídos detectados")
check(df["totals"]["built"] >= 1, "construção nova detectada")
check(df["totals"]["started"] >= 1, "upgrade iniciado detectado")
check(sum(df["spent_estimate"].values()) > 0, "gasto estimado calculado")

print("[2] velocidade real")
now = int(time.time())
serie = [{"taken_at": now - 10*86400, "progress": 70.0}, {"taken_at": now, "progress": 75.0}]
v = diffmod.velocity(serie)
check(abs(v["pct_per_day"] - 0.5) < 0.01, "0.5%/dia")
check(abs(v["days_to_max"] - 50) < 1, "~50 dias p/ 100%")
check(diffmod.velocity([serie[0]]) is None, "1 ponto só → sem velocidade")

print("[3] planner")
s = metrics.compute(snap_a)
p = planner.plan(snap_a, s, "defense", now_ts=now)
check(len(p["suggestions"]) > 0, "sugestões geradas")
check(all(x["category"] in ("defense","trap") for x in p["suggestions"][:3]), "estratégia defesa prioriza defesas")
sched = p["builders"]["schedule"]
check(all(sched[i]["start"] <= sched[i]["end"] for i in range(len(sched))), "start<=end")
# cadeia: mesmo prédio não sobrepõe
by_item = {}
for x in sched:
    key = (x["name"], x["worker"])
per_inst = {}
p2 = planner.plan(snap_a, s, "cheap", now_ts=now)
check(p2["suggestions"][0]["cost"] <= p["suggestions"][0]["cost"], "estratégia 'barato' começa mais barato")
check(p["projected_all_done"] > now, "projeção no futuro")

print("[4] alertas")
acc = {"id": 1, "name": "Main"}
st = {"lead_minutes": 30, "toast_enabled": False}
summ = {"active_upgrades": [
    {"data": 9, "name": "X-Bow", "from_lvl": 5, "to_lvl": 6, "finish_ts": now - 60, "queue": "builder"},
    {"data": 8, "name": "Barbarian", "from_lvl": 12, "to_lvl": 13, "finish_ts": now + 600, "queue": "lab"},
    {"data": 7, "name": "Monolith", "from_lvl": 1, "to_lvl": 2, "finish_ts": now + 86400, "queue": "builder"},
]}
evs = notify.build_events(acc, summ, st, now)
kinds = sorted(e["key"].split(":")[0] for e in evs)
check(kinds == ["fin", "soon"], "1 concluído + 1 'termina em breve' (o de amanhã fica fora)")
check("construtor liberado" in evs[0]["body"] or "construtor liberado" in evs[1]["body"], "menciona construtor liberado")
digest = notify.build_digest([(acc, {**summ, "th_level": 16, "progress_total": 80.0,
                                     "builders": {"total": 5}})], now)
check("Main" in digest and "construtores livres" in digest, "resumo diário montado")

print("[5] settings + dedupe + API supercell (endpoints)")
import app as A
c = A.app.test_client()
st2 = c.put("/api/settings", json={"notify_enabled": True, "lead_minutes": 15, "junk_key": 1}).json
check(st2["lead_minutes"] == 15 and "junk_key" not in st2, "settings salvos e chave inválida ignorada")
from coc import db
con = db.connect()
check(not db.was_notified(con, "k1"), "dedupe: não notificado")
db.mark_notified(con, "k1"); db.mark_notified(con, "k1")
check(db.was_notified(con, "k1"), "dedupe: marcado (idempotente)")
con.close()
r = c.post("/api/import", data=open(os.path.join(HERE, "fixture_real_th18.json")).read(),
           content_type="application/json")
aid = r.json["account"]["id"]
r = c.get(f"/api/accounts/{aid}/plan?strategy=farm")
check(r.status_code == 200 and r.json["strategy"] == "farm", "endpoint /plan")
r = c.post(f"/api/accounts/{aid}/sync-supercell")
check(r.status_code == 400 and "token" in r.json["error"], "sync sem token → erro amigável")
compact = supercell_api._compact({"tag": "#X", "name": "Chris", "trophies": 5400,
    "league": {"name": "Legend League"}, "clan": {"tag": "#C", "name": "BR"}, "role": "coLeader",
    "warStars": 900, "donations": 100, "donationsReceived": 50, "expLevel": 260})
check(compact["league"] == "Legend League" and compact["clan"]["name"] == "BR", "parse do player compacto")



print("[6] correções v4: liga, nome, verificação, migração")
check(supercell_api._league({"league": {"name": "Legend League"}}) == "Legend League", "liga: campo clássico")
check(supercell_api._league({"rankedLeague": {"name": "Lenda II"}}) == "Lenda II", "liga: campo ranqueado novo")
check(supercell_api._league({"superLeagueTier": {"id": 1, "name": "Lenda III"}}) == "Lenda III", "liga: qualquer chave c/ 'league'")
check(supercell_api._league({"legendStatistics": {"currentSeason": {"rank": 34}}}) == "Legend League", "liga: fallback legendStatistics")
check(supercell_api._league({"trophies": 100}) is None, "liga: ausente → None")
check(A.is_default_name("Vila #2UVGCRCY0", "#2UVGCRCY0"), "nome automático detectado")
check(A.is_default_name("Nova vila", None), "'Nova vila' é automático")
check(not A.is_default_name("Main TH18", "#X"), "nome custom preservado")
con2 = db.connect()
acc2 = db.create_account(con2, db.owner_id(con2), "Vila #ZZZ", tag="#ZZZ")
adopted = A.maybe_adopt_player_name(con2, acc2, {"name": "EL.BR_NbsK"})
check(adopted["name"] == "EL.BR_NbsK", "sync adota nome real do jogador")
cols = {r["name"] for r in con2.execute("PRAGMA table_info(accounts)")}
check("verified" in cols and "verified_at" in cols, "migração: colunas de verificação")
db.set_verified(con2, acc2["user_id"], acc2["id"], True)
check(db.get_account(con2, acc2["user_id"], acc2["id"])["verified"] == 1, "set_verified persiste")
con2.close()
r = c.post(f"/api/accounts/{aid}/verify", json={"token": "abc"})
check(r.status_code == 400 and "token" in r.json["error"].lower(), "verify sem dev-token → erro amigável")
compact2 = supercell_api._compact({"tag": "#X", "name": "N", "rankedLeague": {"name": "Lenda II"}, "trophies": 786})
check(compact2["league"] == "Lenda II" and compact2["_raw"]["trophies"] == 786, "compact: liga nova + raw preservado")

print("[7] parser: campos novos do export (extra, helper_recurrent)")
mini = {"tag": "#T", "timestamp": 1, "buildings": [
    {"data": 1000002, "lvl": 17, "timer": 100, "extra": True, "supercharge": 2},
    {"data": 1000001, "lvl": 18}],
    "units": [{"data": 4000006, "lvl": 13, "timer": 50, "extra": True, "helper_recurrent": True}]}
sn = parser.parse(json.dumps(mini))
check(sn["counts"]["total"] == 3 and sn["th_level"] == 18, "parse com 'extra'/'helper_recurrent' ok")
mm = metrics.compute(sn)
check(len(mm["active_upgrades"]) == 2, "timers com flags novas viram upgrades ativos")

print(f"\n{ok} verificações passaram ✔")
