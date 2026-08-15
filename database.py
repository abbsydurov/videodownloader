import logging
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, MONGO_DB_URI, DB_NAME, SUPER_ADMIN_ID, DEFAULT_PREMIUM_EMOJIS, update_emoji_cache

logger = logging.getLogger("SocialMediaDownloaderBot.DB")

client = None
db = None

async def init_db():
    """Initialize MongoDB client, collections, indexes, and default emojis."""
    global client, db
    try:
        client = AsyncIOMotorClient(MONGO_URI or MONGO_DB_URI)
        db = client[DB_NAME]
        
        # Collection indexes
        await db.authorized_users.create_index("user_id", unique=True)
        await db.bot_users.create_index("user_id", unique=True)
        await db.custom_emojis.create_index("name", unique=True)
        await db.download_logs.create_index("downloaded_at")
        await db.download_logs.create_index("user_id")
        
        # Ensure Super Admin is always authorized
        await db.authorized_users.update_one(
            {"user_id": SUPER_ADMIN_ID},
            {"$set": {
                "user_id": SUPER_ADMIN_ID,
                "granted_by": SUPER_ADMIN_ID,
                "granted_at": datetime.utcnow().isoformat(),
                "note": "Super Admin"
            }},
            upsert=True
        )
        
        # Load saved custom premium emojis into memory cache
        async for emoji_doc in db.custom_emojis.find():
            name = emoji_doc.get("name")
            char = emoji_doc.get("char", "✨")
            emoji_id = emoji_doc.get("emoji_id", "")
            if name and emoji_id:
                update_emoji_cache(name, char, emoji_id)
                
        logger.info("✅ MongoDB connected & initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize MongoDB: {e}")
        raise e

# ==================== USER MANAGEMENT ====================
async def register_user(user_id: int, first_name: str = "", username: str = ""):
    now = datetime.utcnow().isoformat()
    await db.bot_users.update_one(
        {"user_id": int(user_id)},
        {
            "$set": {
                "user_id": int(user_id),
                "first_name": first_name or "",
                "username": username or "",
                "last_active": now
            },
            "$setOnInsert": {
                "joined_at": now,
                "total_downloads": 0
            }
        },
        upsert=True
    )

async def increment_user_download(user_id: int):
    await db.bot_users.update_one(
        {"user_id": int(user_id)},
        {"$inc": {"total_downloads": 1}, "$set": {"last_active": datetime.utcnow().isoformat()}}
    )

async def get_all_users():
    cursor = db.bot_users.find({})
    return await cursor.to_list(length=10000)

async def get_total_users_count() -> int:
    return await db.bot_users.count_documents({})

# ==================== ACCESS CONTROL ====================
async def is_user_authorized(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    doc = await db.authorized_users.find_one({"user_id": int(user_id)})
    return doc is not None

async def grant_user_access(user_id: int, granted_by: int, note: str = "") -> bool:
    await db.authorized_users.update_one(
        {"user_id": int(user_id)},
        {"$set": {
            "user_id": int(user_id),
            "granted_by": int(granted_by),
            "granted_at": datetime.utcnow().isoformat(),
            "note": note
        }},
        upsert=True
    )
    return True

async def revoke_user_access(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return False
    result = await db.authorized_users.delete_one({"user_id": int(user_id)})
    return result.deleted_count > 0

async def get_all_authorized_users():
    cursor = db.authorized_users.find({}).sort("granted_at", -1)
    return await cursor.to_list(length=1000)

# ==================== EMOJI PERSISTENCE & MANAGEMENT ====================
async def save_custom_emoji(name: str, emoji_id: str, char: str = "✨", updated_by: int = 0) -> bool:
    name_clean = name.strip().lower()
    emoji_id_clean = emoji_id.strip()
    now = datetime.utcnow().isoformat()
    
    await db.custom_emojis.update_one(
        {"name": name_clean},
        {"$set": {
            "name": name_clean,
            "emoji_id": emoji_id_clean,
            "char": char,
            "updated_by": int(updated_by),
            "updated_at": now
        }},
        upsert=True
    )
    update_emoji_cache(name_clean, char, emoji_id_clean)
    return True

async def get_all_custom_emojis():
    cursor = db.custom_emojis.find({}).sort("name", 1)
    return await cursor.to_list(length=100)

async def delete_custom_emoji(name: str) -> bool:
    name_clean = name.strip().lower()
    res = await db.custom_emojis.delete_one({"name": name_clean})
    if name_clean in DEFAULT_PREMIUM_EMOJIS:
        update_emoji_cache(name_clean, DEFAULT_PREMIUM_EMOJIS[name_clean][0], DEFAULT_PREMIUM_EMOJIS[name_clean][1])
    return res.deleted_count > 0

# ==================== DOWNLOAD LOGGING & ANALYTICS ====================
async def log_download_request(user_id: int, platform: str, url: str, status: str = "success", title: str = "", media_type: str = "video"):
    now = datetime.utcnow().isoformat()
    log_doc = {
        "user_id": int(user_id),
        "platform": platform.lower(),
        "url": url,
        "status": status,
        "title": title or "",
        "media_type": media_type,
        "downloaded_at": now
    }
    await db.download_logs.insert_one(log_doc)
    await increment_user_download(user_id)

async def get_recent_download_logs(limit: int = 30):
    cursor = db.download_logs.find({}).sort("downloaded_at", -1).limit(limit)
    return await cursor.to_list(length=limit)

async def get_system_stats():
    total_downloads = await db.download_logs.count_documents({})
    total_users = await db.bot_users.count_documents({})
    total_authorized = await db.authorized_users.count_documents({})
    
    # Platform counts
    insta_count = await db.download_logs.count_documents({"platform": "instagram"})
    pin_count = await db.download_logs.count_documents({"platform": "pinterest"})
    snap_count = await db.download_logs.count_documents({"platform": "snapchat"})
    fb_count = await db.download_logs.count_documents({"platform": "facebook"})
    
    return {
        "total_downloads": total_downloads,
        "total_users": total_users,
        "total_authorized": total_authorized,
        "platforms": {
            "instagram": insta_count,
            "pinterest": pin_count,
            "snapchat": snap_count,
            "facebook": fb_count
        }
    }
