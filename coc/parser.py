"""
Parser do export de vila do Clash of Clans ("Exportação de dados" -> JSON).

Estratégia defensiva: percorre TODAS as chaves do JSON cujo valor é lista de
objetos com campo de id ("data"), extraindo {data, lvl, timer, cnt}. Assim o
parser sobrevive a variações de nome de seção entre versões do jogo.
"""
import json
import re
from . import gamedata

# seções que não representam progressão (ignoradas nas métricas)
IGNORED_CLASSES = {
    8,   # 8xxxxxx  obstáculos
    18,  # 18xxxxxx decorações
    52,  # skins
    62,  # sceneries
}


def looks_like_village_export(text):
    """Heurística rápida p/ watcher de clipboard."""
    if not text or len(text) < 50 or len(text) > 5_000_000:
        return False
    t = text.strip()
    if not (t.startswith("{") and t.endswith("}")):
        return False
    if '"tag"' not in t and "'tag'" not in t:
        return False
    try:
        obj = json.loads(t)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    # precisa ter ao menos uma lista de itens com ids numéricos de 7+ dígitos
    for v in obj.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            did = v[0].get("data", v[0].get("id"))
            if isinstance(did, int) and did >= 1_000_000:
                return True
    return False


def _iter_items(obj, prefix=""):
    """Percorre recursivamente listas de itens {data|id, lvl|level, timer, cnt}."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            yield from _iter_items(val, f"{prefix}{key}.")
    elif isinstance(obj, list):
        for el in obj:
            if isinstance(el, dict):
                did = el.get("data", el.get("id"))
                if isinstance(did, int) and did >= 1_000_000:
                    yield {
                        "section": prefix.rstrip("."),
                        "data": did,
                        "lvl": el.get("lvl", el.get("level")),
                        "timer": el.get("timer", el.get("t")),
                        "cnt": el.get("cnt", el.get("count", 1)),
                        "extra": {k: v for k, v in el.items()
                                  if k not in ("data", "id", "lvl", "level", "timer", "t", "cnt", "count")},
                    }
                    # itens aninhados (ex.: Estação de Criação -> types -> modules)
                    for k, v in el.items():
                        if isinstance(v, (list, dict)):
                            yield from _iter_items(v, prefix)
                else:
                    yield from _iter_items(el, prefix)


def _detect_level_offset(items):
    """
    Detecta se os níveis do export são 0-based (offset +1) ou 1-based (offset 0).
    Escolhe o offset com menos níveis impossíveis (acima do máximo conhecido
    ou abaixo de 1) considerando apenas entidades conhecidas.
    """
    scores = {}
    for off in (0, 1):
        bad = 0
        for it in items:
            ent = gamedata.entity(it["data"])
            if not ent or it["lvl"] is None:
                continue
            lvl = it["lvl"] + off
            mx = gamedata.max_level(ent)
            if lvl < 1 or (mx is not None and lvl > mx):
                bad += 1
        scores[off] = bad
    # empate -> assume 1-based (offset 0)
    return 0 if scores[0] <= scores[1] else 1


def parse(text_or_obj):
    """
    Retorna snapshot normalizado:
    {
      tag, timestamp, level_offset,
      items: [{section, data, lvl (corrigido), timer, cnt, name, category, base, known}],
      unknown_ids: [...], counts: {...}
    }
    """
    if isinstance(text_or_obj, str):
        obj = json.loads(text_or_obj)
    else:
        obj = text_or_obj
    if not isinstance(obj, dict):
        raise ValueError("Export inválido: raiz não é objeto JSON")

    tag = obj.get("tag") or obj.get("playerTag") or ""
    if tag and not tag.startswith("#"):
        tag = "#" + tag
    timestamp = obj.get("timestamp") or obj.get("time") or obj.get("exportedAt")

    raw_items = list(_iter_items(obj))
    offset = _detect_level_offset(raw_items)

    items, unknown = [], {}
    for it in raw_items:
        cls = it["data"] // 1_000_000
        ent = gamedata.entity(it["data"])
        lvl = (it["lvl"] + offset) if isinstance(it["lvl"], int) else it["lvl"]
        rec = {
            "section": it["section"],
            "data": it["data"],
            "lvl": lvl,
            "timer": it["timer"],
            "cnt": it["cnt"] or 1,
            "known": ent is not None,
            "ignored": cls in IGNORED_CLASSES,
        }
        ex = it.get("extra") or {}
        if ex.get("supercharge"):
            rec["supercharge"] = ex["supercharge"]
        if ex.get("gear_up"):
            rec["gear_up"] = ex["gear_up"]
        if ent:
            rec.update(name=ent["name"], category=ent["category"], base=ent["base"])
        else:
            if cls not in IGNORED_CLASSES:
                unknown[it["data"]] = unknown.get(it["data"], 0) + 1
        items.append(rec)

    th_lvl = None
    for rec in items:
        if rec["data"] == 1000001:  # Town Hall
            th_lvl = rec["lvl"]
            break

    return {
        "tag": tag,
        "timestamp": timestamp,
        "level_offset": offset,
        "th_level": th_lvl,
        "items": items,
        "unknown_ids": sorted(unknown.keys()),
        "counts": {
            "total": len(items),
            "known": sum(1 for i in items if i["known"]),
            "unknown": len(unknown),
        },
    }
