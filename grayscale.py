"""
医疗器械 QMS - 厂区灰度发布与监控
Medical Device QMS - Factory Grayscale Release & Monitoring
支持分级灰度、实时监控指标采集
"""

import time
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import uuid

from models import (
    ReleaseRecord, GrayscalePhase, FactoryZone, MonitorMetrics,
    FactoryTier, ReleaseStatus,
)
from config import CONFIG, get_circuit_breaker_config
from audit_log import AuditLogger
from notification import NotificationService
from zone_store import FactoryZoneStore


class MetricsCollector:
    def __init__(self):
        self.mock_mode = True

    def collect_metrics(self, zone_id: str) -> MonitorMetrics:
        if self.mock_mode:
            return self._mock_collect(zone_id)
        return self._api_collect(zone_id)

    def _mock_collect(self, zone_id: str) -> MonitorMetrics:
        return MonitorMetrics(
            timestamp=datetime.now(),
            zone_id=zone_id,
            deviation_rate=round(random.uniform(0.1, 3.0), 2),
            anomaly_delay_rate=round(random.uniform(0.5, 7.0), 2),
            approval_block_rate=round(random.uniform(1.0, 12.0), 2),
            additional_metrics={
                "system_availability": round(random.uniform(99.0, 99.99), 2),
                "response_time_ms": round(random.uniform(50, 500), 0),
            },
        )

    def _api_collect(self, zone_id: str) -> MonitorMetrics:
        return MonitorMetrics(
            timestamp=datetime.now(),
            zone_id=zone_id,
            deviation_rate=0.0,
            anomaly_delay_rate=0.0,
            approval_block_rate=0.0,
        )


class GrayscaleReleaseManager:
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.notifier = NotificationService()
        self.metrics_collector = MetricsCollector()
        self.cb_config = get_circuit_breaker_config()
        self.zone_store = FactoryZoneStore()

    def init_grayscale_phases(self, release: ReleaseRecord) -> List[GrayscalePhase]:
        phases_config = CONFIG["grayscale"]["default_phases"]

        if release.release_type.value == "hotfix":
            phases_count = CONFIG["grayscale"]["hotfix_phases_count"]
            phases_config = phases_config[:phases_count]

        phases = []
        for i, phase_cfg in enumerate(phases_config):
            zones_in_tier = [
                z.zone_id for z in self.zone_store.get_zones_by_tier(phase_cfg["tier"])
            ]

            phase = GrayscalePhase(
                phase_id=f"phase_{i+1}_{str(uuid.uuid4())[:8]}",
                name=phase_cfg["name"],
                tier=phase_cfg["tier"],
                zones=zones_in_tier,
                status="pending",
                monitor_interval_minutes=phase_cfg["monitor_interval_minutes"],
                duration_minutes=phase_cfg["duration_minutes"],
            )
            phases.append(phase)

        release.grayscale_phases = phases
        return phases

    def start_release(self, release: ReleaseRecord) -> ReleaseStatus:
        if release.status != ReleaseStatus.APPROVED:
            raise ValueError(f"发布状态不正确: {release.status.value}，需要审批通过")

        if not release.grayscale_phases:
            self.init_grayscale_phases(release)

        release.status = ReleaseStatus.GRAYSCALE_IN_PROGRESS
        release.previous_version = self.zone_store.get_current_system_version()

        self.audit_logger.log_action(
            actor="system",
            action="grayscale_release_started",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "version": release.version,
                "phases_count": len(release.grayscale_phases),
                "previous_version": release.previous_version,
            },
            is_critical=True,
        )

        self.notifier.notify_release_status(
            release_id=release.release_id,
            version=release.version,
            status="灰度发布启动",
            extra_info=(
                f"发布版本: {release.version}\n"
                f"原版本: {release.previous_version}\n"
                f"灰度阶段数: {len(release.grayscale_phases)}\n"
                f"系统将按预设阶段逐步放量发布。"
            ),
        )

        return release.status

    def start_phase(self, release: ReleaseRecord, phase_index: int) -> bool:
        if phase_index >= len(release.grayscale_phases):
            return False

        phase = release.grayscale_phases[phase_index]
        if phase.status == "in_progress":
            return True

        phase.status = "in_progress"
        phase.started_at = datetime.now()

        self._deploy_to_zones(release, phase.zones)

        self.audit_logger.log_action(
            actor="system",
            action="grayscale_phase_started",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "phase_index": phase_index,
                "phase_name": phase.name,
                "zones": phase.zones,
            },
        )

        return True

    def complete_phase(self, release: ReleaseRecord, phase_index: int) -> bool:
        if phase_index >= len(release.grayscale_phases):
            return False

        phase = release.grayscale_phases[phase_index]
        phase.status = "completed"
        phase.completed_at = datetime.now()

        self.audit_logger.log_action(
            actor="system",
            action="grayscale_phase_completed",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "phase_index": phase_index,
                "phase_name": phase.name,
                "duration_minutes": self._phase_duration_minutes(phase),
            },
        )

        if phase_index == len(release.grayscale_phases) - 1:
            release.status = ReleaseStatus.FULLY_RELEASED
            self._finalize_release(release)

        return True

    def pause_release(self, release: ReleaseRecord, reason: str) -> None:
        release.status = ReleaseStatus.GRAYSCALE_PAUSED

        self.audit_logger.log_action(
            actor="system",
            action="grayscale_release_paused",
            resource_type="release",
            resource_id=release.release_id,
            details={"reason": reason},
            is_critical=True,
        )

    def _deploy_to_zones(self, release: ReleaseRecord, zones: List[str]):
        self.zone_store.batch_update_version(zones, release.version, release.release_id)

    def _phase_duration_minutes(self, phase: GrayscalePhase) -> float:
        if phase.started_at and phase.completed_at:
            delta = phase.completed_at - phase.started_at
            return round(delta.total_seconds() / 60, 2)
        return 0.0

    def _finalize_release(self, release: ReleaseRecord):
        self.audit_logger.log_action(
            actor="system",
            action="release_fully_deployed",
            resource_type="release",
            resource_id=release.release_id,
            details={"version": release.version},
            is_critical=True,
        )

        self.notifier.notify_release_status(
            release_id=release.release_id,
            version=release.version,
            status="发布完成",
            extra_info="所有厂区/产线已完成版本升级，发布成功。",
        )

    def get_active_phases(self, release: ReleaseRecord) -> List[GrayscalePhase]:
        return [p for p in release.grayscale_phases if p.status == "in_progress"]

    def get_all_zone_status(self) -> List[Dict]:
        return self.zone_store.get_zones_status()
