import os
import logging
from typing import Dict, Tuple, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AutoProtectionBot")

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "8887193580:AAHVMkh8vSp9rVlHjVAM4B8r8XN_ZEyFsp8")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "5157557268"))

# Allow multiple comma-separated super admin IDs
raw_admin_ids = os.getenv("SUPER_ADMIN_IDS", "")
SUPER_ADMIN_IDS = set()
if raw_admin_ids:
    for aid in raw_admin_ids.split(","):
        aid = aid.strip()
        if aid.isdigit():
            SUPER_ADMIN_IDS.add(int(aid))
SUPER_ADMIN_IDS.add(SUPER_ADMIN_ID)

LOG_CHANNEL_ID_STR = os.getenv("LOG_CHANNEL_ID", "-1003445839958")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID_STR) if LOG_CHANNEL_ID_STR and LOG_CHANNEL_ID_STR.lstrip("-").isdigit() else None

# MongoDB Configuration
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://notimepass367_db_user:abbsy%40123@cluster0.wof2cvr.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
)
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

# 💎 Custom Premium Emojis mapping
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
    "insta": ("📸", "6165899765042122114"),
    "pin": ("📌", "6165582852290252628"),
    "snap": ("👻", "6163600858027135317"),
    "fb": ("📘", "6163336970941501725"),
    "link": ("🔗", "5389118804590604722"),
    "folder": ("📁", "5886223731088431288"),
    "sound": ("🔊", "6109651730872408665"),
    "tv": ("📺", "5114287571056198794"),
    "user": ("👤", "5264942233387285985"),
    "time": ("⏱", "6165894413512871182"),
    "globe": ("🌐", "6163336970941501725"),
    "one": ("1️⃣", "5345986836038694332"),
    "two": ("2️⃣", "6158868637290601091"),
    "three": ("3️⃣", "6163600858027135317"),
    "four": ("4️⃣", "6109418703126796249"),
    "box": ("📦", "5886223731088431288"),
    "search": ("🔎", "6336887317948536124"),
    "star": ("★", "6163600858027135317"),
    "warn": ("⚠️", "6165894413512871182"),
    "cross": ("❌", "5240408207666455054"),
    "bullet": ("•", "6158935325247805180")
}

PREMIUM_EMOJIS = {k: v for k, v in DEFAULT_PREMIUM_EMOJIS.items()}

def get_p_emoji(name: str) -> str:
    """Return custom premium emoji HTML tag <tg-emoji emoji-id='...'>...</tg-emoji>"""
    item = PREMIUM_EMOJIS.get(name) if isinstance(PREMIUM_EMOJIS, dict) else None
    if not item:
        item = DEFAULT_PREMIUM_EMOJIS.get(name)
    if not item:
        return '<tg-emoji emoji-id="6154310409974190743">✨</tg-emoji>'
    if isinstance(item, dict):
        char = item.get("char", "✨")
        emoji_id = item.get("id", "")
    elif isinstance(item, (tuple, list)):
        char = item[0]
        emoji_id = item[1] if len(item) > 1 else ""
    else:
        return str(item)

    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{char}</tg-emoji>'
    return char

def get_btn_emoji(name: str) -> str:
    """Return character for button fallback"""
    item = PREMIUM_EMOJIS.get(name) if isinstance(PREMIUM_EMOJIS, dict) else None
    if not item:
        item = DEFAULT_PREMIUM_EMOJIS.get(name)
    if not item:
        return ""
    if isinstance(item, dict):
        return item.get("char", "")
    elif isinstance(item, (tuple, list)):
        return item[0]
    return ""

def get_btn_emoji_id(name: str) -> Optional[str]:
    """Return custom emoji ID for icon_custom_emoji_id attribute"""
    item = PREMIUM_EMOJIS.get(name) if isinstance(PREMIUM_EMOJIS, dict) else None
    if not item:
        item = DEFAULT_PREMIUM_EMOJIS.get(name)
    if not item:
        return None
    if isinstance(item, dict):
        return item.get("id")
    elif isinstance(item, (tuple, list)) and len(item) > 1:
        return item[1]
    return None

def update_emoji_cache(name: str, char: str, emoji_id: str):
    """Update in-memory premium emoji cache dynamically."""
    PREMIUM_EMOJIS[name] = {"char": char, "id": str(emoji_id)}
