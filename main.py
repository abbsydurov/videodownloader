import asyncio
import logging
import os
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
    FSInputFile, TelegramObject
)
from aiogram.exceptions import TelegramAPIError

from config import (
    BOT_TOKEN, SUPER_ADMIN_ID, SUPER_ADMIN_IDS, LOG_CHANNEL_ID, WELCOME_IMAGE,
    get_p_emoji, get_btn_emoji, get_btn_emoji_id, logger
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

USER_HELP_GUIDE = (
    "★ <b><u>Sᴏᴄɪᴀʟ Mᴇᴅɪᴀ Vɪᴅᴇᴏ Dᴏᴡɴʟᴏᴀᴅᴇʀ & Mᴇᴅɪᴀ Rᴇsɪᴢᴇʀ Gᴜɪᴅᴇ</u></b> ★\n\n"
    "✨ <b>Sᴜᴘᴘᴏʀᴛᴇᴅ Pʟᴀᴛғᴏʀᴍs:</b>\n"
    "• 📸 <b>Instagram</b> ── <i>Reels, Posts, IGTV, Stories</i>\n"
    "• 📌 <b>Pinterest</b> ── <i>Pins & Video clips</i>\n"
    "• 👻 <b>Snapchat</b> ── <i>Spotlight & Stories</i>\n"
    "• 📘 <b>Facebook</b> ── <i>Reels, Videos & Meta Ads</i>\n\n"
    "⚡️ <b>Hᴏᴡ Tᴏ Usᴇ:</b>\n"
    "1️⃣ <b>Download with Sound:</b> Send any video link to download with 100% full audio track.\n"
    "2️⃣ <b>Direct Media Resizer:</b> Send ANY Video or Photo directly to resize, convert to 4K / 1080p / 720p, 1:1 Square, or 9:16 Vertical!\n"
    "3️⃣ <b>Voice Note & Audio:</b> Convert any video into a Telegram Voice Note (.ogg) or MP3.\n\n"
    "📦 <b>Mᴜʟᴛɪ-Dᴏᴡɴʟᴏᴀᴅɪɴɢ:</b> Paste multiple video links together in one message!\n"
    "🔎 <b>Iɴʟɪɴᴇ Sᴇᴀʀᴄʜ Mᴏᴅᴇ:</b> Type <code>@botusername &lt;link&gt;</code> in any Telegram chat."
)

ADMIN_HELP_GUIDE = (
    "★ <b><u>👑 Aᴅᴍɪɴ Cᴏɴᴛʀᴏʟ Gᴜɪᴅᴇ</u></b> ★\n\n"
    "• <code>/stats</code> ── <i>Live platform download statistics & user counts</i>\n"
    "• <code>/logs</code> ── <i>View recent system download logs from MongoDB</i>\n"
    "• <code>/grant &lt;user_id&gt;</code> ── <i>Grant admin authorization</i>\n"
    "• <code>/revoke &lt;user_id&gt;</code> ── <i>Revoke admin access</i>\n"
    "• <code>/addemoji &lt;name&gt; &lt;id&gt;</code> ── <i>Upload custom premium emoji ID</i>\n"
    "• <code>/emojis</code> ── <i>View all saved custom emoji IDs</i>\n"
    "• <code>/broadcast</code> ── <i>Send announcement to all registered users</i>"
)

# Helper function to generate styled inline buttons with colors and custom emoji icons
def make_btn(text: str, callback_data: str, style: str = "primary", emoji_name: str = None) -> InlineKeyboardButton:
    kwargs = {
        "text": text,
        "callback_data": callback_data,
        "style": style
    }
    if emoji_name:
        emoji_id = get_btn_emoji_id(emoji_name)
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        else:
            kwargs["text"] = f"{get_btn_emoji(emoji_name)} {text}"
    return InlineKeyboardButton(**kwargs)

def get_downloader_keyboard(url: str, platform: str, video_url: str, cache_hash: str) -> InlineKeyboardMarkup:
    kb = [
        [
            make_btn("Video (Full Sound 4K)", f"dl_vid:{platform}:{cache_hash}", style="success", emoji_name="fire"),
            make_btn("Voice Note (.ogg)", f"dl_voice:{platform}:{cache_hash}", style="primary", emoji_name="mic")
        ],
        [
            make_btn("Audio (MP3)", f"dl_audio:{platform}:{cache_hash}", style="primary", emoji_name="studio_mic"),
            make_btn("📐 Size Converter", f"size_menu:{platform}:{cache_hash}", style="primary", emoji_name="sparkles")
        ],
        [
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
    else: # Video or document video
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

# Store download cache for callbacks
DOWNLOAD_CACHE: Dict[str, Dict[str, Any]] = {}
DIRECT_MEDIA_CACHE: Dict[str, Dict[str, Any]] = {}

# ==================== START & HELP ROUTER ====================
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
        f"{get_p_emoji('fire')} <b>ADVANCED SOCIAL MEDIA DOWNLOADER & MEDIA RESIZER</b> {get_p_emoji('fire')}\n\n"
        f"Welcome, <b>{user.first_name}</b>!\n\n"
        f"⚡️ <b>Features:</b>\n"
        f"• 🔗 <b>Download with Full Sound:</b> Send any link from Instagram, Pinterest, Snapchat, or Facebook.\n"
        f"• 📁 <b>Direct Media Converter:</b> Send ANY Video or Photo directly to resize to 4K, 1080p, 720p, 1:1 Square, or 9:16 Vertical!\n"
        f"• 🎙 <b>Audio Extraction:</b> Convert any video into a Voice Note (.ogg) or MP3.\n"
        f"• 🔎 <b>Inline Search Mode:</b> Type <code>@{bot_info.username} &lt;link&gt;</code> in any chat.\n\n"
        f"<i>Paste your video link or send any media file below!</i>"
    )
    try:
        await message.answer_photo(photo=WELCOME_IMAGE, caption=caption_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await message.answer(caption_text, reply_markup=keyboard, parse_mode="HTML")

@start_router.message(Command("help"))
async def command_help_handler(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = await is_admin_user(user_id)
    if is_admin:
        text = f"{USER_HELP_GUIDE}\n\n{ADMIN_HELP_GUIDE}"
    else:
        text = USER_HELP_GUIDE
    await message.answer(text, parse_mode="HTML")

@start_router.message(Command("stats"))
async def command_stats_handler(message: Message):
    stats = await db.get_system_stats()
    text = (
        f"{get_p_emoji('chart_up')} <b>LIVE DOWNLOADER STATISTICS</b> {get_p_emoji('chart_up')}\n\n"
        f"• {get_p_emoji('fire')} <b>Total Media Downloaded:</b> {stats['total_downloads']}\n"
        f"• {get_p_emoji('glowing_star')} <b>Total Active Users:</b> {stats['total_users']}\n"
        f"• {get_p_emoji('crown')} <b>Authorized Admins:</b> {stats['total_authorized']}\n\n"
        f"📊 <b>Platform Breakdown:</b>\n"
        f"📸 Instagram Downloads: {stats['platforms']['instagram']}\n"
        f"📌 Pinterest Downloads: {stats['platforms']['pinterest']}\n"
        f"👻 Snapchat Downloads: {stats['platforms']['snapchat']}\n"
        f"📘 Facebook & Meta Ads: {stats['platforms']['facebook']}\n\n"
        f"{get_p_emoji('check_mark')} <i>All Downloader APIs & Audio Remuxer Engine Active!</i>"
    )
    await message.answer(text, parse_mode="HTML")

# ==================== DOWNLOADER & MULTI-QUEUE ROUTER ====================
@downloader_router.message(F.text)
async def process_media_urls(message: Message, bot: Bot):
    text = message.text or ""
    urls = downloader.extract_urls(text)
    
    if not urls:
        return

    user_id = message.from_user.id
    total_urls = len(urls)

    if total_urls > 1:
        await message.answer(
            f"{get_p_emoji('zap')} <b>Multi-Downloading System Activated!</b>\n\n"
            f"Processing <b>{total_urls}</b> social media links with full sound guarantee...",
            parse_mode="HTML"
        )

    for idx, url in enumerate(urls, 1):
        platform = downloader.detect_platform(url)
        status_msg = await message.answer(
            f"{get_p_emoji('down')} <b>Downloading Media [{idx}/{total_urls}]</b>...\n"
            f"• <b>Platform:</b> {platform.title() if platform else 'Social Media'}\n"
            f"• <b>Sound Track:</b> Stereo Audio Guaranteed\n"
            f"• <b>Quality:</b> Original Full HD / 4K\n"
            f"<i>Please wait a moment...</i>",
            parse_mode="HTML"
        )

        res = await downloader.download_media(url, force_local_download=True)

        if res.get("status") == "success" and (res.get("video_url") or res.get("local_file")):
            video_url = res.get("video_url")
            local_file = res.get("local_file")
            title = res.get("title", f"{platform.title()} Video")
            width = res.get("width")
            height = res.get("height")
            duration = res.get("duration", 0)

            cache_hash = str(abs(hash(url)) % 1000000)
            cache_key = f"{platform}:{cache_hash}"
            
            DOWNLOAD_CACHE[cache_key] = {
                "url": url,
                "platform": platform,
                "video_url": video_url,
                "local_file": local_file,
                "title": title,
                "thumbnail": res.get("thumbnail"),
                "width": width,
                "height": height,
                "duration": duration
            }

            keyboard = get_downloader_keyboard(url, platform, video_url or "", cache_hash)
            caption = (
                f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
                f"• 🌐 <b>Platform:</b> {platform.title()}\n"
                f"• 🔊 <b>Sound:</b> High Quality Audio Included\n"
                f"• 📺 <b>Resolution:</b> {width}x{height if height else 'Original'}\n"
                f"• ⚡️ <b>Status:</b> Ready"
            )

            # Send video with sound
            try:
                if local_file and os.path.exists(local_file):
                    await message.answer_video(
                        video=FSInputFile(local_file),
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                        supports_streaming=True,
                        width=int(width) if width else None,
                        height=int(height) if height else None,
                        duration=int(duration) if duration else None
                    )
                elif video_url:
                    await message.answer_video(
                        video=URLInputFile(video_url),
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                        supports_streaming=True,
                        width=int(width) if width else None,
                        height=int(height) if height else None,
                        duration=int(duration) if duration else None
                    )
                await status_msg.delete()
            except Exception as e:
                logger.warning(f"Video stream send failed, sending download options: {e}")
                await status_msg.edit_text(
                    caption,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

            # Log to DB and Log Channel
            await db.log_download_request(user_id, platform, url, status="success", title=title)

            if LOG_CHANNEL_ID:
                try:
                    log_text = (
                        f"📥 <b>NEW DOWNLOAD REQUEST</b>\n"
                        f"👤 <b>User:</b> {message.from_user.full_name} (<code>{user_id}</code>)\n"
                        f"🌐 <b>Platform:</b> {platform.title()}\n"
                        f"🔗 <b>URL:</b> {url}\n"
                        f"⏱ <b>Time:</b> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                    )
                    await bot.send_message(LOG_CHANNEL_ID, log_text, parse_mode="HTML")
                except Exception as log_err:
                    logger.warning(f"Could not send log to channel: {log_err}")

        else:
            err_msg = res.get("message", "Unable to download video.")
            await status_msg.edit_text(
                f"{get_p_emoji('trash')} <b>Download Failed [{idx}/{total_urls}]</b>\n\n"
                f"• <b>Platform:</b> {platform.title() if platform else 'Unknown'}\n"
                f"• <b>Error:</b> {err_msg}\n\n"
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
        f"{get_p_emoji('sparkles')} 📐 <b>DIRECT VIDEO RECEIVED ── RESIZE & CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
        f"• 📺 <b>Current Resolution:</b> {w}x{h}\n"
        f"• 📦 <b>File Size:</b> {file_size_mb} MB\n"
        f"• ⏱ <b>Duration:</b> {dur}s\n\n"
        f"Select your desired resolution, aspect ratio, or audio extraction below:"
    )
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

@downloader_router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def handle_direct_photo_upload(message: Message, bot: Bot):
    if message.photo:
        photo_obj = message.photo[-1] # Largest resolution
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
        f"{get_p_emoji('sparkles')} 📐 <b>IMAGE RECEIVED ── RESIZE & CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
        f"• 🖼 <b>Current Size:</b> {w}x{h if h else 'Auto'}\n"
        f"• 📦 <b>File Size:</b> {file_size_mb} MB\n\n"
        f"Select your desired output resolution or crop format below:"
    )
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

# ==================== CALLBACK ROUTER ====================
@callback_router.callback_query(F.data.startswith("prompt_") | F.data.startswith("info_"))
async def handle_platform_prompt(callback: CallbackQuery, bot: Bot):
    platform_key = callback.data.split("_")[1]
    prompt_map = {
        "insta": ("📸 Instagram Video Downloader", "Send your Instagram Reel, Post, IGTV, or Story video link below!"),
        "pin": ("📌 Pinterest Video Downloader", "Send your Pinterest Pin or Video clip link below!"),
        "snap": ("👻 Snapchat Video Downloader", "Send your Snapchat Spotlight or Story link below!"),
        "fb": ("📘 Facebook & Meta Ads Downloader", "Send your Facebook Reel, Video, or Meta Ads link below!")
    }
    title, desc = prompt_map.get(platform_key, ("Social Media Downloader", "Please send your video link below!"))
    text = (
        f"{get_p_emoji('fire')} <b>{title}</b> {get_p_emoji('fire')}\n\n"
        f"• {get_p_emoji('mic')} <b>Instruction:</b> {desc}\n\n"
        f"{get_p_emoji('sparkles')} <i>Direct video with full stereo sound will be downloaded automatically!</i>"
    )
    await callback.answer("📥 Send your video link below!", show_alert=False)
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_voice_guide")
async def handle_voice_guide_callback(callback: CallbackQuery):
    text = (
        f"{get_p_emoji('mic')} <b>VOICE, RESIZER & USAGE INSTRUCTION GUIDE</b> {get_p_emoji('mic')}\n\n"
        f"• <b>Download with Sound:</b> Send any video link from Instagram, Pinterest, Snapchat, or Facebook. The bot downloads high quality 1080p/4K with complete audio!\n\n"
        f"• <b>Send Any Video or Photo:</b> Send any video or image directly to this chat, and choose 4K, 1080p, 720p, 1:1 Square (Instagram Feed), or 9:16 Vertical (Reel/Story) format!\n\n"
        f"• <b>Voice Note & MP3:</b> Click 'Voice Note' or 'Audio MP3' on any video to extract crisp audio."
    )
    await callback.answer("🎙 Instructions sent below!", show_alert=False)
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data.startswith("dl_"))
async def handle_download_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    parts = data.split(":")
    action = parts[0]
    platform = parts[1] if len(parts) > 1 else "video"
    cache_id = f"{platform}:{parts[2]}" if len(parts) > 2 else None

    cached_item = DOWNLOAD_CACHE.get(cache_id) if cache_id else None

    if action == "dl_vid":
        await callback.answer("⚡️ Fetching Full HD / 4K Video...", show_alert=False)
        if cached_item:
            local_file = cached_item.get("local_file")
            video_url = cached_item.get("video_url")
            try:
                if local_file and os.path.exists(local_file):
                    await callback.message.answer_video(
                        video=FSInputFile(local_file),
                        caption=f"{get_p_emoji('check_mark')} <b>Downloaded with Full Stereo Sound!</b>",
                        parse_mode="HTML"
                    )
                elif video_url:
                    await callback.message.answer_video(
                        video=URLInputFile(video_url),
                        caption=f"{get_p_emoji('check_mark')} <b>Downloaded with Full Stereo Sound!</b>",
                        parse_mode="HTML"
                    )
            except Exception as e:
                await callback.message.answer(
                    f"🔗 <b>Direct Video Link:</b>\n{video_url}",
                    parse_mode="HTML"
                )

    elif action == "dl_voice" or action == "dl_audio":
        await callback.answer("🎙 Extracting Audio...", show_alert=True)
        if cached_item:
            media_url = cached_item.get("video_url")
            local_file = cached_item.get("local_file")
            
            temp_dir = tempfile.gettempdir()
            input_video = local_file
            
            # Download stream if local file not present
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
                    await callback.answer("❌ Could not extract audio from this stream.", show_alert=True)

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
            f"{get_p_emoji('sparkles')} 📐 <b>MEDIA SIZE & RESOLUTION CONVERTER</b> {get_p_emoji('sparkles')}\n\n"
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
            await callback.answer("⚠️ Media session expired. Please re-send link.", show_alert=True)
            return

        await callback.answer(f"⚡️ Converting to {target_mode.upper()} with audio...", show_alert=False)
        proc_msg = await callback.message.answer(
            f"{get_p_emoji('gear')} <b>Converting Media to {target_mode.upper()}...</b>\n"
            f"<i>Applying hardware encoding & preserving sound track...</i>",
            parse_mode="HTML"
        )

        temp_dir = tempfile.gettempdir()
        input_file = cached_item.get("local_file")
        
        # Ensure input file exists locally and is not 0 bytes
        if not input_file or not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
            input_file = os.path.join(temp_dir, f"conv_in_{cache_hash}.mp4")
            url = cached_item.get("url")
            v_url = cached_item.get("video_url")
            
            if url:
                dl_res = await downloader.fallback_ytdlp_downloader(url, download_file=True)
                if dl_res and dl_res.get("local_file") and os.path.exists(dl_res["local_file"]):
                    input_file = dl_res["local_file"]
            
            if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
                if v_url:
                    await downloader.download_url_to_file(v_url, input_file)

        if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
            await proc_msg.edit_text(
                "❌ <b>Error:</b> Could not fetch original video stream. Please re-send the link.",
                parse_mode="HTML"
            )
            return

        output_file = os.path.join(temp_dir, f"conv_out_{target_mode}_{cache_hash}.mp4")

        success, err = await downloader.convert_video_media(input_file, output_file, target_mode)

        if success and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            new_size_mb = round(os.path.getsize(output_file) / (1024 * 1024), 2)
            caption = (
                f"{get_p_emoji('check_mark')} <b>Successfully Converted to {target_mode.upper()}!</b>\n\n"
                f"• 📐 <b>Output Format:</b> {target_mode.upper()}\n"
                f"• 🔊 <b>Sound:</b> Full Audio Preserved\n"
                f"• 📦 <b>File Size:</b> {new_size_mb} MB"
            )
            try:
                await callback.message.answer_video(
                    video=FSInputFile(output_file),
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True
                )
                await proc_msg.delete()
            except Exception as send_err:
                logger.error(f"Error sending converted video: {send_err}")
                await proc_msg.edit_text(f"❌ Failed to send converted file: {send_err}")
            
            try:
                os.remove(output_file)
            except Exception:
                pass
        else:
            await proc_msg.edit_text(
                f"❌ <b>Conversion Failed:</b>\n<code>{err or 'FFmpeg conversion error'}</code>\n\n<i>Please try another format like 1080p or 720p.</i>",
                parse_mode="HTML"
            )

    elif action == "size_back":
        platform = parts[1] if len(parts) > 1 else "video"
        cache_hash = parts[2] if len(parts) > 2 else "0"
        cache_key = f"{platform}:{cache_hash}"
        cached_item = DOWNLOAD_CACHE.get(cache_key)
        video_url = cached_item.get("video_url", "") if cached_item else ""
        url = cached_item.get("url", "") if cached_item else ""
        
        kb = get_downloader_keyboard(url, platform, video_url, cache_hash)
        caption = (
            f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
            f"• 🌐 <b>Platform:</b> {platform.title()}\n"
            f"• 🔊 <b>Sound:</b> Stereo Audio Included\n"
            f"• ⚡️ <b>Status:</b> Ready"
        )
        await callback.answer()
        try:
            await callback.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(text=caption, reply_markup=kb, parse_mode="HTML")

# ==================== DIRECT MEDIA CONVERTER CALLBACKS ====================
@callback_router.callback_query(F.data.startswith("dir_"))
async def handle_direct_media_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    parts = data.split(":")
    action = parts[0]
    
    if action == "dir_size":
        target_mode = parts[1]
        media_type = parts[2]
        cache_id = parts[3]

        cached = DIRECT_MEDIA_CACHE.get(cache_id)
        if not cached:
            await callback.answer("⚠️ Media expired. Please upload video/photo again.", show_alert=True)
            return

        await callback.answer(f"⚡️ Processing {target_mode.upper()}...", show_alert=False)
        proc_msg = await callback.message.answer(
            f"{get_p_emoji('gear')} <b>Converting {media_type.title()} to {target_mode.upper()}...</b>\n"
            f"<i>Please wait a few seconds...</i>",
            parse_mode="HTML"
        )

        temp_dir = tempfile.gettempdir()
        file_id = cached["file_id"]
        
        # Download from Telegram
        tg_file = await bot.get_file(file_id)
        in_ext = ".jpg" if media_type == "photo" else ".mp4"
        in_path = os.path.join(temp_dir, f"dir_in_{cache_id}{in_ext}")
        await bot.download_file(tg_file.file_path, in_path)

        out_ext = ".jpg" if media_type == "photo" else ".mp4"
        out_path = os.path.join(temp_dir, f"dir_out_{target_mode}_{cache_id}{out_ext}")

        if media_type == "photo":
            success, err = await downloader.convert_image_media(in_path, out_path, target_mode)
            if success and os.path.exists(out_path):
                new_size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
                await callback.message.answer_photo(
                    photo=FSInputFile(out_path),
                    caption=f"{get_p_emoji('check_mark')} <b>Image Resized to {target_mode.upper()}!</b>\n• 📦 <b>Size:</b> {new_size_mb} MB",
                    parse_mode="HTML"
                )
                await proc_msg.delete()
            else:
                await proc_msg.edit_text(f"❌ Image resizing failed: {err}")
        else: # Video
            success, err = await downloader.convert_video_media(in_path, out_path, target_mode)
            if success and os.path.exists(out_path):
                new_size_mb = round(os.path.getsize(out_path) / (1024 * 1024), 2)
                await callback.message.answer_video(
                    video=FSInputFile(out_path),
                    caption=f"{get_p_emoji('check_mark')} <b>Video Converted to {target_mode.upper()}!</b>\n• 🔊 <b>Sound:</b> Intact\n• 📦 <b>Size:</b> {new_size_mb} MB",
                    parse_mode="HTML",
                    supports_streaming=True
                )
                await proc_msg.delete()
            else:
                await proc_msg.edit_text(f"❌ Video conversion failed: {err}")

        # Cleanup
        try:
            if os.path.exists(in_path): os.remove(in_path)
            if os.path.exists(out_path): os.remove(out_path)
        except Exception:
            pass

    elif action in ("dir_voice", "dir_audio"):
        cache_id = parts[2]
        cached = DIRECT_MEDIA_CACHE.get(cache_id)
        if not cached:
            await callback.answer("⚠️ Media expired. Re-upload video.", show_alert=True)
            return

        await callback.answer("🎙 Extracting Audio...", show_alert=True)
        temp_dir = tempfile.gettempdir()
        file_id = cached["file_id"]
        tg_file = await bot.get_file(file_id)
        in_path = os.path.join(temp_dir, f"dir_in_{cache_id}.mp4")
        await bot.download_file(tg_file.file_path, in_path)

        is_voice = (action == "dir_voice")
        ext = ".ogg" if is_voice else ".mp3"
        out_path = os.path.join(temp_dir, f"dir_audio_{cache_id}{ext}")

        success = await downloader.extract_audio_from_media(in_path, out_path, is_voice=is_voice)
        if success and os.path.exists(out_path):
            if is_voice:
                await callback.message.answer_voice(
                    voice=FSInputFile(out_path),
                    caption=f"{get_p_emoji('mic')} <b>Voice Note Extracted!</b>",
                    parse_mode="HTML"
                )
            else:
                await callback.message.answer_audio(
                    audio=FSInputFile(out_path),
                    title="Audio Note",
                    caption=f"{get_p_emoji('studio_mic')} <b>MP3 Audio Extracted!</b>",
                    parse_mode="HTML"
                )
        else:
            await callback.message.answer("❌ Failed to extract audio.")

        try:
            if os.path.exists(in_path): os.remove(in_path)
            if os.path.exists(out_path): os.remove(out_path)
        except Exception:
            pass

@callback_router.callback_query(F.data == "cmd_close")
async def handle_close_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Closed!")

@callback_router.callback_query(F.data == "cmd_stats")
async def handle_stats_callback(callback: CallbackQuery):
    stats = await db.get_system_stats()
    text = (
        f"{get_p_emoji('chart_up')} <b>LIVE DOWNLOADER STATISTICS</b> {get_p_emoji('chart_up')}\n\n"
        f"• {get_p_emoji('fire')} <b>Total Media Downloaded:</b> {stats['total_downloads']}\n"
        f"• {get_p_emoji('glowing_star')} <b>Total Active Users:</b> {stats['total_users']}\n"
        f"• {get_p_emoji('crown')} <b>Authorized Admins:</b> {stats['total_authorized']}\n\n"
        f"📊 <b>Platform Breakdown:</b>\n"
        f"📸 Instagram: {stats['platforms']['instagram']}\n"
        f"📌 Pinterest: {stats['platforms']['pinterest']}\n"
        f"👻 Snapchat: {stats['platforms']['snapchat']}\n"
        f"📘 Facebook & Ads: {stats['platforms']['facebook']}"
    )
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")

# ==================== EMOJI UPLOAD & MANAGEMENT ROUTER ====================
@emoji_router.message(Command("addemoji"))
@emoji_router.message(Command("saveemoji"))
async def command_add_emoji(message: Message):
    user_id = message.from_user.id
    if not await is_admin_user(user_id):
        await message.answer("⛔ Only authorized admins can manage premium custom emoji IDs.")
        return

    parts = message.text.split()
    if len(parts) < 3:
        usage_text = (
            f"{get_p_emoji('gear')} <b>UPLOAD & SAVE EMOJI ID USAGE</b>\n\n"
            f"<b>Syntax:</b> <code>/addemoji &lt;emoji_name&gt; &lt;emoji_id&gt; [char]</code>\n\n"
            f"<b>Examples:</b>\n"
            f"• <code>/addemoji fire 6165899765042122114 🔥</code>\n"
            f"• <code>/addemoji crown 6165733687246720248 👑</code>\n"
            f"• <code>/addemoji down 6158868637290601091 ⬇️</code>"
        )
        await message.answer(usage_text, parse_mode="HTML")
        return

    name = parts[1]
    emoji_id = parts[2]
    char = parts[3] if len(parts) > 3 else "✨"

    success = await db.save_custom_emoji(name, emoji_id, char=char, updated_by=user_id)
    if success:
        formatted_preview = get_p_emoji(name)
        await message.answer(
            f"{get_p_emoji('check_mark')} <b>Emoji ID Saved & Applied Successfully!</b>\n\n"
            f"• <b>Name:</b> <code>{name}</code>\n"
            f"• <b>Emoji ID:</b> <code>{emoji_id}</code>\n"
            f"• <b>Preview:</b> {formatted_preview}",
            parse_mode="HTML"
        )

@emoji_router.message(Command("emojis"))
async def command_list_emojis(message: Message):
    custom_list = await db.get_all_custom_emojis()
    text = f"{get_p_emoji('sparkles')} <b>SAVED CUSTOM PREMIUM EMOJI IDs</b> {get_p_emoji('sparkles')}\n\n"
    if not custom_list:
        text += "<i>No custom emoji IDs uploaded yet. Use <code>/addemoji &lt;name&gt; &lt;id&gt;</code> to upload.</i>"
    else:
        for item in custom_list:
            formatted = get_p_emoji(item['name'])
            text += f"• <b>{item['name']}</b>: <code>{item['emoji_id']}</code> ({formatted})\n"

    text += "\n<i>All saved emoji IDs render automatically in bot buttons and messages.</i>"
    await message.answer(text, parse_mode="HTML")

@emoji_router.message(Command("delemoji"))
async def command_delete_emoji(message: Message):
    user_id = message.from_user.id
    if not await is_admin_user(user_id):
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/delemoji &lt;emoji_name&gt;</code>", parse_mode="HTML")
        return

    name = parts[1]
    res = await db.delete_custom_emoji(name)
    if res:
        await message.answer(f"✅ Emoji <code>{name}</code> deleted from database.", parse_mode="HTML")
    else:
        await message.answer(f"❌ Emoji <code>{name}</code> not found.", parse_mode="HTML")

# ==================== ADMIN & LOGS ROUTER ====================
@admin_router.message(Command("logs"))
async def command_logs_handler(message: Message):
    user_id = message.from_user.id
    if not await is_admin_user(user_id):
        return

    logs = await db.get_recent_download_logs(limit=20)
    text = f"{get_p_emoji('gear')} <b>RECENT SYSTEM & DOWNLOAD LOGS</b>\n\n"
    if not logs:
        text += "<i>No download logs recorded yet.</i>"
    else:
        for lg in logs:
            st_icon = "✅" if lg.get("status") == "success" else "❌"
            dt = lg.get("downloaded_at", "")[:19].replace("T", " ")
            text += (
                f"{st_icon} <b>[{lg.get('platform', 'media').upper()}]</b> User: <code>{lg.get('user_id')}</code>\n"
                f"🔗 <code>{lg.get('url', '')[:45]}...</code>\n"
                f"⏱ <i>{dt}</i>\n\n"
            )

    await message.answer(text, parse_mode="HTML")

@admin_router.message(Command("grant"))
async def command_grant_user(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/grant &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.grant_user_access(target_id, message.from_user.id)
    await message.answer(f"✅ User <code>{target_id}</code> granted admin authorization.", parse_mode="HTML")

@admin_router.message(Command("revoke"))
async def command_revoke_user(message: Message):
    if message.from_user.id not in SUPER_ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/revoke &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.revoke_user_access(target_id)
    await message.answer(f"🚫 User <code>{target_id}</code> access revoked.", parse_mode="HTML")

@admin_router.message(Command("broadcast"))
async def command_broadcast(message: Message, bot: Bot):
    if not await is_admin_user(message.from_user.id):
        return

    if not message.reply_to_message and len(message.text.split()) < 2:
        await message.answer("Usage: Reply to a message with <code>/broadcast</code> or type <code>/broadcast &lt;text&gt;</code>", parse_mode="HTML")
        return

    users = await db.get_all_users()
    await message.answer(f"📢 Starting broadcast to <b>{len(users)}</b> users...", parse_mode="HTML")

    success_cnt = 0
    fail_cnt = 0
    for u in users:
        try:
            if message.reply_to_message:
                await message.reply_to_message.copy_to(chat_id=u["user_id"])
            else:
                b_text = message.text.split(maxsplit=1)[1]
                await bot.send_message(u["user_id"], b_text, parse_mode="HTML")
            success_cnt += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_cnt += 1

    await message.answer(
        f"{get_p_emoji('check_mark')} <b>Broadcast Completed!</b>\n\n"
        f"• <b>Successful:</b> {success_cnt}\n"
        f"• <b>Failed/Blocked:</b> {fail_cnt}",
        parse_mode="HTML"
    )

# ==================== ADVANCED INLINE MODE ROUTER ====================
@inline_router.inline_query()
async def inline_download_handler(inline_query: InlineQuery):
    query_text = inline_query.query.strip()
    if not query_text:
        return

    urls = downloader.extract_urls(query_text)
    if not urls:
        return

    url = urls[0]
    platform = downloader.detect_platform(url) or "Social Media"
    res = await downloader.download_media(url)

    results = []
    if res.get("status") == "success" and res.get("video_url"):
        v_url = res.get("video_url")
        title = res.get("title", f"{platform.title()} Video")

        results.append(
            InlineQueryResultVideo(
                id=f"vid_{abs(hash(url)) % 100000}",
                video_url=v_url,
                mime_type="video/mp4",
                thumbnail_url=res.get("thumbnail") or "https://i.ibb.co/Gfc7zqjp/Auto-Rq-Tools.png",
                title=f"🎬 Download {platform.title()} Video (Full HD)",
                caption=f"🎬 <b>{title}</b>\n\nDownloaded via Social Media Video Downloader Bot",
                parse_mode="HTML"
            )
        )
    else:
        results.append(
            InlineQueryResultArticle(
                id=f"err_{abs(hash(url)) % 100000}",
                title=f"❌ Download Failed for {platform.title()}",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ Unable to fetch video from link: {url}",
                    parse_mode="HTML"
                )
            )
        )

    await inline_query.answer(results, cache_time=10, is_personal=True)

# ==================== MAIN INITIALIZATION ====================
async def main():
    logger.info("🚀 Starting Social Media Video Downloader & Media Resizer Bot...")
    
    # Initialize MongoDB
    await db.init_db()

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
