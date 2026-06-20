"""
医疗器械 QMS - 通知模块
Medical Device QMS - Notification Module
支持企微、钉钉、邮件多通道通知
"""

import json
from typing import List, Dict, Any
from abc import ABC, abstractmethod

from config import CONFIG


class NotificationChannel(ABC):
    @abstractmethod
    def send(self, title: str, content: str, **kwargs) -> bool:
        pass


class WeChatWorkChannel(NotificationChannel):
    def __init__(self, webhook_url: str, mentioned_mobiles: List[str] = None):
        self.webhook_url = webhook_url
        self.mentioned_mobiles = mentioned_mobiles or []

    def send(self, title: str, content: str, **kwargs) -> bool:
        if not self.webhook_url:
            print(f"[企微通知-模拟] {title}\n{content}")
            return True

        try:
            import requests
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"## {title}\n\n{content}"
                }
            }
            if self.mentioned_mobiles:
                payload["markdown"]["mentioned_mobile_list"] = self.mentioned_mobiles

            response = requests.post(self.webhook_url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"企微通知发送失败: {e}")
            return False


class DingTalkChannel(NotificationChannel):
    def __init__(self, webhook_url: str, at_mobiles: List[str] = None):
        self.webhook_url = webhook_url
        self.at_mobiles = at_mobiles or []

    def send(self, title: str, content: str, **kwargs) -> bool:
        if not self.webhook_url:
            print(f"[钉钉通知-模拟] {title}\n{content}")
            return True

        try:
            import requests
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"## {title}\n\n{content}"
                },
                "at": {
                    "atMobiles": self.at_mobiles,
                    "isAtAll": False
                }
            }

            response = requests.post(self.webhook_url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"钉钉通知发送失败: {e}")
            return False


class EmailChannel(NotificationChannel):
    def __init__(self, smtp_server: str, smtp_port: int,
                 sender: str, recipients: List[str]):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender = sender
        self.recipients = recipients

    def send(self, title: str, content: str, **kwargs) -> bool:
        if not self.smtp_server:
            print(f"[邮件通知-模拟] {title}\n收件人: {', '.join(self.recipients)}\n{content}")
            return True

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header

            msg = MIMEText(content, 'plain', 'utf-8')
            msg['From'] = Header(self.sender, 'utf-8')
            msg['To'] = Header(', '.join(self.recipients), 'utf-8')
            msg['Subject'] = Header(title, 'utf-8')

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.sendmail(self.sender, self.recipients, msg.as_string())
            return True
        except Exception as e:
            print(f"邮件通知发送失败: {e}")
            return False


class NotificationService:
    def __init__(self):
        self.channels: Dict[str, NotificationChannel] = {}
        self.enabled = CONFIG["notification"]["enabled"]
        self._init_channels()

    def _init_channels(self):
        notif_config = CONFIG["notification"]

        if "wechat_work" in notif_config:
            wc = notif_config["wechat_work"]
            self.channels["wechat_work"] = WeChatWorkChannel(
                webhook_url=wc.get("webhook_url", ""),
                mentioned_mobiles=wc.get("mentioned_mobile_list", []),
            )

        if "dingtalk" in notif_config:
            dt = notif_config["dingtalk"]
            self.channels["dingtalk"] = DingTalkChannel(
                webhook_url=dt.get("webhook_url", ""),
                at_mobiles=dt.get("at_mobiles", []),
            )

        if "email" in notif_config:
            em = notif_config["email"]
            self.channels["email"] = EmailChannel(
                smtp_server=em.get("smtp_server", ""),
                smtp_port=em.get("smtp_port", 587),
                sender=em.get("sender", ""),
                recipients=em.get("recipients", []),
            )

    def send(self, title: str, content: str,
             channels: List[str] = None, **kwargs) -> Dict[str, bool]:
        if not self.enabled:
            print(f"[通知已禁用] {title}")
            return {"disabled": True}

        target_channels = channels or list(self.channels.keys())
        results = {}

        for channel_name in target_channels:
            if channel_name in self.channels:
                results[channel_name] = self.channels[channel_name].send(
                    title, content, **kwargs
                )

        return results

    def notify_release_status(self, release_id: str, version: str,
                              status: str, extra_info: str = "") -> Dict[str, bool]:
        title = f"【QMS版本发布】{version} - {status}"
        content = f"发布ID: {release_id}\n版本号: {version}\n状态: {status}"
        if extra_info:
            content += f"\n\n{extra_info}"
        return self.send(title, content)

    def notify_circuit_breaker(self, release_id: str, version: str,
                               reason: str, affected_zones: List[str]) -> Dict[str, bool]:
        title = f"【紧急熔断告警】版本 {version} 发布已熔断"
        content = (
            f"**发布ID**: {release_id}\n"
            f"**版本号**: {version}\n"
            f"**熔断原因**: {reason}\n"
            f"**影响厂区**: {', '.join(affected_zones)}\n\n"
            f"⚠️ 系统已自动触发熔断机制，请相关人员立即关注处理。"
        )
        return self.send(title, content)

    def notify_rollback_complete(self, release_id: str, version: str,
                                 rollback_version: str,
                                 affected_zones: List[str]) -> Dict[str, bool]:
        title = f"【回滚完成】版本 {version} 已回滚至 {rollback_version}"
        content = (
            f"**发布ID**: {release_id}\n"
            f"**原版本**: {version}\n"
            f"**回滚至**: {rollback_version}\n"
            f"**影响厂区**: {', '.join(affected_zones)}\n\n"
            f"回滚操作已完成，请确认系统运行正常。"
        )
        return self.send(title, content)
