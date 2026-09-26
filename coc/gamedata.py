"""Carrega a base estática (data/game_data.json) e oferece helpers de consulta."""
import json
import os

_DATA = None


def load(path=None):
    global _DATA
    if _DATA is None:
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "game_data.json")
        with open(path, encoding="utf-8") as f:
            _DATA = json.load(f)
        ov_path = os.path.join(os.path.dirname(path), "overrides.json")
        if os.path.exists(ov_path):
            try:
                with open(ov_path, encoding="utf-8") as f:
                    ov = json.load(f)
                for did, ent in (ov.get("entities") or {}).items():
                    _DATA["entities"][str(did)] = ent
            except Exception as e:
                print(f"[gamedata] overrides.json ignorado: {e}")
    return _DATA


def entity(data_id):
    """Entidade pelo dataId do export (int ou str). None se desconhecida."""
    return load()["entities"].get(str(data_id))


def max_level(ent):
    return ent["levels"][-1]["lvl"] if ent["levels"] else None


def max_level_at_th(ent, th):
    """Maior nível disponível no TH informado (None se nenhum nível tem info de TH)."""
    best, has_th = None, False
    for lv in ent["levels"]:
        if "th" in lv:
            has_th = True
            if lv["th"] <= th:
                best = lv["lvl"]
        elif best is not None:
            # níveis sem info de TH depois de níveis com info: assume liberado
            pass
    if not has_th:
        return None
    return best


def levels_between(ent, from_lvl, to_lvl):
    """Níveis (from_lvl, to_lvl] — os upgrades que faltam."""
    return [lv for lv in ent["levels"] if from_lvl < lv["lvl"] <= to_lvl]


def town_hall_meta(th):
    return load()["town_hall_meta"].get(str(th), {})
