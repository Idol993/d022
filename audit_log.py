"""
医疗器械 QMS - 合规审计日志模块
Medical Device QMS - Compliance Audit Log Module
GxP 合规审计日志，不可篡改，支持检索与导出
"""

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from models import AuditLogEntry
from config import CONFIG


class AuditLogger:
    _instance = None

    def __init__(self):
        self.log_file = CONFIG["storage"]["audit_log_file"]
        self._ensure_log_file()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_log_file(self):
        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.touch()

    def log(self, entry: AuditLogEntry) -> None:
        log_entry = {
            "log_id": entry.log_id,
            "timestamp": entry.timestamp.isoformat(),
            "actor": entry.actor,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "details": entry.details,
            "ip_address": entry.ip_address,
            "is_critical": entry.is_critical,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def log_action(self, actor: str, action: str, resource_type: str,
                   resource_id: str, details: Dict[str, Any] = None,
                   is_critical: bool = False) -> AuditLogEntry:
        entry = AuditLogEntry.create(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            is_critical=is_critical,
        )
        self.log(entry)
        return entry

    def query(self, start_time: Optional[datetime] = None,
              end_time: Optional[datetime] = None,
              actor: Optional[str] = None,
              action: Optional[str] = None,
              resource_type: Optional[str] = None,
              resource_id: Optional[str] = None,
              is_critical: Optional[bool] = None) -> List[AuditLogEntry]:
        results = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line.strip())
                timestamp = datetime.fromisoformat(data["timestamp"])

                if start_time and timestamp < start_time:
                    continue
                if end_time and timestamp > end_time:
                    continue
                if actor and data["actor"] != actor:
                    continue
                if action and data["action"] != action:
                    continue
                if resource_type and data["resource_type"] != resource_type:
                    continue
                if resource_id and data["resource_id"] != resource_id:
                    continue
                if is_critical is not None and data["is_critical"] != is_critical:
                    continue

                entry = AuditLogEntry(
                    log_id=data["log_id"],
                    timestamp=timestamp,
                    actor=data["actor"],
                    action=data["action"],
                    resource_type=data["resource_type"],
                    resource_id=data["resource_id"],
                    details=data.get("details", {}),
                    ip_address=data.get("ip_address", ""),
                    is_critical=data.get("is_critical", False),
                )
                results.append(entry)

        return results

    def export_logs(self, output_file: str,
                    start_time: Optional[datetime] = None,
                    end_time: Optional[datetime] = None,
                    format: str = "json") -> str:
        logs = self.query(start_time=start_time, end_time=end_time)

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump([
                    {
                        "log_id": l.log_id,
                        "timestamp": l.timestamp.isoformat(),
                        "actor": l.actor,
                        "action": l.action,
                        "resource_type": l.resource_type,
                        "resource_id": l.resource_id,
                        "details": l.details,
                        "is_critical": l.is_critical,
                    }
                    for l in logs
                ], f, ensure_ascii=False, indent=2)
        elif format == "csv":
            import csv
            with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "日志ID", "时间", "操作人", "操作", "资源类型",
                    "资源ID", "详情", "是否关键操作"
                ])
                for l in logs:
                    writer.writerow([
                        l.log_id,
                        l.timestamp.isoformat(),
                        l.actor,
                        l.action,
                        l.resource_type,
                        l.resource_id,
                        json.dumps(l.details, ensure_ascii=False),
                        "是" if l.is_critical else "否",
                    ])

        return output_file

    def get_log_count(self) -> int:
        count = 0
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
