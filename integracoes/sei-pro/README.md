# Integração SEI Pro

Patch para o commit 6b339453eed642c57e2bdeb46f83c5b24adfbb08 de https://github.com/SEI-Pro/sei-pro.

```sh
git apply /caminho/nomes-e-transferencia.patch
cd agente-ia
npm install
npm run tipos
node --no-experimental-global-navigator --import tsx tests/verificar.ts
node build.mjs
```

O agente fornece nome_arquivo a documento_baixar. A ferramenta preserva extensão e número SEI e grava o hash do download aprovado. A ponte de mcp_chamar transfere os bytes diretamente do SEI ao MCP após aprovação, confere o hash, omite o caminho Windows e não entrega base64 ao provedor de IA. Funciona com HTTPS autenticado ou localhost por túnel.
Após atualizar a extensão, execute Testar conexão no conector para atualizar o schema. Refaça downloads antigos, sem hash. Skill atualizada em skills/cadastrar-contrato-arrendamento.md na raiz deste repositório.
A suite teve 1292 verificações sem falhas, além dos testes específicos do patch; tipos e compilação passaram. Upload real exige documento, contrato de destino e aprovação do usuário e ainda não foi validado neste trabalho.
