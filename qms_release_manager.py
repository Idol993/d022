"""
医疗器械 QMS 质量管理系统 - 版本发布与智能回滚自动化平台
Medical Device QMS - Release & Rollback Automation Platform
主入口脚本 - 提供完整的发布管理生命周期操作
"""

import sys
import time
from datetime import datetime, timedelta
from typing import List, Optional

from models import (
    ReleaseRecord, ReleaseType, ReleaseStatus,
    ApprovalRole, ApprovalStatus,
)
from config import CONFIG
from pre_check import PreCheckExecutor
from approval import ApprovalEngine
from grayscale import GrayscaleReleaseManager
from rollback import RollbackManager
from reports import DrillManager, ReportGenerator, ReleaseQueryService
from audit_log import AuditLogger
from storage import ReleaseStorage
from notification import NotificationService
from scheduler import TaskScheduler


class QMSReleaseManager:
    """
    QMS 版本发布与智能回滚管理器
    整合所有模块，提供统一的操作接口
    """

    def __init__(self):
        self.pre_check_executor = PreCheckExecutor()
        self.approval_engine = ApprovalEngine()
        self.grayscale_manager = GrayscaleReleaseManager()
        self.rollback_manager = RollbackManager()
        self.drill_manager = DrillManager()
        self.report_generator = ReportGenerator()
        self.query_service = ReleaseQueryService()
        self.audit_logger = AuditLogger()
        self.storage = ReleaseStorage()
        self.notifier = NotificationService()
        self.scheduler = TaskScheduler()

    def create_release(self, version: str, release_type: ReleaseType,
                       title: str = "", description: str = "",
                       requester: str = "",
                       change_control_id: str = "") -> ReleaseRecord:
        release = ReleaseRecord.create(
            version=version,
            release_type=release_type,
            title=title,
            description=description,
            requester=requester,
            change_control_id=change_control_id,
        )

        self.storage.save_release(release)

        self.audit_logger.log_action(
            actor=requester or "system",
            action="release_created",
            resource_type="release",
            resource_id=release.release_id,
            details={
                "version": version,
                "release_type": release_type.value,
                "title": title,
            },
        )

        print(f"✅ 发布申请已创建: {release.release_id}")
        print(f"   版本: {version} | 类型: {release_type.value}")
        return release

    def submit_for_precheck(self, release: ReleaseRecord) -> ReleaseRecord:
        print(f"\n📋 开始前置校验 - 版本 {release.version}")
        print("=" * 50)

        result = self.pre_check_executor.run_pre_check(release)

        self.storage.save_release(release)

        if result.overall_pass:
            print(f"✅ 前置校验通过 ({len(result.checks)} 项检查)")
        else:
            print(f"❌ 前置校验未通过")
            suggestions = self.pre_check_executor.generate_fix_suggestions(result)
            print(suggestions)

        return release

    def start_approval(self, release: ReleaseRecord,
                       hotfix_reason: str = "",
                       hotfix_urgency: str = "medium",
                       deviation_report_id: str = "",
                       deviation_report_description: str = "") -> ReleaseRecord:
        print(f"\n📝 启动审批流程 - 版本 {release.version}")
        print("=" * 50)

        flow = self.approval_engine.init_approval_flow(
            release=release,
            hotfix_reason=hotfix_reason,
            hotfix_urgency=hotfix_urgency,
            deviation_report_id=deviation_report_id,
            deviation_report_description=deviation_report_description,
        )
        self.storage.save_release(release)

        flow_type = "紧急热修复" if flow.is_hotfix else "常规迭代"
        print(f"审批类型: {flow_type}")
        print(f"审批环节数: {len(flow.steps)}")

        if flow.is_hotfix:
            print(f"紧急原因: {hotfix_reason or '未提供'}")
            print(f"紧急程度: {hotfix_urgency}")
            if deviation_report_id:
                print(f"偏差报告: {deviation_report_id}")

        return release

    def create_hotfix_release(self, version: str, title: str = "",
                              description: str = "", requester: str = "",
                              hotfix_reason: str = "",
                              hotfix_urgency: str = "high",
                              deviation_report_id: str = "",
                              deviation_report_description: str = "",
                              change_control_id: str = "") -> ReleaseRecord:
        release = self.create_release(
            version=version,
            release_type=ReleaseType.HOTFIX,
            title=title,
            description=description,
            requester=requester,
            change_control_id=change_control_id,
        )

        print(f"\n🔥 紧急热修复发布")
        print("=" * 50)
        print(f"紧急原因: {hotfix_reason or '未提供'}")
        print(f"紧急程度: {hotfix_urgency}")
        if deviation_report_id:
            print(f"关联偏差: {deviation_report_id}")
            if deviation_report_description:
                print(f"偏差说明: {deviation_report_description}")

        self.submit_for_precheck(release)

        if release.status == ReleaseStatus.PRE_CHECK_FAILED:
            print("\n⚠️  前置校验未通过，但热修复可继续（需事后补签）")

        self.start_approval(
            release=release,
            hotfix_reason=hotfix_reason,
            hotfix_urgency=hotfix_urgency,
            deviation_report_id=deviation_report_id,
            deviation_report_description=deviation_report_description,
        )

        return release

    def post_sign_approval(self, release: ReleaseRecord, role: ApprovalRole,
                           signer: str, comment: str = "") -> ReleaseRecord:
        result = self.approval_engine.post_sign(release, role, signer, comment)
        self.storage.save_release(release)

        if result:
            print(f"✅ 事后补签完成 - {role.value}: {signer}")
        else:
            print(f"ℹ️  {role.value} 已补签或无需补签")

        flow = release.approval_flow
        if flow and flow.is_hotfix:
            status = flow.get_post_sign_status()
            print(f"   补签总状态: {status}")

        return release

    def approve_step(self, release: ReleaseRecord, role: ApprovalRole,
                     approver: str, comment: str = "") -> ReleaseRecord:
        status = self.approval_engine.approve(release, role, approver, comment)
        self.storage.save_release(release)

        if status == ApprovalStatus.APPROVED:
            print(f"✅ {role.value} 审批通过 - {approver}")
        else:
            print(f"ℹ️  {role.value} 状态: {status.value}")

        return release

    def reject_step(self, release: ReleaseRecord, role: ApprovalRole,
                    rejecter: str, reason: str) -> ReleaseRecord:
        status = self.approval_engine.reject(release, role, rejecter, reason)
        self.storage.save_release(release)
        print(f"❌ {role.value} 审批驳回 - {rejecter}")
        print(f"   原因: {reason}")
        return release

    def start_grayscale_release(self, release: ReleaseRecord) -> ReleaseRecord:
        print(f"\n🚀 启动灰度发布 - 版本 {release.version}")
        print("=" * 50)

        self.grayscale_manager.init_grayscale_phases(release)
        status = self.grayscale_manager.start_release(release)
        self.storage.save_release(release)

        print(f"发布状态: {status.value}")
        print(f"灰度阶段数: {len(release.grayscale_phases)}")

        for i, phase in enumerate(release.grayscale_phases, 1):
            print(f"  阶段 {i}: {phase.name} ({len(phase.zones)} 个厂区)")

        return release

    def advance_phase(self, release: ReleaseRecord) -> ReleaseRecord:
        current_idx = -1
        for i, phase in enumerate(release.grayscale_phases):
            if phase.status == "in_progress":
                self.grayscale_manager.complete_phase(release, i)
                current_idx = i
                break

        if current_idx + 1 < len(release.grayscale_phases):
            self.grayscale_manager.start_phase(release, current_idx + 1)
            next_phase = release.grayscale_phases[current_idx + 1]
            print(f"▶️  进入下一灰度阶段: {next_phase.name}")
        else:
            print(f"🎉 所有灰度阶段完成，发布成功!")

        self.storage.save_release(release)
        return release

    def start_phase_by_index(self, release: ReleaseRecord,
                             phase_index: int) -> ReleaseRecord:
        success = self.grayscale_manager.start_phase(release, phase_index)
        if success:
            phase = release.grayscale_phases[phase_index]
            print(f"▶️  灰度阶段 {phase_index + 1} 已启动: {phase.name}")
            print(f"   涉及厂区: {', '.join(phase.zones)}")
        self.storage.save_release(release)
        return release

    def monitor_and_check(self, release: ReleaseRecord) -> dict:
        result = self.rollback_manager.monitor_and_check(release)
        self.storage.save_release(release)

        if result["status"] == "circuit_breaker_tripped":
            print(f"⚠️  熔断触发! 原因: {result['violations'][0]['reason']}")
            if result["action_taken"] == "auto_rollback":
                print(f"🔄 已自动执行回滚")

        return result

    def manual_rollback(self, release: ReleaseRecord, reason: str) -> ReleaseRecord:
        print(f"\n🔄 执行手动回滚 - 版本 {release.version}")
        print("=" * 50)

        rollback = self.rollback_manager.execute_rollback(
            release=release,
            reason=reason,
            is_drill=False,
        )

        self.storage.save_release(release)

        print(f"回滚完成: {rollback.rollback_id}")
        print(f"回滚至版本: {rollback.to_version}")
        print(f"影响厂区: {', '.join(rollback.affected_zones)}")

        return release

    def run_drill(self, drill_name: str, release: ReleaseRecord = None) -> None:
        print(f"\n🎯 执行回滚演练: {drill_name}")
        print("=" * 50)

        if release is None:
            releases = self.storage.list_releases(
                status=ReleaseStatus.FULLY_RELEASED
            )
            if releases:
                release = releases[0]
            else:
                release = self.create_release(
                    version="v2.4.0-drill",
                    release_type=ReleaseType.REGULAR,
                    title="回滚演练专用发布",
                    requester="system",
                )
                self.submit_for_precheck(release)
                self.start_approval(release)
                for role in [ApprovalRole.QUALITY, ApprovalRole.REGULATORY,
                             ApprovalRole.RND, ApprovalRole.PRODUCTION]:
                    self.approve_step(release, role, "drill_user")
                self.start_grayscale_release(release)
                for i in range(len(release.grayscale_phases)):
                    self.start_phase_by_index(release, i)

        drill = self.drill_manager.schedule_drill(
            name=drill_name,
            scheduled_at=datetime.now(),
            is_automated=True,
        )

        result = self.drill_manager.execute_drill(drill, release)

        print(f"演练状态: {result.status}")
        print(f"演练结果: {result.result}")
        print(f"耗时: {result.duration_seconds} 秒")
        if result.notes:
            print(f"备注: {result.notes}")

    def generate_weekly_report(self) -> dict:
        print("\n📊 生成周度运营报表")
        print("=" * 50)

        releases = self.storage.list_releases()
        report = self.report_generator.generate_weekly_report(releases)
        summary = self.report_generator.get_report_summary(report)
        print(summary)

        files = self.report_generator.export_full_report(report)

        print(f"\n📁 报表文件已生成:")
        print(f"   📊 Excel: {files['excel']}")
        print(f"   📄 PDF:   {files['pdf']}")

        return files

    def query_releases(self, start_date: str = None, end_date: str = None,
                       zone_id: str = None, version: str = None,
                       status: str = None, release_type: str = None) -> list:
        from datetime import datetime

        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        status_enum = ReleaseStatus(status) if status else None
        type_enum = ReleaseType(release_type) if release_type else None

        results = self.query_service.query_releases(
            start_date=start_dt,
            end_date=end_dt,
            zone_id=zone_id,
            version=version,
            status=status_enum,
            release_type=type_enum,
        )

        print(f"\n🔍 发布记录检索 (共 {len(results)} 条)")
        filter_info = {}
        if start_date: filter_info["start"] = start_date
        if end_date: filter_info["end"] = end_date
        if zone_id: filter_info["zone"] = zone_id
        if version: filter_info["version"] = version
        if status: filter_info["status"] = status
        if release_type: filter_info["type"] = release_type
        if filter_info:
            print(f"   筛选条件: {filter_info}")
        print("=" * 70)
        print(f"{'版本号':<15} {'类型':<10} {'状态':<18} {'创建时间':<20} {'影响厂区数':<10}")
        print("-" * 70)

        for r in results:
            zone_count = len(self.query_service._get_release_zones(r))
            created_at = r.get("created_at", "")[:16].replace("T", " ")
            print(f"{r.get('version',''):<15} {r.get('release_type',''):<10} "
                  f"{r.get('status',''):<18} {created_at:<20} "
                  f"{zone_count:<10}")

        return results

    def query_rollbacks(self, start_date: str = None, end_date: str = None,
                        zone_id: str = None, version: str = None) -> list:
        from datetime import datetime

        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None

        results = self.query_service.query_rollbacks(
            start_date=start_dt,
            end_date=end_dt,
            zone_id=zone_id,
            version=version,
        )

        print(f"\n🔍 回滚记录检索 (共 {len(results)} 条)")
        filter_info = {}
        if start_date: filter_info["start"] = start_date
        if end_date: filter_info["end"] = end_date
        if zone_id: filter_info["zone"] = zone_id
        if version: filter_info["version"] = version
        if filter_info:
            print(f"   筛选条件: {filter_info}")
        print("=" * 70)
        print(f"{'回滚ID':<12} {'版本':<12} {'类型':<8} {'原因':<20} {'时间':<18}")
        print("-" * 70)

        for rb in results:
            rb_type = "演练" if rb.get("is_drill") else "正式"
            reason = (rb.get("reason", "") or "")[:18]
            exec_time = (rb.get("executed_at", "") or "")[:16].replace("T", " ")
            print(f"{rb.get('rollback_id',''):<12} {rb.get('to_version',''):<12} "
                  f"{rb_type:<8} {reason:<20} {exec_time:<18}")

        return results

    def export_query_results(self, output_format: str = "json",
                             start_date: str = None, end_date: str = None,
                             zone_id: str = None, version: str = None,
                             status: str = None, release_type: str = None,
                             output_path: str = None) -> str:
        from datetime import datetime
        from pathlib import Path

        start_dt = datetime.fromisoformat(start_date) if start_date else None
        end_dt = datetime.fromisoformat(end_date) if end_date else None
        status_enum = ReleaseStatus(status) if status else None
        type_enum = ReleaseType(release_type) if release_type else None

        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "json" if output_format == "json" else "csv"
            output_path = str(Path(CONFIG["storage"]["data_dir"]) / f"releases_export_{timestamp}.{ext}")

        path = self.query_service.export_releases(
            output_file=output_path,
            format=output_format,
            start_date=start_dt,
            end_date=end_dt,
            zone_id=zone_id,
            version=version,
            status=status_enum,
            release_type=type_enum,
        )

        print(f"\n📤 导出完成: {path}")
        return path

    def start_scheduler(self):
        self.scheduler.start()
        print(f"\n⏰ 计划任务调度器已启动")
        self.print_scheduler_status()

    def stop_scheduler(self):
        self.scheduler.stop()

    def print_scheduler_status(self):
        status = self.scheduler.get_status()

        print(f"\n⏰ 计划任务状态")
        print("=" * 60)
        print(f"运行中: {'是' if status['running'] else '否'}")
        print(f"任务数: {len(status['tasks'])}")
        print()

        for task in status["tasks"]:
            status_icon = "🟢" if task["enabled"] else "⚪"
            print(f"{status_icon} {task['name']}")
            print(f"   类型: {task['type']}  |  执行次数: {task['run_count']}")
            if task["last_run"]:
                print(f"   上次执行: {task['last_run']}")
            print(f"   下次执行: {task['next_run']}")
            print(f"   调度规则: {task['schedule']}")
            print()

    def run_scheduled_task_now(self, task_name: str):
        success = self.scheduler.run_task_now(task_name)
        if success:
            print(f"✅ 已立即执行任务: {task_name}")
        else:
            print(f"❌ 任务不存在: {task_name}")

    def list_all_releases(self, status: ReleaseStatus = None) -> List[ReleaseRecord]:
        releases = self.storage.list_releases(status=status)

        print(f"\n📋 发布列表 (共 {len(releases)} 条)")
        print("=" * 70)
        print(f"{'版本号':<15} {'类型':<10} {'状态':<20} {'创建时间':<25}")
        print("-" * 70)

        for r in releases:
            print(f"{r.version:<15} {r.release_type.value:<10} "
                  f"{r.status.value:<20} {r.created_at.strftime('%Y-%m-%d %H:%M'):<25}")

        return releases

    def get_release_detail(self, release_id: str) -> Optional[ReleaseRecord]:
        release = self.storage.load_release(release_id)
        if release:
            self._print_release_detail(release)
        else:
            print(f"未找到发布记录: {release_id}")
        return release

    def _print_release_detail(self, release: ReleaseRecord):
        print(f"\n📋 发布详情 - {release.version}")
        print("=" * 50)
        print(f"发布ID: {release.release_id}")
        print(f"版本号: {release.version}")
        print(f"发布类型: {release.release_type.value}")
        print(f"当前状态: {release.status.value}")
        print(f"创建人: {release.requester}")
        print(f"创建时间: {release.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"变更控制单: {release.change_control_id}")
        print(f"前序版本: {release.previous_version}")

        if release.pre_check_result:
            print(f"\n前置校验: {'通过' if release.pre_check_result.overall_pass else '未通过'}")
            print(f"  检查项数: {len(release.pre_check_result.checks)}")

        if release.approval_flow:
            flow = release.approval_flow
            print(f"\n审批流程:")
            print(f"  类型: {'紧急热修复' if flow.is_hotfix else '常规迭代'}")
            print(f"  状态: {'已完成' if flow.is_completed() else '进行中'}")

            if flow.is_hotfix:
                print(f"  紧急原因: {flow.hotfix_reason or '未提供'}")
                print(f"  紧急程度: {flow.hotfix_urgency}")
                if flow.deviation_report_id:
                    print(f"  关联偏差: {flow.deviation_report_id}")
                    if flow.deviation_report_description:
                        print(f"  偏差说明: {flow.deviation_report_description}")
                post_status = flow.get_post_sign_status()
                post_icon = "✅" if post_status == "completed" else "⏳"
                print(f"  事后补签状态: {post_icon} {post_status}")
                if flow.post_sign_deadline:
                    print(f"  补签截止: {flow.post_sign_deadline.strftime('%Y-%m-%d %H:%M')}")

            for step in flow.steps:
                status_icon = "✅" if step.status == ApprovalStatus.APPROVED else \
                              "❌" if step.status == ApprovalStatus.REJECTED else "⏳"
                is_post = " (事后补签)" if (step.status == ApprovalStatus.APPROVED and
                                             step.comment and "事后补签" in step.comment) else ""
                print(f"  {status_icon} {step.role.value}: {step.status.value}{is_post}")

        if release.grayscale_phases:
            print(f"\n灰度阶段:")
            for i, phase in enumerate(release.grayscale_phases, 1):
                status_icon = "✅" if phase.status == "completed" else \
                              "▶️" if phase.status == "in_progress" else "⏳"
                print(f"  {status_icon} 阶段 {i}: {phase.name} ({phase.status})")

        if release.rollback_records:
            print(f"\n回滚记录:")
            for rb in release.rollback_records:
                print(f"  - {rb.rollback_id}")
                print(f"    类型: {'演练' if rb.is_drill else '正式回滚'}")
                print(f"    原因: {rb.reason}")
                print(f"    从 {rb.from_version} 回滚至 {rb.to_version}")

    def get_factory_zone_status(self):
        zones = self.grayscale_manager.get_all_zone_status()
        print(f"\n🏭 厂区版本状态")
        print("=" * 60)
        print(f"{'厂区名称':<20} {'级别':<20} {'当前版本':<15}")
        print("-" * 60)
        for z in zones:
            print(f"{z['name']:<20} {z['tier']:<20} {z['current_version']:<15}")
        return zones

    def query_audit_logs(self, start_date: datetime = None,
                         end_date: datetime = None,
                         actor: str = None) -> list:
        logs = self.audit_logger.query(
            start_time=start_date,
            end_time=end_date,
            actor=actor,
        )

        print(f"\n📝 审计日志 (共 {len(logs)} 条)")
        print("=" * 70)
        for log in logs[-10:]:
            print(f"[{log.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"{log.actor} - {log.action} - {log.resource_type}:{log.resource_id}")

        return logs

    def run_full_demo(self):
        """
        运行完整的演示流程，展示系统全部功能
        """
        print("\n" + "=" * 60)
        print("🏥  医疗器械 QMS 版本发布与智能回滚自动化平台 - 完整演示")
        print("=" * 60)

        release = self.create_release(
            version="v2.4.0",
            release_type=ReleaseType.REGULAR,
            title="QMS 系统 2.4 版本 - 功能增强与bug修复",
            description="包含偏差管理模块优化、CAPA流程增强、报表功能升级",
            requester="dev_leader",
            change_control_id="CC-2024-032",
        )

        self.submit_for_precheck(release)

        if release.status == ReleaseStatus.PRE_CHECK_FAILED:
            print("\n⚠️  前置校验未通过，演示终止")
            return

        self.start_approval(release)

        self.approve_step(release, ApprovalRole.QUALITY, "qa_manager", "质量评估通过")
        self.approve_step(release, ApprovalRole.REGULATORY, "ra_specialist", "法规符合性确认")
        self.approve_step(release, ApprovalRole.RND, "rnd_manager", "设计控制与需求追溯确认")
        self.approve_step(release, ApprovalRole.PRODUCTION, "prod_supervisor", "生产影响评估通过")

        self.start_grayscale_release(release)

        for i in range(len(release.grayscale_phases)):
            print(f"\n--- 灰度阶段 {i + 1} ---")
            self.start_phase_by_index(release, i)

            print("  执行监控检查...")
            for check_round in range(3):
                result = self.monitor_and_check(release)
                if result["status"] != "normal":
                    print(f"  第 {check_round + 1} 次检查: 异常!")
                    break
                print(f"  第 {check_round + 1} 次检查: 正常")

            if release.status == ReleaseStatus.ROLLED_BACK:
                print("\n⚠️  灰度过程触发熔断，自动回滚")
                break

            self.advance_phase(release)

        if release.status == ReleaseStatus.FULLY_RELEASED:
            print(f"\n🎉 版本 {release.version} 发布成功!")

        self.run_drill("6月月度回滚演练", release)

        self.generate_weekly_report()

        print("\n" + "=" * 60)
        print("✅ 演示完成")
        print("=" * 60)

        self.list_all_releases()
        self.get_factory_zone_status()
        self.query_audit_logs()


def main():
    manager = QMSReleaseManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "demo":
            manager.run_full_demo()
        elif command == "list":
            manager.list_all_releases()
        elif command == "zones":
            manager.get_factory_zone_status()
        elif command == "report":
            manager.generate_weekly_report()
        elif command == "audit":
            manager.query_audit_logs()
        elif command == "drill":
            drill_name = sys.argv[2] if len(sys.argv) > 2 else "临时演练"
            manager.run_drill(drill_name)
        elif command == "detail":
            if len(sys.argv) > 2:
                manager.get_release_detail(sys.argv[2])
            else:
                print("请提供发布ID")
        elif command == "query":
            _handle_query_command(manager)
        elif command == "export":
            _handle_export_command(manager)
        elif command == "scheduler":
            _handle_scheduler_command(manager)
        elif command == "hotfix":
            _handle_hotfix_command(manager)
        elif command == "post-sign":
            _handle_post_sign_command(manager)
        else:
            print(f"未知命令: {command}")
            print_help()
    else:
        print_help()
        manager.run_full_demo()


def _parse_args(args):
    params = {}
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                params[key] = sys.argv[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1
    return params


def _handle_query_command(manager):
    params = _parse_args(sys.argv)
    query_type = params.get("type", "release")

    if query_type == "rollback":
        manager.query_rollbacks(
            start_date=params.get("start"),
            end_date=params.get("end"),
            zone_id=params.get("zone"),
            version=params.get("version"),
        )
    else:
        manager.query_releases(
            start_date=params.get("start"),
            end_date=params.get("end"),
            zone_id=params.get("zone"),
            version=params.get("version"),
            status=params.get("status"),
            release_type=params.get("release-type"),
        )


def _handle_export_command(manager):
    params = _parse_args(sys.argv)
    export_type = params.get("type", "release")
    output_format = params.get("format", "json")
    output_path = params.get("output")
    start_date = params.get("start")
    end_date = params.get("end")
    zone_id = params.get("zone")
    version = params.get("version")

    from datetime import datetime
    from pathlib import Path

    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None

    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "json" if output_format == "json" else "csv"
        prefix = "rollbacks" if export_type == "rollback" else "releases"
        output_path = str(Path(CONFIG["storage"]["data_dir"]) / f"{prefix}_export_{timestamp}.{ext}")

    if export_type == "rollback":
        path = manager.query_service.export_rollbacks(
            output_file=output_path,
            format=output_format,
            start_date=start_dt,
            end_date=end_dt,
            zone_id=zone_id,
            version=version,
        )
    else:
        from models import ReleaseStatus, ReleaseType
        status_enum = ReleaseStatus(params.get("status")) if params.get("status") else None
        type_enum = ReleaseType(params.get("release-type")) if params.get("release-type") else None

        path = manager.query_service.export_releases(
            output_file=output_path,
            format=output_format,
            start_date=start_dt,
            end_date=end_dt,
            zone_id=zone_id,
            version=version,
            status=status_enum,
            release_type=type_enum,
        )

    print(f"\n📤 导出完成: {path}")
    return path


def _handle_scheduler_command(manager):
    params = _parse_args(sys.argv)
    action = params.get("action", "status")

    if action == "start":
        manager.start_scheduler()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n停止调度器...")
            manager.stop_scheduler()
    elif action == "stop":
        manager.stop_scheduler()
    elif action == "status":
        manager.print_scheduler_status()
    elif action == "run":
        task_name = params.get("task", "weekly_report")
        manager.run_scheduled_task_now(task_name)
    else:
        print(f"未知调度操作: {action}")


def _handle_hotfix_command(manager):
    params = _parse_args(sys.argv)
    version = params.get("version", "v0.0.0-hotfix")
    title = params.get("title", "紧急热修复")
    reason = params.get("reason", "")
    urgency = params.get("urgency", "high")
    deviation_id = params.get("deviation-id", "")
    deviation_desc = params.get("deviation-desc", "")
    requester = params.get("requester", "system")

    manager.create_hotfix_release(
        version=version,
        title=title,
        hotfix_reason=reason,
        hotfix_urgency=urgency,
        deviation_report_id=deviation_id,
        deviation_report_description=deviation_desc,
        requester=requester,
    )


def _handle_post_sign_command(manager):
    params = _parse_args(sys.argv)
    release_id = params.get("release-id", "")
    role = params.get("role", "")
    signer = params.get("signer", "system")
    comment = params.get("comment", "")

    if not release_id or not role:
        print("请提供 --release-id 和 --role 参数")
        return

    release = manager.storage.load_release(release_id)
    if not release:
        print(f"未找到发布记录: {release_id}")
        return

    manager.post_sign_approval(
        release=release,
        role=ApprovalRole(role),
        signer=signer,
        comment=comment,
    )


def print_help():
    print("""
🏥  医疗器械 QMS 版本发布与智能回滚自动化平台

使用方法:
  python qms_release_manager.py [命令] [选项]

基础命令:
  demo                - 运行完整功能演示
  list                - 列出所有发布记录
  zones               - 查看厂区版本状态
  report              - 生成周度运营报表 (PDF + Excel)
  audit               - 查看审计日志
  drill [名称]        - 执行回滚演练
  detail [ID]         - 查看发布详情

历史检索与导出:
  query [选项]        - 检索发布/回滚记录
    --type release|rollback  检索类型 (默认 release)
    --start YYYY-MM-DD       开始日期
    --end YYYY-MM-DD         结束日期
    --zone <zone_id>         按厂区筛选
    --version <版本号>       按版本号筛选
    --status <状态>          按状态筛选
    --release-type <类型>    按发布类型筛选

  export [选项]       - 导出发布记录
    --format json|csv         导出格式 (默认 json)
    --output <路径>           输出文件路径
    --start/--end/--zone/...  筛选条件同 query

计划任务:
  scheduler [选项]    - 计划任务管理
    --action start          启动调度器
    --action stop           停止调度器
    --action status         查看状态 (默认)
    --action run --task <名> 立即执行指定任务

紧急热修复:
  hotfix [选项]       - 创建紧急热修复发布
    --version <版本号>       版本号
    --title <标题>           发布标题
    --reason <原因>          紧急原因
    --urgency low|medium|high 紧急程度 (默认 high)
    --deviation-id <ID>      关联偏差报告ID
    --deviation-desc <描述>  偏差报告描述
    --requester <申请人>     申请人

  post-sign [选项]    - 事后补签
    --release-id <ID>        发布ID
    --role <角色>            审批角色
    --signer <签署人>        签署人
    --comment <备注>         补签备注
""")


if __name__ == "__main__":
    main()
