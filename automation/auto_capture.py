#!/usr/bin/env python3
"""
Automação opcional: captura o export da vila no Google Play Games Beta (Windows)
e envia para o COC Control.

v2 — clique com VERIFICAÇÃO VISUAL: o script não clica mais às cegas na posição
gravada. Ele rola a janela de configurações e só clica quando LOCALIZA o botão
"Copiar" na tela (template matching multi-escala via OpenCV). Se não encontrar,
aborta sem clicar em nada (evita acertar botões errados como "Sim").

Passos
======
1. `python automation/auto_capture.py --record`
   Grava o perfil UMA vez. Além das posições, agora salva uma IMAGEM de cada
   botão (automation/templates/*.png) usada para reconhecê-los na execução.
   -> Se você tinha um perfil antigo, rode --record de novo.

2. `python automation/auto_capture.py --run [--dry-run]`
   Localiza a janela do jogo, navega (engrenagem -> Mais configurações),
   rola até ENCONTRAR o botão Copiar, clica, valida o clipboard e envia ao
   COC Control. Com --dry-run ele para em cima do botão sem clicar (teste).

3. `python automation/auto_capture.py --run --loop 360`
   Repete a cada 360 minutos.

Segurança: mouse no CANTO SUPERIOR ESQUERDO aborta (pyautogui failsafe).

AVISO (ToS): automatizar interação com o cliente pode violar os Termos da
Supercell mesmo usando só o export oficial. Alternativa 100% segura: watcher de
clipboard (você clica em Copiar manualmente).
"""
import argparse
import json
import os
import sys
import time

try:
    import pyautogui
    import pygetwindow as gw
    import pyperclip
    import requests
except ImportError as e:
    print(f"Dependência faltando: {e}. Rode: pip install -r requirements.txt")
    sys.exit(1)

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

pyautogui.FAILSAFE = True
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(HERE, "profile.json")
TPL_DIR = os.path.join(HERE, "templates")
DEFAULT_SERVER = "http://127.0.0.1:8420"

STEPS = [
    {"key": "engrenagem",  "tpl": True,  "size": (90, 90),
     "hint": "botão de ENGRENAGEM (configurações) no canto direito"},
    {"key": "mais_config", "tpl": True,  "size": (240, 70),
     "hint": "botão 'MAIS CONFIGURAÇÕES'"},
    {"key": "area_scroll", "tpl": False, "size": None,
     "hint": "CENTRO da janela de configurações (área que rola, longe de botões)"},
    {"key": "copiar",      "tpl": True,  "size": (220, 64),
     "hint": "botão 'COPIAR' da Exportação de dados (ROLE até o fim antes, deixe-o visível)"},
]

# ---------------------------------------------------------------- janela
def find_window(title_contains):
    wins = [w for w in gw.getAllWindows()
            if title_contains.lower() in (w.title or "").lower() and w.width > 200]
    return wins[0] if wins else None


def win_region(win):
    return (max(0, win.left), max(0, win.top), win.width, win.height)


def rel(win, x, y):
    return (x - win.left) / win.width, (y - win.top) / win.height


def absolute(win, rx, ry):
    return int(win.left + rx * win.width), int(win.top + ry * win.height)

# ------------------------------------------------- template matching
def find_template(screen_bgr, tmpl_bgr, scales=None, conf=0.80):
    """
    Procura tmpl em screen em várias escalas (janela pode ter tamanho diferente
    do momento da gravação). Retorna (x, y, score, scale) do centro, ou None.
    Função pura — testável sem tela.
    """
    if scales is None:
        scales = [round(0.55 + i * 0.07, 2) for i in range(15)]  # 0.55..1.53
    sg = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    tg0 = cv2.cvtColor(tmpl_bgr, cv2.COLOR_BGR2GRAY)
    best = None
    for sc in scales:
        w = max(12, int(tg0.shape[1] * sc))
        h = max(12, int(tg0.shape[0] * sc))
        if w >= sg.shape[1] or h >= sg.shape[0]:
            continue
        tg = cv2.resize(tg0, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(sg, tg, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best[2]:
            best = (loc[0] + w // 2, loc[1] + h // 2, float(mx), sc)
    if best and best[2] >= conf:
        return best
    return None


def screenshot_bgr(region):
    img = pyautogui.screenshot(region=region)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def locate_on_window(win, tpl_path, conf):
    region = win_region(win)
    screen = screenshot_bgr(region)
    tmpl = cv2.imread(tpl_path)
    if tmpl is None:
        return None
    hit = find_template(screen, tmpl, conf=conf)
    if not hit:
        return None
    x, y, score, sc = hit
    return (region[0] + x, region[1] + y, score, sc)

# ---------------------------------------------------------------- record
def record(args):
    print("== Gravação de perfil (v2 — com captura de imagem dos botões) ==")
    print("Deixe o Clash of Clans aberto no Google Play Games Beta.")
    title = input(f"Trecho do título da janela [{args.window}]: ").strip() or args.window
    win = find_window(title)
    if not win:
        print(f"Janela contendo '{title}' não encontrada. Janelas visíveis:")
        for w in gw.getAllWindows():
            if w.title.strip():
                print("  -", w.title)
        return
    print(f"Janela: '{win.title}' ({win.width}x{win.height})")
    os.makedirs(TPL_DIR, exist_ok=True)
    profile = {"version": 2, "window": title, "steps": {}, "templates": {},
               "scroll_step": -300, "max_scroll_rounds": 14,
               "confidence": 0.80, "delay": 1.2}
    for step in STEPS:
        input(f"\n>> Posicione o mouse sobre: {step['hint']}\n   (navegue no jogo se precisar) e pressione ENTER aqui...")
        for i in (3, 2, 1):
            print(f"   capturando em {i}...", end="\r")
            time.sleep(1)
        x, y = pyautogui.position()
        rx, ry = rel(win, x, y)
        profile["steps"][step["key"]] = [round(rx, 4), round(ry, 4)]
        if step["tpl"]:
            tw, th = step["size"]
            shot = pyautogui.screenshot(region=(x - tw // 2, y - th // 2, tw, th))
            tpl_path = os.path.join(TPL_DIR, f"{step['key']}.png")
            shot.save(tpl_path)
            profile["templates"][step["key"]] = os.path.relpath(tpl_path, HERE)
            print(f"   {step['key']}: pos ({rx:.3f},{ry:.3f}) + template {tw}x{th} salvo   ")
        else:
            print(f"   {step['key']}: pos ({rx:.3f},{ry:.3f})                         ")
    with open(PROFILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    print(f"\nPerfil salvo em {PROFILE}.")
    print("Teste sem clicar em Copiar:  python automation/auto_capture.py --run --dry-run")

# ------------------------------------------------------------------- run
def click_step(win, prof, key, conf, required_template=False, dry=False):
    """Clica um passo. Usa template se existir; posição gravada é só fallback
    de passos de navegação. Retorna True se clicou/encontrou."""
    tpl_rel = (prof.get("templates") or {}).get(key)
    tpl_path = os.path.join(HERE, tpl_rel) if tpl_rel else None
    if tpl_path and os.path.exists(tpl_path):
        hit = locate_on_window(win, tpl_path, conf)
        if hit:
            x, y, score, sc = hit
            pyautogui.moveTo(x, y, duration=0.35)
            if dry:
                print(f"   [dry-run] '{key}' encontrado (score {score:.2f}, escala {sc}) — não cliquei.")
                return True
            pyautogui.click()
            print(f"   '{key}' clicado (score {score:.2f}, escala {sc})")
            return True
        if required_template:
            return False
        print(f"   template de '{key}' não encontrado na tela; usando posição gravada (fallback).")
    elif required_template:
        print(f"   ERRO: template de '{key}' não existe — rode --record novamente (perfil antigo).")
        return False
    x, y = absolute(win, *prof["steps"][key])
    pyautogui.moveTo(x, y, duration=0.35)
    if not dry:
        pyautogui.click()
    return True


def run_once(args):
    if not HAS_CV2:
        print("OpenCV não instalado (necessário p/ localizar botões com segurança).")
        print("Rode: pip install opencv-python numpy")
        return False
    if not os.path.exists(PROFILE):
        print("Perfil não encontrado. Rode: python automation/auto_capture.py --record")
        return False
    with open(PROFILE, encoding="utf-8") as f:
        prof = json.load(f)
    if prof.get("version", 1) < 2 or not prof.get("templates"):
        print("Perfil antigo (sem imagens dos botões). Rode --record novamente.")
        return False
    win = find_window(prof.get("window", args.window))
    if not win:
        print("Janela do jogo não encontrada — o jogo está aberto?")
        return False
    try:
        win.activate()
    except Exception:
        pass
    time.sleep(1.0)
    delay = float(prof.get("delay", 1.2))
    conf = float(prof.get("confidence", 0.80))

    # navegação
    if not click_step(win, prof, "engrenagem", conf):
        print("Abortado: engrenagem não encontrada.")
        return False
    time.sleep(delay)
    if not click_step(win, prof, "mais_config", conf):
        print("Abortado: 'Mais configurações' não encontrado.")
        return False
    time.sleep(delay)

    # rola ATÉ ENCONTRAR o botão Copiar — nunca clica às cegas
    pyperclip.copy("")
    sx, sy = absolute(win, *prof["steps"]["area_scroll"])
    pyautogui.moveTo(sx, sy, duration=0.3)
    tpl_path = os.path.join(HERE, prof["templates"]["copiar"])
    rounds = int(prof.get("max_scroll_rounds", 14))
    step = int(prof.get("scroll_step", -300))
    found = None
    for i in range(rounds):
        hit = locate_on_window(win, tpl_path, conf)
        if hit:
            found = hit
            break
        pyautogui.scroll(step)
        time.sleep(0.45)
    if not found:
        print(f"Botão 'Copiar' NÃO localizado após {rounds} rolagens — nada foi clicado.")
        print("Dicas: aumente 'max_scroll_rounds' no profile.json, regrave o template (--record)")
        print("ou diminua 'confidence' (ex.: 0.75).")
        pyautogui.press("esc")  # fecha a janela de configurações
        return False

    x, y, score, sc = found
    pyautogui.moveTo(x, y, duration=0.35)
    if args.dry_run:
        print(f"[dry-run] 'Copiar' localizado (score {score:.2f}, escala {sc}) — teste OK, nada clicado.")
        pyautogui.press("esc")
        return True
    pyautogui.click()
    print(f"'Copiar' clicado (score {score:.2f}, escala {sc})")
    time.sleep(0.9)

    text = pyperclip.paste()
    if not text or not text.strip().startswith("{") or '"tag"' not in text:
        print("Clipboard não recebeu um export válido — nada foi enviado.")
        return False
    headers = {"Content-Type": "application/json"}
    api_key = args.api_key or os.environ.get("COC_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = requests.post(f"{args.server}/api/import",
                          data=text.encode("utf-8"),
                          headers=headers, timeout=15)
        if r.ok:
            j = r.json()
            print(f"OK: vila {j.get('tag')} (TH{j.get('th_level')}) importada -> conta '{j['account']['name']}'")
            pyautogui.press("esc")
            return True
        print("Servidor recusou:", r.status_code, r.text[:300])
    except Exception as e:
        print(f"Falha ao enviar para o COC Control ({args.server}): {e}")
        print("O JSON continua no clipboard — use 'Importar do clipboard' na interface.")
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", action="store_true", help="grava o perfil de cliques + imagens dos botões")
    ap.add_argument("--run", action="store_true", help="executa a captura")
    ap.add_argument("--dry-run", action="store_true", help="com --run: localiza tudo mas não clica em Copiar")
    ap.add_argument("--loop", type=int, metavar="MIN", help="repete a cada N minutos")
    ap.add_argument("--window", default="Clash of Clans", help="trecho do título da janela do jogo")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--api-key", default=None,
                    help="API key do COC Control (Configurações) p/ servidor com login; ou env COC_API_KEY")
    args = ap.parse_args()

    if args.record:
        record(args)
    elif args.run:
        if args.loop:
            print(f"Loop: captura a cada {args.loop} min. Ctrl+C para parar. Mouse no canto sup. esquerdo aborta.")
            while True:
                run_once(args)
                time.sleep(args.loop * 60)
        else:
            run_once(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
