#!/usr/bin/env python3
"""
Gera data/game_data.json a partir do pacote npm `clash-of-clans-data` (MIT).

Uso:
    npm pack clash-of-clans-data@latest && tar -xzf clash-of-clans-data-*.tgz
    python tools/build_game_data.py --src ./package/data --out data/game_data.json

Rode novamente quando a Supercell lancar update de balanceamento/novo TH.
"""
import argparse, glob, json, os
from datetime import datetime, timezone

CATEGORY_MAP = {
    "defenses": "defense", "crafted-defenses": "defense", "traps": "trap",
    "walls": "wall", "resource-buildings": "resource", "army-buildings": "army",
    "town-hall": "townhall", "heroes": "hero", "troops": "troop",
    "spells": "spell", "siege-machines": "siege", "pets": "pet",
    "hero-equipment": "equipment", "guardians": "guardian", "other": "other",
}

def time_to_secs(t):
    if not isinstance(t, dict): return 0
    return t.get("days",0)*86400 + t.get("hours",0)*3600 + t.get("minutes",0)*60 + t.get("seconds",0)

def norm_level(lv, category):
    out = {"lvl": lv.get("level")}
    if category == "equipment":
        out["cost"] = {"shiny": lv.get("upgradeShinyOre",0), "glowing": lv.get("upgradeGlowingOre",0), "starry": lv.get("upgradeStarryOre",0)}
        out["res"] = "Ore"; out["secs"] = 0
        out["req"] = {"blacksmith": lv.get("blacksmithLevelRequired")}
        return out
    cost = lv.get("buildCost", lv.get("researchCost", lv.get("upgradeCost")))
    res = lv.get("buildCostResource", lv.get("researchCostResource", lv.get("upgradeCostResource")))
    secs = time_to_secs(lv.get("buildTime", lv.get("researchTime", lv.get("upgradeTime"))))
    out["cost"] = cost if cost is not None else 0
    out["res"] = res or ""
    out["secs"] = secs
    if lv.get("townHallRequired") is not None: out["th"] = lv["townHallRequired"]
    req = {}
    for k, tag in (("laboratoryRequired","lab"),("heroHallLevelRequired","heroHall"),
                   ("petHouseLevelRequired","petHouse"),("workshopLevelRequired","workshop"),
                   ("spellFactoryLevelRequired","spellFactory")):
        if lv.get(k) is not None: req[tag] = lv[k]
    if req: out["req"] = req
    return out

def building_th_by_level(entity):
    return {lv.get("level"): lv.get("townHallRequired")
            for lv in entity.get("levels", []) if lv.get("townHallRequired") is not None}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    entities, aux = {}, {}
    for base in ("home", "builder"):
        basedir = os.path.join(args.src, base)
        if not os.path.isdir(basedir): continue
        for path in sorted(glob.glob(os.path.join(basedir, "**", "*.json"), recursive=True)):
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                continue
            folder = os.path.relpath(path, basedir).split(os.sep)[0]
            category = CATEGORY_MAP.get(folder, folder)
            if base == "builder": category = "bb-" + category
            data_id = raw.get("dataId")
            levels = raw.get("levels") or []
            if raw.get("id"): aux[f"{base}:{raw['id']}"] = raw
            if data_id is None or not levels: continue
            ent = {
                "id": raw.get("id"), "name": raw.get("name"), "base": base,
                "category": category,
                "levels": [norm_level(lv, category.replace("bb-","")) for lv in levels],
            }
            if raw.get("availablePerTownHall"):
                ent["perTH"] = {str(x["townHallLevel"]): x["count"] for x in raw["availablePerTownHall"]}
            entities[str(data_id)] = ent

    hh_th = building_th_by_level(aux.get("home:hero-hall", {}))
    ph_th = building_th_by_level(aux.get("home:pet-house", {}))
    def min_th_for(req_level, table):
        ths = [th for lvl, th in table.items() if lvl >= (req_level or 0)]
        return min(ths) if ths else None

    for ent in entities.values():
        if ent["category"] == "hero":
            for lv in ent["levels"]:
                th = min_th_for((lv.get("req") or {}).get("heroHall"), hh_th)
                if th and "th" not in lv: lv["th"] = th
        elif ent["category"] == "pet":
            for lv in ent["levels"]:
                if "th" in lv: continue
                th = min_th_for((lv.get("req") or {}).get("petHouse"), ph_th)
                if th: lv["th"] = th

    th_meta = {}
    th_ent = aux.get("home:town-hall")
    if th_ent:
        for lv in th_ent.get("levels", []):
            th_meta[str(lv["level"])] = {"maxBuildings": lv.get("maxBuildings"), "maxTraps": lv.get("maxTraps")}

    version = None
    pkg_json = os.path.join(os.path.dirname(args.src), "package.json")
    if os.path.exists(pkg_json):
        try:
            version = json.load(open(pkg_json)).get("version")
        except Exception:
            pass
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_version": version,
        "source": "clash-of-clans-data (npm, MIT) - dados do Clash of Clans Wiki",
        "entity_count": len(entities),
        "town_hall_meta": th_meta,
        "entities": entities,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",",":"))
    print(f"OK: {len(entities)} entidades -> {args.out}")
    cats = {}
    for e in entities.values(): cats[e["category"]] = cats.get(e["category"],0)+1
    print(json.dumps(cats, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
