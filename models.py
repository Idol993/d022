"""
医疗器械 QMS 质量管理系统 - 核心数据模型
Medical Device QMS - Core Data Models
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any
import uuid


class ReleaseType(Enum):
    REGULAR = "regular"
    HOTFIX = "hotfix"


class ReleaseStatus(Enum):
    DRAFT = "draft"
    PRE_CHECK_PENDING = "pre_check_pending"
    PRE_CHECK_FAILED = "pre_check_failed"
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVED = "approved"
    GRAYSCALE_IN_PROGRESS = "grayscale_in_progress"
    GRAYSCALE_PAUSED = "grayscale_paused"
    GRAYSCALE_FAILED = "grayscale_failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FULLY_RELEASED = "fully_released"


class ApprovalRole(Enum):
    QUALITY = "quality"
    REGULATORY = "regulatory"
    RND = "rnd"
    PRODUCTION = "production"


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FactoryTier(Enum):
    TIER_3_NON_CORE = "tier3_non_core"
    TIER_2_ASSEMBLY = "tier2_assembly"
    TIER_1_STERILE = "tier1_sterile"


class CheckItemStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class CheckItem:
    check_id: str
    name: str
    category: str
    status: CheckItemStatus
    description: str = ""
    suggestion: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    checked_at: Optional[datetime] = None


@dataclass
class PreCheckResult:
    release_id: str
    overall_pass: bool
    checks: List[CheckItem] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def get_failed_checks(self) -> List[CheckItem]:
        return [c for c in self.checks if c.status == CheckItemStatus.FAIL]

    def get_warning_checks(self) -> List[CheckItem]:
        return [c for c in self.checks if c.status == CheckItemStatus.WARNING]


@dataclass
class ApprovalStep:
    role: ApprovalRole
    status: ApprovalStatus
    approver: Optional[str] = None
    comment: str = ""
    approved_at: Optional[datetime] = None
    is_parallel: bool = False


@dataclass
class ApprovalFlow:
    release_id: str
    steps: List[ApprovalStep] = field(default_factory=list)
    current_step_index: int = 0
    is_hotfix: bool = False
    hotfix_reason: str = ""
    hotfix_urgency: str = "medium"
    deviation_report_id: str = ""
    deviation_report_description: str = ""
    post_sign_complete: bool = False
    post_sign_deadline: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def get_current_step(self) -> Optional[ApprovalStep]:
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def is_completed(self) -> bool:
        return all(s.status == ApprovalStatus.APPROVED for s in self.steps)

    def is_rejected(self) -> bool:
        return any(s.status == ApprovalStatus.REJECTED for s in self.steps)

    def get_post_sign_status(self) -> str:
        if not self.is_hotfix:
            return "not_applicable"
        if self.post_sign_complete:
            return "completed"
        pending = [s for s in self.steps if s.status == ApprovalStatus.PENDING]
        if pending:
            return "pending"
        return "completed"


@dataclass
class FactoryZone:
    zone_id: str
    name: str
    tier: FactoryTier
    description: str = ""
    current_version: str = ""
    is_active: bool = True


@dataclass
class GrayscalePhase:
    phase_id: str
    name: str
    tier: FactoryTier
    zones: List[str] = field(default_factory=list)
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    monitor_interval_minutes: int = 5
    duration_minutes: int = 60


@dataclass
class MonitorMetrics:
    timestamp: datetime
    zone_id: str
    deviation_rate: float = 0.0
    anomaly_delay_rate: float = 0.0
    approval_block_rate: float = 0.0
    additional_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class CircuitBreakerConfig:
    deviation_rate_threshold: float = 2.0
    anomaly_delay_rate_threshold: float = 5.0
    approval_block_rate_threshold: float = 10.0
    consecutive_failures_trigger: int = 3
    auto_rollback_enabled: bool = True


@dataclass
class RollbackRecord:
    rollback_id: str
    release_id: str
    reason: str
    affected_zones: List[str] = field(default_factory=list)
    affected_batches: List[str] = field(default_factory=list)
    from_version: str = ""
    to_version: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    is_drill: bool = False
    report_generated: bool = False


@dataclass
class ReleaseRecord:
    release_id: str
    version: str
    release_type: ReleaseType
    status: ReleaseStatus
    title: str = ""
    description: str = ""
    change_control_id: str = ""
    requester: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    target_zones: List[str] = field(default_factory=list)
    previous_version: str = ""

    pre_check_result: Optional[PreCheckResult] = None
    approval_flow: Optional[ApprovalFlow] = None
    grayscale_phases: List[GrayscalePhase] = field(default_factory=list)
    rollback_records: List[RollbackRecord] = field(default_factory=list)

    @classmethod
    def create(cls, version: str, release_type: ReleaseType, title: str = "",
               description: str = "", requester: str = "",
               change_control_id: str = "") -> 'ReleaseRecord':
        return cls(
            release_id=str(uuid.uuid4()),
            version=version,
            release_type=release_type,
            status=ReleaseStatus.DRAFT,
            title=title,
            description=description,
            requester=requester,
            change_control_id=change_control_id,
        )


@dataclass
class AuditLogEntry:
    log_id: str
    timestamp: datetime
    actor: str
    action: str
    resource_type: str
    resource_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""
    is_critical: bool = False

    @classmethod
    def create(cls, actor: str, action: str, resource_type: str,
               resource_id: str, details: Dict[str, Any] = None,
               is_critical: bool = False) -> 'AuditLogEntry':
        return cls(
            log_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            is_critical=is_critical,
        )


@dataclass
class WeeklyReport:
    report_id: str
    start_date: datetime
    end_date: datetime
    total_releases: int = 0
    success_releases: int = 0
    rollback_count: int = 0
    avg_approval_hours: float = 0.0
    success_rate: float = 0.0
    release_details: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: Optional[datetime] = None


@dataclass
class DrillRecord:
    drill_id: str
    name: str
    scheduled_at: datetime
    status: str = "scheduled"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: int = 0
    result: str = ""
    notes: str = ""
    is_automated: bool = False
