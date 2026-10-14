import socket

from mcp_arrendamento.iniciar import cabecalho_do_conector, instrucoes, porta_ocupada, primeira_vez


def test_porta_livre_e_ocupada():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        porta = s.getsockname()[1]
        assert porta_ocupada(porta) is True
    assert porta_ocupada(porta) is False


def test_primeira_vez_so_e_verdade_uma_vez(tmp_path):
    assert primeira_vez(tmp_path) is True
    assert primeira_vez(tmp_path) is False


def test_cabecalho_do_conector_leva_o_prefixo_bearer():
    assert cabecalho_do_conector("abc") == "Bearer abc"


def test_instrucoes_dizem_o_endereco_e_nao_mostram_o_token():
    texto = instrucoes(8765, "https://arrendamento.antaq.gov.br", primeira=True)
    assert "http://127.0.0.1:8765/mcp" in texto
    assert "PRODUÇÃO" in texto
    assert "HOMOLOGAÇÃO" in instrucoes(8765, "https://hmg-arrendamento.antaq.gov.br", primeira=False)


def test_escolha_do_ambiente():
    from mcp_arrendamento.iniciar import AMBIENTES, ambiente_escolhido
    assert ambiente_escolhido("1") == AMBIENTES["1"] and "hmg-" not in AMBIENTES["1"].url
    assert ambiente_escolhido(" 2 ") == AMBIENTES["2"] and "hmg-" in AMBIENTES["2"].url
    assert ambiente_escolhido("") is None and ambiente_escolhido("x") is None


def test_homologacao_usa_perfil_de_chrome_separado():
    from mcp_arrendamento.iniciar import AMBIENTES
    assert AMBIENTES["1"].perfil != AMBIENTES["2"].perfil


def test_pergunta_repete_ate_vir_resposta_valida():
    from mcp_arrendamento.iniciar import AMBIENTES, perguntar_ambiente
    respostas = iter(["", "9", "2"])
    assert perguntar_ambiente(lambda _: next(respostas)) == AMBIENTES["2"]


def test_porta_ocupada_por_outro_programa_nao_e_tratada_como_o_mcp():
    # Um impostor na porta receberia o token que o SEI Pro envia.
    import http.server
    import threading

    from mcp_arrendamento.iniciar import e_o_nosso_servidor

    class Impostor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"qualquer coisa")
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Impostor)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert e_o_nosso_servidor(srv.server_address[1], "t" * 40) is False
    finally:
        srv.shutdown()


def test_primeira_vez_nao_copia_o_token_sozinha():
    texto = instrucoes(8765, "https://arrendamento.antaq.gov.br", primeira=True)
    assert "Copiar token do conector" in texto and "já está na área de transferência" not in texto


def _servidor(resposta):
    """Sobe um servidor local cujo GET é decidido por `resposta(handler)`."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            resposta(self)
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _verdadeiro(token):
    """Responde como o MCP de verdade responderia NESTA porta."""
    from urllib.parse import parse_qs, urlsplit

    from mcp_arrendamento.http import prova_de_identidade

    def resposta(h):
        desafio = parse_qs(urlsplit(h.path).query).get("desafio", [""])[0]
        corpo = prova_de_identidade(token, desafio, h.server.server_address[1]).encode()
        h.send_response(200); h.end_headers(); h.wfile.write(corpo)
    return _servidor(resposta)


TOKEN = "t" * 40


def test_servidor_verdadeiro_e_reconhecido():
    from mcp_arrendamento.iniciar import e_o_nosso_servidor
    srv = _verdadeiro(TOKEN)
    try:
        assert e_o_nosso_servidor(srv.server_address[1], TOKEN) is True
    finally:
        srv.shutdown()


def test_resposta_com_acento_ou_lixo_nao_derruba_a_verificacao():
    from mcp_arrendamento.iniciar import e_o_nosso_servidor

    def acento(h):
        h.send_response(200); h.end_headers(); h.wfile.write("não sou o MCP ção".encode())

    def lixo(h):
        h.wfile.write(b"\x00\xff isto nao e HTTP\r\n\r\n"); h.wfile.flush()

    for resposta in (acento, lixo):
        srv = _servidor(resposta)
        try:
            assert e_o_nosso_servidor(srv.server_address[1], TOKEN) is False
        finally:
            srv.shutdown()


def test_impostor_que_redireciona_para_um_mcp_verdadeiro_em_outra_porta_nao_passa():
    from mcp_arrendamento.iniciar import e_o_nosso_servidor
    real = _verdadeiro(TOKEN)

    def redirecionar(h):
        h.send_response(302)
        h.send_header("Location", f"http://127.0.0.1:{real.server_address[1]}{h.path}")
        h.end_headers()

    impostor = _servidor(redirecionar)
    try:
        assert e_o_nosso_servidor(impostor.server_address[1], TOKEN) is False
    finally:
        impostor.shutdown(); real.shutdown()


def test_impostor_que_repassa_o_desafio_a_um_mcp_em_outra_porta_nao_passa():
    # Sem seguir redirect: o impostor busca a resposta no MCP verdadeiro e a devolve.
    import urllib.request

    from mcp_arrendamento.iniciar import e_o_nosso_servidor
    real = _verdadeiro(TOKEN)

    def repassar(h):
        corpo = urllib.request.urlopen(f"http://127.0.0.1:{real.server_address[1]}{h.path}").read()
        h.send_response(200); h.end_headers(); h.wfile.write(corpo)

    impostor = _servidor(repassar)
    try:
        assert e_o_nosso_servidor(impostor.server_address[1], TOKEN) is False
    finally:
        impostor.shutdown(); real.shutdown()
