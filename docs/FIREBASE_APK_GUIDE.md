# Firebase Setup & APK Build Guide

Panduan ini mencakup setup Firebase (push notification) dan cara build APK untuk distribusi ke teknisi.

---

## Part 1 — Firebase Project Setup

### 1. Buat Firebase Project

1. Buka [console.firebase.google.com](https://console.firebase.google.com)
2. Klik **Add project** → Nama: `SanoCare SNC`
3. Disable Google Analytics (tidak dibutuhkan)
4. Klik **Create project**

### 2. Tambah Android App

1. Di Firebase console, klik ikon Android
2. **Android package name**: `com.sanocare.snc`
   - Pastikan ini sesuai dengan `applicationId` di `android/app/build.gradle`
3. **App nickname**: `SNC Teknisi`
4. Klik **Register app**
5. Download `google-services.json`
6. Taruh di `mobile/android/app/google-services.json`

### 3. Verifikasi android/app/build.gradle

Pastikan ada:
```gradle
android {
    defaultConfig {
        applicationId "com.sanocare.snc"   // ← harus sama dengan Firebase
        minSdkVersion 21
        targetSdkVersion 34
    }
}

dependencies {
    implementation platform('com.google.firebase:firebase-bom:33.0.0')
    implementation 'com.google.firebase:firebase-messaging'
}
```

### 4. Verifikasi android/build.gradle (project level)

```gradle
buildscript {
    dependencies {
        classpath 'com.google.gms:google-services:4.4.1'
    }
}
```

### 5. Verifikasi android/app/build.gradle (app level, bawah)

```gradle
apply plugin: 'com.google.gms.google-services'
```

### 6. Ambil FCM Server Key

1. Firebase console → Project Settings → **Cloud Messaging** tab
2. Copy **Server key** (bukan Web Push certificate)
3. Tambahkan ke `.env` di server:
   ```
   FCM_SERVER_KEY=AAAAxxxxxxx...
   ```
4. Restart service:
   ```bash
   ssh root@104.194.154.108 'systemctl restart kil-api'
   ```

---

## Part 2 — Build APK

### Prerequisites

```bash
# Install Flutter SDK (jika belum)
# https://docs.flutter.dev/get-started/install

# Verify setup
flutter doctor

# Install dependencies
cd mobile
flutter pub get
```

### Build APK (Release)

```bash
cd mobile

# Debug build — untuk testing
flutter build apk --debug

# Release build — untuk distribusi
flutter build apk --release

# APK tersimpan di:
# build/app/outputs/flutter-apk/app-release.apk
```

### Build App Bundle (untuk Play Store)

```bash
flutter build appbundle --release
# Output: build/app/outputs/bundle/release/app-release.aab
```

### Build APK per-ABI (lebih kecil file size)

```bash
flutter build apk --split-per-abi --release
# Menghasilkan:
# app-armeabi-v7a-release.apk  (32-bit, HP lama)
# app-arm64-v8a-release.apk    (64-bit, HP modern — gunakan ini)
# app-x86_64-release.apk       (emulator)
```

**Rekomendasi**: distribusikan `app-arm64-v8a-release.apk` untuk HP Android modern (2018+).

---

## Part 3 — Distribusi ke Teknisi

### Opsi A: WhatsApp / Direct Share

1. Build APK release
2. Share file `app-release.apk` via WhatsApp / Google Drive
3. Teknisi install manual:
   - Settings → Security → Enable "Unknown sources" / "Install unknown apps"
   - Buka file APK dan install

### Opsi B: Firebase App Distribution (Recommended)

1. Firebase console → **App Distribution**
2. Upload APK
3. Tambahkan email teknisi sebagai tester
4. Teknisi dapat link download via email

### Opsi C: Internal Track (Play Store)

Untuk masa depan — jika ingin push update otomatis.

---

## Part 4 — Update Credentials Teknisi

Setelah APK terpasang, teknisi login dengan:

| Field    | Value                                   |
|----------|-----------------------------------------|
| URL      | (otomatis ke `safencare.work`)          |
| Email    | `[nama]@sanocare.work` atau email terdaftar |
| Password | `SanoCare` + 4 digit terakhir ID (contoh: ID 392 → `SanoCare0392`) |

Admin bisa reset password via endpoint:
```
PUT /api/v1/enterprise/users/{id}/password
Body: { "new_password": "..." }
```

---

## Part 5 — Test Push Notification

Setelah FCM_SERVER_KEY diset dan APK terpasang:

1. Login di app → FCM token otomatis terkirim ke server
2. Test dari server:
   ```bash
   curl -X POST https://safencare.work/api/v1/enterprise/scheduling/road-plans \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "p_user_id": 392,
       "customer_id": 1234,
       "visit_date": "2026-04-15T09:00:00+07:00",
       "title": "Test notif"
     }'
   ```
3. HP teknisi seharusnya menerima notifikasi "Jadwal Baru"

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `google-services.json` not found | Pastikan file ada di `android/app/`, bukan di root |
| Build error: `minSdkVersion` | Set `minSdkVersion 21` di `android/app/build.gradle` |
| FCM token tidak terkirim | Cek Firebase project terdaftar, `google-services.json` sesuai package name |
| Notif tidak muncul | Cek `FCM_SERVER_KEY` di `.env` server, restart kil-api |
| App crash saat buka | Run `flutter run --debug` untuk lihat error log |
