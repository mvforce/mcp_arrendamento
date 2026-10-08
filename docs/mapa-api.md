# Mapa da API — Sistema de Arrendamento ANTAQ

Levantado em 06/10/2026 a partir do tráfego de rede e do bundle do front (`assets/index-CiqfETMS.js`, versão 1.0.0).
Base: `https://arrendamento.antaq.gov.br/api`. Backend ASP.NET Core (erros em ProblemDetails: campo `detail`).
Não há Swagger/OpenAPI exposto em produção.

## Autenticação

1. `GET /api/v1/auth/microsoft/authorize` → redireciona para o Entra ID (tenant `8e57f727-0e5e-4130-8e24-2d5f7c8c38f6`,
   client `29e9ac5b-de4e-4544-b2b3-5e289a4828d8`, scope `openid profile email`, PKCE feito pelo backend).
2. Entra devolve o `code` para `GET /api/v1/auth/microsoft/callback`, que troca o código e responde `302` para
   `/auth/microsoft/callback#access_token=<token>`.
3. O front guarda o token em `sessionStorage['antaq.accessToken']` e envia `Authorization: Bearer <token>`.

Token próprio do sistema, formato `base64url(payload).assinatura` (não é JWT padrão, nem token do Entra):

```json
{ "sub": 21, "email": "...", "login": "...", "perfil": "Administrador", "perfilCodigo": "ADMIN_ANTAQ",
  "permissoes": ["ADMIN_TOTAL", "TABELA_PRECO_CONSULTAR", "TABELA_PRECO_CRIAR", "USUARIOS_ADMINISTRAR"],
  "deveTrocarSenha": false, "exp": 1791353494, "nome": "..." }
```

- Validade de 8h e não há refresh token.
- **Renovação silenciosa funciona:** com a sessão do Entra ativa no navegador, abrir `/api/v1/auth/microsoft/authorize`
  devolve um token novo sem interação.
- Não existe endpoint de login local (usuário e senha), só o `trocar-senha`.
- Se o sistema recusar o usuário (ex.: "Usuario cadastrado, mas inativo no sistema."), o callback
  devolve `#error=<mensagem>` no lugar do `#access_token`.

Homologação: `https://hmg-arrendamento.antaq.gov.br` (só pela VPN, sem Cloudflare, mesmo bundle, base própria).

## Cloudflare (restrição principal)

`/api/*` e o HTML são protegidos por *managed challenge* (`cf-mitigated: challenge`, HTTP 403 "Just a moment...").
`curl` e `fetch` do Node são bloqueados mesmo com cabeçalhos de Chrome e token válido. Só `/assets/*` passa.
Chrome **headless** também é barrado: o Cloudflare o identifica (`HeadlessChrome` no User-Agent) e mostra a
caixa "Confirme que é humano". Chrome com janela real, mesmo minimizada, passa sem desafio.
Consequência: as chamadas precisam sair de um navegador real com janela (ou de uma regra de exceção no WAF,
a pedir à STI).

## Convenções

- Sub-entidades de contrato seguem o padrão `GET /{recurso}/por-contrato/{idContrato}`, `POST /{recurso}`,
  `PUT /{recurso}/{id}`, `DELETE /{recurso}/{id}`.
- `POST` devolve o registro criado; `PUT` e `DELETE` costumam devolver 204.
- Datas em ISO (`2026-06-25T03:00:00`). Respostas às vezes vêm em PascalCase; o front aceita os dois formatos.
- `401` = sessão expirada; `403` = sem permissão.

## Sessão e acessos

| Método | Rota | Corpo / observação |
|---|---|---|
| GET | `/v1/auth/microsoft/status` | sem auth → `{enabled}` |
| GET | `/auth/me` | `{usuario:{id,nome,email,login,perfil,perfilCodigo,deveTrocarSenha,permissoes[]}}` |
| POST | `/auth/trocar-senha` | `{senhaAtual, novaSenha}` |
| GET / POST | `/auth/usuarios` | lista / cria |
| PATCH | `/auth/usuarios/{id}` | altera |
| PATCH | `/auth/usuarios/{id}/ativar` · `/inativar` | |
| DELETE | `/auth/usuarios/{id}/definitivo` | exclusão definitiva |
| GET | `/auth/solicitacoes-acesso` | |
| PATCH | `/auth/solicitacoes-acesso/{id}/autorizar` | `{perfilCodigo}` |
| PATCH | `/auth/solicitacoes-acesso/{id}/negar` | |
| GET / POST | `/auth/perfis` | |
| PATCH | `/auth/perfis/{codigo}` · `/ativar` · `/inativar` | |
| DELETE | `/auth/perfis/{codigo}/definitivo` | |
| GET | `/auth/auditoria-login` | |

Perfis vistos no front: `ADMIN_ANTAQ`, `ANTAQ_ANALISTA`.

## Contratos de arrendamento

| Método | Rota | Observação |
|---|---|---|
| GET | `/contratos-arrendamento/resumo` | paginado; ver filtros abaixo |
| GET | `/contratos-arrendamento/{id}` | 46 campos |
| POST | `/contratos-arrendamento` | payload completo |
| PUT | `/contratos-arrendamento/{id}` | **substitui o registro inteiro**: fazer GET → mesclar → PUT |
| GET | `/contratos-arrendamento/{id}/analise-exclusao` | `{possuiAditivos, dependencias:[{codigo,descricao,quantidade}]}` |
| DELETE | `/contratos-arrendamento/{id}[?removerDependencias=true]` | `removerDependencias` cobre abas e arquivos; com aditivo vinculado responde **409** |
| GET | `/contratos-arrendamento-aditivos/por-contrato-pai/{id}` | aditivos do contrato; **responde em PascalCase** (`NRVersao`, `IDContratoArrendamento`) |

Filtros do `resumo`: `pagina`, `tamanhoPagina`, `cdContrato`, `noTipoOutorga`, `cdTrigrama`, `noFantasiaEmpresa`,
`possuiDecisaoJudicial`, `situacaoContrato` (`Vigente` · `Vigente Decisão Judicial` · `Encerrado`), `dsAtoAntaq`, `nrAto`.
Resposta: `{itens[], pagina, tamanhoPagina, totalRegistros, totalPaginas, temPaginaAnterior, temProximaPagina}`.

Campos do contrato (POST/PUT): `idContratoArrendamento`, `idContratoArrendamentoPai`, `cdContrato`, `dtInicialContrato`,
`dtFimContrato`, `mmObjeto`, `noRenovacao`, `dsExercida`, `nrVersao`, `nrCnpj` (só dígitos), `cdHash`, `dTcriacao`,
`dtOperacao`, `nrPrazoContrato`, `noTipoOutorga`, `dtAssinatura`, `dtPublicacao`, `stInicioContrato`, `stHomogacao`,
`noJustificativaHomologacao`, `stExpiracao`, `noFantasiaEmpresa`, `noContrato`, `dtAssinaturaAditivo`, `dtDesocupacao`,
`vlwacc`, `noNomeInstrumento`, `stContrato`, `idTerminal`, `cdTrigrama`, `cdArea`, `stMostrarAteLei12815`, `tpContrato`,
`stLicitacaoPrevia`, `dtVigenciaContrato`, `nrEditalLicitacao`, `dtEditalLicitacao`, `idTipoLicitacao`,
`nrPrazoContratoMeses`, `nrPrazoContratoDias`, `noUsuarioCadastro`, `dsPassivelLicitacao`, `dsIdentificacao`,
`dsDestinacao`, `nrcnpjInstalacao` (só dígitos), `noInstalacao`.

Obrigatórios no front: versão, número, nome do instrumento, tipo de contrato, licitação prévia, tipo de outorga, porto,
CNPJ, razão social, CNPJ e razão social da instalação, prazo (anos/meses/dias), assinatura, início e término da
vigência, ostensividade (`stContrato`), cláusula de prorrogação, exercida, objeto. Aditivo = contrato com
`idContratoArrendamentoPai` e `dtAssinaturaAditivo` obrigatória.

## Sub-entidades do contrato

| Recurso | Chave | Corpo POST/PUT (além de `idContratoArrendamento`) |
|---|---|---|
| `aspectos-fisicos` | `idAspectoFisico` | `nrBerco` (""), `vlExtencaoLinhaCais`, `vlAreaTotal`*, `vlAreaAmpliacao` |
| `bens` | `idBem` | `dsBem`*, `noClassificacao`* (`Equipamento`·`Imovel`·`Utilidade`), `stReversivel`* (`Sim`·`Nao`), `noOrigem`* (`Nao Informado`·`Arrendatario`·`Autoridade Portuaria`), `nrVidaUtil` (int/null), `vlBem` |
| `partes-significativas` | `idParteSignificativa` | `noClausula`, `noParagrafo`, `dsParagrafo` |
| `coordenadas` | `idCoordenada` | `idAspectoFisico`, `dsPonto`, `vlLatitude`, `vlMinLatitude`, `vlSecLatitude`, `vlLatitudeCardial`, `vlLongitude`, `vlMinLongitude`, `vlSecLongitude`, `vlLongitudeCardial` (`L`·`O`) |
| `contratos-processos` | `idContratoProcesso` | `nrProcesso`, `dsAtoAntaq` (`Acórdão`·`Resolução`), `nrAto`, `dtAto` |
| `decisoes-judiciais` | `idDecisaoJudicial` | `dsOrigemDecisao`, `nrProcessoJudicial`, `dsTeorDecisao`, `dsCondicaoEfeito`, `dtDecisaoJudicial`, `dtInicioEfeito`, `dtFimEfeito`, `idSituacaoDecisaoJudicial` (0 pendente de verificação · 1 liminar produzindo efeitos · 2 condição materializada · 3 decisão reformada) |
| `contratos-encerrados` | `idContratoEncerrado` | `dtFinalizacaoContrato`, `dsMotivo` (um por contrato, olhando todas as versões; a tela grava na versão mais recente) |
| `investimentos-previstos` | `idInvestimentoPrevisto` | `dsInvestimentoPrevisto`, `vlInvestimentoPrevisto`, `dtInvestimentoPrevisto` |
| `investimentos-realizados` | `idInvestimentoRealizado` | `dsInvestimentoRealizado`, `vlInvestimentoRealizado`, `dtInvestimentoRealizado` |
| `observacoes` | `idObservacao` | `noResponsavel`, `dsObservacao`, `dtObservacao` |
| `perfis-carga-passageiros` | `idClassificaoSubclassificaoCarga` | `idNaturezaCarga` |
| `tipos-servicos-contrato` | **composta**: `PUT`/`DELETE /tipos-servicos-contrato/{idContrato}/{idTipoServico}` | `idTipoServico` |
| `situacoes-adimplemento` | `idSituacaoAdimplemento` | `stAdimplemento` (1 sim · 2 não), `dtAdimplemento` (ISO), `dsObservacao` |
| `arquivos` | `idArquivo` | `POST` multipart: `idContratoArrendamento` + `arquivo`; `GET /arquivos/{id}/conteudo` devolve o binário. Objeto guardado como `<idContrato>/<nome>` (`nrLink`); o mesmo nome no mesmo contrato dá 412 |

## Opções (tabelas de domínio)

`GET /contratos-arrendamento-opcoes/…`: `tipos-contrato`, `licitacoes-previas`, `tipos-outorga` (`{valor,descricao}`),
`portos` (`{noPorto,cdTrigrama}`), `natureza-carga`, `tipo-servico`, `tipos-licitacao` (`{idTipoLicitacao,noTipoLicitacao}`),
`instalacoes-portuarias/razao-social?cnpj=`.

## Relatórios

| Rota | Parâmetros |
|---|---|
| `GET /relatorios/contratos-arrendamento/dashboard` | totais vigentes por tipo de outorga e por porto |
| `GET /relatorios/contratos-arrendamento/vencimentos` | contratos que vencem em 1 a 90 dias, com `nivelAlerta` |
| `GET /relatorios/contratos-arrendamento/lei-12815` | `ano`, `tiposOutorga` (repetível) |
| `GET /relatorios/contratos-arrendamento` | `noTipoOutorga`, `cdTrigrama`, `situacaoContrato`, `possuiDecisaoJudicial` |
| `GET /relatorios/contratos-arrendamento/{id}/aditivos` | |

## Comportamentos observados em homologação (07/10/2026)

- **Situação do contrato** (lista, filtros, relatório, painel): calculada pela versão mais recente.
  Encerrado se houver encerramento com data até hoje; senão "Vigente Decisão Judicial" se houver
  decisão em efeito; senão pela data de término. Encerramento gravado em versão anterior é ignorado:
  contrato encerrado que recebe aditivo volta a "Vigente".
- **Ids reaproveitados:** contrato e anexo novos recebem o maior id + 1, inclusive o de um registro excluído.
- **Anexo órfão:** `removerDependencias` apaga o registro do anexo mas não o objeto; `DELETE /arquivos/{id}` apaga os dois.

## Outros

`GET /api/health` → `{status:"ok"}`. Telemetria do front: Grafana Faro (`faro.antaq.gov.br`) e Cloudflare RUM.
