# ⚡ YouTube Video & Shorts Downloader + REST API

A high-performance YouTube Videos & YouTube Shorts downloader with a clean Web UI and a fully documented REST API. Built with Python, Flask, `yt-dlp`, and FFmpeg.

---

## 🚀 Features
- **YouTube Shorts & Videos:** Automatic detection of Shorts and regular videos.
- **Multiple Qualities:** 1080p Full HD, 720p HD, 480p, 360p, Best Available (MP4).
- **Audio Extraction:** High-quality MP3 (320 kbps, 192 kbps, 128 kbps) or M4A.
- **Real-Time Progress:** Percent, download speed (MB/s), and ETA tracking.
- **CORS Enabled REST API:** Ready for integrations into Python, Node.js, PHP, or mobile apps.
- **1-Click Quick Download Endpoint:** Direct stream download for terminal/curl.

---

## 🏃 Quick Start

### 1. Web Dashboard
Double click `start.bat` or run:
```bash
py app.py
```
Open in browser: **`http://localhost:5055`**

### 2. Live Public Link (Mobile & Remote Access)
Double click `start_live.bat` to launch with Cloudflare Tunnel.

---

## 📡 REST API Reference

Base URL: `http://localhost:5055`

### 1. Main Video API (Direct JSON Response)
```http
GET /api?url=https://www.youtube.com/watch?v=7SlptRQ_kPU
```
**Response:**
```json
{
  "status": "success",
  "id": "7SlptRQ_kPU",
  "title": "Avengers: Doomsday | Final Trailer | In Cinemas December 17",
  "channel": "IndiaMarvel",
  "duration": 195,
  "duration_str": "03:15",
  "thumbnail": "https://i.ytimg.com/vi/7SlptRQ_kPU/maxresdefault.jpg",
  "view_count": 2159616,
  "views_formatted": "2.16M",
  "is_short": false,
  "downloads": {
    "video": [
      {
        "quality": "1080p",
        "label": "Full HD (1080p)",
        "format": "mp4",
        "download_url": "http://localhost:5055/api/quick-download?url=...&quality=1080p&type=video"
      },
      {
        "quality": "720p",
        "label": "HD (720p)",
        "format": "mp4",
        "download_url": "http://localhost:5055/api/quick-download?url=...&quality=720p&type=video"
      }
    ],
    "audio": [
      {
        "quality": "320",
        "label": "MP3 High Quality (320 kbps)",
        "format": "mp3",
        "download_url": "http://localhost:5055/api/quick-download?url=...&quality=320&type=audio"
      }
    ]
  }
}
```

---

### 2. Health Check
```http
GET /api/health
```
**Response:**
```json
{
  "status": "online",
  "ffmpeg_available": true,
  "service": "YouTube & Shorts Downloader API",
  "yt_dlp_version": "2026.11.23"
}
```

---

### 2. Inspect Video / Get Formats
```http
POST /api/info
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=..."
}
```
**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "4Vz6L8B73i4",
    "title": "...",
    "duration_str": "02:55:06",
    "channel": "Raj Shamani",
    "thumbnail": "https://...",
    "is_short": false,
    "video_options": [
      { "quality": "best", "label": "Best Available (1080p)", "format": "mp4" },
      { "quality": "1080p", "label": "Full HD (1080p)", "format": "mp4" },
      { "quality": "720p", "label": "HD (720p)", "format": "mp4" }
    ],
    "audio_options": [
      { "quality": "320", "label": "MP3 High Quality (320 kbps)", "format": "mp3" }
    ]
  }
}
```

---

### 3. Start Asynchronous Download
```http
POST /api/download
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=...",
  "type": "video",
  "quality": "720p"
}
```
**Response:**
```json
{
  "status": "queued",
  "job_id": "job_a1b2c3d4",
  "check_progress_url": "/api/progress/job_a1b2c3d4"
}
```

---

### 4. Check Download Progress
```http
GET /api/progress/<job_id>
```
**Response:**
```json
{
  "status": "downloading",
  "percent": 68.4,
  "speed": "4.2 MB/s",
  "eta": "8s",
  "downloaded": "25.1 MB",
  "total": "36.7 MB",
  "result": null
}
```
*When completed:*
```json
{
  "status": "completed",
  "percent": 100.0,
  "result": {
    "filename": "My Video [video_id].mp4",
    "filesize_str": "36.7 MB",
    "download_url": "/api/file/My%20Video%20[video_id].mp4"
  }
}
```

---

### 5. Quick Download (Synchronous Stream)
Ideal for scripts and terminal curl:
```bash
curl -O -J "http://localhost:5055/api/quick-download?url=https://www.youtube.com/watch?v=...&quality=720p&type=video"
```

---

## 💻 Developer Code Examples

### Python (`requests`)
```python
import requests
import time

BASE = "http://localhost:5055"
url = "https://www.youtube.com/watch?v=4Vz6L8B73i4"

# 1. Start download
res = requests.post(f"{BASE}/api/download", json={
    "url": url,
    "type": "video",
    "quality": "720p"
}).json()

job_id = res["job_id"]
print(f"Download started: {job_id}")

# 2. Poll progress
while True:
    status = requests.get(f"{BASE}/api/progress/{job_id}").json()
    print(f"Progress: {status.get('percent', 0)}% | Speed: {status.get('speed')}")
    if status["status"] in ["completed", "failed"]:
        break
    time.sleep(1)

if status["status"] == "completed":
    file_url = f"{BASE}{status['result']['download_url']}"
    print(f"Download URL: {file_url}")
```

### JavaScript / Node.js
```javascript
const res = await fetch('http://localhost:5055/api/download', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'https://www.youtube.com/shorts/...',
    type: 'video',
    quality: 'best'
  })
});
const data = await res.json();
console.log('Job ID:', data.job_id);
```
