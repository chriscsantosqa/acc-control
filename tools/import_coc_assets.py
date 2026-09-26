#!/usr/bin/env python3
"""Importa o pacote local ``coc.rar`` para ``static/assets/coc``.

Preserva arquivos de licença/proveniência presentes no pacote e gera
``assets-manifest.json`` para consumo da interface. Não baixa conteúdo externo.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ALLOWED = {".png", ".webp", ".jpg", ".jpeg", ".svg", ".json", ".txt"}


def _extract_with_rarfile(src: Path, target: Path) -> bool:
    try:
        import rarfile  # type: ignore

        with rarfile.RarFile(src) as rf:
            rf.extractall(target)
        return True
    except Exception:
        return False


def _extract_with_cli(src: Path, target: Path) -> bool:
    commands = []
    if shutil.which("7z"):
        commands.append(["7z", "x", "-y", f"-o{target}", str(src)])
    if shutil.which("7zz"):
        commands.append(["7zz", "x", "-y", f"-o{target}", str(src)])
    if shutil.which("unar"):
        commands.append(["unar", "-quiet", "-output-directory", str(target), str(src)])
    if shutil.which("bsdtar"):
        commands.append(["bsdtar", "-xf", str(src), "-C", str(target)])
    if shutil.which("unrar"):
        commands.append(["unrar", "x", "-o+", str(src), str(target)])

    for command in commands:
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except subprocess.CalledProcessError:
            continue
    return False


def _find_source_root(tmp: Path) -> Path:
    direct = tmp / "coc"
    if direct.is_dir():
        return direct
    matches = [path for path in tmp.rglob("coc") if path.is_dir()]
    if matches:
        return matches[0]
    return tmp


def _safe_relative(path: Path, base: Path) -> Path:
    rel = path.resolve().relative_to(base.resolve())
    if any(part in {"..", ""} for part in rel.parts):
        raise ValueError("caminho inválido no pacote")
    return rel


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa assets locais do COC Control")
    parser.add_argument("archive", type=Path, help="caminho para coc.rar")
    parser.add_argument("--repo", type=Path, default=Path("."), help="raiz do checkout do repositório")
    args = parser.parse_args()

    src = args.archive.expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"Arquivo não encontrado: {src}")

    destination = args.repo.resolve() / "static" / "assets" / "coc"
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="coc-assets-") as tmpdir:
        tmp = Path(tmpdir)
        if not (_extract_with_rarfile(src, tmp) or _extract_with_cli(src, tmp)):
            raise SystemExit(
                "Não foi possível extrair o RAR. Instale 7-Zip/7zz, unar, bsdtar ou unrar e tente novamente."
            )

        source_root = _find_source_root(tmp)
        manifest: list[dict[str, str]] = []

        for item in source_root.rglob("*"):
            if not item.is_file() or item.suffix.lower() not in ALLOWED:
                continue
            rel = _safe_relative(item, source_root)
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            manifest.append(
                {
                    "path": rel.as_posix(),
                    "name": item.stem,
                    "category": rel.parts[0] if len(rel.parts) > 1 else "root",
                }
            )

        manifest.sort(key=lambda value: (value["category"], value["path"]))
        (destination / "assets-manifest.json").write_text(
            json.dumps({"count": len(manifest), "assets": manifest}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"Assets importados: {len(manifest)}")
    print(f"Destino: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
