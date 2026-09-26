#!/usr/bin/env python3
"""Importa e completa o catálogo local de assets do COC Control.

Fluxo normal:
    python tools/import_coc_assets.py caminho/para/coc.rar

Para complementar imagens ausentes usando catálogos públicos:
    python tools/import_coc_assets.py caminho/para/coc.rar --complete

O runtime do COC Control continua 100% local: ``--complete`` acessa a internet
somente durante a sincronização e materializa tudo em ``static/assets/coc``.
Licença/proveniência das fontes são preservadas sem criar dependência de CDN.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ALLOWED = {".png", ".webp", ".jpg", ".jpeg", ".svg", ".json", ".txt"}
IMAGE_EXT = {".png", ".webp", ".jpg", ".jpeg", ".svg"}
CLASHKING_REPO = "https://github.com/ClashKingInc/ClashKingAssets.git"
SYNC_DIRS = (
    "assets/buildings",
    "assets/traps",
    "assets/helpers",
    "assets/heroes",
    "assets/troops",
    "assets/spells",
    "assets/pets",
    "assets/equipment",
)

# O próprio ClashKingApp registra que estes assets não existem no catálogo
# ClashKingAssets. Os URLs abaixo são referências estáticas públicas usadas pelo
# projeto clashpost. São baixados somente no --complete e ficam locais depois.
SUPPLEMENT_HOSTS = {"static.clashpost.com"}
SUPPLEMENTAL_ASSETS = (
    {
        "target": "buildings/home-village/bob's_hut/level_1.png",
        "url": "https://static.clashpost.com/upgrade/home_buildings/0501/B.O.Bs_Hut.png",
        "reference": "https://github.com/lemonicy/clashpost/blob/97fcc5c930d20a9f29ba33cbff631a3729094dee/docs/upgrade/0501-B.O.Bs-Hut.md",
    },
    {
        "target": "buildings/home-village/helper_hut/level_1.png",
        "url": "https://static.clashpost.com/upgrade/home_buildings/0502/Helper_Hut.png",
        "reference": "https://github.com/lemonicy/clashpost/blob/97fcc5c930d20a9f29ba33cbff631a3729094dee/docs/upgrade/category/home.md",
    },
    {
        "target": "buildings/home-village/crafting_station/level_1.png",
        "url": "https://static.clashpost.com/upgrade/home_buildings/048a/Crafting_Station_info.png",
        "reference": "https://github.com/lemonicy/clashpost/blob/97fcc5c930d20a9f29ba33cbff631a3729094dee/docs/upgrade/048a-Crafting-Station.md",
    },
    {
        "target": "buildings/builder-base/reinforcement_camp/level_1.png",
        "url": "https://static.clashpost.com/upgrade/bh_buildings/1285/Reinforcement_Camp.png",
        "reference": "https://github.com/lemonicy/clashpost/blob/97fcc5c930d20a9f29ba33cbff631a3729094dee/docs/upgrade/1285-Reinforcement-Camp.md",
    },
)

# Alguns objetos do export são altares/representações do herói e não possuem
# building art no ClashKingAssets. Materializamos um alias local usando o ícone
# do herói do mesmo catálogo. O Alchemist também recebe alias compatível com a
# categoria antiga `other`, enquanto o backend o classifica como ajudante.
LOCAL_ALIASES = (
    ("heroes/battle_machine/icon.webp", "buildings/builder-base/battle_machine_altar/level_1.webp"),
    ("heroes/battle_copter/icon.webp", "buildings/builder-base/battle_copter_altar/level_1.webp"),
    ("helpers/alchemist.png", "buildings/home-village/alchemist/level_1.png"),
)
MAX_SUPPLEMENT_BYTES = 5 * 1024 * 1024


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
    return matches[0] if matches else tmp


def _safe_relative(path: Path, base: Path) -> Path:
    rel = path.resolve().relative_to(base.resolve())
    if any(part in {"..", ""} for part in rel.parts):
        raise ValueError("caminho inválido no pacote")
    return rel


def _copy_tree(source: Path, destination: Path) -> int:
    count = 0
    if not source.exists():
        return count
    for item in source.rglob("*"):
        if not item.is_file() or item.suffix.lower() not in ALLOWED:
            continue
        rel = _safe_relative(item, source)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def _sync_clashking(destination: Path) -> int:
    if not shutil.which("git"):
        raise SystemExit("--complete requer Git disponível no PATH.")
    with tempfile.TemporaryDirectory(prefix="coc-clashking-") as td:
        checkout = Path(td) / "ClashKingAssets"
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", CLASHKING_REPO, str(checkout)],
            check=True,
        )
        subprocess.run(["git", "-C", str(checkout), "sparse-checkout", "set", *SYNC_DIRS], check=True)
        assets = checkout / "assets"
        copied = 0
        for dirname in ("buildings", "traps", "helpers", "heroes", "troops", "spells", "pets", "equipment"):
            copied += _copy_tree(assets / dirname, destination / dirname)

        license_file = checkout / "LICENSE"
        if license_file.is_file():
            shutil.copy2(license_file, destination / "CLASHKING-LICENSE.txt")
        head = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        (destination / "catalog-provenance.json").write_text(
            json.dumps({
                "source": "ClashKingInc/ClashKingAssets",
                "repository": CLASHKING_REPO,
                "commit": head,
                "synced_at": int(time.time()),
                "runtime_dependency": False,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return copied


def _looks_like_image(payload: bytes) -> bool:
    return (
        payload.startswith(b"\x89PNG\r\n\x1a\n")
        or payload.startswith((b"\xff\xd8\xff", b"RIFF"))
        or payload.lstrip().startswith(b"<svg")
        or b"<svg" in payload[:512].lower()
    )


def _download_supplement(url: str, target: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in SUPPLEMENT_HOSTS:
        raise ValueError("origem suplementar não permitida")
    request = Request(url, headers={"User-Agent": "COC-Control-Asset-Sync/1.0"})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - URL hardcoded/allowlisted acima
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in SUPPLEMENT_HOSTS:
            raise ValueError("redirecionamento para origem não permitida")
        payload = response.read(MAX_SUPPLEMENT_BYTES + 1)
    if len(payload) > MAX_SUPPLEMENT_BYTES:
        raise ValueError("asset excede 5 MiB")
    if not _looks_like_image(payload):
        raise ValueError("resposta não parece ser uma imagem")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _sync_supplements(destination: Path) -> int:
    copied = 0
    provenance = []
    for item in SUPPLEMENTAL_ASSETS:
        target = destination / item["target"]
        status = "existing"
        if not target.is_file():
            try:
                _download_supplement(item["url"], target)
                copied += 1
                status = "downloaded"
            except Exception as exc:
                status = f"error: {exc}"
                print(f"Aviso: não foi possível obter {item['target']}: {exc}")
        provenance.append({**item, "status": status})
    (destination / "supplemental-provenance.json").write_text(
        json.dumps({
            "source": "lemonicy/clashpost (referências públicas de assets)",
            "synced_at": int(time.time()),
            "runtime_dependency": False,
            "license_note": (
                "O repositório de referência lemonicy/clashpost não declarava licença no metadata "
                "consultado. Revise os direitos de redistribuição antes de publicar esses binários."
            ),
            "assets": provenance,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return copied


def _materialize_aliases(destination: Path) -> int:
    copied = 0
    for source_rel, target_rel in LOCAL_ALIASES:
        source = destination / source_rel
        target = destination / target_rel
        if target.is_file() or not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def _manifest_entry(rel: Path) -> dict:
    parts = rel.parts
    category = parts[0] if parts else "root"
    base = None
    entity = None
    level = None

    if category in {"buildings", "traps"} and len(parts) >= 4:
        base, entity = parts[1], parts[2]
    elif category in {"heroes", "pets", "helpers", "troops", "equipment"} and len(parts) >= 3:
        # ClashKingAssets organiza estes catálogos como categoria/entidade/arquivo.
        # O entity é necessário para resolver icon.webp e variações por nome.
        entity = parts[1]
    elif len(parts) >= 2:
        entity = rel.stem

    match = re.search(r"(?:level_|^)(\d+)$", rel.stem)
    if match:
        level = int(match.group(1))

    return {
        "path": rel.as_posix(),
        "name": rel.stem,
        "category": category,
        "base": base,
        "entity": entity,
        "level": level,
    }


def _write_manifest(destination: Path) -> int:
    manifest = []
    for item in destination.rglob("*"):
        if not item.is_file() or item.suffix.lower() not in IMAGE_EXT:
            continue
        rel = _safe_relative(item, destination)
        manifest.append(_manifest_entry(rel))
    manifest.sort(key=lambda value: (value["category"], value.get("base") or "", value["path"]))
    (destination / "assets-manifest.json").write_text(
        json.dumps({"count": len(manifest), "assets": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa/completa assets locais do COC Control")
    parser.add_argument("archive", type=Path, nargs="?", help="caminho para coc.rar")
    parser.add_argument("--repo", type=Path, default=Path("."), help="raiz do checkout")
    parser.add_argument(
        "--complete", action="store_true",
        help="completa assets ausentes usando catálogos públicos e mantém tudo local",
    )
    args = parser.parse_args()
    if not args.archive and not args.complete:
        parser.error("informe coc.rar e/ou use --complete")

    destination = args.repo.resolve() / "static" / "assets" / "coc"
    destination.mkdir(parents=True, exist_ok=True)
    imported = 0

    if args.archive:
        src = args.archive.expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"Arquivo não encontrado: {src}")
        with tempfile.TemporaryDirectory(prefix="coc-assets-") as tmpdir:
            tmp = Path(tmpdir)
            if not (_extract_with_rarfile(src, tmp) or _extract_with_cli(src, tmp)):
                raise SystemExit(
                    "Não foi possível extrair o RAR. Instale 7-Zip/7zz, unar, bsdtar ou unrar e tente novamente."
                )
            imported += _copy_tree(_find_source_root(tmp), destination)

    clashking = _sync_clashking(destination) if args.complete else 0
    supplemental = _sync_supplements(destination) if args.complete else 0
    aliases = _materialize_aliases(destination) if args.complete else 0
    total = _write_manifest(destination)
    print(f"Arquivos importados do pacote: {imported}")
    print(f"Arquivos complementados do ClashKingAssets: {clashking}")
    print(f"Assets suplementares conhecidos: {supplemental}")
    print(f"Aliases locais materializados: {aliases}")
    print(f"Assets no manifest: {total}")
    print(f"Destino: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
