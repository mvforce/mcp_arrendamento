# mcp-arrendamento

Servidor MCP (Python, FastMCP, stdio) para `arrendamento.antaq.gov.br`. Mapa da API em
`docs/mapa-api.md`. Rodar testes: `.venv/bin/pytest -q` (sem rede).

## Fatos que não estão no código à primeira vista

- **Cloudflare:** curl/httpx/Node levam 403 `cf-mitigated: challenge` em `/api/*` e no HTML
  (`/assets/*` passa). Chrome **headless** é identificado (`HeadlessChrome` no UA) e recebe a
  caixa "Confirme que é humano". Chrome com **janela real minimizada** (CDP
  `Browser.setWindowBounds`) passa sem desafio. Por isso o padrão é `ARRENDAMENTO_JANELA=minimizada`.
  Não disfarçar headless nem clicar no Turnstile: a alternativa legítima é exceção no WAF (STI).
- **Login:** só SSO Entra (não há login local). O backend troca o code e devolve
  `/auth/microsoft/callback#access_token=...`. Token próprio (`base64url(payload).assinatura`),
  8 h, sem refresh. `GET /api/v1/auth/microsoft/authorize` com cookie `ESTSAUTHPERSISTENT`
  no perfil devolve token novo em ~2 s sem interação ("Continuar conectado?" = Sim no 1º login).
- **PUT substitui o registro inteiro** (contrato e abas): sempre GET → mesclar → PUT
  (`contratos.mesclar_contrato`, `subentidades.mesclar_payload`).
- **Regras copiadas do front** (bundle `assets/index-*.js`): datas vão como
  `AAAA-MM-DDT03:00:00.000Z`; o id de contrato novo é gerado no cliente (`Date.now() % 1e9`);
  aditivo copia campos específicos do pai e usa `nrVersao = máx + 1`; ostensividade A/B/C = 1/2/3;
  filtro `possuiDecisaoJudicial` usa `Sim`/`Nao`. Se o front mudar, rever `contratos.py` e
  `subentidades.py` contra o bundle novo.
- **Escritas:** `confirmar=false` por padrão em todas; sem confirmação devolvem só a prévia.
- **Homologação:** `https://hmg-arrendamento.antaq.gov.br`, só pela VPN da ANTAQ, sem Cloudflare,
  mesmo bundle de produção, base própria. Perfil separado: `ARRENDAMENTO_PERFIL=~/.mcp-arrendamento/perfil-hmg`.
  `scripts/bateria_hmg.py` exercita todas as escritas pelo protocolo MCP e limpa no fim
  (141 verificações em 07/10/2026). Rodar de novo quando o front mudar.
- **Respostas em PascalCase:** `/contratos-arrendamento-aditivos/por-contrato-pai/{id}` devolve
  `NRVersao`, `IDContratoArrendamento`, `DTcriacao`. `cliente._normalizar` converte toda resposta
  para o camelCase do front (`camel_como_front`); sem isso o 2º aditivo repetiria a versão.
- **Aditivos bloqueiam a exclusão do pai:** o sistema responde 409 mesmo com
  `removerDependencias=true` (que só cobre abas e arquivos). O cliente recusa antes, com os ids.
- **Login recusado** (ex.: usuário inativo): o callback devolve `#error=<mensagem>` no lugar do
  token; vira `ErroArrendamento` de origem `acesso` na hora.
- O backend ignora o id gerado no cliente ao criar contrato e **reaproveita ids** (maior + 1):
  excluir o contrato de maior id faz o próximo nascer com o mesmo id. Idem para anexos.
- **Encerramento vai na versão mais recente** (último aditivo; funções `go`/`So` do front). A
  situação de lista, filtros, relatório e painel é calculada pela versão mais recente; encerramento
  gravado em versão anterior é ignorado ali. Um por contrato, olhando todas as versões
  (`cliente._destino_do_encerramento`). Contrato encerrado que recebe aditivo volta a "Vigente":
  levado à SOG (doc "Arrendamento: contrato encerrado volta a constar como Vigente ao receber aditivo").
- **Anexos:** guardados no Object Storage como `<idContrato>/<nome>` (`nrLink`). `DELETE /arquivos/{id}`
  apaga registro e objeto; `removerDependencias` apaga só o registro e deixa o objeto órfão, que com
  id reaproveitado dá 412 `IfNoneMatchFailed` ao anexar o mesmo nome. Por isso `excluir_contrato`
  apaga cada anexo pelo endpoint próprio antes. Homologação já tem órfãos de teste em `4406/`.
- **`.pth` oculto:** em `~/Documents` (iCloud) o `.pth` da instalação editável ganha a flag
  `hidden` e o Python 3.12+ o ignora. Testes usam `pythonpath = ["src"]`; o servidor roda com
  `PYTHONPATH=src`.

- **Leitura de arquivo local:** `enviar_arquivo` passa por `seguranca.arquivo_para_envio` (pastas
  permitidas, sem ocultos, links resolvidos, só extensões de documento). Não relaxar: o modelo pode
  ser induzido por texto lido do sistema a pedir o envio de `~/.ssh/...`.

- **Modo HTTP local** (`python -m mcp_arrendamento http`, `http.py`): para o Agente de IA do SEI Pro
  (extensão; cliente Streamable HTTP, token fixo em cabeçalho, desiste em 60 s). Só 127.0.0.1, token
  em `~/.mcp-arrendamento/token-http`, checagem de Origin do SDK desligada (a origem é
  `chrome-extension://`) e substituída por Host local + token. Login vai para segundo plano.
  Hospedagem remota (Railway) foi descartada: VPN, Cloudflare e MFA por usuário.
- **Pacote de um clique** (`scripts/empacotar.py`, `lancadores/`, `iniciar.py`): uv embutido conferido por
  SHA-256, dependências com hash, pergunta de ambiente, prova de identidade em `/identidade` (HMAC do
  desafio com o token) contra programa que ocupe a porta, token só copiado a pedido e apagado em 60 s.
  Windows nunca foi executado.
- **Convenções da GPO** para cessão de uso estão em `skills/cadastrar-contrato-arrendamento.md`.

## Arquitetura

`transporte.Sessao` (token, renovação, nova tentativa em 401 e desafio) → `navegador.PaginaChrome`
(Playwright, `fetch` dentro da página estacionada em `/api/health`) · `cliente.ClienteArrendamento`
(endpoints, prévias, classificação de erros) · `server.py` (ferramentas e anotações).
