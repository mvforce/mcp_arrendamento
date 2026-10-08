import json

import pytest

from mcp_arrendamento.server import mcp

LEITURA = {
    "arrendamento_sessao", "arrendamento_buscar_contratos", "arrendamento_consultar_contrato",
    "arrendamento_listar_aditivos", "arrendamento_listar_registros", "arrendamento_listar_opcoes",
    "arrendamento_consultar_cnpj", "arrendamento_consultar_campos", "arrendamento_relatorio_painel",
    "arrendamento_relatorio_vencimentos", "arrendamento_relatorio_lei_12815",
    "arrendamento_relatorio_contratos", "arrendamento_listar_arquivos", "arrendamento_baixar_arquivo",
    "arrendamento_listar_usuarios", "arrendamento_listar_perfis",
    "arrendamento_listar_solicitacoes_acesso", "arrendamento_consultar_auditoria_login",
}
ADITIVAS = {
    "arrendamento_criar_contrato", "arrendamento_criar_aditivo", "arrendamento_incluir_registro",
    "arrendamento_enviar_arquivo",
}
DESTRUTIVAS = {
    "arrendamento_alterar_contrato", "arrendamento_excluir_contrato",
    "arrendamento_alterar_registro", "arrendamento_excluir_registro", "arrendamento_excluir_arquivo",
}


@pytest.fixture(scope="module")
async def ferramentas():
    return {t.name: t for t in await mcp.list_tools()}


async def test_expoe_exatamente_as_ferramentas_previstas(ferramentas):
    assert set(ferramentas) == LEITURA | ADITIVAS | DESTRUTIVAS


async def test_toda_ferramenta_tem_titulo(ferramentas):
    assert [n for n, t in ferramentas.items() if not t.title] == []


async def test_leituras_sao_marcadas_como_somente_leitura(ferramentas):
    for nome in LEITURA:
        assert ferramentas[nome].annotations.readOnlyHint is True, nome


async def test_alterar_e_excluir_sao_destrutivas(ferramentas):
    for nome in DESTRUTIVAS:
        a = ferramentas[nome].annotations
        assert a.readOnlyHint is False and a.destructiveHint is True, nome


async def test_inclusoes_escrevem_mas_nao_destroem(ferramentas):
    for nome in ADITIVAS:
        a = ferramentas[nome].annotations
        assert a.readOnlyHint is False and a.destructiveHint is False, nome


async def test_toda_escrita_exige_confirmar_e_o_padrao_e_falso(ferramentas):
    for nome in ADITIVAS | DESTRUTIVAS:
        props = ferramentas[nome].inputSchema["properties"]
        assert props["confirmar"]["default"] is False, nome


async def test_recurso_aparece_como_enum_no_schema(ferramentas):
    schema = ferramentas["arrendamento_incluir_registro"].inputSchema
    texto = json.dumps(schema)
    assert "decisoes-judiciais" in texto and "situacoes-adimplemento" in texto


async def test_consultar_campos_descreve_obrigatorios_e_opcoes_sem_tocar_a_api():
    resultado = await mcp.call_tool("arrendamento_consultar_campos", {"recurso": "bens"})
    dados = json.loads(resultado[0][0].text) if isinstance(resultado, tuple) else json.loads(resultado[0].text)
    campos = {c["nome"]: c for c in dados["campos"]}
    assert campos["dsBem"]["obrigatorio"] is True
    assert campos["noClassificacao"]["opcoes"] == ["Equipamento", "Imovel", "Utilidade"]


async def test_sessao_informa_o_ambiente_conectado(monkeypatch):
    from types import SimpleNamespace

    from mcp_arrendamento import server
    from tests.test_sessao import _token_valido

    class ClienteFalso:
        async def me(self):
            return {"nome": "Fulano", "perfil": "Administrador"}

    monkeypatch.setattr(server, "_estado", {
        "cliente": ClienteFalso(),
        "sessao": SimpleNamespace(token=_token_valido()),
        "config": SimpleNamespace(base_url="https://hmg-arrendamento.antaq.gov.br"),
    })
    resultado = await mcp.call_tool("arrendamento_sessao", {})
    dados = json.loads(resultado[0][0].text) if isinstance(resultado, tuple) else json.loads(resultado[0].text)
    assert dados["ambiente"] == "https://hmg-arrendamento.antaq.gov.br"


async def test_consultar_campos_do_contrato_lista_os_obrigatorios_da_tela():
    resultado = await mcp.call_tool("arrendamento_consultar_campos", {"recurso": "contrato"})
    dados = json.loads(resultado[0][0].text) if isinstance(resultado, tuple) else json.loads(resultado[0].text)
    obrigatorios = {c["nome"] for c in dados["campos"] if c["obrigatorio"]}
    assert {"cdContrato", "cdTrigrama", "mmObjeto", "stContrato"} <= obrigatorios


async def test_enviar_arquivo_recusa_chave_ssh_antes_de_qualquer_acesso_a_api(monkeypatch, tmp_path):
    from mcp_arrendamento import server

    monkeypatch.setattr(server, "_estado", {})  # sem cliente: se tentasse a API, criaria o Chrome
    monkeypatch.setenv("ARRENDAMENTO_PASTAS_ENVIO", str(tmp_path))
    oculta = tmp_path / ".ssh"
    oculta.mkdir()
    (oculta / "id_ed25519").write_text("chave")
    with pytest.raises(Exception, match=r"\[validacao\].*oculto"):
        await mcp.call_tool(
            "arrendamento_enviar_arquivo",
            {"id_contrato": 1, "caminho_arquivo": str(oculta / "id_ed25519"), "confirmar": True},
        )
    assert server._estado == {}
