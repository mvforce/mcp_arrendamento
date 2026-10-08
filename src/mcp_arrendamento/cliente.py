"""Cliente da API do sistema de Arrendamento.

Fala com um `Transporte` (em produção, o Chrome real de transporte.py) e
concentra as regras de segurança das escritas: nada é gravado sem
`confirmar=True`. Sem a confirmação, cada operação devolve uma prévia com o
payload exato, ou com o diff no caso de alteração.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional, Protocol
from urllib.parse import urlencode

from mcp_arrendamento import contratos as regras
from mcp_arrendamento.erros import ErroArrendamento, ErroValidacao
from mcp_arrendamento.subentidades import (
    caminho_registro,
    mesclar_payload,
    montar_payload,
    obter,
)
from mcp_arrendamento.transporte import Resposta, eh_bloqueio_waf, eh_desafio_cloudflare

FILTROS_BUSCA = (
    "cdContrato", "noTipoOutorga", "cdTrigrama", "noFantasiaEmpresa", "possuiDecisaoJudicial",
    "situacaoContrato", "dsAtoAntaq", "nrAto",
)
FILTROS_RELATORIO = ("noTipoOutorga", "cdTrigrama", "situacaoContrato", "possuiDecisaoJudicial")
OPCOES = (
    "tipos-contrato", "licitacoes-previas", "tipos-outorga", "portos", "natureza-carga",
    "tipo-servico", "tipos-licitacao",
)

_AVISO_PREVIA = "Nada foi gravado. Para executar, repita a chamada com confirmar=true."


class Transporte(Protocol):
    async def requisitar(
        self, metodo: str, caminho: str, json: Any = None,
        arquivo: Optional[tuple[str, str, bytes, str]] = None, campos: Optional[dict] = None,
    ) -> Resposta: ...



def _detalhe(resp: Resposta) -> str:
    try:
        corpo = resp.json()
    except ValueError:
        return ""
    if isinstance(corpo, dict):
        for chave in ("detail", "message", "title"):
            if corpo.get(chave):
                return str(corpo[chave])
    return ""


def _erro(resp: Resposta) -> ErroArrendamento:
    if eh_desafio_cloudflare(resp):
        return ErroArrendamento(
            "O Cloudflare desafiou a requisição mesmo dentro do navegador. Rode "
            "`mcp-arrendamento login` para reabrir a sessão com a janela visível.",
            "cloudflare_borda", resp.status,
        )
    if eh_bloqueio_waf(resp):
        return ErroArrendamento(
            "O WAF do Cloudflare barrou o conteúdo enviado, antes de chegar ao sistema. "
            "Nada foi gravado. Alguma regra casou com o texto (no SEI, o gatilho foi "
            "'#' dentro de texto); ajuste o conteúdo ou peça exceção à STI.",
            "cloudflare_waf", resp.status,
        )
    detalhe = _detalhe(resp)
    if resp.status == 401:
        return ErroArrendamento(
            detalhe or "Sessão expirada. Rode `mcp-arrendamento login`.", "sessao", 401
        )
    if resp.status == 403:
        return ErroArrendamento(
            detalhe or "Usuário sem permissão para executar esta ação.", "permissao", 403
        )
    if resp.status == 404:
        return ErroArrendamento(detalhe or "Registro não encontrado.", "nao_encontrado", 404)
    return ErroArrendamento(
        detalhe or f"A API respondeu HTTP {resp.status}.", "api", resp.status
    )


def camel_como_front(chave: str) -> str:
    """Chave PascalCase da API → camelCase, como os normalizadores do front.

    Alguns endpoints (ex.: aditivos por contrato pai) respondem `NRVersao`,
    `IDContratoArrendamento`, `DTcriacao`; os demais já vêm em camelCase.
    """
    maiusculas = re.match(r"^[A-Z]+", chave)
    if not maiusculas:
        return chave
    trecho = maiusculas.group(0)
    if len(trecho) == len(chave):
        return chave.lower()
    if len(trecho) == 1:
        return chave[0].lower() + chave[1:]
    # A última maiúscula da sequência já começa a palavra seguinte.
    return trecho[:-1].lower() + chave[len(trecho) - 1:]


def _normalizar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {camel_como_front(k): _normalizar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_normalizar(v) for v in valor]
    return valor


def _query(parametros: dict) -> str:
    limpos = {k: v for k, v in parametros.items() if v is not None and str(v).strip() != ""}
    # O único filtro sim/não da API (possuiDecisaoJudicial) espera "Sim"/"Nao".
    limpos = {k: (("Sim" if v else "Nao") if isinstance(v, bool) else v) for k, v in limpos.items()}
    return urlencode(limpos, doseq=True)


def _previa(operacao: str, **dados) -> dict:
    return {"executado": False, "operacao": operacao, "aviso": _AVISO_PREVIA, **dados}


def _agora_ms() -> int:
    return int(time.time() * 1000)


class ClienteArrendamento:
    def __init__(self, transporte: Transporte):
        self._t = transporte

    async def _resposta(self, metodo: str, caminho: str, **kw) -> Resposta:
        resp = await self._t.requisitar(metodo, caminho, **kw)
        if not resp.ok:
            raise _erro(resp)
        return resp

    async def _chamar(self, metodo: str, caminho: str, **kw) -> Any:
        resp = await self._resposta(metodo, caminho, **kw)
        return None if resp.status == 204 or not resp.corpo else _normalizar(resp.json())

    # ------------------------------------------------------------------ sessão
    async def me(self) -> dict:
        return (await self._chamar("GET", "/auth/me"))["usuario"]

    # --------------------------------------------------------------- consultas
    async def buscar_contratos(self, pagina: int = 1, tamanho_pagina: int = 20, **filtros) -> dict:
        desconhecidos = sorted(set(filtros) - set(FILTROS_BUSCA))
        if desconhecidos:
            raise ErroValidacao(
                f"Filtro(s) desconhecido(s): {', '.join(desconhecidos)}. Use: {', '.join(FILTROS_BUSCA)}."
            )
        q = _query({"pagina": pagina, "tamanhoPagina": tamanho_pagina, **filtros})
        return await self._chamar("GET", f"/contratos-arrendamento/resumo?{q}")

    async def obter_contrato(self, id_contrato: int) -> dict:
        return await self._chamar("GET", f"/contratos-arrendamento/{id_contrato}")

    async def listar_aditivos(self, id_contrato: int) -> list:
        return await self._chamar("GET", f"/contratos-arrendamento-aditivos/por-contrato-pai/{id_contrato}")

    async def analise_exclusao(self, id_contrato: int) -> dict:
        return await self._chamar("GET", f"/contratos-arrendamento/{id_contrato}/analise-exclusao")

    async def listar_subentidade(self, recurso: str, id_contrato: int) -> list:
        obter(recurso)
        return await self._chamar("GET", f"/{recurso}/por-contrato/{id_contrato}")

    async def listar_arquivos(self, id_contrato: int) -> list:
        return await self._chamar("GET", f"/arquivos/por-contrato/{id_contrato}")

    async def baixar_arquivo(self, id_arquivo: int) -> Resposta:
        return await self._resposta("GET", f"/arquivos/{id_arquivo}/conteudo")

    async def opcoes(self, tipo: str) -> list:
        if tipo not in OPCOES:
            raise ErroValidacao(f"Opção {tipo!r} desconhecida. Use: {', '.join(OPCOES)}.")
        return await self._chamar("GET", f"/contratos-arrendamento-opcoes/{tipo}")

    async def razao_social(self, cnpj: str) -> dict:
        q = _query({"cnpj": "".join(c for c in cnpj if c.isdigit())})
        return await self._chamar("GET", f"/contratos-arrendamento-opcoes/instalacoes-portuarias/razao-social?{q}")

    # -------------------------------------------------------------- relatórios
    async def relatorio_dashboard(self) -> dict:
        return await self._chamar("GET", "/relatorios/contratos-arrendamento/dashboard")

    async def relatorio_vencimentos(self) -> list:
        return await self._chamar("GET", "/relatorios/contratos-arrendamento/vencimentos")

    async def relatorio_lei_12815(self, ano: int, tipos_outorga: Optional[list[str]] = None) -> list:
        q = _query({"ano": ano, "tiposOutorga": [t for t in (tipos_outorga or []) if t.strip()]})
        return await self._chamar("GET", f"/relatorios/contratos-arrendamento/lei-12815?{q}")

    async def relatorio_contratos(self, **filtros) -> list:
        desconhecidos = sorted(set(filtros) - set(FILTROS_RELATORIO))
        if desconhecidos:
            raise ErroValidacao(
                f"Filtro(s) desconhecido(s): {', '.join(desconhecidos)}. Use: {', '.join(FILTROS_RELATORIO)}."
            )
        q = _query(filtros)
        return await self._chamar("GET", "/relatorios/contratos-arrendamento" + (f"?{q}" if q else ""))

    # ------------------------------------------------------ gestão de acessos
    async def listar_usuarios(self) -> list:
        return await self._chamar("GET", "/auth/usuarios")

    async def listar_perfis(self) -> list:
        return await self._chamar("GET", "/auth/perfis")

    async def listar_solicitacoes_acesso(self) -> list:
        return await self._chamar("GET", "/auth/solicitacoes-acesso")

    async def auditoria_login(self) -> list:
        return await self._chamar("GET", "/auth/auditoria-login")

    # ------------------------------------------------------ escrita: contrato
    async def criar_contrato(self, dados: dict, confirmar: bool) -> dict:
        payload = regras.montar_novo_contrato(dados, agora_ms=_agora_ms())
        if not confirmar:
            return _previa("criar_contrato", payload=payload)
        criado = await self._chamar("POST", "/contratos-arrendamento", json=payload)
        return {"executado": True, "contrato": criado}

    async def criar_aditivo(self, id_contrato_pai: int, dados: dict, confirmar: bool) -> dict:
        pai = await self.obter_contrato(id_contrato_pai)
        aditivos = await self.listar_aditivos(id_contrato_pai)
        payload = regras.montar_aditivo(pai, aditivos or [], dados, agora_ms=_agora_ms())
        if not confirmar:
            return _previa("criar_aditivo", payload=payload)
        criado = await self._chamar("POST", "/contratos-arrendamento", json=payload)
        return {"executado": True, "aditivo": criado}

    async def alterar_contrato(self, id_contrato: int, alteracoes: dict, confirmar: bool) -> dict:
        atual = await self.obter_contrato(id_contrato)
        payload = regras.mesclar_contrato(atual, alteracoes)
        diff = regras.diferencas(atual, payload)
        if not diff:
            return {"executado": False, "operacao": "alterar_contrato", "diferencas": {},
                    "aviso": "Nenhum campo muda; nada foi enviado."}
        if not confirmar:
            return _previa("alterar_contrato", diferencas=diff)
        await self._chamar("PUT", f"/contratos-arrendamento/{id_contrato}", json=payload)
        return {"executado": True, "operacao": "alterar_contrato", "diferencas": diff}

    async def excluir_contrato(self, id_contrato: int, remover_dependencias: bool, confirmar: bool) -> dict:
        analise = await self.analise_exclusao(id_contrato)
        if analise.get("possuiAditivos"):
            # O sistema responde 409 mesmo com removerDependencias: aditivos saem antes.
            aditivos = await self.listar_aditivos(id_contrato) or []
            ids = ", ".join(str(a.get("idContratoArrendamento")) for a in aditivos) or "?"
            raise ErroValidacao(
                f"O contrato {id_contrato} tem aditivo(s) vinculado(s) (id {ids}) e o sistema não "
                "permite excluí-lo. Exclua os aditivos antes; remover_dependencias não os inclui."
            )
        dependencias = [d for d in analise.get("dependencias") or [] if d.get("quantidade")]
        if dependencias and not remover_dependencias:
            lista = "; ".join(f"{d['descricao']}: {d['quantidade']}" for d in dependencias)
            raise ErroValidacao(
                f"O contrato {id_contrato} tem registros vinculados ({lista}). "
                "Para excluir junto, use remover_dependencias=true."
            )
        # O removerDependencias do sistema apaga o registro do anexo, mas deixa o arquivo no
        # armazenamento (chave <idContrato>/<nome>); como o id do contrato é reaproveitado, o
        # órfão impede anexar o mesmo nome depois. O DELETE de cada anexo limpa os dois.
        arquivos: list = []
        if remover_dependencias and any(d.get("codigo") == "arquivos" for d in dependencias):
            arquivos = await self.listar_arquivos(id_contrato) or []
        contrato = await self.obter_contrato(id_contrato)
        resumo = {k: contrato.get(k) for k in ("cdContrato", "noFantasiaEmpresa", "noTipoOutorga", "nrVersao")}
        if not confirmar:
            extras = {"arquivos": arquivos} if arquivos else {}
            return _previa("excluir_contrato", contrato=resumo, dependencias=dependencias, **extras)
        for arquivo in arquivos:
            await self._chamar("DELETE", f"/arquivos/{arquivo['idArquivo']}")
        sufixo = "?removerDependencias=true" if remover_dependencias else ""
        await self._chamar("DELETE", f"/contratos-arrendamento/{id_contrato}{sufixo}")
        return {"executado": True, "operacao": "excluir_contrato", "contrato": resumo,
                "dependencias_removidas": dependencias, "arquivos_excluidos": arquivos}

    # ------------------------------------------------ escrita: sub-entidades
    async def _versoes(self, id_contrato: int) -> tuple[dict, list[dict]]:
        """Contrato original e seus aditivos, a partir do id de qualquer versão."""
        contrato = await self.obter_contrato(id_contrato)
        id_pai = contrato.get("idContratoArrendamentoPai")
        original = await self.obter_contrato(id_pai) if id_pai else contrato
        aditivos = await self.listar_aditivos(original["idContratoArrendamento"]) or []
        return original, aditivos

    @staticmethod
    def _mais_recente(original: dict, aditivos: list[dict]) -> dict:
        # Funções go/So do front: o aditivo de maior versão (desempate pelo id); sem aditivo, o original.
        if not aditivos:
            return original
        return max(aditivos, key=lambda a: (a.get("nrVersao") or 0, a.get("idContratoArrendamento") or 0))

    async def _registro(self, recurso: str, id_contrato: int, id_registro: int) -> dict:
        chave = obter(recurso).chave
        ids = [id_contrato]
        if recurso == "contratos-encerrados":
            # O encerramento pode estar em qualquer versão (a tela grava na mais recente).
            original, aditivos = await self._versoes(id_contrato)
            ids = [v["idContratoArrendamento"] for v in [original, *aditivos]]
        for id_versao in ids:
            for registro in await self.listar_subentidade(recurso, id_versao) or []:
                if registro.get(chave) == id_registro:
                    return registro
        raise ErroValidacao(
            f"Não há registro {chave}={id_registro} em {recurso} do contrato {id_contrato}."
        )

    async def _destino_do_encerramento(self, id_contrato: int) -> int:
        """Como a tela: um encerramento por contrato (todas as versões), gravado na mais recente.

        A situação na lista, nos filtros, no relatório e no painel é calculada pela versão
        mais recente; um encerramento gravado em versão anterior é ignorado ali.
        """
        original, aditivos = await self._versoes(id_contrato)
        for versao in [original, *aditivos]:
            if await self.listar_subentidade("contratos-encerrados", versao["idContratoArrendamento"]):
                raise ErroValidacao(
                    f"O contrato {original['idContratoArrendamento']} já tem encerramento cadastrado "
                    f"(na versão {versao['idContratoArrendamento']}). Altere ou exclua o registro existente."
                )
        return self._mais_recente(original, aditivos)["idContratoArrendamento"]

    async def incluir_subentidade(self, recurso: str, id_contrato: int, dados: dict, confirmar: bool) -> dict:
        payload = montar_payload(recurso, id_contrato, dados)
        extras: dict[str, Any] = {}
        if recurso == "contratos-encerrados":
            destino = await self._destino_do_encerramento(id_contrato)
            payload["idContratoArrendamento"] = destino
            if destino != id_contrato:
                extras["observacao"] = (
                    f"Gravado na versão mais recente do contrato (id {destino}), como a tela faz."
                )
        if not confirmar:
            return _previa(f"incluir {recurso}", payload=payload, **extras)
        criado = await self._chamar("POST", f"/{recurso}", json=payload)
        return {"executado": True, "operacao": f"incluir {recurso}", "registro": criado, **extras}

    async def alterar_subentidade(
        self, recurso: str, id_contrato: int, id_registro: int, alteracoes: dict, confirmar: bool
    ) -> dict:
        atual = await self._registro(recurso, id_contrato, id_registro)
        dono = atual.get("idContratoArrendamento") or id_contrato
        antes = mesclar_payload(recurso, dono, atual, {})
        payload = mesclar_payload(recurso, dono, atual, alteracoes)
        diff = {k: {"de": antes[k], "para": v} for k, v in payload.items() if antes.get(k) != v}
        if not diff:
            return {"executado": False, "operacao": f"alterar {recurso}", "diferencas": {},
                    "aviso": "Nenhum campo muda; nada foi enviado."}
        if not confirmar:
            return _previa(f"alterar {recurso}", diferencas=diff)
        await self._chamar("PUT", caminho_registro(recurso, id_contrato, id_registro), json=payload)
        return {"executado": True, "operacao": f"alterar {recurso}", "diferencas": diff}

    async def excluir_subentidade(self, recurso: str, id_contrato: int, id_registro: int, confirmar: bool) -> dict:
        registro = await self._registro(recurso, id_contrato, id_registro)
        if not confirmar:
            return _previa(f"excluir {recurso}", registro=registro)
        await self._chamar("DELETE", caminho_registro(recurso, id_contrato, id_registro))
        return {"executado": True, "operacao": f"excluir {recurso}", "registro": registro}

    # ---------------------------------------------------- escrita: arquivos
    async def enviar_arquivo(
        self, id_contrato: int, nome: str, conteudo: bytes, tipo: str, confirmar: bool
    ) -> dict:
        info = {"idContratoArrendamento": id_contrato, "nome": nome, "bytes": len(conteudo), "tipo": tipo}
        if not confirmar:
            return _previa("enviar_arquivo", arquivo=info)
        criado = await self._chamar(
            "POST", "/arquivos",
            campos={"idContratoArrendamento": str(id_contrato)},
            arquivo=("arquivo", nome, conteudo, tipo),
        )
        return {"executado": True, "operacao": "enviar_arquivo", "arquivo": criado}

    async def excluir_arquivo(self, id_contrato: int, id_arquivo: int, confirmar: bool) -> dict:
        arquivos = await self.listar_arquivos(id_contrato) or []
        alvo = next((a for a in arquivos if a.get("idArquivo") == id_arquivo), None)
        if alvo is None:
            raise ErroValidacao(f"O contrato {id_contrato} não tem o arquivo {id_arquivo}.")
        if not confirmar:
            return _previa("excluir_arquivo", arquivo=alvo)
        await self._chamar("DELETE", f"/arquivos/{id_arquivo}")
        return {"executado": True, "operacao": "excluir_arquivo", "arquivo": alvo}
