"""Modo HTTP local: o servidor MCP em http://127.0.0.1:<porta>/mcp (Streamable HTTP).

Serve a clientes MCP que falam HTTP na mesma máquina, como o Agente de IA do
SEI Pro. Não é para expor na rede: escuta só em 127.0.0.1 e exige um token,
porque qualquer programa ou página aberta na máquina alcança o localhost.
"""

from __future__ import annotations

import hmac
import os
import secrets
import sys
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs

PORTA_PADRAO = 8765
_HOSTS_LOCAIS = ("127.0.0.1", "localhost")
_TAMANHO_MINIMO = 32


def carregar_token(arquivo: Path, env: Mapping[str, str] = os.environ) -> str:
    """Token do modo HTTP: da variável de ambiente, ou criado uma vez em disco (0600)."""
    do_ambiente = env.get("ARRENDAMENTO_TOKEN_HTTP", "").strip()
    if do_ambiente:
        if len(do_ambiente) < _TAMANHO_MINIMO:
            raise ValueError(f"ARRENDAMENTO_TOKEN_HTTP precisa ter ao menos {_TAMANHO_MINIMO} caracteres.")
        return do_ambiente
    if arquivo.exists():
        guardado = arquivo.read_text().strip()
        # Arquivo vazio ou truncado (queda no meio da gravação) não pode virar token vazio:
        # um token vazio casaria com um pedido sem cabeçalho.
        if len(guardado) >= _TAMANHO_MINIMO:
            return guardado
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    temporario = arquivo.with_name(arquivo.name + ".novo")
    temporario.touch(mode=0o600)
    temporario.chmod(0o600)
    temporario.write_text(token)
    temporario.replace(arquivo)  # troca atômica: nunca fica um arquivo pela metade
    return token


def prova_de_identidade(token: str, desafio: str, porta: int) -> str:
    """HMAC do desafio com o token: prova que o servidor conhece o token sem mostrá-lo.

    A porta entra na conta para a prova de um servidor não servir a outro: um programa na
    porta A não consegue se passar pelo MCP repassando o desafio a um MCP na porta B.
    """
    return hmac.new(token.encode(), f"{porta}:{desafio}".encode(), "sha256").hexdigest()


class Porteiro:
    """Só deixa passar pedido feito a um host local e com o token certo."""

    def __init__(self, app, token: str, hosts: tuple[str, ...] = _HOSTS_LOCAIS):
        if len(token) < _TAMANHO_MINIMO:
            raise ValueError("token do modo HTTP ausente ou curto demais")
        self._app = app
        self._token = token
        self._hosts = hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self._app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        # Contra DNS rebinding: um domínio externo apontado para 127.0.0.1 chega com outro Host.
        if headers.get("host", "").rsplit(":", 1)[0].lower() not in getattr(self, "_hosts", _HOSTS_LOCAIS):
            return await self._recusar(send, 403, "host não permitido")
        if scope.get("path") == "/identidade":
            # Sem token: o lançador usa para saber se quem ocupa a porta é mesmo este servidor.
            desafio = parse_qs(scope.get("query_string", b"").decode()).get("desafio", [""])[0][:128]
            porta = (scope.get("server") or ("", 0))[1]  # a porta em que ESTE servidor escuta
            return await self._recusar(send, 200, prova_de_identidade(self._token, desafio, porta))
        recebido = headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not recebido or not self._token or not hmac.compare_digest(recebido, self._token):
            return await self._recusar(send, 401, "token ausente ou inválido")
        return await self._app(scope, receive, send)

    @staticmethod
    async def _recusar(send, status: int, motivo: str) -> None:
        corpo = motivo.encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": corpo})


def servir(mcp, anunciar: bool = True) -> None:
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    porta = int(os.environ.get("ARRENDAMENTO_PORTA", PORTA_PADRAO))
    arquivo = Path.home() / ".mcp-arrendamento" / "token-http"
    token = carregar_token(arquivo)
    # A checagem de Host e o token ficam no Porteiro; a de Origin do SDK recusaria
    # a origem chrome-extension:// da extensão.
    mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    extras = tuple(h.strip().lower() for h in os.environ.get("ARRENDAMENTO_HOSTS_HTTP", "").split(",") if h.strip())
    app = Porteiro(mcp.streamable_http_app(), token, _HOSTS_LOCAIS + extras)
    if anunciar:
        print(f"MCP Arrendamento em http://127.0.0.1:{porta}/mcp", file=sys.stderr)
        print(f"Cabeçalho do conector: Authorization: Bearer <token de {arquivo}>", file=sys.stderr)
    uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
