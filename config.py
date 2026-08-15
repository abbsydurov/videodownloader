import os
import sys
import logging
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("SocialMediaDownloaderBot")

API_ID = int(os.getenv("API_ID", "32397550"))
API_HASH = os.getenv("API_HASH", "1888c6fb45d30c4a0e46e999ba26e051")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8887193580:AAHVMkh8vSp9rVlHjVAM4B8r8XN_ZEyFsp8")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "1988538065"))
SUPER_ADMIN_IDS = {1988538065, 5157557268, SUPER_ADMIN_ID}
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0")) if os.getenv("LOG_CHANNEL_ID") else 0

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://notimepass367_db_user:abbsy%40123@cluster0.wof2cvr.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
MONGO_DB_URI = MONGO_URI
DB_NAME = os.getenv("DB_NAME", "downloader_bot_db")

WELCOME_IMAGE = os.getenv("WELCOME_IMAGE", "https://i.ibb.co/Gfc7zqjp/Auto-Rq-Tools.png")

# Primary APIs provided
API_ENDPOINTS = {
    "instagram": "https://api-owner-2.onrender.com/insta?video=",
    "pinterest": "https://api-owner-2.onrender.com/pin?video=",
    "snapchat": "https://api-owner-2.onrender.com/snap?video=",
    "facebook": "https://api-owner-2.onrender.com/fb?video="
}

# 💎 48 Learned Premium Emojis mapping
DEFAULT_PREMIUM_EMOJIS = {
    "mic": ("🎤", "6109651730872408665"),
    "diamond": ("💎", "5287627524795290725"),
    "crown": ("👑", "5271557007009128936"),
    "phone": ("📱", "5114287571056198794"),
    "selfie": ("🤳", "5233455639161750788"),
    "fire": ("🔥", "6165899765042122114"),
    "speech": ("💬", "5339175649267428634"),
    "write": ("✍️", "5197269100878907942"),
    "dizzy": ("💫", "6165894413512871182"),
    "finger_up": ("☝️", "5345986836038694332"),
    "check_box": ("✅", "6158935325247805180"),
    "zap_alt": ("⚡️", "5431895514922641912"),
    "zap": ("⚡", "6165582852290252628"),
    "gear": ("⚙️", "5341715473882955310"),
    "studio_mic": ("🎙", "5474279751143136434"),
    "studio_mic_alt": ("🎙️", "5474279751143136434"),
    "sparkles": ("✨", "6154310409974190743"),
    "thumbs_up": ("👍", "6183943695746732556"),
    "smile": ("😊", "6161213251347551709"),
    "owl": ("🦉", "6186045884669628967"),
    "duck": ("🦆", "6186020952384475802"),
    "money_face": ("🤑", "6186175669991379791"),
    "t_rex": ("🦖", "6186233896863011865"),
    "ninja": ("🥷", "6233527959307688784"),
    "sweat": ("😓", "6260478625687018336"),
    "check_mark": ("✔️", "6336628528989083013"),
    "eye": ("👁", "6336887317948536124"),
    "point_up": ("👆", "6161121450716566360"),
    "glowing_star": ("🌟", "6163600858027135317"),
    "chart_up": ("📈", "6109418703126796249"),
    "snowflake": ("❄️", "6109347707317393978"),
    "question": ("❔", "6163186994978492950"),
    "blue_circle": ("🔵", "6163336970941501725"),
    "blossom": ("🌸", "6165618590713122679"),
    "arrow_right": ("➡️", "6158868637290601091"),
    "yin_yang": ("☯️", "6163667490149765932"),
    "plug": ("🔌", "5389118804590604722"),
    "clipboard": ("📋", "5886223731088431288"),
    "key": ("🔑", "5784887271979227029"),
    "door": ("🚪", "6165899765042122114"),
    "plus": ("➕", "5253652327734192243"),
    "minus": ("➖", "6120775833608001118"),
    "people": ("👥", "5264942233387285985"),
    "back": ("🔙", "5388781950305580591"),
    "trash_alt": ("🗑️", "6260478625687018336"),
    "point_down": ("👇", "5253793138236995404"),
    "angry": ("😡", "5240408207666455054"),
    "trash": ("🗑", "5231010832107708935"),
    "down": ("⬇️", "6158868637290601091"),
}

# Dynamic in-memory premium emojis registry (loaded from DB on startup)
PREMIUM_EMOJIS_CACHE = dict(DEFAULT_PREMIUM_EMOJIS)

def get_p_emoji(name: str) -> str:
    """Returns HTML tg-emoji tag if available, else plain unicode emoji (for HTML messages/captions)."""
    if name in PREMIUM_EMOJIS_CACHE:
        char, custom_id = PREMIUM_EMOJIS_CACHE[name]
        if custom_id:
            return f'<tg-emoji emoji-id="{custom_id}"></tg-emoji>'
        return char
    return DEFAULT_PREMIUM_EMOJIS.get(name, ("✨", ""))[0]

def get_btn_emoji(name: str) -> str:
    """Returns clean unicode emoji character for Inline Keyboard buttons (since buttons do not support HTML tags)."""
    if name in PREMIUM_EMOJIS_CACHE:
        return PREMIUM_EMOJIS_CACHE[name][0]
    return DEFAULT_PREMIUM_EMOJIS.get(name, ("✨", ""))[0]

def get_btn_emoji_id(name: str) -> Optional[str]:
    """Returns custom emoji ID for InlineKeyboardButton icon_custom_emoji_id parameter."""
    if name in PREMIUM_EMOJIS_CACHE:
        return PREMIUM_EMOJIS_CACHE[name][1] or None
    return DEFAULT_PREMIUM_EMOJIS.get(name, ("✨", ""))[1] or None

def update_emoji_cache(name: str, char: str, emoji_id: str):
    PREMIUM_EMOJIS_CACHE[name] = (char, str(emoji_id))
