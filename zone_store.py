"""
医疗器械 QMS - 厂区版本状态存储
Medical Device QMS - Factory Zone Version Store
统一管理厂区版本状态，确保灰度发布/回滚/查询数据一致
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from models import FactoryZone, FactoryTier
from config import CONFIG


class FactoryZoneStore:
    _instance = None

    def __init__(self):
        self.data_dir = Path(CONFIG["storage"]["data_dir"])
        self.zones_file = self.data_dir / "factory_zones.json"
        self._ensure_storage()
        self._init_zones()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_storage(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _init_zones(self):
        if self.zones_file.exists():
            return

        zones = []
        for z in CONFIG["factory_zones"]:
            zones.append({
                "zone_id": z["zone_id"],
                "name": z["name"],
                "tier": z["tier"].value,
                "description": z["description"],
                "current_version": z["current_version"],
                "is_active": True,
                "last_updated": datetime.now().isoformat(),
                "last_release_id": "",
            })

        with open(self.zones_file, "w", encoding="utf-8") as f:
            json.dump(zones, f, ensure_ascii=False, indent=2)

    def get_all_zones(self) -> List[FactoryZone]:
        if not self.zones_file.exists():
            self._init_zones()

        with open(self.zones_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        zones = []
        for z in data:
            zone = FactoryZone(
                zone_id=z["zone_id"],
                name=z["name"],
                tier=FactoryTier(z["tier"]),
                description=z.get("description", ""),
                current_version=z.get("current_version", ""),
                is_active=z.get("is_active", True),
            )
            zones.append(zone)
        return zones

    def get_zone_by_id(self, zone_id: str) -> Optional[FactoryZone]:
        zones = self.get_all_zones()
        for z in zones:
            if z.zone_id == zone_id:
                return z
        return None

    def get_zones_by_tier(self, tier: FactoryTier) -> List[FactoryZone]:
        zones = self.get_all_zones()
        return [z for z in zones if z.tier == tier and z.is_active]

    def update_zone_version(self, zone_id: str, version: str,
                            release_id: str = "") -> bool:
        zones_data = self._load_zones_data()
        found = False

        for z in zones_data:
            if z["zone_id"] == zone_id:
                z["current_version"] = version
                z["last_updated"] = datetime.now().isoformat()
                z["last_release_id"] = release_id
                found = True
                break

        if found:
            self._save_zones_data(zones_data)
        return found

    def batch_update_version(self, zone_ids: List[str], version: str,
                             release_id: str = "") -> int:
        count = 0
        for zone_id in zone_ids:
            if self.update_zone_version(zone_id, version, release_id):
                count += 1
        return count

    def get_current_system_version(self) -> str:
        zones = self.get_all_zones()
        if zones:
            return zones[0].current_version
        return "unknown"

    def get_zones_status(self) -> List[Dict]:
        zones = self.get_all_zones()
        return [
            {
                "zone_id": z.zone_id,
                "name": z.name,
                "tier": z.tier.value,
                "current_version": z.current_version,
                "is_active": z.is_active,
            }
            for z in zones
        ]

    def get_version_distribution(self) -> Dict[str, List[str]]:
        dist = {}
        zones = self.get_all_zones()
        for z in zones:
            v = z.current_version
            if v not in dist:
                dist[v] = []
            dist[v].append(z.zone_id)
        return dist

    def is_zone_affected_by_release(self, zone_id: str,
                                    release_id: str) -> bool:
        zones_data = self._load_zones_data()
        for z in zones_data:
            if z["zone_id"] == zone_id and z.get("last_release_id") == release_id:
                return True
        return False

    def reset_all(self, version: str = "v2.3.0"):
        zones_data = self._load_zones_data()
        for z in zones_data:
            z["current_version"] = version
            z["last_updated"] = datetime.now().isoformat()
            z["last_release_id"] = ""
        self._save_zones_data(zones_data)

    def _load_zones_data(self) -> List[Dict]:
        if not self.zones_file.exists():
            self._init_zones()
        with open(self.zones_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_zones_data(self, data: List[Dict]):
        with open(self.zones_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
