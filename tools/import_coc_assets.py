#!/usr/bin/env python3
"""Importa o pacote de assets fornecido para o COC Control.

Uso:
    python tools/import_coc_assets.py caminho/para/coc.rar

O script não baixa conteúdo externo. Ele preserva os arquivos de licença/proveniência
que existirem no pacote e gera ``static/assets/coc/assets-manifest.json`` para a UI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "static" / "assets" / "coc"
ALLOWED = {".png", ".webp", ".jpg", ".jpeg", ".svg", ".json", ".txt"}


def _extract_with_rarfile(src: Path, tmp: Path) -> bool:
    try:
        import rarfile  # type: ignore
        with rarfile.RarFile(src) as rf:
            rf.extractall(tmp)
        return True
    except Exception:
        return False


def _extract_with_cli(src: Path, tmp: Path) -> bool:
    candidates = [
        ["unrar", "x", "-o+", str(src), str(tmp)],
        ["7z", "x", f"-o{tmp}", str(src), "-y"],
        ["unar", "-o", str(tmp), str(src)],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return True
            except subprocess.CalledProcessError:
                pass
    return False


def _safe_relative(path: Path, base: Path) -> Path:
    rel = path.resolve().relative_to(base.resolve())
    if any(part in {"..", ""} for part in rel.parts):
        raise ValueError("caminho inválido no pacote")
    return rel


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python tools/import_coc_assets.py caminho/para/coc.rar")
        return 2
    src = Path(sys.argv[1]).expanduser().resolve()
    if not src.is_file():
        print(f"Arquivo não encontrado: {src}")
        return 2

    import tempfile
    with tempfile.TemporaryDirectory(prefix="coc-assets-") as td:
        tmp = Path(td)
        if not (_extract_with_rarfile(src, tmp) or _extract_with_cli(src, tmp)):
            print("Não foi possível extrair o RAR. Instale unrar, 7z ou unar e tente novamente.")
            return 1

        roots = [p for p in tmp.iterdir() if p.is_dir()]
        source_root = roots[0] if len(roots) == 1 and roots[0].name.lower() == "coc" else tmp
        DEST.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, str]] = []

        for item in source_root.rglob("*"):
            if not item.is_file() or item.suffix.lower() not in ALLOWED:
                continue
            rel = _safe_relative(item, source_root)
            target = DEST / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            manifest.append({
                "path": rel.as_posix(),
                "name": item.stem,
                "category": rel.parts[0] if len(rel.parts) > 1 else "root",
            })

        manifest.sort(key=lambda x: (x["category"], x["path"]))
        (DEST / "assets-manifest.json").write_text(
            json.dumps({"count": len(manifest), "assets": manifest}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"Assets importados: {len(manifest)}")
    print(f"Destino: {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
