from pathlib import Path

import pytest

from mcp_arrendamento.config import carregar_config


def test_padroes_apontam_para_producao_e_perfil_no_home():
    c = carregar_config({})
    assert c.base_url == "https://arrendamento.antaq.gov.br"
    assert c.perfil_dir == Path.home() / ".mcp-arrendamento" / "perfil-chrome"
    assert c.canal == "chrome"
    assert c.login_interativo is True


def test_janela_padrao_e_minimizada():
    # Headless leva a caixa "Confirme que é humano" do Cloudflare; janela real minimizada passa.
    assert carregar_config({}).janela == "minimizada"


def test_janela_invalida_e_recusada():
    with pytest.raises(ValueError, match="minimizada"):
        carregar_config({"ARRENDAMENTO_JANELA": "escondida"})


def test_variaveis_de_ambiente_sobrescrevem():
    c = carregar_config({
        "ARRENDAMENTO_URL": "https://homolog.exemplo/",
        "ARRENDAMENTO_JANELA": "visivel",
        "ARRENDAMENTO_CANAL": "chromium",
        "ARRENDAMENTO_LOGIN_INTERATIVO": "0",
        "ARRENDAMENTO_PERFIL": "/tmp/perfil",
    })
    assert c.base_url == "https://homolog.exemplo"
    assert c.janela == "visivel"
    assert c.canal is None  # chromium = Chromium do Playwright, sem channel
    assert c.login_interativo is False
    assert c.perfil_dir == Path("/tmp/perfil")


def test_pastas_de_envio_padrao_sao_downloads_documentos_e_mesa():
    c = carregar_config({})
    assert c.pastas_envio == (
        Path.home() / "Downloads", Path.home() / "Documents", Path.home() / "Desktop",
    )


def test_pastas_de_envio_vem_da_variavel_separadas_por_dois_pontos():
    c = carregar_config({"ARRENDAMENTO_PASTAS_ENVIO": "/tmp/a:~/Anexos"})
    assert c.pastas_envio == (Path("/tmp/a"), Path.home() / "Anexos")
