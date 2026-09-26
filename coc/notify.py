"""
Alertas de término de upgrades.

Canais: toast do Windows (via PowerShell/WinRT, sem dependências extras),
Telegram (bot) e Discord (webhook). Dedupe persistido em SQLite (tabela
`notified`), então reiniciar o app não repete avisos.

Assinantes (trusted=False) não recebem toast (seria a tela do servidor) e só
enviam para endereços públicos (coc/netguard.py). Nenhum envio segue
redirecionamento.
"""
import datetime
import html
import json
import platform
import re
import subprocess

from . import netguard

try:
    import requests
except ImportError:
    requests = None


# ------------------------------------------------------------- canais
def send_toast(title, body):
    if platform.system() != "Windows":
        return False
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] > $null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n = $t.GetElementsByTagName('text');"
        "$n.Item(0).AppendChild($t.CreateTextNode($env:T_TITLE)) > $null;"
        "$n.Item(1).AppendChild($t.CreateTextNode($env:T_BODY)) > $null;"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($t);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'COC Control').Show($toast);"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env={**__import__('os').environ, "T_TITLE": title, "T_BODY": body},
                       timeout=15, capture_output=True)
        return True
    except Exception:
        return False


def send_telegram(token, chat_id, text):
    if not (requests and token and chat_id):
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                          timeout=10, allow_redirects=False)
        return r.ok
    except Exception:
        return False


def send_evolution(url, apikey, instance, number, text):
    """WhatsApp via Evolution API: POST {url}/message/sendText/{instance}
    com header apikey. `number` aceita telefone (5511...) ou JID de grupo
    (...@g.us) — mesmo formato dos seus fluxos do n8n."""
    if not (requests and url and apikey and instance and number):
        return False
    url = evolution_base(url)                   # aceita o endpoint completo colado
    try:
        r = requests.post(f"{url}/message/sendText/{instance}",
                          json={"number": number, "text": text},
                          headers={"apikey": apikey}, timeout=12, allow_redirects=False)
        return r.status_code in (200, 201)
    except Exception:
        return False


def send_discord(webhook, text):
    if not (requests and webhook):
        return False
    try:
        r = requests.post(webhook, json={"content": text[:1900]}, timeout=10, allow_redirects=False)
        return r.status_code in (200, 204)
    except Exception:
        return False


TELEGRAM_TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,80}$")
EVOLUTION_INSTANCE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def evolution_base(url):
    """Base da Evolution API como o envio vai usá-la."""
    url = (url or "").strip().rstrip("/")
    if "/message/" in url:
        url = url.split("/message/")[0]
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def channel_problems(settings):
    """Canais de um assinante que não podem ser usados, com o motivo: {campo: motivo}."""
    out = {}
    tok = settings.get("telegram_token")
    if tok and not TELEGRAM_TOKEN.match(str(tok)):
        out["telegram_token"] = "token do bot inválido (formato 123456:ABC...)"
    hook = settings.get("discord_webhook")
    if hook:
        why = netguard.discord_problem(hook)
        if why:
            out["discord_webhook"] = why
    ev = settings.get("evolution_url")
    if ev:
        why = netguard.public_https_problem(evolution_base(ev))
        if why:
            out["evolution_url"] = why
    inst = settings.get("evolution_instance")
    if inst and not EVOLUTION_INSTANCE.match(str(inst)):
        out["evolution_instance"] = "use só letras, números, ponto, hífen ou sublinhado"
    return out


def dispatch(settings, title, body, trusted=True):
    """Envia para todos os canais habilitados. Retorna lista dos que aceitaram.
    `trusted` é o dono; os canais de assinantes passam por channel_problems."""
    sent = []
    blocked = {} if trusted else channel_problems(settings)
    if trusted and settings.get("toast_enabled") and send_toast(title, body):
        sent.append("toast")
    if settings.get("telegram_token") and settings.get("telegram_chat_id") and "telegram_token" not in blocked:
        if send_telegram(settings["telegram_token"], settings["telegram_chat_id"],
                         f"<b>{html.escape(title)}</b>\n{html.escape(body)}"):
            sent.append("telegram")
    if settings.get("discord_webhook") and "discord_webhook" not in blocked:
        if send_discord(settings["discord_webhook"], f"**{title}**\n{body}"):
            sent.append("discord")
    if (settings.get("evolution_url") and settings.get("evolution_apikey")
            and "evolution_url" not in blocked and "evolution_instance" not in blocked):
        if send_evolution(settings["evolution_url"], settings["evolution_apikey"],
                          settings.get("evolution_instance") or "principal",
                          settings.get("evolution_number"),
                          f"*{title}*\n{body}"):
            sent.append("whatsapp")
    return sent


# ---------------------------------------------------- geração de eventos
def _fmt_dt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def event_key(kind, account_id, data_id, finish_ts):
    """Chave de dedupe com bucket de 10 min: o finish_ts deriva alguns segundos
    entre re-imports (timestamp+timer arredondam) e sem o bucket o mesmo
    upgrade notificaria de novo a cada import."""
    return f"{kind}:{account_id}:{data_id}:{int((finish_ts + 300) // 600)}"


def build_events(account, summary, settings, now, stale_after=86400):
    """
    Eventos de notificação (função pura p/ teste): [{key, title, body, stale}].
    `stale`=True marca término antigo (> stale_after) — deve ser registrado no
    dedupe SEM disparar, para não inundar o WhatsApp ao ligar os alertas com
    um snapshot velho.
    """
    events = []
    lead = int(settings.get("lead_minutes") or 0) * 60
    name = account["name"]
    for up in summary.get("active_upgrades", []):
        fin = up["finish_ts"]
        base = f"{up['name']} {up['from_lvl']}→{up['to_lvl']}"
        tail = " — construtor liberado!" if up["queue"] == "builder" else \
               " — laboratório livre!" if up["queue"] == "lab" else ""
        if fin <= now:
            events.append({
                "key": event_key("fin", account["id"], up["data"], fin),
                "title": f"✅ {name}: upgrade concluído",
                "body": f"{base} terminou ({_fmt_dt(fin)}){tail}",
                "stale": (now - fin) > stale_after,
            })
        elif lead and fin - lead <= now:
            mins = max(1, round((fin - now) / 60))
            events.append({
                "key": event_key("soon", account["id"], up["data"], fin),
                "title": f"⏳ {name}: termina em ~{mins} min",
                "body": f"{base} termina às {_fmt_dt(fin)}",
                "stale": False,
            })
    return events


def build_digest(accounts_summaries, now):
    """Resumo diário: [(account, summary)] -> texto."""
    lines = []
    day_ago = now - 86400
    for acc, s in accounts_summaries:
        if not s:
            continue
        done = [u for u in s["active_upgrades"] if day_ago <= u["finish_ts"] <= now]
        nxt = [u for u in s["active_upgrades"] if u["finish_ts"] > now][:3]
        b = s["builders"]
        line = f"• {acc['name']} (TH{s['th_level']}, {s['progress_total']}%): "
        parts = []
        if done:
            parts.append(f"{len(done)} concluído(s) nas últimas 24h")
        free = b["total"] - sum(1 for u in s["active_upgrades"]
                                if u["queue"] == "builder" and u["finish_ts"] > now)
        parts.append(f"{max(0, free)}/{b['total']} construtores livres")
        if nxt:
            parts.append("próximos: " + "; ".join(f"{u['name']} {_fmt_dt(u['finish_ts'])}" for u in nxt))
        lines.append(line + " | ".join(parts))
    if not lines:
        return None
    return "Resumo diário COC Control\n" + "\n".join(lines)
