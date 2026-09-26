"""
Métricas por snapshot: progresso por categoria, upgrades pendentes,
custos restantes, timers ativos e ETAs (construtores / laboratório / pet house).
"""
import time
from collections import defaultdict
from . import gamedata

# categorias da vila principal e rótulos pt-BR
CATEGORY_LABELS = {
    "townhall": "Centro de Vila",
    "defense": "Defesas",
    "trap": "Armadilhas",
    "wall": "Muros",
    "resource": "Recursos",
    "army": "Constr. militares",
    "hero": "Heróis",
    "troop": "Tropas (lab)",
    "spell": "Feitiços (lab)",
    "siege": "Máq. de cerco",
    "pet": "Pets",
    "equipment": "Equipamentos",
    "guardian": "Guardiões",
    "other": "Outros",
}
# fila de quem executa o upgrade
BUILDER_QUEUE = {"townhall", "defense", "trap", "wall", "resource", "army", "other", "hero"}
LAB_QUEUE = {"troop", "spell", "siege"}
PET_QUEUE = {"pet"}

BOB_HUT_NAMES = {"bobs-hut"}

# prédios mesclados (TH16+): mesclado -> (dataId base, unidades consumidas por mesclagem)
MERGE_CREDITS = {
    1000085: (1000008, 2),  # Ricochet Cannon    <- 2x Cannon
    1000084: (1000009, 2),  # Multi-Archer Tower <- 2x Archer Tower
    1000102: (1000011, 2),  # Super Wizard Tower <- 2x Wizard Tower
}


def _fmt_breakdown(level_counts, to_lvl):
    parts = [f"{n}x Lv {lv}" for lv, n in sorted(level_counts.items())]
    return f"{', '.join(parts)} → Lv {to_lvl}"


def compute(snapshot, now_ts=None):
    now_ts = now_ts or int(time.time())
    ts = snapshot.get("timestamp") or now_ts
    th = snapshot.get("th_level") or 1

    cats = defaultdict(lambda: {
        "cur_sum": 0, "max_sum": 0, "items": 0, "maxed_items": 0,
        "pending_levels": 0, "cost": defaultdict(int), "secs": 0, "partial": 0,
        "supercharged": 0,
    })
    pending_by_entity = defaultdict(lambda: {
        "items": 0, "levels": defaultdict(int), "to_lvl": 0,
        "cost": defaultdict(int), "secs": 0, "category": None, "name": None, "partial": 0,
        "ores": defaultdict(int),
    })
    ores_needed = {"shiny": 0, "glowing": 0, "starry": 0}
    active = []
    owned_count = defaultdict(int)
    builders_total = 0
    unknown_seen = 0
    clamped = defaultdict(int)

    for it in snapshot["items"]:
        if it.get("ignored"):
            continue
        if not it.get("known"):
            unknown_seen += 1
            continue
        ent = gamedata.entity(it["data"])
        cat = ent["category"]
        if cat.startswith("bb-"):
            continue  # builder base fora das métricas da vila principal (v1)
        cnt = it.get("cnt") or 1
        owned_count[it["data"]] += cnt
        lvl = it.get("lvl")
        if not isinstance(lvl, int):
            continue

        if ent["id"] == "builders-hut":
            builders_total += cnt
        if ent["id"] in BOB_HUT_NAMES:
            builders_total += cnt

        if cat == "townhall":
            mx = lvl  # progresso é relativo ao TH atual; próximo CV vira card separado
        else:
            mx_th = gamedata.max_level_at_th(ent, th)
            mx = mx_th if mx_th is not None else gamedata.max_level(ent)
            abs_mx = gamedata.max_level(ent)
            if abs_mx is not None and lvl > abs_mx:
                clamped[ent["name"]] += cnt
            mx = max(mx or lvl, lvl)  # nunca menor que o nível atual

        # upgrade em andamento
        timer = it.get("timer")
        upgrading = isinstance(timer, (int, float)) and timer > 0
        if upgrading:
            finish = ts + int(timer)
            active.append({
                "data": it["data"], "name": ent["name"], "category": cat,
                "from_lvl": lvl, "to_lvl": lvl + 1,
                "finish_ts": finish, "secs_left": max(0, finish - now_ts),
                "queue": ("lab" if cat in LAB_QUEUE else "pet" if cat in PET_QUEUE else "builder"),
            })

        c = cats[cat]
        c["items"] += cnt
        if it.get("supercharge"):
            c["supercharged"] += cnt
        c["cur_sum"] += lvl * cnt
        c["max_sum"] += mx * cnt
        if lvl >= mx:
            c["maxed_items"] += cnt

        start_from = lvl + 1 if upgrading else lvl
        pend = gamedata.levels_between(ent, start_from, mx)
        if pend:
            pe = pending_by_entity[it["data"]]
            pe["name"], pe["category"] = ent["name"], cat
            pe["items"] += cnt
            pe["levels"][start_from] += cnt
            pe["to_lvl"] = max(pe["to_lvl"], mx)
            for lv in pend:
                c["pending_levels"] += cnt
                if cat == "equipment":
                    for k, v in lv["cost"].items():
                        ores_needed[k] += v * cnt
                        pe["ores"][k] += v * cnt
                else:
                    if isinstance(lv["cost"], (int, float)) and lv["cost"] > 0:
                        c["cost"][lv["res"]] += lv["cost"] * cnt
                        pe["cost"][lv["res"]] += lv["cost"] * cnt
                    elif lv["secs"] == 0 and cat != "wall":
                        c["partial"] += 1
                        pe["partial"] += 1
                    c["secs"] += lv["secs"] * cnt
                    pe["secs"] += lv["secs"] * cnt

    if builders_total == 0:
        builders_total = 5  # padrão sensato quando o export não traz as cabanas

    # construções ainda não construídas neste TH (perTH) — estimativa c/ crédito de mesclagem
    merged_credit = defaultdict(int)
    for merged_id, (base_id, per) in MERGE_CREDITS.items():
        merged_credit[base_id] += owned_count.get(merged_id, 0) * per
    missing = []
    for did, ent in gamedata.load()["entities"].items():
        if ent["category"].startswith("bb-") or "perTH" not in ent:
            continue
        expected = ent["perTH"].get(str(th))
        if not expected:
            continue
        have = owned_count.get(int(did), 0) + merged_credit.get(int(did), 0)
        if have < expected:
            missing.append({"data": int(did), "name": ent["name"],
                            "category": ent["category"], "missing": expected - have})

    # agregados de fila
    builder_secs = sum(cats[c]["secs"] for c in cats if c in BUILDER_QUEUE)
    lab_secs = sum(cats[c]["secs"] for c in cats if c in LAB_QUEUE)
    pet_secs = sum(cats[c]["secs"] for c in cats if c in PET_QUEUE)
    builder_eta = builder_secs / builders_total if builders_total else builder_secs

    cur_total = sum(c["cur_sum"] for c in cats.values())
    max_total = sum(c["max_sum"] for c in cats.values())

    cost_total = defaultdict(int)
    for c in cats.values():
        for res, v in c["cost"].items():
            cost_total[res] += v

    categories = {}
    for cat, c in cats.items():
        categories[cat] = {
            "label": CATEGORY_LABELS.get(cat, cat),
            "progress": round(100 * c["cur_sum"] / c["max_sum"], 1) if c["max_sum"] else 100.0,
            "items": c["items"], "maxed_items": c["maxed_items"],
            "pending_levels": c["pending_levels"],
            "cost": dict(c["cost"]), "secs": c["secs"], "partial": c["partial"],
            "supercharged": c["supercharged"],
        }

    top_pending = []
    for did, pe in pending_by_entity.items():
        top_pending.append({
            "data": did, "name": pe["name"], "category": pe["category"],
            "items": pe["items"],
            "breakdown": _fmt_breakdown(pe["levels"], pe["to_lvl"]),
            "cost": dict(pe["cost"]), "secs": pe["secs"], "partial": pe["partial"],
            "ores": dict(pe["ores"]),
        })
    top_pending.sort(key=lambda x: (-x["secs"], -sum(x["cost"].values())))

    # próximo Centro de Vila (informativo, fora do % de progresso)
    next_th = None
    th_ent = gamedata.entity(1000001)
    if th_ent:
        nxt = gamedata.levels_between(th_ent, th, th + 1)
        if nxt:
            lv = nxt[0]
            next_th = {"to_lvl": lv["lvl"], "cost": lv["cost"], "res": lv["res"], "secs": lv["secs"]}

    active.sort(key=lambda a: a["finish_ts"])
    busy_builders = sum(1 for a in active if a["queue"] == "builder")

    return {
        "th_level": th,
        "timestamp": ts,
        "computed_at": now_ts,
        "level_offset": snapshot.get("level_offset", 0),
        "progress_total": round(100 * cur_total / max_total, 1) if max_total else 0.0,
        "categories": categories,
        "top_pending": top_pending[:80],
        "active_upgrades": active,
        "builders": {
            "total": builders_total,
            "busy": busy_builders,
            "available": max(0, builders_total - busy_builders),
            "next_free_ts": min((a["finish_ts"] for a in active if a["queue"] == "builder"), default=None),
        },
        "lab_busy": any(a["queue"] == "lab" for a in active),
        "eta": {
            "builder_secs": int(builder_eta),
            "lab_secs": int(lab_secs),
            "pet_secs": int(pet_secs),
            "critical_secs": int(max(builder_eta, lab_secs, pet_secs)),
        },
        "next_th": next_th,
        "cost_left": dict(cost_total),
        "ores_needed": ores_needed,
        "missing_buildings": missing,
        "pending_total": sum(c["pending_levels"] for c in cats.values()),
        "data_warnings": {
            "clamped_items": sum(clamped.values()),
            "clamped_names": sorted(clamped.keys())[:12],
        },
        "unknown_items": snapshot["counts"]["unknown"],
        "unknown_ids": snapshot.get("unknown_ids", []),
    }
