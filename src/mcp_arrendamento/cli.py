"""Comandos de terminal: `mcp-arrendamento login` e `mcp-arrendamento teste`."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from mcp_arrendamento.cliente import ClienteArrendamento
from mcp_arrendamento.config import Config, carregar_config
from mcp_arrendamento.erros import ErroArrendamento
from mcp_arrendamento.navegador import PaginaChrome
from mcp_arrendamento.transporte import Sessao, decodificar_token


def _pagina(config: Config, janela: str) -> PaginaChrome:
    return PaginaChrome(config.base_url, config.perfil_dir, janela=janela, canal=config.canal)


async def login(config: Config) -> int:
    """Abre o Chrome visível para entrar com a conta Microsoft (MFA incluído)."""
    pagina = _pagina(config, janela="visivel")
    try:
        print(f"Abrindo o Chrome em {config.base_url}. Entre com a conta institucional;", flush=True)
        print('quando a Microsoft perguntar "Continuar conectado?", responda Sim.', flush=True)
        try:
            token = await pagina.login_interativo()
        except ErroArrendamento as e:
            print(str(e), file=sys.stderr)
            return 1
        if not token:
            print("Login não concluído (janela fechada ou tempo esgotado).", file=sys.stderr)
            return 1
        usuario = (await pagina.fetch("GET", "/auth/me", token)).json()["usuario"]
        validade = datetime.fromtimestamp(decodificar_token(token)["exp"])
        print(f"OK: {usuario['nome']} ({usuario['perfil']}). Token válido até {validade:%d/%m %H:%M}.")
        return 0
    finally:
        await pagina.fechar()


async def teste(config: Config) -> int:
    """Faz só leituras, do mesmo jeito que o servidor faz (SSO silencioso, sem interação)."""
    sessao = Sessao(_pagina(config, config.janela), login_interativo=False)
    cliente = ClienteArrendamento(sessao)
    try:
        usuario = await cliente.me()
        print(f"sessão: {usuario['nome']} · {usuario['perfil']} · {', '.join(usuario['permissoes'])}")
        painel = await cliente.relatorio_dashboard()
        print(f"dashboard: {painel['totalContratosVigentes']} contratos vigentes")
        busca = await cliente.buscar_contratos(pagina=1, tamanho_pagina=1)
        print(f"busca: {busca['totalRegistros']} contratos no total")
        portos = await cliente.opcoes("portos")
        print(f"opções: {len(portos)} portos")
        return 0
    finally:
        await sessao.fechar()


def main(argv: list[str]) -> int:
    config = carregar_config()
    comandos = {"login": login, "teste": teste}
    if not argv or argv[0] not in comandos:
        print("uso: mcp-arrendamento [login|teste]  (sem argumento: servidor MCP via stdio)", file=sys.stderr)
        return 2
    try:
        return asyncio.run(comandos[argv[0]](config))
    except ErroArrendamento as e:
        print(f"[{e.origem}] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
