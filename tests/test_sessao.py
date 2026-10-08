import time

import pytest

from mcp_arrendamento.erros import ErroArrendamento
from mcp_arrendamento.transporte import Resposta, Sessao
from tests.test_transporte import _token

DESAFIO = Resposta(403, {"cf-mitigated": "challenge", "server": "cloudflare"}, b"Just a moment...")


def _token_valido(horas=8.0) -> str:
    return _token({"sub": 21, "exp": time.time() + horas * 3600})


class PaginaFalsa:
    def __init__(self, respostas=(), silencioso=None, interativo=None, recusa=None):
        self.recusa = recusa
        self.respostas = list(respostas)
        self.silencioso = list(silencioso or [])
        self.interativo = list(interativo or [])
        self.tokens_enviados: list[str] = []
        self.desafios_resolvidos = 0
        self.logins_interativos = 0

    async def fetch(self, metodo, caminho, token, json=None, arquivo=None, campos=None):
        self.tokens_enviados.append(token)
        return self.respostas.pop(0) if self.respostas else Resposta(200, {}, b"{}")

    async def token_silencioso(self):
        if self.recusa:
            raise ErroArrendamento(self.recusa, "acesso")
        return self.silencioso.pop(0) if self.silencioso else None

    async def login_interativo(self):
        self.logins_interativos += 1
        return self.interativo.pop(0) if self.interativo else None

    async def resolver_desafio(self):
        self.desafios_resolvidos += 1

    async def fechar(self):
        pass


async def test_primeira_chamada_obtem_token_silencioso_e_envia():
    t = _token_valido()
    pagina = PaginaFalsa(silencioso=[t])
    resp = await Sessao(pagina).requisitar("GET", "/auth/me")
    assert resp.status == 200
    assert pagina.tokens_enviados == [t]


async def test_reaproveita_o_token_enquanto_valido():
    t = _token_valido()
    pagina = PaginaFalsa(silencioso=[t])
    sessao = Sessao(pagina)
    await sessao.requisitar("GET", "/a")
    await sessao.requisitar("GET", "/b")
    assert pagina.tokens_enviados == [t, t]


async def test_renova_antes_de_expirar():
    quase_vencido, novo = _token_valido(horas=0.01), _token_valido()
    pagina = PaginaFalsa(silencioso=[quase_vencido, novo])
    sessao = Sessao(pagina)
    await sessao.requisitar("GET", "/a")
    await sessao.requisitar("GET", "/b")
    assert pagina.tokens_enviados[-1] == novo


async def test_401_renova_o_token_e_tenta_de_novo_uma_vez():
    velho, novo = _token_valido(), _token_valido(horas=7)
    pagina = PaginaFalsa(respostas=[Resposta(401), Resposta(200, {}, b"{}")], silencioso=[velho, novo])
    resp = await Sessao(pagina).requisitar("GET", "/auth/me")
    assert resp.status == 200
    assert pagina.tokens_enviados == [velho, novo]


async def test_desafio_do_cloudflare_e_resolvido_e_a_chamada_repetida():
    pagina = PaginaFalsa(respostas=[DESAFIO, Resposta(200, {}, b"{}")], silencioso=[_token_valido()])
    resp = await Sessao(pagina).requisitar("GET", "/auth/me")
    assert resp.status == 200
    assert pagina.desafios_resolvidos == 1


async def test_sem_sso_e_sem_login_interativo_pede_para_logar():
    pagina = PaginaFalsa(silencioso=[None])
    with pytest.raises(ErroArrendamento) as e:
        await Sessao(pagina, login_interativo=False).requisitar("GET", "/auth/me")
    assert e.value.origem == "sessao"
    assert "mcp-arrendamento login" in str(e.value)


async def test_sem_sso_abre_login_interativo_quando_permitido():
    t = _token_valido()
    pagina = PaginaFalsa(silencioso=[None], interativo=[t])
    await Sessao(pagina, login_interativo=True).requisitar("GET", "/auth/me")
    assert pagina.logins_interativos == 1
    assert pagina.tokens_enviados == [t]


async def test_recusa_do_sistema_chega_com_a_mensagem_e_nao_abre_login_interativo():
    pagina = PaginaFalsa(recusa="Usuario cadastrado, mas inativo no sistema.")
    with pytest.raises(ErroArrendamento) as e:
        await Sessao(pagina, login_interativo=True).requisitar("GET", "/auth/me")
    assert e.value.origem == "acesso"
    assert "inativo" in str(e.value)
    assert pagina.logins_interativos == 0
