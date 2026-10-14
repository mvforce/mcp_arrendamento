"""Regras do contrato de arrendamento, copiadas do formulário do front (bundle 1.0.0).

O `PUT /contratos-arrendamento/{id}` substitui o registro inteiro. Toda alteração
parte do GET atual, aplica só o que mudou e reenvia os 46 campos.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

from mcp_arrendamento.erros import ErroValidacao

_DATAS = (
    "dtInicialContrato", "dtFimContrato", "dTcriacao", "dtOperacao", "dtAssinatura",
    "dtPublicacao", "dtAssinaturaAditivo", "dtDesocupacao", "dtVigenciaContrato",
    "dtEditalLicitacao",
)
# Number(...) no front: sempre numérico.
_NUMEROS = ("idContratoArrendamento", "nrVersao", "nrPrazoContrato", "tpContrato")
# Número ou null.
_NUMEROS_OPCIONAIS = (
    "idContratoArrendamentoPai", "stInicioContrato", "stHomogacao", "stExpiracao", "vlwacc",
    "idTerminal", "stLicitacaoPrevia", "idTipoLicitacao", "nrPrazoContratoMeses",
    "nrPrazoContratoDias",
)
# Texto com trim, nunca null.
_TEXTOS = ("cdContrato", "noRenovacao")
# Texto ou null.
_TEXTOS_OPCIONAIS = (
    "mmObjeto", "dsExercida", "cdHash", "noTipoOutorga", "noJustificativaHomologacao",
    "noFantasiaEmpresa", "noContrato", "noNomeInstrumento", "cdTrigrama", "cdArea",
    "nrEditalLicitacao", "noUsuarioCadastro", "dsPassivelLicitacao", "dsIdentificacao",
    "dsDestinacao", "noInstalacao",
)
_CNPJS = ("nrCnpj", "nrcnpjInstalacao")
_OSTENSIVIDADE = {"A": 1, "B": 2, "C": 3}  # Publicar · Concessão Portuária ou de Acesso · Não Publicar

# Ordem do payload do front (função Oo).
CAMPOS_CONTRATO: tuple[str, ...] = (
    "idContratoArrendamento", "idContratoArrendamentoPai", "cdContrato", "dtInicialContrato",
    "dtFimContrato", "mmObjeto", "noRenovacao", "dsExercida", "nrVersao", "nrCnpj", "cdHash",
    "dTcriacao", "dtOperacao", "nrPrazoContrato", "noTipoOutorga", "dtAssinatura",
    "dtPublicacao", "stInicioContrato", "stHomogacao", "noJustificativaHomologacao",
    "stExpiracao", "noFantasiaEmpresa", "noContrato", "dtAssinaturaAditivo", "dtDesocupacao",
    "vlwacc", "noNomeInstrumento", "stContrato", "idTerminal", "cdTrigrama", "cdArea",
    "stMostrarAteLei12815", "tpContrato", "stLicitacaoPrevia", "dtVigenciaContrato",
    "nrEditalLicitacao", "dtEditalLicitacao", "idTipoLicitacao", "nrPrazoContratoMeses",
    "nrPrazoContratoDias", "noUsuarioCadastro", "dsPassivelLicitacao", "dsIdentificacao",
    "dsDestinacao", "nrcnpjInstalacao", "noInstalacao",
)

# Obrigatórios do formulário (função Do), com o rótulo da tela.
OBRIGATORIOS: tuple[tuple[str, str], ...] = (
    ("nrVersao", "Versão do Contrato"), ("cdContrato", "Número do Contrato"),
    ("noNomeInstrumento", "Nome do Instrumento"), ("tpContrato", "Tipo de Contrato"),
    ("stLicitacaoPrevia", "Licitação Prévia"), ("noTipoOutorga", "Tipo de Outorga"),
    ("cdTrigrama", "Porto"), ("nrCnpj", "CNPJ"), ("noFantasiaEmpresa", "Razão Social Contrato"),
    ("nrcnpjInstalacao", "CNPJ Instalação Portuária"),
    ("noInstalacao", "Razão Social Instalação Portuária"), ("nrPrazoContrato", "Prazo (Anos)"),
    ("dtAssinatura", "Data de Assinatura do Contrato"), ("dtOperacao", "Data de Início da Vigência"),
    ("dtFimContrato", "Data de Término da Vigência"), ("nrPrazoContratoMeses", "Prazo (Meses)"),
    ("nrPrazoContratoDias", "Prazo (Dias)"), ("stContrato", "Ostensividade"),
    ("noRenovacao", "Cláusula de Prorrogação"), ("dsExercida", "Exercida"),
    ("mmObjeto", "Objeto do Contrato"),
)

# Campos que o front copia do contrato pai ao preparar um aditivo (função $t).
_COPIADOS_NO_ADITIVO = (
    "cdContrato", "dtInicialContrato", "dtFimContrato", "mmObjeto", "noRenovacao", "dsExercida",
    "nrCnpj", "dtOperacao", "nrPrazoContrato", "noTipoOutorga", "dtAssinatura", "dtPublicacao",
    "stHomogacao", "noJustificativaHomologacao", "noFantasiaEmpresa", "dtDesocupacao",
    "noNomeInstrumento", "stContrato", "cdTrigrama", "cdArea", "stMostrarAteLei12815",
    "tpContrato", "stLicitacaoPrevia", "nrEditalLicitacao", "dtEditalLicitacao",
    "idTipoLicitacao", "nrPrazoContratoMeses", "nrPrazoContratoDias", "nrcnpjInstalacao",
    "noInstalacao",
)

# Valores iniciais do formulário de inclusão (Wa).
_PADROES_NOVO = {"nrVersao": 1, "nrPrazoContrato": 0, "nrPrazoContratoMeses": 0, "nrPrazoContratoDias": 0}

_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A tela grava a descrição da opção de tipo de outorga, exceto nestes códigos (função $o).
_OUTORGA_POR_CODIGO = {
    1: "Arrendamento", 2: "Contrato de Passagem", 3: "Contrato de Transição",
    4: "Contrato de Uso Temporário", 5: "Cessão de Uso Onerosa", 6: "Cessão de Uso Não Onerosa",
}
# Rótulos curtos usados nos filtros da tela (função Qo) → valor gravado.
_OUTORGA_POR_ROTULO = {
    "PASSAGEM": "Contrato de Passagem", "TRANSICAO": "Contrato de Transição",
    "USO TEMPORARIO": "Contrato de Uso Temporário",
}


def _vazio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _data(nome: str, valor: Any) -> Optional[str]:
    if _vazio(valor):
        return None
    dia = str(valor).strip()[:10]
    if not _DIA.match(dia):
        raise ErroValidacao(f"{nome}: use o formato AAAA-MM-DD (recebido {valor!r}).")
    return f"{dia}T03:00:00.000Z"


def _numero(nome: str, valor: Any) -> Optional[float | int]:
    if _vazio(valor):
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return valor
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except ValueError:
        raise ErroValidacao(f"{nome}: esperado número (recebido {valor!r}).") from None
    return int(numero) if numero.is_integer() else numero


def _ostensividade(valor: Any) -> Optional[int]:
    if _vazio(valor):
        return None
    letra = str(valor).strip().upper()
    if letra in _OSTENSIVIDADE:
        return _OSTENSIVIDADE[letra]
    numero = _numero("stContrato", valor)
    if numero not in (1, 2, 3):
        raise ErroValidacao("stContrato: use A/1 (Publicar), B/2 (Concessão Portuária ou de Acesso) ou C/3 (Não Publicar).")
    return int(numero)


def _sim_nao(valor: Any) -> Optional[bool]:
    if isinstance(valor, bool) or valor is None:
        return valor
    texto = str(valor).strip().casefold()
    if not texto:
        return None
    if texto in ("sim", "s", "true", "1"):
        return True
    if texto in ("não", "nao", "n", "false", "0"):
        return False
    raise ErroValidacao(f"stMostrarAteLei12815: use Sim ou Não (recebido {valor!r}).")


def _converter(nome: str, valor: Any) -> Any:
    if nome in _DATAS:
        return _data(nome, valor)
    if nome in _NUMEROS or nome in _NUMEROS_OPCIONAIS:
        return _numero(nome, valor)
    if nome in _TEXTOS:
        return "" if valor is None else str(valor).strip()
    if nome in _TEXTOS_OPCIONAIS:
        return None if _vazio(valor) else str(valor).strip()
    if nome in _CNPJS:
        digitos = re.sub(r"\D", "", "" if valor is None else str(valor))[:14]
        return digitos or None
    if nome == "stContrato":
        return _ostensividade(valor)
    if nome == "stMostrarAteLei12815":
        return _sim_nao(valor)
    raise AssertionError(f"campo sem regra de conversão: {nome}")


def _tipo_outorga_informado(valor: Any) -> Any:
    """Converte o tipo de outorga informado pelo usuário no texto que a tela grava.

    Só vale para o valor informado: o que já está gravado não é reescrito.
    """
    if _vazio(valor) or isinstance(valor, bool):
        return valor
    texto = str(valor).strip()
    if texto.isdigit():
        codigo = int(texto)
        if codigo not in _OUTORGA_POR_CODIGO:
            raise ErroValidacao(
                f"noTipoOutorga: código {codigo} sem valor conhecido; informe a descrição "
                "(ver arrendamento_listar_opcoes('tipos-outorga'))."
            )
        return _OUTORGA_POR_CODIGO[codigo]
    chave = "".join(
        c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)
    ).upper()
    if chave in _OUTORGA_POR_ROTULO:
        return _OUTORGA_POR_ROTULO[chave]
    # A lista de opções da API vem sem acento ("Cessao de Uso Onerosa"); a tela grava com.
    for gravado in _OUTORGA_POR_CODIGO.values():
        sem_acento = "".join(
            c for c in unicodedata.normalize("NFD", gravado) if not unicodedata.combining(c)
        ).upper()
        if sem_acento == chave:
            return gravado
    return texto


# Selects da tela: valor gravado → formas aceitas (sem acento, minúsculas).
_SELECTS = {
    "noRenovacao": {"Possui": ("possui", "sim"), "Nao possui": ("nao possui", "nao")},
    "dsExercida": {"Sim": ("sim",), "Não": ("nao",)},
}
# Opções fixas mostradas em arrendamento_consultar_campos.
_OPCOES_DESCRITAS = {
    "noRenovacao": "Possui · Nao possui",
    "dsExercida": "Sim · Não",
    "tpContrato": "1 Operacional · 2 Nao Operacional",
    "stLicitacaoPrevia": "1 Sim · 2 Nao · 3 Em Apuracao",
    "noTipoOutorga": "descrição de arrendamento_listar_opcoes('tipos-outorga') ou o código 1 a 6",
    "cdTrigrama": "trigrama de arrendamento_listar_opcoes('portos')",
    "idTipoLicitacao": "id de arrendamento_listar_opcoes('tipos-licitacao')",
}


def _sem_acento(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfd if not unicodedata.combining(c)).strip().casefold()


def _select_informado(nome: str, valor: Any) -> Any:
    if _vazio(valor):
        return valor
    chave = _sem_acento(str(valor))
    for gravado, formas in _SELECTS[nome].items():
        if chave in formas:
            return gravado
    raise ErroValidacao(f"{nome}: valor {valor!r} não aceito. Use: {' ou '.join(_SELECTS[nome])}.")


def _preparar_informados(dados: dict) -> dict:
    dados = dict(dados)
    if "noTipoOutorga" in dados:
        dados["noTipoOutorga"] = _tipo_outorga_informado(dados["noTipoOutorga"])
    for nome in _SELECTS:
        if nome in dados:
            dados[nome] = _select_informado(nome, dados[nome])
    return dados


def normalizar_contrato(contrato: dict) -> dict:
    """Converte para o formato que o front envia, sem validar obrigatórios."""
    return {nome: _converter(nome, contrato.get(nome)) for nome in CAMPOS_CONTRATO}


def _recusar_desconhecidos(dados: dict, proibidos: tuple[str, ...] = ()) -> None:
    sobra = sorted(set(dados) - set(CAMPOS_CONTRATO))
    if sobra:
        raise ErroValidacao(f"Campo(s) desconhecido(s) no contrato: {', '.join(sobra)}.")
    vetados = sorted(set(dados) & set(proibidos))
    if vetados:
        raise ErroValidacao(f"Não é possível informar {', '.join(vetados)} aqui.")


def _validar_obrigatorios(payload: dict, aditivo: bool) -> None:
    exigidos = list(OBRIGATORIOS)
    if aditivo:
        exigidos.append(("dtAssinaturaAditivo", "Data Assinatura do Aditivo"))
    faltando = [f"{nome} ({rotulo})" for nome, rotulo in exigidos if _vazio(payload.get(nome))]
    if faltando:
        raise ErroValidacao("Campos obrigatórios sem valor: " + "; ".join(faltando) + ".")


def mesclar_contrato(atual: dict, alteracoes: dict) -> dict:
    _recusar_desconhecidos(alteracoes, proibidos=("idContratoArrendamento",))
    payload = normalizar_contrato({**atual, **_preparar_informados(alteracoes)})
    _validar_obrigatorios(payload, aditivo=payload["idContratoArrendamentoPai"] is not None)
    return payload


def diferencas(antes: dict, depois: dict) -> dict:
    """Campos que mudam, comparando os dois lados no formato de envio."""
    a = normalizar_contrato(antes)
    return {
        nome: {"de": a[nome], "para": depois.get(nome)}
        for nome in CAMPOS_CONTRATO
        if a[nome] != depois.get(nome)
    }


def _id_novo(agora_ms: int) -> int:
    # O front gera o id do lado do cliente: Date.now() % 1e9.
    return agora_ms % 1_000_000_000


def _hoje_utc(agora_ms: int) -> str:
    # new Date().toISOString().slice(0, 10): data em UTC, como no front.
    return datetime.fromtimestamp(agora_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def montar_novo_contrato(dados: dict, agora_ms: int) -> dict:
    _recusar_desconhecidos(dados, proibidos=("idContratoArrendamento", "idContratoArrendamentoPai"))
    base = {**_PADROES_NOVO, "dTcriacao": _hoje_utc(agora_ms), **_preparar_informados(dados)}
    base["idContratoArrendamento"] = _id_novo(agora_ms)
    payload = normalizar_contrato(base)
    _validar_obrigatorios(payload, aditivo=False)
    return payload


def montar_aditivo(pai: dict, aditivos: list[dict], dados: dict, agora_ms: int) -> dict:
    _recusar_desconhecidos(dados, proibidos=("idContratoArrendamento", "idContratoArrendamentoPai"))
    versao = max([pai.get("nrVersao") or 0] + [a.get("nrVersao") or 0 for a in aditivos]) + 1
    base = {nome: pai.get(nome) for nome in _COPIADOS_NO_ADITIVO}
    base.update(
        idContratoArrendamento=_id_novo(agora_ms),
        idContratoArrendamentoPai=pai["idContratoArrendamento"],
        nrVersao=versao,
        dTcriacao=_hoje_utc(agora_ms),
    )
    base.update(_preparar_informados(dados))
    payload = normalizar_contrato(base)
    _validar_obrigatorios(payload, aditivo=True)
    return payload


def descrever_campos() -> list[dict]:
    """Ficha dos campos do contrato para quem monta `dados` ou `alteracoes`."""
    rotulos = dict(OBRIGATORIOS)
    rotulos["dtAssinaturaAditivo"] = "Data Assinatura do Aditivo (obrigatória no aditivo)"

    def tipo(nome: str) -> str:
        if nome in _OPCOES_DESCRITAS:
            return _OPCOES_DESCRITAS[nome]
        if nome in _DATAS:
            return "data AAAA-MM-DD"
        if nome in _CNPJS:
            return "CNPJ (com ou sem pontuação)"
        if nome == "stContrato":
            return "A/1 Publicar · B/2 Concessão Portuária ou de Acesso · C/3 Não Publicar"
        if nome == "stMostrarAteLei12815":
            return "Sim/Não"
        if nome in _NUMEROS or nome in _NUMEROS_OPCIONAIS:
            return "número"
        return "texto"

    return [
        {"nome": nome, "tipo": tipo(nome), "obrigatorio": nome in dict(OBRIGATORIOS), "rotulo": rotulos.get(nome)}
        for nome in CAMPOS_CONTRATO
    ]
