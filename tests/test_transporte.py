import base64
import json

from mcp_arrendamento.transporte import (
    Resposta,
    decodificar_token,
    eh_bloqueio_waf,
    eh_desafio_cloudflare,
    extrair_erro_da_url,
    extrair_token_da_url,
    segundos_restantes,
)


def _token(payload: dict) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{corpo}.assinatura"


def test_decodifica_payload_do_token_sem_padding():
    token = _token({"sub": 21, "perfilCodigo": "ADMIN_ANTAQ", "exp": 1791353494})
    assert decodificar_token(token)["perfilCodigo"] == "ADMIN_ANTAQ"


def test_segundos_restantes_usa_exp_do_token():
    token = _token({"exp": 1_000_100})
    assert segundos_restantes(token, agora=1_000_000) == 100


def test_token_ilegivel_conta_como_expirado():
    assert segundos_restantes("lixo", agora=0) == 0


def test_extrai_token_do_fragmento_do_callback():
    url = "https://arrendamento.antaq.gov.br/auth/microsoft/callback#access_token=abc.def&x=1"
    assert extrair_token_da_url(url) == "abc.def"


def test_url_sem_token_devolve_none():
    assert extrair_token_da_url("https://arrendamento.antaq.gov.br/") is None


def test_extrai_erro_do_fragmento_do_callback():
    url = ("https://hmg-arrendamento.antaq.gov.br/auth/microsoft/callback"
           "#error=Usuario%20cadastrado%2C%20mas%20inativo%20no%20sistema.")
    assert extrair_erro_da_url(url) == "Usuario cadastrado, mas inativo no sistema."
    assert extrair_token_da_url(url) is None


def test_url_sem_erro_devolve_none():
    assert extrair_erro_da_url("https://x/auth/microsoft/callback#access_token=a.b") is None


def test_desafio_pelo_cabecalho_cf_mitigated():
    resp = Resposta(403, {"cf-mitigated": "challenge", "server": "cloudflare"}, b"<html>")
    assert eh_desafio_cloudflare(resp)


def test_desafio_pela_pagina_just_a_moment():
    resp = Resposta(403, {"server": "cloudflare"}, b"<title>Just a moment...</title>")
    assert eh_desafio_cloudflare(resp)


def test_403_json_da_api_nao_e_desafio_nem_waf():
    resp = Resposta(
        403,
        {"server": "cloudflare", "content-type": "application/json"},
        b'{"detail":"Usuario sem permissao"}',
    )
    assert not eh_desafio_cloudflare(resp)
    assert not eh_bloqueio_waf(resp)


def test_bloqueio_waf_e_403_html_da_borda_sem_desafio():
    resp = Resposta(
        403,
        {"server": "cloudflare", "content-type": "text/html"},
        b"<title>Attention Required! | Cloudflare</title>",
    )
    assert eh_bloqueio_waf(resp)
    assert not eh_desafio_cloudflare(resp)


def test_resposta_json_e_texto():
    resp = Resposta(200, {"content-type": "application/json"}, '{"a": "ção"}'.encode())
    assert resp.json() == {"a": "ção"}
    assert resp.ok
