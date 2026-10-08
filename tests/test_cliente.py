import json

import pytest

from mcp_arrendamento.cliente import ClienteArrendamento, ErroArrendamento
from mcp_arrendamento.subentidades import ErroValidacao
from mcp_arrendamento.transporte import Resposta
from tests.test_contratos import _contrato_do_get


def _json(dados, status=200) -> Resposta:
    return Resposta(status, {"content-type": "application/json"}, json.dumps(dados).encode())


class TransporteFalso:
    """Responde por (método, caminho) e registra cada chamada."""

    def __init__(self, rotas: dict):
        self.rotas = rotas
        self.chamadas: list[tuple] = []

    async def requisitar(self, metodo, caminho, json=None, arquivo=None, campos=None):
        self.chamadas.append((metodo, caminho, json))
        resposta = self.rotas.get((metodo, caminho))
        if resposta is None:
            return Resposta(204) if metodo in ("PUT", "DELETE") else Resposta(404, {}, b"")
        return resposta

    def metodos(self):
        return [(m, c) for m, c, _ in self.chamadas]


@pytest.fixture
def contrato():
    return _contrato_do_get()


async def test_alterar_contrato_sem_confirmar_so_mostra_a_diferenca(contrato):
    t = TransporteFalso({("GET", "/contratos-arrendamento/4398"): _json(contrato)})
    r = await ClienteArrendamento(t).alterar_contrato(4398, {"mmObjeto": "Novo"}, confirmar=False)
    assert r["executado"] is False
    assert r["diferencas"] == {"mmObjeto": {"de": "Movimentação de granéis", "para": "Novo"}}
    assert ("PUT", "/contratos-arrendamento/4398") not in t.metodos()


async def test_alterar_contrato_confirmado_envia_o_registro_inteiro(contrato):
    t = TransporteFalso({("GET", "/contratos-arrendamento/4398"): _json(contrato)})
    r = await ClienteArrendamento(t).alterar_contrato(4398, {"mmObjeto": "Novo"}, confirmar=True)
    assert r["executado"] is True
    put = [j for m, c, j in t.chamadas if m == "PUT"]
    assert len(put) == 1
    assert put[0]["mmObjeto"] == "Novo"
    assert put[0]["cdContrato"] == contrato["cdContrato"]
    assert len(put[0]) == 46


async def test_alterar_contrato_sem_mudanca_nao_envia_nada(contrato):
    t = TransporteFalso({("GET", "/contratos-arrendamento/4398"): _json(contrato)})
    r = await ClienteArrendamento(t).alterar_contrato(
        4398, {"mmObjeto": contrato["mmObjeto"]}, confirmar=True
    )
    assert r["executado"] is False
    assert r["diferencas"] == {}
    assert all(m == "GET" for m, _ in t.metodos())


async def test_excluir_contrato_com_dependencias_exige_remover_dependencias():
    analise = {"idContratoArrendamento": 4398, "possuiAditivos": False, "dependencias": [
        {"codigo": "arquivos", "descricao": "Arquivos", "quantidade": 2},
    ]}
    t = TransporteFalso({("GET", "/contratos-arrendamento/4398/analise-exclusao"): _json(analise)})
    with pytest.raises(ErroValidacao, match="Arquivos"):
        await ClienteArrendamento(t).excluir_contrato(4398, remover_dependencias=False, confirmar=True)
    assert "DELETE" not in [m for m, _ in t.metodos()]


async def test_excluir_contrato_confirmado_com_dependencias_usa_o_parametro_do_front(contrato):
    analise = {"idContratoArrendamento": 4398, "possuiAditivos": False, "dependencias": [
        {"codigo": "arquivos", "descricao": "Arquivos", "quantidade": 2},
    ]}
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4398/analise-exclusao"): _json(analise),
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
        ("GET", "/arquivos/por-contrato/4398"): _json([]),
    })
    r = await ClienteArrendamento(t).excluir_contrato(4398, remover_dependencias=True, confirmar=True)
    assert r["executado"] is True
    assert ("DELETE", "/contratos-arrendamento/4398?removerDependencias=true") in t.metodos()


async def test_excluir_contrato_sem_confirmar_nao_apaga(contrato):
    analise = {"idContratoArrendamento": 4398, "possuiAditivos": False, "dependencias": []}
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4398/analise-exclusao"): _json(analise),
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
    })
    r = await ClienteArrendamento(t).excluir_contrato(4398, remover_dependencias=False, confirmar=False)
    assert r["executado"] is False
    assert "DELETE" not in [m for m, _ in t.metodos()]


async def test_alterar_subentidade_de_chave_composta_usa_o_caminho_do_front():
    atuais = [{"idTipoServico": 3, "idContratoArrendamento": 4398, "noTipoServico": "Carga"}]
    t = TransporteFalso({("GET", "/tipos-servicos-contrato/por-contrato/4398"): _json(atuais)})
    r = await ClienteArrendamento(t).alterar_subentidade(
        "tipos-servicos-contrato", 4398, 3, {"idTipoServico": 5}, confirmar=True
    )
    assert r["executado"] is True
    assert ("PUT", "/tipos-servicos-contrato/4398/3") in t.metodos()


async def test_alterar_subentidade_inexistente_e_erro():
    t = TransporteFalso({("GET", "/observacoes/por-contrato/4398"): _json([])})
    with pytest.raises(ErroValidacao, match="99"):
        await ClienteArrendamento(t).alterar_subentidade(
            "observacoes", 4398, 99, {"dsObservacao": "x"}, confirmar=True
        )


async def test_incluir_subentidade_sem_confirmar_devolve_o_payload():
    t = TransporteFalso({})
    r = await ClienteArrendamento(t).incluir_subentidade(
        "observacoes", 4398,
        {"noResponsavel": "x", "dsObservacao": "y", "dtObservacao": "2026-10-06"},
        confirmar=False,
    )
    assert r["executado"] is False
    assert r["payload"]["idContratoArrendamento"] == 4398
    assert t.chamadas == []


def _rotas_versoes(contrato, aditivos, encerrados_por_versao):
    """Contrato 4398 com aditivos (resposta em PascalCase, como a API) e encerramentos por versão."""
    rotas = {
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
        ("GET", "/contratos-arrendamento-aditivos/por-contrato-pai/4398"): _json([
            {"IDContratoArrendamento": a, "IDContratoArrendamentoPai": 4398, "NRVersao": v} for a, v in aditivos
        ]),
    }
    for versao in [4398] + [a for a, _ in aditivos]:
        rotas[("GET", f"/contratos-encerrados/por-contrato/{versao}")] = _json(encerrados_por_versao.get(versao, []))
    return rotas


ENCERRAMENTO = {"dtFinalizacaoContrato": "2026-10-06", "dsMotivo": "Fim"}


async def test_encerramento_vai_para_a_versao_mais_recente_como_na_tela(contrato):
    rotas = _rotas_versoes(contrato, [(4500, 2), (4501, 3)], {})
    rotas[("POST", "/contratos-encerrados")] = _json({"idContratoEncerrado": 9, "idContratoArrendamento": 4501})
    t = TransporteFalso(rotas)
    r = await ClienteArrendamento(t).incluir_subentidade("contratos-encerrados", 4398, ENCERRAMENTO, confirmar=True)
    post = [j for m, c, j in t.chamadas if m == "POST"]
    assert post[0]["idContratoArrendamento"] == 4501
    assert r["executado"] is True


async def test_encerramento_de_contrato_sem_aditivo_fica_no_proprio_contrato(contrato):
    t = TransporteFalso(_rotas_versoes(contrato, [], {}))
    r = await ClienteArrendamento(t).incluir_subentidade("contratos-encerrados", 4398, ENCERRAMENTO, confirmar=False)
    assert r["payload"]["idContratoArrendamento"] == 4398


async def test_encerramento_informado_pelo_id_de_um_aditivo_antigo_tambem_vai_para_o_mais_recente(contrato):
    rotas = _rotas_versoes(contrato, [(4500, 2), (4501, 3)], {})
    rotas[("GET", "/contratos-arrendamento/4500")] = _json({**contrato, "idContratoArrendamento": 4500, "idContratoArrendamentoPai": 4398})
    t = TransporteFalso(rotas)
    r = await ClienteArrendamento(t).incluir_subentidade("contratos-encerrados", 4500, ENCERRAMENTO, confirmar=False)
    assert r["payload"]["idContratoArrendamento"] == 4501


async def test_segundo_encerramento_e_recusado_mesmo_se_o_primeiro_estiver_em_outra_versao(contrato):
    existente = {4398: [{"idContratoEncerrado": 1, "idContratoArrendamento": 4398}]}
    t = TransporteFalso(_rotas_versoes(contrato, [(4500, 2)], existente))
    with pytest.raises(ErroValidacao, match="encerramento"):
        await ClienteArrendamento(t).incluir_subentidade("contratos-encerrados", 4398, ENCERRAMENTO, confirmar=True)
    assert "POST" not in [m for m, _ in t.metodos()]


async def test_alterar_encerramento_gravado_no_aditivo_informando_o_contrato_original(contrato):
    existente = {4500: [{"idContratoEncerrado": 7, "idContratoArrendamento": 4500,
                         "dtFinalizacaoContrato": "2026-10-06T03:00:00", "dsMotivo": "Fim"}]}
    t = TransporteFalso(_rotas_versoes(contrato, [(4500, 2)], existente))
    r = await ClienteArrendamento(t).alterar_subentidade(
        "contratos-encerrados", 4398, 7, {"dsMotivo": "Outro"}, confirmar=True
    )
    put = [(c, j) for m, c, j in t.chamadas if m == "PUT"]
    assert put == [("/contratos-encerrados/7", {
        "idContratoArrendamento": 4500, "dtFinalizacaoContrato": "2026-10-06T03:00:00.000Z", "dsMotivo": "Outro",
    })]
    assert r["executado"] is True


async def test_busca_monta_querystring_sem_filtros_vazios():
    t = TransporteFalso({})
    t.rotas[("GET", "/contratos-arrendamento/resumo?pagina=2&tamanhoPagina=20&cdTrigrama=SSZ")] = _json({"itens": []})
    await ClienteArrendamento(t).buscar_contratos(pagina=2, tamanho_pagina=20, cdTrigrama="SSZ", noFantasiaEmpresa="")
    assert t.metodos() == [("GET", "/contratos-arrendamento/resumo?pagina=2&tamanhoPagina=20&cdTrigrama=SSZ")]


async def test_filtro_de_decisao_judicial_usa_sim_e_nao_como_o_select_do_front():
    esperadas = [
        ("GET", "/contratos-arrendamento/resumo?pagina=1&tamanhoPagina=20&possuiDecisaoJudicial=Sim"),
        ("GET", "/relatorios/contratos-arrendamento?possuiDecisaoJudicial=Nao"),
    ]
    t = TransporteFalso({rota: _json([]) for rota in esperadas})
    await ClienteArrendamento(t).buscar_contratos(possuiDecisaoJudicial=True)
    await ClienteArrendamento(t).relatorio_contratos(possuiDecisaoJudicial=False)
    assert t.metodos() == esperadas


async def test_opcao_desconhecida_lista_as_validas():
    with pytest.raises(ErroValidacao, match="portos"):
        await ClienteArrendamento(TransporteFalso({})).opcoes("porto")


async def test_403_json_da_api_vira_erro_de_permissao_com_o_detalhe():
    t = TransporteFalso({("GET", "/auth/usuarios"): _json({"detail": "Usuario sem permissao"}, 403)})
    with pytest.raises(ErroArrendamento) as e:
        await ClienteArrendamento(t).listar_usuarios()
    assert e.value.origem == "permissao"
    assert "Usuario sem permissao" in str(e.value)


async def test_403_html_da_borda_vira_erro_de_waf():
    t = TransporteFalso({("POST", "/observacoes"): Resposta(
        403, {"server": "cloudflare", "content-type": "text/html"}, b"Attention Required"
    )})
    with pytest.raises(ErroArrendamento) as e:
        await ClienteArrendamento(t).incluir_subentidade(
            "observacoes", 4398,
            {"noResponsavel": "x", "dsObservacao": "y", "dtObservacao": "2026-10-06"},
            confirmar=True,
        )
    assert e.value.origem == "cloudflare_waf"


async def test_erro_500_usa_o_title_do_problem_details():
    t = TransporteFalso({("GET", "/contratos-arrendamento/1"): _json({"title": "Falha interna"}, 500)})
    with pytest.raises(ErroArrendamento, match="Falha interna") as e:
        await ClienteArrendamento(t).obter_contrato(1)
    assert e.value.origem == "api"


ADITIVO_PASCAL = {
    "IDContratoArrendamento": 4407, "IDContratoArrendamentoPai": 4406, "CDContrato": "X/2026",
    "DTFimContrato": "2051-10-01T03:00:00", "Outorgada": "EMPRESA", "NRVersao": 2,
    "DTcriacao": "2026-10-07T03:00:00", "DTAssinaturaAditivo": "2026-10-05T03:00:00",
}


@pytest.mark.parametrize("pascal, camel", [
    ("IDContratoArrendamento", "idContratoArrendamento"),
    ("NRVersao", "nrVersao"),
    ("DTcriacao", "dTcriacao"),  # o front usa exatamente esse nome
    ("Outorgada", "outorgada"),
    ("CDArea", "cdArea"),
    ("nrVersao", "nrVersao"),
])
def test_chave_pascal_vira_o_camel_do_front(pascal, camel):
    from mcp_arrendamento.cliente import camel_como_front
    assert camel_como_front(pascal) == camel


async def test_aditivos_em_pascal_case_sao_devolvidos_em_camel_case():
    t = TransporteFalso({("GET", "/contratos-arrendamento-aditivos/por-contrato-pai/4406"): _json([ADITIVO_PASCAL])})
    itens = await ClienteArrendamento(t).listar_aditivos(4406)
    assert itens[0]["idContratoArrendamento"] == 4407
    assert itens[0]["nrVersao"] == 2
    assert "NRVersao" not in itens[0]


async def test_segundo_aditivo_usa_a_versao_seguinte_mesmo_com_resposta_em_pascal_case(contrato):
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
        ("GET", "/contratos-arrendamento-aditivos/por-contrato-pai/4398"): _json([ADITIVO_PASCAL]),
    })
    r = await ClienteArrendamento(t).criar_aditivo(4398, {"dtAssinaturaAditivo": "2026-11-01"}, confirmar=False)
    assert r["payload"]["nrVersao"] == 3


async def test_contrato_com_aditivo_nao_e_excluido_nem_com_remover_dependencias():
    # O sistema responde 409 nesse caso; o servidor avisa antes, com os ids dos aditivos.
    analise = {"idContratoArrendamento": 4406, "possuiAditivos": True, "dependencias": []}
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4406/analise-exclusao"): _json(analise),
        ("GET", "/contratos-arrendamento-aditivos/por-contrato-pai/4406"): _json([ADITIVO_PASCAL]),
    })
    with pytest.raises(ErroValidacao, match="4407"):
        await ClienteArrendamento(t).excluir_contrato(4406, remover_dependencias=True, confirmar=True)
    assert "DELETE" not in [m for m, _ in t.metodos()]


async def test_excluir_contrato_com_dependencias_apaga_os_anexos_um_a_um_antes(contrato):
    # Com removerDependencias o sistema apaga o registro do anexo mas deixa o arquivo no
    # armazenamento (chave <idContrato>/<nome>). O DELETE /arquivos/{id} limpa os dois.
    analise = {"idContratoArrendamento": 4398, "possuiAditivos": False, "dependencias": [
        {"codigo": "arquivos", "descricao": "Arquivos", "quantidade": 2},
    ]}
    arquivos = [{"idArquivo": 11, "noLink": "a.pdf"}, {"idArquivo": 12, "noLink": "b.pdf"}]
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4398/analise-exclusao"): _json(analise),
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
        ("GET", "/arquivos/por-contrato/4398"): _json(arquivos),
    })
    r = await ClienteArrendamento(t).excluir_contrato(4398, remover_dependencias=True, confirmar=True)
    deletes = [c for m, c in t.metodos() if m == "DELETE"]
    assert deletes == ["/arquivos/11", "/arquivos/12", "/contratos-arrendamento/4398?removerDependencias=true"]
    assert [a["idArquivo"] for a in r["arquivos_excluidos"]] == [11, 12]


async def test_previa_da_exclusao_lista_os_anexos_que_serao_apagados(contrato):
    analise = {"idContratoArrendamento": 4398, "possuiAditivos": False, "dependencias": [
        {"codigo": "arquivos", "descricao": "Arquivos", "quantidade": 1},
    ]}
    t = TransporteFalso({
        ("GET", "/contratos-arrendamento/4398/analise-exclusao"): _json(analise),
        ("GET", "/contratos-arrendamento/4398"): _json(contrato),
        ("GET", "/arquivos/por-contrato/4398"): _json([{"idArquivo": 11, "noLink": "a.pdf"}]),
    })
    r = await ClienteArrendamento(t).excluir_contrato(4398, remover_dependencias=True, confirmar=False)
    assert r["executado"] is False
    assert r["arquivos"] == [{"idArquivo": 11, "noLink": "a.pdf"}]
    assert "DELETE" not in [m for m, _ in t.metodos()]
