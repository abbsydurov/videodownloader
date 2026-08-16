import asyncio
import re
import os
import sys
import shutil
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

def get_ffmpeg_binary() -> str:
    """Find available ffmpeg binary across system PATH, imageio, and common locations."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for candidate in [
        "ffmpeg",
        "ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
    ]:
        if shutil.which(candidate) or os.path.exists(candidate):
            return candidate
    return "ffmpeg"

async def expand_short_url(url: str) -> str:
    """Expand shortened social links (e.g. pin.it, fb.watch, share links)."""
    if any(k in url for k in ["pin.it", "fb.watch", "bit.ly", "t.co", "/share/"]):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    expanded = str(resp.url)
                    logger.info(f"Expanded URL: {url} -> {expanded}")
                    return expanded
        except Exception as e:
            logger.warning(f"Failed to expand URL {url}: {e}")
    return url

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

async def direct_pinterest_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Direct scraper for Pinterest video streams to prevent black screen and token expiration."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    mp4_matches = re.findall(r'https?://[^\s"\'<>]+\.mp4', html)
                    valid_mp4s = [m for m in mp4_matches if "pinimg.com" in m or "v.pinimg" in m]
                    if valid_mp4s:
                        # Prefer 720p or 1080p
                        best_mp4 = valid_mp4s[0]
                        for m in valid_mp4s:
                            if "720p" in m or "1080p" in m:
                                best_mp4 = m
                                break
                        return {
                            "status": "success",
                            "video_url": best_mp4,
                            "title": "Pinterest Video",
                            "source": "pinterest_direct_scraper"
                        }
    except Exception as e:
        logger.warning(f"Pinterest direct scraper error: {e}")
    return None

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

async def fallback_ytdlp_downloader(url: str, download_file: bool = True) -> Optional[Dict[str, Any]]:
    """Fallback engine using yt-dlp with audio merge guarantee."""
    loop = asyncio.get_event_loop()
    
    def run_yt_dlp():
        try:
            import yt_dlp
            
            temp_dir = tempfile.gettempdir()
            out_template = os.path.join(temp_dir, f"ytdl_%(id)s_{int(asyncio.get_event_loop().time())}.%(ext)s")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'skip_download': not download_file,
                'outtmpl': out_template,
                'postprocessors': [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }] if download_file else [],
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
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
                
                formats = info.get("formats", [])
                video_url = info.get("url")
                hd_url = None
                sd_url = None
                
                if formats:
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
                    "local_file": downloaded_file_path if (downloaded_file_path and os.path.exists(downloaded_file_path) and os.path.getsize(downloaded_file_path) > 1024) else None,
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

async def ensure_playable_video(input_path: str, output_path: str) -> bool:
    """Remux video into 100% playable progressive MP4 with yuv420p & faststart (eliminating black screen)."""
    loop = asyncio.get_event_loop()
    def _remux():
        ffmpeg_bin = get_ffmpeg_binary()
        cmd = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-map", "0:v:0",
            "-map", "0:a?",
            "-movflags", "+faststart",
            output_path
        ]
        success, _ = run_ffmpeg_command(cmd)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True
        return False
    return await loop.run_in_executor(None, _remux)

async def download_media(url: str, force_local_download: bool = True) -> Dict[str, Any]:
    """Unified downloader entry point with automatic URL expansion, local download, and black screen fix."""
    # 1. Expand short URLs (e.g. pin.it, share links)
    expanded_url = await expand_short_url(url)
    platform = detect_platform(expanded_url) or detect_platform(url)
    
    if not platform:
        return {"status": "error", "message": "Unsupported or invalid social media URL!"}

    temp_dir = tempfile.gettempdir()

    # 2. Try yt-dlp with direct download
    fallback_res = await fallback_ytdlp_downloader(expanded_url, download_file=True)
    if fallback_res and fallback_res.get("local_file") and os.path.exists(fallback_res["local_file"]):
        raw_file = fallback_res["local_file"]
        # Remux to guarantee yuv420p faststart playback (fixes black screen)
        remuxed_file = os.path.join(temp_dir, f"play_{int(asyncio.get_event_loop().time())}.mp4")
        if await ensure_playable_video(raw_file, remuxed_file):
            try: os.remove(raw_file)
            except Exception: pass
            fallback_res["local_file"] = remuxed_file
        fallback_res["platform"] = platform
        return fallback_res

    # 3. For Pinterest, try direct HTML scraper
    if platform == "pinterest":
        pin_res = await direct_pinterest_scraper(expanded_url)
        if pin_res and pin_res.get("video_url"):
            raw_target = os.path.join(temp_dir, f"pin_raw_{int(asyncio.get_event_loop().time())}.mp4")
            if await download_url_to_file(pin_res["video_url"], raw_target):
                play_target = os.path.join(temp_dir, f"pin_play_{int(asyncio.get_event_loop().time())}.mp4")
                if await ensure_playable_video(raw_target, play_target):
                    try: os.remove(raw_target)
                    except Exception: pass
                    pin_res["local_file"] = play_target
                else:
                    pin_res["local_file"] = raw_target
                pin_res["platform"] = platform
                return pin_res

    # 4. Try Primary Render API
    primary_res = await fetch_api_downloader(platform, expanded_url)
    if primary_res and primary_res.get("video_url"):
        v_url = primary_res["video_url"]
        raw_target = os.path.join(temp_dir, f"api_raw_{int(asyncio.get_event_loop().time())}.mp4")
        if await download_url_to_file(v_url, raw_target):
            play_target = os.path.join(temp_dir, f"api_play_{int(asyncio.get_event_loop().time())}.mp4")
            if await ensure_playable_video(raw_target, play_target):
                try: os.remove(raw_target)
                except Exception: pass
                primary_res["local_file"] = play_target
            else:
                primary_res["local_file"] = raw_target
            primary_res["platform"] = platform
            return primary_res

    # 5. If stream URL obtained from yt-dlp metadata
    if fallback_res and fallback_res.get("video_url"):
        v_url = fallback_res["video_url"]
        raw_target = os.path.join(temp_dir, f"ytdl_stream_{int(asyncio.get_event_loop().time())}.mp4")
        if await download_url_to_file(v_url, raw_target):
            play_target = os.path.join(temp_dir, f"ytdl_play_{int(asyncio.get_event_loop().time())}.mp4")
            if await ensure_playable_video(raw_target, play_target):
                try: os.remove(raw_target)
                except Exception: pass
                fallback_res["local_file"] = play_target
            else:
                fallback_res["local_file"] = raw_target
            fallback_res["platform"] = platform
            return fallback_res

    return {
        "status": "error",
        "platform": platform,
        "message": f"Unable to fetch video from {platform.title()}. Please verify if the post is public."
    }

async def download_file_to_bytes(url: str) -> Optional[bytes]:
    """Download direct video/audio stream into memory."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.error(f"Failed to download file stream from {url}: {e}")
    return None

async def download_url_to_file(url: str, output_path: str) -> bool:
    """Download direct URL stream into local file with headers & verification."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.google.com/"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=90)) as resp:
                if resp.status == 200:
                    with open(output_path, "wb") as f:
                        while True:
                            chunk = await resp.content.read(1024 * 64)
                            if not chunk:
                                break
                            f.write(chunk)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                        return True
    except Exception as e:
        logger.error(f"Failed to download URL to file {url}: {e}")
    return False

# ==================== ADVANCED MEDIA & SIZE CONVERTER ENGINE ====================
def run_ffmpeg_command(cmd: List[str]) -> Tuple[bool, str]:
    """Execute ffmpeg command synchronously with error handling."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180
        )
        if res.returncode == 0:
            return True, ""
        err_msg = res.stderr.decode('utf-8', errors='ignore')
        logger.error(f"FFmpeg error: {err_msg}")
        return False, err_msg[-300:] if err_msg else "Unknown FFmpeg error"
    except Exception as e:
        logger.error(f"FFmpeg command exception: {e}")
        return False, str(e)

async def convert_video_media(
    input_path: str,
    output_path: str,
    target_mode: str
) -> Tuple[bool, Optional[str]]:
    """
    Convert video resolution or aspect ratio while preserving full audio track.
    Modes: 2160p, 1080p, 720p, 480p, 1to1 (Square), 9to16 (Vertical), compress
    """
    loop = asyncio.get_event_loop()

    def _convert():
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return False, "Input video file is empty or missing."

        ffmpeg_bin = get_ffmpeg_binary()

        # Robust scaling filters guaranteeing even pixel dimensions (yuv420p compliant)
        filter_map = {
            "2160p": r"scale=trunc(iw*min(3840/iw,2160/ih)/2)*2:trunc(ih*min(3840/iw,2160/ih)/2)*2,setsar=1",
            "1080p": r"scale=trunc(iw*min(1920/iw,1080/ih)/2)*2:trunc(ih*min(1920/iw,1080/ih)/2)*2,setsar=1",
            "720p": r"scale=trunc(iw*min(1280/iw,720/ih)/2)*2:trunc(ih*min(1280/iw,720/ih)/2)*2,setsar=1",
            "480p": r"scale=trunc(iw*min(854/iw,480/ih)/2)*2:trunc(ih*min(854/iw,480/ih)/2)*2,setsar=1",
            "1to1": r"scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
            "9to16": r"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
            "compress": r"scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
        }

        vf_str = filter_map.get(target_mode, "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1")
        crf_val = "28" if target_mode == "compress" else "22"

        cmd = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-vf", vf_str,
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", crf_val,
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ]

        success, err = run_ffmpeg_command(cmd)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True, None
        return False, err or "FFmpeg encoding failed."

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
            from PIL import Image, ImageOps
            img = Image.open(input_path)
            img = ImageOps.exif_transpose(img)

            orig_w, orig_h = img.size

            if target_mode == "1to1":
                target_size = (1080, 1080)
                thumb = ImageOps.pad(img, target_size, color=(0, 0, 0))
                thumb.save(output_path, "JPEG", quality=95)
            elif target_mode == "9to16":
                target_size = (1080, 1920)
                thumb = ImageOps.pad(img, target_size, color=(0, 0, 0))
                thumb.save(output_path, "JPEG", quality=95)
            elif target_mode == "2160p":
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
            ffmpeg_bin = get_ffmpeg_binary()
            cmd = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-q:v", "2",
                output_path
            ]
            success, err = run_ffmpeg_command(cmd)
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
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return False
        
        ffmpeg_bin = get_ffmpeg_binary()
        
        if is_voice:
            cmd = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libopus",
                "-b:a", "32k",
                "-vbr", "on",
                output_path
            ]
        else:
            cmd = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libmp3lame",
                "-q:a", "2",
                output_path
            ]
        success, _ = run_ffmpeg_command(cmd)
        return success

    return await loop.run_in_executor(None, _extract)
