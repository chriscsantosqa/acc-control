"""Métricas por snapshot para Vila Principal e Base do Construtor."""
import time
from collections import defaultdict
from . import gamedata

CATEGORY_LABELS = {
    "townhall":"Centro de Vila","defense":"Defesas","trap":"Armadilhas","wall":"Muros","resource":"Recursos","army":"Construções militares","hero":"Heróis","troop":"Tropas (lab)","spell":"Feitiços (lab)","siege":"Máquinas de cerco","pet":"Pets","equipment":"Equipamentos","guardian":"Guardiões","other":"Outros",
    "bb-builder-hall":"Centro do Construtor","bb-defense":"Defesas","bb-trap":"Armadilhas","bb-wall":"Muros","bb-resource":"Recursos","bb-army":"Construções militares","bb-hero":"Heróis","bb-troop":"Tropas (Laboratório Estelar)","bb-other":"Outros",
}
BUILDER_QUEUE={"townhall","defense","trap","wall","resource","army","other","hero"}
LAB_QUEUE={"troop","spell","siege"}
PET_QUEUE={"pet"}
BB_BUILDER_QUEUE={"bb-builder-hall","bb-defense","bb-trap","bb-resource","bb-army","bb-other","bb-hero"}
BB_LAB_QUEUE={"bb-troop"}
HELPER_IDS={"builders-apprentice","lab-assistant","prospector"}
BOB_HUT_NAMES={"bobs-hut"}
MERGE_CREDITS={1000085:(1000008,2),1000084:(1000009,2),1000102:(1000011,2)}

def _fmt_breakdown(level_counts,to_lvl):
    return f"{', '.join(f'{n}x Lv {lv}' for lv,n in sorted(level_counts.items()))} → Lv {to_lvl}"

def _queue(ent,base):
    if ent["id"] in HELPER_IDS:return None
    cat=ent["category"]
    if base=="builder":
        return "lab" if cat in BB_LAB_QUEUE else "builder" if cat in BB_BUILDER_QUEUE else None
    return "lab" if cat in LAB_QUEUE else "pet" if cat in PET_QUEUE else "builder" if cat in BUILDER_QUEUE else None

def _hall(snapshot,base):
    target=1000001 if base=="home" else 1000034
    for it in snapshot.get("items",[]):
        if it.get("data")==target and isinstance(it.get("lvl"),int):return it["lvl"]
    return snapshot.get("th_level") or 1 if base=="home" else 1

def _inventory(snapshot):
    out=[]
    for it in snapshot.get("items",[]):
        if it.get("ignored") or not it.get("known"):continue
        ent=gamedata.entity(it["data"])
        if not ent:continue
        out.append({"data":it["data"],"id":ent["id"],"name":ent["name"],"category":ent["category"],"base":ent.get("base","home"),"lvl":it.get("lvl"),"cnt":it.get("cnt") or 1,"timer":it.get("timer"),"helper":ent["id"] in HELPER_IDS})
    return out

def _compute_base(snapshot,base,now_ts):
    ts=snapshot.get("timestamp") or now_ts; hall=_hall(snapshot,base)
    cats=defaultdict(lambda:{"cur_sum":0,"max_sum":0,"items":0,"maxed_items":0,"pending_levels":0,"cost":defaultdict(int),"secs":0,"partial":0,"supercharged":0})
    pendings=defaultdict(lambda:{"items":0,"levels":defaultdict(int),"to_lvl":0,"cost":defaultdict(int),"secs":0,"category":None,"name":None,"partial":0,"ores":defaultdict(int)})
    ores={"shiny":0,"glowing":0,"starry":0};active=[];owned=defaultdict(int);builders_total=0;clamped=defaultdict(int)
    for it in snapshot.get("items",[]):
        if it.get("ignored") or not it.get("known"):continue
        ent=gamedata.entity(it["data"])
        if not ent or ent.get("base","home")!=base:continue
        cat=ent["category"];cnt=it.get("cnt") or 1;owned[it["data"]]+=cnt;lvl=it.get("lvl")
        if not isinstance(lvl,int):continue
        if base=="home" and ent["id"]=="builders-hut":builders_total+=cnt
        if base=="home" and ent["id"] in BOB_HUT_NAMES:builders_total+=cnt
        if (base=="home" and cat=="townhall") or (base=="builder" and cat=="bb-builder-hall"):mx=lvl
        elif base=="home":
            mx_th=gamedata.max_level_at_th(ent,hall);mx=mx_th if mx_th is not None else gamedata.max_level(ent);abs_mx=gamedata.max_level(ent)
            if abs_mx is not None and lvl>abs_mx:clamped[ent["name"]]+=cnt
            mx=max(mx or lvl,lvl)
        else:
            abs_mx=gamedata.max_level(ent)
            if abs_mx is not None and lvl>abs_mx:clamped[ent["name"]]+=cnt
            mx=max(abs_mx or lvl,lvl)
        timer=it.get("timer");upgrading=isinstance(timer,(int,float)) and timer>0;queue=_queue(ent,base)
        if upgrading and queue:
            finish=ts+int(timer);active.append({"data":it["data"],"name":ent["name"],"category":cat,"base":base,"from_lvl":lvl,"to_lvl":lvl+1,"finish_ts":finish,"secs_left":max(0,finish-now_ts),"queue":queue})
        c=cats[cat];c["items"]+=cnt;c["cur_sum"]+=lvl*cnt;c["max_sum"]+=mx*cnt
        if it.get("supercharge"):c["supercharged"]+=cnt
        if lvl>=mx:c["maxed_items"]+=cnt
        start=lvl+1 if upgrading else lvl;levels=gamedata.levels_between(ent,start,mx)
        if not levels:continue
        pe=pendings[it["data"]];pe["name"]=ent["name"];pe["category"]=cat;pe["items"]+=cnt;pe["levels"][start]+=cnt;pe["to_lvl"]=max(pe["to_lvl"],mx)
        for lv in levels:
            c["pending_levels"]+=cnt
            if cat=="equipment":
                for k,v in lv["cost"].items():ores[k]+=v*cnt;pe["ores"][k]+=v*cnt
                continue
            if isinstance(lv["cost"],(int,float)) and lv["cost"]>0 and lv["res"]:
                c["cost"][lv["res"]]+=lv["cost"]*cnt;pe["cost"][lv["res"]]+=lv["cost"]*cnt
            elif lv["secs"]==0 and cat not in {"wall","bb-wall"} and ent["id"] not in HELPER_IDS:c["partial"]+=1;pe["partial"]+=1
            c["secs"]+=lv["secs"]*cnt;pe["secs"]+=lv["secs"]*cnt
    active.sort(key=lambda x:x["finish_ts"]);busy=sum(1 for x in active if x["queue"]=="builder")
    if base=="home":builders_total=builders_total or 5;estimated=False
    else:builders_total=max(2 if hall>=6 else 1,busy,1);estimated=True
    missing=[]
    if base=="home":
        credit=defaultdict(int)
        for merged,(base_id,per) in MERGE_CREDITS.items():credit[base_id]+=owned.get(merged,0)*per
        for did,ent in gamedata.load()["entities"].items():
            if ent.get("base","home")!="home" or "perTH" not in ent:continue
            expected=ent["perTH"].get(str(hall))
            if expected:
                have=owned.get(int(did),0)+credit.get(int(did),0)
                if have<expected:missing.append({"data":int(did),"name":ent["name"],"category":ent["category"],"base":"home","missing":expected-have})
    bq=BUILDER_QUEUE if base=="home" else BB_BUILDER_QUEUE;lq=LAB_QUEUE if base=="home" else BB_LAB_QUEUE;pq=PET_QUEUE if base=="home" else set()
    bsecs=sum(cats[c]["secs"] for c in cats if c in bq);lsecs=sum(cats[c]["secs"] for c in cats if c in lq);psecs=sum(cats[c]["secs"] for c in cats if c in pq);beta=bsecs/builders_total if builders_total else bsecs
    cur=sum(c["cur_sum"] for c in cats.values());mxsum=sum(c["max_sum"] for c in cats.values());cost=defaultdict(int)
    for c in cats.values():
        for res,v in c["cost"].items():
            if res:cost[res]+=v
    categories={cat:{"label":CATEGORY_LABELS.get(cat,cat),"progress":round(100*c["cur_sum"]/c["max_sum"],1) if c["max_sum"] else 100.0,"items":c["items"],"maxed_items":c["maxed_items"],"pending_levels":c["pending_levels"],"cost":dict(c["cost"]),"secs":c["secs"],"partial":c["partial"],"supercharged":c["supercharged"]} for cat,c in cats.items()}
    top=[]
    for did,pe in pendings.items():top.append({"data":did,"name":pe["name"],"category":pe["category"],"base":base,"items":pe["items"],"breakdown":_fmt_breakdown(pe["levels"],pe["to_lvl"]),"cost":dict(pe["cost"]),"secs":pe["secs"],"partial":pe["partial"],"ores":dict(pe["ores"])})
    top.sort(key=lambda x:(-x["secs"],-sum(x["cost"].values())))
    hall_ent=gamedata.entity(1000001 if base=="home" else 1000034);next_hall=None
    if hall_ent:
        nxt=gamedata.levels_between(hall_ent,hall,hall+1)
        if nxt:
            lv=nxt[0];next_hall={"to_lvl":lv["lvl"],"cost":lv["cost"],"res":lv["res"],"secs":lv["secs"]}
    return {"base":base,"hall_level":hall,"th_level":hall if base=="home" else None,"builder_hall_level":hall if base=="builder" else None,"timestamp":ts,"computed_at":now_ts,"progress_total":round(100*cur/mxsum,1) if mxsum else 0.0,"categories":categories,"top_pending":top[:80],"active_upgrades":active,"builders":{"total":builders_total,"busy":busy,"available":max(0,builders_total-busy),"estimated":estimated,"next_free_ts":min((x["finish_ts"] for x in active if x["queue"]=="builder"),default=None)},"lab_busy":any(x["queue"]=="lab" for x in active),"eta":{"builder_secs":int(beta),"lab_secs":int(lsecs),"pet_secs":int(psecs),"critical_secs":int(max(beta,lsecs,psecs))},"next_hall":next_hall,"next_th":next_hall if base=="home" else None,"cost_left":dict(cost),"ores_needed":ores if base=="home" else {},"missing_buildings":missing,"pending_total":sum(c["pending_levels"] for c in cats.values()),"data_warnings":{"clamped_items":sum(clamped.values()),"clamped_names":sorted(clamped.keys())[:12]}}

def compute(snapshot,now_ts=None):
    now_ts=now_ts or int(time.time());home=_compute_base(snapshot,"home",now_ts);builder=_compute_base(snapshot,"builder",now_ts)
    result=dict(home);result["level_offset"]=snapshot.get("level_offset",0);result["inventory"]=_inventory(snapshot);result["builder_base"]=builder;result["unknown_items"]=snapshot.get("counts",{}).get("unknown",0);result["unknown_ids"]=snapshot.get("unknown_ids",[])
    return result
