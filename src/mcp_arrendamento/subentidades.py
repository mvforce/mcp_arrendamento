"""Registro das sub-entidades do contrato (as abas da tela de contrato).

Todas seguem o mesmo CRUD: `GET /{recurso}/por-contrato/{idContrato}`,
`POST /{recurso}`, `PUT /{recurso}/{id}` e `DELETE /{recurso}/{id}`.
A exceção é `tipos-servicos-contrato`, cuja chave é composta.

Campos, obrigatoriedade, opções e formato de data foram copiados das funções
do front que montam cada payload (bundle 1.0.0). Ver docs/mapa-api.md.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp_arrendamento.erros import ErroValidacao


@dataclass(frozen=True)
class Campo:
    nome: str
    # texto | numero (>= 0, aceita vírgula) | inteiro (>= 0) |
    # dia ("AAAA-MM-DD", enviado assim) | data_iso ("AAAA-MM-DD" → meia-noite de Brasília em UTC)
    tipo: str
    obrigatorio: bool = False
    opcoes: tuple = ()
    sinonimos: dict = field(default_factory=dict)
    descricao: str = ""


@dataclass(frozen=True)
class Subentidade:
    recurso: str
    rotulo: str
    chave: str
    campos: tuple[Campo, ...]
    fixos: dict = field(default_factory=dict)
    chave_composta: bool = False


_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Padrão de quando o campo opcional não vem, igual ao front: número vazio vira 0.
_PADRAO_POR_TIPO = {"texto": "", "numero": 0, "inteiro": None, "dia": None, "data_iso": None}


def _sem_acento(valor: str) -> str:
    nfd = unicodedata.normalize("NFD", valor)
    return "".join(c for c in nfd if not unicodedata.combining(c)).strip().casefold()


def _vazio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _dia(campo: Campo, valor: Any) -> str:
    texto = str(valor).strip()[:10]
    if not _DIA.match(texto):
        raise ErroValidacao(f"{campo.nome}: use o formato AAAA-MM-DD (recebido {valor!r}).")
    return texto


def _numero(campo: Campo, valor: Any) -> float | int:
    if isinstance(valor, bool):
        raise ErroValidacao(f"{campo.nome}: esperado número.")
    if isinstance(valor, (int, float)):
        numero = valor
    else:
        try:
            numero = float(str(valor).strip().replace(",", "."))
        except ValueError:
            raise ErroValidacao(f"{campo.nome}: esperado número (recebido {valor!r}).") from None
    if numero < 0:
        raise ErroValidacao(f"{campo.nome}: deve ser maior ou igual a zero.")
    return numero


def _inteiro(campo: Campo, valor: Any) -> int:
    try:
        inteiro = int(str(valor).strip()) if not isinstance(valor, int) else valor
    except ValueError:
        raise ErroValidacao(f"{campo.nome}: esperado número inteiro (recebido {valor!r}).") from None
    if inteiro < 0:
        raise ErroValidacao(f"{campo.nome}: deve ser maior ou igual a zero.")
    return inteiro


def _opcao(campo: Campo, valor: Any) -> Any:
    if campo.tipo == "inteiro":
        if valor in campo.opcoes:
            return valor
    else:
        chave = _sem_acento(str(valor))
        chave = _sem_acento(campo.sinonimos.get(chave.upper(), chave))
        for opcao in campo.opcoes:
            if _sem_acento(opcao) == chave:
                return opcao
    aceitas = ", ".join(str(o) for o in campo.opcoes)
    raise ErroValidacao(f"{campo.nome}: valor {valor!r} não aceito. Use: {aceitas}.")


def converter_campo(campo: Campo, valor: Any) -> Any:
    if _vazio(valor):
        if campo.obrigatorio:
            raise ErroValidacao(f"{campo.nome} é obrigatório.")
        return _PADRAO_POR_TIPO[campo.tipo]
    if campo.tipo == "texto":
        valor = str(valor).strip()
    elif campo.tipo == "numero":
        valor = _numero(campo, valor)
    elif campo.tipo == "inteiro":
        valor = _inteiro(campo, valor)
    elif campo.tipo == "dia":
        valor = _dia(campo, valor)
    elif campo.tipo == "data_iso":
        valor = f"{_dia(campo, valor)}T03:00:00.000Z"
    if campo.opcoes:
        valor = _opcao(campo, valor)
    return valor


def _texto(nome, obrigatorio=False, **kw) -> Campo:
    return Campo(nome, "texto", obrigatorio, **kw)


_SUBENTIDADES = (
    Subentidade(
        "aspectos-fisicos", "Aspectos físicos", "idAspectoFisico",
        (
            Campo("vlExtencaoLinhaCais", "numero", descricao="extensão da linha de cais (m)"),
            Campo("vlAreaTotal", "numero", True, descricao="área total (m²)"),
            Campo("vlAreaAmpliacao", "numero", descricao="área de ampliação (m²)"),
        ),
        fixos={"nrBerco": ""},
    ),
    Subentidade(
        "bens", "Bens", "idBem",
        (
            _texto("dsBem", True, descricao="descrição do bem"),
            _texto("noClassificacao", True, opcoes=("Equipamento", "Imovel", "Utilidade")),
            _texto("stReversivel", True, opcoes=("Sim", "Nao")),
            _texto("noOrigem", True, opcoes=("Nao Informado", "Arrendatario", "Autoridade Portuaria")),
            Campo("nrVidaUtil", "inteiro", descricao="vida útil pós-contrato (anos)"),
            Campo("vlBem", "numero", descricao="avaliação na data do contrato (R$)"),
        ),
    ),
    Subentidade(
        "partes-significativas", "Partes significativas", "idParteSignificativa",
        (_texto("noClausula", True), _texto("noParagrafo", True), _texto("dsParagrafo", True)),
    ),
    Subentidade(
        "coordenadas", "Coordenadas", "idCoordenada",
        (
            Campo("idAspectoFisico", "inteiro", descricao="aspecto físico (berço) ao qual o ponto pertence"),
            _texto("dsPonto", True),
            Campo("vlLatitude", "numero", True, descricao="graus"),
            Campo("vlMinLatitude", "inteiro", True),
            Campo("vlSecLatitude", "numero", True),
            _texto("vlLatitudeCardial", True, opcoes=("N", "S")),
            Campo("vlLongitude", "numero", True, descricao="graus"),
            Campo("vlMinLongitude", "inteiro", True),
            Campo("vlSecLongitude", "numero", True),
            _texto("vlLongitudeCardial", True, opcoes=("L", "O"), sinonimos={"E": "L", "W": "O"}),
        ),
    ),
    Subentidade(
        "contratos-processos", "Processos e atos da ANTAQ", "idContratoProcesso",
        (
            _texto("nrProcesso", descricao="número do processo SEI"),
            _texto("dsAtoAntaq", opcoes=("Acórdão", "Resolução")),
            _texto("nrAto"),
            Campo("dtAto", "dia"),
        ),
    ),
    Subentidade(
        "decisoes-judiciais", "Decisões judiciais", "idDecisaoJudicial",
        (
            _texto("dsOrigemDecisao", True),
            _texto("nrProcessoJudicial", True),
            _texto("dsTeorDecisao", True),
            _texto("dsCondicaoEfeito", True),
            Campo("dtDecisaoJudicial", "dia", True),
            Campo("dtInicioEfeito", "dia", True),
            Campo("dtFimEfeito", "dia"),
            Campo(
                "idSituacaoDecisaoJudicial", "inteiro", True, opcoes=(0, 1, 2, 3),
                descricao="0 pendente de verificação · 1 liminar produzindo efeitos · "
                "2 condição materializada · 3 decisão reformada",
            ),
        ),
    ),
    Subentidade(
        "contratos-encerrados", "Encerramento do contrato", "idContratoEncerrado",
        (Campo("dtFinalizacaoContrato", "data_iso", True), _texto("dsMotivo", True)),
    ),
    Subentidade(
        "investimentos-previstos", "Investimentos previstos", "idInvestimentoPrevisto",
        (
            _texto("dsInvestimentoPrevisto", True),
            Campo("vlInvestimentoPrevisto", "numero", True, descricao="R$"),
            Campo("dtInvestimentoPrevisto", "dia", True),
        ),
    ),
    Subentidade(
        "investimentos-realizados", "Investimentos realizados", "idInvestimentoRealizado",
        (
            _texto("dsInvestimentoRealizado", True),
            Campo("vlInvestimentoRealizado", "numero", True, descricao="R$"),
            Campo("dtInvestimentoRealizado", "dia", True),
        ),
    ),
    Subentidade(
        "observacoes", "Observações", "idObservacao",
        (_texto("noResponsavel", True), _texto("dsObservacao", True), Campo("dtObservacao", "dia", True)),
    ),
    Subentidade(
        "perfis-carga-passageiros", "Perfil de carga ou passageiros", "idClassificaoSubclassificaoCarga",
        (Campo("idNaturezaCarga", "inteiro", True, descricao="ver opções natureza-carga"),),
    ),
    Subentidade(
        "tipos-servicos-contrato", "Tipos de serviço", "idTipoServico",
        (Campo("idTipoServico", "inteiro", True, descricao="ver opções tipo-servico"),),
        chave_composta=True,
    ),
    Subentidade(
        "situacoes-adimplemento", "Situação de adimplemento", "idSituacaoAdimplemento",
        (
            Campo("stAdimplemento", "inteiro", True, opcoes=(1, 2), descricao="1 adimplente · 2 inadimplente"),
            Campo("dtAdimplemento", "data_iso", True),
            _texto("dsObservacao"),
        ),
    ),
)

SUBENTIDADES: dict[str, Subentidade] = {s.recurso: s for s in _SUBENTIDADES}


def obter(recurso: str) -> Subentidade:
    try:
        return SUBENTIDADES[recurso]
    except KeyError:
        raise ErroValidacao(
            f"Recurso {recurso!r} desconhecido. Use um destes: {', '.join(SUBENTIDADES)}."
        ) from None


def _recusar_desconhecidos(sub: Subentidade, dados: dict) -> None:
    aceitos = {c.nome for c in sub.campos}
    sobra = sorted(set(dados) - aceitos)
    if sobra:
        raise ErroValidacao(
            f"Campo(s) desconhecido(s) em {sub.recurso}: {', '.join(sobra)}. "
            f"Aceitos: {', '.join(sorted(aceitos))}."
        )


def montar_payload(recurso: str, id_contrato: int, dados: dict) -> dict:
    sub = obter(recurso)
    _recusar_desconhecidos(sub, dados)
    payload: dict[str, Any] = {"idContratoArrendamento": id_contrato}
    payload.update(sub.fixos)
    for campo in sub.campos:
        payload[campo.nome] = converter_campo(campo, dados.get(campo.nome))
    return payload


def mesclar_payload(recurso: str, id_contrato: int, registro_atual: dict, alteracoes: dict) -> dict:
    """Payload de PUT: o registro atual com as alterações aplicadas por cima."""
    sub = obter(recurso)
    _recusar_desconhecidos(sub, alteracoes)
    base: dict[str, Optional[Any]] = {}
    for campo in sub.campos:
        valor = registro_atual.get(campo.nome)
        if campo.tipo in ("dia", "data_iso") and isinstance(valor, str):
            valor = valor[:10]
        base[campo.nome] = valor
    base.update(alteracoes)
    return montar_payload(recurso, id_contrato, base)


def caminho_registro(recurso: str, id_contrato: int, id_registro: int) -> str:
    sub = obter(recurso)
    if sub.chave_composta:
        return f"/{recurso}/{id_contrato}/{id_registro}"
    return f"/{recurso}/{id_registro}"
