# Implantação na casa7 (Ubuntu)

Configuração usada: Ubuntu 26.04.1 LTS, Python 3.14, usuário marcus, diretório /home/marcus/apps/mcp-arrendamento.
Os serviços systemd desta pasta contêm esses caminhos. Ajuste User, Group, HOME, WorkingDirectory, PYTHONPATH e ExecStart antes de instalar em outra máquina.

## Dependências

```sh
sudo apt-get update
sudo apt-get install -y python3-venv xvfb x11vnc novnc websockify openbox curl fonts-liberation
```

Instale o Google Chrome pelo pacote oficial de https://www.google.com/chrome/ e o Tailscale pelo instalador oficial de https://tailscale.com/download. Entre na conta Tailscale na máquina.

```sh
cd /home/marcus/apps/mcp-arrendamento
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
mkdir -p ~/.mcp-arrendamento
chmod 700 ~/.mcp-arrendamento
sudo install -m 644 deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-arrendamento-display mcp-arrendamento-window mcp-arrendamento-vnc mcp-arrendamento-web mcp-arrendamento
```

## HTTPS público autenticado

```sh
sudo mkdir -p /etc/systemd/system/mcp-arrendamento.service.d
sudo install -m 644 deploy/public-host.conf.example /etc/systemd/system/mcp-arrendamento.service.d/public-host.conf
sudo systemctl daemon-reload
sudo systemctl restart mcp-arrendamento
sudo tailscale funnel --bg --yes http://127.0.0.1:8765
```

Habilite Funnel na conta quando solicitado. Se o hostname for outro, ajuste public-host.conf.example. Nunca use wildcard nem desabilite a checagem de Host.
Conector configurado na casa7: https://casa7.tail3c84be.ts.net/mcp.
Cabeçalho Authorization: Bearer seguido do conteúdo de ~/.mcp-arrendamento/token-http. Esse arquivo deve permanecer privado. O cliente público não precisa de Tailscale nem túnel SSH.
O DNS público pode levar até 10 minutos para propagar. Documentação oficial: https://tailscale.com/docs/features/tailscale-funnel.
Não houve abertura de portas no roteador nem alteração de firewall.

## Tela de login privada

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:6080:127.0.0.1:6080 marcus@casa7.tail3c84be.ts.net
```

Para administrar a tela, o dispositivo cliente precisa do Tailscale e de acesso SSH autorizado. Abra http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale. A chamada arrendamento_sessao abre o Chrome para login Microsoft/MFA. Digite credenciais somente nessa tela.
A tela web e VNC escutam apenas em loopback; não publique 6080/5901 no Funnel. VNC não usa senha adicional: o túnel SSH protege o acesso, mas usuários locais da casa7 também alcançam loopback.

## Disponibilidade e diagnóstico

Serviços com Restart=on-failure e habilitados na inicialização. Na casa7 também foram mascarados sleep.target, suspend.target, hibernate.target, hybrid-sleep.target e suspend-then-hibernate.target para evitar suspensão. Essa escolha é da implantação específica, não é feita automaticamente pelos arquivos.

```sh
systemctl status mcp-arrendamento
tailscale funnel status
journalctl -u mcp-arrendamento -n 50 --no-pager
sudo tailscale funnel --https=443 off # retira o endpoint público
```

174 testes Python passaram na casa7. Sessão institucional persistiu após reinício, consulta de portos funcionou e negociação HTTPS initialize/list_tools retornou 27 ferramentas. Sem token: HTTP 401. Teste independente por relay público estava pendente de DNS na verificação automatizada; o usuário informou sucesso do conector.
Não houve teste por reboot nem gravação de contratos/anexos na implantação. Confira um envio real autorizado para validar o ciclo completo com a extensão atualizada.
