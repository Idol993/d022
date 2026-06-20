"""
医疗器械 QMS - 分级审批流转与动态路由
Medical Device QMS - Approval Workflow & Dynamic Routing
支持常规发布串行审批、紧急Hotfix并行审批/事后补签
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import uuid

from models import (
    ReleaseRecord, ApprovalFlow, ApprovalStep, ApprovalRole,
    ApprovalStatus, ReleaseType, ReleaseStatus,
)
from config import CONFIG
from audit_log import AuditLogger
from notification import NotificationService


class ApprovalEngine:
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.notifier = NotificationService()

    def init_approval_flow(self, release: ReleaseRecord,
                           hotfix_reason: str = "",
                           hotfix_urgency: str = "medium",
                           deviation_report_id: str = "",
                           deviation_report_description: str = "") -> ApprovalFlow:
        is_hotfix = release.release_type == ReleaseType.HOTFIX

        if is_hotfix:
            flow = self._create_hotfix_flow(
                release,
                hotfix_reason=hotfix_reason,
                hotfix_urgency=hotfix_urgency,
                deviation_report_id=deviation_report_id,
                deviation_report_description=deviation_report_description,
            )
        else:
            flow = self._create_regular_flow(release)

        release.approval_flow = flow
        release.status = ReleaseStatus.APPROVAL_PENDING

        details = {
            "is_hotfix": is_hotfix,
            "steps_count": len(flow.steps),
            "flow_type": "hotfix" if is_hotfix else "regular",
        }
        if is_hotfix:
            details["hotfix_reason"] = hotfix_reason
            details["hotfix_urgency"] = hotfix_urgency
            details["deviation_report_id"] = deviation_report_id
            details["deviation_report_description"] = deviation_report_description

        self.audit_logger.log_action(
            actor="system",
            action="approval_flow_started",
            resource_type="release",
            resource_id=release.release_id,
            details=details,
            is_critical=is_hotfix,
        )

        self._notify_current_approver(release, flow)

        return flow

    def _create_regular_flow(self, release: ReleaseRecord) -> ApprovalFlow:
        approval_config = CONFIG["approval"]
        roles = approval_config["regular_flow"]

        steps = []
        for role in roles:
            steps.append(ApprovalStep(
                role=ApprovalRole(role),
                status=ApprovalStatus.PENDING,
                is_parallel=False,
            ))

        return ApprovalFlow(
            release_id=release.release_id,
            steps=steps,
            current_step_index=0,
            is_hotfix=False,
            started_at=datetime.now(),
        )

    def _create_hotfix_flow(self, release: ReleaseRecord,
                            hotfix_reason: str = "",
                            hotfix_urgency: str = "medium",
                            deviation_report_id: str = "",
                            deviation_report_description: str = "") -> ApprovalFlow:
        approval_config = CONFIG["approval"]
        roles = approval_config["hotfix_flow"]
        is_parallel = approval_config["hotfix_parallel"]

        steps = []
        for role in roles:
            steps.append(ApprovalStep(
                role=ApprovalRole(role),
                status=ApprovalStatus.PENDING,
                is_parallel=is_parallel,
            ))

        post_sign_deadline = None
        if approval_config.get("hotfix_require_post_sign", False):
            post_sign_deadline = datetime.now() + timedelta(hours=24)

        flow = ApprovalFlow(
            release_id=release.release_id,
            steps=steps,
            current_step_index=0,
            is_hotfix=True,
            hotfix_reason=hotfix_reason,
            hotfix_urgency=hotfix_urgency,
            deviation_report_id=deviation_report_id,
            deviation_report_description=deviation_report_description,
            post_sign_complete=False,
            post_sign_deadline=post_sign_deadline,
            started_at=datetime.now(),
        )

        if is_parallel:
            flow.current_step_index = len(steps)

        return flow

    def approve(self, release: ReleaseRecord, role: ApprovalRole,
                approver: str, comment: str = "") -> ApprovalStatus:
        flow = release.approval_flow
        if not flow:
            raise ValueError("审批流程未初始化")

        if flow.is_completed():
            return ApprovalStatus.APPROVED

        if flow.is_rejected():
            return ApprovalStatus.REJECTED

        target_step = self._find_step_by_role(flow, role)
        if not target_step:
            raise ValueError(f"审批角色 {role.value} 不在当前审批流程中")

        if target_step.status == ApprovalStatus.APPROVED:
            return ApprovalStatus.APPROVED

        if not self._can_approve(flow, target_step):
            raise ValueError(f"当前轮次不允许 {role.value} 审批")

        target_step.status = ApprovalStatus.APPROVED
        target_step.approver = approver
        target_step.comment = comment
        target_step.approved_at = datetime.now()

        self.audit_logger.log_action(
            actor=approver,
            action="approval_step_approved",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "role": role.value,
                "approver": approver,
                "comment": comment,
            },
        )

        self._advance_flow(release, flow)
        self._check_flow_completion(release, flow)

        return ApprovalStatus.APPROVED

    def reject(self, release: ReleaseRecord, role: ApprovalRole,
               rejecter: str, reason: str) -> ApprovalStatus:
        flow = release.approval_flow
        if not flow:
            raise ValueError("审批流程未初始化")

        if flow.is_rejected():
            return ApprovalStatus.REJECTED

        target_step = self._find_step_by_role(flow, role)
        if not target_step:
            raise ValueError(f"审批角色 {role.value} 不在当前审批流程中")

        target_step.status = ApprovalStatus.REJECTED
        target_step.approver = rejecter
        target_step.comment = reason
        target_step.approved_at = datetime.now()

        flow.completed_at = datetime.now()
        release.status = ReleaseStatus.APPROVAL_REJECTED

        self.audit_logger.log_action(
            actor=rejecter,
            action="approval_step_rejected",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "role": role.value,
                "rejecter": rejecter,
                "reason": reason,
            },
            is_critical=True,
        )

        self.notifier.notify_release_status(
            release_id=release.release_id,
            version=release.version,
            status="审批被驳回",
            extra_info=f"驳回角色: {role.value}\n驳回人: {rejecter}\n驳回原因: {reason}",
        )

        return ApprovalStatus.REJECTED

    def post_sign(self, release: ReleaseRecord, role: ApprovalRole,
                  signer: str, comment: str = "") -> bool:
        if not release.approval_flow or not release.approval_flow.is_hotfix:
            raise ValueError("仅紧急热修复支持事后补签")

        flow = release.approval_flow

        if not CONFIG["approval"].get("hotfix_require_post_sign", False):
            flow.post_sign_complete = True
            return True

        target_step = self._find_step_by_role(flow, role)
        if not target_step:
            raise ValueError(f"审批角色 {role.value} 不在审批流程中")

        signed = False
        if target_step.status == ApprovalStatus.PENDING:
            target_step.status = ApprovalStatus.APPROVED
            target_step.approver = signer
            target_step.comment = comment + " (事后补签)"
            target_step.approved_at = datetime.now()
            signed = True

            self.audit_logger.log_action(
                actor=signer,
                action="approval_post_sign",
                resource_type="release",
                resource_id=release.release_id,
                details={
                    "role": role.value,
                    "signer": signer,
                    "comment": comment,
                },
            )

        all_signed = all(s.status == ApprovalStatus.APPROVED for s in flow.steps)
        if all_signed:
            flow.post_sign_complete = True

            signers = [f"{s.role.value}:{s.approver}" for s in flow.steps if s.approver]
            self.audit_logger.log_action(
                actor="system",
                action="approval_post_sign_complete",
                resource_type="release",
                resource_id=release.release_id,
                details={
                    "all_steps_signed": True,
                    "post_sign_status": "completed",
                    "signers": signers,
                    "signers_count": len(signers),
                },
            )

        return signed

    def _find_step_by_role(self, flow: ApprovalFlow,
                           role: ApprovalRole) -> Optional[ApprovalStep]:
        for step in flow.steps:
            if step.role == role:
                return step
        return None

    def _can_approve(self, flow: ApprovalFlow, step: ApprovalStep) -> bool:
        if flow.is_hotfix and any(s.is_parallel for s in flow.steps):
            return step.status == ApprovalStatus.PENDING

        step_index = flow.steps.index(step)
        return step_index == flow.current_step_index

    def _advance_flow(self, release: ReleaseRecord, flow: ApprovalFlow):
        if flow.is_hotfix and any(s.is_parallel for s in flow.steps):
            return

        if flow.current_step_index < len(flow.steps):
            current_step = flow.steps[flow.current_step_index]
            if current_step.status == ApprovalStatus.APPROVED:
                flow.current_step_index += 1

        if flow.current_step_index < len(flow.steps):
            self._notify_current_approver(release, flow)

    def _check_flow_completion(self, release: ReleaseRecord, flow: ApprovalFlow):
        if flow.is_completed():
            flow.completed_at = datetime.now()
            release.status = ReleaseStatus.APPROVED

            self.audit_logger.log_action(
                actor="system",
                action="approval_flow_completed",
                resource_type="release",
                resource_id=release.release_id,
                details={
                    "duration_hours": self._calc_duration_hours(flow),
                    "steps_count": len(flow.steps),
                },
            )

            self.notifier.notify_release_status(
                release_id=release.release_id,
                version=release.version,
                status="审批通过，准备灰度发布",
                extra_info="所有审批环节已通过，系统将按计划执行灰度发布。",
            )

    def _notify_current_approver(self, release: ReleaseRecord, flow: ApprovalFlow):
        current_step = flow.get_current_step()
        if current_step and current_step.status == ApprovalStatus.PENDING:
            role_approvers = CONFIG["approval"]["role_approvers"].get(
                current_step.role.value, []
            )

            self.notifier.notify_release_status(
                release_id=release.release_id,
                version=release.version,
                status="待审批",
                extra_info=(
                    f"审批角色: {current_step.role.value}\n"
                    f"待审批人: {', '.join(role_approvers)}\n"
                    f"请及时处理审批事项。"
                ),
            )

    def _calc_duration_hours(self, flow: ApprovalFlow) -> float:
        if flow.started_at and flow.completed_at:
            delta = flow.completed_at - flow.started_at
            return round(delta.total_seconds() / 3600, 2)
        return 0.0

    def get_approval_summary(self, release: ReleaseRecord) -> Dict:
        flow = release.approval_flow
        if not flow:
            return {"status": "not_started", "steps": []}

        steps_summary = []
        for step in flow.steps:
            steps_summary.append({
                "role": step.role.value,
                "status": step.status.value,
                "approver": step.approver,
                "approved_at": step.approved_at.isoformat() if step.approved_at else None,
                "comment": step.comment,
                "is_parallel": step.is_parallel,
            })

        summary = {
            "is_hotfix": flow.is_hotfix,
            "current_step_index": flow.current_step_index,
            "total_steps": len(flow.steps),
            "is_completed": flow.is_completed(),
            "is_rejected": flow.is_rejected(),
            "steps": steps_summary,
            "duration_hours": self._calc_duration_hours(flow),
        }

        if flow.is_hotfix:
            summary.update({
                "hotfix_reason": flow.hotfix_reason,
                "hotfix_urgency": flow.hotfix_urgency,
                "deviation_report_id": flow.deviation_report_id,
                "deviation_report_description": flow.deviation_report_description,
                "post_sign_status": flow.get_post_sign_status(),
                "post_sign_complete": flow.post_sign_complete,
                "post_sign_deadline": flow.post_sign_deadline.isoformat() if flow.post_sign_deadline else None,
            })

        return summary

    def check_timeout(self, release: ReleaseRecord) -> bool:
        flow = release.approval_flow
        if not flow or flow.is_completed() or flow.is_rejected():
            return False

        timeout_hours = CONFIG["approval"]["approval_timeout_hours"]
        if not flow.started_at:
            return False

        elapsed = datetime.now() - flow.started_at
        return elapsed > timedelta(hours=timeout_hours)

    def escalate(self, release: ReleaseRecord) -> bool:
        if not CONFIG["approval"]["escalation_enabled"]:
            return False

        flow = release.approval_flow
        if not flow:
            return False

        self.audit_logger.log_action(
            actor="system",
            action="approval_escalated",
            resource_type="release",
            resource_id=release.release_id,
            details={"current_step": flow.current_step_index},
            is_critical=True,
        )

        self.notifier.notify_release_status(
            release_id=release.release_id,
            version=release.version,
            status="审批超时-已升级",
            extra_info="当前审批环节已超时，请上级主管关注处理。",
        )

        return True


def init_approval(release: ReleaseRecord) -> ApprovalFlow:
    engine = ApprovalEngine()
    return engine.init_approval_flow(release)


def approve_release(release: ReleaseRecord, role: ApprovalRole,
                    approver: str, comment: str = "") -> ApprovalStatus:
    engine = ApprovalEngine()
    return engine.approve(release, role, approver, comment)


def reject_release(release: ReleaseRecord, role: ApprovalRole,
                   rejecter: str, reason: str) -> ApprovalStatus:
    engine = ApprovalEngine()
    return engine.reject(release, role, rejecter, reason)
