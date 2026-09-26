# COC Control

Sistema local de controle e gerenciamento de contas do **Clash of Clans**, baseado
no recurso oficial de **Exportação de dados** da Supercell (⚙️ Configurações →
Mais configurações → Exportação de dados → Copiar).

Todas as informações vêm do export oficial em JSON — o sistema não acessa sua
conta nem interfere no jogo.

## O que ele faz

- **Multi-contas**: cadastre quantas vilas quiser; o import identifica a conta
  automaticamente pela **tag** do jogador (cria a conta no 1º import).
- **Dashboard por vila**: progresso total e por categoria (defesas, armadilhas,
  muros, heróis, tropas/lab, feitiços, cerco, pets, equipamentos…), upgrades
  pendentes com **custo restante** (Ouro/Elixir/Elixir Negro/minérios) e
  **tempo total**, ETA de construtores / laboratório / pets e caminho crítico.
- **Upgrades em andamento** com data/hora de término (lidos dos timers do export).
- **Histórico**: cada import vira um snapshot → gráfico de evolução do progresso.
- **Planner de upgrades**: sugere o próximo upgrade de cada construtor por
  estratégia (defesa, farm, mais rápido, mais barato, balanceado) e desenha o
  cronograma (Gantt) das filas até o máximo do TH, com datas projetadas.
- **O que mudou**: changelog automático entre os dois últimos imports (níveis
  concluídos, construções novas, upgrades iniciados, gasto estimado) e
  **velocidade real** (%/dia do seu histórico → ETA realista de vila maxada).
- **Alertas de término**: notificação do Windows (toast), **WhatsApp (Evolution
  API)**, Telegram e/ou Discord
  quando um upgrade termina / construtor libera, aviso X min antes e resumo
  diário no horário que você escolher — sem precisar abrir o jogo (os términos
  são calculados dos timers do último export).
- **API oficial da Supercell** (opcional): troféus, liga, estrelas de guerra,
  doações e clã por conta, sincronizados a cada import.
- **3 formas de importar**:
  1. **Watcher de clipboard** (recomendado): deixe o COC Control aberto, copie o
     export no jogo e pronto — importa sozinho na conta certa.
  2. **Importar do clipboard / Colar JSON** na interface.
  3. **Automação opcional** do Google Play Games Beta (ver abaixo).

## Instalação (Windows)

Requer Python 3.10+ ([python.org](https://python.org), marque "Add to PATH").

```bat
cd coc-control
pip install -r requirements.txt
python app.py
```

Ou dê dois cliques em **`Iniciar COC Control.bat`**.
A interface abre em <http://127.0.0.1:8420>.

## Fluxo recomendado

1. Abra o COC Control (watcher já inicia ligado).
2. No jogo (Google Play Games Beta ou celular*): ⚙️ → Mais configurações →
   Exportação de dados → **Copiar**.
3. O toast "vila importada" aparece no dashboard. Repita para cada conta
   (troque de conta no jogo e copie de novo).

\* No celular, use qualquer app de notas para mandar o JSON ao PC e cole na opção
**Colar JSON**.

## Automação do Google Play Games Beta (opcional)

Grava uma vez o caminho (posições **e imagens** dos botões) e depois reproduz
sozinho com **verificação visual**: engrenagem → Mais configurações → rola **até
localizar o botão Copiar na tela** (template matching multi-escala/OpenCV) →
clica → envia ao COC Control. Se o botão não for localizado, **aborta sem clicar
em nada** — nunca clica às cegas em posição gravada.

```bat
:: gravar o perfil (uma vez; regrave se veio da v1)
python automation\auto_capture.py --record

:: testar sem clicar em Copiar (recomendado após gravar)
python automation\auto_capture.py --run --dry-run

:: capturar agora
python automation\auto_capture.py --run

:: capturar a cada 6 horas (deixe o jogo aberto)
python automation\auto_capture.py --run --loop 360
```

Ajustes no `automation/profile.json`: `max_scroll_rounds` (qtd. de rolagens até
achar o botão), `scroll_step`, `confidence` (0.75–0.90) e `delay`.
Mouse no canto superior esquerdo da tela = aborta (failsafe).

> **Aviso**: automatizar cliques no cliente pode violar os Termos de Serviço da
> Supercell, mesmo usando só o recurso oficial de export. Use por sua conta e
> risco. O watcher de clipboard é a alternativa 100% segura (você clica em
> Copiar manualmente).

## Alertas (⚙️ Configurações na interface)

- **Windows**: ative "Notificação do Windows" — usa toast nativo, sem instalar nada.
- **Telegram**: crie um bot com o @BotFather (pegue o token), mande um /start
  para o bot e descubra seu chat_id com o @userinfobot. Preencha os dois campos.
- **Discord**: crie um webhook no canal (Configurações do canal → Integrações)
  e cole a URL.
- **WhatsApp (Evolution API)**: preencha URL do servidor (ex.:
  `https://evolution.seudominio.tech`), instância (ex.: `principal`), a `apikey`
  da instância e o destino — número (`5511999999999`) ou JID de grupo
  (`120363...@g.us`). São os mesmos valores dos seus fluxos do n8n
  (`POST /message/sendText/{instância}`).
- Use "🔔 Testar notificação" para validar os canais. O aviso "X min antes" e o
  resumo diário são configuráveis; o dedupe é persistido (reiniciar não repete).

## API oficial da Supercell (opcional)

1. Crie uma conta em <https://developer.clashofclans.com> e gere uma chave
   (key) informando o **IP público atual** da sua máquina.
2. Cole o token em ⚙️ Configurações → API Supercell.
3. Use "↻ Sincronizar" no detalhe da conta, ou deixe o auto-sync ligado (busca
   a cada import). Se o seu IP mudar, edite a chave no site da Supercell.
4. No sync, contas com nome automático ("Vila #TAG") recebem o **nome real do
   jogador**. O botão `{ }` no detalhe mostra a resposta bruta da API (útil se
   algum campo, como a liga, mudar de nome após updates do jogo).

### Verificação de posse (Token de API do jogo)

O jogo tem um "Token de API" próprio (⚙️ → Mais configurações → **Token de API**
→ Mostrar). Ele **não dá acesso a dados** — serve exclusivamente para provar que
a conta é sua, via endpoint oficial `verifytoken`. No COC Control: ✏️ Editar
conta → cole o token → **✅ Verificar**. A conta ganha o selo ✅ de verificada.
O token é de uso único (o jogo gera outro a cada consulta) e requer o token de
desenvolvedor configurado.

## Base de dados de custos/tempos

`data/game_data.json` (gerada do pacote npm [`clash-of-clans-data`](https://github.com/chiefpansancolt/clash-of-clans-data),
MIT, dados do Clash of Clans Wiki) traz custos, tempos e nível máximo por TH de
cada item — é o que permite calcular % de progresso, custo restante e ETAs.

**Quando o jogo receber update de balanceamento/novo TH**, atualize a base:

```bat
npm pack clash-of-clans-data@latest
tar -xzf clash-of-clans-data-*.tgz
python tools\build_game_data.py --src package\data --out data\game_data.json
```

O dashboard avisa quando detecta itens acima do máximo conhecido (base
desatualizada) — o aviso mostra a versão da base (ex.: v0.16.0), pode ser
dispensado no ✕ e volta apenas se a divergência mudar. Importante: se o pacote
npm ainda não cobre o último update do jogo, regenerar a base não limpa o aviso
— aguarde a comunidade publicar a versão nova e rode o comando acima. IDs novos que ainda não existem no pacote podem ser nomeados em
**`data/overrides.json`** (formato documentado no próprio arquivo).

## Estrutura

```
coc-control/
├── app.py                  # servidor Flask + API REST + watcher de clipboard
├── coc/
│   ├── labs.py             # assinantes: entrada pela Clash Labs, passe, avisos
│   ├── netguard.py         # alertas de assinantes só para endereços públicos
│   ├── parser.py           # parser defensivo do export (seções, cnt, timers, módulos aninhados)
│   ├── metrics.py          # progresso, pendências, custos, ETAs, mesclagens TH16+
│   ├── gamedata.py         # base estática + overrides
│   └── db.py               # SQLite (usuários, vilas por usuário, snapshots)
├── static/index.html       # dashboard (offline, sem CDN)
├── data/game_data.json     # base de custos/tempos (regenerável)
├── data/overrides.json     # entidades novas/custom
├── automation/auto_capture.py
├── tools/build_game_data.py
└── tests/                  # fixtures (export real TH18 anonimizável + sintético TH16)
```

API (sempre dentro das vilas de quem está logado): `GET/POST /api/accounts`, `PATCH/DELETE /api/accounts/<id>`,
`GET /api/accounts/<id>/detail` (inclui diff, velocidade, série e jogador),
`GET /api/accounts/<id>/plan?strategy=defense|farm|fast|cheap|balanced`,
`POST /api/accounts/<id>/sync-supercell`, `POST /api/import[?account_id=]`,
`DELETE /api/snapshots/<id>`, `GET/PUT /api/settings`, `POST /api/notify/test`,
`GET /api/status`, `POST /api/watcher` (só o dono), `GET /api/me`, `POST /api/apikey`,
`GET /api/admin/subscribers` (só o dono). Clash Labs: `GET /entrar/clash-labs`,
`GET /api/labs/callback`, `POST /api/labs/webhook`, `GET /api/labs/info`.

## Limitações conhecidas

- O export **não** traz: construtores no Forge, boosts/poções ativos, nível de
  ajudantes em cooldown detalhado, Gold Pass — os timers assumem velocidade normal.
- Custos de **supercharge** e dos **módulos da Estação de Criação** ainda não
  estão na base pública — itens aparecem marcados, sem custo.
- Base do Construtor é importada e reconhecida, mas fica fora dos % (v1).

## Assinantes (Clash Labs)

O COC Control também é vendido como passe na Clash Labs. Cada assinante tem a
própria conta aqui, com as próprias vilas, alertas e API key, e não vê nada de
ninguém. O login do `.env` (`ADMIN_USER`) é o **dono**: fica com as vilas que já
existiam, a chave da Supercell do servidor e a lista de assinantes (⚙️ Configurações).

Ligar:

1. No `.env` do COC Control: `LABS_URL` (endereço da vitrine) e
   `LABS_PRODUCT_SECRET` (48+ caracteres aleatórios). Se o servidor alcança a
   vitrine por outro endereço, `LABS_API_URL`.
2. No `.env` da vitrine: `PRODUCT_COC_CONTROL_URL` = endereço deste painel e
   `PRODUCT_COC_CONTROL_SECRET` = o mesmo segredo.
3. Atualize (Deploy VPS.bat). O instalador faz backup do banco antes e a
   primeira subida passa as vilas existentes para o dono, sem perder nada.

Como funciona:

- **Entrada**: "Entrar com a Clash Labs" na tela de login, ou "Abrir" na vitrine.
  Ninguém cria senha aqui. A troca do código é feita servidor a servidor, com o
  segredo, e amarrada ao navegador que pediu (quem chega da vitrine sem esse
  vínculo dá uma volta rápida para criá-lo).
- **Passe**: pagamento, renovação, cancelamento e reembolso chegam como aviso da
  vitrine (`POST /api/labs/webhook`). O aviso só diz quem mudou; o passe é relido
  aqui. Se um aviso se perder, o painel relê sozinho a cada 15 min
  (`LABS_SYNC_INTERVAL`) e quando o assinante abre a página.
- **Passe vencido**: vilas, histórico e alertas ficam guardados, os alertas param
  e a API responde 402 até a renovação.
- **Limites por assinante** (o dono não tem): `COC_MAX_ACCOUNTS` vilas (padrão 20)
  e os `COC_MAX_SNAPSHOTS` imports mais recentes por vila (padrão 150).
- **Alertas de assinantes**: sem toast do Windows (é a tela do servidor), e
  WhatsApp/Discord só para endereços públicos (nada de localhost, rede do Docker
  ou 169.254.169.254). O dono continua podendo usar o n8n/Evolution interno.
- **API key**: cada usuário gera a sua em ⚙️ Configurações. O banco guarda só o
  hash, então a chave aparece uma vez. A chave antiga do dono continua valendo.

## Login e segurança

O login liga automaticamente quando há senha configurada ou a Clash Labs ligada (obrigatório na VPS):

- Local (Windows): `python app.py --set-password` define a senha; sem senha, o
  app continua aberto (uso local).
- Produção: use `ADMIN_USER` + `ADMIN_PASSWORD_HASH` no `.env`
  (gere com `python tools/hash_password.py`).

Proteções: hash scrypt, sessão em cookie HttpOnly/SameSite (Secure com
`COC_HTTPS=1`), CSRF (double-submit + header `X-CSRF`), bloqueio progressivo por
IP após 5 falhas de login, headers CSP/nosniff/frame-deny, vilas sempre filtradas
pelo usuário logado e **API key** por usuário (⚙️ Configurações) para acessos
programáticos via `Authorization: Bearer` — usada
pela automação: `python automation\auto_capture.py --run --server https://coc.seudominio.tech --api-key SUAKEY`.

## Deploy na VPS — 1 clique (Windows)

Dê dois cliques em **`Deploy VPS.bat`** (host, usuário e subdomínio editáveis no
topo do arquivo). Ele empacota o projeto, envia por `scp` e roda o instalador
via `ssh` — você digita a senha da VPS 2x. Na primeira execução o instalador
pergunta usuário/senha de login do COC Control (senha vira hash scrypt no
`.env`, nunca fica em texto plano).

O instalador (`deploy/install_vps.sh`, idempotente):

1. extrai o projeto em `/opt/coc-control` (projeto compose separado — não toca
   no seu `automation-stack`);
2. sobe o container na rede do Caddy (`automation_proxy`), sem expor porta;
3. adiciona o bloco do subdomínio no `Caddyfile` (com backup) e recarrega o
   Caddy — HTTPS automático;
4. healthcheck + resumo.

Requisito: registro DNS **A** do subdomínio (padrão
`coccontrol.chriscsantosqa.tech`) apontando para a VPS. Rodar de novo o .bat
atualiza o código preservando `.env` e banco (volume `coc_control_data`).

## Deploy na VPS (Docker, manual)

```bash
# na VPS (pasta do projeto)
cp .env.example .env
python3 tools/hash_password.py        # cole o hash no .env
nano .env                             # ADMIN_USER, SECRET_KEY, TZ...
docker compose up -d --build
docker compose logs -f coc-control    # conferir subida
```

Sobe em `http://IP-DA-VPS:8420` (login obrigatório). Com proxy reverso
(Traefik/Nginx Proxy Manager — veja comentários no `docker-compose.yml`):
aponte um subdomínio (ex.: `coc.seudominio.tech`) para a porta interna 8420
com HTTPS e mantenha `COC_HTTPS=1` e `COC_BEHIND_PROXY=1` no `.env`.

Particularidades na VPS: o servidor não tem clipboard, então o toggle vira
**Watcher (navegador)** — a própria página lê o clipboard do seu PC (pede
permissão uma vez) e importa sozinha enquanto a aba estiver em foco: copie no
jogo e volte para a aba. Alternativas: **Importar do clipboard**, **Colar
JSON**, ou a automação no seu PC com `--server https://... --api-key ...`. Para o auto-sync da
Supercell funcionar, crie uma chave em developer.clashofclans.com com o **IP da
VPS**. O banco fica no volume `coc_data` (backup: `docker compose cp
coc-control:/data/coc_control.db ./backup.db`; o `Deploy VPS.bat` já faz um
backup em `/opt/coc-control/backups` antes de cada atualização).

## Aviso legal

Projeto pessoal não afiliado à Supercell. Usa apenas dados que o próprio jogo
exporta, conforme a [Fan Content Policy](https://www.supercell.com/fan-content-policy).
