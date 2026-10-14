"""`mcp-arrendamento iniciar`: o que os lançadores de um clique executam.

Sobe o modo HTTP local com mensagens para quem não é técnico: avisa se já está
rodando, copia o cabeçalho do conector na primeira vez e diz o que colar no SEI Pro.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from mcp_arrendamento.http import PORTA_PADRAO, carregar_token

RAIZ = Path.home() / ".mcp-arrendamento"


@dataclass(frozen=True)
class Ambiente:
    nome: str
    url: str
    perfil: Path  # um perfil de Chrome por ambiente: os logins não se misturam


AMBIENTES = {
    "1": Ambiente("PRODUÇÃO", "https://arrendamento.antaq.gov.br", RAIZ / "perfil-chrome"),
    "2": Ambiente("HOMOLOGAÇÃO", "https://hmg-arrendamento.antaq.gov.br", RAIZ / "perfil-hmg"),
}


def ambiente_escolhido(resposta: str) -> Optional[Ambiente]:
    return AMBIENTES.get(resposta.strip())


def perguntar_ambiente(ler: Callable[[str], str] = input) -> Ambiente:
    print("\n  Qual ambiente do Sistema de Arrendamento você quer usar?\n")
    print("    1 - Produção     (dados reais)")
    print("    2 - Homologação  (testes; precisa da VPN da ANTAQ)\n")
    while True:
        ambiente = ambiente_escolhido(ler("  Digite 1 ou 2 e pressione Enter: "))
        if ambiente:
            return ambiente


def porta_ocupada(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def primeira_vez(raiz: Path) -> bool:
    marca = raiz / "conector-configurado"
    if marca.exists():
        return False
    raiz.mkdir(parents=True, exist_ok=True)
    marca.touch()
    return True


def cabecalho_do_conector(token: str) -> str:
    return f"Bearer {token}"


def copiar(texto: str) -> bool:
    comando = ["clip"] if sys.platform == "win32" else ["pbcopy"] if sys.platform == "darwin" else None
    if comando is None:
        return False
    try:
        subprocess.run(comando, input=texto.encode("utf-16" if sys.platform == "win32" else "utf-8"), check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def e_o_nosso_servidor(porta: int, token: str) -> bool:
    """Quem ocupa a porta prova que conhece o token (sem que o token trafegue).

    Qualquer resposta inesperada conta como "não é o nosso": quem responde pode ser um
    programa hostil, então nada do que ele mande pode derrubar esta verificação.
    """
    import hmac
    import secrets
    import urllib.request

    from mcp_arrendamento.http import prova_de_identidade

    class SemRedirecionar(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # a prova tem de vir desta porta
            return None

    desafio = secrets.token_hex(16)
    esperado = prova_de_identidade(token, desafio, porta).encode()
    try:
        abrir = urllib.request.build_opener(SemRedirecionar, urllib.request.ProxyHandler({})).open
        with abrir(f"http://127.0.0.1:{porta}/identidade?desafio={desafio}", timeout=3) as r:
            if r.status != 200:
                return False
            resposta = r.read(len(esperado) + 1)
    except Exception:  # noqa: BLE001 — rede, HTTP malformado, redirect recusado: tudo é "não"
        return False
    return hmac.compare_digest(resposta, esperado)


def _area_de_transferencia() -> str:
    comando = (["powershell", "-NoProfile", "-Command", "Get-Clipboard"] if sys.platform == "win32"
               else ["pbpaste"] if sys.platform == "darwin" else None)
    if comando is None:
        return ""
    try:
        return subprocess.run(comando, capture_output=True, timeout=10).stdout.decode(errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def copiar_token_por_um_tempo(token: str, segundos: int = 60) -> int:
    """Copia só a pedido do usuário e apaga depois, para o valor não ficar na área de transferência."""
    import time

    valor = cabecalho_do_conector(token)
    if not copiar(valor):
        print(f"  Não consegui copiar. O valor está em {RAIZ / 'token-http'} (cole precedido de 'Bearer ').")
        return 1
    print('  Valor copiado. Cole agora no campo "Valor" do conector no SEI Pro (Ctrl+V ou Cmd+V).')
    print(f"  Por segurança, ele sai da área de transferência em {segundos} segundos. Não feche esta janela.")
    time.sleep(segundos)
    if _area_de_transferencia() == valor:
        copiar("")
    print("  Pronto. Pode fechar esta janela.")
    return 0


def instrucoes(porta: int, base_url: str, primeira: bool) -> str:
    ambiente = "HOMOLOGAÇÃO" if "hmg-" in base_url else "PRODUÇÃO"
    linhas = [
        "",
        f"  MCP Arrendamento ligado ({ambiente}).",
        "  Deixe esta janela aberta (pode minimizar). Para desligar, feche a janela.",
        "",
    ]
    if primeira:
        linhas += [
            "  PRIMEIRA VEZ: cadastre o conector no SEI Pro. No painel do Agente de IA, abra a",
            '  configuração > "O que o agente pode" > "Conectores (MCP)" > "Novo conector":',
            "    Nome:                  Arrendamento",
            f"    Endereço do servidor:  http://127.0.0.1:{porta}/mcp",
            "    Cabeçalho:             Authorization",
            '    Valor:                 clique duas vezes em "Copiar token do conector" e cole aqui',
            '  Clique em "Adicionar" e aceite o pedido do Chrome para acessar 127.0.0.1.',
            "  O passo a passo completo está no arquivo LEIA-ME.txt.",
            "",
        ]
    linhas.append("  Na primeira chamada o Chrome abre para o login da Microsoft; depois ele fica minimizado.")
    return "\n".join(linhas)


def executar(mcp, argumentos: list[str]) -> int:
    from mcp_arrendamento.config import carregar_config
    from mcp_arrendamento.http import servir

    porta = int(os.environ.get("ARRENDAMENTO_PORTA", PORTA_PADRAO))
    token = carregar_token(RAIZ / "token-http")
    if argumentos[:1] == ["token"]:
        return copiar_token_por_um_tempo(token)
    if porta_ocupada(porta):
        if e_o_nosso_servidor(porta, token):
            print(f"\n  O MCP Arrendamento já está ligado neste computador (porta {porta}).")
            print("  Para trocar de ambiente, feche a outra janela dele e abra este atalho de novo.")
            return 0
        print(f"\n  ATENÇÃO: outro programa está usando a porta {porta} e NÃO é o MCP Arrendamento.")
        print("  Não use o conector Arrendamento no SEI Pro agora: o token seria enviado a esse programa.")
        print("  Feche o programa que usa a porta (ou reinicie o computador) e tente de novo.")
        return 1
    # Variável já definida (uso técnico) dispensa a pergunta.
    if "ARRENDAMENTO_URL" not in os.environ:
        ambiente = perguntar_ambiente()
        os.environ["ARRENDAMENTO_URL"] = ambiente.url
        os.environ.setdefault("ARRENDAMENTO_PERFIL", str(ambiente.perfil))
    print(instrucoes(porta, carregar_config().base_url, primeira_vez(RAIZ)), flush=True)
    servir(mcp, anunciar=False)
    print("\n  MCP Arrendamento desligado. Pode fechar esta janela.")
    return 0
