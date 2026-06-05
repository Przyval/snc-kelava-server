#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# migrate_enterprise_db.sh — Backup enterprise DB dari VPS lama → restore ke baru
#
# Usage (jalankan dari laptop, BUKAN di VPS):
#   bash scripts/migrate_enterprise_db.sh OLD_VPS_IP NEW_VPS_IP
#
# Contoh:
#   bash scripts/migrate_enterprise_db.sh 104.194.154.108 203.0.113.42
#
# Asumsi:
#   - Anda punya SSH access ke kedua VPS (bisa via console kalau key hilang)
#   - DB credentials sama: kil_ent / KilEnt2026! di local enterprise DB
#   - File backup disimpan lokal: ~/Downloads/enterprise_backup_YYYYMMDD.sql
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

OLD_VPS="${1:?Usage: $0 OLD_VPS_IP NEW_VPS_IP}"
NEW_VPS="${2:?Usage: $0 OLD_VPS_IP NEW_VPS_IP}"
DB_NAME="kil_enterprise"
DB_USER="kil_ent"
DB_PASS="KilEnt2026!"
BACKUP_FILE="$HOME/Downloads/enterprise_backup_$(date +%Y%m%d_%H%M%S).sql"

echo "═══════════════════════════════════════════════════════════════════"
echo " Migrate enterprise DB: $OLD_VPS → $NEW_VPS"
echo " Backup file: $BACKUP_FILE"
echo "═══════════════════════════════════════════════════════════════════"

# ── 1. Dump dari VPS lama ─────────────────────────────────────────────────
echo "▶ [1/4] pg_dump dari ${OLD_VPS}..."
ssh "root@${OLD_VPS}" \
    "PGPASSWORD='${DB_PASS}' pg_dump -h 127.0.0.1 -U ${DB_USER} ${DB_NAME} \
     --no-owner --no-acl --clean --if-exists" \
    > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "  ✓ Backup OK: ${SIZE}"

# ── 2. Inspect ───────────────────────────────────────────────────────────
echo ""
echo "▶ [2/4] Inspect backup..."
echo "  Tables ke-export:"
grep -E "^CREATE TABLE" "$BACKUP_FILE" | awk '{print "    -",$3}'
echo ""
echo "  Lines: $(wc -l < "$BACKUP_FILE")"

# ── 3. Upload + restore ke VPS baru ──────────────────────────────────────
echo ""
echo "▶ [3/4] Upload ke ${NEW_VPS}..."
scp "$BACKUP_FILE" "root@${NEW_VPS}:/tmp/enterprise_restore.sql"

echo ""
echo "▶ [4/4] Restore ke VPS baru..."
ssh "root@${NEW_VPS}" \
    "PGPASSWORD='${DB_PASS}' psql -h 127.0.0.1 -U ${DB_USER} ${DB_NAME} \
     -f /tmp/enterprise_restore.sql 2>&1 | tail -20"

# ── Verify ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Verifikasi tabel di VPS baru:"
ssh "root@${NEW_VPS}" \
    "PGPASSWORD='${DB_PASS}' psql -h 127.0.0.1 -U ${DB_USER} ${DB_NAME} -c \"
     SELECT schemaname, tablename, n_live_tup AS rows
     FROM pg_stat_user_tables ORDER BY tablename;\""

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " ✓ Migration selesai. Backup file: $BACKUP_FILE"
echo "═══════════════════════════════════════════════════════════════════"
