import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME, logger

client: Optional[AsyncIOMotorClient] = None
db = None

users_col = None
authorized_col = None
logs_col = None
emojis_col = None

async def init_db():
    global client, db, users_col, authorized_col, logs_col, emojis_col
    try:
        # Ignore dummy placeholder URIs
        if not MONGO_URI or "test:test@cluster0.mongodb.net" in MONGO_URI:
            logger.warning("⚠️ Running with memory cache (No custom MongoDB URI configured).")
            return

        client = AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000
        )
        db = client[DB_NAME]
        users_col = db["users"]
        authorized_col = db["authorized_users"]
        logs_col = db["download_logs"]
        emojis_col = db["custom_emojis"]
        
        # Verify connection
        await client.admin.command('ping')
        logger.info("✅ MongoDB connected & initialized successfully.")
    except Exception as e:
        logger.warning(f"⚠️ MongoDB connection notice: {e}. Bot will run smoothly in resilient mode.")
        client = None
        db = None
        users_col = None
        authorized_col = None
        logs_col = None
        emojis_col = None

async def register_user(user_id: int, first_name: str = "", username: str = ""):
    if users_col is None:
        return
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "first_name": first_name,
                    "username": username,
                    "last_seen": datetime.utcnow()
                },
                "$setOnInsert": {
                    "joined_at": datetime.utcnow()
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.warning(f"DB register_user error: {e}")

async def is_user_authorized(user_id: int) -> bool:
    if authorized_col is None:
        return False
    try:
        doc = await authorized_col.find_one({"user_id": user_id})
        return doc is not None
    except Exception:
        return False

async def grant_user_access(user_id: int, granted_by: int):
    if authorized_col is None:
        return
    try:
        await authorized_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "granted_by": granted_by, "granted_at": datetime.utcnow()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"DB grant_user_access error: {e}")

async def revoke_user_access(user_id: int):
    if authorized_col is None:
        return
    try:
        await authorized_col.delete_one({"user_id": user_id})
    except Exception as e:
        logger.error(f"DB revoke_user_access error: {e}")

async def log_download_request(user_id: int, platform: str, url: str, status: str = "success", title: str = ""):
    if logs_col is None:
        return
    try:
        await logs_col.insert_one({
            "user_id": user_id,
            "platform": platform,
            "url": url,
            "status": status,
            "title": title,
            "downloaded_at": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.warning(f"DB log_download_request error: {e}")

async def get_recent_download_logs(limit: int = 20) -> List[Dict[str, Any]]:
    if logs_col is None:
        return []
    try:
        cursor = logs_col.find().sort("_id", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []

async def get_all_users() -> List[Dict[str, Any]]:
    if users_col is None:
        return []
    try:
        cursor = users_col.find()
        return await cursor.to_list(length=100000)
    except Exception:
        return []

async def get_system_stats() -> Dict[str, Any]:
    stats = {
        "total_users": 0,
        "total_downloads": 0,
        "total_authorized": 0,
        "platforms": {
            "instagram": 0,
            "pinterest": 0,
            "snapchat": 0,
            "facebook": 0
        }
    }
    if db is None:
        return stats
    try:
        stats["total_users"] = await users_col.count_documents({})
        stats["total_downloads"] = await logs_col.count_documents({})
        stats["total_authorized"] = await authorized_col.count_documents({})
        for p in stats["platforms"].keys():
            stats["platforms"][p] = await logs_col.count_documents({"platform": p, "status": "success"})
    except Exception as e:
        logger.warning(f"DB get_system_stats error: {e}")
    return stats

async def save_custom_emoji(name: str, emoji_id: str, char: str = "✨", updated_by: int = 0) -> bool:
    if emojis_col is None:
        return False
    try:
        await emojis_col.update_one(
            {"name": name},
            {"$set": {"name": name, "emoji_id": emoji_id, "char": char, "updated_by": updated_by, "updated_at": datetime.utcnow()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"DB save_custom_emoji error: {e}")
        return False

async def get_all_custom_emojis() -> List[Dict[str, Any]]:
    if emojis_col is None:
        return []
    try:
        cursor = emojis_col.find()
        return await cursor.to_list(length=200)
    except Exception:
        return []

async def delete_custom_emoji(name: str) -> bool:
    if emojis_col is None:
        return False
    try:
        res = await emojis_col.delete_one({"name": name})
        return res.deleted_count > 0
    except Exception:
        return False
