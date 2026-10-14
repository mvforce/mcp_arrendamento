import pytest

from mcp_arrendamento.contratos import (
    CAMPOS_CONTRATO,
    diferencas,
    mesclar_contrato,
    montar_aditivo,
    montar_novo_contrato,
    normalizar_contrato,
)
from mcp_arrendamento.subentidades import ErroValidacao


def _contrato_do_get(**sobrescrever) -> dict:
    """Formato devolvido por GET /contratos-arrendamento/{id}."""
    c = {nome: None for nome in CAMPOS_CONTRATO}
    c.update({
        "idContratoArrendamento": 4398, "idContratoArrendamentoPai": None,
        "cdContrato": "DIPRE-DINEG/06.2026", "dtInicialContrato": "2026-06-25T03:00:00",
        "dtFimContrato": "2027-06-25T03:00:00", "mmObjeto": "Movimentação de granéis",
        "noRenovacao": "Sim", "dsExercida": "Não", "nrVersao": 1, "nrCnpj": "33000167000101",
        "dTcriacao": "2026-06-26T03:00:00", "dtOperacao": "2026-06-25T03:00:00",
        "nrPrazoContrato": 1, "noTipoOutorga": "Contrato de Transição",
        "dtAssinatura": "2026-06-25T03:00:00", "noFantasiaEmpresa": "PETROBRAS",
        "noNomeInstrumento": "Contrato", "stContrato": 1, "cdTrigrama": "SSZ",
        "stMostrarAteLei12815": False, "tpContrato": 1, "stLicitacaoPrevia": 2,
        "nrPrazoContratoMeses": 0, "nrPrazoContratoDias": 0,
        "nrcnpjInstalacao": "33000167000101", "noInstalacao": "PETROBRAS",
    })
    c.update(sobrescrever)
    return c


def test_lista_os_46_campos_do_contrato():
    assert len(CAMPOS_CONTRATO) == 46


def test_normaliza_datas_para_meia_noite_de_brasilia_como_o_front():
    p = normalizar_contrato(_contrato_do_get(dtFimContrato="2030-01-31"))
    assert p["dtFimContrato"] == "2030-01-31T03:00:00.000Z"
    assert p["dtAssinatura"] == "2026-06-25T03:00:00.000Z"
    assert p["dtPublicacao"] is None


def test_normaliza_cnpj_para_so_digitos():
    p = normalizar_contrato(_contrato_do_get(nrCnpj="33.000.167/0001-01"))
    assert p["nrCnpj"] == "33000167000101"


def test_ostensividade_aceita_letra_da_tela():
    assert normalizar_contrato(_contrato_do_get(stContrato="C"))["stContrato"] == 3


def test_mostrar_ate_lei_12815_aceita_sim_e_nao():
    assert normalizar_contrato(_contrato_do_get(stMostrarAteLei12815="Sim"))["stMostrarAteLei12815"] is True
    assert normalizar_contrato(_contrato_do_get(stMostrarAteLei12815="não"))["stMostrarAteLei12815"] is False


def test_texto_opcional_vazio_vira_null():
    assert normalizar_contrato(_contrato_do_get(cdArea="  "))["cdArea"] is None


def test_mescla_mantem_todos_os_campos_e_aplica_a_alteracao():
    p = mesclar_contrato(_contrato_do_get(), {"mmObjeto": "Novo objeto"})
    assert p["mmObjeto"] == "Novo objeto"
    assert p["cdContrato"] == "DIPRE-DINEG/06.2026"
    assert set(p) == set(CAMPOS_CONTRATO)


def test_mescla_recusa_campo_desconhecido():
    with pytest.raises(ErroValidacao, match="mmObjecto"):
        mesclar_contrato(_contrato_do_get(), {"mmObjecto": "x"})


def test_mescla_nao_deixa_trocar_o_id():
    with pytest.raises(ErroValidacao, match="idContratoArrendamento"):
        mesclar_contrato(_contrato_do_get(), {"idContratoArrendamento": 1})


def test_mescla_exige_os_obrigatorios_da_tela():
    with pytest.raises(ErroValidacao, match="noNomeInstrumento"):
        mesclar_contrato(_contrato_do_get(), {"noNomeInstrumento": ""})


def test_obrigatorio_numerico_zero_conta_como_preenchido():
    p = mesclar_contrato(_contrato_do_get(), {"nrPrazoContratoMeses": 0})
    assert p["nrPrazoContratoMeses"] == 0


def test_diferencas_mostra_so_o_que_muda():
    antes = _contrato_do_get()
    depois = mesclar_contrato(antes, {"mmObjeto": "Novo", "dtFimContrato": "2027-06-25"})
    assert diferencas(antes, depois) == {"mmObjeto": {"de": "Movimentação de granéis", "para": "Novo"}}


def test_novo_contrato_gera_id_como_o_front_e_preenche_padroes():
    dados = {
        k: v for k, v in _contrato_do_get().items()
        if v is not None and k not in ("idContratoArrendamento", "dTcriacao")
    }
    p = montar_novo_contrato(dados, agora_ms=1_791_324_706_123)
    assert p["idContratoArrendamento"] == 1_791_324_706_123 % 1_000_000_000
    assert p["dTcriacao"] == "2026-10-06T03:00:00.000Z"
    assert p["idContratoArrendamentoPai"] is None


def test_novo_contrato_sem_obrigatorio_lista_o_que_falta():
    with pytest.raises(ErroValidacao, match="cdTrigrama"):
        montar_novo_contrato({"cdContrato": "1/2026"}, agora_ms=0)


def test_aditivo_copia_o_pai_e_incrementa_a_versao():
    pai = _contrato_do_get(cdHash="hash-do-pai", vlwacc=8, dsDestinacao="Granel")
    aditivos = [{"nrVersao": 2}, {"nrVersao": 3}]
    p = montar_aditivo(pai, aditivos, {"dtAssinaturaAditivo": "2026-10-01"}, agora_ms=1_791_324_706_123)
    assert p["idContratoArrendamentoPai"] == 4398
    assert p["idContratoArrendamento"] != 4398
    assert p["nrVersao"] == 4
    assert p["cdContrato"] == pai["cdContrato"]
    assert p["dtAssinaturaAditivo"] == "2026-10-01T03:00:00.000Z"
    # O front não copia hash, WACC nem destinação para o aditivo.
    assert p["cdHash"] is None and p["vlwacc"] is None and p["dsDestinacao"] is None


def test_aditivo_exige_data_de_assinatura_do_aditivo():
    with pytest.raises(ErroValidacao, match="dtAssinaturaAditivo"):
        montar_aditivo(_contrato_do_get(), [], {}, agora_ms=0)


def _dados_novos(**sobrescrever) -> dict:
    dados = {
        k: v for k, v in _contrato_do_get().items()
        if v is not None and k not in ("idContratoArrendamento", "dTcriacao")
    }
    dados.update(sobrescrever)
    return dados


@pytest.mark.parametrize("informado, gravado", [
    ("Transição", "Contrato de Transição"),
    ("passagem", "Contrato de Passagem"),
    (2, "Contrato de Passagem"),
    ("1", "Arrendamento"),
    ("Cessão de Uso Onerosa", "Cessão de Uso Onerosa"),
])
def test_tipo_de_outorga_informado_vira_o_valor_que_a_tela_grava(informado, gravado):
    p = montar_novo_contrato(_dados_novos(noTipoOutorga=informado), agora_ms=0)
    assert p["noTipoOutorga"] == gravado


def test_tipo_de_outorga_legado_nao_muda_ao_alterar_outro_campo():
    atual = _contrato_do_get(noTipoOutorga="Transição")
    p = mesclar_contrato(atual, {"mmObjeto": "Novo"})
    assert p["noTipoOutorga"] == "Transição"


def test_tipo_de_outorga_numerico_desconhecido_pede_o_texto():
    with pytest.raises(ErroValidacao, match="noTipoOutorga"):
        montar_novo_contrato(_dados_novos(noTipoOutorga=9), agora_ms=0)


@pytest.mark.parametrize("campo, informado, gravado", [
    ("noRenovacao", "não possui", "Nao possui"),
    ("noRenovacao", "POSSUI", "Possui"),
    ("noRenovacao", "Não", "Nao possui"),
    ("noRenovacao", "Sim", "Possui"),
    ("dsExercida", "nao", "Não"),
    ("dsExercida", "sim", "Sim"),
])
def test_prorrogacao_e_exercida_viram_os_valores_do_select_da_tela(campo, informado, gravado):
    p = montar_novo_contrato(_dados_novos(**{campo: informado}), agora_ms=0)
    assert p[campo] == gravado


def test_prorrogacao_invalida_lista_as_opcoes():
    with pytest.raises(ErroValidacao, match="Nao possui"):
        montar_novo_contrato(_dados_novos(noRenovacao="talvez"), agora_ms=0)


def test_descricao_dos_campos_traz_as_opcoes_dos_selects():
    from mcp_arrendamento.contratos import descrever_campos
    campos = {c["nome"]: c for c in descrever_campos()}
    assert "Nao possui" in campos["noRenovacao"]["tipo"]
    assert "Nao Operacional" in campos["tpContrato"]["tipo"]
    assert "Em Apuracao" in campos["stLicitacaoPrevia"]["tipo"]


@pytest.mark.parametrize("informado, gravado", [
    ("Cessao de Uso Onerosa", "Cessão de Uso Onerosa"),      # descrição sem acento de listar_opcoes
    ("Cessao de Uso Nao Onerosa", "Cessão de Uso Não Onerosa"),
    ("Contrato de Transicao", "Contrato de Transição"),
    ("contrato de uso temporario", "Contrato de Uso Temporário"),
    ("Outras Formas Contratuais", "Outras Formas Contratuais"),
])
def test_descricao_sem_acento_da_lista_de_opcoes_vira_o_valor_gravado_pela_tela(informado, gravado):
    p = montar_novo_contrato(_dados_novos(noTipoOutorga=informado), agora_ms=0)
    assert p["noTipoOutorga"] == gravado
