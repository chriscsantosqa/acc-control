# Refatoração COC Control — execução e configuração

Esta versão mantém o backend Flask/SQLite existente e evolui o COC Control para um painel de **Village Intelligence**, com perfil do jogador, progresso da vila, custos e tempos pendentes, arsenal (heróis, equipamentos, tropas, feitiços, máquinas e pets), planejamento, histórico e integração segura com a Clash Labs.

> COC Control não é afiliado, endossado ou patrocinado pela Supercell.

## 1. Requisitos

- Python 3.11+ recomendado.
- Dependências de `requirements.txt`.
- Para produção: proxy reverso HTTPS recomendado.
- Token da API oficial do Clash of Clans para sincronização de jogador.
- Para importar o pacote `coc.rar`: 7-Zip (`7z`/`7zz`), `unar`, `bsdtar` ou `unrar` disponível no sistema.

## 2. Instalação

```bash
git clone https://github.com/chriscsantosqa/acc-control.git
cd acc-control
git checkout refactor/coc-control-player-intelligence

python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## 3. Variáveis de ambiente

O `.env.example` já contém a base necessária.

### Login do dono

```env
ADMIN_USER=chris
ADMIN_PASSWORD_HASH=
# ou, apenas se necessário:
# ADMIN_PASSWORD=troque-esta-senha
SECRET_KEY=
```

Gere o hash de senha com:

```bash
python tools/hash_password.py
```

Gere uma `SECRET_KEY` com:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Produção / proxy

```env
COC_HTTPS=1
COC_BEHIND_PROXY=1
TZ=America/Sao_Paulo
```

`COC_HTTPS=1` faz o cookie de sessão usar `Secure`. Ative somente quando a aplicação estiver publicada por HTTPS.

### Clash Labs

```env
LABS_URL=https://SEU-DOMINIO-CLASH-LABS
LABS_API_URL=https://SEU-ENDERECO-DE-API-CLASH-LABS
LABS_PRODUCT_SECRET=SEGREDO_COM_32_OU_MAIS_CARACTERES
LABS_SYNC_INTERVAL=900
COC_MAX_ACCOUNTS=20
COC_MAX_SNAPSHOTS=150
```

Regras da integração:

- Produto: `coc-control`.
- O vínculo do assinante é feito **somente por `labs_user_id` UUID**; e-mail nunca vincula contas.
- Entrada: `/entrar/clash-labs` cria `state` de uso único e validade de 10 minutos.
- Callback: `/api/labs/callback`.
- Webhook: `/api/labs/webhook`.
- O webhook deve enviar:
  - `Authorization: Bearer <LABS_PRODUCT_SECRET>`
  - `X-Labs-Product: coc-control`
  - JSON `{ "userId": "<uuid>" }`
- Segredo incorreto: `401`.
- UUID malformado: `422`.
- Falha ao reconferir o entitlement na central: `502`.
- Usuário ainda inexistente no produto: `200`, sem revelar sua existência.
- Passe vencido: rotas da vila retornam `402`, mas os dados permanecem armazenados.
- Usuário vencido continua podendo acessar `/api/me`, exportar os próprios dados e solicitar exclusão.
- Suspensão manual do dono é independente do entitlement e não é removida por uma sincronização da Clash Labs.

## 4. API oficial do Clash of Clans

A chave de desenvolvedor da Supercell continua sendo uma configuração global do servidor e somente o dono pode alterá-la.

1. Entre como dono.
2. Abra **Configurações**.
3. Informe o **Token de desenvolvedor Supercell**.
4. Salve.
5. Cadastre uma vila com a tag do jogador.
6. Clique em **Sincronizar API**.

A Player API alimenta nome, tag, troféus, liga, estatísticas e o Arsenal. O export JSON do jogo continua sendo usado para progresso fino, níveis pendentes, custos, filas e ETAs.

## 5. Assets do `coc.rar`

Os binários do arquivo enviado no chat não são transferidos automaticamente pelo conector do GitHub. O PR inclui `tools/import_coc_assets.py` para colocar os assets no caminho esperado pelo frontend.

Com o `coc.rar` disponível localmente:

```bash
python tools/import_coc_assets.py /caminho/para/coc.rar --repo .
```

O destino é:

```text
static/assets/coc/
```

O frontend procura, entre outros:

```text
static/assets/coc/townhall/
static/assets/coc/heroes/
static/assets/coc/equipment/
static/assets/coc/troops/
static/assets/coc/spells/
static/assets/coc/pets/
static/assets/coc/resources/
static/assets/coc/icons/
```

O pacote analisado contém Town Halls, heróis, equipamentos, tropas, feitiços, pets, recursos, ícones e ligas. **Ele não contém uma pasta completa de assets de construções**, portanto construções sem imagem específica permanecem com representação textual/fallback; isso não é preenchido silenciosamente com uma fonte externa.

Preserve também os arquivos de licença/proveniência existentes no pacote de assets.

## 6. Banco de dados e migração

O SQLite continua sendo a fonte local do COC Control.

Antes de uma alteração de schema em banco existente, a aplicação cria automaticamente um backup consistente com o padrão:

```text
coc_control.db.pre-migration-YYYYMMDD-HHMMSS.bak
```

A migração:

- preserva IDs das vilas legadas;
- preserva snapshots e estatísticas;
- mantém as vilas antigas pertencendo ao dono;
- adiciona suspensão manual aos usuários;
- adiciona `access_audit` para mudanças de acesso;
- continua idempotente.

Ainda é recomendado manter backup externo/volume snapshot antes de qualquer deploy de produção.

## 7. Privacidade e isolamento

- Toda vila pertence a um `user_id`.
- ID de vila ou snapshot pertencente a outro usuário retorna `404`.
- Assinantes não recebem o token global da Supercell.
- A API key do usuário é armazenada somente como hash e exibida uma única vez na criação.
- `GET /api/me/export` exporta os dados do próprio usuário sem hashes de API key ou segredo global da Supercell.
- `DELETE /api/me/data` remove conta, vilas, snapshots e configurações do assinante; a conta do dono não pode ser removida por essa rota.
- Mutação via sessão exige `X-CSRF` correspondente ao cookie `csrf`.
- Cookies de sessão são `HttpOnly`.
- URLs configuráveis por assinantes continuam passando pelas validações contra SSRF e exigem destinos públicos HTTPS.

## 8. Testes

Validação sintática:

```bash
python -m py_compile app.py coc/db.py coc/labs.py tools/import_coc_assets.py tests/test_contract_refactor.py
```

Suíte principal:

```bash
python tests/test_auth.py
python tests/test_basic.py
python tests/test_features.py
python tests/test_matcher.py
python tests/test_sync_all.py
python tests/test_multiuser.py
python tests/test_contract_refactor.py
```

A suíte multiusuário cobre, entre outros:

- migração de banco legado e backup pré-migration;
- state ausente, reutilizado e de outro navegador;
- código SSO de uso único;
- UUID da Labs;
- isolamento entre assinantes;
- `404` para IDs de outro usuário;
- CSRF;
- owner-only;
- suspensão e reativação manual;
- webhook `401`, `422` e `502`;
- passe vencido e renovado;
- preservação do histórico;
- limites por assinatura;
- proteção contra SSRF;
- exportação e exclusão dos próprios dados.

## 9. Execução local

```bash
python app.py --no-watcher
```

Padrão:

```text
http://127.0.0.1:8420
```

Para não abrir o navegador automaticamente:

```bash
python app.py --no-watcher --no-browser
```

## 10. Execução em produção

A aplicação já suporta Waitress:

```bash
python app.py --production --host 0.0.0.0 --port 8420 --no-browser --no-watcher
```

Ou defina:

```env
COC_PRODUCTION=1
```

Recomendações de produção:

1. Publique atrás de Nginx/Traefik/Caddy com HTTPS.
2. Use `COC_HTTPS=1`.
3. Use `COC_BEHIND_PROXY=1` somente atrás do proxy confiável.
4. Não exponha a porta SQLite nem arquivos `.env`.
5. Restrinja permissões do arquivo do banco.
6. Mantenha `LABS_PRODUCT_SECRET` apenas no servidor.
7. Faça backup externo antes do primeiro deploy desta versão.
8. Após subir, valide `/api/health` e realize um SSO completo de teste.

## 11. Fluxo recomendado de validação pós-deploy

1. `GET /api/health` retorna `200` e `{ "ok": true }`.
2. Login do dono funciona.
3. Token da Supercell está configurado.
4. Uma vila sincroniza pela Player API.
5. Importação do JSON do jogo gera snapshot/progresso.
6. Arsenal apresenta dados retornados pela Player API.
7. SSO Clash Labs cria uma conta assinante separada.
8. Assinante A não acessa IDs da vila do assinante B (`404`).
9. Suspensão manual bloqueia o assinante e não é revertida pelo webhook.
10. Expiração do passe retorna `402` e a renovação recupera o mesmo histórico.
11. Exportação dos próprios dados funciona mesmo com passe vencido.
12. Alertas e canais configurados continuam isolados por usuário.
