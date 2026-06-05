#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup_new_vps.sh — Bootstrap VPS baru untuk SanoCare/KIL
# Target: Ubuntu 22.04 LTS clean install
# Usage:  curl -fsSL https://raw.githubusercontent.com/Przyval/snc-kelava-server/main/scripts/setup_new_vps.sh | sudo bash -s -- kalender.safencare.work
# Atau:   sudo bash setup_new_vps.sh kalender.safencare.work
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="${1:-kalender.safencare.work}"
DEPLOY_DIR="/root/kil-server"
DB_NAME="kil_enterprise"
DB_USER="kil_ent"
DB_PASS="KilEnt2026!"        # CHANGE THIS untuk produksi serius
REPO="https://github.com/Przyval/snc-kelava-server.git"

echo "═══════════════════════════════════════════════════════════════════"
echo " Setup VPS baru untuk SanoCare/KIL"
echo " Domain: $DOMAIN"
echo " Deploy: $DEPLOY_DIR"
echo "═══════════════════════════════════════════════════════════════════"

# ── 1. System packages ────────────────────────────────────────────────────
echo "▶ [1/9] Update + install packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3.10 python3.10-venv python3-pip \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    git rsync curl jq ufw fail2ban htop

# ── 2. PostgreSQL — Enterprise auth DB ───────────────────────────────────
echo "▶ [2/9] Setup PostgreSQL..."
systemctl enable --now postgresql
sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" 2>/dev/null || true

# ── 3. Firewall ──────────────────────────────────────────────────────────
echo "▶ [3/9] Firewall (UFW)..."
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https
ufw --force enable

# ── 4. Clone repo ────────────────────────────────────────────────────────
echo "▶ [4/9] Clone repository..."
if [ ! -d "$DEPLOY_DIR" ]; then
    git clone "$REPO" "$DEPLOY_DIR"
else
    cd "$DEPLOY_DIR" && git pull
fi

# ── 5. Python venv + deps ────────────────────────────────────────────────
echo "▶ [5/9] Python venv + dependencies..."
cd "$DEPLOY_DIR"
python3.10 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
.venv/bin/pip install --quiet gunicorn

# ── 6. .env file (PLACEHOLDER — perlu di-edit manual) ────────────────────
echo "▶ [6/9] Create .env (perlu di-edit manual setelah ini)..."
cat > "$DEPLOY_DIR/.env" <<ENVEOF
# ─── App ─────────────────────────────────
KIL_ENV=PROD
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)

# ─── Kelava DB (operasional, READ-ONLY) ──
# IMPORTANT: minta whitelist IP VPS baru ini ke ~Kamz
KELAVA_HOST=172.104.188.76
KELAVA_PORT=5432
KELAVA_DB=sanocare
KELAVA_USER=snc_read
KELAVA_PASSWORD=SnCR3aD2026&

# ─── Local Enterprise DB ─────────────────
LOCAL_DB_HOST=127.0.0.1
LOCAL_DB_PORT=5432
LOCAL_DB_NAME=${DB_NAME}
LOCAL_DB_USER=${DB_USER}
LOCAL_DB_PASSWORD=${DB_PASS}
ENVEOF
chmod 600 "$DEPLOY_DIR/.env"

# ── 7. Gunicorn config ────────────────────────────────────────────────────
echo "▶ [7/9] Gunicorn config..."
cat > "$DEPLOY_DIR/gunicorn.conf.py" <<'GUNEOF'
bind = "127.0.0.1:5002"
workers = 2
threads = 4
worker_class = "gthread"
timeout = 60
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
GUNEOF

# ── 8. Systemd service ────────────────────────────────────────────────────
echo "▶ [8/9] Systemd service..."
cp "$DEPLOY_DIR/infra/kil-api.service" /etc/systemd/system/kil-api.service
systemctl daemon-reload
systemctl enable kil-api

# ── 9. Nginx + SSL ────────────────────────────────────────────────────────
echo "▶ [9/9] Nginx config + Let's Encrypt..."
# Generate nginx config dengan domain baru (substitute safencare.work → DOMAIN)
sed "s/safencare\.work/${DOMAIN}/g; s/server_name ${DOMAIN} www\.${DOMAIN}/server_name ${DOMAIN}/g" \
    "$DEPLOY_DIR/infra/nginx.conf" > /etc/nginx/sites-available/kil-api

# Sementara pakai HTTP-only sampai SSL ready
cat > /etc/nginx/sites-available/kil-api-bootstrap <<NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ { root /var/www/html; }

    location / {
        proxy_pass http://127.0.0.1:5002;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF
ln -sf /etc/nginx/sites-available/kil-api-bootstrap /etc/nginx/sites-enabled/kil-api
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " ✓ Base setup selesai."
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "LANGKAH SELANJUTNYA (manual):"
echo ""
echo "  1. Tambah DNS A record:"
echo "       ${DOMAIN}  →  $(curl -s ifconfig.me)"
echo "       (tunggu propagasi ~5 menit, cek via: dig ${DOMAIN})"
echo ""
echo "  2. Restore DB lama (kalau ada backup):"
echo "       bash ${DEPLOY_DIR}/scripts/restore_enterprise_db.sh enterprise_backup.sql"
echo "     ATAU seed bersih:"
echo "       ${DEPLOY_DIR}/.venv/bin/python ${DEPLOY_DIR}/kil/backend/scripts/seed_enterprise_users.py"
echo ""
echo "  3. Apply semua migrations:"
echo "       cd ${DEPLOY_DIR}/kil/db/migrations"
echo "       for f in *.sql; do PGPASSWORD=${DB_PASS} psql -h 127.0.0.1 -U ${DB_USER} -d ${DB_NAME} -f \$f; done"
echo ""
echo "  4. Import master rules:"
echo "       ${DEPLOY_DIR}/.venv/bin/python -m kil.backend.scripts.import_master_rules_xlsx \\"
echo "         '${DEPLOY_DIR}/data/golden/Data Jadwal Client & Teknisi.xlsx'"
echo ""
echo "  5. Start service:"
echo "       systemctl start kil-api"
echo "       systemctl status kil-api"
echo ""
echo "  6. Setup SSL (setelah DNS sudah propagasi):"
echo "       certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@safencare.work"
echo ""
echo "  7. Update Kelava whitelist (kontak ~Kamz):"
echo "       Tambah IP $(curl -s ifconfig.me) ke pg_hba whitelist Kelava DB."
echo ""
echo "  8. Update GitHub Actions secret (di github.com/Przyval/snc-kelava-server):"
echo "       SSH_PRIVATE_KEY  → private key VPS baru ini"
echo "       DEPLOY_HOST      → $(curl -s ifconfig.me)"
echo "       DEPLOY_DOMAIN    → ${DOMAIN}"
echo ""
echo "═══════════════════════════════════════════════════════════════════"
