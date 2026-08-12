#!/bin/bash
# Deploy script untuk EVA Finance Assistant di VPS
# Dijalankan Hajid via SSH: sudo bash deploy/deploy.sh
set -e

AGENT_NAME="eva-finance"
PORT="8081"
DOMAIN="finance.holomoc.com"

DEPLOY_DIR="/var/www/${AGENT_NAME}"
PROJECT_DIR="${DEPLOY_DIR}/holomoc-bot"
VENV_DIR="${DEPLOY_DIR}/venv"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }

[[ $EUID -ne 0 ]] && { echo "Jalankan dengan sudo"; exit 1; }

log "Install system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git nginx ffmpeg

log "Setup folder storage..."
mkdir -p "${DEPLOY_DIR}/storage-data"/{rmb,cas,pr,po,qt,inv,bud,laporan,exports}

log "Setup virtualenv..."
[ ! -d "${VENV_DIR}" ] && python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip -q
"${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt" -q

log "Setup .env..."
if [ ! -f "${DEPLOY_DIR}/.env" ]; then
    cp "${PROJECT_DIR}/.env.production" "${DEPLOY_DIR}/.env"
    warn "Isi ${DEPLOY_DIR}/.env dengan nilai yang benar lalu restart service!"
fi

log "Set permissions..."
chown -R www-data:www-data "${DEPLOY_DIR}"
chmod 600 "${DEPLOY_DIR}/.env"

log "Install systemd service..."
cp "${PROJECT_DIR}/deploy/systemd/eva-finance.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable eva-finance
systemctl restart eva-finance

log "Install nginx config..."
cp "${PROJECT_DIR}/deploy/nginx/eva-finance" /etc/nginx/sites-available/eva-finance
ln -sf /etc/nginx/sites-available/eva-finance /etc/nginx/sites-enabled/eva-finance
nginx -t && systemctl reload nginx

log "=== SELESAI ==="
log "Cek status : systemctl status eva-finance"
log "Lihat log  : journalctl -u eva-finance -f"
warn "Jangan lupa pasang SSL: certbot --nginx -d ${DOMAIN}"
