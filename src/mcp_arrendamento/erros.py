"""Exceções do servidor, compartilhadas pelo transporte e pelo cliente."""

from __future__ import annotations

from typing import Optional


class ErroValidacao(ValueError):
    """Dado recusado antes de chegar à API."""


class ErroArrendamento(Exception):
    """Erro vindo da borda ou da API. `origem` diz o que fazer a respeito:

    cloudflare_borda · cloudflare_waf · sessao · permissao · nao_encontrado · api
    """

    def __init__(self, mensagem: str, origem: str, status: Optional[int] = None):
        super().__init__(mensagem)
        self.origem = origem
        self.status = status
