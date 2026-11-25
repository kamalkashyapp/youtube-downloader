"""
Core YouTube & Shorts Downloader Engine
Powered by yt-dlp & FFmpeg
"""

import os
import re
import sys
import time
import shutil
import subprocess
from pathlib import Path
import yt_dlp

def sanitize_filename(name: str) -> str:
    """Sanitize string for safe file paths across Windows & Unix."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip()
    return name[:120] if len(name) > 120 else name

def format_bytes(size: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if not size or size <= 0:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def format_duration(seconds: int) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if not seconds:
        return "00:00"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def is_shorts_url(url: str) -> bool:
    """Check if the provided URL is a YouTube Shorts URL."""
    return "/shorts/" in url.lower()

# Cookie support for cloud datacenter hosting (Hugging Face / Render / Koyeb)
COOKIE_FILE = Path(__file__).resolve().parent / "cookies.txt"

def sanitize_cookie_file(cookie_path: Path):
    """
    Sanitize cookie file:
    If cookie file has all browser cookies (e.g. 1.12MB),
    filter only .youtube.com and .google.com cookies so HTTP headers don't exceed GFE 8KB limit.
    """
    if not cookie_path.exists():
        return
    try:
        content = cookie_path.read_text(encoding="utf-8", errors="ignore")
        if len(content) < 30000 and "youtube.com" in content:
            return
        lines = content.splitlines()
        valid_lines = [
            "# Netscape HTTP Cookie File",
            "# http://curl.haxx.se/rfc/cookie_spec.html\n"
        ]
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split("\t")
            domain = parts[0].lower() if parts else ""
            if any(d in domain for d in ["youtube.com", "google.com", "googlevideo.com"]):
                valid_lines.append(stripped)
        if len(valid_lines) > 2:
            cookie_path.write_text("\n".join(valid_lines) + "\n", encoding="utf-8")
    except Exception:
        pass

if not COOKIE_FILE.exists() and os.environ.get("YOUTUBE_COOKIES"):
    try:
        COOKIE_FILE.write_text(os.environ["YOUTUBE_COOKIES"].strip(), encoding="utf-8")
    except Exception:
        pass

sanitize_cookie_file(COOKIE_FILE)

def get_base_ydl_opts() -> dict:
    global COOKIE_FILE
    if (not COOKIE_FILE.exists() or COOKIE_FILE.stat().st_size <= 10) and os.environ.get("YOUTUBE_COOKIES"):
        try:
            COOKIE_FILE.write_text(os.environ["YOUTUBE_COOKIES"].strip(), encoding="utf-8")
        except Exception:
            pass

    sanitize_cookie_file(COOKIE_FILE)

    opts = {
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'web_creator']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    if COOKIE_FILE.exists() and COOKIE_FILE.stat().st_size > 10:
        opts['cookiefile'] = str(COOKIE_FILE)
    return opts

def extract_with_pytubefix(url: str) -> dict:
    from pytubefix import YouTube
    yt = None
    for client in ['ANDROID', 'IOS', 'WEB']:
        try:
            cand = YouTube(url, client=client)
            if cand.title:
                yt = cand
                break
        except Exception:
            continue
    if not yt:
        raise ValueError("Pytubefix could not extract video info.")

    title = yt.title or "YouTube Video"
    video_id = yt.video_id or ""
    duration = yt.length or 0
    channel = yt.author or "Unknown Channel"
    thumbnail = yt.thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    view_count = yt.views or 0
    upload_date = str(yt.publish_date or "")[:10].replace("-", "")
    description = (yt.description or "")[:300]
    webpage_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
    is_short = "/shorts/" in url.lower() or (duration and duration <= 60 and "short" in title.lower())

    streams = yt.streams
    available_res = set()
    for s in streams.filter(type="video"):
        if s.resolution:
            try:
                res_num = int(s.resolution.replace("p", ""))
                available_res.add(res_num)
            except ValueError:
                pass

    standard_qualities = [
        {"quality": "1080p", "height": 1080, "label": "Full HD (1080p)"},
        {"quality": "720p", "height": 720, "label": "HD (720p)"},
        {"quality": "480p", "height": 480, "label": "SD (480p)"},
        {"quality": "360p", "height": 360, "label": "Standard (360p)"},
    ]

    max_height = max(available_res) if available_res else 720
    highest = streams.get_highest_resolution() or streams.filter(progressive=True).first() or streams.first()
    best_cdn = highest.url if highest else ""

    video_options = [{
        "quality": "best",
        "label": f"Best Available ({max_height}p)",
        "height": max_height,
        "format": "mp4",
        "type": "video",
        "direct_cdn_url": best_cdn
    }]

    for q in standard_qualities:
        if any(h >= q["height"] for h in available_res) or not available_res:
            matching = streams.filter(res=q["quality"]).first()
            cdn_url = matching.url if matching else best_cdn
            video_options.append({
                "quality": q["quality"],
                "label": q["label"],
                "height": q["height"],
                "format": "mp4",
                "type": "video",
                "direct_cdn_url": cdn_url
            })

    audio_stream = streams.get_audio_only()
    best_audio_cdn = audio_stream.url if audio_stream else None
    audio_options = [
        {"quality": "320", "label": "MP3 High Quality (320 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "192", "label": "MP3 Medium Quality (192 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "128", "label": "MP3 Standard Quality (128 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "m4a", "label": "M4A Original Audio", "format": "m4a", "type": "audio", "direct_cdn_url": best_audio_cdn},
    ]

    return {
        "id": video_id,
        "url": webpage_url,
        "title": title,
        "duration": duration,
        "duration_str": format_duration(duration),
        "channel": channel,
        "thumbnail": thumbnail,
        "view_count": view_count,
        "upload_date": upload_date,
        "is_short": is_short,
        "description": description + "..." if len(description) >= 300 else description,
        "video_options": video_options,
        "audio_options": audio_options
    }

def download_with_pytubefix(url: str,
                            target_type: str = "video",
                            quality: str = "720p",
                            out_dir: Path = None,
                            progress_callback = None) -> dict:
    from pytubefix import YouTube
    yt = None
    for client in ['ANDROID', 'IOS', 'WEB']:
        try:
            cand = YouTube(url, client=client)
            if cand.title:
                yt = cand
                break
        except Exception:
            continue
    if not yt:
        raise ValueError("Video download ke liye source connect nahi ho paya.")

    title = sanitize_filename(yt.title or "Video")
    vid_id = yt.video_id or "yt"

    if progress_callback:
        progress_callback({"stage": "downloading", "percent": 25.0, "speed": "--", "eta": "--", "message": "Downloading stream via secondary engine..."})

    if target_type == "audio":
        final_filename = f"{title}_{vid_id}.mp3" if quality != "m4a" else f"{title}_{vid_id}.m4a"
        final_path = out_dir / final_filename

        # Download progressive stream and extract clean audio with ffmpeg (bypasses YouTube SABR restriction)
        prog_stream = yt.streams.filter(progressive=True).first() or yt.streams.filter(type="video").first()
        temp_prog = out_dir / f"temp_{vid_id}.mp4"
        prog_stream.download(output_path=str(out_dir), filename=temp_prog.name)

        codec_flag = ["-b:a", "192k"] if quality != "m4a" else ["-c:a", "copy"]
        try:
            subprocess.run(["ffmpeg", "-y", "-i", str(temp_prog), "-vn"] + codec_flag + [str(final_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            if temp_prog.exists():
                temp_prog.unlink()

    else:
        # Video
        target_res = quality if quality in ["1080p", "720p", "480p", "360p"] else None
        stream = None
        if target_res:
            stream = yt.streams.filter(progressive=True, res=target_res).first()
            if not stream:
                stream = yt.streams.filter(type="video", res=target_res).first()
        if not stream:
            stream = yt.streams.filter(progressive=True).first() or yt.streams.get_highest_resolution() or yt.streams.first()

        final_filename = f"{title}_{vid_id}.mp4"
        final_path = out_dir / final_filename
        stream.download(output_path=str(out_dir), filename=final_filename)

    file_size = final_path.stat().st_size if final_path.exists() else 0
    if progress_callback:
        progress_callback({"stage": "completed", "percent": 100.0, "speed": "--", "eta": "Done", "message": f"Download complete! ({format_bytes(file_size)})"})

    return {
        "filepath": str(final_path),
        "filename": final_path.name,
        "filesize": file_size,
        "filesize_str": format_bytes(file_size),
        "title": yt.title or title,
        "ext": final_path.suffix.lstrip("."),
        "download_url": f"/api/file/{final_path.name}"
    }

def extract_video_info(url: str) -> dict:
    """
    Extract video details and available download qualities without downloading.
    Multi-layer mobile client fallback (bypasses YouTube datacenter bot detection):
    1. Base options (with sanitized cookies if valid + iOS/Android clients)
    2. Mobile iOS & Android client clean session
    3. TV & Creator client fallback
    """
    attempts = [
        get_base_ydl_opts(),
        {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        },
        {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'web_creator']
                }
            }
        }
    ]

    info = None
    last_err = None

    for opts in attempts:
        ydl_opts = dict(opts)
        ydl_opts.update({
            'skip_download': True,
            'extract_flat': False,
        })
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get("title"):
                    break
        except Exception as e:
            last_err = e
            continue

    if not info:
        try:
            return extract_with_pytubefix(url)
        except Exception as pte:
            raise ValueError(f"Video metadata fetch nahi ho paya: {str(pte)}")

    video_id = info.get("id", "")
    title = info.get("title", "YouTube Video")
    duration = info.get("duration", 0)
    channel = info.get("uploader", "") or info.get("channel", "Unknown Channel")
    thumbnail = info.get("thumbnail", "")
    view_count = info.get("view_count", 0)
    upload_date = info.get("upload_date", "")
    description = info.get("description", "") or ""
    webpage_url = info.get("webpage_url", url)

    # Detect if Shorts
    is_short = is_shorts_url(url) or (duration and duration <= 60 and ("shorts" in title.lower() or "short" in str(info.get("tags", []))))

    # Analyze available video resolutions
    available_heights = set()
    formats = info.get("formats", [])
    
    # Check resolutions present
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec")
        if h and vcodec and vcodec != "none":
            available_heights.add(h)

    # Standard quality presets to offer
    standard_qualities = [
        {"quality": "1080p", "height": 1080, "label": "Full HD (1080p)"},
        {"quality": "720p", "height": 720, "label": "HD (720p)"},
        {"quality": "480p", "height": 480, "label": "SD (480p)"},
        {"quality": "360p", "height": 360, "label": "Standard (360p)"},
    ]

    # Find direct Google CDN URLs for each resolution
    def find_cdn_url(target_h=None, audio_only=False):
        if audio_only:
            audio_formats = [f for f in formats if f.get("vcodec") == "none" and f.get("url")]
            return audio_formats[-1]["url"] if audio_formats else None
        if target_h:
            matching = [f for f in formats if f.get("height") == target_h and f.get("url")]
            if matching:
                mp4s = [f for f in matching if f.get("ext") == "mp4"]
                return mp4s[-1]["url"] if mp4s else matching[-1]["url"]
        return None

    video_options = []
    max_height = max(available_heights) if available_heights else 720

    # Best available option
    video_options.append({
        "quality": "best",
        "label": f"Best Available ({max_height}p)",
        "height": max_height,
        "format": "mp4",
        "type": "video",
        "direct_cdn_url": find_cdn_url(target_h=max_height)
    })

    for q in standard_qualities:
        if any(h >= q["height"] for h in available_heights) or not available_heights:
            video_options.append({
                "quality": q["quality"],
                "label": q["label"],
                "height": q["height"],
                "format": "mp4",
                "type": "video",
                "direct_cdn_url": find_cdn_url(target_h=q["height"])
            })

    best_audio_cdn = find_cdn_url(audio_only=True)
    audio_options = [
        {"quality": "320", "label": "MP3 High Quality (320 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "192", "label": "MP3 Medium Quality (192 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "128", "label": "MP3 Standard Quality (128 kbps)", "format": "mp3", "type": "audio", "direct_cdn_url": best_audio_cdn},
        {"quality": "m4a", "label": "M4A Original Audio", "format": "m4a", "type": "audio", "direct_cdn_url": best_audio_cdn},
    ]

    return {
        "id": video_id,
        "url": webpage_url,
        "title": title,
        "duration": duration,
        "duration_str": format_duration(duration),
        "channel": channel,
        "thumbnail": thumbnail,
        "view_count": view_count,
        "upload_date": upload_date,
        "is_short": is_short,
        "description": description[:300] + "..." if len(description) > 300 else description,
        "video_options": video_options,
        "audio_options": audio_options
    }


def download_media(url: str,
                   target_type: str = "video",
                   quality: str = "720p",
                   out_dir: Path = None,
                   progress_callback = None) -> dict:
    """
    Download video or audio with real-time progress callbacks.
    """
    if out_dir is None:
        out_dir = Path(__file__).resolve().parent / "downloads"
    out_dir.mkdir(parents=True, exist_ok=True)

    target_type = target_type.lower()
    quality = quality.lower()

    # Fast cache check: if already downloaded in this quality/type, serve immediately
    vid_match = re.search(r'(?:v=|shorts/|youtu\.be/)([\w-]{11})', url)
    if vid_match:
        vid_id = vid_match.group(1)
        ext_check = ".mp3" if target_type == "audio" and quality != "m4a" else (".m4a" if target_type == "audio" else ".mp4")
        for p in out_dir.glob(f"*{vid_id}*{ext_check}"):
            if p.is_file() and p.stat().st_size > 10000:
                return {
                    "filepath": str(p),
                    "filename": p.name,
                    "filesize": p.stat().st_size,
                    "filesize_str": format_bytes(p.stat().st_size),
                    "title": p.stem,
                    "ext": p.suffix.lstrip("."),
                    "download_url": f"/api/file/{p.name}"
                }

    # Track download state
    download_state = {
        "final_filepath": None,
        "title": None,
        "ext": None,
        "filename": None,
    }

    def my_progress_hook(d):
        if progress_callback:
            status = d.get('status')
            if status == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                
                pct = 0.0
                if total > 0:
                    pct = round((downloaded / total) * 100, 1)

                speed_str = format_bytes(speed) + "/s" if speed else "-- MB/s"
                eta_str = f"{eta}s" if eta else "--"
                
                progress_callback({
                    "stage": "downloading",
                    "percent": min(pct, 98.0),
                    "speed": speed_str,
                    "eta": eta_str,
                    "downloaded": format_bytes(downloaded),
                    "total": format_bytes(total),
                    "message": f"Downloading {pct}% at {speed_str} (ETA {eta_str})"
                })
            elif status == 'finished':
                progress_callback({
                    "stage": "processing",
                    "percent": 99.0,
                    "speed": "--",
                    "eta": "Processing",
                    "message": "Merging audio & video / processing final file..."
                })

    def my_postprocessor_hook(d):
        if d.get('status') == 'finished':
            download_state["final_filepath"] = d.get('info_dict', {}).get('filepath')

    # Configure yt-dlp options based on target_type & quality
    outtmpl = str(out_dir / "%(title).80B [%(id)s].%(ext)s")

    attempts = [
        get_base_ydl_opts(),
        {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        }
    ]

    info = None
    last_err = None

    for base in attempts:
        ydl_opts = dict(base)
        ydl_opts.update({
            'outtmpl': outtmpl,
            'progress_hooks': [my_progress_hook],
            'postprocessor_hooks': [my_postprocessor_hook],
        })

        if target_type == "audio":
            codec = "m4a" if quality == "m4a" else "mp3"
            bitrate = "320" if quality not in ["192", "128"] else quality
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': codec,
                    'preferredquality': bitrate,
                }, {
                    'key': 'FFmpegMetadata',
                }],
            })
        else:
            # Video + Audio
            if quality == "best":
                format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
            elif quality == "1080p":
                format_spec = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]'
            elif quality == "720p":
                format_spec = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]'
            elif quality == "480p":
                format_spec = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]'
            elif quality == "360p":
                format_spec = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360]'
            else:
                format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

            ydl_opts.update({
                'format': format_spec,
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegMetadata',
                }],
            })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                download_state["title"] = info.get("title", "Video")
                last_err = None
                break
        except Exception as e:
            last_err = e
            continue

    if last_err and not info:
        try:
            return download_with_pytubefix(url=url, target_type=target_type, quality=quality, out_dir=out_dir, progress_callback=progress_callback)
        except Exception as pte:
            raise ValueError(f"Download complete nahi ho paya: {str(last_err or pte)}")

    # Determine final saved file
    final_file = download_state.get("final_filepath")
    if not final_file or not os.path.exists(final_file):
        # Scan out_dir for the most recently modified file
        files = list(out_dir.glob("*.*"))
        if files:
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            final_file = str(files[0])

    if not final_file or not os.path.exists(final_file):
        raise FileNotFoundError("Download complete hone ke baad file nahi mili.")

    final_path = Path(final_file)
    file_size = final_path.stat().st_size

    if progress_callback:
        progress_callback({
            "stage": "completed",
            "percent": 100.0,
            "speed": "--",
            "eta": "Done",
            "message": f"Download poora hua! ({format_bytes(file_size)})"
        })

    return {
        "filepath": str(final_path),
        "filename": final_path.name,
        "filesize": file_size,
        "filesize_str": format_bytes(file_size),
        "title": download_state["title"] or final_path.stem,
        "ext": final_path.suffix.lstrip("."),
        "download_url": f"/api/file/{final_path.name}"
    }
