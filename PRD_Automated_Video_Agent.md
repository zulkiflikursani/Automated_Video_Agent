# Product Requirement Document (PRD) — Automated Video Syndication Agent for Facebook
**Versi Document:** 1.1  
**Tanggal:** 13 September 2026  
**Status:** Approved / Technical Design  
**Target Platform:** Halaman Facebook (Facebook Page - Regular Video & Reels)  

---

## 1. Executive Summary & Core Objectives

### 1.1 Overview
Sistem **Automated Video Syndication Agent** adalah infrastruktur backend dan otomasi tingkat lanjut yang dirancang untuk memantau, mengunduh, memproses, serta mengunggah konten video drama Cina berdubbing Indonesia ke Halaman Facebook secara mandiri tanpa intervensi manual harian.

Sistem ini memproses 1 video sumber berdurasi panjang menjadi **2 format output utama**:
1. **Full-Length Video (16:9)** — Diunggah ke feed video Halaman Facebook.
2. **Reels Clips (9:16)** — Dipotong menjadi beberapa episode pendek (30–60 detik) dengan format vertikal, dilengkapi *overlay text* interaktif dan penomoran *part* otomatis.

### 1.2 Key Performance Indicators (KPIs)
* **100% Fully Automated Pipeline:** Berjalan secara terjadwal (*cron/task queue*).
* **Dual-Format Delivery:** Memproduksi 1 video *full* dan 3–5 klip *Reels* dari setiap 1 video sumber.
* **Storage Optimization:** Pembersihan otomatis file media lokal pasca-unggah berhasil (*zero disk bloat*).
* **High Availability & Alerting:** Monitoring real-time via Web Dashboard dan notifikasi insiden langsung ke Telegram Bot.

---

## 2. Architecture & Data Flow

```
                                  ┌──► [ Process 16:9 Full Video ] ──► [ FB Video API ] ──┐
[ Target Source ] ──► [ yt-dlp ] ─┼                                                        ├──► [ Database & Telegram Logs ]
                                  └──► [ Reels Clip Generator ]  ──► [ FB Reels API ] ──┘
                                                 │
                                                 ▼
                                     [ Web Control Dashboard ]
```

---

## 3. Detailed Database Schema Design (PostgreSQL / Supabase / SQLite)

### 3.1 Tabel `sources` (Daftar Channel / Playlist Target)
Mengelola daftar URL sumber yang dipantau oleh *ingestion agent*.

```sql
CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL UNIQUE,
    platform VARCHAR(50) DEFAULT 'youtube', -- youtube, douyin, tiktok, etc.
    is_active BOOLEAN DEFAULT TRUE,
    check_interval_hours INT DEFAULT 6,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.2 Tabel `videos` (Registry Media & Status Pipeline)
Mencatat seluruh data video yang telah terdeteksi, diunduh, dan diproses untuk mencegah duplikasi.

```sql
CREATE TABLE videos (
    id SERIAL PRIMARY KEY,
    source_id INT REFERENCES sources(id) ON DELETE SET NULL,
    source_video_id VARCHAR(255) UNIQUE NOT NULL, -- Unique ID dari platform asal
    title VARCHAR(500) NOT NULL,
    description TEXT,
    duration INT, -- Durasi dalam detik
    original_url TEXT NOT NULL,
    local_raw_path TEXT,
    status VARCHAR(50) DEFAULT 'PENDING', -- PENDING, DOWNLOADING, PROCESSING, READY, PUBLISHED, FAILED
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 Tabel `clips` (Daftar Klip Reels Vertikal)
Menyimpan segmen-segmen potongan video pendek (9:16) hasil ekstraksi dari video utama.

```sql
CREATE TABLE clips (
    id SERIAL PRIMARY KEY,
    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
    part_number INT NOT NULL,
    start_time_sec INT NOT NULL,
    end_time_sec INT NOT NULL,
    duration INT NOT NULL,
    local_clip_path TEXT,
    overlay_title VARCHAR(255),
    status VARCHAR(50) DEFAULT 'PENDING', -- PENDING, PROCESSING, READY, PUBLISHED, FAILED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.4 Tabel `publishing_queue` (Antrean Jadwal Unggah ke Facebook)
Mengatur jadwal eksekusi unggah (*drip feeding*) agar tidak memicu deteksi spam Facebook.

```sql
CREATE TABLE publishing_queue (
    id SERIAL PRIMARY KEY,
    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
    clip_id INT REFERENCES clips(id) ON DELETE CASCADE, -- NULL jika postingan video full
    post_type VARCHAR(20) NOT NULL, -- 'REGULAR_VIDEO' atau 'REELS'
    scheduled_for TIMESTAMP WITH TIME ZONE NOT NULL,
    fb_post_id VARCHAR(255),
    status VARCHAR(50) DEFAULT 'QUEUED', -- QUEUED, UPLOADING, SUCCESS, FAILED
    retry_count INT DEFAULT 0,
    logs TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.5 Tabel `system_settings` (Konfigurasi Dynamic Agent)
Penyimpanan kredensial API, preferensi FFmpeg, watermark, dan parameter otomatisasi.

```sql
CREATE TABLE system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Module Specifications & Implementation Scripts

### 4.1 Modul Ingestion: Script `yt-dlp` Downloader (Python)

```python
import os
import sqlite3
import yt_dlp

DB_PATH = "system.db"

def download_video(video_url, output_dir="downloads"):
    os.makedirs(output_dir, exist_ok=True)
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
        'quiet': False,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        filename = ydl.prepare_filename(info)
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "duration": info.get("duration"),
            "file_path": filename
        }

if __name__ == "__main__":
    url = "https://www.youtube.com/watch?example"
    print("Ingestion script ready.")
```

---

### 4.2 Modul Processing: Pipeline FFmpeg Dual-Format (Python + FFmpeg)

Script ini melakukan 2 tugas:
1. **Full Video (16:9):** Penyesuaian kecerahan ringan, watermark logo, dan modifikasi audio pitch/speed.
2. **Reels Clips (9:16):** Auto-crop center 9:16 dengan background blur dan overlay teks judul + nomor part.

```python
import subprocess
import os

def process_full_video(input_path, output_path, watermark_text="Drachin Indo"):
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"eq=brightness=0.03:contrast=1.03,drawtext=text='{watermark_text}':x=w-tw-20:y=20:fontsize=24:fontcolor=white@0.8",
        "-filter:a", "atempo=1.02,asetrate=44100*1.01",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", output_path
    ]
    subprocess.run(cmd, check=True)

def generate_reels_clip(input_path, output_path, start_sec, duration_sec, part_num, title_text):
    filter_complex = (
        f"[0:v]trim=start={start_sec}:duration={duration_sec},setpts=PTS-STARTPTS,split[v1][v2];"
        f"[v1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];"
        f"[v2]scale=1080:-1,crop=1080:min(ih\,1080)[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]drawtext=text='{title_text}':x=(w-text_w)/2:y=180:fontsize=38:fontcolor=yellow:box=1:boxcolor=black@0.6,"
        f"drawtext=text='PART {part_num}':x=(w-text_w)/2:y=h-250:fontsize=48:fontcolor=white:box=1:boxcolor=red@0.8[outv];"
        f"[0:a]atrim=start={start_sec}:duration={duration_sec},asetpts=PTS-STARTPTS[outa]"
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", output_path
    ]
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    print("FFmpeg Processing Pipeline ready.")
```

---

### 4.3 Modul Publishing: Facebook Graph API Uploader (Python)

```python
import requests
import os

def upload_full_video(page_id, page_access_token, video_path, title, description):
    url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos"
    payload = {
        'title': title,
        'description': description,
        'access_token': page_access_token
    }
    with open(video_path, 'rb') as video_file:
        files = {'source': video_file}
        response = requests.post(url, data=payload, files=files)
    return response.json()

def upload_reels_video(page_id, page_access_token, video_path, caption):
    init_url = f"https://graph.facebook.com/v19.0/{page_id}/video_reels"
    init_payload = {
        'upload_phase': 'start',
        'access_token': page_access_token
    }
    init_res = requests.post(init_url, data=init_payload).json()
    video_id = init_res.get('video_id')
    upload_url = init_res.get('upload_url')

    file_size = os.path.getsize(video_path)
    headers = {
        'Authorization': f'OAuth {page_access_token}',
        'offset': '0',
        'file_size': str(file_size)
    }
    with open(video_path, 'rb') as f:
        requests.post(upload_url, headers=headers, data=f)

    finish_payload = {
        'upload_phase': 'finish',
        'video_id': video_id,
        'video_state': 'PUBLISHED',
        'description': caption,
        'access_token': page_access_token
    }
    finish_res = requests.post(init_url, data=finish_payload).json()
    return finish_res

if __name__ == "__main__":
    print("Facebook API Publisher Engine ready.")
```

---

## 5. Web Dashboard Interface Specification

Dashboard berbasis web dikembangkan menggunakan **Next.js / Bootstrap 5 / Tailwind CSS** untuk mengontrol seluruh fungsionalitas sistem backend.

### 5.1 Dashboard UI Wireframe Layout

```
+-----------------------------------------------------------------------------------+
|  [LOGO] FB Video Auto-Agent                 Status: [ ACTIVE ]  [ Run Cron Now ]  |
+-------------------+---------------------------------------------------------------+
| NAVIGATION        | METRICS OVERVIEW                                              |
| - Overview        | [ Total Videos: 124 ] [ Reels Cut: 486 ] [ Success Rate: 98%]|
| - Source Manager  +---------------------------------------------------------------+
| - Publishing Queue| PUBLISHING QUEUE (Drip Feed Schedule)                         |
| - Reels Clips     | ID | Title                 | Type   | Scheduled For | Action   |
| - Logs & Alerts   | 01 | CEO jatuh cinta ep 1 | Video  | 14:00 Today   | [Cancel] |
| - System Settings | 02 | Part 1 - CEO marah    | Reels  | 16:30 Today   | [Publish]|
|                   | 03 | Part 2 - Akibat fatal | Reels  | 19:00 Today   | [Delete] |
|                   +---------------------------------------------------------------+
|                   | RECENT LOGS & TELEGRAM ALERTS                                 |
|                   | [14:02:11] [SUCCESS] Uploaded Reels Clip #45 to FB Page.      |
|                   | [11:15:00] [WARN] Source YouTube delay response. Retrying...  |
+-------------------+---------------------------------------------------------------+
```

### 5.2 Dashboard Key Features
* **Source Management Panel:** Form CRUD untuk memasukkan playlist URL YouTube/TikTok target.
* **Interactive Queue Override:** Opsi memajukan atau menunda jam tayang postingan secara manual.
* **Manual Video Clipper:** Fitur preview video langsung di web dashboard jika admin ingin memotong klip Reels di titik waktu tertentu secara manual.
* **Resource Cleanup Trigger:** Tombol manual pemicu penghapusan file *temp* dan *cache* server.

---

## 6. Risk Mitigation & Security Policies

| Risks | Severity | Automated Mitigation Strategy |
| :--- | :--- | :--- |
| **Copyright Takedown** | High | Eksekusi transformasi FFmpeg (brightness offset + pitch shift + frame cropping + overlay border). |
| **Rate Limit / API Block** | Medium | *Drip feeding scheduler* membatasi maksimum 2 Video Full & 4 Reels per 24 jam. |
| **Facebook Token Expiry** | Medium | Bot Telegram mengirimkan alert 5 hari sebelum *Long-Lived Access Token* kedaluwarsa. |
| **Server Disk Full** | High | Modul pembersih (*Garbage Collector*) otomatis mengeksekusi `os.remove()` pada file lokal tepat setelah status DB berubah menjadi `SUCCESS`. |

---
