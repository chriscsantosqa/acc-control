"""Planejador separado para Vila Principal e Base do Construtor."""
import heapq
import time
from . import gamedata
from .metrics import (
    BUILDER_QUEUE, LAB_QUEUE, PET_QUEUE,
    BB_BUILDER_QUEUE, BB_LAB_QUEUE, HELPER_IDS,
)

STRATEGIES={
    "defense":{"rank":{"defense":0,"trap":1,"hero":2,"army":3,"resource":4,"other":5,"bb-defense":0,"bb-trap":1,"bb-hero":2,"bb-army":3,"bb-resource":4,"bb-other":5},"label":"Defesa primeiro","tiebreak":"fast"},
    "farm":{"rank":{"resource":0,"army":1,"hero":2,"defense":3,"trap":4,"other":5,"bb-resource":0,"bb-army":1,"bb-hero":2,"bb-defense":3,"bb-trap":4,"bb-other":5},"label":"Farm primeiro","tiebreak":"fast"},
    "fast":{"rank":{},"label":"Mais rápidos primeiro","tiebreak":"fast"},
    "cheap":{"rank":{},"label":"Mais baratos primeiro","tiebreak":"cheap"},
    "balanced":{"rank":{"hero":0,"defense":1,"resource":1,"army":2,"trap":2,"other":3,"bb-hero":0,"bb-defense":1,"bb-resource":1,"bb-army":2,"bb-trap":2,"bb-other":3},"label":"Balanceado","tiebreak":"fast"},
}

def _hall(snapshot,base):
    target=1000001 if base=="home" else 1000034
    for it in snapshot.get("items",[]):
        if it.get("data")==target and isinstance(it.get("lvl"),int):return it["lvl"]
    return snapshot.get("th_level") or 1

def _queue(cat,base):
    if base=="builder":return "lab" if cat in BB_LAB_QUEUE else "builder" if cat in BB_BUILDER_QUEUE else None
    return "lab" if cat in LAB_QUEUE else "pet" if cat in PET_QUEUE else "builder" if cat in BUILDER_QUEUE else None

def _chains(snapshot,base):
    hall=_hall(snapshot,base);chains={"builder":[],"lab":[],"pet":[]};inst=0
    for it in snapshot.get("items",[]):
        if it.get("ignored") or not it.get("known") or not isinstance(it.get("lvl"),int):continue
        ent=gamedata.entity(it["data"])
        if not ent or ent.get("base","home")!=base or ent["id"] in HELPER_IDS:continue
        cat=ent["category"]
        if cat in {"equipment","townhall","wall","guardian","bb-builder-hall","bb-wall"}:continue
        queue=_queue(cat,base)
        if not queue:continue
        if base=="home":
            mx_th=gamedata.max_level_at_th(ent,hall);mx=mx_th if mx_th is not None else (gamedata.max_level(ent) or it["lvl"])
        else:mx=gamedata.max_level(ent) or it["lvl"]
        mx=max(mx,it["lvl"]);upgrading=isinstance(it.get("timer"),(int,float)) and it["timer"]>0;start=it["lvl"]+1 if upgrading else it["lvl"];levels=gamedata.levels_between(ent,start,mx)
        if not levels:continue
        for _ in range(it.get("cnt") or 1):
            inst+=1;chains[queue].append({"inst":inst,"data":it["data"],"name":ent["name"],"category":cat,"base":base,"levels":[{"lvl":lv["lvl"],"secs":lv["secs"],"cost":lv["cost"] if isinstance(lv["cost"],(int,float)) else 0,"res":lv["res"]} for lv in levels]})
    return chains

def _score(strategy,chain):
    st=STRATEGIES[strategy];nxt=chain["levels"][0];rank=st["rank"].get(chain["category"],50);tie=nxt["secs"] if st["tiebreak"]=="fast" else nxt["cost"]
    return rank,tie,nxt["cost"]

def _simulate(chains,workers,strategy,now,limit):
    if not workers:workers=[now]
    schedule=[];heap=[(max(now,t),i) for i,t in enumerate(workers)];heapq.heapify(heap);pending=[c for c in chains if c["levels"]]
    while pending and len(schedule)<limit:
        free_at,worker=heapq.heappop(heap);pending.sort(key=lambda c:_score(strategy,c));chain=pending[0];lv=chain["levels"].pop(0);start,end=free_at,free_at+lv["secs"]
        schedule.append({"worker":worker+1,"name":chain["name"],"category":chain["category"],"base":chain["base"],"to_lvl":lv["lvl"],"start":int(start),"end":int(end),"secs":lv["secs"],"cost":lv["cost"],"res":lv["res"]})
        if not chain["levels"]:pending.remove(chain)
        heapq.heappush(heap,(end,worker))
    return schedule,max((s["end"] for s in schedule),default=now),sum(len(c["levels"]) for c in pending)

def _plan_base(snapshot,summary,strategy,base,limit,now):
    chains=_chains(snapshot,base);b=summary.get("builders") or {"total":1};active=summary.get("active_upgrades") or []
    busy=sorted(a["finish_ts"] for a in active if a["queue"]=="builder")[:b["total"]];workers=busy+[now]*max(0,b["total"]-len(busy));lab_busy=[a["finish_ts"] for a in active if a["queue"]=="lab"];pet_busy=[a["finish_ts"] for a in active if a["queue"]=="pet"]
    bs,bd,bl=_simulate(chains["builder"],workers,strategy,now,limit);ls,ld,ll=_simulate(chains["lab"],[max(lab_busy) if lab_busy else now],strategy,now,limit);ps,pd,pl=_simulate(chains["pet"],[max(pet_busy) if pet_busy else now],strategy,now,limit)
    suggestions=[];seen=set()
    for s in bs:
        if s["worker"] in seen:continue
        seen.add(s["worker"]);suggestions.append({**s,"when":"agora" if s["start"]<=now+60 else None})
        if len(suggestions)>=b["total"]:break
    return {"base":base,"builders":{"schedule":bs,"done_at":bd,"not_scheduled":bl},"lab":{"schedule":ls,"done_at":ld,"not_scheduled":ll},"pets":{"schedule":ps,"done_at":pd,"not_scheduled":pl},"suggestions":suggestions,"next_lab":ls[0] if ls else None,"projected_all_done":max(bd,ld,pd)}

def plan(snapshot,summary,strategy="balanced",limit=150,now_ts=None):
    now=now_ts or int(time.time());strategy=strategy if strategy in STRATEGIES else "balanced";home=_plan_base(snapshot,summary,strategy,"home",limit,now);builder=_plan_base(snapshot,summary.get("builder_base") or {},strategy,"builder",limit,now)
    return {"strategy":strategy,"strategies":{k:v["label"] for k,v in STRATEGIES.items()},**home,"builder_base":builder,"note":"Simulação aproximada e separada por base. Helpers, muros, boosts e disponibilidade futura de recursos não ocupam a fila simulada."}
