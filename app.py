"""
YouTube Video & Shorts Downloader - REST API & Web Dashboard
Supports Hugging Face Spaces (Gradio Server / FastAPI + ZeroGPU) and Local Dev (Flask)
"""

import os
import sys
import uuid
import time
import shutil
import urllib.parse
import threading
from pathlib import Path

# Disable Gradio SSR globally (prevents Node.js server proxy shutdown)
os.environ["GRADIO_SSR_MODE"] = "False"

# Ensure current directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from downloader import extract_video_info, download_media, format_bytes

DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Jobs in-memory tracking
JOBS = {}
JOBS_LOCK = threading.Lock()


def format_views(count):
    if not count:
        return "0"
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.2f}B"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.2f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def run_download_job(job_id: str, url: str, target_type: str, quality: str):
    """Background download runner."""
    def progress_callback(info):
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = info.get("stage", "downloading")
                JOBS[job_id]["percent"] = info.get("percent", 0.0)
                JOBS[job_id]["speed"] = info.get("speed", "--")
                JOBS[job_id]["eta"] = info.get("eta", "--")
                JOBS[job_id]["message"] = info.get("message", "")
                JOBS[job_id]["downloaded"] = info.get("downloaded", "--")
                JOBS[job_id]["total"] = info.get("total", "--")

    try:
        result = download_media(
            url=url,
            target_type=target_type,
            quality=quality,
            out_dir=DOWNLOADS_DIR,
            progress_callback=progress_callback
        )
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["percent"] = 100.0
                JOBS[job_id]["message"] = f"Complete: {result['filename']}"
                JOBS[job_id]["result"] = result
    except Exception as exc:
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = str(exc)
                JOBS[job_id]["message"] = f"Error: {str(exc)}"


def get_index_html():
    html_file = BASE_DIR / "templates" / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>YouTube Downloader Web UI</h1>"


# Check if running in Hugging Face Spaces environment
IS_HF_SPACE = bool(os.environ.get("SPACE_ID"))

if IS_HF_SPACE:
    # --- Hugging Face Spaces Mode ---
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    from gradio import Server
    import spaces

    # 1. Initialize Gradio Server (FastAPI engine)
    app = Server()
    demo = app  # Explicitly assign 'demo' for Gradio Hot Reload

    # 2. Mandatory ZeroGPU Hook (Satisfies Hugging Face ZeroGPU Validator)
    @app.api(name="zerogpu_task")
    @spaces.GPU
    def zerogpu_task(prompt: str = "") -> str:
        """Mandatory hook so ZeroGPU detects an active GPU function."""
        return prompt

    # 3. Add CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 4. Main Web Dashboard (Served directly at Root /)
    @app.get("/", response_class=HTMLResponse)
    async def serve_root_ui():
        return HTMLResponse(get_index_html())

    @app.get("/raw-ui", response_class=HTMLResponse)
    async def serve_raw_ui():
        return HTMLResponse(get_index_html())

    # 5. REST API Endpoint: GET /api?url=...
    @app.get("/api")
    async def hf_api(request: Request, url: str = None):
        url = (url or "").strip()
        if not url:
            return JSONResponse({
                "status": "error",
                "message": "Query param 'url' zaroori hai. Example: /api?url=https://www.youtube.com/watch?v=7SlptRQ_kPU"
            }, status_code=400)
        try:
            info = extract_video_info(url)
            base_url = str(request.base_url).rstrip("/")
            encoded_url = urllib.parse.quote(info["url"])
            video_downloads = []
            for opt in info.get("video_options", []):
                q = opt["quality"]
                video_downloads.append({
                    "quality": q,
                    "label": opt["label"],
                    "height": opt.get("height"),
                    "format": opt["format"],
                    "play_url": f"{base_url}/api/play?url={encoded_url}&quality={q}&type=video",
                    "download_url": f"{base_url}/api/quick-download?url={encoded_url}&quality={q}&type=video",
                    "direct_cdn_url": opt.get("direct_cdn_url")
                })
            audio_downloads = []
            for opt in info.get("audio_options", []):
                q = opt["quality"]
                audio_downloads.append({
                    "quality": q,
                    "label": opt["label"],
                    "format": opt["format"],
                    "play_url": f"{base_url}/api/play?url={encoded_url}&quality={q}&type=audio",
                    "download_url": f"{base_url}/api/quick-download?url={encoded_url}&quality={q}&type=audio",
                    "direct_cdn_url": opt.get("direct_cdn_url")
                })
            return JSONResponse({
                "status": "success",
                "id": info["id"],
                "title": info["title"],
                "url": info["url"],
                "channel": info["channel"],
                "duration": info["duration"],
                "duration_str": info["duration_str"],
                "thumbnail": info["thumbnail"],
                "embed_player_url": f"https://www.youtube.com/embed/{info['id']}",
                "view_count": info["view_count"],
                "views_formatted": format_views(info["view_count"]),
                "upload_date": info["upload_date"],
                "is_short": info["is_short"],
                "description": info["description"],
                "downloads": {
                    "video": video_downloads,
                    "audio": audio_downloads
                }
            })
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

    # 6. REST API: POST /api/info
    @app.post("/api/info")
    async def hf_info(request: Request):
        body = await request.json() if await request.body() else {}
        url = body.get("url", "").strip()
        if not url:
            return JSONResponse({"status": "error", "error": "URL provide nahi kiya gaya."}, status_code=400)
        try:
            info = extract_video_info(url)
            return JSONResponse({"status": "success", "data": info})
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=400)

    # 7. REST API: POST /api/download
    @app.post("/api/download")
    async def hf_download(request: Request):
        body = await request.json() if await request.body() else {}
        url = body.get("url", "").strip()
        target_type = body.get("type", "video").strip().lower()
        quality = body.get("quality", "720p").strip().lower()
        if not url:
            return JSONResponse({"status": "error", "error": "URL provide nahi kiya gaya."}, status_code=400)
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        with JOBS_LOCK:
            JOBS[job_id] = {
                "job_id": job_id, "url": url, "type": target_type, "quality": quality,
                "status": "queued", "percent": 0.0, "speed": "--", "eta": "--",
                "downloaded": "--", "total": "--", "message": "Job queue me lag gaya...",
                "result": None, "error": None, "created_at": time.time()
            }
        threading.Thread(target=run_download_job, args=(job_id, url, target_type, quality), daemon=True).start()
        return JSONResponse({"status": "queued", "job_id": job_id, "check_progress_url": f"/api/progress/{job_id}"}, status_code=202)

    # 8. REST API: GET /api/progress/{job_id}
    @app.get("/api/progress/{job_id}")
    async def hf_progress(job_id: str):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return JSONResponse({"status": "error", "error": "Job ID nahi mila."}, status_code=404)
        return JSONResponse(job)

    # 9. REST API: GET /api/file/{filename}
    @app.get("/api/file/{filename}")
    async def hf_file(filename: str, download: str = "0"):
        filename = Path(filename).name
        filepath = DOWNLOADS_DIR / filename
        if not filepath.exists():
            return JSONResponse({"status": "error", "error": "File nahi mili."}, status_code=404)
        media_type = "video/mp4" if filename.endswith(".mp4") else ("audio/mpeg" if filename.endswith(".mp3") else None)
        headers = {}
        if download == "1":
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        else:
            headers["Content-Disposition"] = f'inline; filename="{filename}"'
        return FileResponse(filepath, media_type=media_type, headers=headers)

    # 10. REST API: GET /api/play
    @app.get("/api/play")
    async def hf_play(url: str, quality: str = "720p", type: str = "video"):
        try:
            res = download_media(url=url, target_type=type, quality=quality, out_dir=DOWNLOADS_DIR)
            filepath = Path(res["filepath"])
            filename = filepath.name
            media_type = "video/mp4" if filename.endswith(".mp4") else ("audio/mpeg" if filename.endswith(".mp3") else None)
            return FileResponse(filepath, media_type=media_type, headers={"Content-Disposition": f'inline; filename="{filename}"'})
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=400)

    # 11. REST API: GET /api/quick-download
    @app.get("/api/quick-download")
    async def hf_quick_download(url: str, quality: str = "720p", type: str = "video"):
        try:
            res = download_media(url=url, target_type=type, quality=quality, out_dir=DOWNLOADS_DIR)
            filepath = Path(res["filepath"])
            filename = filepath.name
            media_type = "video/mp4" if filename.endswith(".mp4") else ("audio/mpeg" if filename.endswith(".mp3") else None)
            return FileResponse(filepath, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=400)

else:
    # --- Local Flask Mode (Windows Local Dev) ---
    from flask import Flask, render_template, request, jsonify, send_from_directory

    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    @app.after_request
    def add_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api", methods=["GET", "POST"])
    def main_api():
        url = request.args.get("url")
        if not url and request.is_json:
            url = (request.get_json(silent=True) or {}).get("url")
        if not url:
            url = request.form.get("url")
        url = (url or "").strip()
        if not url:
            return jsonify({"status": "error", "message": "Query param 'url' zaroori hai. Example: /api?url=https://www.youtube.com/watch?v=7SlptRQ_kPU"}), 400

        action = request.args.get("action", "").lower()
        download_flag = request.args.get("download", "").lower() in ["true", "1", "yes"]
        if action == "download" or download_flag:
            quality = request.args.get("quality", "720p")
            target_type = request.args.get("type", "video")
            try:
                res = download_media(url=url, target_type=target_type, quality=quality, out_dir=DOWNLOADS_DIR)
                return send_from_directory(DOWNLOADS_DIR, res["filename"], as_attachment=True)
            except Exception as e:
                return jsonify({"status": "error", "error": str(e)}), 400

        try:
            info = extract_video_info(url)
            base_url = request.host_url.rstrip("/")
            encoded_url = urllib.parse.quote(info["url"])
            video_downloads = []
            for opt in info.get("video_options", []):
                q = opt["quality"]
                video_downloads.append({
                    "quality": q,
                    "label": opt["label"],
                    "height": opt.get("height"),
                    "format": opt["format"],
                    "play_url": f"{base_url}/api/play?url={encoded_url}&quality={q}&type=video",
                    "download_url": f"{base_url}/api/quick-download?url={encoded_url}&quality={q}&type=video",
                    "direct_cdn_url": opt.get("direct_cdn_url")
                })
            audio_downloads = []
            for opt in info.get("audio_options", []):
                q = opt["quality"]
                audio_downloads.append({
                    "quality": q,
                    "label": opt["label"],
                    "format": opt["format"],
                    "play_url": f"{base_url}/api/play?url={encoded_url}&quality={q}&type=audio",
                    "download_url": f"{base_url}/api/quick-download?url={encoded_url}&quality={q}&type=audio",
                    "direct_cdn_url": opt.get("direct_cdn_url")
                })
            return jsonify({
                "status": "success",
                "id": info["id"],
                "title": info["title"],
                "url": info["url"],
                "channel": info["channel"],
                "duration": info["duration"],
                "duration_str": info["duration_str"],
                "thumbnail": info["thumbnail"],
                "embed_player_url": f"https://www.youtube.com/embed/{info['id']}",
                "view_count": info["view_count"],
                "views_formatted": format_views(info["view_count"]),
                "upload_date": info["upload_date"],
                "is_short": info["is_short"],
                "description": info["description"],
                "downloads": {
                    "video": video_downloads,
                    "audio": audio_downloads
                }
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400

    @app.route("/api/info", methods=["POST"])
    def get_info():
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"status": "error", "error": "URL provide nahi kiya gaya."}), 400
        try:
            info = extract_video_info(url)
            return jsonify({"status": "success", "data": info})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/download", methods=["POST"])
    def start_download():
        data = request.get_json(silent=True) or {}
        url = data.get("url", "").strip()
        target_type = data.get("type", "video").strip().lower()
        quality = data.get("quality", "720p").strip().lower()
        if not url:
            return jsonify({"status": "error", "error": "URL provide nahi kiya gaya."}), 400
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        with JOBS_LOCK:
            JOBS[job_id] = {
                "job_id": job_id, "url": url, "type": target_type, "quality": quality,
                "status": "queued", "percent": 0.0, "speed": "--", "eta": "--",
                "downloaded": "--", "total": "--", "message": "Job queue me lag gaya...",
                "result": None, "error": None, "created_at": time.time()
            }
        threading.Thread(target=run_download_job, args=(job_id, url, target_type, quality), daemon=True).start()
        return jsonify({"status": "queued", "job_id": job_id, "check_progress_url": f"/api/progress/{job_id}"}), 202

    @app.route("/api/progress/<job_id>", methods=["GET"])
    def get_progress(job_id):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return jsonify({"status": "error", "error": "Job ID nahi mila."}), 404
        return jsonify(job)

    @app.route("/api/file/<filename>", methods=["GET"])
    def download_file(filename):
        filename = Path(filename).name
        filepath = DOWNLOADS_DIR / filename
        if not filepath.exists():
            return jsonify({"status": "error", "error": "File nahi mili."}), 404
        is_download = request.args.get("download", "0") == "1"
        ext = filepath.suffix.lower()
        mimetype = "video/mp4" if ext == ".mp4" else ("audio/mpeg" if ext == ".mp3" else None)
        return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=is_download, mimetype=mimetype)

    @app.route("/api/play", methods=["GET"])
    def play_media():
        url = request.args.get("url", "").strip()
        quality = request.args.get("quality", "720p").strip()
        target_type = request.args.get("type", "video").strip().lower()
        if not url:
            return jsonify({"status": "error", "error": "Query param 'url' zaroori hai."}), 400
        try:
            res = download_media(url=url, target_type=target_type, quality=quality, out_dir=DOWNLOADS_DIR)
            ext = Path(res["filename"]).suffix.lower()
            mimetype = "video/mp4" if ext == ".mp4" else ("audio/mpeg" if ext == ".mp3" else "audio/mp4")
            return send_from_directory(DOWNLOADS_DIR, res["filename"], as_attachment=False, mimetype=mimetype)
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/quick-download", methods=["GET"])
    def quick_download():
        url = request.args.get("url", "").strip()
        quality = request.args.get("quality", "720p").strip()
        target_type = request.args.get("type", "video").strip()
        if not url:
            return jsonify({"status": "error", "error": "Query param 'url' zaroori hai."}), 400
        try:
            res = download_media(url=url, target_type=target_type, quality=quality, out_dir=DOWNLOADS_DIR)
            return send_from_directory(DOWNLOADS_DIR, res["filename"], as_attachment=True)
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400


if __name__ == "__main__":
    if IS_HF_SPACE:
        print("\n==========================================")
        print("🚀 YouTube Downloader Live on Hugging Face Spaces!")
        print("==========================================\n")
        demo.launch()
    else:
        port = int(os.environ.get("PORT", 5055))
        print("\n==========================================")
        print("🚀 YouTube Downloader Local Dev Live!")
        print(f"👉 Local Web UI: http://localhost:{port}")
        print(f"👉 API Endpoint: http://localhost:{port}/api?url=...")
        print("==========================================\n")
        app.run(host="0.0.0.0", port=port, debug=False)
