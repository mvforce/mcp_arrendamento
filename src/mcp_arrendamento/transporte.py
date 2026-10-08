"""Transporte HTTP do sistema de Arrendamento.

O domínio arrendamento.antaq.gov.br está atrás de um Managed Challenge do
Cloudflare: curl, httpx e fetch do Node levam 403 na borda, com ou sem token.
Por isso as chamadas não saem de um cliente HTTP. Saem de um `fetch` executado
dentro de um Chrome real, que resolve o desafio sozinho.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from urllib.parse import parse_qs, urlsplit

from mcp_arrendamento.erros import ErroArrendamento


@dataclass
class Resposta:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    corpo: bytes = b""

    def __post_init__(self) -> None:
        self.headers = {k.lower(): v for k, v in self.headers.items()}

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def texto(self) -> str:
        return self.corpo.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.corpo) if self.corpo else None


def decodificar_token(token: str) -> dict:
    """Lê o payload do token do sistema (`base64url(payload).assinatura`).

    Não confere a assinatura; só serve para saber validade e perfil.
    """
    payload = token.split(".")[0]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def segundos_restantes(token: str, agora: Optional[float] = None) -> float:
    try:
        exp = float(decodificar_token(token)["exp"])
    except Exception:
        return 0
    return exp - (time.time() if agora is None else agora)


def extrair_token_da_url(url: str) -> Optional[str]:
    """O callback do login devolve o token no fragmento: `#access_token=...`."""
    fragmento = urlsplit(url).fragment
    valores = parse_qs(fragmento).get("access_token")
    return valores[0] if valores else None


def extrair_erro_da_url(url: str) -> Optional[str]:
    """Quando recusa o usuário, o callback devolve `#error=<mensagem>` no lugar do token."""
    valores = parse_qs(urlsplit(url).fragment).get("error")
    return valores[0] if valores else None


def eh_desafio_cloudflare(resp: Resposta) -> bool:
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if resp.status in (403, 429, 503):
        trecho = resp.texto[:2000].lower()
        return "just a moment" in trecho or "challenges.cloudflare.com" in trecho
    return False


def eh_bloqueio_waf(resp: Resposta) -> bool:
    """403 da borda por regra do WAF (corpo HTML do Cloudflare, sem desafio).

    É o caso "Attention Required" que o mcp-sei encontrou no SEI: a regra
    inspeciona o corpo do POST. Navegador não resolve; só mudar o conteúdo
    ou pedir exceção no WAF.
    """
    if resp.status != 403 or eh_desafio_cloudflare(resp):
        return False
    if "cloudflare" not in resp.headers.get("server", "").lower():
        return False
    return "json" not in resp.headers.get("content-type", "").lower()


class Pagina(Protocol):
    """O que a sessão precisa do navegador (implementado em navegador.py)."""

    async def fetch(
        self, metodo: str, caminho: str, token: str, json: Any = None,
        arquivo: Optional[tuple[str, str, bytes, str]] = None, campos: Optional[dict] = None,
    ) -> Resposta: ...

    async def token_silencioso(self) -> Optional[str]: ...

    async def login_interativo(self) -> Optional[str]: ...

    async def resolver_desafio(self) -> None: ...

    async def fechar(self) -> None: ...


# Renova com folga para uma operação longa não começar com o token no fim.
_MARGEM_RENOVACAO_S = 300


class Sessao:
    """Mantém o token válido e repete a chamada quando a borda ou a API pedem.

    - Sem token, ou perto de expirar: pede um novo pelo SSO silencioso do Entra.
    - 401: renova uma vez e repete.
    - Desafio do Cloudflare: deixa o navegador resolver e repete.
    """

    def __init__(self, pagina: Pagina, login_interativo: bool = True):
        self._pagina = pagina
        self._login_interativo = login_interativo
        self._token: Optional[str] = None
        self._trava = asyncio.Lock()

    @property
    def token(self) -> Optional[str]:
        return self._token

    async def _renovar(self) -> str:
        token = await self._pagina.token_silencioso()
        if not token and self._login_interativo:
            token = await self._pagina.login_interativo()
        if not token:
            raise ErroArrendamento(
                "Sem sessão no sistema de Arrendamento e o login silencioso da Microsoft "
                "não funcionou. Rode `mcp-arrendamento login` no terminal e entre com a "
                "conta institucional.",
                "sessao",
            )
        self._token = token
        return token

    async def _token_valido(self) -> str:
        if self._token and segundos_restantes(self._token) > _MARGEM_RENOVACAO_S:
            return self._token
        return await self._renovar()

    async def garantir_login(self) -> dict:
        async with self._trava:
            return decodificar_token(await self._token_valido())

    async def requisitar(
        self, metodo: str, caminho: str, json: Any = None,
        arquivo: Optional[tuple[str, str, bytes, str]] = None, campos: Optional[dict] = None,
    ) -> Resposta:
        async with self._trava:
            token = await self._token_valido()
            resp = await self._pagina.fetch(metodo, caminho, token, json, arquivo, campos)
            if eh_desafio_cloudflare(resp):
                await self._pagina.resolver_desafio()
                resp = await self._pagina.fetch(metodo, caminho, token, json, arquivo, campos)
            if resp.status == 401:
                token = await self._renovar()
                resp = await self._pagina.fetch(metodo, caminho, token, json, arquivo, campos)
            return resp

    async def fechar(self) -> None:
        await self._pagina.fechar()
