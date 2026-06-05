# Runbook — Migrasi ke VPS Baru + Subdomain `kalender.safencare.work`

**Last updated**: 2026-06-05
**Estimated time**: 60-90 menit (kalau DNS sudah propagasi cepat)
**Prerequisite**: VPS baru sudah di-provision (Ubuntu 22.04+, root SSH access), domain `safencare.work` di-kelola di Cloudflare/registrar.

---

## Ringkasan flow

```
┌──────────────┐    ┌────────────────────┐    ┌──────────────────┐
│ 1. DNS A     │───▶│ 2. Bootstrap VPS   │───▶│ 3. Migrate DB    │
│  record      │    │  (setup_new_vps.sh)│    │  (dump+restore)  │
└──────────────┘    └────────────────────┘    └──────────────────┘
                                                       │
                                                       ▼
┌──────────────┐    ┌────────────────────┐    ┌──────────────────┐
│ 6. Kelava    │◀───│ 5. SSL + service   │◀───│ 4. Import master │
│   whitelist  │    │   start            │    │   rules + smoke  │
└──────────────┘    └────────────────────┘    └──────────────────┘
                                                       │
                                                       ▼
                                            ┌──────────────────┐
                                            │ 7. GitHub Actions │
                                            │   secret update   │
                                            └──────────────────┘
```

---

## Step 1 — DNS A record

Login ke registrar (Cloudflare / Niagahoster / dst), tambah record:

| Type | Name       | Value         | TTL  | Proxy |
|------|------------|---------------|------|-------|
| A    | kalender   | `NEW_VPS_IP`  | Auto | OFF (DNS only — supaya Let's Encrypt bisa) |

**Verifikasi propagasi** dari laptop:
```bash
dig +short kalender.safencare.work
# harus return: NEW_VPS_IP
```

⏱ Tunggu 2-5 menit. Cloudflare biasanya instan.

---

## Step 2 — Bootstrap VPS baru

SSH ke VPS baru dari laptop:
```bash
ssh root@NEW_VPS_IP
```

Jalankan setup script:
```bash
# Opsi A: one-liner dari GitHub (recommended)
curl -fsSL https://raw.githubusercontent.com/Przyval/snc-kelava-server/main/scripts/setup_new_vps.sh \
  | bash -s -- kalender.safencare.work

# Opsi B: clone manual dulu, run lokal
git clone https://github.com/Przyval/snc-kelava-server.git /root/kil-server
bash /root/kil-server/scripts/setup_new_vps.sh kalender.safencare.work
```

Script ini install: Python 3.10, PostgreSQL, Nginx, Certbot, firewall, clone repo, venv, .env, gunicorn, systemd, nginx bootstrap HTTP-only.

⏱ 5-10 menit.

---

## Step 3 — Migrasi database enterprise dari VPS lama

Dari laptop, kalau Anda masih bisa SSH ke VPS lama (104.194.154.108):
```bash
cd "/Users/michael/Downloads/Live SnC - Kelava Server"
bash scripts/migrate_enterprise_db.sh 104.194.154.108 NEW_VPS_IP
```

Kalau SSH lama putus (host key changed), pakai console provider:
1. Login ke Linode/provider console VPS lama
2. Run `pg_dump`:
   ```bash
   PGPASSWORD='KilEnt2026!' pg_dump -h 127.0.0.1 -U kil_ent kil_enterprise \
     --no-owner --no-acl --clean --if-exists > /tmp/enterprise_backup.sql
   ```
3. Download via `scp` ke laptop (kalau outbound SSH dari VPS lama masih jalan), atau copy-paste content via console.
4. Upload ke VPS baru:
   ```bash
   scp /Users/michael/Downloads/enterprise_backup.sql root@NEW_VPS_IP:/tmp/
   ssh root@NEW_VPS_IP \
     "PGPASSWORD='KilEnt2026!' psql -h 127.0.0.1 -U kil_ent kil_enterprise -f /tmp/enterprise_backup.sql"
   ```

**Verifikasi**: 87 users + master rules + draft batches harus ada.
```bash
ssh root@NEW_VPS_IP \
  "PGPASSWORD='KilEnt2026!' psql -h 127.0.0.1 -U kil_ent kil_enterprise -c \
   'SELECT COUNT(*) FROM enterprise_users; SELECT COUNT(*) FROM snc_recurring_rules;'"
```

---

## Step 4 — Apply migrations + import master rules

```bash
ssh root@NEW_VPS_IP
cd /root/kil-server/kil/db/migrations

# Apply semua migration (idempotent)
for f in $(ls *.sql | sort); do
    echo "→ $f"
    PGPASSWORD=KilEnt2026! psql -h 127.0.0.1 -U kil_ent -d kil_enterprise -f "$f" 2>&1 | tail -3
done

# Import master rules dari xlsx golden
cd /root/kil-server
.venv/bin/python -m kil.backend.scripts.import_master_rules_xlsx \
    "data/golden/Data Jadwal Client & Teknisi.xlsx"
```

---

## Step 5 — Start service + SSL

```bash
# Start Flask app via gunicorn
systemctl start kil-api
systemctl status kil-api --no-pager
# pastikan "Active: active (running)"

# Test internal: app respond di port 5002?
curl -s http://127.0.0.1:5002/api/v1/health

# Test HTTP via nginx (bootstrap config):
curl -s http://kalender.safencare.work/api/v1/health

# Setelah HTTP OK, enable SSL:
certbot --nginx -d kalender.safencare.work \
    --non-interactive --agree-tos -m admin@safencare.work

# Setelah cert ok, replace bootstrap config dengan production config
cd /root/kil-server
sed 's/safencare\.work/kalender.safencare.work/g' infra/nginx.conf \
    > /etc/nginx/sites-available/kil-api
ln -sf /etc/nginx/sites-available/kil-api /etc/nginx/sites-enabled/kil-api
rm /etc/nginx/sites-enabled/kil-api-bootstrap   # bersihkan bootstrap
nginx -t && systemctl reload nginx

# Test HTTPS:
curl -s https://kalender.safencare.work/api/v1/health
```

---

## Step 6 — Whitelist IP baru ke Kelava DB

Kontak `~Kamz` via WhatsApp, kirim pesan:

> Halo Kamz, ini Michael dari SanoCare. VPS kami migrasi ke IP baru:
> **NEW_VPS_IP**
>
> Mohon tambahkan ke pg_hba whitelist Kelava DB (port 5432, user `snc_read`).
> Yang lama (`104.194.154.108`) boleh di-remove juga.
>
> Terima kasih.

Sambil tunggu, test connectivity setelah whitelist:
```bash
ssh root@NEW_VPS_IP
PGPASSWORD='SnCR3aD2026&' psql -h 172.104.188.76 -U snc_read -d sanocare -c 'SELECT 1'
```

---

## Step 7 — GitHub Actions auto-deploy

### 7a. Generate SSH key baru di VPS
```bash
ssh root@NEW_VPS_IP
ssh-keygen -t ed25519 -f /root/.ssh/github_deploy -N ""
cat /root/.ssh/github_deploy.pub >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

# Print private key — paste ke GitHub
cat /root/.ssh/github_deploy
```

### 7b. Update GitHub Secrets
URL: https://github.com/Przyval/snc-kelava-server/settings/secrets/actions

Update/buat:
- `SSH_PRIVATE_KEY` ← paste isi private key dari step 7a
- `DEPLOY_HOST` ← `NEW_VPS_IP`
- `DEPLOY_DOMAIN` ← `kalender.safencare.work`

### 7c. Edit `.github/workflows/deploy.yml`

Ganti hardcoded value jadi secret. Saya sudah commit perubahan ini (lihat commit terbaru).

### 7d. Test deploy
Trigger manual:
```bash
gh workflow run deploy.yml
gh run watch
```

---

## Step 8 — Smoke test end-to-end

Dari browser:
1. https://kalender.safencare.work/enterprise/login → login `admin@sanocare.work` / `SanoCare2026!`
2. Buka **Calendar Draft** → generate Juli 2026 → verifikasi 28/28 master rules visible
3. Buka **Master Rules** → audit list rules
4. Download xlsx export → verifikasi CG Kaliasin punya 4 visit pagi+malam alternating

---

## Step 9 — Cutover (optional)

Kalau mau pensiun `safencare.work`:
- Update DNS `safencare.work` A record juga ke NEW_VPS_IP
- Tambah di nginx config: `server_name kalender.safencare.work safencare.work;`
- Re-run certbot dengan kedua domain
- Atau redirect `safencare.work` → `kalender.safencare.work`

---

## Rollback plan

Kalau ada masalah parah:
1. Stop service baru: `systemctl stop kil-api` di NEW_VPS
2. Revert DNS A record `kalender.safencare.work` ke IP lama (kalau VPS lama masih hidup)
3. Atau koordinator pakai xlsx manual sementara (operational continuity)

DB backup file (`enterprise_backup_*.sql`) di laptop adalah single source of truth — bisa restore ulang kalau perlu.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `502 Bad Gateway` | `systemctl status kil-api` — kemungkinan crash. Cek `journalctl -u kil-api -n 50` |
| Cert renewal fail | `certbot renew --dry-run` — biasanya DNS/firewall issue |
| Kelava DB connection refused | Tunggu whitelist propagasi (~5 menit setelah Kamz confirm) |
| Login admin gagal | Cek seed: `psql ... -c "SELECT email FROM enterprise_users"` — kalau kosong, run `seed_enterprise_users.py` |
| xlsx export berbeda dengan local | Master rules belum di-import, lihat Step 4 |

---

## Checklist final

- [ ] DNS A record kalender.safencare.work → NEW_VPS_IP, dig confirms
- [ ] `setup_new_vps.sh` selesai, no error
- [ ] Enterprise DB restored (87 users, rules, batches visible)
- [ ] All migrations applied
- [ ] Master rules imported (audit script: 12/13 multi-slot OK)
- [ ] systemd `kil-api.service` active
- [ ] HTTPS works (SSL cert valid)
- [ ] Kelava whitelist updated (psql test OK)
- [ ] GitHub Actions deploy success (manual trigger)
- [ ] Login admin via browser OK
- [ ] Generate calendar test OK, xlsx export OK
- [ ] Old VPS dimatikan / dipensiun (atau di-keep sebagai backup 1 minggu)
