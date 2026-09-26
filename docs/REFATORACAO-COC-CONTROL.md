# COC Control — Refatoração Clash Labs

Este documento descreve a configuração e execução da refatoração do COC Control, preservando o modo proprietário local e endurecendo o acesso de assinantes pela Clash Labs.

## 1. Pré-requisitos

- Python 3.11+ recomendado.
- `pip` e ambiente virtual.
- SQLite disponível pelo Python.
- Para integração com a API oficial do Clash of Clans: token de desenvolvedor da Supercell.
- Para assinantes: acesso à Clash Labs e segredo compartilhado do produto `coc-control`.
- Para importar o pacote visual `coc.rar`: `unrar`, `7z` ou `unar` quando o módulo Python `rarfile` não conseguir extrair sozinho.

## 2. Instalação local

```bash
git clone https://github.com/chriscsantosqa/acc-control.git
cd acc-control
git checkout refactor/coc-control-clash-labs

python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. Variáveis de ambiente

Configuração mínima do proprietário:

```env
ADMIN_USER=chris
ADMIN_PASSWORD_HASH=
SECRET_KEY=
COC_HTTPS=0
COC_BEHIND_PROXY=0
TZ=America/Sao_Paulo
```

Gere a chave de sessão:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Gere o hash da senha usando o utilitário já existente no projeto:

```bash
python tools/hash_password.py
```

### Integração Clash Labs

```env
LABS_URL=https://seu-dominio-clash-labs
LABS_API_URL=https://seu-dominio-clash-labs
LABS_PRODUCT_SECRET=SEGREDO_COM_PELO_MENOS_32_CARACTERES
LABS_SYNC_INTERVAL=900
COC_MAX_ACCOUNTS=20
COC_MAX_SNAPSHOTS=150
```

`LABS_PRODUCT_SECRET` deve ser o mesmo segredo configurado para o produto `coc-control` na Clash Labs. Ele nunca deve ser enviado ao navegador ou salvo em JavaScript.

Gerador sugerido:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. Contrato SSO

Fluxo esperado:

1. O usuário acessa `/entrar/clash-labs`.
2. O COC Control cria `state` aleatório preso à sessão do navegador.
3. O navegador é enviado para `/app/coc-control?state=<state>&volta=%2F` na Clash Labs.
4. A Clash Labs retorna para `/api/labs/callback?code=<code>&state=<state>`.
5. O COC Control valida o `state`, que expira em 10 minutos e só pode ser usado uma vez.
6. O backend troca o `code` em `/api/v1/sso/redeem` usando `LABS_PRODUCT_SECRET`.
7. O usuário é vinculado somente pelo `labs_user_id` UUID. E-mail nunca é usado para vínculo de identidade.
8. O acesso só é considerado ativo quando o entitlement pertence ao produto `coc-control`, está ativo e possui `accessUntil` futuro com timezone.

Quando o callback chega sem `state`, o código recebido não é trocado: uma nova rodada SSO é iniciada.

## 5. Webhook de entitlement

Endpoint:

```text
POST /api/labs/webhook
```

Cabeçalhos:

```text
Authorization: Bearer <LABS_PRODUCT_SECRET>
X-Labs-Product: coc-control
Content-Type: application/json
```

Payload:

```json
{
  "userId": "550e8400-e29b-41d4-a716-446655440000"
}
```

Comportamento esperado:

- segredo incorreto: `401`;
- produto incorreto: `401`;
- `userId` fora do formato UUID: `422`;
- usuário ainda não existente no COC Control: `200` sem revelar a ausência;
- indisponibilidade da Clash Labs durante a releitura do entitlement: `502`;
- sucesso: `200`.

## 6. Importação dos assets do Clash of Clans

O repositório não precisa depender de CDN para os assets fornecidos no pacote local.

Execute:

```bash
python tools/import_coc_assets.py /caminho/para/coc.rar
```

No Windows:

```powershell
python tools\import_coc_assets.py C:\caminho\coc.rar
```

Destino:

```text
static/assets/coc/
```

O script também gera:

```text
static/assets/coc/assets-manifest.json
```

Arquivos de licença e proveniência presentes no pacote são preservados. O pacote analisado contém heróis, tropas, feitiços, pets, equipamentos, Town Halls, recursos, ícones e ligas. Não foi identificada uma coleção dedicada de imagens para todas as construções; nesses casos a interface deve manter fallback visual em vez de inventar arquivos ausentes.

## 7. API oficial da Supercell

A chave de desenvolvedor da Supercell continua sendo configuração de servidor/proprietário. O COC Control utiliza a Player API para enriquecer os dados de cada vila, incluindo informações disponíveis de heróis, tropas, feitiços, equipamentos, liga, troféus, doações, guerra e demais campos retornados oficialmente.

A importação JSON da vila continua sendo a fonte para progresso, timers, custos, recursos e planejamento quando essas informações não existem na Player API pública.

## 8. Execução

Servidor padrão:

```bash
python app.py
```

Sem watcher de clipboard:

```bash
python app.py --no-watcher
```

Abra:

```text
http://127.0.0.1:8420
```

Em VPS com HTTPS e proxy reverso:

```env
COC_HTTPS=1
COC_BEHIND_PROXY=1
```

O proxy deve terminar TLS e encaminhar para a porta interna do COC Control.

## 9. Testes

Execute todos os testes:

```bash
pytest -q
```

Somente o contrato Clash Labs:

```bash
pytest -q tests/test_labs_contract.py tests/test_multiuser.py
```

Os testes de segurança devem cobrir, no mínimo:

- state correto;
- state ausente;
- state reutilizado;
- state de outro navegador;
- UUID inválido;
- webhook com segredo/produto inválidos;
- entitlement expirado e renovado;
- isolamento entre usuários;
- migração de banco antigo sem perda de dados.

## 10. Checklist antes de produção

1. Fazer backup de `coc_control.db`.
2. Configurar `SECRET_KEY` forte.
3. Configurar `ADMIN_PASSWORD_HASH`.
4. Configurar `LABS_URL`, `LABS_API_URL` e `LABS_PRODUCT_SECRET`.
5. Ativar `COC_HTTPS=1` somente atrás de HTTPS real.
6. Importar os assets locais do `coc.rar`.
7. Configurar o token oficial da Supercell pela área administrativa.
8. Executar `pytest -q`.
9. Validar login do proprietário.
10. Validar SSO de assinante em navegador separado.
11. Validar renovação/expiração via webhook.
12. Conferir que assinantes não conseguem acessar IDs de vilas/snapshots de outros usuários.

## 11. Segurança aplicada nesta alteração

- identificação Clash Labs limitada a UUID canônico;
- state SSO com TTL de 10 minutos e uso único;
- comparação do segredo em tempo constante;
- sem vínculo por e-mail;
- redirects HTTP da central desabilitados;
- entitlement validado por produto, status e data futura com timezone;
- falha de upstream no webhook representada como `502`;
- assets servidos localmente pelo projeto, sem necessidade de CDN externa;
- segredo da Clash Labs permanece exclusivamente no backend.

## 12. Aviso

COC Control é uma ferramenta independente e não é afiliada, endossada ou patrocinada pela Supercell.
