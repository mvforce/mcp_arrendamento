"""Bateria de ponta a ponta em HOMOLOGAÇÃO, pelo protocolo MCP, incluindo escritas.

Cria um contrato de teste (MCP-TESTE/<data-hora>), exercita todas as ferramentas
(prévia → nada gravado → confirmação → releitura) e apaga tudo no fim, mesmo se
algo falhar no meio. Recusa rodar se o servidor não estiver em homologação.

Requer a VPN da ANTAQ e um login prévio no perfil de homologação:

    ARRENDAMENTO_URL=https://hmg-arrendamento.antaq.gov.br \\
    ARRENDAMENTO_PERFIL=~/.mcp-arrendamento/perfil-hmg \\
    PYTHONPATH=src .venv/bin/python -m mcp_arrendamento login

Uso:  .venv/bin/python scripts/bateria_hmg.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parent.parent
HMG = "https://hmg-arrendamento.antaq.gov.br"
CNPJ = "04903587000108"  # da própria ANTAQ
_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Valor que a API devolve quando o informado é convertido no envio.
ESPERADO_ESPECIAL = {("coordenadas", "vlLongitudeCardial"): "O"}

PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


class Falha(Exception):
    pass


class Bateria:
    def __init__(self, sessao: ClientSession):
        self.s = sessao
        self.ok = 0
        self.falhas: list[str] = []

    async def chamar(self, nome: str, **args):
        r = await self.s.call_tool(nome, args)
        texto = r.content[0].text if r.content else ""
        try:
            dados = json.loads(texto)
        except ValueError:
            dados = texto
        return r.isError, dados

    async def sucesso(self, nome: str, **args):
        erro, dados = await self.chamar(nome, **args)
        if erro:
            raise Falha(f"{nome} falhou: {dados}")
        return dados

    async def recusa(self, nome: str, **args) -> str:
        erro, dados = await self.chamar(nome, **args)
        if not erro:
            raise Falha(f"{nome} deveria ter sido recusado e passou: {dados}")
        return str(dados)

    def checar(self, descricao: str, condicao: bool, detalhe: object = "") -> None:
        if condicao:
            self.ok += 1
            print(f"  ok     {descricao}", flush=True)
        else:
            self.falhas.append(f"{descricao} {detalhe}".strip())
            print(f"  FALHA  {descricao} {detalhe}", flush=True)

    async def listar(self, recurso: str, id_contrato: int) -> list:
        return (await self.sucesso("arrendamento_listar_registros", recurso=recurso, id_contrato=id_contrato))["itens"]

    async def contrato(self, id_contrato: int) -> dict:
        return (await self.sucesso("arrendamento_consultar_contrato", id_contrato=id_contrato, abas=[]))["contrato"]


def igual(gravado, esperado) -> bool:
    if isinstance(esperado, str) and _DIA.match(esperado):
        return isinstance(gravado, str) and gravado[:10] == esperado
    if isinstance(esperado, (int, float)) and not isinstance(esperado, bool):
        return gravado is not None and abs(float(gravado) - float(esperado)) < 1e-6
    return gravado == esperado


def conferir_campos(b: Bateria, recurso: str, registro: dict, dados: dict, etapa: str) -> None:
    divergentes = {
        k: (registro.get(k), ESPERADO_ESPECIAL.get((recurso, k), v))
        for k, v in dados.items()
        if not igual(registro.get(k), ESPERADO_ESPECIAL.get((recurso, k), v))
    }
    b.checar(f"{recurso}: {etapa} gravou os valores enviados", not divergentes, divergentes)


# ---------------------------------------------------------------- contrato
async def criar_contrato(b: Bateria, opcoes: dict, cd: str) -> int:
    print("\n[contrato] criar", flush=True)
    dados = {
        "cdContrato": cd,
        "noNomeInstrumento": "Contrato de Arrendamento",
        "tpContrato": opcoes["tipos-contrato"][0]["valor"],
        "stLicitacaoPrevia": opcoes["licitacoes-previas"][0]["valor"],
        "noTipoOutorga": 1,  # código da opção: a tela grava "Arrendamento"
        "cdTrigrama": opcoes["portos"][0]["cdTrigrama"],
        "nrCnpj": "04.903.587/0001-08",
        "noFantasiaEmpresa": "MCP TESTE ARRENDATARIA (BATERIA DE HOMOLOGACAO)",
        "nrcnpjInstalacao": CNPJ,
        "noInstalacao": "MCP TESTE INSTALACAO PORTUARIA",
        "nrPrazoContrato": 25, "nrPrazoContratoMeses": 0, "nrPrazoContratoDias": 0,
        "dtAssinatura": "2026-10-01", "dtOperacao": "2026-10-02", "dtFimContrato": "2051-10-01",
        "stContrato": "A", "noRenovacao": "Sim", "dsExercida": "Não",
        "mmObjeto": "Contrato de teste criado pela bateria do MCP. Pode excluir.",
    }
    previa = await b.sucesso("arrendamento_criar_contrato", dados=dados)
    b.checar("prévia não grava (executado=false)", previa["executado"] is False)
    b.checar("prévia traz o payload com os 46 campos", len(previa["payload"]) == 46, len(previa["payload"]))
    busca = await b.sucesso("arrendamento_buscar_contratos", numero_contrato=cd)
    b.checar("nada gravado depois da prévia", busca["totalRegistros"] == 0, busca["totalRegistros"])

    criado = await b.sucesso("arrendamento_criar_contrato", dados=dados, confirmar=True)
    b.checar("confirmação executa", criado["executado"] is True)
    busca = await b.sucesso("arrendamento_buscar_contratos", numero_contrato=cd)
    b.checar("contrato aparece na busca", busca["totalRegistros"] == 1, busca["totalRegistros"])
    if not busca["itens"]:
        raise Falha("contrato criado não foi encontrado; interrompendo")
    id_ = busca["itens"][0]["idContratoArrendamento"]
    retorno = criado.get("contrato")
    print(f"         id={id_} · resposta do POST: {type(retorno).__name__} "
          f"{sorted(retorno)[:6] if isinstance(retorno, dict) else retorno!r}", flush=True)

    c = await b.contrato(id_)
    esperado = {
        "cdContrato": cd, "noFantasiaEmpresa": dados["noFantasiaEmpresa"], "nrCnpj": CNPJ,
        "noTipoOutorga": "Arrendamento", "stContrato": 1, "dtAssinatura": "2026-10-01",
        "dtOperacao": "2026-10-02", "dtFimContrato": "2051-10-01", "nrPrazoContrato": 25,
        "nrVersao": 1, "idContratoArrendamentoPai": None,
    }
    divergentes = {k: (c.get(k), v) for k, v in esperado.items() if not igual(c.get(k), v)}
    b.checar("campos gravados conferem (datas, CNPJ, outorga, ostensividade)", not divergentes, divergentes)
    return id_


async def alterar_contrato(b: Bateria, id_: int) -> None:
    print("\n[contrato] alterar", flush=True)
    antes = await b.contrato(id_)
    novo = antes["mmObjeto"] + " (alterado pela bateria)"
    previa = await b.sucesso("arrendamento_alterar_contrato", id_contrato=id_, alteracoes={"mmObjeto": novo})
    b.checar("prévia mostra só o campo alterado", list(previa.get("diferencas", {})) == ["mmObjeto"], previa.get("diferencas"))
    b.checar("prévia não grava", (await b.contrato(id_))["mmObjeto"] == antes["mmObjeto"])
    feito = await b.sucesso("arrendamento_alterar_contrato", id_contrato=id_, alteracoes={"mmObjeto": novo}, confirmar=True)
    b.checar("confirmação executa", feito["executado"] is True)
    depois = await b.contrato(id_)
    b.checar("campo alterado gravado", depois["mmObjeto"] == novo)
    mudaram = {k: (antes[k], depois.get(k)) for k in antes if k != "mmObjeto" and antes[k] != depois.get(k)}
    b.checar("os outros 45 campos ficaram intactos (inclusive datas)", not mudaram, mudaram)
    repetido = await b.sucesso("arrendamento_alterar_contrato", id_contrato=id_, alteracoes={"mmObjeto": novo}, confirmar=True)
    b.checar("alteração sem diferença não envia nada", repetido["executado"] is False)


async def aditivo(b: Bateria, id_: int, cd: str) -> int:
    print("\n[aditivo] criar e alterar", flush=True)
    previa = await b.sucesso("arrendamento_criar_aditivo", id_contrato_pai=id_, dados={"dtAssinaturaAditivo": "2026-10-05"})
    p = previa["payload"]
    b.checar("prévia: versão 2, pai e número herdados", (p["nrVersao"], p["idContratoArrendamentoPai"], p["cdContrato"]) == (2, id_, cd), (p["nrVersao"], p["idContratoArrendamentoPai"], p["cdContrato"]))
    sem = await b.sucesso("arrendamento_listar_aditivos", id_contrato=id_)
    b.checar("nada gravado depois da prévia", sem["total"] == 0, sem["total"])
    await b.sucesso("arrendamento_criar_aditivo", id_contrato_pai=id_, dados={"dtAssinaturaAditivo": "2026-10-05"}, confirmar=True)
    ads = await b.sucesso("arrendamento_listar_aditivos", id_contrato=id_)
    b.checar("aditivo listado com versão 2", ads["total"] == 1 and ads["itens"][0]["nrVersao"] == 2, ads)
    id_ad = ads["itens"][0]["idContratoArrendamento"]
    ad = await b.contrato(id_ad)
    b.checar("aditivo: data de assinatura do aditivo gravada", igual(ad.get("dtAssinaturaAditivo"), "2026-10-05"), ad.get("dtAssinaturaAditivo"))
    await b.sucesso("arrendamento_alterar_contrato", id_contrato=id_ad, alteracoes={"mmObjeto": "Aditivo alterado pela bateria"}, confirmar=True)
    b.checar("aditivo alterado", (await b.contrato(id_ad))["mmObjeto"] == "Aditivo alterado pela bateria")
    return id_ad


# -------------------------------------------------------------------- abas
async def ciclo_aba(b: Bateria, id_: int, recurso: str, dados: dict, alteracao: dict, excluir: bool = True) -> int:
    print(f"\n[aba] {recurso}", flush=True)
    chave = (await b.sucesso("arrendamento_consultar_campos", recurso=recurso))["chave"]
    antes = await b.listar(recurso, id_)
    previa = await b.sucesso("arrendamento_incluir_registro", recurso=recurso, id_contrato=id_, dados=dados)
    b.checar(f"{recurso}: prévia de inclusão não grava", previa["executado"] is False and len(await b.listar(recurso, id_)) == len(antes))
    await b.sucesso("arrendamento_incluir_registro", recurso=recurso, id_contrato=id_, dados=dados, confirmar=True)
    lista = await b.listar(recurso, id_)
    ids_antes = {r[chave] for r in antes}
    novos = [r for r in lista if r[chave] not in ids_antes]
    b.checar(f"{recurso}: incluído", len(novos) == 1, len(novos))
    if not novos:
        raise Falha(f"{recurso}: registro incluído não apareceu")
    registro = novos[0]
    id_reg = registro[chave]
    conferir_campos(b, recurso, registro, dados, "inclusão")

    previa = await b.sucesso("arrendamento_alterar_registro", recurso=recurso, id_contrato=id_, id_registro=id_reg, alteracoes=alteracao)
    b.checar(f"{recurso}: prévia de alteração mostra o diff", previa["executado"] is False and set(previa["diferencas"]) == set(alteracao), previa.get("diferencas"))
    await b.sucesso("arrendamento_alterar_registro", recurso=recurso, id_contrato=id_, id_registro=id_reg, alteracoes=alteracao, confirmar=True)
    id_atual = alteracao.get(chave, id_reg)  # tipos-servicos: a chave é o próprio tipo
    atual = next((r for r in await b.listar(recurso, id_) if r[chave] == id_atual), None)
    b.checar(f"{recurso}: alteração gravada", atual is not None)
    if atual is not None:
        conferir_campos(b, recurso, atual, {**dados, **alteracao}, "alteração")
    if excluir:
        await excluir_aba(b, id_, recurso, chave, id_atual)
    return id_atual


async def excluir_aba(b: Bateria, id_: int, recurso: str, chave: str, id_reg: int) -> None:
    previa = await b.sucesso("arrendamento_excluir_registro", recurso=recurso, id_contrato=id_, id_registro=id_reg)
    ainda = any(r[chave] == id_reg for r in await b.listar(recurso, id_))
    b.checar(f"{recurso}: prévia de exclusão não apaga", previa["executado"] is False and ainda)
    await b.sucesso("arrendamento_excluir_registro", recurso=recurso, id_contrato=id_, id_registro=id_reg, confirmar=True)
    sumiu = not any(r[chave] == id_reg for r in await b.listar(recurso, id_))
    b.checar(f"{recurso}: excluído", sumiu)


async def abas(b: Bateria, id_: int, id_ad: int, opcoes: dict) -> None:
    naturezas = [o["idNaturezaCarga"] for o in opcoes["natureza-carga"]]
    servicos = [o["idTipoServico"] for o in opcoes["tipo-servico"]]

    id_aspecto = await ciclo_aba(b, id_, "aspectos-fisicos",
        {"vlAreaTotal": 1000, "vlExtencaoLinhaCais": 200.5, "vlAreaAmpliacao": 0}, {"vlAreaTotal": 1500}, excluir=False)
    await ciclo_aba(b, id_, "coordenadas", {
        "idAspectoFisico": id_aspecto, "dsPonto": "P1", "vlLatitude": 23, "vlMinLatitude": 58,
        "vlSecLatitude": 12.5, "vlLatitudeCardial": "S", "vlLongitude": 46, "vlMinLongitude": 18,
        "vlSecLongitude": 30.2, "vlLongitudeCardial": "W",
    }, {"dsPonto": "P1 alterado"})
    await excluir_aba(b, id_, "aspectos-fisicos", "idAspectoFisico", id_aspecto)

    casos = [
        ("bens", {"dsBem": "Guindaste de teste", "noClassificacao": "Equipamento", "stReversivel": "Sim",
                  "noOrigem": "Arrendatario", "nrVidaUtil": 10, "vlBem": 12345.67}, {"vlBem": 20000}),
        ("partes-significativas", {"noClausula": "Cláusula 1", "noParagrafo": "Parágrafo único",
                                   "dsParagrafo": "Texto de teste"}, {"dsParagrafo": "Texto alterado"}),
        ("contratos-processos", {"nrProcesso": "50300.000001/2026-01", "dsAtoAntaq": "Resolução",
                                 "nrAto": "123", "dtAto": "2026-10-01"}, {"nrAto": "456"}),
        ("decisoes-judiciais", {"dsOrigemDecisao": "TRF1", "nrProcessoJudicial": "0000001-00.2026.4.01.3400",
                                "dsTeorDecisao": "Teor de teste", "dsCondicaoEfeito": "Condição de teste",
                                "dtDecisaoJudicial": "2026-10-01", "dtInicioEfeito": "2026-10-02",
                                "dtFimEfeito": "2027-10-01", "idSituacaoDecisaoJudicial": 0},
         {"idSituacaoDecisaoJudicial": 1}),
        ("investimentos-previstos", {"dsInvestimentoPrevisto": "Dragagem de teste", "vlInvestimentoPrevisto": 1000000,
                                     "dtInvestimentoPrevisto": "2027-01-01"}, {"vlInvestimentoPrevisto": 1500000}),
        ("investimentos-realizados", {"dsInvestimentoRealizado": "Pavimentação de teste",
                                      "vlInvestimentoRealizado": 250000.5, "dtInvestimentoRealizado": "2026-09-01"},
         {"dsInvestimentoRealizado": "Pavimentação alterada"}),
        ("observacoes", {"noResponsavel": "Bateria MCP", "dsObservacao": "Observação de teste",
                         "dtObservacao": "2026-10-07"}, {"dsObservacao": "Observação alterada"}),
        ("perfis-carga-passageiros", {"idNaturezaCarga": naturezas[0]}, {"idNaturezaCarga": naturezas[1]}),
        ("tipos-servicos-contrato", {"idTipoServico": servicos[0]}, {"idTipoServico": servicos[1]}),
        ("situacoes-adimplemento", {"stAdimplemento": 1, "dtAdimplemento": "2026-10-01",
                                    "dsObservacao": "Adimplente"}, {"stAdimplemento": 2}),
    ]
    for recurso, dados, alteracao in casos:
        try:
            await ciclo_aba(b, id_, recurso, dados, alteracao)
        except Falha as e:
            b.checar(f"{recurso}: ciclo completo", False, e)

    await encerramento(b, id_, id_ad)


async def situacao(b: Bateria, id_: int) -> str:
    cd = (await b.contrato(id_))["cdContrato"]
    itens = (await b.sucesso("arrendamento_buscar_contratos", numero_contrato=cd))["itens"]
    return itens[0]["situacaoContrato"] if itens else "?"


async def encerramento(b: Bateria, id_: int, id_ad: int) -> None:
    """Um por contrato, gravado na versão mais recente (o aditivo), como a tela faz."""
    print("\n[aba] contratos-encerrados (contrato com aditivo)", flush=True)
    recurso = "contratos-encerrados"
    dados = {"dtFinalizacaoContrato": "2026-10-07", "dsMotivo": "Encerramento de teste"}
    b.checar("situação antes do encerramento é Vigente", await situacao(b, id_) == "Vigente")
    previa = await b.sucesso("arrendamento_incluir_registro", recurso=recurso, id_contrato=id_, dados=dados)
    b.checar("prévia aponta o aditivo (versão mais recente) como destino",
             previa["payload"]["idContratoArrendamento"] == id_ad, previa["payload"])
    await b.sucesso("arrendamento_incluir_registro", recurso=recurso, id_contrato=id_, dados=dados, confirmar=True)
    no_aditivo, no_original = await b.listar(recurso, id_ad), await b.listar(recurso, id_)
    b.checar("encerramento gravado no aditivo, não no original", len(no_aditivo) == 1 and not no_original,
             (len(no_aditivo), len(no_original)))
    b.checar("situação na lista passa a Encerrado", await situacao(b, id_) == "Encerrado", await situacao(b, id_))
    msg = await b.recusa("arrendamento_incluir_registro", recurso=recurso, id_contrato=id_, dados=dados)
    b.checar("segundo encerramento recusado antes de enviar", "[validacao]" in msg, msg)
    id_enc = no_aditivo[0]["idContratoEncerrado"]
    await b.sucesso("arrendamento_alterar_registro", recurso=recurso, id_contrato=id_, id_registro=id_enc,
                    alteracoes={"dsMotivo": "Motivo alterado"}, confirmar=True)
    b.checar("alteração pelo id do original acha o registro no aditivo",
             (await b.listar(recurso, id_ad))[0]["dsMotivo"] == "Motivo alterado")
    previa = await b.sucesso("arrendamento_excluir_registro", recurso=recurso, id_contrato=id_, id_registro=id_enc)
    b.checar("prévia de exclusão não apaga", previa["executado"] is False and len(await b.listar(recurso, id_ad)) == 1)
    await b.sucesso("arrendamento_excluir_registro", recurso=recurso, id_contrato=id_, id_registro=id_enc, confirmar=True)
    b.checar("encerramento excluído", not await b.listar(recurso, id_ad))
    b.checar("situação volta a Vigente", await situacao(b, id_) == "Vigente")


# ---------------------------------------------------------------- arquivos
async def arquivos(b: Bateria, id_: int, pasta: Path, marca: str) -> None:
    print("\n[arquivos]", flush=True)
    # Nome único: o sistema reaproveita ids de contrato e o armazenamento guarda <idContrato>/<nome>.
    caminho = pasta / f"teste-bateria-mcp-{marca}.pdf"
    caminho.write_bytes(PDF)
    previa = await b.sucesso("arrendamento_enviar_arquivo", id_contrato=id_, caminho_arquivo=str(caminho))
    vazio = await b.sucesso("arrendamento_listar_arquivos", id_contrato=id_)
    b.checar("prévia de envio não grava", previa["executado"] is False and vazio["total"] == 0)
    await b.sucesso("arrendamento_enviar_arquivo", id_contrato=id_, caminho_arquivo=str(caminho), confirmar=True)
    lista = await b.sucesso("arrendamento_listar_arquivos", id_contrato=id_)
    b.checar("arquivo listado", lista["total"] == 1, lista)
    id_arq = lista["itens"][0]["idArquivo"]
    baixado = await b.sucesso("arrendamento_baixar_arquivo", id_contrato=id_, id_arquivo=id_arq)
    conteudo = Path(baixado["caminho"]).read_bytes()
    b.checar("download devolve os mesmos bytes enviados", conteudo == PDF, (len(conteudo), len(PDF)))
    Path(baixado["caminho"]).unlink(missing_ok=True)
    previa = await b.sucesso("arrendamento_excluir_arquivo", id_contrato=id_, id_arquivo=id_arq)
    b.checar("prévia de exclusão não apaga", previa["executado"] is False)
    await b.sucesso("arrendamento_excluir_arquivo", id_contrato=id_, id_arquivo=id_arq, confirmar=True)
    b.checar("arquivo excluído", (await b.sucesso("arrendamento_listar_arquivos", id_contrato=id_))["total"] == 0)


# ------------------------------------------------------------- validações
async def validacoes(b: Bateria, id_: int) -> None:
    print("\n[validações sem gravar]", flush=True)
    msg = await b.recusa("arrendamento_incluir_registro", recurso="bens", id_contrato=id_,
                         dados={"dsBem": "x", "noClassificacao": "Navio", "stReversivel": "Sim", "noOrigem": "Arrendatario"})
    b.checar("opção inválida recusada", "[validacao]" in msg and "Equipamento" in msg, msg)
    msg = await b.recusa("arrendamento_alterar_contrato", id_contrato=id_, alteracoes={"mmObjecto": "x"}, confirmar=True)
    b.checar("campo desconhecido recusado", "[validacao]" in msg and "mmObjecto" in msg, msg)
    msg = await b.recusa("arrendamento_excluir_registro", recurso="observacoes", id_contrato=id_, id_registro=999999999, confirmar=True)
    b.checar("registro inexistente recusado", "[validacao]" in msg, msg)
    msg = await b.recusa("arrendamento_enviar_arquivo", id_contrato=id_,
                         caminho_arquivo=str(Path.home() / ".ssh" / "id_ed25519"), confirmar=True)
    b.checar("anexo fora das pastas permitidas recusado", "[validacao]" in msg, msg)


# ---------------------------------------------------------------- exclusão
async def exclusao(b: Bateria, id_: int, id_ad: int, cd: str, pasta: Path, marca: str) -> None:
    print("\n[exclusão com dependências]", flush=True)
    await b.sucesso("arrendamento_incluir_registro", recurso="observacoes", id_contrato=id_, confirmar=True,
                    dados={"noResponsavel": "Bateria MCP", "dsObservacao": "Fica para a exclusão", "dtObservacao": "2026-10-07"})
    await b.sucesso("arrendamento_incluir_registro", recurso="bens", id_contrato=id_, confirmar=True,
                    dados={"dsBem": "Bem para a exclusão", "noClassificacao": "Imóvel", "stReversivel": "Não", "noOrigem": "Autoridade Portuária"})
    caminho = pasta / f"dependencia-{marca}.pdf"
    caminho.write_bytes(PDF)
    await b.sucesso("arrendamento_enviar_arquivo", id_contrato=id_, caminho_arquivo=str(caminho), confirmar=True)

    msg = await b.recusa("arrendamento_excluir_contrato", id_contrato=id_, remover_dependencias=True, confirmar=True)
    b.checar("contrato com aditivo recusado antes de enviar (o sistema daria 409)",
             "[validacao]" in msg and str(id_ad) in msg, msg)
    previa = await b.sucesso("arrendamento_excluir_contrato", id_contrato=id_ad)
    b.checar("aditivo: prévia de exclusão não apaga", previa["executado"] is False)
    await b.sucesso("arrendamento_excluir_contrato", id_contrato=id_ad, confirmar=True)
    b.checar("aditivo excluído", (await b.sucesso("arrendamento_listar_aditivos", id_contrato=id_))["total"] == 0)

    msg = await b.recusa("arrendamento_excluir_contrato", id_contrato=id_, confirmar=True)
    b.checar("contrato com dependências exige remover_dependencias", "[validacao]" in msg and "remover_dependencias" in msg, msg)
    previa = await b.sucesso("arrendamento_excluir_contrato", id_contrato=id_, remover_dependencias=True)
    b.checar("prévia lista as dependências e não apaga", previa["executado"] is False and len(previa["dependencias"]) >= 3, previa.get("dependencias"))
    b.checar("prévia lista o anexo que será apagado individualmente", len(previa.get("arquivos", [])) == 1, previa.get("arquivos"))
    feito = await b.sucesso("arrendamento_excluir_contrato", id_contrato=id_, remover_dependencias=True, confirmar=True)
    b.checar("anexo apagado pelo endpoint próprio antes do contrato (sem órfão no armazenamento)",
             len(feito.get("arquivos_excluidos", [])) == 1, feito.get("arquivos_excluidos"))
    busca = await b.sucesso("arrendamento_buscar_contratos", numero_contrato=cd)
    b.checar("contrato excluído (busca vazia)", busca["totalRegistros"] == 0, busca["totalRegistros"])
    msg = await b.recusa("arrendamento_consultar_contrato", id_contrato=id_, abas=[])
    b.checar("consulta do contrato excluído dá erro", "[" in msg, msg)


async def faxina(b: Bateria, cd: str) -> None:
    """Apaga o que sobrou de uma execução interrompida (aditivos antes do contrato)."""
    erro, busca = await b.chamar("arrendamento_buscar_contratos", numero_contrato=cd)
    if erro:
        print(f"  faxina: busca falhou: {busca}", flush=True)
        return
    for item in busca["itens"]:
        id_ = item["idContratoArrendamento"]
        erro, aditivos = await b.chamar("arrendamento_listar_aditivos", id_contrato=id_)
        alvos = [a["idContratoArrendamento"] for a in (aditivos.get("itens", []) if not erro else [])] + [id_]
        for alvo in alvos:
            erro, r = await b.chamar("arrendamento_excluir_contrato", id_contrato=alvo,
                                     remover_dependencias=True, confirmar=True)
            print(f"  faxina: excluir {alvo}: {'ERRO ' + str(r) if erro else 'ok'}", flush=True)
    erro, busca = await b.chamar("arrendamento_buscar_contratos", numero_contrato=cd)
    b.checar("faxina: nada de teste sobrou", not erro and busca["totalRegistros"] == 0, busca)


async def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        return await bateria(Path(tmp))


async def bateria(pasta: Path) -> int:
    env = {
        **os.environ,
        "PYTHONPATH": str(RAIZ / "src"),
        "ARRENDAMENTO_URL": HMG,
        "ARRENDAMENTO_PERFIL": str(Path.home() / ".mcp-arrendamento" / "perfil-hmg"),
        "ARRENDAMENTO_LOGIN_INTERATIVO": "false",
        # O servidor só envia anexos de pastas permitidas (seguranca.py).
        "ARRENDAMENTO_PASTAS_ENVIO": str(pasta),
    }
    params = StdioServerParameters(command=str(RAIZ / ".venv/bin/python"), args=["-m", "mcp_arrendamento"], env=env)
    async with stdio_client(params) as (leitura, escrita), ClientSession(leitura, escrita) as sessao:
        await sessao.initialize()
        b = Bateria(sessao)
        info = await b.sucesso("arrendamento_sessao")
        if info.get("ambiente") != HMG:
            print(f"ABORTADO: o servidor está em {info.get('ambiente')!r}, não em homologação.", file=sys.stderr)
            return 2
        print(f"ambiente: {info['ambiente']} · {info['nome']} ({info['perfil']})", flush=True)
        opcoes = {}
        for tipo in ("tipos-contrato", "licitacoes-previas", "portos", "natureza-carga", "tipo-servico"):
            opcoes[tipo] = (await b.sucesso("arrendamento_listar_opcoes", tipo=tipo))["itens"]

        cd = f"MCP-TESTE/{datetime.now():%Y%m%d-%H%M%S}"
        marca = cd.split("/")[-1]
        try:
            id_ = await criar_contrato(b, opcoes, cd)
            await alterar_contrato(b, id_)
            id_ad = await aditivo(b, id_, cd)
            await abas(b, id_, id_ad, opcoes)
            await arquivos(b, id_, pasta, marca)
            await validacoes(b, id_)
            await exclusao(b, id_, id_ad, cd, pasta, marca)
        except Exception as e:  # noqa: BLE001 — relatar e limpar, qualquer que seja o erro
            b.checar("bateria seguiu até o fim", False, f"{type(e).__name__}: {e}")
        finally:
            print("\n[faxina]", flush=True)
            await faxina(b, cd)

        print(f"\n{b.ok} verificações ok · {len(b.falhas)} falha(s)")
        for f in b.falhas:
            print(f"  - {f}")
        return 1 if b.falhas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
