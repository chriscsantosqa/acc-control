#!/usr/bin/env python3
"""Gera um export sintético (TH16) p/ testes: sample_export.json"""
import json, random, sys, time
sys.path.insert(0, ".")
from coc import gamedata

random.seed(42)
G = gamedata.load()["entities"]
now = int(time.time())
out = {"tag": "#TESTVILA1", "timestamp": now, "buildings": [], "traps": [],
       "units": [], "spells": [], "heroes": [], "pets": [], "siege_machines": [],
       "equipment": [], "obstacles": [{"data": 8000000, "lvl": 0} for _ in range(5)]}
TH = 16

def lvl_for(ent):
    mx = gamedata.max_level_at_th(ent, TH) or gamedata.max_level(ent)
    lo = max(1, int(mx*0.6))
    return random.randint(lo, mx)

timers_left = 5
for did, ent in G.items():
    did = int(did)
    cat = ent["category"]
    if cat.startswith("bb-") or cat in ("equipment","guardian","other"):
        continue
    if cat == "townhall":
        out["buildings"].append({"data": did, "lvl": TH}); continue
    if cat == "wall":
        per = int(ent["perTH"][str(TH)])
        counts = {13: 54, 14: per-54-11-1, 15: 11, 16: 1}
        for lv, n in counts.items():
            out["buildings"].append({"data": did, "lvl": lv, "cnt": n})
        continue
    if cat in ("defense","resource","army"):
        per = ent.get("perTH", {}).get(str(TH))
        n = int(per) if per else random.choice([1,1,2])
        for i in range(n):
            item = {"data": did, "lvl": lvl_for(ent)}
            if timers_left and random.random() < 0.35:
                item["timer"] = random.randint(3600, 6*86400); timers_left -= 1
            out["buildings"].append(item)
        continue
    if cat == "trap":
        per = ent.get("perTH", {}).get(str(TH), 2)
        for i in range(int(per)):
            out["traps"].append({"data": did, "lvl": max(1, lvl_for(ent)-random.randint(0,4))})
        continue
    key = {"troop":"units","spell":"spells","hero":"heroes","pet":"pets","siege":"siege_machines"}[cat]
    first_th = next((l.get("th") for l in ent["levels"] if l.get("th")), 99)
    if first_th and first_th > TH:
        continue
    out[key].append({"data": did, "lvl": lvl_for(ent)})

# um herói subindo + ids desconhecidos p/ testar robustez
for h in out["heroes"]:
    h["lvl"] = min(h["lvl"], 90)
out["heroes"][0]["timer"] = 3*86400
out["buildings"].append({"data": 1099999, "lvl": 3})
out["units"].append({"data": 4099999, "lvl": 2})

json.dump(out, open("tests/sample_export_th16.json","w"))
print("itens:", sum(len(v) for v in out.values() if isinstance(v, list)))
