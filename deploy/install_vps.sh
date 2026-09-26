#!/usr/bin/env bash
# ============================================================================
# COC Control — instalador para a VPS (idempotente; pode rodar de novo).
# Executado pelo "Deploy VPS.bat" após o upload do projeto para /opt/coc-control.
#
# O que faz:
#   1. cria o .env (pergunta usuário/senha na 1ª vez; senha vira hash scrypt)
#   2. build + up do container na rede do Caddy (automation_proxy)
#   3. adiciona o bloco do subdomínio no Caddyfile do automation-stack e
#      recarrega o Caddy (HTTPS automático via Let's Encrypt)
#   4. healthcheck e resumo
#
# Variáveis ajustáveis (pode exportar antes de rodar):
#   COC_DOMAIN   (padrão: coccontrol.chriscsantosqa.tech)
#   STACK_DIR    (padrão: /opt/automation-stack)
#   DRY_RUN=1    (mostra os comandos docker sem executar)
# ============================================================================
set -euo pipefail

DIR="/opt/coc-control"
COC_DOMAIN="${COC_DOMAIN:-coccontrol.chriscsantosqa.tech}"
STACK_DIR="${STACK_DIR:-/opt/automation-stack}"
CADDYFILE="$STACK_DIR/caddy/Caddyfile"
COMPOSE=(docker compose --project-directory "$DIR" -f "$DIR/deploy/docker-compose.vps.yml")

log()  { echo -e "\033[1;36m[coc-control]\033[0m $*"; }
warn() { echo -e "\033[1;33m[aviso]\033[0m $*"; }
die()  { echo -e "\033[1;31m[erro]\033[0m $*"; exit 1; }

run() {  # executa (ou só mostra, em DRY_RUN=1)
  if [ "${DRY_RUN:-0}" = "1" ]; then echo "  DRY: $*"; else "$@"; fi
}

[ -d "$DIR" ] || die "pasta $DIR não encontrada — o upload falhou?"
cd "$DIR"
command -v docker >/dev/null || die "docker não encontrado na VPS"

# rede do proxy (Caddy) do stack existente
PROXY_NET="$(docker network ls --format '{{.Name}}' | grep -E '(^|_)proxy$' | head -1 || true)"
[ -n "$PROXY_NET" ] || PROXY_NET="automation_proxy"
log "rede do proxy detectada: $PROXY_NET"

# ---------------------------------------------------------------- 1. .env
NEW_ENV=0
if [ ! -f .env ]; then
  NEW_ENV=1
  log "criando .env (primeira instalação)"
  printf "Usuário de login [chris]: " > /dev/tty
  read -r ADMIN_USER < /dev/tty || true
  ADMIN_USER="${ADMIN_USER:-chris}"
  while :; do
    printf "Senha de acesso (mín. 8 caracteres): " > /dev/tty
    read -rs PW1 < /dev/tty; echo > /dev/tty
    printf "Confirme a senha: " > /dev/tty
    read -rs PW2 < /dev/tty; echo > /dev/tty
    [ "$PW1" = "$PW2" ] || { warn "senhas não conferem"; continue; }
    [ "${#PW1}" -ge 8 ] || { warn "use pelo menos 8 caracteres"; continue; }
    break
  done
  SECRET_KEY="$(openssl rand -hex 32)"
  cat > .env <<ENVEOF
# COC Control — produção (gerado pelo instalador em $(date -Iseconds))
ADMIN_USER=$ADMIN_USER
# ADMIN_PASSWORD_HASH é preenchido após o build (hash scrypt)
ADMIN_PASSWORD_HASH=
SECRET_KEY=$SECRET_KEY
COC_HTTPS=1
COC_BEHIND_PROXY=1
COC_PROXY_NET=$PROXY_NET
TZ=America/Sao_Paulo
# Clash Labs (assinantes). Preencha para vender o COC Control pela vitrine:
# LABS_URL=https://clashlabs.seudominio
# LABS_PRODUCT_SECRET=   (o mesmo PRODUCT_COC_CONTROL_SECRET da vitrine)
ENVEOF
  chmod 600 .env
else
  log ".env já existe — mantendo configurações (senha/segredos preservados)"
  grep -q "^COC_PROXY_NET=" .env || echo "COC_PROXY_NET=$PROXY_NET" >> .env
fi

# ------------------------------------------------ 2a. backup antes de atualizar
# A versão multiusuário migra o banco na primeira subida (as vilas passam a ter dono).
# A migração é testada, mas o backup sai antes, com a API de backup do SQLite.
if [ "${DRY_RUN:-0}" != "1" ] && docker ps --format '{{.Names}}' | grep -qx coc-control; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$DIR/backups"
  if docker exec coc-control python -c "import sqlite3;s=sqlite3.connect('/data/coc_control.db');d=sqlite3.connect('/data/backup-$STAMP.db');s.backup(d);d.close()"      && docker cp "coc-control:/data/backup-$STAMP.db" "$DIR/backups/coc_control-$STAMP.db"      && docker exec coc-control rm -f "/data/backup-$STAMP.db"; then
    chmod 600 "$DIR/backups/coc_control-$STAMP.db"
    log "backup do banco: $DIR/backups/coc_control-$STAMP.db"
  else
    die "não consegui fazer o backup do banco; nada foi atualizado"
  fi
fi

# ------------------------------------------------------------- 2. build/up
log "build da imagem"
run "${COMPOSE[@]}" build

if [ "$NEW_ENV" = "1" ]; then
  log "gerando hash scrypt da senha dentro da imagem"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    HASH="scrypt:DRYRUN"
  else
    HASH="$(printf '%s' "$PW1" | "${COMPOSE[@]}" run --rm -T \
      coc-control python -c \
      'import sys;from werkzeug.security import generate_password_hash;print(generate_password_hash(sys.stdin.read()))' \
      | tr -d '\r' | tail -1)"
    [ -n "$HASH" ] || die "falha ao gerar hash da senha"
  fi
  sed -i "s|^ADMIN_PASSWORD_HASH=.*|ADMIN_PASSWORD_HASH=$HASH|" .env
  unset PW1 PW2
fi

log "subindo o serviço"
run "${COMPOSE[@]}" up -d

# ------------------------------------------------- 3. Caddy (proxy + HTTPS)
if [ -f "$CADDYFILE" ]; then
  if grep -q "$COC_DOMAIN" "$CADDYFILE"; then
    log "bloco do Caddy já existe para $COC_DOMAIN"
  else
    log "adicionando $COC_DOMAIN ao Caddyfile (backup: Caddyfile.bak-coc)"
    run cp "$CADDYFILE" "$CADDYFILE.bak-coc"
    if [ "${DRY_RUN:-0}" != "1" ]; then
      cat >> "$CADDYFILE" <<CADDYEOF

# COC Control (gerenciador de vilas) — adicionado pelo instalador
$COC_DOMAIN {
	reverse_proxy coc-control:8420
}
CADDYEOF
    fi
    if run docker exec caddy caddy validate --config /etc/caddy/Caddyfile; then
      run docker exec caddy caddy reload --config /etc/caddy/Caddyfile
      log "Caddy recarregado"
    else
      warn "Caddyfile inválido — restaurando backup"
      run cp "$CADDYFILE.bak-coc" "$CADDYFILE"
      die "bloco do Caddy não aplicado; verifique manualmente"
    fi
  fi
else
  warn "Caddyfile não encontrado em $CADDYFILE — configure o proxy manualmente:"
  warn "  $COC_DOMAIN { reverse_proxy coc-control:8420 }"
fi

# ------------------------------------------------------------ 4. health/DNS
if [ "${DRY_RUN:-0}" != "1" ]; then
  sleep 4
  if docker exec coc-control python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8420/api/health',timeout=5)" 2>/dev/null; then
    log "healthcheck OK ✔"
  else
    warn "healthcheck falhou — veja: docker logs coc-control"
  fi
fi
IP_DNS="$(getent hosts "$COC_DOMAIN" 2>/dev/null | awk '{print $1}' | head -1 || true)"
if [ -z "$IP_DNS" ]; then
  warn "DNS de $COC_DOMAIN ainda não resolve — crie o registro A: $COC_DOMAIN -> IP desta VPS."
  warn "O Caddy emite o certificado sozinho assim que o DNS apontar."
fi

echo
log "=================== RESUMO ==================="
log "URL:        https://$COC_DOMAIN (login obrigatório)"
log "Projeto:    $DIR   | dados no volume: coc-control_coc_control_data"
log "Comandos:   cd $DIR && docker compose --project-directory . -f deploy/docker-compose.vps.yml [logs -f|restart|up -d --build]"
log "API key:    após logar, ⚙️ Configurações (use na automação do seu PC:"
log "            auto_capture.py --run --server https://$COC_DOMAIN --api-key SUAKEY)"
log "Backup DB:  automático a cada atualização, em $DIR/backups"
log "=============================================="
