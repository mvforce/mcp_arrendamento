"""Configuração por variáveis de ambiente (todas opcionais)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


@dataclass(frozen=True)
class Config:
    base_url: str
    perfil_dir: Path
    janela: str
    canal: Optional[str]
    login_interativo: bool
    pasta_downloads: Path
    pastas_envio: tuple[Path, ...]


# minimizada: Chrome real com a janela minimizada (padrão). O Cloudflare passa sem desafio.
# visivel: janela normal, útil para acompanhar.
# headless: sem janela. O Cloudflare responde com a caixa "Confirme que é humano"
#   e o login silencioso trava; só serve se a STI criar exceção no WAF.
JANELAS = ("minimizada", "visivel", "headless")


def _booleano(valor: Optional[str], padrao: bool) -> bool:
    if valor is None or not valor.strip():
        return padrao
    return valor.strip().lower() not in ("0", "false", "nao", "não", "no", "off")


def carregar_config(env: Mapping[str, str] = os.environ) -> Config:
    raiz = Path.home() / ".mcp-arrendamento"
    canal = env.get("ARRENDAMENTO_CANAL", "chrome").strip()
    janela = env.get("ARRENDAMENTO_JANELA", "minimizada").strip().lower()
    if janela not in JANELAS:
        raise ValueError(f"ARRENDAMENTO_JANELA={janela!r}: use {', '.join(JANELAS)}.")
    return Config(
        base_url=env.get("ARRENDAMENTO_URL", "https://arrendamento.antaq.gov.br").rstrip("/"),
        perfil_dir=Path(env.get("ARRENDAMENTO_PERFIL") or raiz / "perfil-chrome").expanduser(),
        janela=janela,
        # "chromium" usa o Chromium baixado pelo Playwright (sem channel).
        canal=None if canal in ("", "chromium") else canal,
        login_interativo=_booleano(env.get("ARRENDAMENTO_LOGIN_INTERATIVO"), True),
        pasta_downloads=Path(
            env.get("ARRENDAMENTO_PASTA_DOWNLOADS") or Path.home() / "Downloads" / "Arrendamento"
        ).expanduser(),
        # De onde arrendamento_enviar_arquivo pode ler (ver seguranca.py).
        pastas_envio=tuple(
            Path(p).expanduser()
            for p in env.get("ARRENDAMENTO_PASTAS_ENVIO", "").split(os.pathsep) if p.strip()
        ) or tuple(Path.home() / nome for nome in ("Downloads", "Documents", "Desktop")),
    )
