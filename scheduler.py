"""
医疗器械 QMS - 计划任务调度器
Medical Device QMS - Scheduled Task Scheduler
支持自动执行月度回滚演练和周度报表
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, List
import logging

from models import ReleaseRecord, ReleaseType, ReleaseStatus, ApprovalRole
from config import CONFIG
from audit_log import AuditLogger
from reports import DrillManager, ReportGenerator
from storage import ReleaseStorage


class ScheduledTask:
    def __init__(self, name: str, task_type: str, schedule: str,
                 enabled: bool = True):
        self.name = name
        self.task_type = task_type
        self.schedule = schedule
        self.enabled = enabled
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0


class TaskScheduler:
    _instance = None

    def __init__(self):
        self.audit_logger = AuditLogger()
        self.storage = ReleaseStorage()
        self.drill_manager = DrillManager()
        self.report_generator = ReportGenerator()

        self.tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_interval = 60

        self._init_default_tasks()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _init_default_tasks(self):
        drill_config = CONFIG["drill"]
        if drill_config.get("monthly_drill_enabled", False):
            self.tasks["monthly_drill"] = ScheduledTask(
                name="月度回滚演练",
                task_type="drill",
                schedule=f"monthly day={drill_config.get('drill_day_of_month', 15)} time={drill_config.get('drill_time', '02:00')}",
                enabled=True,
            )

        report_config = CONFIG["reporting"]
        if report_config.get("weekly_report_enabled", False):
            self.tasks["weekly_report"] = ScheduledTask(
                name="周度运营报表",
                task_type="report",
                schedule=f"weekly day={report_config.get('weekly_report_day', 'monday')} time={report_config.get('weekly_report_time', '09:00')}",
                enabled=True,
            )

    def start(self):
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self.audit_logger.log_action(
            actor="system",
            action="scheduler_started",
            resource_type="scheduler",
            resource_id="main",
            details={"tasks_count": len(self.tasks)},
        )

        print("✅ 计划任务调度器已启动")
        for name, task in self.tasks.items():
            if task.enabled:
                next_run = self._calc_next_run(task)
                print(f"   - {task.name}: 下次执行 {next_run.strftime('%Y-%m-%d %H:%M')}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

        self.audit_logger.log_action(
            actor="system",
            action="scheduler_stopped",
            resource_type="scheduler",
            resource_id="main",
            details={"tasks_count": len(self.tasks)},
        )

        print("⏹️  计划任务调度器已停止")

    def _run_loop(self):
        while self._running:
            try:
                self._check_and_run_tasks()
            except Exception as e:
                print(f"❌ 计划任务执行出错: {e}")

            time.sleep(self._check_interval)

    def _check_and_run_tasks(self):
        now = datetime.now()

        for name, task in self.tasks.items():
            if not task.enabled:
                continue

            next_run = self._calc_next_run(task)
            task.next_run = next_run

            if now >= next_run and (task.last_run is None or (now - task.last_run) > timedelta(minutes=1)):
                self._execute_task(task)
                task.last_run = now
                task.run_count += 1

    def _calc_next_run(self, task: ScheduledTask) -> datetime:
        now = datetime.now()

        if task.task_type == "drill":
            day_of_month = CONFIG["drill"].get("drill_day_of_month", 15)
            time_str = CONFIG["drill"].get("drill_time", "02:00")
            hour, minute = map(int, time_str.split(":"))

            if now.day < day_of_month:
                target = now.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
            else:
                if now.month == 12:
                    target = now.replace(year=now.year + 1, month=1, day=day_of_month,
                                        hour=hour, minute=minute, second=0, microsecond=0)
                else:
                    target = now.replace(month=now.month + 1, day=day_of_month,
                                        hour=hour, minute=minute, second=0, microsecond=0)

            return target

        elif task.task_type == "report":
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2,
                "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            }
            day_name = CONFIG["reporting"].get("weekly_report_day", "monday").lower()
            target_weekday = day_map.get(day_name, 0)
            time_str = CONFIG["reporting"].get("weekly_report_time", "09:00")
            hour, minute = map(int, time_str.split(":"))

            days_ahead = target_weekday - now.weekday()
            if days_ahead < 0 or (days_ahead == 0 and
                                  (now.hour > hour or (now.hour == hour and now.minute >= minute))):
                days_ahead += 7

            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)

            return target

        return now + timedelta(hours=1)

    def _execute_task(self, task: ScheduledTask):
        print(f"\n⏰ 执行计划任务: {task.name} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")

        try:
            if task.task_type == "drill":
                self._run_monthly_drill()
            elif task.task_type == "report":
                self._run_weekly_report()

            self.audit_logger.log_action(
                actor="system",
                action="scheduled_task_executed",
                resource_type="scheduler",
                resource_id=task.name,
                details={
                    "task_type": task.task_type,
                    "run_count": task.run_count + 1,
                    "status": "success",
                },
            )

            print(f"✅ 计划任务完成: {task.name}")

        except Exception as e:
            print(f"❌ 计划任务失败: {task.name} - {e}")

            self.audit_logger.log_action(
                actor="system",
                action="scheduled_task_failed",
                resource_type="scheduler",
                resource_id=task.name,
                details={
                    "task_type": task.task_type,
                    "error": str(e),
                },
                is_critical=True,
            )

    def _run_monthly_drill(self):
        releases = self.storage.list_releases(status=ReleaseStatus.FULLY_RELEASED)

        if not releases:
            releases = self.storage.list_releases()
            if not releases:
                raise ValueError("没有可用的发布记录用于演练")

        target_release = releases[0]

        drill = self.drill_manager.schedule_drill(
            name=f"{datetime.now().strftime('%Y年%m月')}月度回滚演练",
            scheduled_at=datetime.now(),
            is_automated=True,
        )

        self.drill_manager.execute_drill(drill, target_release)

    def _run_weekly_report(self):
        releases = self.storage.list_releases()
        report = self.report_generator.generate_weekly_report(releases)
        files = self.report_generator.export_full_report(report)

        print(f"📊 周报已生成:")
        print(f"   Excel: {files['excel']}")
        print(f"   PDF: {files['pdf']}")

    def get_status(self) -> Dict:
        status = {
            "running": self._running,
            "tasks": [],
        }

        for name, task in self.tasks.items():
            task_info = {
                "name": task.name,
                "type": task.task_type,
                "enabled": task.enabled,
                "schedule": task.schedule,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": self._calc_next_run(task).isoformat(),
                "run_count": task.run_count,
            }
            status["tasks"].append(task_info)

        return status

    def run_task_now(self, task_name: str) -> bool:
        if task_name not in self.tasks:
            return False

        task = self.tasks[task_name]
        self._execute_task(task)
        task.last_run = datetime.now()
        task.run_count += 1
        return True

    def list_tasks(self) -> List[Dict]:
        tasks = []
        for name, task in self.tasks.items():
            tasks.append({
                "name": task.name,
                "type": task.task_type,
                "enabled": task.enabled,
                "schedule": task.schedule,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": self._calc_next_run(task).isoformat(),
                "run_count": task.run_count,
            })
        return tasks


def start_scheduler():
    scheduler = TaskScheduler()
    scheduler.start()
    return scheduler


def stop_scheduler():
    scheduler = TaskScheduler()
    scheduler.stop()
