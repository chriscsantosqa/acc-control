#!/usr/bin/env python3
"""Testa o template matching da automação (sem precisar de tela).
Rodar da raiz: python tests/test_matcher.py  (requer opencv + numpy)"""
import importlib.util, os, random, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for m in ("pyautogui", "pygetwindow", "pyperclip", "requests"):
    sys.modules.setdefault(m, types.ModuleType(m))
sys.modules["pyautogui"].FAILSAFE = True
spec = importlib.util.spec_from_file_location(
    "ac", os.path.join(os.path.dirname(__file__), "..", "automation", "auto_capture.py"))
ac = importlib.util.module_from_spec(spec); spec.loader.exec_module(ac)
import cv2, numpy as np
random.seed(7); np.random.seed(7)

def make_button(seed, w=200, h=56):
    img = np.zeros((h, w, 3), np.uint8)
    for i in range(h):
        f = 1.15 - 0.5 * i / h
        img[i, :] = [min(255, int(c * f)) for c in (60, 190, 80)]
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (20, 60, 25), 3)
    rnd, x = random.Random(seed), 30
    for _ in range(seed):
        bw = rnd.randint(8, 16)
        cv2.rectangle(img, (x, 18), (x + bw, 38), (255, 255, 255), -1)
        x += bw + 6
    return img

tmpl, sim = make_button(6), make_button(3, w=160)

def screen(button=None, scale=1.0):
    scr = (np.random.rand(760, 1300, 3) * 60 + 20).astype(np.uint8)
    cv2.rectangle(scr, (200, 80), (1100, 700), (90, 140, 180), -1)
    scr[300:356, 300:460] = sim
    pos = None
    if button is not None:
        b = cv2.resize(button, (int(200 * scale), int(56 * scale)))
        scr[520:520 + b.shape[0], 760:760 + b.shape[1]] = b
        pos = (760 + b.shape[1] // 2, 520 + b.shape[0] // 2)
    return scr, pos

for sc in (1.0, 0.75, 1.3):
    s, pos = screen(tmpl, sc)
    hit = ac.find_template(s, tmpl, conf=0.80)
    assert hit and abs(hit[0] - pos[0]) < 10 and abs(hit[1] - pos[1]) < 10, f"escala {sc}"
    print(f"  ✔ encontra na escala {sc} (score {hit[2]:.2f})")
s, _ = screen(None)
assert ac.find_template(s, tmpl, conf=0.80) is None, "falso positivo!"
print("  ✔ não confunde com botão parecido ('Sim') — sem match, sem clique")
print("matcher ok ✔")
