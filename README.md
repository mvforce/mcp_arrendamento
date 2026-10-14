# mcp-arrendamento

Servidor MCP para o Sistema de Gestão de Arrendamento Portuário da ANTAQ
(`arrendamento.antaq.gov.br`): consultas, relatórios e edição de contratos, aditivos e abas.

## Como funciona

O domínio está atrás de um *Managed Challenge* do Cloudflare. Clientes HTTP (curl, httpx,
fetch do Node) e Chrome headless são barrados, então o servidor faz as chamadas com `fetch` de
dentro de um **Google Chrome real, com a janela minimizada** e perfil próprio
(`~/.mcp-arrendamento/perfil-chrome`).

O login é o SSO da Microsoft (Entra ID). Você entra uma vez com MFA; depois disso o servidor
renova o token de 8 horas sozinho, pelo SSO silencioso, enquanto a sessão da Microsoft durar.

## Instalação

Requer Python 3.11+, [uv](https://docs.astral.sh/uv/) e Google Chrome.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

## Primeiro login

```bash
PYTHONPATH=src .venv/bin/python -m mcp_arrendamento login
```

Abre o Chrome. Entre com a conta institucional e, quando a Microsoft perguntar
**"Continuar conectado?"**, responda **Sim**. É isso que permite a renovação silenciosa.

Para conferir sem interação (faz só leituras):

```bash
PYTHONPATH=src .venv/bin/python -m mcp_arrendamento teste
```

## Registrar no Claude Code

```bash
claude mcp add arrendamento --scope user \
  --env PYTHONPATH="$PWD/src" \
  -- "$PWD/.venv/bin/python" -m mcp_arrendamento
```

O `PYTHONPATH` é proposital: com o projeto em `~/Documents`, o macOS (iCloud) pode marcar o
`.pth` da instalação editável como oculto, e o Python 3.12+ passa a ignorá-lo.

## Usar com o Agente de IA do SEI Pro (HTTP local)

O Agente do SEI Pro fala MCP por HTTP. Suba o servidor na própria máquina:

```bash
PYTHONPATH=src .venv/bin/python -m mcp_arrendamento http
```

No SEI Pro, cadastre um conector com o endereço `http://127.0.0.1:8765/mcp` e o cabeçalho
`Authorization: Bearer <conteúdo de ~/.mcp-arrendamento/token-http>`. O servidor escuta só em
127.0.0.1 e recusa pedidos sem esse token. `ARRENDAMENTO_PORTA` troca a porta.

Se a sessão da Microsoft cair, a chamada responde na hora com `[sessao] A janela de login...`,
a janela do Chrome abre e, concluído o login, basta repetir o pedido.

A skill [skills/cadastrar-contrato-arrendamento.md](skills/cadastrar-contrato-arrendamento.md)
ensina o agente a ler um processo do SEI e cadastrar o contrato.

## Pacote de um clique (Windows e Mac)

Para quem não é técnico. Gere os pacotes com:

```bash
.venv/bin/python scripts/empacotar.py
```

Saem em `dist/` os arquivos `MCP-Arrendamento-mac.zip` e `MCP-Arrendamento-windows.zip`. O usuário
descompacta e clica duas vezes em **Iniciar MCP Arrendamento**. Requer Google Chrome e internet na
primeira execução; nada é instalado no sistema.

| No pacote | Para quê |
|---|---|
| Iniciar MCP Arrendamento | liga o servidor; pergunta o ambiente (1 produção, 2 homologação) |
| Copiar token do conector | copia o valor do cabeçalho `Authorization` e o apaga da área de transferência em 60 s |
| LEIA-ME.txt | passo a passo do conector e da skill no SEI Pro, com os nomes da tela |
| skill-cadastrar-contrato-arrendamento.md | a skill, para colar em Configuração → Skills |
| app/ | o código, `requisitos.txt` e o `uv` |

Como funciona por dentro:

- O lançador chama `python -m mcp_arrendamento iniciar` (`iniciar.py`) pelo `uv` embutido, que baixa
  o Python 3.12 e as bibliotecas na primeira vez.
- O `uv` vem do release oficial e é conferido pelo SHA-256 publicado. As bibliotecas estão fixadas
  com hash em `lancadores/requisitos.txt`; para atualizar, edite `requisitos.in` e rode
  `uv pip compile lancadores/requisitos.in --universal --python-version 3.12 --generate-hashes -o lancadores/requisitos.txt`.
- Cada ambiente usa um perfil de Chrome próprio (`perfil-chrome` e `perfil-hmg`). Só um fica ligado
  por vez, na mesma porta; o conector no SEI Pro é o mesmo para os dois.
- Se a porta já estiver ocupada, o lançador confere se é mesmo o MCP: o servidor responde em
  `/identidade?desafio=...` com um HMAC do desafio feito com o token, sem revelar o token. Se for
  outro programa, o lançador avisa para não usar o conector, porque o token iria para ele.
- O token nunca é copiado sozinho: só quando o usuário clica em "Copiar token do conector".

Limites conhecidos: o pacote do Windows ainda não foi executado numa máquina real; os arquivos não
são assinados (Gatekeeper no Mac e SmartScreen no Windows pedem confirmação no primeiro uso); a
primeira execução precisa alcançar `github.com` e `pypi.org`.

## Ferramentas

| Grupo | Ferramentas |
|---|---|
| Sessão | `arrendamento_sessao` |
| Consultas | `buscar_contratos`, `consultar_contrato`, `listar_aditivos`, `listar_registros`, `listar_opcoes`, `consultar_cnpj`, `consultar_campos` |
| Relatórios | `relatorio_painel`, `relatorio_vencimentos`, `relatorio_lei_12815`, `relatorio_contratos` |
| Arquivos | `listar_arquivos`, `baixar_arquivo`, `enviar_arquivo`, `excluir_arquivo` |
| Contrato | `criar_contrato`, `criar_aditivo`, `alterar_contrato`, `excluir_contrato` |
| Abas | `incluir_registro`, `alterar_registro`, `excluir_registro` |
| Acessos (só leitura) | `listar_usuarios`, `listar_perfis`, `listar_solicitacoes_acesso`, `consultar_auditoria_login` |

Todas com o prefixo `arrendamento_`.

**Nenhuma escrita grava sem `confirmar=true`.** Com o padrão `confirmar=false`, a ferramenta
devolve só a prévia: o payload exato ou o diff campo a campo. Alterações leem o registro atual,
aplicam só o que mudou e reenviam o registro inteiro, porque o `PUT` da API substitui tudo.

## Configuração (opcional)

| Variável | Padrão | Uso |
|---|---|---|
| `ARRENDAMENTO_URL` | `https://arrendamento.antaq.gov.br` | outro ambiente (homologação) |
| `ARRENDAMENTO_JANELA` | `minimizada` | `visivel` para acompanhar; `headless` só funciona com exceção no WAF |
| `ARRENDAMENTO_LOGIN_INTERATIVO` | `true` | se o SSO silencioso falhar, mostra a janela para logar |
| `ARRENDAMENTO_PERFIL` | `~/.mcp-arrendamento/perfil-chrome` | perfil do Chrome |
| `ARRENDAMENTO_CANAL` | `chrome` | `chromium` usa o Chromium do Playwright |
| `ARRENDAMENTO_PASTA_DOWNLOADS` | `~/Downloads/Arrendamento` | destino de `baixar_arquivo` |
| `ARRENDAMENTO_PASTAS_ENVIO` | `~/Downloads:~/Documents:~/Desktop` | de onde `enviar_arquivo` pode ler (separadas por `:`) |

`enviar_arquivo` só lê documentos (PDF, Office, imagens, texto) dentro dessas pastas, nunca de
pastas ou arquivos ocultos (`.ssh`, `.env`...) e resolvendo links simbólicos antes de checar.
Assim, um texto malicioso lido do sistema não consegue induzir o envio de credenciais da máquina.

## Testes

```bash
.venv/bin/pytest -q
```

Os testes não acessam a rede.

### Bateria em homologação (com escritas)

Homologação (`https://hmg-arrendamento.antaq.gov.br`) só responde pela VPN da ANTAQ. Com a VPN
ligada, faça o login uma vez no perfil de homologação e rode a bateria:

```bash
ARRENDAMENTO_URL=https://hmg-arrendamento.antaq.gov.br \
ARRENDAMENTO_PERFIL=~/.mcp-arrendamento/perfil-hmg \
PYTHONPATH=src .venv/bin/python -m mcp_arrendamento login

.venv/bin/python scripts/bateria_hmg.py
```

Ela cria um contrato `MCP-TESTE/<data-hora>`, passa por todas as ferramentas (prévia, conferência
de que nada foi gravado, confirmação, releitura) e apaga tudo no fim. Recusa rodar se o servidor
não estiver em homologação. O mapa da API está em [docs/mapa-api.md](docs/mapa-api.md).


## Implantação persistente e arquivos com nome legível

A versão atual inclui HTTP com token, configuração de hostname HTTPS explícito e envio remoto por conteúdo (limite de 25 MB), além do envio por caminho local. nome_arquivo permite o nome legível; confirmar=false permanece como prévia e confirmar=true efetua o envio.

- [Implantação Ubuntu/systemd e Tailscale Funnel](deploy/README.md)
- [Integração e patch SEI Pro](integracoes/sei-pro/README.md)
- [Skill atualizada](skills/cadastrar-contrato-arrendamento.md)

ARRENDAMENTO_HOSTS_HTTP aceita hostnames adicionais separados por vírgulas, sem protocolo ou caminho. O padrão continua restrito a localhost. A publicação pública exige token; não exponha o perfil Chrome ou a tela de login.
Credenciais, tokens, chaves SSH e cookies não integram este repositório.
