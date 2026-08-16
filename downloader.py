import asyncio
import re
import os
import tempfile
import logging
import aiohttp
import subprocess
from typing import Dict, Any, Optional, List, Tuple
from config import API_ENDPOINTS, logger

# URL Regex Patterns
INSTAGRAM_PATTERN = re.compile(r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories|share)/[a-zA-Z0-9_\-\.]+)')
PINTEREST_PATTERN = re.compile(r'(https?://(?:www\.)?(?:pinterest\.com/pin/|pin\.it/)[a-zA-Z0-9_\-\.]+)')
SNAPCHAT_PATTERN = re.compile(r'(https?://(?:www\.)?snapchat\.com/(?:t|p|spotlight|add)/[a-zA-Z0-9_\-\.]+)')
FACEBOOK_PATTERN = re.compile(r'(https?://(?:www\.)?(?:facebook\.com|fb\.watch|fb\.com)/(?:reel|videos|watch|share|story\.php|ads|posts)/[a-zA-Z0-9_\-\.\?=/]+)')

def detect_platform(url: str) -> Optional[str]:
    url_lower = url.lower()
    if "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    elif "pinterest.com" in url_lower or "pin.it" in url_lower:
        return "pinterest"
    elif "snapchat.com" in url_lower or "snap.com" in url_lower:
        return "snapchat"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    return None

def extract_urls(text: str) -> List[str]:
    """Extract all valid social media URLs from message text."""
    urls = []
    raw_urls = re.findall(r'https?://[^\s]+', text)
    for u in raw_urls:
        p = detect_platform(u)
        if p:
            urls.append(u)
    return urls

async def fetch_api_downloader(platform: str, url: str) -> Optional[Dict[str, Any]]:
    """Query the primary render API endpoint."""
    api_base = API_ENDPOINTS.get(platform)
    if not api_base:
        return None
    
    target_url = f"{api_base}{url}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict) and data.get("status") != "error":
                        media_url = data.get("video_url") or data.get("url") or data.get("video") or data.get("download_url") or data.get("data")
                        if media_url and isinstance(media_url, str) and media_url.startswith("http"):
                            return {
                                "status": "success",
                                "video_url": media_url,
                                "title": data.get("title", f"{platform.title()} Video"),
                                "thumbnail": data.get("thumbnail") or data.get("thumb")
                            }
    except Exception as e:
        logger.warning(f"Primary API error for {platform} ({url}): {e}")
    return None

async def fallback_ytdlp_downloader(url: str, download_file: bool = False) -> Optional[Dict[str, Any]]:
    """Fallback engine using yt-dlp to extract high quality media WITH SOUND / AUDIO intact."""
    loop = asyncio.get_event_loop()
    
    def run_yt_dlp():
        try:
            import yt_dlp
            
            # Temporary file target if download is requested
            temp_dir = tempfile.gettempdir()
            out_template = os.path.join(temp_dir, f"ytdl_%(id)s_%(epoch)s.%(ext)s")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                # Guarantee BOTH video and audio streams are selected and merged
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'skip_download': not download_file,
                'outtmpl': out_template,
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }] if download_file else [],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=download_file)
                if not info:
                    return None
                
                downloaded_file_path = None
                if download_file:
                    downloaded_file_path = ydl.prepare_filename(info)
                    if not downloaded_file_path.endswith('.mp4'):
                        downloaded_file_path = os.path.splitext(downloaded_file_path)[0] + '.mp4'
                
                # Check format list or direct url
                formats = info.get("formats", [])
                video_url = info.get("url")
                hd_url = None
                sd_url = None
                
                if formats:
                    # Filter video formats that have BOTH video AND audio (non-empty acodec & vcodec)
                    with_audio_formats = [
                        f for f in formats 
                        if f.get("url") and f.get("vcodec") != "none" and f.get("acodec") != "none"
                    ]
                    
                    if with_audio_formats:
                        sorted_formats = sorted(with_audio_formats, key=lambda f: f.get("height") or 0, reverse=True)
                        hd_url = sorted_formats[0].get("url")
                        sd_url = sorted_formats[-1].get("url")
                        video_url = hd_url or video_url
                    else:
                        # If separated streams, sort all valid video formats
                        all_vformats = [f for f in formats if f.get("url") and f.get("vcodec") != "none"]
                        if all_vformats:
                            sorted_formats = sorted(all_vformats, key=lambda f: f.get("height") or 0, reverse=True)
                            hd_url = sorted_formats[0].get("url")
                            video_url = hd_url or video_url

                title = info.get("title") or info.get("description") or "Downloaded Media"
                thumb = info.get("thumbnail")
                width = info.get("width")
                height = info.get("height")
                duration = info.get("duration", 0)
                
                return {
                    "status": "success",
                    "video_url": video_url,
                    "hd_url": hd_url or video_url,
                    "sd_url": sd_url or video_url,
                    "local_file": downloaded_file_path if (downloaded_file_path and os.path.exists(downloaded_file_path)) else None,
                    "title": str(title)[:100],
                    "thumbnail": thumb,
                    "width": width,
                    "height": height,
                    "duration": duration,
                    "source": "yt-dlp fallback"
                }
        except Exception as e:
            logger.error(f"yt-dlp exception for {url}: {e}")
            return None

    return await loop.run_in_executor(None, run_yt_dlp)

async def download_media(url: str, force_local_download: bool = False) -> Dict[str, Any]:
    """Unified downloader entry point with primary API + automatic fallback + audio guarantee."""
    platform = detect_platform(url)
    if not platform:
        return {"status": "error", "message": "Unsupported or invalid social media URL!"}

    # 1. Try yt-dlp with audio merge guarantee first or direct API
    fallback_res = await fallback_ytdlp_downloader(url, download_file=force_local_download)
    if fallback_res and (fallback_res.get("video_url") or fallback_res.get("local_file")):
        fallback_res["platform"] = platform
        return fallback_res

    # 2. Try Primary Render API
    primary_res = await fetch_api_downloader(platform, url)
    if primary_res:
        v_url = primary_res.get("video_url")
        if v_url and isinstance(v_url, str) and v_url.startswith("http"):
            return {
                "status": "success",
                "platform": platform,
                "video_url": v_url,
                "hd_url": primary_res.get("hd_url") or v_url,
                "sd_url": primary_res.get("sd_url") or v_url,
                "title": primary_res.get("title", f"{platform.title()} Video"),
                "thumbnail": primary_res.get("thumbnail") or primary_res.get("thumb"),
                "source": "primary_api"
            }

    return {
        "status": "error",
        "platform": platform,
        "message": f"Unable to fetch video from {platform.title()}. The media might be private or deleted."
    }

async def download_file_to_bytes(url: str) -> Optional[bytes]:
    """Download direct video/audio stream into memory or temporary file."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.error(f"Failed to download file stream from {url}: {e}")
    return None

async def download_url_to_file(url: str, output_path: str) -> bool:
    """Download direct URL stream into local file."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=90)) as resp:
                if resp.status == 200:
                    with open(output_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(1024 * 64)
                            if not chunk:
                                break
                            f.write(chunk)
                    return True
    except Exception as e:
        logger.error(f"Failed to download URL to file {url}: {e}")
    return False

# ==================== ADVANCED MEDIA & SIZE CONVERTER ENGINE ====================
def run_ffmpeg_command(cmd: List[str]) -> bool:
    """Execute ffmpeg command synchronously with error handling."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180
        )
        if res.returncode == 0:
            return True
        logger.error(f"FFmpeg error: {res.stderr.decode('utf-8', errors='ignore')}")
    except Exception as e:
        logger.error(f"FFmpeg command exception: {e}")
    return False

async def convert_video_media(
    input_path: str,
    output_path: str,
    target_mode: str
) -> Tuple[bool, Optional[str]]:
    """
    Convert video resolution or aspect ratio while preserving full sound/audio.
    Modes: 2160p, 1080p, 720p, 480p, 1to1 (Square), 9to16 (Vertical), compress
    """
    loop = asyncio.get_event_loop()

    def _convert():
        if not os.path.exists(input_path):
            return False, "Input video file does not exist."

        # Base ffmpeg filter mapping
        # Preserving original aspect ratio with padding or scaling
        filter_map = {
            "2160p": "scale=-2:2160",
            "1080p": "scale=-2:1080",
            "720p": "scale=-2:720",
            "480p": "scale=-2:480",
            "1to1": "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black",
            "9to16": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "compress": "scale='min(1280,iw)':-2"
        }

        vf_str = filter_map.get(target_mode, "scale=-2:1080")
        
        crf_val = "28" if target_mode == "compress" else "22"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", crf_val,
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ]

        success = run_ffmpeg_command(cmd)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True, None
        return False, "FFmpeg conversion failed."

    return await loop.run_in_executor(None, _convert)

async def convert_image_media(
    input_path: str,
    output_path: str,
    target_mode: str
) -> Tuple[bool, Optional[str]]:
    """
    Resize or format images and photos (1:1, 9:16, 4K, 1080p, 720p, 480p, compress).
    """
    loop = asyncio.get_event_loop()

    def _convert():
        try:
            # Try PIL / Pillow first
            from PIL import Image, ImageOps
            img = Image.open(input_path)
            img = ImageOps.exif_transpose(img) # Correct auto-rotation

            orig_w, orig_h = img.size

            if target_mode == "1to1":
                # Square format with centered fit
                target_size = (1080, 1080)
                thumb = ImageOps.pad(img, target_size, color=(0, 0, 0))
                thumb.save(output_path, "JPEG", quality=95)
            elif target_mode == "9to16":
                # Vertical Story format
                target_size = (1080, 1920)
                thumb = ImageOps.pad(img, target_size, color=(0, 0, 0))
                thumb.save(output_path, "JPEG", quality=95)
            elif target_mode == "2160p":
                # 4K Ultra HD
                ratio = 2160 / max(orig_h, 1)
                new_w = int(orig_w * ratio)
                resized = img.resize((new_w, 2160), Image.Resampling.LANCZOS)
                resized.save(output_path, "JPEG", quality=95)
            elif target_mode == "1080p":
                ratio = 1080 / max(orig_h, 1)
                new_w = int(orig_w * ratio)
                resized = img.resize((new_w, 1080), Image.Resampling.LANCZOS)
                resized.save(output_path, "JPEG", quality=92)
            elif target_mode == "720p":
                ratio = 720 / max(orig_h, 1)
                new_w = int(orig_w * ratio)
                resized = img.resize((new_w, 720), Image.Resampling.LANCZOS)
                resized.save(output_path, "JPEG", quality=90)
            elif target_mode == "480p":
                ratio = 480 / max(orig_h, 1)
                new_w = int(orig_w * ratio)
                resized = img.resize((new_w, 480), Image.Resampling.LANCZOS)
                resized.save(output_path, "JPEG", quality=85)
            elif target_mode == "compress":
                img.save(output_path, "JPEG", quality=65, optimize=True)
            else:
                img.save(output_path, "JPEG", quality=90)

            return True, None
        except Exception as pil_err:
            # Fallback to FFmpeg for image resizing
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-q:v", "2",
                output_path
            ]
            success = run_ffmpeg_command(cmd)
            if success and os.path.exists(output_path):
                return True, None
            return False, f"Image conversion error: {pil_err}"

    return await loop.run_in_executor(None, _convert)

async def extract_audio_from_media(
    input_path: str,
    output_path: str,
    is_voice: bool = True
) -> bool:
    """Extract sound into voice note (.ogg with opus) or audio (.mp3)."""
    loop = asyncio.get_event_loop()

    def _extract():
        if not os.path.exists(input_path):
            return False
        
        if is_voice:
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libopus",
                "-b:a", "32k",
                "-vbr", "on",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_path
            ]
        return run_ffmpeg_command(cmd)

    return await loop.run_in_executor(None, _extract)
