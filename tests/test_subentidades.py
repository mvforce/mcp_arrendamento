import pytest

from mcp_arrendamento.subentidades import (
    SUBENTIDADES,
    ErroValidacao,
    caminho_registro,
    mesclar_payload,
    montar_payload,
)


def test_cobre_as_treze_subentidades_do_front():
    assert set(SUBENTIDADES) == {
        "aspectos-fisicos", "bens", "partes-significativas", "coordenadas",
        "contratos-processos", "decisoes-judiciais", "contratos-encerrados",
        "investimentos-previstos", "investimentos-realizados", "observacoes",
        "perfis-carga-passageiros", "tipos-servicos-contrato", "situacoes-adimplemento",
    }


def test_payload_leva_id_do_contrato_e_os_campos():
    p = montar_payload("observacoes", 4398, {
        "noResponsavel": "Fulano", "dsObservacao": "Texto", "dtObservacao": "2026-10-01",
    })
    assert p == {
        "idContratoArrendamento": 4398, "noResponsavel": "Fulano",
        "dsObservacao": "Texto", "dtObservacao": "2026-10-01",
    }


def test_recurso_desconhecido_lista_os_validos():
    with pytest.raises(ErroValidacao, match="observacoes"):
        montar_payload("observacao", 1, {})


def test_campo_obrigatorio_ausente_e_nomeado_no_erro():
    with pytest.raises(ErroValidacao, match="dsObservacao"):
        montar_payload("observacoes", 1, {"noResponsavel": "x", "dtObservacao": "2026-10-01"})


def test_campo_desconhecido_e_recusado_para_pegar_erro_de_digitacao():
    with pytest.raises(ErroValidacao, match="dsObservacaoo"):
        montar_payload("observacoes", 1, {
            "noResponsavel": "x", "dsObservacao": "y", "dtObservacao": "2026-10-01",
            "dsObservacaoo": "z",
        })


def test_opcao_aceita_variacao_de_acento_e_caixa_e_devolve_valor_canonico():
    p = montar_payload("bens", 1, {
        "dsBem": "Guindaste", "noClassificacao": "imóvel", "stReversivel": "não",
        "noOrigem": "autoridade portuária",
    })
    assert p["noClassificacao"] == "Imovel"
    assert p["stReversivel"] == "Nao"
    assert p["noOrigem"] == "Autoridade Portuaria"


def test_processo_usa_ato_com_acento_como_o_front():
    p = montar_payload("contratos-processos", 1, {
        "nrProcesso": "50300.000001/2026-01", "dsAtoAntaq": "acordao", "nrAto": "10",
        "dtAto": "2026-01-02",
    })
    assert p["dsAtoAntaq"] == "Acórdão"


def test_opcao_invalida_lista_as_aceitas():
    with pytest.raises(ErroValidacao, match="Equipamento"):
        montar_payload("bens", 1, {
            "dsBem": "x", "noClassificacao": "Navio", "stReversivel": "Sim",
            "noOrigem": "Arrendatario",
        })


def test_numero_aceita_virgula_decimal():
    p = montar_payload("aspectos-fisicos", 1, {"vlAreaTotal": "1234,5"})
    assert p["vlAreaTotal"] == 1234.5
    assert p["nrBerco"] == ""


def test_longitude_cardinal_converte_leste_e_oeste_como_o_front():
    base = {
        "idAspectoFisico": 7, "dsPonto": "P1", "vlLatitude": 23, "vlMinLatitude": 1,
        "vlSecLatitude": 2.5, "vlLatitudeCardial": "S", "vlLongitude": 46,
        "vlMinLongitude": 3, "vlSecLongitude": 4,
    }
    assert montar_payload("coordenadas", 1, {**base, "vlLongitudeCardial": "W"})["vlLongitudeCardial"] == "O"
    assert montar_payload("coordenadas", 1, {**base, "vlLongitudeCardial": "E"})["vlLongitudeCardial"] == "L"


def test_data_do_encerramento_vai_como_meia_noite_de_brasilia_em_utc():
    p = montar_payload("contratos-encerrados", 1, {
        "dtFinalizacaoContrato": "2026-10-06", "dsMotivo": "Fim do prazo",
    })
    assert p["dtFinalizacaoContrato"] == "2026-10-06T03:00:00.000Z"


def test_data_invalida_e_recusada():
    with pytest.raises(ErroValidacao, match="dtObservacao"):
        montar_payload("observacoes", 1, {
            "noResponsavel": "x", "dsObservacao": "y", "dtObservacao": "06/10/2026",
        })


def test_situacao_de_decisao_judicial_so_aceita_codigos_conhecidos():
    dados = {
        "dsOrigemDecisao": "TRF1", "nrProcessoJudicial": "1", "dsTeorDecisao": "t",
        "dsCondicaoEfeito": "c", "dtDecisaoJudicial": "2026-01-01",
        "dtInicioEfeito": "2026-01-02", "idSituacaoDecisaoJudicial": 9,
    }
    with pytest.raises(ErroValidacao, match="idSituacaoDecisaoJudicial"):
        montar_payload("decisoes-judiciais", 1, dados)


def test_mescla_parte_do_registro_atual_e_aplica_so_as_alteracoes():
    atual = {
        "idObservacao": 55, "idContratoArrendamento": 4398, "noResponsavel": "Fulano",
        "dsObservacao": "Antigo", "dtObservacao": "2026-01-05T00:00:00",
        "cdHash": "abc", "nrVersao": 1, "cdContrato": "X",
    }
    p = mesclar_payload("observacoes", 4398, atual, {"dsObservacao": "Novo"})
    assert p == {
        "idContratoArrendamento": 4398, "noResponsavel": "Fulano",
        "dsObservacao": "Novo", "dtObservacao": "2026-01-05",
    }


def test_caminho_do_registro_simples_e_da_chave_composta():
    assert caminho_registro("bens", 4398, 12) == "/bens/12"
    assert caminho_registro("tipos-servicos-contrato", 4398, 3) == "/tipos-servicos-contrato/4398/3"
