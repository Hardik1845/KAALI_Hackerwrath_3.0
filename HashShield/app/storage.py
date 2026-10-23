import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from app.config import settings
from app.models import VaultItem

logger = logging.getLogger("hashshield.storage")


class StorageInterface:
    """Abstract interface for HashShield storage backends."""
    async def save_vault_item(self, item: VaultItem) -> VaultItem:
        raise NotImplementedError

    async def get_vault_items(self, user_id: str) -> List[VaultItem]:
        raise NotImplementedError

    async def save_case(self, case_dict: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def update_case(self, case_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def clear_all(self):
        raise NotImplementedError


class InMemoryStore(StorageInterface):
    """Fast, thread-safe in-memory store for local testing and standalone runs."""
    def __init__(self):
        self.vault: Dict[str, List[VaultItem]] = {}  # user_id -> List[VaultItem]
        self.cases: Dict[str, Dict[str, Any]] = {}   # case_id -> case_dict
        self.scans: Dict[str, Dict[str, Any]] = {}   # original_id -> scan_dict

    async def save_vault_item(self, item: VaultItem) -> VaultItem:
        if item.user_id not in self.vault:
            self.vault[item.user_id] = []
        self.vault[item.user_id].append(item)
        return item

    async def get_vault_items(self, user_id: str) -> List[VaultItem]:
        return self.vault.get(user_id, [])

    async def save_case(self, case_dict: Dict[str, Any]) -> Dict[str, Any]:
        self.cases[case_dict["case_id"]] = case_dict
        return case_dict

    async def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        return self.cases.get(case_id)

    async def update_case(self, case_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if case_id not in self.cases:
            return None
        self.cases[case_id].update(updates)
        self.cases[case_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self.cases[case_id]

    async def save_scan(self, scan_dict: Dict[str, Any]) -> Dict[str, Any]:
        self.scans[scan_dict["original_id"]] = scan_dict
        return scan_dict

    async def get_scan(self, original_id: str) -> Optional[Dict[str, Any]]:
        return self.scans.get(original_id)

    async def get_due_cases(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        due = []
        for case in self.cases.values():
            if case.get("status") == "sent" and case.get("due_at"):
                try:
                    due_dt = datetime.fromisoformat(case["due_at"])
                    if now >= due_dt:
                        due.append(case)
                except Exception:
                    pass
        return due

    async def clear_all(self):
        self.vault.clear()
        self.cases.clear()
        self.scans.clear()


class MongoStore(StorageInterface):
    """MongoDB storage backend via Motor async client."""
    def __init__(self, mongo_url: str):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.client = AsyncIOMotorClient(mongo_url)
        self.db = self.client.get_default_database("hashshield")
        self.vault_col = self.db.get_collection("vault")
        self.cases_col = self.db.get_collection("cases")

    async def save_vault_item(self, item: VaultItem) -> VaultItem:
        await self.vault_col.insert_one(item.model_dump())
        return item

    async def get_vault_items(self, user_id: str) -> List[VaultItem]:
        cursor = self.vault_col.find({"user_id": user_id})
        items = []
        async for doc in cursor:
            doc.pop("_id", None)
            items.append(VaultItem(**doc))
        return items

    async def save_case(self, case_dict: Dict[str, Any]) -> Dict[str, Any]:
        doc = dict(case_dict)
        await self.cases_col.insert_one(doc)
        return case_dict

    async def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.cases_col.find_one({"case_id": case_id})
        if doc:
            doc.pop("_id", None)
            return doc
        return None

    async def update_case(self, case_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = await self.cases_col.find_one_and_update(
            {"case_id": case_id},
            {"$set": updates},
            return_document=True
        )
        if res:
            res.pop("_id", None)
            return res
        return None

    async def clear_all(self):
        await self.vault_col.delete_many({})
        await self.cases_col.delete_many({})


def get_storage() -> StorageInterface:
    """Factory creating configured storage backend."""
    if settings.MONGO_URL and settings.MONGO_URL.strip():
        logger.info("Initializing MongoStore with MONGO_URL")
        return MongoStore(settings.MONGO_URL.strip())
    logger.info("MONGO_URL not set; using InMemoryStore fallback")
    return InMemoryStore()


# Global storage instance
storage = get_storage()
