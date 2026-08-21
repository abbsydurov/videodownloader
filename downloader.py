import asyncio
import re
import os
import sys
import time
import shutil
import tempfile
import logging
import aiohttp
import subprocess
from typing import Dict, Any, Optional, List, Tuple
from config import API_ENDPOINTS, logger

# URL Regex Patterns
INSTAGRAM_PATTERN = re.compile(r'(https?://(?:www\.)?(?:instagram\.com|instagr\.am|ig\.me)/(?:p|reel|reels|tv|stories|share/reel|share/p|share)/[a-zA-Z0-9_\-\./\?=&]+)')
PINTEREST_PATTERN = re.compile(r'(https?://(?:www\.)?(?:pinterest\.com/pin/|pin\.it/)[a-zA-Z0-9_\-\.]+)')
SNAPCHAT_PATTERN = re.compile(r'(https?://(?:www\.)?snapchat\.com/(?:t|p|spotlight|add)/[a-zA-Z0-9_\-\.]+)')
FACEBOOK_PATTERN = re.compile(r'(https?://(?:www\.)?(?:facebook\.com|fb\.watch|fb\.com|m\.facebook\.com)/(?:reel|videos|watch|share|story\.php|ads|posts)/[a-zA-Z0-9_\-\.\?=/]+)')

def get_ffmpeg_binary() -> str:
    """Find available ffmpeg binary across imageio_ffmpeg, system PATH, and Heroku locations."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    for candidate in [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/app/vendor/ffmpeg/ffmpeg",
        "ffmpeg",
        "ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
    ]:
        if shutil.which(candidate) or os.path.exists(candidate):
            return candidate
    return "ffmpeg"

def is_ffmpeg_available() -> bool:
    """Check if ffmpeg can be executed."""
    bin_path = get_ffmpeg_binary()
    try:
        res = subprocess.run([bin_path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        return res.returncode == 0
    except Exception:
        return False

async def expand_short_url(url: str) -> str:
    """Expand shortened social links (e.g. pin.it, fb.watch, instagram share links)."""
    url = url.strip().strip("[]()<>\"'")
    if any(k in url for k in ["pin.it", "fb.watch", "bit.ly", "t.co", "/share/", "ig.me"]):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    expanded = str(resp.url)
                    logger.info(f"Expanded URL: {url} -> {expanded}")
                    return expanded
        except Exception as e:
            logger.warning(f"Failed to expand URL {url}: {e}")
    return url

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if any(k in url_lower for k in ["instagram.com", "instagr.am", "ig.me"]):
        return "instagram"
    elif any(k in url_lower for k in ["tiktok.com", "douyin.com"]):
        return "tiktok"
    elif any(k in url_lower for k in ["youtube.com", "youtu.be"]):
        return "youtube"
    elif any(k in url_lower for k in ["twitter.com", "x.com/", "//x.com", "t.co/"]):
        return "twitter"
    elif any(k in url_lower for k in ["pinterest.com", "pin.it"]):
        return "pinterest"
    elif any(k in url_lower for k in ["snapchat.com", "snap.com"]):
        return "snapchat"
    elif any(k in url_lower for k in ["facebook.com", "fb.watch", "fb.com", "fb.me"]):
        return "facebook"
    elif any(k in url_lower for k in ["reddit.com", "redd.it"]):
        return "reddit"
    elif any(k in url_lower for k in ["threads.net", "threads.com"]):
        return "threads"
    elif any(k in url_lower for k in ["spotify.com", "soundcloud.com"]):
        return "audio"
    return "media"

def extract_urls(text: str) -> List[str]:
    """Extract all valid social & media URLs from message text with markdown & bracket cleaning."""
    urls = []
    clean_text = text.replace("[", " ").replace("]", " ").replace("(", " ").replace(")", " ").replace("<", " ").replace(">", " ")
    raw_urls = re.findall(r'https?://[^\s\'"<>\[\]\(\)]+', clean_text)
    for u in raw_urls:
        u = u.strip().rstrip(".,;!?:")
        if is_valid_media_url(u) if 'is_valid_media_url' in globals() else True:
            if u not in urls:
                urls.append(u)
    return urls

# ==================== INSTAGRAM MULTI-LAYER SCRAPERS ====================
def is_valid_media_url(u: str) -> bool:
    """Validate that a URL is an actual downloadable media file and not a website asset or ad."""
    if not u or not isinstance(u, str) or not u.startswith("http"):
        return False
    u_lower = u.lower()
    invalid_patterns = [
        "pagead", "adsbygoogle", "googleads", "analytics", "doubleclick",
        "favicon", "apple-icon", "logo", "avatar", "icon/", ".js", ".css",
        ".ico", "null", "undefined", "about:blank", "indown.io/new"
    ]
    if any(p in u_lower for p in invalid_patterns):
        return False
    return True

def extract_instagram_shortcode(url: str) -> Optional[str]:
    """Extract Instagram post/reel shortcode from URL."""
    url = url.strip().strip("[]()<>\"'")
    match = re.search(r'(?:instagram\.com|instagr\.am|ig\.me)/(?:reels|reel|p|tv|stories|share/reel|share/p|share)/([a-zA-Z0-9_\-]+)', url)
    if match:
        return match.group(1)
    
    clean_url = url.split("?")[0].rstrip("/")
    parts = clean_url.split("/")
    if len(parts) >= 2 and parts[-2] in ["reel", "reels", "p", "tv"]:
        return parts[-1]
    return None

def shortcode_to_media_id(shortcode: str) -> Optional[int]:
    """Convert Instagram base64-like shortcode to numeric media ID."""
    try:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        media_id = 0
        for char in shortcode:
            media_id = (media_id * 64) + alphabet.index(char)
        return media_id
    except Exception:
        return None

def decode_snapsave_js(js_code: str) -> str:
    """Decode SnapSave / SnapInsta packed JavaScript obfuscation."""
    try:
        pattern = r'\(\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
        match = re.search(pattern, js_code)
        if match:
            h, u, n, t, e, r = match.groups()
            u, t, e, r = int(u), int(t), int(e), int(r)
            
            def base_decode(d, base_e, base_f):
                alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
                h_set = alphabet[0:base_e]
                i_set = alphabet[0:base_f]
                res = 0
                for idx, char in enumerate(reversed(d)):
                    if char in h_set:
                        res += h_set.index(char) * (base_e ** idx)
                if res == 0:
                    return "0"
                out = ""
                while res > 0:
                    out = i_set[res % base_f] + out
                    res //= base_f
                return out

            res_str = ""
            i = 0
            while i < len(h):
                s = ""
                while i < len(h) and h[i] != n[e]:
                    s += h[i]
                    i += 1
                for j in range(len(n)):
                    s = s.replace(n[j], str(j))
                if s:
                    res_str += chr(int(base_decode(s, e, 10)) - t)
                i += 1
            return res_str
    except Exception:
        pass
    return ""

async def direct_snapsave_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Scrape SnapSave engine and unpack client-side payload."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://snapsave.app/",
        "Origin": "https://snapsave.app"
    }
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), headers=headers) as s:
            async with s.post("https://snapsave.app/action.php", data={"url": url}, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    raw_js = await r.text()
                    decoded_html = decode_snapsave_js(raw_js)
                    if decoded_html:
                        vids = re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\'][^>]*class=["\'][^"\']*download', decoded_html) or \
                               re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\'][^>]*>Download', decoded_html) or \
                               re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\']', decoded_html)
                        for v in vids:
                            clean_v = v.replace("&amp;", "&")
                            if is_valid_media_url(clean_v) and not any(k in clean_v for k in ["snapsave", "facebook.com", "instagram.com", "google.com"]):
                                is_img = any(ext in clean_v.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
                                return {
                                    "status": "success",
                                    "media_type": "photo" if is_img else "video",
                                    "video_url": None if is_img else clean_v,
                                    "image_url": clean_v if is_img else None,
                                    "title": "Instagram Media",
                                    "source": "snapsave_scraper"
                                }
    except Exception as e:
        logger.warning(f"SnapSave scraper error: {e}")
    return None

async def direct_indown_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Scrape InDown.io for Instagram Reels, Posts, and Photos."""
    clean_url = url.split("?")[0]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": "https://indown.io/reels",
        "Origin": "https://indown.io",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), headers=headers) as session:
            async with session.get("https://indown.io/reels", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    token_m = re.search(r'name="_token"\s+value="([^"]+)"', html)
                    if token_m:
                        token = token_m.group(1)
                        post_data = {
                            "referer": "https://indown.io/reels",
                            "locale": "en",
                            "_token": token,
                            "link": clean_url
                        }
                        async with session.post("https://indown.io/download", data=post_data, timeout=aiohttp.ClientTimeout(total=15)) as post_resp:
                            if post_resp.status == 200:
                                post_html = await post_resp.text()
                                
                                v_matches = re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\'][^>]*class=["\'][^"\']*btn-primary[^"\']*["\']', post_html) or \
                                            re.findall(r'href=["\'](https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)["\']', post_html) or \
                                            re.findall(r'src=["\'](https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)["\']', post_html)
                                
                                for v in v_matches:
                                    clean_v = v.replace("&amp;", "&")
                                    if is_valid_media_url(clean_v) and ("cdninstagram" in clean_v or "fbcdn" in clean_v or "mp4" in clean_v or "download" in clean_v):
                                        return {
                                            "status": "success",
                                            "media_type": "video",
                                            "video_url": clean_v,
                                            "title": "Instagram Video",
                                            "source": "indown_scraper"
                                        }
                                
                                img_matches = re.findall(r'href=["\'](https?://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)[^\s"\'<>]*)["\']', post_html) or \
                                              re.findall(r'src=["\'](https?://[^\s"\'<>]*(?:cdninstagram|fbcdn)[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)[^\s"\'<>]*)["\']', post_html)
                                for im in img_matches:
                                    clean_im = im.replace("&amp;", "&")
                                    if is_valid_media_url(clean_im):
                                        return {
                                            "status": "success",
                                            "media_type": "photo",
                                            "image_url": clean_im,
                                            "title": "Instagram Photo",
                                            "source": "indown_scraper"
                                        }
    except Exception as e:
        logger.warning(f"InDown scraper error: {e}")
    return None

async def direct_instagram_graphql_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Query Instagram official Mobile & GraphQL endpoints supporting Photos, Videos, and Carousels."""
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        return None

    media_id = shortcode_to_media_id(shortcode)
    urls_to_try = [
        f"https://www.instagram.com/graphql/query/?doc_id=8845758582119845&variables={{\"shortcode\":\"{shortcode}\"}}",
        f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    ]
    if media_id:
        urls_to_try.insert(0, f"https://www.instagram.com/api/v1/media/{media_id}/info/")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/p/{shortcode}/"
    }

    for target in urls_to_try:
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), headers=headers) as session:
                async with session.get(target, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict):
                            # Check GraphQL format
                            shortcode_media = data.get("data", {}).get("xdt_shortcode_media", {}) or data.get("graphql", {}).get("shortcode_media", {})
                            if shortcode_media:
                                is_vid = shortcode_media.get("is_video", False)
                                v_url = shortcode_media.get("video_url")
                                img_url = shortcode_media.get("display_url")
                                if is_vid and is_valid_media_url(v_url):
                                    return {
                                        "status": "success",
                                        "media_type": "video",
                                        "video_url": v_url,
                                        "title": "Instagram Video",
                                        "source": "instagram_graphql"
                                    }
                                elif img_url and is_valid_media_url(img_url):
                                    return {
                                        "status": "success",
                                        "media_type": "photo",
                                        "image_url": img_url,
                                        "title": "Instagram Photo",
                                        "source": "instagram_graphql"
                                    }

                            # Check items format
                            items = data.get("items", [])
                            if items:
                                item = items[0]
                                caption = "Instagram Media"
                                if isinstance(item.get("caption"), dict):
                                    caption = item.get("caption", {}).get("text", "Instagram Media")
                                
                                media_type = item.get("media_type")
                                if media_type == 2 or item.get("video_versions"):
                                    v_versions = item.get("video_versions", [])
                                    if v_versions:
                                        best_v = sorted(v_versions, key=lambda x: x.get("height", 0), reverse=True)[0]
                                        v_url = best_v.get("url")
                                        if is_valid_media_url(v_url):
                                            return {
                                                "status": "success",
                                                "media_type": "video",
                                                "video_url": v_url,
                                                "title": caption,
                                                "source": "instagram_mobile_api"
                                            }

                                elif media_type == 8 and item.get("carousel_media"):
                                    media_list = []
                                    for c in item["carousel_media"]:
                                        if c.get("video_versions"):
                                            best_c_v = sorted(c["video_versions"], key=lambda x: x.get("height", 0), reverse=True)[0]
                                            media_list.append({"type": "video", "url": best_c_v.get("url")})
                                        elif c.get("image_versions2", {}).get("candidates"):
                                            c_cands = c["image_versions2"]["candidates"]
                                            best_c_img = sorted(c_cands, key=lambda x: x.get("height", 0), reverse=True)[0]
                                            media_list.append({"type": "photo", "url": best_c_img.get("url")})
                                    
                                    if media_list:
                                        first_item = media_list[0]
                                        return {
                                            "status": "success",
                                            "media_type": "carousel" if len(media_list) > 1 else first_item["type"],
                                            "media_list": media_list,
                                            "video_url": first_item["url"] if first_item["type"] == "video" else None,
                                            "image_url": first_item["url"] if first_item["type"] == "photo" else None,
                                            "title": caption,
                                            "source": "instagram_mobile_api"
                                        }

                                elif media_type == 1 or item.get("image_versions2"):
                                    cands = item.get("image_versions2", {}).get("candidates", [])
                                    if cands:
                                        best_img = sorted(cands, key=lambda x: x.get("height", 0), reverse=True)[0]
                                        img_url = best_img.get("url")
                                        if is_valid_media_url(img_url):
                                            return {
                                                "status": "success",
                                                "media_type": "photo",
                                                "image_url": img_url,
                                                "title": caption,
                                                "source": "instagram_mobile_api"
                                            }
        except Exception as e:
            logger.warning(f"Instagram GraphQL/Mobile API error for {target}: {e}")
    return None

async def direct_instagram_ajax_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Scrape Instagram media via high-reliability public AJAX APIs for both Photos and Videos."""
    clean_url = url.split("?")[0]
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://saveig.app/en"
        }
        data = {"q": clean_url, "t": "media", "lang": "en"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://saveig.app/api/ajaxSearch", data=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    json_data = await resp.json()
                    html_content = json_data.get("data", "")
                    if html_content:
                        v_links = re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\'][^>]*class=["\'][^"\']*abutton[^"\']*["\']', html_content) or \
                                  re.findall(r'href=["\'](https?://[^\s"\'<>]+download[^\s"\'<>]*)["\']', html_content) or \
                                  re.findall(r'href=["\'](https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)["\']', html_content)
                        
                        if v_links:
                            return {
                                "status": "success",
                                "media_type": "video",
                                "video_url": v_links[0].replace("&amp;", "&"),
                                "title": "Instagram Video",
                                "source": "saveig_ajax"
                            }
                        
                        img_links = re.findall(r'href=["\'](https?://[^\s"\'<>]+\.(?:jpg|jpeg|webp|png)[^\s"\'<>]*)["\']', html_content) or \
                                    re.findall(r'src=["\'](https?://[^\s"\'<>]+\.(?:jpg|jpeg|webp|png)[^\s"\'<>]*)["\']', html_content)
                        if img_links:
                            return {
                                "status": "success",
                                "media_type": "photo",
                                "image_url": img_links[0].replace("&amp;", "&"),
                                "title": "Instagram Photo",
                                "source": "saveig_ajax"
                            }
    except Exception as e:
        logger.warning(f"SaveIG AJAX scraper error: {e}")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://snapinsta.app/"
        }
        data = {"url": clean_url, "action": "post"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://snapinsta.app/action.php", data=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html_content = await resp.text()
                    links = re.findall(r'href=["\'](https?://[^\s"\'<>]+)["\'][^>]*download', html_content)
                    if links:
                        link_url = links[0].replace("&amp;", "&")
                        is_img = any(ext in link_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
                        return {
                            "status": "success",
                            "media_type": "photo" if is_img else "video",
                            "video_url": None if is_img else link_url,
                            "image_url": link_url if is_img else None,
                            "title": "Instagram Media",
                            "source": "snapinsta_ajax"
                        }
    except Exception as e:
        logger.warning(f"SnapInsta AJAX scraper error: {e}")

    return None

async def cobalt_instagram_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Query multi-instance Cobalt engine for Instagram links."""
    instances = [
        "https://co.wuk.sh/api/json",
        "https://cobalt-api.kwiatekm.pl/api/json",
        "https://api.cobalt.tools/api/json"
    ]
    for inst in instances:
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            payload = {"url": url, "vQuality": "max"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(inst, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        v_url = res.get("url")
                        if v_url and v_url.startswith("http"):
                            return {
                                "status": "success",
                                "media_type": "video",
                                "video_url": v_url,
                                "title": res.get("filename", "Instagram Video"),
                                "source": "cobalt_api"
                            }
        except Exception:
            continue
    return None

async def direct_instagram_embed_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Direct Embed Scraper: Instagram embed pages contain direct CDN video or photo URLs."""
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        return None

    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(embed_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    v_match = (
                        re.search(r'class=["\']EmbeddedVideo["\'][^>]*src=["\']([^"\']+)["\']', html) or
                        re.search(r'src=["\']([^"\']+)["\'][^>]*class=["\']EmbeddedVideo["\']', html) or
                        re.search(r'"video_url"\s*:\s*"([^"]+)"', html) or
                        re.search(r'video_url:\s*["\']([^"\']+)["\']', html) or
                        re.search(r'"video_versions":\[\{"url":"([^"]+)"', html) or
                        re.search(r'https?:\\/\\/[^\s"\'<>]+\.mp4[^\s"\'<>]*', html)
                    )

                    if v_match:
                        clean_url = v_match.group(1).replace("&amp;", "&").replace(r"\/", "/") if hasattr(v_match, 'group') and v_match.group(1) else v_match.group(0).replace(r"\/", "/").replace("&amp;", "&")
                        if clean_url.startswith("http"):
                            logger.info(f"Instagram embed scraper success for shortcode {shortcode}")
                            return {
                                "status": "success",
                                "media_type": "video",
                                "video_url": clean_url,
                                "title": "Instagram Video",
                                "source": "instagram_embed"
                            }
                    
                    img_match = re.search(r'class=["\']EmbeddedMediaImage["\'][^>]*src=["\']([^"\']+)["\']', html) or \
                                re.search(r'src=["\']([^"\']+)["\'][^>]*class=["\']EmbeddedMediaImage["\']', html) or \
                                re.search(r'"display_url"\s*:\s*"([^"]+)"', html)
                    if img_match:
                        clean_img = img_match.group(1).replace("&amp;", "&").replace(r"\/", "/")
                        if clean_img.startswith("http"):
                            return {
                                "status": "success",
                                "media_type": "photo",
                                "image_url": clean_img,
                                "title": "Instagram Photo",
                                "source": "instagram_embed"
                            }
    except Exception as e:
        logger.warning(f"Instagram embed scraper error: {e}")
    return None

async def direct_instagram_api_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Query Instagram web info JSON endpoint."""
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        return None

    info_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
        "X-IG-App-ID": "936619743392459",
        "Sec-Fetch-Site": "same-origin"
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(info_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict):
                        items = data.get("items", [])
                        if items:
                            item = items[0]
                            caption = item.get("caption", {}).get("text", "Instagram Media") if isinstance(item.get("caption"), dict) else "Instagram Media"
                            v_versions = item.get("video_versions", [])
                            if v_versions:
                                best_v = sorted(v_versions, key=lambda x: x.get("height", 0), reverse=True)[0]
                                return {
                                    "status": "success",
                                    "media_type": "video",
                                    "video_url": best_v.get("url"),
                                    "title": caption,
                                    "source": "instagram_api"
                                }
                            cands = item.get("image_versions2", {}).get("candidates", [])
                            if cands:
                                best_img = sorted(cands, key=lambda x: x.get("height", 0), reverse=True)[0]
                                return {
                                    "status": "success",
                                    "media_type": "photo",
                                    "image_url": best_img.get("url"),
                                    "title": caption,
                                    "source": "instagram_api"
                                }
    except Exception as e:
        logger.warning(f"Instagram info API error: {e}")
    return None

# ==================== FACEBOOK DIRECT SCRAPER ====================
def unescape_fb_url(url_str: str) -> str:
    """Clean and unescape Facebook JSON encoded stream URLs."""
    if not url_str:
        return ""
    clean = url_str.replace(r"\/", "/").replace("\\u0025", "%").replace("&amp;", "&")
    return clean

async def direct_facebook_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Direct scraper for Facebook Reels, Watch, and Video posts."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "navigate"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    hd_match = re.search(r'"playable_url_quality_hd"\s*:\s*"([^"]+)"', html) or \
                               re.search(r'"browser_native_hd_url"\s*:\s*"([^"]+)"', html) or \
                               re.search(r'hd_src\s*:\s*"([^"]+)"', html)
                    
                    sd_match = re.search(r'"playable_url"\s*:\s*"([^"]+)"', html) or \
                               re.search(r'"browser_native_sd_url"\s*:\s*"([^"]+)"', html) or \
                               re.search(r'sd_src\s*:\s*"([^"]+)"', html)

                    hd_url = unescape_fb_url(hd_match.group(1)) if hd_match else None
                    sd_url = unescape_fb_url(sd_match.group(1)) if sd_match else None
                    chosen_url = hd_url or sd_url

                    if chosen_url and chosen_url.startswith("http"):
                        title_match = re.search(r'<title>([^<]+)</title>', html)
                        title = title_match.group(1).replace(" | Facebook", "") if title_match else "Facebook Video"

                        return {
                            "status": "success",
                            "media_type": "video",
                            "video_url": chosen_url,
                            "hd_url": hd_url or chosen_url,
                            "sd_url": sd_url or chosen_url,
                            "title": title[:100],
                            "source": "facebook_direct_scraper"
                        }
    except Exception as e:
        logger.warning(f"Facebook direct scraper error for {url}: {e}")
    return None

# ==================== PINTEREST DIRECT SCRAPER ====================
async def direct_pinterest_scraper(url: str) -> Optional[Dict[str, Any]]:
    """Direct scraper for Pinterest video and photo streams."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    mp4_matches = re.findall(r'https?://[^\s"\'<>]+\.mp4', html)
                    valid_mp4s = [m for m in mp4_matches if "pinimg.com" in m or "v.pinimg" in m]
                    if valid_mp4s:
                        best_mp4 = valid_mp4s[0]
                        for m in valid_mp4s:
                            if "720p" in m or "1080p" in m:
                                best_mp4 = m
                                break
                        return {
                            "status": "success",
                            "media_type": "video",
                            "video_url": best_mp4,
                            "title": "Pinterest Video",
                            "source": "pinterest_direct_scraper"
                        }
                    
                    img_matches = re.findall(r'https?://i\.pinimg\.com/originals/[^\s"\'<>]+\.(?:jpg|png|jpeg|webp)', html) or \
                                  re.findall(r'https?://i\.pinimg\.com/736x/[^\s"\'<>]+\.(?:jpg|png|jpeg|webp)', html)
                    if img_matches:
                        return {
                            "status": "success",
                            "media_type": "photo",
                            "image_url": img_matches[0],
                            "title": "Pinterest Photo",
                            "source": "pinterest_direct_scraper"
                        }
    except Exception as e:
        logger.warning(f"Pinterest direct scraper error: {e}")
    return None

# ==================== PRIMARY API ENDPOINT ====================
async def fetch_api_downloader(platform: str, url: str) -> Optional[Dict[str, Any]]:
    """Query the primary render API endpoint with extended timeout and strict media validation."""
    api_base = API_ENDPOINTS.get(platform)
    if not api_base:
        return None
    
    clean_target = url.split("?")[0] if platform == "instagram" else url
    target_url = f"{api_base}{clean_target}"
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict) and data.get("status") != "error" and "error" not in str(data.get("message", "")).lower():
                        media_url = data.get("video_url") or data.get("url") or data.get("video") or data.get("download_url") or data.get("data") or data.get("image_url") or data.get("image")
                        if media_url and is_valid_media_url(media_url):
                            is_img = any(ext in media_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"])
                            return {
                                "status": "success",
                                "media_type": "photo" if is_img else "video",
                                "video_url": None if is_img else media_url,
                                "image_url": media_url if is_img else None,
                                "title": data.get("title", f"{platform.title()} Media"),
                                "thumbnail": data.get("thumbnail") or data.get("thumb")
                            }
    except Exception as e:
        logger.warning(f"Primary API error for {platform} ({url}): {e}")
    return None

# ==================== YT-DLP FALLBACK ENGINE ====================
async def fallback_ytdlp_downloader(url: str, download_file: bool = True) -> Optional[Dict[str, Any]]:
    """Fallback engine using yt-dlp with audio merge guarantee and Instagram extractor support."""
    loop = asyncio.get_event_loop()
    
    def run_yt_dlp():
        try:
            import yt_dlp
            
            temp_dir = tempfile.gettempdir()
            out_template = os.path.join(temp_dir, f"ytdl_%(id)s_{int(time.time())}.%(ext)s")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'skip_download': not download_file,
                'outtmpl': out_template,
                'extractor_args': {
                    'instagram': {'player_client': ['ios', 'android', 'web']}
                },
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 324.0.0.18.109',
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            }
            
            for c_file in ["cookies.txt", "instagram_cookies.txt", "insta_cookies.txt", os.getenv("COOKIES_FILE", "")]:
                if c_file and os.path.exists(c_file):
                    ydl_opts['cookiefile'] = c_file
                    break

            if is_ffmpeg_available() and download_file:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': 'mp4',
                }]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=download_file)
                if not info:
                    return None
                
                downloaded_file_path = None
                if download_file:
                    downloaded_file_path = ydl.prepare_filename(info)
                    if not downloaded_file_path.endswith('.mp4'):
                        alt_path = os.path.splitext(downloaded_file_path)[0] + '.mp4'
                        if os.path.exists(alt_path):
                            downloaded_file_path = alt_path
                
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
                    "media_type": "video",
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

# ==================== REMUX & VIDEO PLAYABILITY ENGINE ====================
def get_video_metadata_and_thumb(video_path: str) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[str]]:
    """Extract width, height, duration, and thumbnail using ffmpeg for flawless Telegram video player streaming."""
    try:
        ffmpeg_bin = get_ffmpeg_binary()
        temp_dir = tempfile.gettempdir()
        thumb_path = os.path.join(temp_dir, f"thumb_{int(time.time())}_{abs(hash(video_path)) % 10000}.jpg")
        
        # 1. Generate Thumbnail
        cmd_thumb = [
            ffmpeg_bin, "-y",
            "-ss", "00:00:00.500",
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            thumb_path
        ]
        run_ffmpeg_command(cmd_thumb)
        
        w, h, dur = None, None, None
        if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 100:
            try:
                from PIL import Image
                with Image.open(thumb_path) as img:
                    w, h = img.size
            except Exception:
                pass
        else:
            thumb_path = None

        # 2. Probe Duration and Dimensions via ffmpeg info if available
        try:
            cmd_probe = [ffmpeg_bin, "-i", video_path]
            res = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8)
            probe_out = res.stderr.decode('utf-8', errors='ignore')
            
            dur_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.?\d*)', probe_out)
            if dur_match:
                hours = int(dur_match.group(1))
                minutes = int(dur_match.group(2))
                seconds = float(dur_match.group(3))
                dur = int(hours * 3600 + minutes * 60 + seconds)
            
            if not w or not h:
                res_match = re.search(r'Video:.*,\s*(\d{2,5})x(\d{2,5})', probe_out)
                if res_match:
                    w = int(res_match.group(1))
                    h = int(res_match.group(2))
        except Exception as probe_err:
            logger.warning(f"Video metadata probe error: {probe_err}")

        return w, h, dur, thumb_path
    except Exception as e:
        logger.warning(f"Failed to generate video thumbnail: {e}")
    return None, None, None, None

async def ensure_playable_video(input_path: str, output_path: str) -> bool:
    """
    Remux video into 100% playable progressive MP4 with yuv420p & faststart.
    Fixes Instagram/Telegram 'Cannot play video' errors on all mobile & desktop clients.
    """
    if not is_ffmpeg_available():
        return False

    loop = asyncio.get_event_loop()
    def _remux():
        ffmpeg_bin = get_ffmpeg_binary()
        
        # Pass 1: Full H.264 Main profile + AAC stereo + yuv420p + faststart
        cmd1 = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-profile:v", "main",
            "-level", "4.0",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ac", "2",
            "-ar", "44100",
            "-movflags", "+faststart",
            output_path
        ]
        success, _ = run_ffmpeg_command(cmd1)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True

        # Pass 2: Fallback conversion with automatic audio detection
        cmd2 = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ]
        success, _ = run_ffmpeg_command(cmd2)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True

        # Pass 3: Video-only transcode if audio stream is missing/corrupted
        cmd3 = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            output_path
        ]
        success, _ = run_ffmpeg_command(cmd3)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True

        # Pass 4: Fast stream copy with faststart container fix
        cmd4 = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ]
        success, _ = run_ffmpeg_command(cmd4)
        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True

        return False

    return await loop.run_in_executor(None, _remux)

def is_explicit_video_url(url: str) -> bool:
    """Check if the URL is specifically a video or reel link."""
    u_lower = url.lower()
    return any(k in u_lower for k in [
        "/reel/", "/reels/", "/tv/", "/share/reel", "/watch", "/videos/",
        "fb.watch", "/spotlight/", "pin.it"
    ])

# ==================== UNIFIED DOWNLOADER ENTRYPOINT ====================
async def download_media(url: str, force_local_download: bool = True) -> Dict[str, Any]:
    """
    Unified Downloader Pipeline supporting Instagram (Reels/Posts/Stories/Photos/Carousels),
    Pinterest (Pins/Clips/Photos), Facebook (Reels/Watch), and Snapchat.
    Guarantees video extraction for Reels/Videos without falling back to cover photos.
    """
    expanded_url = await expand_short_url(url)
    platform = detect_platform(expanded_url) or detect_platform(url)
    
    if not platform:
        return {"status": "error", "message": "Unsupported or invalid social media URL!"}

    temp_dir = tempfile.gettempdir()
    must_be_video = is_explicit_video_url(expanded_url) or is_explicit_video_url(url)
    fallback_photo_res = None

    # ---------------- 1. INSTAGRAM PIPELINE ----------------
    if platform == "instagram":
        # A. Try User's Primary Render API First
        primary_res = await fetch_api_downloader(platform, expanded_url)
        if primary_res:
            if primary_res.get("video_url"):
                v_url = primary_res["video_url"]
                raw_target = os.path.join(temp_dir, f"insta_raw_{int(time.time())}.mp4")
                if await download_url_to_file(v_url, raw_target):
                    play_target = os.path.join(temp_dir, f"insta_play_{int(time.time())}.mp4")
                    if await ensure_playable_video(raw_target, play_target):
                        try: os.remove(raw_target)
                        except Exception: pass
                        primary_res["local_file"] = play_target
                    else:
                        primary_res["local_file"] = raw_target
                    primary_res["platform"] = platform
                    return primary_res
            elif primary_res.get("image_url") and not must_be_video:
                raw_target = os.path.join(temp_dir, f"insta_img_{int(time.time())}.jpg")
                if await download_url_to_file(primary_res["image_url"], raw_target):
                    primary_res["local_file"] = raw_target
                primary_res["platform"] = platform
                return primary_res
            elif primary_res.get("image_url"):
                fallback_photo_res = primary_res

        # B. Multi-layer direct video scrapers
        scrapers = [
            direct_snapsave_scraper,
            direct_instagram_graphql_scraper,
            direct_instagram_ajax_scraper,
            cobalt_instagram_scraper,
            direct_instagram_embed_scraper,
            direct_indown_scraper,
            direct_instagram_api_scraper
        ]

        for scraper in scrapers:
            try:
                res = await scraper(expanded_url)
                if res and res.get("status") == "success":
                    res["platform"] = platform
                    
                    # 1. Handle Video
                    if res.get("video_url"):
                        raw_target = os.path.join(temp_dir, f"insta_raw_{int(time.time())}.mp4")
                        if await download_url_to_file(res["video_url"], raw_target):
                            play_target = os.path.join(temp_dir, f"insta_play_{int(time.time())}.mp4")
                            if await ensure_playable_video(raw_target, play_target):
                                try: os.remove(raw_target)
                                except Exception: pass
                                res["local_file"] = play_target
                            else:
                                res["local_file"] = raw_target
                        return res

                    # 2. Handle Carousel
                    elif res.get("media_type") == "carousel" and res.get("media_list"):
                        return res

                    # 3. Handle Photo only if not an explicit Reel/Video
                    elif res.get("media_type") == "photo" and res.get("image_url"):
                        if not must_be_video:
                            raw_target = os.path.join(temp_dir, f"insta_img_{int(time.time())}.jpg")
                            if await download_url_to_file(res["image_url"], raw_target):
                                res["local_file"] = raw_target
                            return res
                        else:
                            if not fallback_photo_res:
                                fallback_photo_res = res
            except Exception as scraper_err:
                logger.warning(f"Instagram scraper {scraper.__name__} error: {scraper_err}")
                continue

        # C. Fallback to yt-dlp extractor engine
        try:
            ytdl_res = await fallback_ytdlp_downloader(expanded_url, download_file=True)
            if ytdl_res and (ytdl_res.get("video_url") or ytdl_res.get("local_file")):
                ytdl_res["platform"] = platform
                return ytdl_res
        except Exception as yt_err:
            logger.warning(f"yt-dlp fallback error: {yt_err}")

        # D. If all video scrapers failed and fallback photo exists (for normal posts)
        if fallback_photo_res and not must_be_video:
            if fallback_photo_res.get("image_url") and not fallback_photo_res.get("local_file"):
                raw_target = os.path.join(temp_dir, f"insta_img_{int(time.time())}.jpg")
                if await download_url_to_file(fallback_photo_res["image_url"], raw_target):
                    fallback_photo_res["local_file"] = raw_target
            fallback_photo_res["platform"] = platform
            return fallback_photo_res

    # ---------------- 2. FACEBOOK PIPELINE ----------------
    if platform == "facebook":
        fb_res = await direct_facebook_scraper(expanded_url)
        if fb_res and fb_res.get("video_url"):
            raw_target = os.path.join(temp_dir, f"fb_raw_{int(time.time())}.mp4")
            if await download_url_to_file(fb_res["video_url"], raw_target):
                play_target = os.path.join(temp_dir, f"fb_play_{int(time.time())}.mp4")
                if await ensure_playable_video(raw_target, play_target):
                    try: os.remove(raw_target)
                    except Exception: pass
                    fb_res["local_file"] = play_target
                else:
                    fb_res["local_file"] = raw_target
                fb_res["platform"] = platform
                return fb_res

    # ---------------- 3. PINTEREST PIPELINE ----------------
    if platform == "pinterest":
        pin_res = await direct_pinterest_scraper(expanded_url)
        if pin_res and pin_res.get("status") == "success":
            pin_res["platform"] = platform
            if pin_res.get("media_type") == "photo" and pin_res.get("image_url"):
                raw_target = os.path.join(temp_dir, f"pin_img_{int(time.time())}.jpg")
                if await download_url_to_file(pin_res["image_url"], raw_target):
                    pin_res["local_file"] = raw_target
                return pin_res
            elif pin_res.get("video_url"):
                raw_target = os.path.join(temp_dir, f"pin_raw_{int(time.time())}.mp4")
                if await download_url_to_file(pin_res["video_url"], raw_target):
                    play_target = os.path.join(temp_dir, f"pin_play_{int(time.time())}.mp4")
                    if await ensure_playable_video(raw_target, play_target):
                        try: os.remove(raw_target)
                        except Exception: pass
                        pin_res["local_file"] = play_target
                    else:
                        pin_res["local_file"] = raw_target
                return pin_res

    # ---------------- 4. YT-DLP ENGINE (ALL PLATFORMS) ----------------
    fallback_res = await fallback_ytdlp_downloader(expanded_url, download_file=True)
    if fallback_res and fallback_res.get("local_file") and os.path.exists(fallback_res["local_file"]):
        raw_file = fallback_res["local_file"]
        remuxed_file = os.path.join(temp_dir, f"play_{int(time.time())}.mp4")
        if await ensure_playable_video(raw_file, remuxed_file):
            try: os.remove(raw_file)
            except Exception: pass
            fallback_res["local_file"] = remuxed_file
        fallback_res["platform"] = platform
        return fallback_res

    # ---------------- 5. PRIMARY RENDER API FALLBACK ----------------
    primary_res = await fetch_api_downloader(platform, expanded_url)
    if primary_res and (primary_res.get("video_url") or primary_res.get("image_url")):
        if primary_res.get("image_url"):
            raw_target = os.path.join(temp_dir, f"api_img_{int(time.time())}.jpg")
            if await download_url_to_file(primary_res["image_url"], raw_target):
                primary_res["local_file"] = raw_target
            primary_res["platform"] = platform
            return primary_res
        elif primary_res.get("video_url"):
            v_url = primary_res["video_url"]
            raw_target = os.path.join(temp_dir, f"api_raw_{int(time.time())}.mp4")
            if await download_url_to_file(v_url, raw_target):
                play_target = os.path.join(temp_dir, f"api_play_{int(time.time())}.mp4")
                if await ensure_playable_video(raw_target, play_target):
                    try: os.remove(raw_target)
                    except Exception: pass
                    primary_res["local_file"] = play_target
                else:
                    primary_res["local_file"] = raw_target
                primary_res["platform"] = platform
                return primary_res

    # ---------------- 6. STREAM URL FALLBACK ----------------
    if fallback_res and fallback_res.get("video_url"):
        v_url = fallback_res["video_url"]
        raw_target = os.path.join(temp_dir, f"ytdl_stream_{int(time.time())}.mp4")
        if await download_url_to_file(v_url, raw_target):
            play_target = os.path.join(temp_dir, f"ytdl_play_{int(time.time())}.mp4")
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
        "message": f"Unable to fetch media from {platform.title()}. Please verify if the post is public."
    }

async def download_file_to_bytes(url: str) -> Optional[bytes]:
    """Download direct video/audio stream into memory."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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

        filter_map = {
            "2160p": "scale=-2:2160",
            "1080p": "scale=-2:1080",
            "720p": "scale=-2:720",
            "480p": "scale=-2:480",
            "1to1": "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black",
            "9to16": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "compress": "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        }

        vf_str = filter_map.get(target_mode, "scale=trunc(iw/2)*2:trunc(ih/2)*2")
        crf_val = "28" if target_mode == "compress" else "22"

        cmd = [
            ffmpeg_bin, "-y",
            "-i", input_path,
            "-vf", vf_str,
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
    Properly converts RGBA/palette modes to RGB for clean JPEG output.
    """
    loop = asyncio.get_event_loop()

    def _convert():
        try:
            from PIL import Image, ImageOps
            img = Image.open(input_path)
            img = ImageOps.exif_transpose(img)

            # Ensure image is in RGB mode before saving as JPEG
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if "A" in img.mode:
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

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
    """
    Extract sound into Telegram voice note (.ogg with Opus) or MP3 audio (.mp3 with LAME).
    Prevents container/codec incompatibility errors.
    """
    if not is_ffmpeg_available():
        return False

    loop = asyncio.get_event_loop()

    def _extract():
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            return False
        
        ffmpeg_bin = get_ffmpeg_binary()
        
        if is_voice:
            # Telegram voice notes require Opus in OGG container at 48000Hz mono
            cmd1 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libopus",
                "-b:a", "64k",
                "-ar", "48000",
                "-ac", "1",
                output_path
            ]
            success, _ = run_ffmpeg_command(cmd1)
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return True

            # Fallback 2: General ogg encoding
            cmd2 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "opus",
                "-b:a", "64k",
                output_path
            ]
            success, _ = run_ffmpeg_command(cmd2)
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return True

            # Fallback 3: Copy audio stream
            cmd3 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "copy",
                output_path
            ]
            success, _ = run_ffmpeg_command(cmd3)
            return success and os.path.exists(output_path) and os.path.getsize(output_path) > 100

        else:
            # MP3 audio with MP3 encoder
            cmd1 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
                output_path
            ]
            success, _ = run_ffmpeg_command(cmd1)
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return True

            # Fallback 2: Default mp3 transcode
            cmd2 = [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-vn",
                "-b:a", "192k",
                output_path
            ]
            success, _ = run_ffmpeg_command(cmd2)
            return success and os.path.exists(output_path) and os.path.getsize(output_path) > 100

    return await loop.run_in_executor(None, _extract)
