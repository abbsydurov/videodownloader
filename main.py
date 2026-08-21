import asyncio
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List, Callable, Awaitable, Optional

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware, types
from aiogram.enums import ParseMode, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message,
    CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InlineQueryResultVideo, InputTextMessageContent, URLInputFile,
    FSInputFile, InputMediaPhoto, InputMediaVideo, TelegramObject
)
from aiogram.exceptions import TelegramAPIError

import config
from config import (
    BOT_TOKEN, SUPER_ADMIN_ID, SUPER_ADMIN_IDS, LOG_CHANNEL_ID, WELCOME_IMAGE,
    get_p_emoji, get_btn_emoji_id, logger
)
import database as db
import downloader

async def is_admin_user(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    return await db.is_user_authorized(user_id)

# Middleware for registering user activity on every incoming update
class UserActivityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            try:
                await db.register_user(
                    user_id=event.from_user.id,
                    first_name=event.from_user.first_name or "",
                    username=event.from_user.username or ""
                )
            except Exception as e:
                logger.warning(f"Failed to register user: {e}")
        return await handler(event, data)

# Initialize Routers
start_router = Router(name="start_handler")
downloader_router = Router(name="downloader_handler")
callback_router = Router(name="callback_handler")
emoji_router = Router(name="emoji_handler")
admin_router = Router(name="admin_handler")
inline_router = Router(name="inline_handler")

def get_user_help_guide() -> str:
    return (
        f"{get_p_emoji('star')} <b><u>Sᴏᴄɪᴀʟ Mᴇᴅɪᴀ Vɪᴅᴇᴏ Dᴏᴡɴʟᴏᴀᴅᴇʀ &amp; Mᴇᴅɪᴀ Rᴇsɪᴢᴇʀ Gᴜɪᴅᴇ</u></b> {get_p_emoji('star')}\n\n"
        f"{get_p_emoji('sparkles')} <b>Sᴜᴘᴘᴏʀᴛᴇᴅ Pʟᴀᴛғᴏʀᴍs:</b>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('insta')} <b>Instagram</b> ── <i>Reels, Posts, Photos, Carousels, Stories</i>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('pin')} <b>Pinterest</b> ── <i>Pins, Photos &amp; Video clips</i>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('snap')} <b>Snapchat</b> ── <i>Spotlight &amp; Stories</i>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('fb')} <b>Facebook</b> ── <i>Reels, Videos &amp; Meta Ads</i>\n\n"
        f"{get_p_emoji('zap')} <b>Hᴏᴡ Tᴏ Usᴇ:</b>\n"
        f"{get_p_emoji('one')} <b>Download with Sound:</b> Send any video link to download with 100% full audio track.\n"
        f"{get_p_emoji('two')} <b>Download Photos &amp; Carousels:</b> Send any Instagram/Pinterest photo post to download in full high quality!\n"
        f"{get_p_emoji('three')} <b>Direct Media Resizer:</b> Send ANY Video or Photo directly to resize to 4K, 1080p, 720p, 1:1 Square, or 9:16 Vertical!\n"
        f"{get_p_emoji('four')} <b>Voice Note &amp; Audio:</b> Convert any video into a Telegram Voice Note (.ogg) or MP3.\n\n"
        f"{get_p_emoji('box')} <b>Mᴜʟᴛɪ-Dᴏᴡɴʟᴏᴀᴅɪɴɢ:</b> Paste multiple links together in one message!\n"
        f"{get_p_emoji('search')} <b>Iɴʟɪɴᴇ Sᴇᴀʀᴄʜ Mᴏᴅᴇ:</b> Type <code>@botusername &lt;link&gt;</code> in any Telegram chat."
    )

def get_admin_help_guide() -> str:
    return (
        f"{get_p_emoji('star')} <b><u>{get_p_emoji('crown')} Aᴅᴍɪɴ Cᴏɴᴛʀᴏʟ Gᴜɪᴅᴇ</u></b> {get_p_emoji('star')}\n\n"
        f"{get_p_emoji('bullet')} <code>/stats</code> ── <i>Live platform download statistics &amp; user counts</i>\n"
        f"{get_p_emoji('bullet')} <code>/logs</code> ── <i>View recent system download logs from MongoDB</i>\n"
        f"{get_p_emoji('bullet')} <code>/grant &lt;user_id&gt;</code> ── <i>Grant admin authorization</i>\n"
        f"{get_p_emoji('bullet')} <code>/revoke &lt;user_id&gt;</code> ── <i>Revoke admin access</i>\n"
        f"{get_p_emoji('bullet')} <code>/addemoji &lt;name&gt; &lt;id&gt;</code> ── <i>Upload custom premium emoji ID</i>\n"
        f"{get_p_emoji('bullet')} <code>/emojis</code> ── <i>View all saved custom emoji IDs</i>\n"
        f"{get_p_emoji('bullet')} <code>/broadcast</code> ── <i>Send announcement to all registered users</i>"
    )

def make_btn(
    text: str,
    callback_data: Optional[str] = None,
    url: Optional[str] = None,
    style: str = "primary",
    emoji_name: Optional[str] = None
) -> InlineKeyboardButton:
    """Create stylish Telegram Inline Button with native button colors (primary, success, danger) & premium emoji icons."""
    kwargs = {
        "text": text,
        "style": style if style in ["primary", "success", "danger"] else "primary"
    }
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url

    if emoji_name:
        emoji_id = config.get_btn_emoji_id(emoji_name) if hasattr(config, 'get_btn_emoji_id') else None
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        else:
            char = config.get_btn_emoji(emoji_name) if hasattr(config, 'get_btn_emoji') else None
            if char:
                kwargs["text"] = f"{char} {text}"

    return InlineKeyboardButton(**kwargs)

def clean_markup_for_fallback(reply_markup: Optional[InlineKeyboardMarkup]) -> Optional[InlineKeyboardMarkup]:
    """Clean custom emoji IDs from markup if Telegram client raises BUTTON_DATA_INVALID."""
    if not reply_markup or not hasattr(reply_markup, "inline_keyboard"):
        return reply_markup
    new_rows = []
    for row in reply_markup.inline_keyboard:
        new_row = []
        for btn in row:
            kwargs = {"text": btn.text}
            if hasattr(btn, "style") and btn.style:
                kwargs["style"] = btn.style
            if btn.callback_data:
                kwargs["callback_data"] = btn.callback_data
            if btn.url:
                kwargs["url"] = btn.url
            new_row.append(InlineKeyboardButton(**kwargs))
        new_rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)

async def safe_reply(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    photo: Optional[str] = None
) -> Message:
    """
    Sends message with Custom Premium Emojis (<tg-emoji>) and Button Colors.
    If Telegram raises ENTITY_TEXT_INVALID, DOCUMENT_INVALID, or BUTTON_DATA_INVALID,
    it automatically strips restricted tags and retries seamlessly!
    """
    try:
        if photo and photo.startswith("http"):
            return await message.answer_photo(photo=photo, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        err_msg = str(e)
        if any(err in err_msg for err in ["ENTITY_TEXT_INVALID", "DOCUMENT_INVALID", "BUTTON_DATA_INVALID", "can't parse entities"]):
            clean_text = re.sub(r'<tg-emoji emoji-id="[^"]*">([^<]*)</tg-emoji>', r'\1', text)
            clean_kb = clean_markup_for_fallback(reply_markup)
            try:
                if photo and photo.startswith("http"):
                    return await message.answer_photo(photo=photo, caption=clean_text, reply_markup=clean_kb, parse_mode=parse_mode)
                return await message.answer(clean_text, reply_markup=clean_kb, parse_mode=parse_mode)
            except Exception:
                try:
                    return await message.answer(clean_text, reply_markup=clean_kb)
                except Exception:
                    pass
        raise e

async def safe_edit_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None
):
    """Safely edits caption or text with auto-fallback for custom emojis."""
    try:
        if callback.message.photo or callback.message.caption:
            await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        err_msg = str(e)
        if any(err in err_msg for err in ["ENTITY_TEXT_INVALID", "DOCUMENT_INVALID", "BUTTON_DATA_INVALID", "can't parse entities"]):
            clean_text = re.sub(r'<tg-emoji emoji-id="[^"]*">([^<]*)</tg-emoji>', r'\1', text)
            clean_kb = clean_markup_for_fallback(reply_markup)
            try:
                if callback.message.photo or callback.message.caption:
                    await callback.message.edit_caption(caption=clean_text, reply_markup=clean_kb, parse_mode=parse_mode)
                else:
                    await callback.message.edit_text(text=clean_text, reply_markup=clean_kb, parse_mode=parse_mode)
                return
            except Exception:
                pass
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass

def get_downloader_keyboard(url: str, platform: str, video_url: str, cache_hash: str) -> InlineKeyboardMarkup:
    kb = [
        [
            make_btn("Video (Full Sound 4K)", f"dl_vid:{platform}:{cache_hash}", style="success", emoji_name="fire"),
            make_btn("Voice Note (.ogg)", f"dl_voice:{platform}:{cache_hash}", style="primary", emoji_name="mic")
        ],
        [
            make_btn("Audio (MP3)", f"dl_audio:{platform}:{cache_hash}", style="primary", emoji_name="studio_mic"),
            make_btn("Size Converter", f"size_menu:{platform}:{cache_hash}", style="primary", emoji_name="sparkles")
        ],
        [
            make_btn("Close", "cmd_close", style="danger", emoji_name="trash")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_photo_downloader_keyboard(platform: str, cache_hash: str) -> InlineKeyboardMarkup:
    kb = [
        [
            make_btn("4K Ultra HD", f"dir_size:2160p:photo:{cache_hash}", style="success", emoji_name="glowing_star"),
            make_btn("1080p Full HD", f"dir_size:1080p:photo:{cache_hash}", style="primary", emoji_name="snowflake")
        ],
        [
            make_btn("1:1 Square (Post)", f"dir_size:1to1:photo:{cache_hash}", style="primary", emoji_name="check_box"),
            make_btn("9:16 Vertical (Story)", f"dir_size:9to16:photo:{cache_hash}", style="primary", emoji_name="selfie")
        ],
        [
            make_btn("Compress / Optimize", f"dir_size:compress:photo:{cache_hash}", style="primary", emoji_name="chart_up"),
            make_btn("Close", "cmd_close", style="danger", emoji_name="trash")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_size_converter_keyboard(platform: str, cache_hash: str) -> InlineKeyboardMarkup:
    kb = [
        [
            make_btn("4K Ultra HD (2160p)", f"size_set:2160p:{platform}:{cache_hash}", style="success", emoji_name="glowing_star"),
            make_btn("1080p Full HD", f"size_set:1080p:{platform}:{cache_hash}", style="primary", emoji_name="snowflake")
        ],
        [
            make_btn("720p HD", f"size_set:720p:{platform}:{cache_hash}", style="primary", emoji_name="fire"),
            make_btn("480p SD", f"size_set:480p:{platform}:{cache_hash}", style="primary", emoji_name="phone")
        ],
        [
            make_btn("1:1 Square (Feed)", f"size_set:1to1:{platform}:{cache_hash}", style="primary", emoji_name="check_box"),
            make_btn("9:16 Vertical (Reels)", f"size_set:9to16:{platform}:{cache_hash}", style="primary", emoji_name="selfie")
        ],
        [
            make_btn("Compress / Optimize", f"size_set:compress:{platform}:{cache_hash}", style="primary", emoji_name="chart_up"),
            make_btn("Back", f"size_back:{platform}:{cache_hash}", style="danger", emoji_name="back")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_direct_media_keyboard(media_type: str, cache_id: str) -> InlineKeyboardMarkup:
    if media_type == "photo":
        kb = [
            [
                make_btn("4K Ultra HD", f"dir_size:2160p:photo:{cache_id}", style="success", emoji_name="glowing_star"),
                make_btn("1080p Full HD", f"dir_size:1080p:photo:{cache_id}", style="primary", emoji_name="snowflake")
            ],
            [
                make_btn("1:1 Square (Post)", f"dir_size:1to1:photo:{cache_id}", style="primary", emoji_name="check_box"),
                make_btn("9:16 Vertical (Story)", f"dir_size:9to16:photo:{cache_id}", style="primary", emoji_name="selfie")
            ],
            [
                make_btn("Compress / Optimize", f"dir_size:compress:photo:{cache_id}", style="primary", emoji_name="chart_up"),
                make_btn("Close", "cmd_close", style="danger", emoji_name="trash")
            ]
        ]
    else:
        kb = [
            [
                make_btn("4K Ultra HD (2160p)", f"dir_size:2160p:video:{cache_id}", style="success", emoji_name="glowing_star"),
                make_btn("1080p Full HD", f"dir_size:1080p:video:{cache_id}", style="primary", emoji_name="snowflake")
            ],
            [
                make_btn("720p HD", f"dir_size:720p:video:{cache_id}", style="primary", emoji_name="fire"),
                make_btn("480p SD", f"dir_size:480p:video:{cache_id}", style="primary", emoji_name="phone")
            ],
            [
                make_btn("1:1 Square (Feed)", f"dir_size:1to1:video:{cache_id}", style="primary", emoji_name="check_box"),
                make_btn("9:16 Vertical (Reel)", f"dir_size:9to16:video:{cache_id}", style="primary", emoji_name="selfie")
            ],
            [
                make_btn("Voice Note (.ogg)", f"dir_voice:video:{cache_id}", style="primary", emoji_name="mic"),
                make_btn("Audio (MP3)", f"dir_audio:video:{cache_id}", style="primary", emoji_name="studio_mic")
            ],
            [
                make_btn("Compress / Optimize", f"dir_size:compress:video:{cache_id}", style="primary", emoji_name="chart_up"),
                make_btn("Close", "cmd_close", style="danger", emoji_name="trash")
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

DOWNLOAD_CACHE: Dict[str, Dict[str, Any]] = {}
DIRECT_MEDIA_CACHE: Dict[str, Dict[str, Any]] = {}

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            make_btn("Instagram", "prompt_insta", style="primary", emoji_name="fire"),
            make_btn("Pinterest", "prompt_pin", style="primary", emoji_name="zap")
        ],
        [
            make_btn("Snapchat", "prompt_snap", style="primary", emoji_name="glowing_star"),
            make_btn("Facebook Ads", "prompt_fb", style="primary", emoji_name="eye")
        ],
        [
            make_btn("Media Resizer & Converter Guide", "cmd_voice_guide", style="success", emoji_name="mic")
        ]
    ]
    if is_admin:
        buttons.append([make_btn("Admin Panel", "cmd_admin_panel", style="danger", emoji_name="crown")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

@start_router.message(CommandStart())
async def command_start_handler(message: Message, bot: Bot):
    user = message.from_user
    if not user:
        return

    is_admin = await is_admin_user(user.id)
    bot_info = await bot.get_me()
    keyboard = get_main_menu_keyboard(is_admin=is_admin)

    caption_text = (
        f"{get_p_emoji('fire')} <b>ADVANCED SOCIAL MEDIA DOWNLOADER &amp; MEDIA RESIZER</b> {get_p_emoji('fire')}\n\n"
        f"Welcome, <b>{user.first_name}</b>!\n\n"
        f"{get_p_emoji('zap')} <b>Features:</b>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('link')} <b>Download with Full Sound:</b> Send any link from Instagram, Pinterest, Snapchat, or Facebook.\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('insta')} <b>Photo &amp; Carousel Posts:</b> Full support for Instagram photos, albums &amp; Pinterest pins.\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('folder')} <b>Direct Media Converter:</b> Send ANY Video or Photo directly to resize to 4K, 1080p, 720p, 1:1 Square, or 9:16 Vertical!\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('studio_mic')} <b>Audio Extraction:</b> Convert any video into a Voice Note (.ogg) or MP3.\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('search')} <b>Inline Search Mode:</b> Type <code>@{bot_info.username} &lt;link&gt;</code> in any chat.\n\n"
        f"<i>Paste your video/photo link or send any media file below!</i>"
    )
    await safe_reply(message, caption_text, reply_markup=keyboard, photo=WELCOME_IMAGE)

@start_router.message(Command("help"))
async def command_help_handler(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = await is_admin_user(user_id)
    if is_admin:
        text = f"{get_user_help_guide()}\n\n{get_admin_help_guide()}"
    else:
        text = get_user_help_guide()
    await safe_reply(message, text)

@start_router.message(Command("stats"))
async def command_stats_handler(message: Message):
    stats = await db.get_system_stats()
    text = (
        f"{get_p_emoji('chart_up')} <b>LIVE DOWNLOADER STATISTICS</b> {get_p_emoji('chart_up')}\n\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('fire')} <b>Total Media Downloaded:</b> {stats['total_downloads']}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('glowing_star')} <b>Total Active Users:</b> {stats['total_users']}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('crown')} <b>Authorized Admins:</b> {stats['total_authorized']}\n\n"
        f"{get_p_emoji('chart_up')} <b>Platform Breakdown:</b>\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('insta')} Instagram: {stats['platforms']['instagram']}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('pin')} Pinterest: {stats['platforms']['pinterest']}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('snap')} Snapchat: {stats['platforms']['snapchat']}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('fb')} Facebook &amp; Meta Ads: {stats['platforms']['facebook']}\n\n"
        f"{get_p_emoji('check_mark')} <i>All Downloader APIs &amp; Audio Remuxer Engine Active!</i>"
    )
    await safe_reply(message, text)

def extract_urls(text: str) -> List[str]:
    """Extract all valid social media URLs from message text with markdown & bracket cleaning."""
    if hasattr(downloader, 'extract_urls'):
        try:
            res = downloader.extract_urls(text)
            if res:
                return res
        except Exception:
            pass
    urls = []
    clean_text = text.replace("[", " ").replace("]", " ").replace("(", " ").replace(")", " ").replace("<", " ").replace(">", " ")
    raw_urls = re.findall(r'https?://[^\s\'"<>\[\]\(\)]+', clean_text)
    for u in raw_urls:
        u = u.strip().rstrip(".,;!?:")
        p = downloader.detect_platform(u) if hasattr(downloader, 'detect_platform') else None
        if p and u not in urls:
            urls.append(u)
    return urls

# ==================== DOWNLOADER & MULTI-QUEUE ROUTER ====================
@downloader_router.message(F.text)
async def process_media_urls(message: Message, bot: Bot):
    text = message.text or ""
    urls = extract_urls(text)
    
    if not urls:
        return

    user_id = message.from_user.id
    total_urls = len(urls)

    if total_urls > 1:
        await message.answer(
            f"{get_p_emoji('zap')} <b>Multi-Downloading System Activated!</b>\n\n"
            f"Processing <b>{total_urls}</b> social media links...",
            parse_mode="HTML"
        )

    for idx, url in enumerate(urls, 1):
        platform = downloader.detect_platform(url)
        status_msg = await message.answer(
            f"{get_p_emoji('down')} <b>Downloading Media [{idx}/{total_urls}]</b>...\n"
            f"{get_p_emoji('bullet')} <b>Platform:</b> {platform.title() if platform else 'Social Media'}\n"
            f"{get_p_emoji('bullet')} <b>Quality:</b> Original Full HD / 4K\n"
            f"<i>Please wait a moment...</i>",
            parse_mode="HTML"
        )

        res = await downloader.download_media(url, force_local_download=True)

        if res.get("status") == "success":
            media_type = res.get("media_type", "video")
            video_url = res.get("video_url")
            image_url = res.get("image_url")
            local_file = res.get("local_file")
            media_list = res.get("media_list", [])
            title = res.get("title", f"{platform.title()} Media")
            width = res.get("width")
            height = res.get("height")
            duration = res.get("duration", 0)

            cache_hash = str(abs(hash(url)) % 1000000)
            cache_key = f"{platform}:{cache_hash}"

            DOWNLOAD_CACHE[cache_key] = {
                "url": url,
                "platform": platform,
                "video_url": video_url,
                "image_url": image_url,
                "local_file": local_file,
                "media_type": media_type,
                "title": title,
                "thumbnail": res.get("thumbnail"),
                "width": width,
                "height": height,
                "duration": duration
            }

            # 1. Handle Carousel / Album
            if media_type == "carousel" and media_list:
                group = []
                for m_idx, m_item in enumerate(media_list[:10]):
                    m_type = m_item.get("type", "photo")
                    m_url = m_item.get("url")
                    if m_type == "video":
                        group.append(InputMediaVideo(media=m_url, caption=f"{get_p_emoji('check_mark')} <b>{title} [{m_idx+1}/{len(media_list)}]</b>" if m_idx == 0 else "", parse_mode="HTML"))
                    else:
                        group.append(InputMediaPhoto(media=m_url, caption=f"{get_p_emoji('check_mark')} <b>{title} [{m_idx+1}/{len(media_list)}]</b>" if m_idx == 0 else "", parse_mode="HTML"))
                
                try:
                    await message.answer_media_group(media=group)
                    await status_msg.delete()
                except Exception as grp_err:
                    logger.warning(f"Carousel send error: {grp_err}")
                    for m_item in media_list[:5]:
                        if m_item.get("type") == "video":
                            await message.answer_video(video=URLInputFile(m_item["url"]), caption=f"{get_p_emoji('check_mark')} <b>Downloaded from {platform.title()}</b>", parse_mode="HTML")
                        else:
                            await message.answer_photo(photo=URLInputFile(m_item["url"]), caption=f"{get_p_emoji('check_mark')} <b>Downloaded from {platform.title()}</b>", parse_mode="HTML")
                    await status_msg.delete()

            # 2. Handle Single Photo
            elif media_type == "photo" or (image_url and not video_url):
                DIRECT_MEDIA_CACHE[cache_hash] = {
                    "file_id": None,
                    "url": image_url,
                    "local_file": local_file,
                    "type": "photo",
                    "user_id": user_id
                }
                photo_kb = get_photo_downloader_keyboard(platform, cache_hash)
                caption = (
                    f"{get_p_emoji('check_mark')} <b>Photo Downloaded Successfully!</b>\n\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('globe')} <b>Platform:</b> {platform.title()}\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('insta')} <b>Quality:</b> High Resolution Original\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('zap')} <b>Status:</b> Ready"
                )
                try:
                    if local_file and os.path.exists(local_file):
                        await message.answer_photo(
                            photo=FSInputFile(local_file),
                            caption=caption,
                            reply_markup=photo_kb,
                            parse_mode="HTML"
                        )
                    elif image_url:
                        await message.answer_photo(
                            photo=URLInputFile(image_url),
                            caption=caption,
                            reply_markup=photo_kb,
                            parse_mode="HTML"
                        )
                    await status_msg.delete()
                except Exception as p_err:
                    logger.warning(f"Photo send failed: {p_err}")
                    await status_msg.edit_text(caption, reply_markup=photo_kb, parse_mode="HTML")

            # 3. Handle Single Video
            else:
                keyboard = get_downloader_keyboard(url, platform, video_url or "", cache_hash)
                
                # Probe video metadata and generate native thumbnail
                w_probe, h_probe, dur_probe, thumb_file = (None, None, None, None)
                if local_file and os.path.exists(local_file):
                    w_probe, h_probe, dur_probe, thumb_file = downloader.get_video_metadata_and_thumb(local_file)

                final_w = w_probe or width
                final_h = h_probe or height
                final_dur = dur_probe or duration

                caption = (
                    f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('globe')} <b>Platform:</b> {platform.title()}\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('sound')} <b>Sound:</b> High Quality Audio Included\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('tv')} <b>Resolution:</b> {final_w}x{final_h if final_h else 'Original'}\n"
                    f"{get_p_emoji('bullet')} {get_p_emoji('zap')} <b>Status:</b> Ready"
                )

                try:
                    temp_dir = tempfile.gettempdir()
                    target_video_file = local_file

                    # If local file is missing or not downloaded, download it locally first to bypass CDN 403 Forbidden
                    if (not target_video_file or not os.path.exists(target_video_file)) and video_url:
                        fallback_path = os.path.join(temp_dir, f"dl_{cache_hash}_{int(time.time())}.mp4")
                        if await downloader.download_url_to_file(video_url, fallback_path):
                            target_video_file = fallback_path
                            w_p, h_p, dur_p, t_p = downloader.get_video_metadata_and_thumb(fallback_path)
                            final_w = w_p or final_w
                            final_h = h_p or final_h
                            final_dur = dur_p or final_dur
                            if t_p and os.path.exists(t_p):
                                thumb_file = t_p

                    if target_video_file and os.path.exists(target_video_file) and os.path.getsize(target_video_file) > 1024:
                        thumb_input = FSInputFile(thumb_file) if (thumb_file and os.path.exists(thumb_file)) else None
                        await message.answer_video(
                            video=FSInputFile(target_video_file),
                            caption=caption,
                            thumbnail=thumb_input,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                            supports_streaming=True,
                            width=int(final_w) if final_w else None,
                            height=int(final_h) if final_h else None,
                            duration=int(final_dur) if final_dur else None
                        )
                        if thumb_file and os.path.exists(thumb_file):
                            try: os.remove(thumb_file)
                            except Exception: pass
                    elif video_url:
                        await message.answer_video(
                            video=URLInputFile(video_url),
                            caption=caption,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                            supports_streaming=True,
                            width=int(final_w) if final_w else None,
                            height=int(final_h) if final_h else None,
                            duration=int(final_dur) if final_dur else None
                        )
                    await status_msg.delete()
                except Exception as v_err:
                    logger.warning(f"Video send failed: {v_err}")
                    await status_msg.edit_text(caption, reply_markup=keyboard, parse_mode="HTML")

            await db.log_download_request(user_id, platform, url, status="success", title=title)

            if LOG_CHANNEL_ID:
                try:
                    log_text = (
                        f"{get_p_emoji('down')} <b>NEW DOWNLOAD REQUEST</b>\n"
                        f"{get_p_emoji('bullet')} {get_p_emoji('user')} <b>User:</b> {message.from_user.full_name} (<code>{user_id}</code>)\n"
                        f"{get_p_emoji('bullet')} {get_p_emoji('globe')} <b>Platform:</b> {platform.title()}\n"
                        f"{get_p_emoji('bullet')} {get_p_emoji('link')} <b>URL:</b> {url}\n"
                        f"{get_p_emoji('bullet')} {get_p_emoji('time')} <b>Time:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                    )
                    await bot.send_message(LOG_CHANNEL_ID, log_text, parse_mode="HTML")
                except Exception as log_err:
                    logger.warning(f"Could not send log to channel: {log_err}")

        else:
            err_msg = res.get("message", "Unable to download media.")
            await status_msg.edit_text(
                f"{get_p_emoji('trash')} <b>Download Failed [{idx}/{total_urls}]</b>\n\n"
                f"{get_p_emoji('bullet')} <b>Platform:</b> {platform.title() if platform else 'Unknown'}\n"
                f"{get_p_emoji('bullet')} <b>Error:</b> {err_msg}\n\n"
                f"<i>Tip: Check if the link is public or try again.</i>",
                parse_mode="HTML"
            )
            await db.log_download_request(user_id, platform or "unknown", url, status="error")

# ==================== DIRECT MEDIA HANDLERS (VIDEO & PHOTO) ====================
@downloader_router.message(F.video | F.animation | (F.document & F.document.mime_type.startswith("video/")))
async def handle_direct_video_upload(message: Message, bot: Bot):
    video_obj = message.video or message.animation or message.document
    file_id = video_obj.file_id
    file_unique_id = video_obj.file_unique_id
    
    file_size_mb = round((video_obj.file_size or 0) / (1024 * 1024), 2)
    w = getattr(video_obj, "width", 0)
    h = getattr(video_obj, "height", 0)
    dur = getattr(video_obj, "duration", 0)

    DIRECT_MEDIA_CACHE[file_unique_id] = {
        "file_id": file_id,
        "type": "video",
        "size_mb": file_size_mb,
        "width": w,
        "height": h,
        "duration": dur,
        "user_id": message.from_user.id
    }

    keyboard = get_direct_media_keyboard("video", file_unique_id)
    text = (
        f"{get_p_emoji('sparkles')} <b>DIRECT VIDEO RECEIVED ── RESIZE &amp; CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('tv')} <b>Current Resolution:</b> {w}x{h}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('box')} <b>File Size:</b> {file_size_mb} MB\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('time')} <b>Duration:</b> {dur}s\n\n"
        f"Select your desired resolution, aspect ratio, or audio extraction below:"
    )
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

@downloader_router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def handle_direct_photo_upload(message: Message, bot: Bot):
    if message.photo:
        photo_obj = message.photo[-1]
        file_id = photo_obj.file_id
        file_unique_id = photo_obj.file_unique_id
        w = photo_obj.width
        h = photo_obj.height
        file_size_mb = round((photo_obj.file_size or 0) / (1024 * 1024), 2)
    else:
        doc = message.document
        file_id = doc.file_id
        file_unique_id = doc.file_unique_id
        w, h = 0, 0
        file_size_mb = round((doc.file_size or 0) / (1024 * 1024), 2)

    DIRECT_MEDIA_CACHE[file_unique_id] = {
        "file_id": file_id,
        "type": "photo",
        "size_mb": file_size_mb,
        "width": w,
        "height": h,
        "user_id": message.from_user.id
    }

    keyboard = get_direct_media_keyboard("photo", file_unique_id)
    text = (
        f"{get_p_emoji('sparkles')} <b>IMAGE RECEIVED ── RESIZE &amp; CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('insta')} <b>Current Size:</b> {w}x{h if h else 'Auto'}\n"
        f"{get_p_emoji('bullet')} {get_p_emoji('box')} <b>File Size:</b> {file_size_mb} MB\n\n"
        f"Select your desired output resolution or crop format below:"
    )
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

# ==================== CALLBACK ROUTER ====================
@callback_router.callback_query(F.data.startswith("prompt_") | F.data.startswith("info_"))
async def handle_platform_prompt(callback: CallbackQuery, bot: Bot):
    platform_key = callback.data.split("_")[1]
    prompt_map = {
        "insta": ("Instagram Video &amp; Photo Downloader", "Send your Instagram Reel, Post, Photo, or Story link below!"),
        "pin": ("Pinterest Video &amp; Photo Downloader", "Send your Pinterest Pin or video clip link below!"),
        "snap": ("Snapchat Spotlight Downloader", "Send your Snapchat Spotlight or Story link below!"),
        "fb": ("Facebook &amp; Meta Ads Downloader", "Send your Facebook Reel, Watch, or Meta Ad video link below!")
    }
    title, prompt_desc = prompt_map.get(platform_key, ("Video Downloader", "Send your social media video/photo link below!"))
    await callback.answer()
    await callback.message.answer(
        f"{get_p_emoji('zap')} <b>{title}</b>\n\n"
        f"<i>{prompt_desc}</i>\n"
        f"{get_p_emoji('bullet')} Guaranteed 100% full audio track\n"
        f"{get_p_emoji('bullet')} Highest resolution available (up to 4K)",
        parse_mode="HTML"
    )

@callback_router.callback_query(F.data == "cmd_voice_guide")
async def handle_voice_guide_callback(callback: CallbackQuery):
    await callback.answer()
    guide_text = (
        f"{get_p_emoji('studio_mic')} <b><u>ADVANCED MEDIA RESIZER &amp; AUDIO EXTRACTOR GUIDE</u></b> {get_p_emoji('studio_mic')}\n\n"
        f"{get_p_emoji('bullet')} <b>Download with Sound:</b> Send any video link from Instagram, Pinterest, Snapchat, or Facebook. The bot downloads high quality 1080p/4K with complete audio!\n\n"
        f"{get_p_emoji('bullet')} <b>Send Any Video or Photo:</b> Send any video or image directly to this chat, and choose 4K, 1080p, 720p, 1:1 Square (Instagram Feed), or 9:16 Vertical (Reel/Story) format!\n\n"
        f"{get_p_emoji('bullet')} <b>Extract Voice Note:</b> Click 'Voice Note (.ogg)' to receive an instant playable voice message waveform.\n"
        f"{get_p_emoji('bullet')} <b>Extract MP3 Audio:</b> Click 'Audio (MP3)' to download pure crystal clear music/soundtrack."
    )
    await callback.message.answer(guide_text, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_close")
async def handle_close_button(callback: CallbackQuery):
    await callback.answer("Closed.")
    try:
        await callback.message.delete()
    except Exception:
        pass

@callback_router.callback_query(F.data.startswith("dl_"))
async def handle_download_action_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    parts = data.split(":")
    action = parts[0]
    platform = parts[1] if len(parts) > 1 else "video"
    cache_hash = parts[2] if len(parts) > 2 else "0"
    cache_key = f"{platform}:{cache_hash}"

    cached_item = DOWNLOAD_CACHE.get(cache_key)

    if action == "dl_vid":
        await callback.answer("⚡️ Sending Video with Full Stereo Sound...", show_alert=False)
        if cached_item:
            video_url = cached_item.get("video_url")
            local_file = cached_item.get("local_file")
            try:
                if local_file and os.path.exists(local_file):
                    w, h, dur, thumb_file = downloader.get_video_metadata_and_thumb(local_file)
                    thumb_input = FSInputFile(thumb_file) if (thumb_file and os.path.exists(thumb_file)) else None
                    await callback.message.answer_video(
                        video=FSInputFile(local_file),
                        thumbnail=thumb_input,
                        caption=f"{get_p_emoji('check_mark')} <b>Downloaded with Full Stereo Sound!</b>",
                        supports_streaming=True,
                        parse_mode="HTML"
                    )
                    if thumb_file and os.path.exists(thumb_file):
                        try: os.remove(thumb_file)
                        except Exception: pass
                elif video_url:
                    await callback.message.answer_video(
                        video=URLInputFile(video_url),
                        caption=f"{get_p_emoji('check_mark')} <b>Downloaded with Full Stereo Sound!</b>",
                        supports_streaming=True,
                        parse_mode="HTML"
                    )
            except Exception as e:
                await callback.message.answer(
                    f"{get_p_emoji('link')} <b>Direct Video Link:</b>\n{video_url}",
                    parse_mode="HTML"
                )

    elif action == "dl_voice" or action == "dl_audio":
        await callback.answer("Extracting Audio...", show_alert=True)
        if cached_item:
            media_url = cached_item.get("video_url")
            local_file = cached_item.get("local_file")
            
            temp_dir = tempfile.gettempdir()
            input_video = local_file
            
            if not input_video or not os.path.exists(input_video):
                input_video = os.path.join(temp_dir, f"in_{callback.from_user.id}_{int(time.time())}.mp4")
                if media_url:
                    await downloader.download_url_to_file(media_url, input_video)

            if input_video and os.path.exists(input_video):
                is_voice = (action == "dl_voice")
                ext = ".ogg" if is_voice else ".mp3"
                out_audio = os.path.join(temp_dir, f"out_{callback.from_user.id}_{int(time.time())}{ext}")
                
                success = await downloader.extract_audio_from_media(input_video, out_audio, is_voice=is_voice)
                if success and os.path.exists(out_audio):
                    if is_voice:
                        await callback.message.answer_voice(
                            voice=FSInputFile(out_audio),
                            caption=f"{get_p_emoji('mic')} <b>Voice Note Extracted!</b>",
                            parse_mode="HTML"
                        )
                    else:
                        await callback.message.answer_audio(
                            audio=FSInputFile(out_audio),
                            title=cached_item.get('title', 'Extracted Audio'),
                            caption=f"{get_p_emoji('studio_mic')} <b>High Quality MP3 Audio!</b>",
                            parse_mode="HTML"
                        )
                    try:
                        os.remove(out_audio)
                    except Exception:
                        pass
                else:
                    await callback.answer("Could not extract audio from this stream.", show_alert=True)

# ==================== SIZE CONVERTER ENGINE CALLBACKS ====================
@callback_router.callback_query(F.data.startswith("size_"))
async def handle_size_converter_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    parts = data.split(":")
    action = parts[0]
    
    if action == "size_menu":
        platform = parts[1] if len(parts) > 1 else "video"
        cache_hash = parts[2] if len(parts) > 2 else "0"
        kb = get_size_converter_keyboard(platform, cache_hash)
        text = (
            f"{get_p_emoji('sparkles')} <b>MEDIA SIZE &amp; RESOLUTION CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
            f"Select your desired output resolution or aspect ratio format below:"
        )
        await callback.answer()
        try:
            await callback.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")

    elif action == "size_set":
        target_mode = parts[1]
        platform = parts[2] if len(parts) > 2 else "video"
        cache_hash = parts[3] if len(parts) > 3 else "0"
        cache_key = f"{platform}:{cache_hash}"

        cached_item = DOWNLOAD_CACHE.get(cache_key)
        if not cached_item:
            await callback.answer("Media session expired. Please re-send link.", show_alert=True)
            return

        await callback.answer(f"Converting to {target_mode.upper()} with audio...", show_alert=False)
        proc_msg = await callback.message.answer(
            f"{get_p_emoji('gear')} <b>Converting Media to {target_mode.upper()}...</b>\n"
            f"<i>Applying hardware encoding &amp; preserving sound track...</i>",
            parse_mode="HTML"
        )

        temp_dir = tempfile.gettempdir()
        input_file = cached_item.get("local_file")
        
        if not input_file or not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
            input_file = os.path.join(temp_dir, f"conv_in_{cache_hash}.mp4")
            url = cached_item.get("url")
            v_url = cached_item.get("video_url")
            
            if url:
                dl_res = await downloader.fallback_ytdlp_downloader(url, download_file=True)
                if dl_res and dl_res.get("local_file"):
                    input_file = dl_res["local_file"]
            elif v_url:
                await downloader.download_url_to_file(v_url, input_file)

        if not os.path.exists(input_file):
            await proc_msg.edit_text(f"{get_p_emoji('cross')} Failed to retrieve original stream for conversion.")
            return

        output_file = os.path.join(temp_dir, f"conv_out_{target_mode}_{int(time.time())}.mp4")
        success, err = await downloader.convert_video_media(input_file, output_file, target_mode)

        if success and os.path.exists(output_file):
            w_p, h_p, dur_p, thumb_p = downloader.get_video_metadata_and_thumb(output_file)
            thumb_inp = FSInputFile(thumb_p) if (thumb_p and os.path.exists(thumb_p)) else None
            caption = (
                f"{get_p_emoji('check_mark')} <b>Conversion Complete!</b>\n\n"
                f"{get_p_emoji('bullet')} <b>Target Format:</b> {target_mode.upper()}\n"
                f"{get_p_emoji('bullet')} {get_p_emoji('sound')} <b>Sound:</b> Original Stereo Audio Preserved\n"
                f"{get_p_emoji('bullet')} {get_p_emoji('zap')} <b>Engine:</b> High Quality Fast Remux"
            )
            await callback.message.answer_video(
                video=FSInputFile(output_file),
                thumbnail=thumb_inp,
                caption=caption,
                parse_mode="HTML",
                supports_streaming=True,
                width=int(w_p) if w_p else None,
                height=int(h_p) if h_p else None
            )
            if thumb_p and os.path.exists(thumb_p):
                try: os.remove(thumb_p)
                except Exception: pass
            await proc_msg.delete()
            try:
                os.remove(output_file)
            except Exception:
                pass
        else:
            await proc_msg.edit_text(f"{get_p_emoji('cross')} Conversion failed: {err or 'Unknown error'}")

    elif action == "size_back":
        platform = parts[1] if len(parts) > 1 else "video"
        cache_hash = parts[2] if len(parts) > 2 else "0"
        cache_key = f"{platform}:{cache_hash}"
        cached_item = DOWNLOAD_CACHE.get(cache_key, {})
        
        kb = get_downloader_keyboard(
            cached_item.get("url", ""),
            platform,
            cached_item.get("video_url", ""),
            cache_hash
        )
        caption = (
            f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
            f"{get_p_emoji('bullet')} {get_p_emoji('globe')} <b>Platform:</b> {platform.title()}\n"
            f"{get_p_emoji('bullet')} {get_p_emoji('sound')} <b>Sound:</b> High Quality Audio Included\n"
            f"{get_p_emoji('bullet')} {get_p_emoji('zap')} <b>Status:</b> Ready"
        )
        await callback.answer()
        try:
            await callback.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(text=caption, reply_markup=kb, parse_mode="HTML")

# ==================== DIRECT MEDIA CONVERTER CALLBACKS ====================
@callback_router.callback_query(F.data.startswith("dir_"))
async def handle_direct_converter_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    parts = data.split(":")
    action = parts[0]
    
    if action == "dir_size":
        target_mode = parts[1]
        media_type = parts[2]
        cache_id = parts[3]
        
        cached_item = DIRECT_MEDIA_CACHE.get(cache_id)
        if not cached_item:
            await callback.answer("Media session expired. Please re-send file.", show_alert=True)
            return

        await callback.answer(f"Processing {target_mode.upper()}...", show_alert=False)
        proc_msg = await callback.message.answer(
            f"{get_p_emoji('gear')} <b>Processing Direct Media to {target_mode.upper()}...</b>\n"
            f"<i>Applying hardware filter and format adjustments...</i>",
            parse_mode="HTML"
        )

        temp_dir = tempfile.gettempdir()
        file_id = cached_item.get("file_id")
        in_path = cached_item.get("local_file")

        if not in_path or not os.path.exists(in_path):
            if file_id:
                tg_file = await bot.get_file(file_id)
                in_path = os.path.join(temp_dir, f"dir_in_{cache_id}_{int(time.time())}")
                await bot.download_file(tg_file.file_path, in_path)
            elif cached_item.get("url"):
                in_path = os.path.join(temp_dir, f"dir_in_{cache_id}_{int(time.time())}")
                await downloader.download_url_to_file(cached_item["url"], in_path)

        if not in_path or not os.path.exists(in_path):
            await proc_msg.edit_text(f"{get_p_emoji('cross')} Failed to access media file.")
            return

        if media_type == "photo":
            out_path = os.path.join(temp_dir, f"dir_out_{cache_id}_{int(time.time())}.jpg")
            success, err = await downloader.convert_image_media(in_path, out_path, target_mode)
            if success and os.path.exists(out_path):
                caption = f"{get_p_emoji('check_mark')} <b>Image Formatted to {target_mode.upper()} Successfully!</b>"
                await callback.message.answer_photo(photo=FSInputFile(out_path), caption=caption, parse_mode="HTML")
                await proc_msg.delete()
                try: os.remove(out_path)
                except Exception: pass
            else:
                await proc_msg.edit_text(f"{get_p_emoji('cross')} Image resizing failed: {err}")
        else: # Video
            out_path = os.path.join(temp_dir, f"dir_out_{cache_id}_{int(time.time())}.mp4")
            success, err = await downloader.convert_video_media(in_path, out_path, target_mode)
            if success and os.path.exists(out_path):
                w_p, h_p, dur_p, thumb_p = downloader.get_video_metadata_and_thumb(out_path)
                thumb_inp = FSInputFile(thumb_p) if (thumb_p and os.path.exists(thumb_p)) else None
                caption = f"{get_p_emoji('check_mark')} <b>Video Resized to {target_mode.upper()} with Full Audio!</b>"
                await callback.message.answer_video(
                    video=FSInputFile(out_path),
                    thumbnail=thumb_inp,
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    width=int(w_p) if w_p else None,
                    height=int(h_p) if h_p else None
                )
                if thumb_p and os.path.exists(thumb_p):
                    try: os.remove(thumb_p)
                    except Exception: pass
                await proc_msg.delete()
                try: os.remove(out_path)
                except Exception: pass
            else:
                await proc_msg.edit_text(f"{get_p_emoji('cross')} Video resizing failed: {err}")

    elif action == "dir_voice" or action == "dir_audio":
        media_type = parts[1]
        cache_id = parts[2]
        cached_item = DIRECT_MEDIA_CACHE.get(cache_id)
        if not cached_item:
            await callback.answer("Media session expired. Please re-send file.", show_alert=True)
            return

        await callback.answer("Extracting sound...", show_alert=True)
        temp_dir = tempfile.gettempdir()
        file_id = cached_item["file_id"]
        
        tg_file = await bot.get_file(file_id)
        in_path = os.path.join(temp_dir, f"dir_audio_in_{cache_id}_{int(time.time())}.mp4")
        await bot.download_file(tg_file.file_path, in_path)

        is_voice = (action == "dir_voice")
        ext = ".ogg" if is_voice else ".mp3"
        out_audio = os.path.join(temp_dir, f"dir_audio_out_{cache_id}_{int(time.time())}{ext}")

        success = await downloader.extract_audio_from_media(in_path, out_audio, is_voice=is_voice)
        if success and os.path.exists(out_audio):
            if is_voice:
                await callback.message.answer_voice(
                    voice=FSInputFile(out_audio),
                    caption=f"{get_p_emoji('mic')} <b>Voice Note Extracted!</b>",
                    parse_mode="HTML"
                )
            else:
                await callback.message.answer_audio(
                    audio=FSInputFile(out_audio),
                    caption=f"{get_p_emoji('studio_mic')} <b>High Quality MP3 Audio!</b>",
                    parse_mode="HTML"
                )
            try: os.remove(out_audio)
            except Exception: pass
        else:
            await callback.message.answer(f"{get_p_emoji('cross')} Audio extraction failed.")

        try: os.remove(in_path)
        except Exception: pass

# ==================== ADMIN PANEL & COMMANDS ====================
@admin_router.message(Command("grant"))
async def admin_grant_handler(message: Message):
    if not await is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply(f"{get_p_emoji('cross')} Usage: <code>/grant &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.grant_user_access(target_id, message.from_user.id)
    await message.reply(f"{get_p_emoji('crown')} <b>User {target_id} has been granted Admin Access!</b>", parse_mode="HTML")

@admin_router.message(Command("revoke"))
async def admin_revoke_handler(message: Message):
    if not await is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.reply(f"{get_p_emoji('cross')} Usage: <code>/revoke &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.revoke_user_access(target_id)
    await message.reply(f"{get_p_emoji('cross')} <b>User {target_id} admin privileges revoked.</b>", parse_mode="HTML")

@admin_router.message(Command("logs"))
async def admin_logs_handler(message: Message):
    if not await is_admin_user(message.from_user.id):
        return
    logs = await db.get_recent_download_logs(limit=10)
    if not logs:
        await message.reply(f"{get_p_emoji('clipboard')} No download logs recorded yet.")
        return
    
    log_text = f"{get_p_emoji('clipboard')} <b>RECENT DOWNLOAD REQUEST LOGS</b> {get_p_emoji('clipboard')}\n\n"
    for l in logs:
        status_tag = get_p_emoji("check_box") if l.get("status") == "success" else get_p_emoji("cross")
        dt_str = l.get("downloaded_at", "N/A")
        if "T" in str(dt_str):
            dt_str = dt_str.split("T")[0] + " " + dt_str.split("T")[1][:5]
        log_text += f"{status_tag} <b>{l.get('platform', 'N/A').title()}</b> | User: <code>{l.get('user_id')}</code> | {dt_str}\n"
    await message.reply(log_text, parse_mode="HTML")

@admin_router.message(Command("addemoji"))
async def admin_add_emoji_handler(message: Message):
    if not await is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply(f"{get_p_emoji('cross')} Usage: <code>/addemoji &lt;name&gt; &lt;emoji_id&gt;</code>", parse_mode="HTML")
        return
    name = parts[1].lower()
    emoji_id = parts[2]
    await db.save_custom_emoji(name, emoji_id, updated_by=message.from_user.id)
    config.update_emoji_cache(name, "✨", emoji_id)
    await message.reply(f"{get_p_emoji('sparkles')} <b>Custom Emoji Saved & Cached!</b>\n• Name: <code>{name}</code>\n• ID: <code>{emoji_id}</code>", parse_mode="HTML")

@admin_router.message(Command("emojis"))
async def admin_view_emojis_handler(message: Message):
    if not await is_admin_user(message.from_user.id):
        return
    emojis_list = await db.get_all_custom_emojis()
    if not emojis_list:
        await message.reply(f"{get_p_emoji('diamond')} No custom MongoDB emojis saved. Using default premium set.")
        return
    text = f"{get_p_emoji('diamond')} <b>CUSTOM PREMIUM EMOJIS CONFIGURED:</b>\n\n"
    for item in emojis_list:
        name = item.get("name", "unknown")
        eid = item.get("emoji_id", "")
        char = item.get("char", "✨")
        text += f"{get_p_emoji('bullet')} {char} <b>{name}</b>: <code>{eid}</code>\n"
    await message.reply(text, parse_mode="HTML")

@admin_router.message(Command("broadcast"))
async def admin_broadcast_handler(message: Message, bot: Bot):
    if not await is_admin_user(message.from_user.id):
        return
    
    reply_msg = message.reply_to_message
    if not reply_msg:
        await message.reply(f"{get_p_emoji('cross')} Please reply to a message you want to broadcast to all users with <code>/broadcast</code>", parse_mode="HTML")
        return

    users = await db.get_all_users()
    total = len(users)
    sent = 0
    failed = 0

    status_msg = await message.reply(f"{get_p_emoji('zap')} Starting broadcast to <b>{total}</b> users...", parse_mode="HTML")

    for u in users:
        uid = u.get("user_id")
        if not uid:
            continue
        try:
            await reply_msg.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"{get_p_emoji('check_mark')} <b>Broadcast Completed!</b>\n\n"
        f"{get_p_emoji('bullet')} Total Users: {total}\n"
        f"{get_p_emoji('bullet')} Successfully Sent: {sent}\n"
        f"{get_p_emoji('bullet')} Failed / Blocked: {failed}",
        parse_mode="HTML"
    )

# ==================== INLINE QUERY ROUTER ====================
@inline_router.inline_query()
async def inline_query_handler(inline_query: InlineQuery, bot: Bot):
    query = inline_query.query.strip()
    if not query:
        return

    urls = downloader.extract_urls(query)
    if not urls:
        return

    url = urls[0]
    platform = downloader.detect_platform(url)
    res = await downloader.download_media(url, force_local_download=False)

    results = []
    if res.get("status") == "success" and (res.get("video_url") or res.get("image_url")):
        media_url = res.get("video_url") or res.get("image_url")
        thumb = res.get("thumbnail") or WELCOME_IMAGE
        title = res.get("title", f"{platform.title()} Media")

        if res.get("video_url"):
            results.append(
                InlineQueryResultVideo(
                    id=f"vid_{abs(hash(url)) % 100000}",
                    video_url=media_url,
                    mime_type="video/mp4",
                    thumbnail_url=thumb,
                    title=f"Download {platform.title()} Video",
                    description="High Quality Video with Complete Sound",
                    caption=f"{get_p_emoji('check_mark')} <b>{title}</b>\n\n<i>Downloaded with @{(await bot.get_me()).username}</i>",
                    parse_mode="HTML"
                )
            )
    else:
        results.append(
            InlineQueryResultArticle(
                id=f"err_{abs(hash(url)) % 100000}",
                title=f"Download Failed for {platform.title() if platform else 'Media'}",
                input_message_content=InputTextMessageContent(
                    message_text=f"{get_p_emoji('cross')} Unable to fetch media from link: {url}",
                    parse_mode="HTML"
                )
            )
        )

    await inline_query.answer(results, cache_time=10, is_personal=True)

# ==================== MAIN INITIALIZATION ====================
async def main():
    logger.info("🚀 Starting Social Media Video & Photo Downloader & Media Resizer Bot...")
    
    # Initialize MongoDB & Load custom emojis
    await db.init_db()
    try:
        saved_emojis = await db.get_all_custom_emojis()
        for e in saved_emojis:
            name = e.get("name")
            eid = e.get("emoji_id")
            char = e.get("char", "✨")
            if name and eid:
                config.update_emoji_cache(name, char, eid)
        if saved_emojis:
            logger.info(f"Loaded {len(saved_emojis)} custom premium emojis from MongoDB.")
    except Exception as e_err:
        logger.warning(f"Error loading custom emojis: {e_err}")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Outer Middleware for tracking user activity without blocking routers
    dp.message.outer_middleware(UserActivityMiddleware())

    # Include Routers
    dp.include_router(start_router)
    dp.include_router(downloader_router)
    dp.include_router(callback_router)
    dp.include_router(emoji_router)
    dp.include_router(admin_router)
    dp.include_router(inline_router)

    # Start Polling
    logger.info("✅ Bot is online & listening for commands & media uploads!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
