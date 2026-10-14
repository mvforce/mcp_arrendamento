import base64
import hashlib
import json

import pytest

from mcp_arrendamento import server
from mcp_arrendamento.erros import ErroValidacao
from mcp_arrendamento.seguranca import nome_para_envio


@pytest.mark.parametrize('nome', ['../contrato.pdf', 'C:\\contrato.pdf', '.oculto.pdf', 'contrato.exe', 'CON.pdf', 'a\n.pdf'])
def test_nome_invalido(nome):
    with pytest.raises(ErroValidacao):
        nome_para_envio(nome)


def test_extensao_preservada():
    with pytest.raises(ErroValidacao):
        nome_para_envio('Contrato.docx', '.pdf')


async def test_conteudo_remoto_e_nome_sem_ler_caminho_local(monkeypatch):
    chamadas = []
    async def executar(op):
        class Cliente:
            async def enviar_arquivo(self, *args):
                chamadas.append(args)
                return {'executado': args[-1]}
        return await op(Cliente())
    monkeypatch.setattr(server, '_executar', executar)
    payload = b'%PDF-1.7\nteste'
    nome = 'Contrato de Cessão de Uso 002-2026 (1234567).pdf'
    for confirmar in (False, True):
        resultado = await server.arrendamento_enviar_arquivo(
            7, 'C:\\caminho-inexistente.pdf', confirmar, nome, base64.b64encode(payload).decode())
        assert resultado['nome_arquivo'] == nome
        assert resultado['sha256'] == hashlib.sha256(payload).hexdigest()
        assert resultado['executado'] is confirmar
        assert 'caminho_local' not in resultado
        assert chamadas[-1] == (7, nome, payload, 'application/pdf', confirmar)


@pytest.mark.parametrize('conteudo', ['', 'nao-e-base64!', 'é'])
async def test_base64_invalido_antes_da_api(monkeypatch, conteudo):
    async def nao_executar(_):
        pytest.fail('Não deve chegar à API')
    monkeypatch.setattr(server, '_executar', nao_executar)
    with pytest.raises(Exception, match='base64|vazio'):
        await server.arrendamento_enviar_arquivo(7, '', False, 'Contrato.pdf', conteudo)


async def test_arquivo_local_nome_legivel_preserva_conteudo(monkeypatch, tmp_path):
    arquivo = tmp_path / 'nome-tecnico.pdf'
    arquivo.write_bytes(b'%PDF-teste')
    monkeypatch.setenv('ARRENDAMENTO_PASTAS_ENVIO', str(tmp_path))
    chamadas = []
    async def executar(op):
        class Cliente:
            async def enviar_arquivo(self, *args):
                chamadas.append(args)
                return {}
        return await op(Cliente())
    monkeypatch.setattr(server, '_executar', executar)
    await server.arrendamento_enviar_arquivo(7, str(arquivo), False, 'Contrato legível.pdf')
    assert chamadas[0][1:3] == ('Contrato legível.pdf', b'%PDF-teste')
    assert arquivo.name == 'nome-tecnico.pdf'


async def test_limite_antes_de_decodificar(monkeypatch):
    monkeypatch.setattr(server.base64, 'b64decode', lambda *a, **k: pytest.fail('Não deve decodificar'))
    with pytest.raises(Exception, match='25 MB'):
        await server.arrendamento_enviar_arquivo(7, '', False, 'Contrato.pdf', 'a' * (4 * ((25 * 1024 * 1024 + 2) // 3) + 4))
