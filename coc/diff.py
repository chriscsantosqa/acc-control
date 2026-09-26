"""Diff entre dois snapshots: o que mudou, gasto estimado e velocidade real."""
from collections import defaultdict
from . import gamedata


def _level_counts(snapshot):
    """{data_id: {lvl: cnt}} e {data_id: set(níveis com timer)} (só itens de nível)."""
    levels = defaultdict(lambda: defaultdict(int))
    upgrading = defaultdict(set)
    for it in snapshot["items"]:
        if it.get("ignored") or not isinstance(it.get("lvl"), int):
            continue
        levels[it["data"]][it["lvl"]] += it.get("cnt") or 1
        if isinstance(it.get("timer"), (int, float)) and it["timer"] > 0:
            upgrading[it["data"]].add(it["lvl"])
    return levels, upgrading


def compute_diff(snap_from, snap_to):
    """Changelog entre dois snapshots parseados (from mais antigo)."""
    lv_a, up_a = _level_counts(snap_from)
    lv_b, up_b = _level_counts(snap_to)
    changes, spent = [], defaultdict(int)
    ids = set(lv_a) | set(lv_b)

    for did in ids:
        ent = gamedata.entity(did)
        name = ent["name"] if ent else f"id {did}"
        cat = ent["category"] if ent else "?"
        a, b = lv_a.get(did, {}), lv_b.get(did, {})
        tot_a, tot_b = sum(a.values()), sum(b.values())
        sum_a = sum(l * c for l, c in a.items())
        sum_b = sum(l * c for l, c in b.items())

        if tot_b > tot_a:
            changes.append({"kind": "built", "name": name, "category": cat,
                            "count": tot_b - tot_a,
                            "text": f"+{tot_b - tot_a} construído(s)"})
        # movimentos de nível: deltas por nível (negativos saíram, positivos chegaram)
        deltas = {l: b.get(l, 0) - a.get(l, 0) for l in set(a) | set(b)}
        ups = {l: d for l, d in deltas.items() if d > 0}
        if ups and sum_b > sum_a:
            moved = sum(ups.values()) if tot_a == tot_b else max(0, sum(ups.values()) - (tot_b - tot_a))
            desc = ", ".join(f"{d}x → lv {l}" for l, d in sorted(ups.items()))
            levels_gained = sum_b - sum_a - (tot_b - tot_a) * min(b.keys() or [1])
            if ent and ent.get("levels"):
                for l, d in ups.items():
                    lvdata = next((x for x in ent["levels"] if x["lvl"] == l), None)
                    if lvdata and isinstance(lvdata.get("cost"), (int, float)):
                        spent[lvdata.get("res") or "?"] += lvdata["cost"] * d
            if moved > 0:
                changes.append({"kind": "upgraded", "name": name, "category": cat,
                                "count": moved, "text": desc})
        # upgrades iniciados agora
        started = up_b.get(did, set()) - up_a.get(did, set())
        for l in sorted(started):
            changes.append({"kind": "started", "name": name, "category": cat,
                            "count": 1, "text": f"iniciou lv {l} → {l + 1}"})

    order = {"built": 0, "upgraded": 1, "started": 2}
    changes.sort(key=lambda c: (order.get(c["kind"], 9), -c["count"]))
    return {
        "from_ts": snap_from.get("timestamp"),
        "to_ts": snap_to.get("timestamp"),
        "days": round(((snap_to.get("timestamp") or 0) - (snap_from.get("timestamp") or 0)) / 86400, 2),
        "changes": changes[:120],
        "totals": {
            "upgraded_levels": sum(c["count"] for c in changes if c["kind"] == "upgraded"),
            "built": sum(c["count"] for c in changes if c["kind"] == "built"),
            "started": sum(c["count"] for c in changes if c["kind"] == "started"),
        },
        "spent_estimate": dict(spent),
    }


def velocity(series):
    """
    series: [{taken_at, progress}] em ordem cronológica.
    Retorna %/dia real + projeção realista até 100%.
    """
    pts = [(s["taken_at"], s["progress"]) for s in series if s.get("taken_at")]
    if len(pts) < 2:
        return None
    (t0, p0), (t1, p1) = pts[0], pts[-1]
    days = (t1 - t0) / 86400
    if days < 0.25:
        return None
    rate = (p1 - p0) / days
    out = {"pct_per_day": round(rate, 3), "window_days": round(days, 1),
           "snapshots": len(pts)}
    if rate > 0:
        rem_days = (100 - p1) / rate
        out["days_to_max"] = round(rem_days, 1)
        out["max_at_ts"] = int(t1 + rem_days * 86400)
    return out
