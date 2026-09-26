# Refatoração COC Control — execução e configuração

Esta versão mantém Flask + SQLite e evolui o COC Control para um painel de **Player/Village Intelligence**, usando a API oficial da Supercell para dados vivos do jogador e o export oficial/game data para progresso, custos, tempos e planejamento.

> COC Control não é afiliado, endossado ou patrocinado pela Supercell.

## 1. Branch e PR

Branch da refatoração:

```text
refactor/clash-labs-player-intelligence
```

Para testar antes do merge:

```bash
git fetch origin
git checkout refactor/clash-labs-player-intelligence
```

## 2. Requisitos

- Python 3.11+ para execução local.
- Docker + Docker Compose recomendado para VPS/produção.
- Token de desenvolvedor da API oficial do Clash of Clans para sincronização do jogador.
- Proxy reverso HTTPS recomendado em produção.

## 3. Instalação local

Crie o ambiente virtual e instale as dependências:

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Variáveis no modo local

O `app.py` lê as variáveis do **ambiente do processo**. Copiar `.env.example` para `.env` sozinho não faz o Python carregar esse arquivo.

No modo local você pode:

1. definir as variáveis no terminal/sistema operacional; ou
2. usar Docker Compose, que já possui `env_file: .env`.

Exemplo PowerShell para uma execução local simples:

```powershell
$env:ADMIN_USER="chris"
$env:ADMIN_PASSWORD="troque-esta-senha"
$env:SECRET_KEY="SEGREDO_ALEATORIO"
python app.py --no-watcher --no-browser
```

Sem configuração de login, o comportamento local existente pode continuar sem autenticação do dono, conforme a configuração atual da aplicação.

## 4. Arquivo `.env` para Docker Compose / produção

Crie a partir do exemplo:

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configuração principal:

```env
ADMIN_USER=chris
ADMIN_PASSWORD_HASH=
SECRET_KEY=
TZ=America/Sao_Paulo

# Produção atrás de HTTPS/proxy confiável
COC_HTTPS=1
COC_BEHIND_PROXY=1

# Clash Labs
LABS_URL=https://SEU-DOMINIO-CLASH-LABS
LABS_API_URL=https://SEU-ENDERECO-DE-API-CLASH-LABS
LABS_PRODUCT_SECRET=SEGREDO_COM_32_OU_MAIS_CARACTERES
LABS_SYNC_INTERVAL=900

# Limites dos assinantes
COC_MAX_ACCOUNTS=20
COC_MAX_SNAPSHOTS=150
```

Gere o hash da senha do dono com:

```bash
python tools/hash_password.py
```

Gere uma `SECRET_KEY` com:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

`COC_HTTPS=1` deve ser usado quando a URL pública realmente estiver em HTTPS, pois o cookie de sessão passa a usar `Secure`.

`COC_BEHIND_PROXY=1` deve ser usado somente atrás de proxy reverso confiável.

## 5. Clash Labs

Produto:

```text
coc-control
```

Fluxo:

- entrada: `GET /entrar/clash-labs`;
- callback: `GET /api/labs/callback`;
- webhook: `POST /api/labs/webhook`;
- vínculo: somente `labs_user_id` UUID, nunca e-mail;
- `state`: ligado à sessão do navegador, uso único, TTL de 10 minutos;
- passe válido: produto correto + `active=true` + `accessUntil` futuro com timezone;
- passe vencido: rotas das vilas retornam `402`, mas os dados permanecem preservados;
- suspensão manual do dono é independente da Clash Labs e não é revertida pelo sync.

Headers do webhook:

```http
Authorization: Bearer <LABS_PRODUCT_SECRET>
X-Labs-Product: coc-control
Content-Type: application/json
```

Body:

```json
{
  "userId": "11111111-1111-4111-8111-111111111111"
}
```

Respostas relevantes:

- segredo/produto inválido: `401`;
- `userId` malformado: `422`;
- usuário ainda inexistente localmente: `200`;
- falha ao reconferir entitlement na central: `502`.

Na Clash Labs, o segredo configurado para o produto deve ser exatamente o mesmo valor de `LABS_PRODUCT_SECRET`, e a URL do produto deve apontar para a URL pública HTTPS do COC Control.

## 6. API oficial da Supercell

O token de desenvolvedor da Supercell permanece uma configuração global do servidor e somente o dono pode alterá-lo.

Passos:

1. entre no COC Control como dono;
2. abra **Configurações**;
3. informe o **Token de desenvolvedor Supercell**;
4. salve;
5. cadastre uma vila com a tag do jogador;
6. use **Sincronizar** no jogador ou **Sincronizar todas**.

A Player API alimenta nome, tag, Centro de Vila, liga, troféus, clã, estatísticas e Arsenal. O export oficial continua responsável pelo progresso detalhado, timers, custos, filas e ETAs.

## 7. Assets locais

O PR já versiona **686 assets** em:

```text
static/assets/coc/
```

O pacote inclui, entre outros:

```text
static/assets/coc/buildings/
static/assets/coc/townhall/
static/assets/coc/heroes/
static/assets/coc/equipment/
static/assets/coc/troops/
static/assets/coc/spells/
static/assets/coc/pets/
static/assets/coc/resources/
static/assets/coc/icons/
static/assets/coc/leagues/
```

Os arquivos de licença/proveniência do pacote foram preservados.

Para futuras atualizações a partir de outro `coc.rar`:

```bash
python tools/import_coc_assets.py /caminho/para/coc.rar --repo .
```

O importador aceita um extrator RAR disponível no sistema, como 7-Zip, `unar`, `bsdtar` ou `unrar`.

## 8. Banco SQLite e migration

Em Docker o banco fica persistido fora da imagem em:

```text
/data/coc_control.db
```

Antes de uma alteração necessária de schema em banco existente, a aplicação cria um backup consistente com o padrão:

```text
coc_control.db.pre-migration-YYYYMMDD-HHMMSS.bak
```

A migration:

- preserva IDs das vilas legadas;
- preserva snapshots e estatísticas;
- mantém as vilas existentes vinculadas ao dono;
- preserva as configurações do dono;
- migra a API key legada sem mantê-la em texto puro;
- adiciona suspensão manual e `access_audit`;
- é idempotente.

Mantenha também backup externo/volume snapshot antes do primeiro deploy em produção.

## 9. Privacidade e isolamento

- cada vila pertence a um `user_id`;
- ID de vila/snapshot de outro usuário retorna `404`;
- assinantes não recebem o token global da Supercell;
- API key é armazenada como hash;
- `GET /api/me/export` exporta os próprios dados sem hash da API key ou segredo global da Supercell;
- `DELETE /api/me/data` exclui a conta e dados próprios do assinante;
- a conta do dono não pode ser excluída por essa rota;
- mutações por sessão exigem CSRF;
- cookie da sessão é `HttpOnly`;
- URLs configuráveis por assinante continuam protegidas contra SSRF e devem ser públicas/HTTPS;
- assinante suspenso manualmente não recebe notificações.

## 10. Testes e CI

O PR inclui:

```text
.github/workflows/coc-control-tests.yml
```

O workflow executa:

```bash
python -m py_compile app.py coc/*.py tools/import_coc_assets.py tests/test_contract_refactor.py
python tests/test_auth.py
python tests/test_basic.py
python tests/test_features.py
python tests/test_matcher.py
python tests/test_sync_all.py
python tests/test_multiuser.py
python tests/test_contract_refactor.py
```

A suíte cobre migration legada, SSO/state, UUID, isolamento, `404` cross-tenant, CSRF, API key, suspensão/reativação manual, webhook `401/422/502`, expiração/renovação, limites, SSRF, exportação e exclusão própria.

## 11. Execução local

Com as variáveis necessárias já definidas no ambiente:

```bash
python app.py --no-watcher --no-browser
```

Endereço padrão:

```text
http://127.0.0.1:8420
```

Para manter o watcher local do clipboard, remova `--no-watcher`.

## 12. Execução recomendada com Docker Compose

O `docker-compose.yml` já usa:

```yaml
env_file: .env
```

Suba/reconstrua:

```bash
docker compose up -d --build
```

Acompanhe:

```bash
docker compose logs -f coc-control
```

Valide o healthcheck:

```bash
curl http://127.0.0.1:8420/api/health
```

Resposta esperada:

```json
{"ok":true}
```

O container executa o app em produção na porta `8420`, com banco persistente no volume `coc_data`.

## 13. Produção com proxy reverso

Recomendações:

1. publique atrás de Nginx, Traefik ou Caddy com HTTPS;
2. defina `COC_HTTPS=1`;
3. mantenha `COC_BEHIND_PROXY=1` apenas atrás do proxy confiável;
4. não exponha `.env` nem o arquivo SQLite;
5. mantenha `LABS_PRODUCT_SECRET` somente nos servidores envolvidos;
6. restrinja permissões do volume/banco;
7. faça backup externo antes do primeiro deploy desta versão.

Se usar Traefik/rede externa, adapte a seção já comentada no `docker-compose.yml`, expondo internamente a porta `8420` para o proxy.

## 14. Checklist pós-deploy

1. `GET /api/health` retorna `200` e `{ "ok": true }`.
2. Login do dono funciona.
3. Token da Supercell está configurado.
4. Uma vila sincroniza pela Player API.
5. Importação do JSON oficial gera snapshot, progresso, custos e ETA.
6. Arsenal e assets locais são exibidos.
7. SSO Clash Labs cria um assinante separado.
8. Assinante A não acessa IDs do assinante B (`404`).
9. Suspensão manual bloqueia o assinante, interrompe alertas e não é revertida pelo webhook/sync.
10. Expiração do passe retorna `402` sem apagar dados.
11. Renovação recupera as mesmas vilas e histórico.
12. Exportação dos próprios dados não contém segredos do servidor.
13. Canais de notificação permanecem isolados por usuário.
