import asyncio
import re
import os
import tempfile
import logging
import aiohttp
import subprocess
from typing import Dict, Any, Optional, List
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
    # Match general http/https URLs
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
                        return data
                    # Check nested or direct media fields
                    if isinstance(data, dict):
                        # Some APIs return direct link inside key
                        media_url = data.get("url") or data.get("video") or data.get("download_url") or data.get("data")
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

async def fallback_ytdlp_downloader(url: str) -> Optional[Dict[str, Any]]:
    """Fallback engine using yt-dlp to extract high quality media links & streams."""
    loop = asyncio.get_event_loop()
    
    def run_yt_dlp():
        try:
            import yt_dlp
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestvideo+bestaudio/best',
                'skip_download': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None
                
                # Check format list or direct url
                formats = info.get("formats", [])
                video_url = info.get("url")
                hd_url = None
                sd_url = None
                
                if formats:
                    # Filter video formats with direct HTTP links
                    video_formats = [f for f in formats if f.get("url") and f.get("vcodec") != "none"]
                    if video_formats:
                        # Sort by resolution/height
                        sorted_formats = sorted(video_formats, key=lambda f: f.get("height") or 0, reverse=True)
                        hd_url = sorted_formats[0].get("url")
                        sd_url = sorted_formats[-1].get("url")
                        video_url = hd_url or video_url

                title = info.get("title") or info.get("description") or "Downloaded Media"
                thumb = info.get("thumbnail")
                
                return {
                    "status": "success",
                    "video_url": video_url,
                    "hd_url": hd_url or video_url,
                    "sd_url": sd_url or video_url,
                    "title": str(title)[:100],
                    "thumbnail": thumb,
                    "duration": info.get("duration", 0),
                    "source": "yt-dlp fallback"
                }
        except Exception as e:
            logger.error(f"yt-dlp fallback exception for {url}: {e}")
            return None

    return await loop.run_in_executor(None, run_yt_dlp)

async def download_media(url: str) -> Dict[str, Any]:
    """Unified downloader entry point with primary API + automatic fallback."""
    platform = detect_platform(url)
    if not platform:
        return {"status": "error", "message": "Unsupported or invalid social media URL!"}

    # 1. Try Primary Render API
    primary_res = await fetch_api_downloader(platform, url)
    if primary_res:
        # Extract fields from primary API response
        v_url = (
            primary_res.get("video_url") or 
            primary_res.get("url") or 
            primary_res.get("video") or 
            primary_res.get("download_url") or
            (primary_res.get("data") if isinstance(primary_res.get("data"), str) else None)
        )
        if v_url and isinstance(v_url, str) and v_url.startswith("http"):
            return {
                "status": "success",
                "platform": platform,
                "video_url": v_url,
                "hd_url": primary_res.get("hd_url") or v_url,
                "sd_url": primary_res.get("sd_url") or v_url,
                "audio_url": primary_res.get("audio_url") or v_url,
                "title": primary_res.get("title", f"{platform.title()} Video"),
                "thumbnail": primary_res.get("thumbnail") or primary_res.get("thumb"),
                "source": "primary_api"
            }

    # 2. Try Fallback yt-dlp Engine
    fallback_res = await fallback_ytdlp_downloader(url)
    if fallback_res and fallback_res.get("video_url"):
        fallback_res["platform"] = platform
        return fallback_res

    return {
        "status": "error",
        "platform": platform,
        "message": f"Unable to fetch video from {platform.title()}. The video might be private or deleted."
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
