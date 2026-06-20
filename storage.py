"""
医疗器械 QMS - 发布存储管理
Medical Device QMS - Release Storage Manager
发布记录的持久化存储与检索
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any

from models import (
    ReleaseRecord, ReleaseType, ReleaseStatus,
    PreCheckResult, CheckItem, CheckItemStatus,
    ApprovalFlow, ApprovalStep, ApprovalRole, ApprovalStatus,
    GrayscalePhase, FactoryTier, RollbackRecord,
)
from config import CONFIG


class ReleaseStorage:
    _instance = None

    def __init__(self):
        self.data_dir = Path(CONFIG["storage"]["data_dir"])
        self.releases_dir = self.data_dir / "releases"
        self._ensure_storage()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _ensure_storage(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.releases_dir.mkdir(parents=True, exist_ok=True)

    def save_release(self, release: ReleaseRecord) -> None:
        file_path = self.releases_dir / f"{release.release_id}.json"
        data = self._release_to_dict(release)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_release(self, release_id: str) -> Optional[ReleaseRecord]:
        file_path = self.releases_dir / f"{release_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._dict_to_release(data)

    def list_releases(self, status: ReleaseStatus = None,
                      release_type: ReleaseType = None,
                      start_date: datetime = None,
                      end_date: datetime = None,
                      version: str = None) -> List[ReleaseRecord]:
        releases = []
        if not self.releases_dir.exists():
            return releases

        for file in self.releases_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                created_at = datetime.fromisoformat(data["created_at"])

                if status and data["status"] != status.value:
                    continue
                if release_type and data["release_type"] != release_type.value:
                    continue
                if start_date and created_at < start_date:
                    continue
                if end_date and created_at > end_date:
                    continue
                if version and version not in data["version"]:
                    continue

                releases.append(self._dict_to_release(data))
            except Exception:
                continue

        return sorted(releases, key=lambda r: r.created_at, reverse=True)

    def delete_release(self, release_id: str) -> bool:
        file_path = self.releases_dir / f"{release_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def get_release_count(self) -> int:
        if not self.releases_dir.exists():
            return 0
        return len(list(self.releases_dir.glob("*.json")))

    def _release_to_dict(self, release: ReleaseRecord) -> Dict[str, Any]:
        data = {
            "release_id": release.release_id,
            "version": release.version,
            "release_type": release.release_type.value,
            "status": release.status.value,
            "title": release.title,
            "description": release.description,
            "change_control_id": release.change_control_id,
            "requester": release.requester,
            "created_at": release.created_at.isoformat(),
            "previous_version": release.previous_version,
            "target_zones": release.target_zones,
        }

        if release.pre_check_result:
            data["pre_check_result"] = self._precheck_to_dict(release.pre_check_result)

        if release.approval_flow:
            data["approval_flow"] = self._approval_to_dict(release.approval_flow)

        data["grayscale_phases"] = [
            self._phase_to_dict(p) for p in release.grayscale_phases
        ]

        data["rollback_records"] = [
            self._rollback_to_dict(r) for r in release.rollback_records
        ]

        return data

    def _precheck_to_dict(self, result: PreCheckResult) -> Dict:
        return {
            "release_id": result.release_id,
            "overall_pass": result.overall_pass,
            "started_at": result.started_at.isoformat() if result.started_at else None,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            "checks": [
                {
                    "check_id": c.check_id,
                    "name": c.name,
                    "category": c.category,
                    "status": c.status.value,
                    "description": c.description,
                    "suggestion": c.suggestion,
                    "evidence": c.evidence,
                    "checked_at": c.checked_at.isoformat() if c.checked_at else None,
                }
                for c in result.checks
            ],
        }

    def _approval_to_dict(self, flow: ApprovalFlow) -> Dict:
        return {
            "release_id": flow.release_id,
            "is_hotfix": flow.is_hotfix,
            "hotfix_reason": flow.hotfix_reason,
            "current_step_index": flow.current_step_index,
            "started_at": flow.started_at.isoformat() if flow.started_at else None,
            "completed_at": flow.completed_at.isoformat() if flow.completed_at else None,
            "steps": [
                {
                    "role": s.role.value,
                    "status": s.status.value,
                    "approver": s.approver,
                    "comment": s.comment,
                    "approved_at": s.approved_at.isoformat() if s.approved_at else None,
                    "is_parallel": s.is_parallel,
                }
                for s in flow.steps
            ],
        }

    def _phase_to_dict(self, phase: GrayscalePhase) -> Dict:
        return {
            "phase_id": phase.phase_id,
            "name": phase.name,
            "tier": phase.tier.value,
            "zones": phase.zones,
            "status": phase.status,
            "started_at": phase.started_at.isoformat() if phase.started_at else None,
            "completed_at": phase.completed_at.isoformat() if phase.completed_at else None,
            "monitor_interval_minutes": phase.monitor_interval_minutes,
            "duration_minutes": phase.duration_minutes,
        }

    def _rollback_to_dict(self, rollback: RollbackRecord) -> Dict:
        return {
            "rollback_id": rollback.rollback_id,
            "release_id": rollback.release_id,
            "reason": rollback.reason,
            "affected_zones": rollback.affected_zones,
            "affected_batches": rollback.affected_batches,
            "from_version": rollback.from_version,
            "to_version": rollback.to_version,
            "started_at": rollback.started_at.isoformat() if rollback.started_at else None,
            "completed_at": rollback.completed_at.isoformat() if rollback.completed_at else None,
            "is_drill": rollback.is_drill,
            "report_generated": rollback.report_generated,
        }

    def _dict_to_release(self, data: Dict) -> ReleaseRecord:
        release = ReleaseRecord(
            release_id=data["release_id"],
            version=data["version"],
            release_type=ReleaseType(data["release_type"]),
            status=ReleaseStatus(data["status"]),
            title=data.get("title", ""),
            description=data.get("description", ""),
            change_control_id=data.get("change_control_id", ""),
            requester=data.get("requester", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            previous_version=data.get("previous_version", ""),
            target_zones=data.get("target_zones", []),
        )

        if "pre_check_result" in data:
            release.pre_check_result = self._dict_to_precheck(data["pre_check_result"])

        if "approval_flow" in data:
            release.approval_flow = self._dict_to_approval(data["approval_flow"])

        if "grayscale_phases" in data:
            release.grayscale_phases = [
                self._dict_to_phase(p) for p in data["grayscale_phases"]
            ]

        if "rollback_records" in data:
            release.rollback_records = [
                self._dict_to_rollback(r) for r in data["rollback_records"]
            ]

        return release

    def _dict_to_precheck(self, data: Dict) -> PreCheckResult:
        result = PreCheckResult(
            release_id=data["release_id"],
            overall_pass=data["overall_pass"],
        )
        if data.get("started_at"):
            result.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            result.completed_at = datetime.fromisoformat(data["completed_at"])

        result.checks = [
            CheckItem(
                check_id=c["check_id"],
                name=c["name"],
                category=c["category"],
                status=CheckItemStatus(c["status"]),
                description=c.get("description", ""),
                suggestion=c.get("suggestion", ""),
                evidence=c.get("evidence", {}),
                checked_at=datetime.fromisoformat(c["checked_at"]) if c.get("checked_at") else None,
            )
            for c in data.get("checks", [])
        ]
        return result

    def _dict_to_approval(self, data: Dict) -> ApprovalFlow:
        flow = ApprovalFlow(
            release_id=data["release_id"],
            is_hotfix=data.get("is_hotfix", False),
            hotfix_reason=data.get("hotfix_reason", ""),
            current_step_index=data.get("current_step_index", 0),
        )
        if data.get("started_at"):
            flow.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            flow.completed_at = datetime.fromisoformat(data["completed_at"])

        flow.steps = [
            ApprovalStep(
                role=ApprovalRole(s["role"]),
                status=ApprovalStatus(s["status"]),
                approver=s.get("approver"),
                comment=s.get("comment", ""),
                approved_at=datetime.fromisoformat(s["approved_at"]) if s.get("approved_at") else None,
                is_parallel=s.get("is_parallel", False),
            )
            for s in data.get("steps", [])
        ]
        return flow

    def _dict_to_phase(self, data: Dict) -> GrayscalePhase:
        phase = GrayscalePhase(
            phase_id=data["phase_id"],
            name=data["name"],
            tier=FactoryTier(data["tier"]),
            zones=data.get("zones", []),
            status=data.get("status", "pending"),
            monitor_interval_minutes=data.get("monitor_interval_minutes", 5),
            duration_minutes=data.get("duration_minutes", 60),
        )
        if data.get("started_at"):
            phase.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            phase.completed_at = datetime.fromisoformat(data["completed_at"])
        return phase

    def _dict_to_rollback(self, data: Dict) -> RollbackRecord:
        rollback = RollbackRecord(
            rollback_id=data["rollback_id"],
            release_id=data["release_id"],
            reason=data.get("reason", ""),
            affected_zones=data.get("affected_zones", []),
            affected_batches=data.get("affected_batches", []),
            from_version=data.get("from_version", ""),
            to_version=data.get("to_version", ""),
            is_drill=data.get("is_drill", False),
            report_generated=data.get("report_generated", False),
        )
        if data.get("started_at"):
            rollback.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            rollback.completed_at = datetime.fromisoformat(data["completed_at"])
        return rollback
