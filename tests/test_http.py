import stat

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_arrendamento.http import Porteiro, carregar_token


def _cliente(token="segredo-de-teste-com-mais-de-32-caracteres", host="127.0.0.1:8765"):
    async def ok(_):
        return PlainTextResponse("ok")
    app = Porteiro(Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])]), token)
    return TestClient(app, base_url=f"http://{host}")


def test_sem_token_e_recusado():
    assert _cliente().post("/mcp").status_code == 401


def test_token_errado_e_recusado():
    assert _cliente().post("/mcp", headers={"Authorization": "Bearer outro"}).status_code == 401


def test_token_certo_passa():
    r = _cliente().post("/mcp", headers={"Authorization": "Bearer segredo-de-teste-com-mais-de-32-caracteres"})
    assert r.status_code == 200 and r.text == "ok"


def test_host_que_nao_e_local_e_recusado_mesmo_com_token():
    # DNS rebinding: uma página externa resolvendo o próprio domínio para 127.0.0.1.
    r = _cliente(host="evil.example:8765").post("/mcp", headers={"Authorization": "Bearer segredo-de-teste-com-mais-de-32-caracteres"})
    assert r.status_code == 403


def test_token_e_criado_uma_vez_e_fica_legivel_so_para_o_dono(tmp_path):
    arquivo = tmp_path / "token-http"
    primeiro = carregar_token(arquivo, {})
    assert len(primeiro) >= 32 and carregar_token(arquivo, {}) == primeiro
    assert stat.S_IMODE(arquivo.stat().st_mode) == 0o600


def test_token_da_variavel_de_ambiente_prevalece(tmp_path):
    assert carregar_token(tmp_path / "t", {"ARRENDAMENTO_TOKEN_HTTP": "x" * 40}) == "x" * 40


def test_arquivo_de_token_vazio_e_refeito_em_vez_de_virar_token_vazio(tmp_path):
    arquivo = tmp_path / "token-http"
    arquivo.write_text("")
    token = carregar_token(arquivo, {})
    assert len(token) >= 32 and arquivo.read_text() == token


def test_token_curto_demais_na_variavel_de_ambiente_e_recusado(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="ARRENDAMENTO_TOKEN_HTTP"):
        carregar_token(tmp_path / "t", {"ARRENDAMENTO_TOKEN_HTTP": "abc"})


def test_porteiro_nao_sobe_com_token_vazio():
    import pytest
    with pytest.raises(ValueError):
        Porteiro(lambda *a: None, "")


def test_pedido_sem_cabecalho_nunca_passa_mesmo_se_o_token_fosse_vazio():
    porteiro = Porteiro.__new__(Porteiro)  # simula um porteiro mal configurado
    async def ok(_):
        return PlainTextResponse("ok")
    porteiro._app = Starlette(routes=[Route("/mcp", ok, methods=["POST"])])
    porteiro._token = ""
    assert TestClient(porteiro, base_url="http://127.0.0.1:8765").post("/mcp").status_code == 401


TOKEN = "segredo-de-teste-com-mais-de-32-caracteres"


def test_host_publico_explicito_exige_token_e_nao_libera_outros_hosts():
    async def ok(_):
        return PlainTextResponse("ok")
    app = Porteiro(Starlette(routes=[Route("/mcp", ok)]), TOKEN,
                   ("127.0.0.1", "casa7.tail3c84be.ts.net"))
    cliente = TestClient(app, base_url="https://casa7.tail3c84be.ts.net")
    assert cliente.get("/mcp").status_code == 401
    assert cliente.get("/mcp", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert cliente.get("/mcp", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
    assert cliente.get("/mcp", headers={"Host": "evil.example", "Authorization": "Bearer " + TOKEN}).status_code == 403


def test_servidor_prova_que_conhece_o_token_sem_revela_lo():
    from mcp_arrendamento.http import prova_de_identidade
    r = _cliente(token=TOKEN).get("/identidade?desafio=abc123")
    assert r.status_code == 200
    assert r.text == prova_de_identidade(TOKEN, "abc123", 8765) and TOKEN not in r.text


def test_prova_muda_com_o_desafio_e_com_o_token():
    from mcp_arrendamento.http import prova_de_identidade
    assert prova_de_identidade(TOKEN, "a", 1) != prova_de_identidade(TOKEN, "b", 1)
    assert prova_de_identidade(TOKEN, "a", 1) != prova_de_identidade(TOKEN + "x", "a", 1)
    assert prova_de_identidade(TOKEN, "a", 1) != prova_de_identidade(TOKEN, "a", 2)
