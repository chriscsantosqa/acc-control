"""
Integração com a API oficial da Supercell (developer.clashofclans.com).

Requer um token gratuito criado pelo usuário, vinculado ao IP público da
máquina. Traz o "lado vivo" da conta que o export não tem: troféus, liga,
guerra, doações e clã.
"""
from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None

BASE = "https://api.clashofclans.com/v1"


class ApiError(Exception):
    pass


def fetch_player(tag, token):
    if not requests:
        raise ApiError("pacote 'requests' não instalado")
    if not token:
        raise ApiError("token da API Supercell não configurado (Configurações)")
    if not tag:
        raise ApiError("conta sem tag")
    r = requests.get(f"{BASE}/players/{quote(tag, safe='')}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=12)
    if r.status_code == 200:
        return _compact(r.json())
    if r.status_code in (401, 403):
        raise ApiError("token inválido ou IP não autorizado — crie/edite a chave em "
                       "developer.clashofclans.com com o IP atual desta máquina")
    if r.status_code == 404:
        raise ApiError(f"jogador {tag} não encontrado")
    if r.status_code == 429:
        raise ApiError("limite de requisições da API atingido — aguarde")
    if r.status_code == 503:
        raise ApiError("API em manutenção (provável manutenção do jogo)")
    raise ApiError(f"erro {r.status_code}: {r.text[:200]}")


def _league(p):
    """Resolve o nome da liga de forma defensiva — a API mudou os campos com o
    sistema ranqueado; procura em campos conhecidos e depois em qualquer chave
    contendo 'league'."""
    for k in ("league", "rankedLeague", "leagueTier", "currentLeague"):
        v = p.get(k)
        if isinstance(v, dict) and v.get("name"):
            return v["name"]
        if isinstance(v, str) and v:
            return v
    for k, v in p.items():
        if "league" in k.lower():
            if isinstance(v, dict) and v.get("name"):
                return v["name"]
            if isinstance(v, str) and v:
                return v
    ls = p.get("legendStatistics")
    if isinstance(ls, dict) and ls.get("currentSeason"):
        return "Legend League"
    return None


def verify_token(tag, dev_token, player_token):
    """POST /players/{tag}/verifytoken — confirma a POSSE da conta usando o
    'Token de API' que o jogador copia dentro do jogo (Configurações → Mais
    configurações → Token de API). Retorna True/False."""
    if not requests:
        raise ApiError("pacote 'requests' não instalado")
    if not dev_token:
        raise ApiError("token da API Supercell não configurado (Configurações)")
    if not tag:
        raise ApiError("conta sem tag")
    if not player_token:
        raise ApiError("informe o token do jogo (Configurações do jogo → Token de API → Mostrar)")
    r = requests.post(f"{BASE}/players/{quote(tag, safe='')}/verifytoken",
                      json={"token": player_token.strip()},
                      headers={"Authorization": f"Bearer {dev_token}"}, timeout=12)
    if r.status_code == 200:
        return (r.json() or {}).get("status") == "ok"
    if r.status_code in (401, 403):
        raise ApiError("token de desenvolvedor inválido ou IP não autorizado")
    if r.status_code == 404:
        raise ApiError(f"jogador {tag} não encontrado")
    raise ApiError(f"erro {r.status_code}: {r.text[:200]}")


def _compact(p):
    return {
        "tag": p.get("tag"),
        "name": p.get("name"),
        "expLevel": p.get("expLevel"),
        "townHallLevel": p.get("townHallLevel"),
        "trophies": p.get("trophies"),
        "bestTrophies": p.get("bestTrophies"),
        "builderBaseTrophies": p.get("builderBaseTrophies"),
        "league": _league(p),
        "warStars": p.get("warStars"),
        "attackWins": p.get("attackWins"),
        "defenseWins": p.get("defenseWins"),
        "donations": p.get("donations"),
        "donationsReceived": p.get("donationsReceived"),
        "clanCapitalContributions": p.get("clanCapitalContributions"),
        "clan": {
            "tag": (p.get("clan") or {}).get("tag"),
            "name": (p.get("clan") or {}).get("name"),
            "role": p.get("role"),
        } if p.get("clan") else None,
        "legend": {
            "trophies": (p.get("legendStatistics") or {}).get("legendTrophies"),
            "bestSeasonRank": ((p.get("legendStatistics") or {}).get("bestSeason") or {}).get("rank"),
        } if p.get("legendStatistics") else None,
        "_raw": p,  # resposta completa da API p/ depuração (botão { } na UI)
    }
