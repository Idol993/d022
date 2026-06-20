"""
医疗器械 QMS - 熔断机制与自动回滚
Medical Device QMS - Circuit Breaker & Auto Rollback
监控阈值检测、熔断触发、自动回滚、结构化报告
"""

from datetime import datetime
from typing import List, Dict, Optional, Tuple
import uuid

from models import (
    ReleaseRecord, GrayscalePhase, MonitorMetrics, RollbackRecord,
    CircuitBreakerConfig, ReleaseStatus, FactoryTier,
)
from config import CONFIG, get_circuit_breaker_config
from audit_log import AuditLogger
from notification import NotificationService
from grayscale import MetricsCollector, GrayscaleReleaseManager
from zone_store import FactoryZoneStore


class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig = None):
        self.config = config or get_circuit_breaker_config()
        self.audit_logger = AuditLogger()
        self.notifier = NotificationService()
        self.consecutive_failures: Dict[str, int] = {}
        self.is_tripped = False
        self.trip_reason = ""
        self.trip_time: Optional[datetime] = None

    def check_metrics(self, metrics: MonitorMetrics, zone_id: str) -> Tuple[bool, str]:
        threshold_violations = []

        if metrics.deviation_rate > self.config.deviation_rate_threshold:
            threshold_violations.append(
                f"偏差发生率 {metrics.deviation_rate}% > 阈值 {self.config.deviation_rate_threshold}%"
            )

        if metrics.anomaly_delay_rate > self.config.anomaly_delay_rate_threshold:
            threshold_violations.append(
                f"异常单处理延迟率 {metrics.anomaly_delay_rate}% > 阈值 {self.config.anomaly_delay_rate_threshold}%"
            )

        if metrics.approval_block_rate > self.config.approval_block_rate_threshold:
            threshold_violations.append(
                f"审批流程阻塞率 {metrics.approval_block_rate}% > 阈值 {self.config.approval_block_rate_threshold}%"
            )

        if threshold_violations:
            self.consecutive_failures[zone_id] = self.consecutive_failures.get(zone_id, 0) + 1

            if self.consecutive_failures[zone_id] >= self.config.consecutive_failures_trigger:
                reason = "; ".join(threshold_violations)
                return True, reason
        else:
            self.consecutive_failures[zone_id] = 0

        return False, ""

    def trip(self, release: ReleaseRecord, reason: str,
             affected_zones: List[str]) -> None:
        if self.is_tripped:
            return

        self.is_tripped = True
        self.trip_reason = reason
        self.trip_time = datetime.now()

        release.status = ReleaseStatus.GRAYSCALE_FAILED

        self.audit_logger.log_action(
            actor="system",
            action="circuit_breaker_triggered",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "reason": reason,
                "affected_zones": affected_zones,
                "consecutive_failures": self.config.consecutive_failures_trigger,
            },
            is_critical=True,
        )

        self.notifier.notify_circuit_breaker(
            release_id=release.release_id,
            version=release.version,
            reason=reason,
            affected_zones=affected_zones,
        )

    def reset(self) -> None:
        self.is_tripped = False
        self.trip_reason = ""
        self.trip_time = None
        self.consecutive_failures.clear()


class RollbackManager:
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.notifier = NotificationService()
        self.circuit_breaker = CircuitBreaker()
        self.release_manager = GrayscaleReleaseManager()
        self.metrics_collector = MetricsCollector()
        self.zone_store = FactoryZoneStore()

    def execute_rollback(self, release: ReleaseRecord, reason: str,
                         affected_zones: List[str] = None,
                         is_drill: bool = False) -> RollbackRecord:
        if not release.previous_version:
            raise ValueError("未设置回滚目标版本（previous_version）")

        rollback_id = str(uuid.uuid4())
        rollback = RollbackRecord(
            rollback_id=rollback_id,
            release_id=release.release_id,
            reason=reason,
            affected_zones=affected_zones or [],
            from_version=release.version,
            to_version=release.previous_version,
            started_at=datetime.now(),
            is_drill=is_drill,
        )

        release.rollback_records.append(rollback)
        release.status = ReleaseStatus.ROLLING_BACK

        rollback_label = "回滚演练" if is_drill else "回滚"
        self.audit_logger.log_action(
            actor="system",
            action=f"rollback_started{'_drill' if is_drill else ''}",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "rollback_id": rollback_id,
                "from_version": release.version,
                "to_version": release.previous_version,
                "affected_zones": affected_zones,
                "reason": reason,
            },
            is_critical=not is_drill,
        )

        self._perform_rollback(release, rollback)

        rollback.completed_at = datetime.now()
        release.status = ReleaseStatus.ROLLED_BACK

        self.audit_logger.log_action(
            actor="system",
            action=f"rollback_completed{'_drill' if is_drill else ''}",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "rollback_id": rollback_id,
                "duration_seconds": self._rollback_duration_seconds(rollback),
            },
            is_critical=not is_drill,
        )

        self.notifier.notify_rollback_complete(
            release_id=release.release_id,
            version=release.version,
            rollback_version=release.previous_version,
            affected_zones=rollback.affected_zones,
        )

        rollback_report = self.generate_rollback_report(release, rollback)
        rollback.report_generated = True

        return rollback

    def _perform_rollback(self, release: ReleaseRecord, rollback: RollbackRecord):
        all_zones = self.zone_store.get_all_zones()

        if not rollback.affected_zones:
            rollback.affected_zones = [z.zone_id for z in all_zones]

        rollback_count = self.zone_store.batch_update_version(
            rollback.affected_zones, rollback.to_version
        )

    def _rollback_duration_seconds(self, rollback: RollbackRecord) -> float:
        if rollback.started_at and rollback.completed_at:
            delta = rollback.completed_at - rollback.started_at
            return round(delta.total_seconds(), 2)
        return 0.0

    def generate_rollback_report(self, release: ReleaseRecord,
                                 rollback: RollbackRecord) -> Dict:
        report = {
            "report_type": "rollback_report",
            "rollback_id": rollback.rollback_id,
            "release_id": release.release_id,
            "release_version": release.version,
            "rollback_to_version": rollback.to_version,
            "rollback_reason": rollback.reason,
            "is_drill": rollback.is_drill,
            "timeline": {
                "started_at": rollback.started_at.isoformat() if rollback.started_at else None,
                "completed_at": rollback.completed_at.isoformat() if rollback.completed_at else None,
                "duration_seconds": self._rollback_duration_seconds(rollback),
            },
            "impact_analysis": {
                "affected_zones": rollback.affected_zones,
                "affected_batches": rollback.affected_batches,
                "estimated_impact_scope": "limited" if len(rollback.affected_zones) <= 2 else "wide",
            },
            "root_cause": {
                "description": rollback.reason,
                "category": "system_anomaly" if not rollback.is_drill else "drill",
            },
            "remediation_actions": [
                "版本已回滚至上一稳定版本",
                "业务监控已重启并持续观察",
                "问题已记录并将进入根本原因分析流程",
            ],
            "follow_up_items": [
                "组织技术团队分析异常根因",
                "评估是否需要启动偏差/CAPA流程",
                "验证修复后重新安排发布",
            ],
            "generated_at": datetime.now().isoformat(),
        }

        self._save_rollback_report(rollback.rollback_id, report)

        return report

    def _save_rollback_report(self, rollback_id: str, report: Dict):
        import json
        import os
        from pathlib import Path

        reports_dir = Path(CONFIG["storage"]["reports_dir"]) / "rollback"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_file = reports_dir / f"rollback_report_{rollback_id}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def monitor_and_check(self, release: ReleaseRecord) -> Dict:
        result = {
            "status": "normal",
            "violations": [],
            "metrics": {},
            "action_taken": None,
        }

        active_phases = self.release_manager.get_active_phases(release)
        if not active_phases:
            return result

        for phase in active_phases:
            for zone_id in phase.zones:
                metrics = self.metrics_collector.collect_metrics(zone_id)
                result["metrics"][zone_id] = {
                    "deviation_rate": metrics.deviation_rate,
                    "anomaly_delay_rate": metrics.anomaly_delay_rate,
                    "approval_block_rate": metrics.approval_block_rate,
                }

                is_tripped, reason = self.circuit_breaker.check_metrics(metrics, zone_id)
                if is_tripped:
                    result["status"] = "circuit_breaker_tripped"
                    result["violations"].append({
                        "zone_id": zone_id,
                        "reason": reason,
                    })

        if result["status"] == "circuit_breaker_tripped":
            affected_zones = [v["zone_id"] for v in result["violations"]]
            self.circuit_breaker.trip(release, result["violations"][0]["reason"], affected_zones)

            if self.circuit_breaker.config.auto_rollback_enabled:
                self.execute_rollback(
                    release=release,
                    reason=result["violations"][0]["reason"],
                    affected_zones=affected_zones,
                )
                result["action_taken"] = "auto_rollback"

        return result

    def get_circuit_breaker_status(self) -> Dict:
        return {
            "is_tripped": self.circuit_breaker.is_tripped,
            "trip_reason": self.circuit_breaker.trip_reason,
            "trip_time": self.circuit_breaker.trip_time.isoformat() if self.circuit_breaker.trip_time else None,
            "consecutive_failures": self.circuit_breaker.consecutive_failures,
            "config": {
                "deviation_rate_threshold": self.circuit_breaker.config.deviation_rate_threshold,
                "anomaly_delay_rate_threshold": self.circuit_breaker.config.anomaly_delay_rate_threshold,
                "approval_block_rate_threshold": self.circuit_breaker.config.approval_block_rate_threshold,
                "consecutive_failures_trigger": self.circuit_breaker.config.consecutive_failures_trigger,
                "auto_rollback_enabled": self.circuit_breaker.config.auto_rollback_enabled,
            },
        }

    def reset_circuit_breaker(self) -> None:
        self.circuit_breaker.reset()


def trigger_rollback(release: ReleaseRecord, reason: str,
                     affected_zones: List[str] = None,
                     is_drill: bool = False) -> RollbackRecord:
    manager = RollbackManager()
    return manager.execute_rollback(release, reason, affected_zones, is_drill)
