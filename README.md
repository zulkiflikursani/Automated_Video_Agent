# Automated_Video_Agent

**Automated Video Syndication Agent for Facebook** — memantau, mengunduh, memproses, dan mengunggah video drama Cina berdubbing Indonesia ke Halaman Facebook secara 100% otomatis (PRD v1.1).

## Fitur

- **Dual-format delivery**: 1 video full 16:9 + 3–5 klip Reels 9:16 per video sumber
- **Transformasi FFmpeg**: brightness/contrast, watermark, pitch shift (full) • background blur + overlay judul & "PART n" (Reels)
- **Drip-feed scheduler**: maksimum 2 video full + 4 Reels per 24 jam (anti rate-limit FB)
- **Garbage collector**: file lokal dihapus otomatis setelah unggah sukses (zero disk bloat)
- **Web Dashboard**: metrics, source manager, queue override, logs, settings
- **Telegram alerts**: insiden pipeline + pengingat token FB H-5
- **Dry-run mode default**: seluruh pipeline dapat diuji tanpa menyentuh Facebook

## Arsitektur

```
                                  ┌──► [ Process 16:9 Full Video ] ──► [ FB Video API ] ──┐
[ Target Source ] ──► [ yt-dlp ] ─┼                                                        ├──► [ Database & Telegram Logs ]
                                  └──► [ Reels Clip Generator ]  ──► [ FB Reels API ] ──┘
                                                 │
                                                 ▼
                                     [ Web Control Dashboard ]
```

## Struktur Project

```
backend/
  config.py          # konfigurasi (env -> .env -> default)
  db.py              # engine SQLite + SQLAlchemy, FK pragma
  models.py          # 5 tabel PRD: sources, videos, clips, publishing_queue, system_settings
  agent.py           # orchestrator: pipeline, publishing (drip feed), GC
  main.py            # entrypoint APScheduler (--run-once / long-running)
  api.py             # FastAPI REST API untuk dashboard
  settings.py        # seed system_settings
  modules/
    ingestion.py     # yt-dlp: list_source_videos, download_video
    processor.py     # FFmpeg dual-format (overlay PNG via Pillow)
    clip_planner.py  # pembagi 3–5 klip x 30–60 detik
    publisher.py     # FB Graph API (full video + Reels 3-phase) + dry-run
    alerter.py       # Telegram alerts + token expiry watch
  jobs/
    scan_sources.py  # deteksi video baru per interval source
dashboard/           # Next.js 14 + Tailwind (PRD 5.1 wireframe)
tests/               # pytest: unit + integrasi + E2E (real FFmpeg)
```

## Setup

### Prasyarat
- Python 3.9+, Node 18+, FFmpeg (`brew install ffmpeg` / `apt install ffmpeg`)

### Backend
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # isi kredensial bila sudah siap
```

### Dashboard
```bash
cd dashboard && npm install
```

## Menjalankan

```bash
# 1. Satu siklus manual (scan -> pipeline -> publish dry-run -> GC)
.venv/bin/python -m backend.main --run-once

# 2. Agent 24/7 (scheduler: scan tiap 6 jam, publish tick tiap 15 menit)
.venv/bin/python -m backend.main

# 3. API server (dashboard backend)
.venv/bin/uvicorn backend.api:app --port 8000

# 4. Dashboard
cd dashboard && npm run dev    # http://localhost:3000
```

## Konfigurasi Utama (`.env`)

| Variabel | Default | Keterangan |
|---|---|---|
| `DRY_RUN` | `true` | `false` = benar-benar unggah ke Facebook |
| `FB_PAGE_ID` / `FB_PAGE_ACCESS_TOKEN` | – | Kredensial Page (long-lived token) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | – | Notifikasi insiden |
| `DRIP_FEED_FULL_PER_DAY` | `2` | Batas video full / 24 jam |
| `DRIP_FEED_REELS_PER_DAY` | `4` | Batas Reels / 24 jam |
| `WATERMARK_TEXT` | `Drachin Indo` | Watermark video full |

Kredensial juga dapat diubah runtime lewat dashboard → Settings (tersimpan di `system_settings`).

## Mode Live (Go-Live)

1. Isi `FB_PAGE_ID` + `FB_PAGE_ACCESS_TOKEN` (long-lived Page token) di `.env` atau dashboard
2. Set `DRY_RUN=false`
3. (Opsional) isi `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` untuk alert
4. Restart agent — publish worker mulai mengirim ke Facebook sesuai drip-feed

## Testing

```bash
.venv/bin/python -m pytest tests/ -q     # 39 test: DB, ingestion, FFmpeg, publisher, E2E, API
cd dashboard && npx next build           # verifikasi dashboard
```

## Deployment (single VPS + systemd)

```ini
# /etc/systemd/system/ava-agent.service
[Service]
WorkingDirectory=/opt/Automated_Video_Agent
ExecStart=/opt/Automated_Video_Agent/.venv/bin/python -m backend.main
Restart=always

# /etc/systemd/system/ava-api.service
[Service]
WorkingDirectory=/opt/Automated_Video_Agent
ExecStart=/opt/Automated_Video_Agent/.venv/bin/uvicorn backend.api:app --port 8000
Restart=always
```

Dashboard production: `cd dashboard && npm run build && npm start` (atau serve via nginx reverse proxy ke :3000/:8000).

## Catatan Kepatuhan

Sistem dirancang sesuai PRD §6 (transformasi konten, drip feeding, pembersihan media). Pengguna bertanggung jawab memastikan hak atas konten sumber sebelum publikasi.
