# Panduan Setup Token Facebook (Publish-Ready)

Target Page: **Drama Favorit** (`1355392760983997`) · App: **My Automasion**

Token yang aktif saat ini adalah **user token** dengan scope read-only
(`pages_show_list`, `pages_read_engagement`) — **belum bisa mengunggah**, dan
kedaluwarsa beberapa jam setelah dibuat. Ikuti langkah berikut untuk menghasilkan
token publish yang tahan lama.

---

## Langkah 1 — Tambah permission `pages_manage_posts`

1. Buka <https://developers.facebook.com/app/1505378338275711/app-review/permissions/> (App: My Automasion)
2. Cari dan tambahkan **`pages_manage_posts`**
3. Karena app milik sendiri (role: Admin/Developer/Tester), permission ini
   langsung aktif untuk akunmu sendiri **tanpa App Review** — pastikan akunmu
   terdaftar di **App Roles > Roles**.
4. (Opsional, untuk mengelola live video) tambahkan juga `pages_manage_engagement`.

## Langkah 2 — Generate user token BARU dengan permission lengkap

1. Buka **Graph API Explorer**: <https://developers.facebook.com/tools/explorer/>
2. Pilih **My Automasion** di dropdown aplikasi
3. **User Token** > dropdown **Permissions** > centang:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`   ← kunci untuk upload
4. Klik **Generate Access Token** > login > **Allow semua**
5. Salin token (berlaku ±1 jam — cukup untuk langkah 3)

## Langkah 3 — Tukar ke long-lived user token (±60 hari)

Jalankan di terminal:

```bash
curl -s "https://graph.facebook.com/v19.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=1505378338275711&\
client_secret=APP_SECRET_KAMU&\
fb_exchange_token=TOKEN_DARI_LANGKAH_2"
```

> `APP_SECRET_KAMU`: <https://developers.facebook.com/app/1505378338275711/settings/basic/> → App secret.
> (Perlu klik "Show".)

Respons JSON berisi `access_token` baru — ini **long-lived user token (±60 hari)**.

## Langkah 4 — Tukar ke **Page access token** (tidak kedaluwarsa)

```bash
curl -s "https://graph.facebook.com/v19.0/me/accounts?\
access_token=TOKEN_LONG_LIVED_LANGKAH_3"
```

Cari entri `"name": "Drama Favorit"` dan salin `access_token` di dalamnya.
Page token yang dibuat dari long-lived user token **tidak punya tanggal
kedaluwarsa** — inilah token yang dipakai sistem.

Verifikasi tipe & izinnya:

```bash
curl -s "https://graph.facebook.com/debug_token?\
input_token=TOKEN_PAGE_BARU&\
access_token=TOKEN_PAGE_BARU" | python3 -m json.tool
```

Yang harus terpenuhi:
- `"type": "PAGE"` (bukan USER)
- `"is_valid": true`
- `"expires_at": 0` (berarti permanen)
- profile atasan punya scope `pages_manage_posts`

## Langkah 5 — Pasang ke sistem

1. Ganti nilai `FB_PAGE_ACCESS_TOKEN` di file `.env` dengan token Page baru
2. (Opsional, untuk alert H-5) catat kedaluwarsa di dashboard:
   Settings → `fb_token_expires_at` → isi tanggal ISO, mis. `2026-11-12T00:00:00+00:00`
3. Set `DRY_RUN=false` di `.env`
4. Uji publish uji:

```bash
.venv/bin/python -m pytest tests/test_publisher.py -q   # logic test tetap hijau
# uji publish 1 entri dari dashboard: Queue → Publish
```

---

## Ringkasan rantai token

```
User token (1 jam, Graph API Explorer, +pages_manage_posts)
   └─ exchange → Long-lived user token (60 hari, butuh App Secret)
         └─ /me/accounts → Page token Drama Favorit (PERMANEN) ← pasang di .env
```

## Checklist masalah umum

| Gejala | Penyebab | Solusi |
|---|---|---|
| `(#200) Requires pages_manage_posts` | Permission belum di-grant | Ulangi Langkah 1–2, pastikan dicentang |
| `Error validating access token... expired` | Token 1-jam dipakai langsung | Lanjutkan Langkah 3–4 (exchange) |
| `type: USER` padahal pakai token /me/accounts | User token belum di-exchange dulu | Selesaikan Langkah 3 sebelum Langkah 4 |
| Page tidak muncul di `/me/accounts` | Bukan admin Page / role app kurang | Tambahkan akun di App Roles, dan pastikan admin Page "Drama Favorit" |
| Upload gagal di tengah | Video > 1GB / > 60 menit | Publisher full memakai endpoint non-resumable; klip Reels 30–60s aman |
