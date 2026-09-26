"""
Endereços de saída escolhidos por assinantes (Evolution API, webhook do Discord).

O servidor faz POST nesses endereços. Sem esta checagem, um assinante apontaria o
alerta para dentro da VPS (localhost, rede do Docker, 169.254.169.254) e usaria o
COC Control como ponte para a rede interna. O dono continua livre para usar o
próprio n8n/Evolution interno: a checagem vale só para assinantes.

Resolve o nome e recusa qualquer IP que não seja público. Resta a janela entre
esta checagem e a conexão (DNS rebinding); por isso os envios também não seguem
redirecionamentos.
"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit

DISCORD_WEBHOOK = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d{5,30}/[A-Za-z0-9_-]{20,200}$")


def _ip_is_public(value):
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def public_https_problem(url):
    """None quando `url` é https e todos os IPs do host são públicos; senão, o motivo."""
    if not isinstance(url, str) or len(url) > 300:
        return "endereço inválido"
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return "endereço inválido"
    if parts.scheme != "https":
        return "use um endereço https://"
    host = parts.hostname
    if not host or parts.username or parts.password:
        return "endereço inválido"
    if not host.isascii():
        return "use o endereço sem acentos (forma punycode)"
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return "não encontrei esse servidor"
    if not infos:
        return "não encontrei esse servidor"
    for info in infos:
        try:
            if not _ip_is_public(info[4][0]):
                return "esse endereço aponta para uma rede interna"
        except ValueError:
            return "endereço inválido"
    return None


def discord_problem(url):
    return None if isinstance(url, str) and DISCORD_WEBHOOK.match(url.strip()) else \
        "use a URL de webhook do Discord (https://discord.com/api/webhooks/...)"
