import pytest

from mcp_arrendamento.erros import ErroValidacao
from mcp_arrendamento.seguranca import arquivo_para_envio


@pytest.fixture
def raiz(tmp_path):
    pasta = tmp_path / "Documentos"
    pasta.mkdir()
    return pasta


def test_aceita_documento_dentro_de_pasta_permitida(raiz):
    pdf = raiz / "contrato.pdf"
    pdf.write_bytes(b"%PDF")
    assert arquivo_para_envio(str(pdf), [raiz]) == pdf.resolve()


def test_recusa_arquivo_fora_das_pastas_permitidas(raiz, tmp_path):
    fora = tmp_path / "fora.pdf"
    fora.write_bytes(b"%PDF")
    with pytest.raises(ErroValidacao, match="pastas permitidas"):
        arquivo_para_envio(str(fora), [raiz])


def test_recusa_pasta_oculta_mesmo_dentro_da_raiz(raiz):
    oculta = raiz / ".ssh"
    oculta.mkdir()
    chave = oculta / "copia.pdf"
    chave.write_bytes(b"x")
    with pytest.raises(ErroValidacao, match="oculto"):
        arquivo_para_envio(str(chave), [raiz])


def test_recusa_arquivo_oculto(raiz):
    env = raiz / ".env.pdf"
    env.write_bytes(b"x")
    with pytest.raises(ErroValidacao, match="oculto"):
        arquivo_para_envio(str(env), [raiz])


def test_link_simbolico_para_fora_da_raiz_e_recusado(raiz, tmp_path):
    segredo = tmp_path / "id_ed25519.pdf"
    segredo.write_bytes(b"chave")
    atalho = raiz / "inocente.pdf"
    atalho.symlink_to(segredo)
    with pytest.raises(ErroValidacao, match="pastas permitidas"):
        arquivo_para_envio(str(atalho), [raiz])


@pytest.mark.parametrize("nome", ["chave.pem", "id_ed25519", "script.sh"])
def test_recusa_extensao_que_nao_e_documento(raiz, nome):
    arquivo = raiz / nome
    arquivo.write_bytes(b"x")
    with pytest.raises(ErroValidacao, match="extensão"):
        arquivo_para_envio(str(arquivo), [raiz])


def test_recusa_arquivo_inexistente(raiz):
    with pytest.raises(ErroValidacao, match="não encontrado"):
        arquivo_para_envio(str(raiz / "nao-existe.pdf"), [raiz])
