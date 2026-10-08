"""Página do Chrome real que a `Sessao` usa (Playwright).

- Chrome instalado (`channel="chrome"`) com perfil próprio e persistente: os
  cookies do Entra ficam no perfil, e o SSO silencioso funciona entre execuções.
- Janela real, minimizada por padrão. Em headless o Cloudflare identifica o
  navegador (`HeadlessChrome` no User-Agent) e exige a caixa "Confirme que é
  humano"; com janela real o desafio passa sozinho, como no uso normal.
- O token vem do redirect do login (`/auth/microsoft/callback#access_token=...`).
- As chamadas são `fetch` de dentro da página, estacionada em `/api/health`
  (mesma origem, sem o JS da SPA, que poderia redirecionar sozinho).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from mcp_arrendamento.erros import ErroArrendamento
from mcp_arrendamento.transporte import Resposta, extrair_erro_da_url, extrair_token_da_url

logger = logging.getLogger(__name__)

_JS_FETCH = r"""
async ([url, method, headers, body]) => {
  const opt = { method, headers };
  if (body !== null) opt.body = body;
  let r;
  try { r = await fetch(url, opt); } catch (e) { return { erroRede: String(e) }; }
  const bytes = new Uint8Array(await r.arrayBuffer());
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  const hdrs = {};
  r.headers.forEach((v, k) => { hdrs[k] = v; });
  return { status: r.status, headers: hdrs, b64: btoa(bin) };
}
"""

_JS_FETCH_MULTIPART = r"""
async ([url, method, headers, campos, campoArquivo, nome, b64, tipo]) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(campos)) fd.append(k, v);
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  fd.append(campoArquivo, new Blob([buf], { type: tipo || 'application/octet-stream' }), nome);
  let r;
  try { r = await fetch(url, { method, headers, body: fd }); } catch (e) { return { erroRede: String(e) }; }
  const bytes = new Uint8Array(await r.arrayBuffer());
  let out = '';
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  const hdrs = {};
  r.headers.forEach((v, k) => { hdrs[k] = v; });
  return { status: r.status, headers: hdrs, b64: btoa(out) };
}
"""

_HOSTS_MICROSOFT = ("login.microsoftonline.com", "login.live.com", "login.microsoft.com")
# O SSO silencioso só passa pela Microsoft; parado lá é porque pede interação.
_PARADO_NA_MICROSOFT_S = 8


class PaginaChrome:
    def __init__(
        self,
        base_url: str,
        perfil_dir: Path,
        janela: str = "minimizada",
        canal: Optional[str] = "chrome",
        timeout_sso_s: float = 40,
        timeout_login_s: float = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self._host = urlsplit(self.base_url).hostname
        self._perfil = Path(perfil_dir).expanduser()
        self._janela = janela
        self._canal = canal or None
        self._timeout_sso = timeout_sso_s
        self._timeout_login = timeout_login_s
        self._pw = None
        self._ctx = None
        self._page = None
        self._token_visto: Optional[str] = None
        self._erro_visto: Optional[str] = None

    # ------------------------------------------------------------ ciclo de vida
    async def _abrir(self, janela: str) -> None:
        from playwright.async_api import async_playwright

        headless = janela == "headless"

        if self._pw is None:
            self._pw = await async_playwright().start()
        self._perfil.mkdir(parents=True, exist_ok=True)
        logger.info("Abrindo Chrome (janela=%s, perfil=%s)", janela, self._perfil)
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self._perfil),
            channel=self._canal,
            headless=headless,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport=None if not headless else {"width": 1280, "height": 800},
        )
        self._ctx.on("close", lambda _: self._descartar())
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        self._page.on("framenavigated", self._ao_navegar)
        if janela == "minimizada":
            await self._estado_janela("minimized")

    async def _estado_janela(self, estado: str) -> None:
        """`minimized` ou `normal`, pelo CDP (só existe com janela real)."""
        try:
            cdp = await self._ctx.new_cdp_session(self._page)
            alvo = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {"windowId": alvo["windowId"], "bounds": {"windowState": estado}},
            )
            await cdp.detach()
        except Exception as e:  # noqa: BLE001 — janela fora do lugar não impede o trabalho
            logger.warning("Não consegui deixar a janela %s: %s", estado, e)

    def _descartar(self) -> None:
        self._ctx = None
        self._page = None

    async def _fechar_contexto(self) -> None:
        if self._ctx is not None:
            ctx = self._ctx
            self._descartar()
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001 — a janela pode já ter sido fechada
                pass

    async def _garantir(self) -> None:
        if self._ctx is None or self._page is None or self._page.is_closed():
            await self._fechar_contexto()
            await self._abrir(self._janela)

    async def fechar(self) -> None:
        await self._fechar_contexto()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    # ------------------------------------------------------------------ login
    def _ao_navegar(self, frame) -> None:
        if self._page is not None and frame == self._page.main_frame:
            token = extrair_token_da_url(frame.url)
            if token:
                self._token_visto = token
            erro = extrair_erro_da_url(frame.url)
            if erro:
                self._erro_visto = erro

    async def _token_da_pagina(self) -> Optional[str]:
        if self._token_visto:
            return self._token_visto
        try:
            if urlsplit(self._page.url).hostname == self._host:
                return await self._page.evaluate("() => sessionStorage.getItem('antaq.accessToken')")
        except Exception:  # noqa: BLE001 — página no meio de uma navegação
            pass
        return None

    async def _aguardar_token(self, timeout_s: float, desistir_na_microsoft: bool) -> Optional[str]:
        limite = time.monotonic() + timeout_s
        na_microsoft_desde: Optional[float] = None
        while time.monotonic() < limite:
            if self._page is None or self._page.is_closed():
                return None  # usuário fechou a janela
            if self._erro_visto:
                raise ErroArrendamento(
                    f"O sistema de Arrendamento ({self.base_url}) recusou o login: {self._erro_visto}",
                    "acesso",
                )
            token = await self._token_da_pagina()
            if token:
                return token
            if urlsplit(self._page.url).hostname in _HOSTS_MICROSOFT:
                na_microsoft_desde = na_microsoft_desde or time.monotonic()
                if desistir_na_microsoft and time.monotonic() - na_microsoft_desde > _PARADO_NA_MICROSOFT_S:
                    return None
            else:
                na_microsoft_desde = None
            await asyncio.sleep(0.5)
        return None

    async def _ir_para_login(self) -> None:
        self._token_visto = None
        self._erro_visto = None
        try:
            await self._page.goto(f"{self.base_url}/api/v1/auth/microsoft/authorize", wait_until="commit")
        except Exception as e:  # noqa: BLE001 — a cadeia de redirects pode interromper o goto
            logger.debug("goto do login interrompido: %s", e)

    async def _estacionar(self) -> None:
        await self._page.goto(f"{self.base_url}/api/health", wait_until="domcontentloaded")
        await self._aguardar_fim_do_desafio()

    async def _aguardar_fim_do_desafio(self, timeout_s: float = 30) -> None:
        limite = time.monotonic() + timeout_s
        while time.monotonic() < limite:
            try:
                titulo = (await self._page.title()).lower()
            except Exception:  # noqa: BLE001
                titulo = ""
            if "just a moment" not in titulo and "um momento" not in titulo:
                return
            await asyncio.sleep(1)
        logger.warning("O desafio do Cloudflare não terminou em %ss", timeout_s)

    async def token_silencioso(self) -> Optional[str]:
        await self._garantir()
        await self._ir_para_login()
        token = await self._aguardar_token(self._timeout_sso, desistir_na_microsoft=True)
        if token:
            await self._estacionar()
        return token

    async def login_interativo(self) -> Optional[str]:
        """Mostra a janela do Chrome para o usuário entrar (MFA incluído)."""
        if self._janela == "headless":
            await self._fechar_contexto()
            await self._abrir("visivel")
        else:
            await self._garantir()
            await self._estado_janela("normal")
        await self._page.bring_to_front()
        await self._ir_para_login()
        try:
            token = await self._aguardar_token(self._timeout_login, desistir_na_microsoft=False)
        finally:
            if self._janela == "headless":
                # Os cookies do Entra ficaram no perfil; volta a trabalhar sem janela.
                await self._fechar_contexto()
                await self._abrir("headless")
            await self._garantir()  # o usuário pode ter fechado a janela
            if self._janela == "minimizada":
                await self._estado_janela("minimized")
        if token:
            await self._estacionar()
        return token

    async def resolver_desafio(self) -> None:
        await self._garantir()
        await self._estacionar()

    # ----------------------------------------------------------------- fetch
    async def fetch(
        self, metodo: str, caminho: str, token: str, json: Any = None,
        arquivo: Optional[tuple[str, str, bytes, str]] = None, campos: Optional[dict] = None,
    ) -> Resposta:
        await self._garantir()
        if urlsplit(self._page.url).hostname != self._host:
            await self._estacionar()
        url = f"{self.base_url}/api{caminho}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if arquivo is not None:
            campo, nome, conteudo, tipo = arquivo
            resultado = await self._page.evaluate(
                _JS_FETCH_MULTIPART,
                [url, metodo, headers, campos or {}, campo, nome, base64.b64encode(conteudo).decode(), tipo],
            )
        else:
            corpo = None
            if json is not None:
                import json as _json

                corpo = _json.dumps(json, ensure_ascii=False)
                headers["Content-Type"] = "application/json"
            resultado = await self._page.evaluate(_JS_FETCH, [url, metodo, headers, corpo])
        if "erroRede" in resultado:
            raise ConnectionError(f"Falha de rede no fetch do navegador: {resultado['erroRede']}")
        return Resposta(
            int(resultado["status"]),
            resultado.get("headers") or {},
            base64.b64decode(resultado.get("b64") or ""),
        )
