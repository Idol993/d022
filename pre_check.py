"""
医疗器械 QMS - 发布前置校验与多维质量门禁
Medical Device QMS - Pre-Release Check & Quality Gate
涵盖变更管理、偏差流程、CAPA、文档审核四大维度
"""

from datetime import datetime
from typing import List, Dict, Any, Optional, Callable

from models import (
    ReleaseRecord, PreCheckResult, CheckItem, CheckItemStatus,
    ReleaseStatus,
)
from config import CONFIG
from audit_log import AuditLogger


class PreCheckExecutor:
    def __init__(self):
        self.audit_logger = AuditLogger()
        self.checkers: Dict[str, Callable] = {
            "change_control": self._check_change_control,
            "deviation": self._check_deviations,
            "capa": self._check_capa,
            "document": self._check_documents,
        }

    def run_pre_check(self, release: ReleaseRecord) -> PreCheckResult:
        pre_check_config = CONFIG["pre_check"]
        result = PreCheckResult(
            release_id=release.release_id,
            overall_pass=True,
            started_at=datetime.now(),
        )

        release.status = ReleaseStatus.PRE_CHECK_PENDING

        checks_to_run = []
        if pre_check_config["change_control_required"]:
            checks_to_run.append("change_control")
        if pre_check_config["deviation_check_enabled"]:
            checks_to_run.append("deviation")
        if pre_check_config["capa_check_enabled"]:
            checks_to_run.append("capa")
        if pre_check_config["document_check_enabled"]:
            checks_to_run.append("document")

        for check_key in checks_to_run:
            if check_key in self.checkers:
                check_item = self.checkers[check_key](release)
                result.checks.append(check_item)

        result.overall_pass = all(
            c.status != CheckItemStatus.FAIL for c in result.checks
        )
        result.completed_at = datetime.now()

        release.pre_check_result = result

        if result.overall_pass:
            release.status = ReleaseStatus.APPROVAL_PENDING
            status_str = "通过"
        else:
            release.status = ReleaseStatus.PRE_CHECK_FAILED
            status_str = "未通过"

        self.audit_logger.log_action(
            actor="system",
            action="pre_check_complete",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "overall_pass": result.overall_pass,
                "check_count": len(result.checks),
                "failed_count": len(result.get_failed_checks()),
                "warning_count": len(result.get_warning_checks()),
            },
            is_critical=not result.overall_pass,
        )

        return result

    def _check_change_control(self, release: ReleaseRecord) -> CheckItem:
        check_id = "change_control_001"
        check = CheckItem(
            check_id=check_id,
            name="变更管理合规性检查",
            category="change_control",
            status=CheckItemStatus.PASS,
            description="验证变更控制流程是否闭环且评估完整",
            checked_at=datetime.now(),
        )

        if not release.change_control_id:
            check.status = CheckItemStatus.FAIL
            check.description = "缺少变更控制单编号"
            check.suggestion = "请关联有效的变更控制单（Change Control），确保变更已完成风险评估与审批"
            check.evidence = {"change_control_id": None}
            return check

        change_control_data = self._fetch_change_control(release.change_control_id)

        if not change_control_data.get("exists", False):
            check.status = CheckItemStatus.FAIL
            check.description = f"变更控制单 {release.change_control_id} 不存在"
            check.suggestion = "请核实变更控制单编号是否正确"
            check.evidence = {"change_control_id": release.change_control_id, "exists": False}
            return check

        if not change_control_data.get("is_closed", False):
            check.status = CheckItemStatus.FAIL
            check.description = "变更控制流程未闭环"
            check.suggestion = "请确保变更控制单已完成所有审批环节并正式关闭"
            check.evidence = {
                "change_control_id": release.change_control_id,
                "status": change_control_data.get("status", "unknown"),
            }
            return check

        if not change_control_data.get("risk_assessment_complete", False):
            check.status = CheckItemStatus.WARNING
            check.description = "风险评估文件不完整"
            check.suggestion = "建议补充完整的风险评估报告（FMEA/FTA）"
            check.evidence = change_control_data

        check.evidence = change_control_data
        return check

    def _check_deviations(self, release: ReleaseRecord) -> CheckItem:
        check_id = "deviation_001"
        check = CheckItem(
            check_id=check_id,
            name="未关闭偏差影响评估",
            category="deviation",
            status=CheckItemStatus.PASS,
            description="检查未关闭偏差是否影响当前发布",
            checked_at=datetime.now(),
        )

        max_open = CONFIG["pre_check"]["max_open_deviations_allowed"]
        deviations = self._fetch_open_deviations(release)

        impact_deviations = [
            d for d in deviations
            if d.get("impact_release", False)
        ]

        if len(impact_deviations) > max_open:
            check.status = CheckItemStatus.FAIL
            check.description = (
                f"存在 {len(impact_deviations)} 个影响本次发布的未关闭偏差"
            )
            check.suggestion = (
                "请关闭或评估以下偏差对本次发布的影响：\n"
                + "\n".join([f"- {d.get('id', '')}: {d.get('description', '')}" for d in impact_deviations[:5]])
            )
            check.evidence = {"impact_deviation_count": len(impact_deviations), "deviations": impact_deviations}
            return check

        if len(deviations) > 0 and len(impact_deviations) <= max_open:
            check.status = CheckItemStatus.WARNING
            check.description = f"存在 {len(deviations)} 个未关闭偏差，但不直接影响本次发布"
            check.suggestion = "建议在发布后跟踪处理这些偏差"

        check.evidence = {
            "total_open_deviations": len(deviations),
            "impact_deviations": len(impact_deviations),
        }
        return check

    def _check_capa(self, release: ReleaseRecord) -> CheckItem:
        check_id = "capa_001"
        check = CheckItem(
            check_id=check_id,
            name="CAPA 执行状态校验",
            category="capa",
            status=CheckItemStatus.PASS,
            description="验证纠正预防措施执行状态",
            checked_at=datetime.now(),
        )

        max_open = CONFIG["pre_check"]["max_open_capas_allowed"]
        capas = self._fetch_related_capas(release)

        overdue_capas = [
            c for c in capas
            if c.get("status") == "open" and c.get("is_overdue", False)
        ]

        if len(overdue_capas) > max_open:
            check.status = CheckItemStatus.FAIL
            check.description = f"存在 {len(overdue_capas)} 个逾期未完成的 CAPA"
            check.suggestion = (
                "请完成以下逾期 CAPA 或获得特批：\n"
                + "\n".join([f"- {c.get('id', '')}: {c.get('description', '')}" for c in overdue_capas[:5]])
            )
            check.evidence = {"overdue_capa_count": len(overdue_capas), "capas": overdue_capas}
            return check

        in_progress_capas = [
            c for c in capas if c.get("status") == "in_progress"
        ]
        if in_progress_capas:
            check.status = CheckItemStatus.WARNING
            check.description = f"存在 {len(in_progress_capas)} 个进行中的 CAPA"
            check.suggestion = "请确保这些 CAPA 按计划推进"

        check.evidence = {
            "total_capas": len(capas),
            "overdue_capas": len(overdue_capas),
            "in_progress_capas": len(in_progress_capas),
        }
        return check

    def _check_documents(self, release: ReleaseRecord) -> CheckItem:
        check_id = "document_001"
        check = CheckItem(
            check_id=check_id,
            name="受控文档审核状态检查",
            category="document",
            status=CheckItemStatus.PASS,
            description="验证受控文档是否已生效且版本一致",
            checked_at=datetime.now(),
        )

        consistency_required = CONFIG["pre_check"]["document_version_consistency_required"]
        documents = self._fetch_related_documents(release)

        if not documents:
            check.status = CheckItemStatus.WARNING
            check.description = "未找到关联的受控文档"
            check.suggestion = "请确认是否有需要随版本发布的受控文档"
            check.evidence = {"document_count": 0}
            return check

        not_effective = [
            d for d in documents
            if d.get("status") != "effective"
        ]

        if not_effective:
            check.status = CheckItemStatus.FAIL
            check.description = f"有 {len(not_effective)} 份文档未生效"
            check.suggestion = (
                "请确保以下文档已完成审批并生效：\n"
                + "\n".join([f"- {d.get('name', '')}: {d.get('status', '')}" for d in not_effective[:5]])
            )
            check.evidence = {"not_effective_count": len(not_effective), "documents": not_effective}
            return check

        if consistency_required:
            version_mismatch = [
                d for d in documents
                if d.get("version") != release.version
            ]
            if version_mismatch:
                check.status = CheckItemStatus.WARNING
                check.description = f"有 {len(version_mismatch)} 份文档版本与发布版本不一致"
                check.suggestion = "请确认文档版本是否需要与发布版本保持一致"

        check.evidence = {
            "total_documents": len(documents),
            "not_effective": len(not_effective),
            "version_consistent": len(documents) - len(version_mismatch) if consistency_required else "N/A",
        }
        return check

    def _fetch_change_control(self, cc_id: str) -> Dict[str, Any]:
        return {
            "exists": True,
            "is_closed": True,
            "status": "approved_closed",
            "risk_assessment_complete": True,
            "change_type": "minor",
            "approval_chain_complete": True,
        }

    def _fetch_open_deviations(self, release: ReleaseRecord) -> List[Dict[str, Any]]:
        return [
            {
                "id": "DEV-2024-001",
                "description": "标签打印机偶尔卡纸",
                "status": "open",
                "impact_release": False,
                "severity": "low",
            },
        ]

    def _fetch_related_capas(self, release: ReleaseRecord) -> List[Dict[str, Any]]:
        return [
            {
                "id": "CAPA-2024-015",
                "description": "提升无菌区环境监测合格率",
                "status": "completed",
                "is_overdue": False,
            },
        ]

    def _fetch_related_documents(self, release: ReleaseRecord) -> List[Dict[str, Any]]:
        return [
            {
                "id": "SOP-QA-001",
                "name": "质量手册",
                "version": release.version,
                "status": "effective",
            },
            {
                "id": "SOP-PROD-023",
                "name": "生产作业指导书",
                "version": release.version,
                "status": "effective",
            },
        ]

    def generate_fix_suggestions(self, result: PreCheckResult) -> str:
        failed = result.get_failed_checks()
        if not failed:
            return "所有检查项均已通过，无需修复。"

        suggestions = ["【前置校验未通过 - 修复建议】\n"]
        for i, check in enumerate(failed, 1):
            suggestions.append(f"{i}. {check.name}")
            suggestions.append(f"   问题: {check.description}")
            suggestions.append(f"   建议: {check.suggestion}")
            suggestions.append("")

        return "\n".join(suggestions)


def run_release_pre_check(release: ReleaseRecord) -> PreCheckResult:
    executor = PreCheckExecutor()
    return executor.run_pre_check(release)
