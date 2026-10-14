"""Gera os pacotes de um clique: dist/MCP-Arrendamento-mac.zip e -windows.zip.

Cada pacote leva o código, os lançadores e o `uv` (baixado do release oficial e
conferido pelo SHA-256 publicado), que na primeira execução baixa o Python e as
bibliotecas. O usuário não instala nada.

Uso:  .venv/bin/python scripts/empacotar.py
"""

from __future__ import annotations

import hashlib
import io
import stat
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
UV = "0.11.7"
BASE = f"https://github.com/astral-sh/uv/releases/download/{UV}"
PASTA = "MCP Arrendamento"


def baixar(nome: str) -> bytes:
    dados = urllib.request.urlopen(f"{BASE}/{nome}").read()
    esperado = urllib.request.urlopen(f"{BASE}/{nome}.sha256").read().split()[0].decode()
    if hashlib.sha256(dados).hexdigest() != esperado:
        raise SystemExit(f"SHA-256 de {nome} não confere")
    return dados


def uv_do_tar(nome: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(baixar(nome))) as tar:
        membro = next(m for m in tar.getmembers() if m.name.endswith("/uv"))
        return tar.extractfile(membro).read()


def uv_do_zip(nome: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(baixar(nome))) as z:
        return z.read(next(n for n in z.namelist() if n.endswith("uv.exe")))


def escrever(z: zipfile.ZipFile, caminho: str, dados: bytes, executavel: bool = False) -> None:
    info = zipfile.ZipInfo(f"{PASTA}/{caminho}")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = ((stat.S_IFREG | (0o755 if executavel else 0o644)) << 16)
    z.writestr(info, dados)


def comum(z: zipfile.ZipFile) -> None:
    for arquivo in sorted((RAIZ / "src" / "mcp_arrendamento").glob("*.py")):
        escrever(z, f"app/src/mcp_arrendamento/{arquivo.name}", arquivo.read_bytes())
    escrever(z, "app/requisitos.txt", (RAIZ / "lancadores" / "requisitos.txt").read_bytes())
    escrever(z, "LEIA-ME.txt", (RAIZ / "lancadores" / "LEIA-ME.txt").read_bytes())
    escrever(z, "skill-cadastrar-contrato-arrendamento.md",
             (RAIZ / "skills" / "cadastrar-contrato-arrendamento.md").read_bytes())


def main() -> None:
    dist = RAIZ / "dist"
    dist.mkdir(exist_ok=True)
    lanc = RAIZ / "lancadores"
    with zipfile.ZipFile(dist / "MCP-Arrendamento-mac.zip", "w") as z:
        comum(z)
        for nome in ("Iniciar MCP Arrendamento.command", "Copiar token do conector.command"):
            escrever(z, nome, (lanc / nome).read_bytes(), executavel=True)
        escrever(z, "app/bin/uv-arm64", uv_do_tar("uv-aarch64-apple-darwin.tar.gz"), executavel=True)
        escrever(z, "app/bin/uv-x86_64", uv_do_tar("uv-x86_64-apple-darwin.tar.gz"), executavel=True)
    with zipfile.ZipFile(dist / "MCP-Arrendamento-windows.zip", "w") as z:
        comum(z)
        for nome in ("Iniciar MCP Arrendamento.bat", "Copiar token do conector.bat"):
            escrever(z, nome, (lanc / nome).read_bytes())
        escrever(z, "app/bin/uv.exe", uv_do_zip("uv-x86_64-pc-windows-msvc.zip"))
    for pacote in sorted(dist.glob("MCP-Arrendamento-*.zip")):
        print(f"{pacote.name}: {pacote.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
