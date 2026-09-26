#!/usr/bin/env python3
"""Importa coc.rar para static/assets/coc usando um extrator RAR instalado."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ALLOWED = {".png", ".webp", ".jpg", ".jpeg", ".svg", ".json", ".txt"}


def extract(archive: Path, target: Path) -> None:
    commands = []
    if shutil.which("7z"):
        commands.append(["7z", "x", "-y", f"-o{target}", str(archive)])
    if shutil.which("7zz"):
        commands.append(["7zz", "x", "-y", f"-o{target}", str(archive)])
    if shutil.which("unar"):
        commands.append(["unar", "-quiet", "-output-directory", str(target), str(archive)])
    if shutil.which("bsdtar"):
        commands.append(["bsdtar", "-xf", str(archive), "-C", str(target)])
    if shutil.which("unrar"):
        commands.append(["unrar", "x", "-o+", str(archive), str(target)])
    for command in commands:
        try:
            subprocess.run(command, check=True)
            return
        except subprocess.CalledProcessError:
            continue
    raise SystemExit(
        "Nenhum extrator RAR compatível funcionou. Instale 7-Zip/unar/unrar, "
        "ou extraia manualmente a pasta coc para static/assets/coc."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    destination = args.repo.resolve() / "static" / "assets" / "coc"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        extract(args.archive.resolve(), tmp)
        source = tmp / "coc"
        if not source.is_dir():
            matches = [path for path in tmp.rglob("coc") if path.is_dir()]
            if not matches:
                raise SystemExit("Pasta coc não encontrada no arquivo.")
            source = matches[0]
        count = 0
        for file in source.rglob("*"):
            if file.is_file() and file.suffix.lower() in ALLOWED:
                output = destination / file.relative_to(source)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, output)
                count += 1
        print(f"{count} assets copiados para {destination}")


if __name__ == "__main__":
    main()
