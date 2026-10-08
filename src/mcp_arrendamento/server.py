"""Servidor MCP do Sistema de Gestão de Arrendamento Portuário da ANTAQ (stdio)."""

from __future__ import annotations

import logging
import mimetypes
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_arrendamento import contratos as regras
from mcp_arrendamento.cliente import ClienteArrendamento
from mcp_arrendamento.config import carregar_config
from mcp_arrendamento.erros import ErroArrendamento, ErroValidacao
from mcp_arrendamento.navegador import PaginaChrome
from mcp_arrendamento.seguranca import arquivo_para_envio
from mcp_arrendamento.subentidades import SUBENTIDADES
from mcp_arrendamento.transporte import Sessao, decodificar_token

logger = logging.getLogger(__name__)

Recurso = Literal[
    "aspectos-fisicos", "bens", "partes-significativas", "coordenadas", "contratos-processos",
    "decisoes-judiciais", "contratos-encerrados", "investimentos-previstos",
    "investimentos-realizados", "observacoes", "perfis-carga-passageiros",
    "tipos-servicos-contrato", "situacoes-adimplemento",
]
Situacao = Literal["Vigente", "Vigente Decisão Judicial", "Encerrado"]
Opcao = Literal[
    "tipos-contrato", "licitacoes-previas", "tipos-outorga", "portos", "natureza-carga",
    "tipo-servico", "tipos-licitacao",
]

INSTRUCOES = """\
Sistema de Gestão de Arrendamento Portuário da ANTAQ (arrendamento.antaq.gov.br), em PRODUÇÃO.

Consultas: arrendamento_buscar_contratos acha o id_contrato (por número, outorgada, porto,
situação...). arrendamento_consultar_contrato traz o contrato com aditivos e todas as abas.
Relatórios: painel, vencimentos (1 a 90 dias), Lei 12.815 e relatório detalhado.

Escritas: TODA ferramenta de escrita tem confirmar=false por padrão e, assim, só devolve a
prévia (payload ou diff) sem gravar. Mostre a prévia ao usuário e só repita com confirmar=true
depois que ele concordar. Alterações enviam o registro inteiro (o sistema substitui tudo), já
mesclado com o atual: informe apenas os campos que mudam. Use arrendamento_consultar_campos
para saber nomes, obrigatórios e valores aceitos. Datas no formato AAAA-MM-DD.

Abas do contrato (recurso): aspectos-fisicos, bens, partes-significativas, coordenadas,
contratos-processos, decisoes-judiciais, contratos-encerrados, investimentos-previstos,
investimentos-realizados, observacoes, perfis-carga-passageiros, tipos-servicos-contrato,
situacoes-adimplemento. Arquivos têm ferramentas próprias.

Erros vêm com a origem entre colchetes: [validacao] dado recusado antes de enviar;
[permissao] perfil sem acesso; [sessao] login expirado; [acesso] o sistema recusou o
usuário no login (ex.: inativo); [cloudflare_waf] a borda barrou o
conteúdo enviado (nada foi gravado); [api] erro do sistema.
"""

_estado: dict[str, Any] = {}


@asynccontextmanager
async def _ciclo_de_vida(_server: FastMCP):
    try:
        yield {}
    finally:
        sessao = _estado.pop("sessao", None)
        if sessao is not None:
            await sessao.fechar()


mcp = FastMCP("arrendamento-antaq", instructions=INSTRUCOES, lifespan=_ciclo_de_vida, log_level="WARNING")


def _cliente() -> ClienteArrendamento:
    """Cria na primeira chamada: o Chrome só abre quando alguém usa uma ferramenta."""
    if "cliente" not in _estado:
        config = carregar_config()
        pagina = PaginaChrome(config.base_url, config.perfil_dir, janela=config.janela, canal=config.canal)
        sessao = Sessao(pagina, login_interativo=config.login_interativo)
        _estado.update(config=config, sessao=sessao, cliente=ClienteArrendamento(sessao))
    return _estado["cliente"]


async def _executar(operacao: Callable[[ClienteArrendamento], Awaitable[Any]]) -> Any:
    try:
        return await operacao(_cliente())
    except ErroValidacao as e:
        raise ToolError(f"[validacao] {e}") from None
    except ErroArrendamento as e:
        raise ToolError(f"[{e.origem}] {e}") from None


def _lista(itens: Optional[list]) -> dict:
    itens = itens or []
    return {"total": len(itens), "itens": itens}


def _leitura(titulo: str) -> dict:
    return {"title": titulo, "annotations": ToolAnnotations(title=titulo, readOnlyHint=True, openWorldHint=True)}


def _escrita(titulo: str, destrutiva: bool) -> dict:
    return {"title": titulo, "annotations": ToolAnnotations(
        title=titulo, readOnlyHint=False, destructiveHint=destrutiva,
        idempotentHint=True if titulo.startswith("Alterar") else None, openWorldHint=True,
    )}


IdContrato = Annotated[int, Field(description="idContratoArrendamento (vem da busca)")]
Confirmar = Annotated[bool, Field(description="false = só prévia, nada é gravado; true = executa")]


# ================================================================== consultas
@mcp.tool(**_leitura("Sessão no Arrendamento"))
async def arrendamento_sessao() -> dict:
    """Ambiente (produção ou homologação), quem está logado, perfil, permissões e validade do token."""
    async def op(c: ClienteArrendamento):
        usuario = await c.me()
        token = _estado["sessao"].token
        validade = datetime.fromtimestamp(decodificar_token(token)["exp"]).isoformat(timespec="minutes")
        return {"ambiente": _estado["config"].base_url, **usuario, "token_valido_ate": validade}
    return await _executar(op)


@mcp.tool(**_leitura("Buscar contratos"))
async def arrendamento_buscar_contratos(
    numero_contrato: Annotated[Optional[str], Field(description="cdContrato, ex. 4/2026")] = None,
    outorgada: Annotated[Optional[str], Field(description="razão social/nome da empresa (noFantasiaEmpresa)")] = None,
    porto: Annotated[Optional[str], Field(description="trigrama do porto, ex. SSZ (ver opções 'portos')")] = None,
    tipo_outorga: Annotated[Optional[str], Field(description="ex. Arrendamento (ver opções 'tipos-outorga')")] = None,
    situacao: Optional[Situacao] = None,
    possui_decisao_judicial: Optional[bool] = None,
    ato_antaq: Annotated[Optional[str], Field(description="Acórdão ou Resolução")] = None,
    numero_ato: Optional[str] = None,
    pagina: int = 1,
    tamanho_pagina: Annotated[int, Field(ge=1, le=100)] = 20,
) -> dict:
    """Busca paginada de contratos e aditivos. Devolve itens com idContratoArrendamento."""
    filtros = {
        "cdContrato": numero_contrato, "noFantasiaEmpresa": outorgada, "cdTrigrama": porto,
        "noTipoOutorga": tipo_outorga, "situacaoContrato": situacao,
        "possuiDecisaoJudicial": possui_decisao_judicial, "dsAtoAntaq": ato_antaq, "nrAto": numero_ato,
    }
    return await _executar(lambda c: c.buscar_contratos(pagina, tamanho_pagina, **filtros))


@mcp.tool(**_leitura("Consultar contrato"))
async def arrendamento_consultar_contrato(
    id_contrato: IdContrato,
    abas: Annotated[
        Optional[list[Recurso | Literal["arquivos"]]],
        Field(description="Abas a trazer; omita para trazer todas"),
    ] = None,
) -> dict:
    """Contrato completo (46 campos), aditivos e as abas pedidas (todas, por padrão)."""
    async def op(c: ClienteArrendamento):
        resultado: dict[str, Any] = {"contrato": await c.obter_contrato(id_contrato)}
        resultado["aditivos"] = await c.listar_aditivos(id_contrato)
        for aba in abas or [*SUBENTIDADES, "arquivos"]:
            if aba == "arquivos":
                resultado[aba] = await c.listar_arquivos(id_contrato)
            else:
                resultado[aba] = await c.listar_subentidade(aba, id_contrato)
        return resultado
    return await _executar(op)


@mcp.tool(**_leitura("Listar aditivos"))
async def arrendamento_listar_aditivos(id_contrato: IdContrato) -> dict:
    """Aditivos do contrato (cada um é um contrato com idContratoArrendamentoPai)."""
    return _lista(await _executar(lambda c: c.listar_aditivos(id_contrato)))


@mcp.tool(**_leitura("Listar registros de uma aba"))
async def arrendamento_listar_registros(recurso: Recurso, id_contrato: IdContrato) -> dict:
    """Registros de uma aba do contrato (bens, coordenadas, decisões judiciais etc.)."""
    return _lista(await _executar(lambda c: c.listar_subentidade(recurso, id_contrato)))


@mcp.tool(**_leitura("Listar opções"))
async def arrendamento_listar_opcoes(tipo: Opcao) -> dict:
    """Tabelas de domínio: portos (trigramas), tipos de outorga, natureza de carga etc."""
    return _lista(await _executar(lambda c: c.opcoes(tipo)))


@mcp.tool(**_leitura("Consultar razão social por CNPJ"))
async def arrendamento_consultar_cnpj(cnpj: str) -> dict:
    """Razão social de instalação portuária pelo CNPJ (o mesmo preenchimento automático da tela)."""
    return await _executar(lambda c: c.razao_social(cnpj))


@mcp.tool(**_leitura("Consultar campos aceitos"))
async def arrendamento_consultar_campos(recurso: Literal["contrato"] | Recurso) -> dict:
    """Nomes, tipos, obrigatórios e valores aceitos de 'contrato' ou de uma aba. Não acessa a API."""
    if recurso == "contrato":
        return {"recurso": "contrato", "campos": regras.descrever_campos()}
    sub = SUBENTIDADES[recurso]
    return {
        "recurso": recurso,
        "rotulo": sub.rotulo,
        "chave": sub.chave,
        "campos": [
            {"nome": c.nome, "tipo": c.tipo, "obrigatorio": c.obrigatorio,
             "opcoes": list(c.opcoes) or None, "descricao": c.descricao or None}
            for c in sub.campos
        ],
    }


# ================================================================= relatórios
@mcp.tool(**_leitura("Painel de contratos vigentes"))
async def arrendamento_relatorio_painel() -> dict:
    """Total de contratos vigentes por tipo de outorga e por porto."""
    return await _executar(lambda c: c.relatorio_dashboard())


@mcp.tool(**_leitura("Vencimentos próximos"))
async def arrendamento_relatorio_vencimentos() -> dict:
    """Contratos que vencem em 1 a 90 dias, com dias restantes e nível de alerta."""
    return _lista(await _executar(lambda c: c.relatorio_vencimentos()))


@mcp.tool(**_leitura("Relatório Lei 12.815"))
async def arrendamento_relatorio_lei_12815(
    ano: Annotated[int, Field(ge=1900, le=2100)],
    tipos_outorga: Optional[list[str]] = None,
) -> dict:
    """Relatório da Lei nº 12.815 do ano, com filtro opcional de tipos de outorga."""
    return _lista(await _executar(lambda c: c.relatorio_lei_12815(ano, tipos_outorga)))


@mcp.tool(**_leitura("Relatório detalhado de contratos"))
async def arrendamento_relatorio_contratos(
    tipo_outorga: Optional[str] = None,
    porto: Annotated[Optional[str], Field(description="trigrama")] = None,
    situacao: Optional[Situacao] = None,
    possui_decisao_judicial: Optional[bool] = None,
) -> dict:
    """Relatório detalhado (sem paginação), com quantidade de aditivos e decisão judicial."""
    filtros = {"noTipoOutorga": tipo_outorga, "cdTrigrama": porto, "situacaoContrato": situacao,
               "possuiDecisaoJudicial": possui_decisao_judicial}
    return _lista(await _executar(lambda c: c.relatorio_contratos(**filtros)))


# =================================================================== arquivos
@mcp.tool(**_leitura("Listar arquivos do contrato"))
async def arrendamento_listar_arquivos(id_contrato: IdContrato) -> dict:
    """Arquivos anexados ao contrato."""
    return _lista(await _executar(lambda c: c.listar_arquivos(id_contrato)))


def _nome_seguro(nome: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", nome).strip() or "arquivo"


@mcp.tool(**_leitura("Baixar arquivo"))
async def arrendamento_baixar_arquivo(id_contrato: IdContrato, id_arquivo: int) -> dict:
    """Salva o arquivo na pasta de downloads (~/Downloads/Arrendamento) e devolve o caminho."""
    async def op(c: ClienteArrendamento):
        arquivos = await c.listar_arquivos(id_contrato) or []
        alvo = next((a for a in arquivos if a.get("idArquivo") == id_arquivo), None)
        if alvo is None:
            raise ErroValidacao(f"O contrato {id_contrato} não tem o arquivo {id_arquivo}.")
        resp = await c.baixar_arquivo(id_arquivo)
        pasta: Path = _estado["config"].pasta_downloads
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{id_arquivo}-{_nome_seguro(alvo.get('noLink') or 'arquivo')}"
        destino.write_bytes(resp.corpo)
        return {"caminho": str(destino), "bytes": len(resp.corpo),
                "tipo": resp.headers.get("content-type"), "arquivo": alvo}
    return await _executar(op)


@mcp.tool(**_escrita("Enviar arquivo ao contrato", destrutiva=False))
async def arrendamento_enviar_arquivo(
    id_contrato: IdContrato,
    caminho_arquivo: Annotated[str, Field(description="documento local (PDF, Office, imagem) em Downloads, Documentos ou Mesa")],
    confirmar: Confirmar = False,
) -> dict:
    """Anexa ao contrato um documento local. Só lê de pastas permitidas, nunca arquivos ocultos."""
    try:
        caminho = arquivo_para_envio(caminho_arquivo, carregar_config().pastas_envio)
    except ErroValidacao as e:
        raise ToolError(f"[validacao] {e}") from None
    tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"

    async def op(c: ClienteArrendamento):
        resultado = await c.enviar_arquivo(id_contrato, caminho.name, caminho.read_bytes(), tipo, confirmar)
        return {**resultado, "caminho_local": str(caminho)}
    return await _executar(op)


@mcp.tool(**_escrita("Excluir arquivo do contrato", destrutiva=True))
async def arrendamento_excluir_arquivo(id_contrato: IdContrato, id_arquivo: int, confirmar: Confirmar = False) -> dict:
    """Remove um arquivo anexado ao contrato."""
    return await _executar(lambda c: c.excluir_arquivo(id_contrato, id_arquivo, confirmar))


# ========================================================== gestão de acessos
@mcp.tool(**_leitura("Listar usuários"))
async def arrendamento_listar_usuarios() -> dict:
    """Usuários do sistema (exige perfil administrador)."""
    return _lista(await _executar(lambda c: c.listar_usuarios()))


@mcp.tool(**_leitura("Listar perfis de acesso"))
async def arrendamento_listar_perfis() -> dict:
    """Perfis de acesso e suas permissões."""
    return _lista(await _executar(lambda c: c.listar_perfis()))


@mcp.tool(**_leitura("Listar solicitações de acesso"))
async def arrendamento_listar_solicitacoes_acesso() -> dict:
    """Pedidos de acesso aguardando autorização."""
    return _lista(await _executar(lambda c: c.listar_solicitacoes_acesso()))


@mcp.tool(**_leitura("Consultar auditoria de login"))
async def arrendamento_consultar_auditoria_login() -> dict:
    """Registro de logins no sistema."""
    return _lista(await _executar(lambda c: c.auditoria_login()))


# =========================================================== escrita: contrato
@mcp.tool(**_escrita("Criar contrato", destrutiva=False))
async def arrendamento_criar_contrato(
    dados: Annotated[dict[str, Any], Field(description="campos do contrato; ver arrendamento_consultar_campos('contrato')")],
    confirmar: Confirmar = False,
) -> dict:
    """Inclui um contrato de arrendamento. O id é gerado como no front."""
    return await _executar(lambda c: c.criar_contrato(dados, confirmar))


@mcp.tool(**_escrita("Criar aditivo", destrutiva=False))
async def arrendamento_criar_aditivo(
    id_contrato_pai: IdContrato,
    dados: Annotated[dict[str, Any], Field(description="dtAssinaturaAditivo é obrigatória; demais campos sobrescrevem os copiados do contrato pai")],
    confirmar: Confirmar = False,
) -> dict:
    """Inclui um aditivo copiando os campos do contrato pai, com a versão seguinte."""
    return await _executar(lambda c: c.criar_aditivo(id_contrato_pai, dados, confirmar))


@mcp.tool(**_escrita("Alterar contrato", destrutiva=True))
async def arrendamento_alterar_contrato(
    id_contrato: IdContrato,
    alteracoes: Annotated[dict[str, Any], Field(description="só os campos que mudam, ex. {\"mmObjeto\": \"...\"}")],
    confirmar: Confirmar = False,
) -> dict:
    """Altera campos do contrato ou aditivo. Mostra o diff; grava o registro inteiro mesclado."""
    return await _executar(lambda c: c.alterar_contrato(id_contrato, alteracoes, confirmar))


@mcp.tool(**_escrita("Excluir contrato", destrutiva=True))
async def arrendamento_excluir_contrato(
    id_contrato: IdContrato,
    remover_dependencias: Annotated[bool, Field(description="exclui também abas e arquivos vinculados")] = False,
    confirmar: Confirmar = False,
) -> dict:
    """Exclui o contrato. Antes confere as dependências (abas, arquivos, aditivos)."""
    return await _executar(lambda c: c.excluir_contrato(id_contrato, remover_dependencias, confirmar))


# ======================================================= escrita: abas (registros)
@mcp.tool(**_escrita("Incluir registro numa aba", destrutiva=False))
async def arrendamento_incluir_registro(
    recurso: Recurso,
    id_contrato: IdContrato,
    dados: Annotated[dict[str, Any], Field(description="campos da aba; ver arrendamento_consultar_campos")],
    confirmar: Confirmar = False,
) -> dict:
    """Inclui um registro numa aba do contrato (bem, coordenada, observação, decisão judicial...)."""
    return await _executar(lambda c: c.incluir_subentidade(recurso, id_contrato, dados, confirmar))


@mcp.tool(**_escrita("Alterar registro de uma aba", destrutiva=True))
async def arrendamento_alterar_registro(
    recurso: Recurso,
    id_contrato: IdContrato,
    id_registro: Annotated[int, Field(description="a chave do registro (ex. idBem); em tipos-servicos-contrato, o idTipoServico atual")],
    alteracoes: Annotated[dict[str, Any], Field(description="só os campos que mudam")],
    confirmar: Confirmar = False,
) -> dict:
    """Altera um registro de uma aba. Mostra o diff; grava o registro inteiro mesclado."""
    return await _executar(lambda c: c.alterar_subentidade(recurso, id_contrato, id_registro, alteracoes, confirmar))


@mcp.tool(**_escrita("Excluir registro de uma aba", destrutiva=True))
async def arrendamento_excluir_registro(
    recurso: Recurso,
    id_contrato: IdContrato,
    id_registro: int,
    confirmar: Confirmar = False,
) -> dict:
    """Exclui um registro de uma aba do contrato."""
    return await _executar(lambda c: c.excluir_subentidade(recurso, id_contrato, id_registro, confirmar))


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) > 1:
        from mcp_arrendamento import cli

        sys.exit(cli.main(sys.argv[1:]))
    mcp.run(transport="stdio")
