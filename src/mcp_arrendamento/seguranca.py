"""Barreiras para ferramentas que leem arquivos locais.

`arrendamento_enviar_arquivo` lê um caminho informado pelo modelo e o envia ao
sistema. Um texto malicioso lido do próprio sistema (uma observação, um nome de
arquivo) poderia induzir o modelo a "anexar" uma chave SSH ou um `.env`. Por
isso só sai o que está em pastas permitidas, fora de pastas e arquivos ocultos
(depois de resolver links simbólicos) e com extensão de documento.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from mcp_arrendamento.erros import ErroValidacao

EXTENSOES_DOCUMENTO = frozenset({
    ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt",
    ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff",
})


def arquivo_para_envio(caminho: str, raizes: Iterable[Path]) -> Path:
    """Devolve o caminho real do arquivo, ou recusa com o motivo."""
    informado = Path(caminho).expanduser()
    if not informado.is_file():
        raise ErroValidacao(f"Arquivo não encontrado: {informado}")
    real = informado.resolve()
    raizes_reais = [Path(r).expanduser().resolve() for r in raizes]
    base = next((r for r in raizes_reais if real.is_relative_to(r)), None)
    if base is None:
        permitidas = ", ".join(str(r) for r in raizes_reais)
        raise ErroValidacao(
            f"{real} está fora das pastas permitidas para envio ({permitidas}). Mova o arquivo "
            "para uma delas ou ajuste ARRENDAMENTO_PASTAS_ENVIO."
        )
    if any(parte.startswith(".") for parte in real.relative_to(base).parts):
        raise ErroValidacao(f"{real} é ou está em um arquivo ou pasta oculto; envio recusado.")
    if real.suffix.lower() not in EXTENSOES_DOCUMENTO:
        aceitas = " ".join(sorted(EXTENSOES_DOCUMENTO))
        raise ErroValidacao(f"{real.name}: extensão não aceita para anexo. Aceitas: {aceitas}.")
    return real
