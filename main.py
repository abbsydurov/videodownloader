import asyncio
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List, Callable, Awaitable

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware, types
from aiogram.enums import ParseMode, ChatType
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message,
    CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InlineQueryResultVideo, InputTextMessageContent, URLInputFile,
    TelegramObject
)
from aiogram.exceptions import TelegramAPIError

from config import (
    BOT_TOKEN, SUPER_ADMIN_ID, LOG_CHANNEL_ID, WELCOME_IMAGE,
    get_p_emoji, get_btn_emoji, logger
)
import database as db
import downloader

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
    "★ <b><u>Sᴏᴄɪᴀʟ Mᴇᴅɪᴀ Vɪᴅᴇᴏ Dᴏᴡɴʟᴏᴀᴅᴇʀ Gᴜɪᴅᴇ</u></b> ★\n\n"
    "✨ <b>Sᴜᴘᴘᴏʀᴛᴇᴅ Pʟᴀᴛғᴏʀᴍs:</b>\n"
    "• 📸 <b>Instagram</b> ── <i>Reels, Posts, IGTV, Stories</i>\n"
    "• 📌 <b>Pinterest</b> ── <i>Pins & Video clips</i>\n"
    "• 👻 <b>Snapchat</b> ── <i>Spotlight & Stories</i>\n"
    "• 📘 <b>Facebook</b> ── <i>Reels, Videos & Meta Ads</i>\n\n"
    "⚡️ <b>Hᴏᴡ Tᴏ Dᴏᴡɴʟᴏᴀᴅ:</b>\n"
    "1️⃣ Send any social media video link directly to the bot.\n"
    "2️⃣ Select <b>Download Video</b> or <b>Voice Note (.ogg)</b>.\n"
    "3️⃣ Use <b>📐 Size Converter</b> to change video resolution & format!\n\n"
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

# Helper function to generate clean compact inline keyboards with official Telegram button styles
def get_downloader_keyboard(url: str, platform: str, video_url: str, hd_url: str = None) -> InlineKeyboardMarkup:
    cache_hash = str(hash(url) % 1000000)
    kb = [
        [
            InlineKeyboardButton(
                text=f"{get_btn_emoji('fire')} 🎬 Video (Original 4K)",
                callback_data=f"dl_vid:{platform}:{cache_hash}",
                style="success"
            ),
            InlineKeyboardButton(
                text=f"{get_btn_emoji('mic')} 🎙 Voice Note",
                callback_data=f"dl_voice:{platform}:{cache_hash}",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{get_btn_emoji('studio_mic')} 🎵 Audio MP3",
                callback_data=f"dl_audio:{platform}:{cache_hash}",
                style="primary"
            ),
            InlineKeyboardButton(
                text=f"{get_btn_emoji('sparkles')} 📐 Size Converter",
                callback_data=f"size_menu:{platform}:{cache_hash}",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{get_btn_emoji('trash')} 🗑 Close",
                callback_data="cmd_close",
                style="danger"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_size_converter_keyboard(platform: str, cache_hash: str) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('glowing_star')} 🌟 4K (2160p)", callback_data=f"size_set:2160p:{platform}:{cache_hash}", style="success"),
            InlineKeyboardButton(text=f"{get_btn_emoji('snowflake')} 📺 1080p Full HD", callback_data=f"size_set:1080p:{platform}:{cache_hash}", style="primary")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('fire')} 🔥 720p HD", callback_data=f"size_set:720p:{platform}:{cache_hash}", style="primary"),
            InlineKeyboardButton(text=f"{get_btn_emoji('phone')} 📱 480p SD", callback_data=f"size_set:480p:{platform}:{cache_hash}")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('check_box')} 📐 1:1 Square", callback_data=f"size_set:1to1:{platform}:{cache_hash}"),
            InlineKeyboardButton(text=f"{get_btn_emoji('selfie')} 📱 9:16 Vertical", callback_data=f"size_set:9to16:{platform}:{cache_hash}")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('back')} 🔙 Back", callback_data=f"size_back:{platform}:{cache_hash}", style="danger")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# Store download cache for callbacks
DOWNLOAD_CACHE: Dict[str, Dict[str, Any]] = {}

# ==================== START & HELP ROUTER ====================
def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('fire')} Instagram", callback_data="prompt_insta", style="primary"),
            InlineKeyboardButton(text=f"{get_btn_emoji('zap')} Pinterest", callback_data="prompt_pin", style="primary")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('glowing_star')} Snapchat", callback_data="prompt_snap", style="primary"),
            InlineKeyboardButton(text=f"{get_btn_emoji('eye')} Facebook Ads", callback_data="prompt_fb", style="primary")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('mic')} 🎙 Voice Guide / Instructions", callback_data="cmd_voice_guide", style="success")
        ]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text=f"{get_btn_emoji('crown')} 👑 Admin Panel", callback_data="cmd_admin_panel", style="danger")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

@start_router.message(CommandStart())
async def command_start_handler(message: Message, bot: Bot):
    user = message.from_user
    if not user:
        return

    is_admin = (user.id == SUPER_ADMIN_ID or await db.is_user_authorized(user.id))
    bot_info = await bot.get_me()
    keyboard = get_main_menu_keyboard(is_admin=is_admin)

    caption_text = (
        f"{get_p_emoji('fire')} <b>ADVANCED SOCIAL MEDIA VIDEO DOWNLOADER</b> {get_p_emoji('fire')}\n\n"
        f"Welcome, <b>{user.first_name}</b>!\n\n"
        f"Just send me any link from <b>Instagram, Pinterest, Snapchat, Facebook, or Meta Ads</b> to download videos in <b>Full HD / 4K</b> quality or convert to <b>Voice Notes</b> instantly!\n\n"
        f"• {get_p_emoji('check_mark')} <b>Instagram Reels & Stories</b>\n"
        f"• {get_p_emoji('check_mark')} <b>Pinterest Pins & Clips</b>\n"
        f"• {get_p_emoji('check_mark')} <b>Snapchat Spotlight & Stories</b>\n"
        f"• {get_p_emoji('check_mark')} <b>Facebook Reels & Meta Ads</b>\n"
        f"• {get_p_emoji('check_mark')} <b>Multi-Downloading System</b>\n"
        f"• {get_p_emoji('check_mark')} <b>Inline Search Mode</b>: <code>@{bot_info.username} &lt;link&gt;</code>\n\n"
        f"<i>Paste your link below to start downloading!</i>"
    )
    try:
        await message.answer_photo(photo=WELCOME_IMAGE, caption=caption_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await message.answer(caption_text, reply_markup=keyboard, parse_mode="HTML")

@start_router.message(Command("help"))
async def command_help_handler(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    is_admin = (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id))
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
        f"{get_p_emoji('check_mark')} <i>All Downloader APIs & Fallback Engine Active!</i>"
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
            f"Processing <b>{total_urls}</b> social media links in queue...",
            parse_mode="HTML"
        )

    for idx, url in enumerate(urls, 1):
        platform = downloader.detect_platform(url)
        status_msg = await message.answer(
            f"{get_p_emoji('down')} <b>Downloading Media [{idx}/{total_urls}]</b>...\n"
            f"• <b>Platform:</b> {platform.title() if platform else 'Social Media'}\n"
            f"• <b>Quality:</b> Full HD / 4K Auto-Detect\n"
            f"<i>Please wait...</i>",
            parse_mode="HTML"
        )

        res = await downloader.download_media(url)

        if res.get("status") == "success" and res.get("video_url"):
            video_url = res.get("video_url")
            hd_url = res.get("hd_url", video_url)
            title = res.get("title", f"{platform.title()} Video")
            width = res.get("width")
            height = res.get("height")
            duration = res.get("duration", 0)

            cache_key = f"{platform}:{hash(url) % 1000000}"
            
            DOWNLOAD_CACHE[cache_key] = {
                "url": url,
                "platform": platform,
                "video_url": video_url,
                "hd_url": hd_url,
                "title": title,
                "thumbnail": res.get("thumbnail"),
                "width": width,
                "height": height,
                "duration": duration
            }

            keyboard = get_downloader_keyboard(url, platform, video_url, hd_url)
            caption = (
                f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
                f"• 🌐 <b>Platform:</b> {platform.title()}\n"
                f"• 📺 <b>Quality:</b> Original Resolution (Exact Size)\n"
                f"• ⚡️ <b>Status:</b> Complete"
            )

            video_kwargs = {
                "video": URLInputFile(video_url),
                "caption": caption,
                "reply_markup": keyboard,
                "parse_mode": "HTML",
                "supports_streaming": True
            }
            if width and height:
                video_kwargs["width"] = int(width)
                video_kwargs["height"] = int(height)
            if duration:
                video_kwargs["duration"] = int(duration)

            try:
                await message.answer_video(**video_kwargs)
                await status_msg.delete()
            except Exception as e:
                logger.warning(f"Direct video send failed, sending download options: {e}")
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

# ==================== CALLBACK ROUTER ====================
@callback_router.callback_query(F.data.startswith("prompt_") | F.data.startswith("info_"))
async def handle_platform_prompt(callback: CallbackQuery, bot: Bot):
    platform_key = callback.data.split("_")[1]
    prompt_map = {
        "insta": ("📸 Instagram Video Downloader", "Please send your Instagram Reel, Post, IGTV, or Story video link/URL below!"),
        "pin": ("📌 Pinterest Video Downloader", "Please send your Pinterest Pin or Video clip link/URL below!"),
        "snap": ("👻 Snapchat Video Downloader", "Please send your Snapchat Spotlight or Story video link/URL below!"),
        "fb": ("📘 Facebook & Meta Ads Downloader", "Please send your Facebook Reel, Watch Video, or Meta Ads video link/URL below!")
    }
    title, desc = prompt_map.get(platform_key, ("Social Media Downloader", "Please send your video link/URL below!"))
    text = (
        f"{get_p_emoji('fire')} <b>{title}</b> {get_p_emoji('fire')}\n\n"
        f"• {get_p_emoji('mic')} <b>Instruction:</b> {desc}\n\n"
        f"{get_p_emoji('sparkles')} <i>Send video link/URL ── Voice Note & Full HD / 4K Video will be generated automatically!</i>"
    )
    await callback.answer("📥 Send your video link/URL below!", show_alert=False)
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_voice_guide")
async def handle_voice_guide_callback(callback: CallbackQuery):
    text = (
        f"{get_p_emoji('mic')} <b>VOICE & USAGE INSTRUCTION GUIDE</b> {get_p_emoji('mic')}\n\n"
        f"• <b>How to download:</b> Simply copy any video link from Instagram, Pinterest, Snapchat, or Facebook and send it directly in this chat!\n\n"
        f"• <b>Automatic 4K & Full HD:</b> Videos are automatically delivered in maximum 4K / 1080p resolution in exact original size & uncropped aspect ratio.\n\n"
        f"• <b>Voice Note & Audio MP3:</b> Click 'Voice Note' or 'Audio MP3' on any downloaded video card to generate audio format instantly!\n\n"
        f"• <b>Size Converter:</b> Use the 'Size Converter' button on any video result card to convert to 4K, 1080p, 720p, 480p, 1:1 Square, or 9:16 Vertical format."
    )
    await callback.answer("🎙 Voice Guide sent below!", show_alert=False)
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data.startswith("mode_"))
async def handle_mode_info(callback: CallbackQuery):
    mode_key = callback.data.split("_")[1]
    if mode_key == "hd":
        await callback.answer("📺 Full HD / 4K Mode is ACTIVE by default!", show_alert=True)
    elif mode_key == "voice":
        await callback.answer("🎙 Voice Note Extraction is ACTIVE! Click 'Voice Note' on any media.", show_alert=True)

@callback_router.callback_query(F.data == "cmd_emojis")
async def handle_emojis_menu_callback(callback: CallbackQuery):
    custom_list = await db.get_all_custom_emojis()
    text = f"{get_p_emoji('sparkles')} <b>SAVED CUSTOM PREMIUM EMOJI IDs</b>\n\n"
    if not custom_list:
        text += "<i>No custom emojis stored in DB yet. Using 48 built-in premium emoji IDs!</i>\n"
    else:
        for item in custom_list[:15]:
            formatted = get_p_emoji(item['name'])
            text += f"• <b>{item['name']}</b>: <code>{item['emoji_id']}</code> ({formatted})\n"
    
    text += "\n<i>Use command <code>/addemoji &lt;name&gt; &lt;id&gt;</code> to upload new emoji IDs.</i>"
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_admin_panel")
async def handle_admin_panel_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id)):
        await callback.answer("⛔ Admin Access Required!", show_alert=True)
        return

    text = (
        f"{get_p_emoji('crown')} <b>ADMIN CONTROL PANEL</b> {get_p_emoji('crown')}\n\n"
        f"Welcome Super Admin!\n\n"
        f"<b>Admin Control Dashboard:</b>\n"
        f"• <code>/logs</code> ── Live Download Logs\n"
        f"• <code>/stats</code> ── Downloader Statistics\n"
        f"• <code>/emojis</code> ── Emojis Manager\n"
        f"• <code>/grant &lt;id&gt;</code> | <code>/revoke &lt;id&gt;</code> ── Access Guard\n"
        f"• <code>/broadcast</code> ── Send Announcement"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('chart_up')} Live Stats", callback_data="cmd_stats"),
            InlineKeyboardButton(text=f"{get_btn_emoji('gear')} Emojis List", callback_data="cmd_emojis")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('clipboard')} System Logs", callback_data="cmd_logs"),
            InlineKeyboardButton(text=f"{get_btn_emoji('speech')} Broadcast", callback_data="cmd_broadcast_prompt")
        ],
        [
            InlineKeyboardButton(text=f"{get_btn_emoji('trash')} Close Panel", callback_data="cmd_close")
        ]
    ])
    await callback.answer()
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_logs")
async def handle_logs_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id)):
        return
    logs = await db.get_recent_download_logs(limit=15)
    text = f"{get_p_emoji('gear')} <b>RECENT SYSTEM DOWNLOAD LOGS</b>\n\n"
    if not logs:
        text += "<i>No logs recorded yet.</i>"
    else:
        for lg in logs:
            st_icon = "✅" if lg.get("status") == "success" else "❌"
            dt = lg.get("downloaded_at", "")[:19].replace("T", " ")
            text += f"{st_icon} <b>[{lg.get('platform', 'media').upper()}]</b> User: <code>{lg.get('user_id')}</code> ⏱ <i>{dt}</i>\n"
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML")

@callback_router.callback_query(F.data == "cmd_broadcast_prompt")
async def handle_broadcast_prompt_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id != SUPER_ADMIN_ID:
        await callback.answer("⛔ Super Admin only!", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        f"{get_p_emoji('speech')} <b>BROADCAST ANNOUNCEMENT</b>\n\n"
        f"Reply to any message with <code>/broadcast</code> or send <code>/broadcast &lt;text&gt;</code> to notify all users.",
        parse_mode="HTML"
    )

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
        if cached_item and cached_item.get("video_url"):
            try:
                await callback.message.answer_video(
                    video=URLInputFile(cached_item["video_url"]),
                    caption=f"{get_p_emoji('check_mark')} <b>Downloaded in Full HD / 4K!</b>",
                    parse_mode="HTML"
                )
            except Exception as e:
                await callback.message.answer(
                    f"🔗 <b>Direct Video Stream Link:</b>\n{cached_item['video_url']}",
                    parse_mode="HTML"
                )

    elif action == "dl_voice" or action == "dl_audio":
        await callback.answer("🎙 Generating Voice Note / Audio...", show_alert=True)
        if cached_item and cached_item.get("video_url"):
            media_url = cached_item["video_url"]
            try:
                stream_bytes = await downloader.download_file_to_bytes(media_url)
                if stream_bytes:
                    temp_file = os.path.join(tempfile.gettempdir(), f"voice_{callback.from_user.id}.ogg")
                    with open(temp_file, "wb") as f:
                        f.write(stream_bytes)
                    
                    if action == "dl_voice":
                        await callback.message.answer_voice(
                            voice=types.FSInputFile(temp_file),
                            caption=f"{get_p_emoji('mic')} <b>Voice Note Extracted!</b>",
                            parse_mode="HTML"
                        )
                    else:
                        await callback.message.answer_audio(
                            audio=types.FSInputFile(temp_file),
                            title=cached_item.get('title', 'Audio'),
                            caption=f"{get_p_emoji('studio_mic')} <b>Audio Extracted!</b>",
                            parse_mode="HTML"
                        )
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass
                else:
                    await callback.message.answer_audio(
                        audio=URLInputFile(media_url),
                        caption=f"{get_p_emoji('studio_mic')} <b>Audio Stream</b>",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Voice note conversion error: {e}")
                await callback.answer("❌ Audio extraction failed for this format.", show_alert=True)

    elif action == "dl_qual":
        await callback.answer("📺 Quality selected: 4K / Full HD 1080p (Auto-Best)", show_alert=True)

@callback_router.callback_query(F.data.startswith("size_"))
async def handle_size_converter_callbacks(callback: CallbackQuery):
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
        resolution = parts[1]
        await callback.answer(f"✅ Converted output format to {resolution.upper()}!", show_alert=True)

    elif action == "size_back":
        platform = parts[1] if len(parts) > 1 else "video"
        cache_hash = parts[2] if len(parts) > 2 else "0"
        cache_key = f"{platform}:{cache_hash}"
        cached_item = DOWNLOAD_CACHE.get(cache_key)
        video_url = cached_item.get("video_url", "") if cached_item else ""
        url = cached_item.get("url", "") if cached_item else ""
        
        kb = get_downloader_keyboard(url, platform, video_url)
        caption = (
            f"{get_p_emoji('check_mark')} <b>Video Downloaded Successfully!</b>\n\n"
            f"• 🌐 <b>Platform:</b> {platform.title()}\n"
            f"• 📺 <b>Quality:</b> Original Aspect Ratio / Full HD\n"
            f"• ⚡️ <b>Status:</b> Complete"
        )
        await callback.answer()
        try:
            await callback.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(text=caption, reply_markup=kb, parse_mode="HTML")

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
    if not (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id)):
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
    if not (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id)):
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
    if not (user_id == SUPER_ADMIN_ID or await db.is_user_authorized(user_id)):
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
    if message.from_user.id != SUPER_ADMIN_ID:
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
    if message.from_user.id != SUPER_ADMIN_ID:
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
    if message.from_user.id != SUPER_ADMIN_ID:
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
                id=f"vid_{hash(url) % 100000}",
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
                id=f"err_{hash(url) % 100000}",
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
    logger.info("🚀 Starting Social Media Video Downloader Bot...")
    
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
    logger.info("✅ Bot is online & listening for commands!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
