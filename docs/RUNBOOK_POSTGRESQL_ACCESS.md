# 🔐 Runbook: PostgreSQL SanoCare Access via VPS Tunnel

> **Last Updated:** 2026-01-10
> **Status:** ✅ VERIFIED WORKING

---

## 📋 Informasi Koneksi

| Parameter | Value |
|-----------|-------|
| **DB Host** | `app.kelava.id` |
| **DB Port** | `5432` |
| **Database** | `sanocare` |
| **User** | `snc_read` (read-only) |
| **VPS IP** | `104.194.154.108` |
| **VPS User** | `root` |

---

## A) Checklist Diagnostik Cepat (5 menit)

### 1. Cek IP Publik (dari Mac)
```bash
curl -s ifconfig.me ; echo
```

### 2. Cek IP Publik VPS
```bash
ssh root@104.194.154.108 "curl -s ifconfig.me ; echo"
```
> Expected: `104.194.154.108` atau IPv6 `2602:fa59:7:259::1`

### 3. Test DNS Resolution
```bash
ssh root@104.194.154.108 "host app.kelava.id"
```
> Expected: `app.kelava.id has address 172.104.188.76`

### 4. Test Port Connectivity
```bash
ssh root@104.194.154.108 "nc -vz app.kelava.id 5432"
```
> Expected: `Connection to app.kelava.id 5432 port [tcp/postgresql] succeeded!`

---

## B) Command Koneksi yang Benar

### Opsi 1: Via SSH ke VPS (Langsung)
```bash
# Interaktif (masuk ke psql shell)
ssh root@104.194.154.108 "psql 'host=app.kelava.id port=5432 dbname=sanocare user=snc_read sslmode=require'"

# Non-interaktif (jalankan query)
ssh root@104.194.154.108 "psql 'host=app.kelava.id port=5432 dbname=sanocare user=snc_read sslmode=require' -c 'SELECT now();'"
```

### Opsi 2: Via SSH Tunnel (Recommended untuk DBeaver)
```bash
# Terminal 1: Buat tunnel (biarkan running)
ssh -N -L 5433:app.kelava.id:5432 root@104.194.154.108

# Terminal 2: Konek via localhost
psql "host=localhost port=5433 dbname=sanocare user=snc_read sslmode=require"
```

### Opsi 3: SSH Tunnel Background Mode
```bash
# Start tunnel di background
ssh -f -N -L 5433:app.kelava.id:5432 root@104.194.154.108

# Cek tunnel berjalan
lsof -i :5433

# Kill tunnel kalau mau stop
pkill -f "ssh -f -N -L 5433"
```

---

## C) Troubleshooting Matrix

### Case 1: `FATAL: no pg_hba.conf entry for host "x.x.x.x"`

| Item | Detail |
|------|--------|
| **Gejala** | Error menyebut IP yang tidak dikenal |
| **Penyebab** | IP belum di-whitelist di server |
| **Fix Client** | Pastikan konek via VPS, bukan langsung |
| **Info ke Admin** | Minta whitelist IP: `104.194.154.108/32` |

### Case 2: `password authentication failed for user "snc_read"`

| Item | Detail |
|------|--------|
| **Gejala** | Password ditolak |
| **Penyebab** | Password salah atau user tidak ada |
| **Fix Client** | Cek `.pgpass` atau input ulang |
| **Info ke Admin** | Konfirmasi credential valid |

### Case 3: `connection timed out` / `connection refused`

| Item | Detail |
|------|--------|
| **Gejala** | Tidak ada response atau refused |
| **Penyebab** | Firewall block, server down, port salah |
| **Fix Client** | Test dengan `nc -vz app.kelava.id 5432` |
| **Info ke Admin** | Cek status server dan firewall |

### Case 4: `SSL connection error` / `certificate verify failed`

| Item | Detail |
|------|--------|
| **Gejala** | SSL handshake gagal |
| **Penyebab** | Certificate issue atau SSL config |
| **Fix Client** | Coba `sslmode=require` (bukan verify-full) |
| **Info ke Admin** | Konfirmasi SSL setup di server |

---

## D) Template Pesan ke Admin (Kamz)

### Template 1: Whitelist IP Saat Ini
```
Halo Kamz,

Mohon whitelist IP berikut untuk akses PostgreSQL:

- IP: 104.194.154.108/32 (VPS Singapore)
- Database: sanocare
- User: snc_read
- Protocol: SSL (hostssl)

Terima kasih.
```

### Template 2: Request Perubahan IP
```
Halo Kamz,

Mohon update whitelist PostgreSQL:

- Hapus IP lama: [IP_LAMA]/32
- Tambah IP baru: [IP_BARU]/32
- Database: sanocare
- User: snc_read

Terima kasih.
```

### Template 3: Request Solusi Proper (Bastion/VPN)
```
Halo Kamz,

Untuk keamanan dan kemudahan akses jangka panjang, apakah memungkinkan setup salah satu dari:

1. Bastion/Jump host dengan SSH key authentication
2. VPN access ke internal network
3. IP range whitelist untuk VPS static IP

Saat ini saya menggunakan VPS dengan IP statis 104.194.154.108 sebagai jump host.

Mohon advisnya.

Terima kasih.
```

---

## E) Setup IP Stabil: VPS + SSH Tunnel ✅

### Status Saat Ini
- [x] VPS aktif: `104.194.154.108` (Cloudzy Singapore)
- [x] SSH key configured
- [x] PostgreSQL client installed
- [x] `.pgpass` configured (password aman)
- [x] Koneksi tested: **WORKING**

### Cara Pakai Sehari-hari

#### Quick Connect (1 command)
```bash
ssh root@104.194.154.108 "psql 'host=app.kelava.id dbname=sanocare user=snc_read sslmode=require'"
```

#### DBeaver / GUI Client Setup
1. Buka terminal, jalankan tunnel:
   ```bash
   ssh -N -L 5433:app.kelava.id:5432 root@104.194.154.108
   ```
2. Di DBeaver, buat koneksi baru:
   - Host: `localhost`
   - Port: `5433`
   - Database: `sanocare`
   - User: `snc_read`
   - Password: (masukkan password)
   - SSL: Enable

#### Auto-reconnect Tunnel (Optional)
```bash
# Install autossh (Mac)
brew install autossh

# Jalankan tunnel yang auto-reconnect
autossh -M 0 -f -N -L 5433:app.kelava.id:5432 root@104.194.154.108
```

---

## F) Credential Storage Aman

### Di VPS (Sudah Configured ✅)
```bash
# File: ~/.pgpass (chmod 600)
# Format: hostname:port:database:username:password
app.kelava.id:5432:sanocare:snc_read:********
```

### Di Mac (Untuk Tunnel Mode)
```bash
# Buat file
echo "localhost:5433:sanocare:snc_read:YOUR_PASSWORD" >> ~/.pgpass
chmod 600 ~/.pgpass
```

### DBeaver
- Simpan password di connection profile
- Jangan screenshot/share connection settings
- Gunakan master password DBeaver jika tersedia

---

## 🧪 Quick Test Command

```bash
# Test dari Mac via VPS (copy-paste langsung)
ssh root@104.194.154.108 "psql 'host=app.kelava.id dbname=sanocare user=snc_read sslmode=require' -c 'SELECT now();'"
```

Expected output:
```
              now              
-------------------------------
 2026-01-10 16:20:49.337008+07
(1 row)
```

---

## 📝 Catatan Penting

1. **Jangan share password** di chat/screenshot
2. **VPS tetap hidup** untuk akses stabil
3. **Backup credential** di password manager
4. **Monitor usage** - ini akun read-only, jangan coba write
