"""
Planner: simula as filas de upgrade (construtores, laboratório, pets) e sugere
os próximos upgrades conforme a estratégia escolhida.

Simulação gulosa e aproximada: cada item só sobe um nível por vez (cadeia),
construtores pegam sempre o melhor upgrade disponível quando liberam.
Muros ficam fora do cronograma (tempo 0 — são só custo).
"""
import heapq
import time
from collections import defaultdict
from . import gamedata
from .metrics import BUILDER_QUEUE, LAB_QUEUE, PET_QUEUE, CATEGORY_LABELS

STRATEGIES = {
    # menor rank = maior prioridade de categoria
    "defense":  {"rank": {"defense": 0, "trap": 1, "hero": 2, "army": 3, "resource": 4, "other": 5},
                 "label": "Defesa primeiro", "tiebreak": "fast"},
    "farm":     {"rank": {"resource": 0, "army": 1, "hero": 2, "defense": 3, "trap": 4, "other": 5},
                 "label": "Farm primeiro", "tiebreak": "fast"},
    "fast":     {"rank": {}, "label": "Mais rápidos primeiro", "tiebreak": "fast"},
    "cheap":    {"rank": {}, "label": "Mais baratos primeiro", "tiebreak": "cheap"},
    "balanced": {"rank": {"hero": 0, "defense": 1, "resource": 1, "army": 2, "trap": 2, "other": 3},
                 "label": "Balanceado", "tiebreak": "fast"},
}


def _chains(snapshot, th):
    """Expande itens pendentes em cadeias de níveis sequenciais por instância."""
    chains = {"builder": [], "lab": [], "pet": []}
    inst = 0
    for it in snapshot["items"]:
        if it.get("ignored") or not it.get("known") or not isinstance(it.get("lvl"), int):
            continue
        ent = gamedata.entity(it["data"])
        cat = ent["category"]
        if cat.startswith("bb-") or cat in ("equipment", "townhall", "wall", "guardian"):
            continue
        queue = "lab" if cat in LAB_QUEUE else "pet" if cat in PET_QUEUE else \
                "builder" if cat in BUILDER_QUEUE else None
        if not queue:
            continue
        mx_th = gamedata.max_level_at_th(ent, th)
        mx = mx_th if mx_th is not None else (gamedata.max_level(ent) or it["lvl"])
        mx = max(mx, it["lvl"])
        upgrading = isinstance(it.get("timer"), (int, float)) and it["timer"] > 0
        start_lvl = it["lvl"] + 1 if upgrading else it["lvl"]
        pend = gamedata.levels_between(ent, start_lvl, mx)
        if not pend:
            continue
        cnt = it.get("cnt") or 1
        for _ in range(cnt):
            inst += 1
            chains[queue].append({
                "inst": inst, "data": it["data"], "name": ent["name"], "category": cat,
                "levels": [{"lvl": lv["lvl"], "secs": lv["secs"],
                            "cost": lv["cost"] if isinstance(lv["cost"], (int, float)) else 0,
                            "res": lv["res"]} for lv in pend],
            })
    return chains


def _score(strategy, chain):
    st = STRATEGIES[strategy]
    nxt = chain["levels"][0]
    rank = st["rank"].get(chain["category"], 50)
    tie = nxt["secs"] if st["tiebreak"] == "fast" else nxt["cost"]
    return (rank, tie, nxt["cost"])


def _simulate(chains, workers_free, strategy, now, limit):
    """workers_free: lista de timestamps em que cada worker libera."""
    schedule = []
    heap = [(max(now, t), i) for i, t in enumerate(workers_free)]
    heapq.heapify(heap)
    pending = [c for c in chains if c["levels"]]
    while pending and len(schedule) < limit:
        free_at, worker = heapq.heappop(heap)
        pending.sort(key=lambda c: _score(strategy, c))
        chain = pending[0]
        lv = chain["levels"].pop(0)
        start, end = free_at, free_at + lv["secs"]
        schedule.append({
            "worker": worker + 1, "name": chain["name"], "category": chain["category"],
            "to_lvl": lv["lvl"], "start": int(start), "end": int(end),
            "secs": lv["secs"], "cost": lv["cost"], "res": lv["res"],
        })
        if not chain["levels"]:
            pending.remove(chain)
        heapq.heappush(heap, (end, worker))
    done_at = max((s["end"] for s in schedule), default=now)
    return schedule, done_at, sum(len(c["levels"]) for c in pending)


def plan(snapshot, summary, strategy="balanced", limit=150, now_ts=None):
    now = now_ts or int(time.time())
    if strategy not in STRATEGIES:
        strategy = "balanced"
    th = snapshot.get("th_level") or 1
    chains = _chains(snapshot, th)

    # construtores: livres agora + os que liberam quando o upgrade atual termina
    b = summary["builders"]
    busy_until = sorted(a["finish_ts"] for a in summary["active_upgrades"] if a["queue"] == "builder")
    busy_until = busy_until[:b["total"]]
    workers = busy_until + [now] * max(0, b["total"] - len(busy_until))

    lab_busy = [a["finish_ts"] for a in summary["active_upgrades"] if a["queue"] == "lab"]
    pet_busy = [a["finish_ts"] for a in summary["active_upgrades"] if a["queue"] == "pet"]

    b_sched, b_done, b_left = _simulate(chains["builder"], workers, strategy, now, limit)
    l_sched, l_done, l_left = _simulate(chains["lab"], [max(lab_busy) if lab_busy else now], strategy, now, limit)
    p_sched, p_done, p_left = _simulate(chains["pet"], [max(pet_busy) if pet_busy else now], strategy, now, limit)

    # sugestões: primeiro upgrade de cada construtor que está/ficará livre logo
    suggestions = []
    seen_workers = set()
    for s in b_sched:
        if s["worker"] in seen_workers:
            continue
        seen_workers.add(s["worker"])
        suggestions.append({**s, "when": "agora" if s["start"] <= now + 60 else None})
        if len(suggestions) >= b["total"]:
            break
    nxt_lab = l_sched[0] if l_sched else None

    return {
        "strategy": strategy,
        "strategies": {k: v["label"] for k, v in STRATEGIES.items()},
        "builders": {"schedule": b_sched, "done_at": b_done, "not_scheduled": b_left},
        "lab": {"schedule": l_sched, "done_at": l_done, "not_scheduled": l_left},
        "pets": {"schedule": p_sched, "done_at": p_done, "not_scheduled": p_left},
        "suggestions": suggestions,
        "next_lab": nxt_lab,
        "projected_all_done": max(b_done, l_done, p_done),
        "note": "Simulação aproximada: 1 nível por vez por item, sem custo de recursos/boosts. Muros fora (tempo 0).",
    }
