"""
医疗器械 QMS - 系统配置
Medical Device QMS - System Configuration
"""

from models import FactoryTier, CircuitBreakerConfig


CONFIG = {
    "system": {
        "name": "医疗器械 QMS 版本发布与智能回滚自动化平台",
        "version": "1.0.0",
        "timezone": "Asia/Shanghai",
        "gxp_compliance_enabled": True,
        "audit_log_immutable": True,
    },

    "notification": {
        "channels": ["wechat_work", "dingtalk", "email"],
        "wechat_work": {
            "webhook_url": "",
            "mentioned_mobile_list": [],
        },
        "dingtalk": {
            "webhook_url": "",
            "at_mobiles": [],
        },
        "email": {
            "smtp_server": "",
            "smtp_port": 587,
            "sender": "",
            "recipients": [],
        },
        "enabled": False,
    },

    "pre_check": {
        "change_control_required": True,
        "deviation_check_enabled": True,
        "capa_check_enabled": True,
        "document_check_enabled": True,
        "max_open_deviations_allowed": 0,
        "max_open_capas_allowed": 0,
        "document_version_consistency_required": True,
    },

    "approval": {
        "regular_flow": ["quality", "regulatory", "rnd", "production"],
        "hotfix_flow": ["quality", "regulatory"],
        "hotfix_parallel": True,
        "hotfix_require_post_sign": True,
        "approval_timeout_hours": 72,
        "escalation_enabled": True,
        "role_approvers": {
            "quality": ["quality_manager", "qa_director"],
            "regulatory": ["regulatory_affairs", "ra_manager"],
            "rnd": ["rnd_manager", "engineering_director"],
            "production": ["production_manager", "operations_director"],
        },
    },

    "grayscale": {
        "default_phases": [
            {
                "name": "非核心/研发厂区",
                "tier": FactoryTier.TIER_3_NON_CORE,
                "duration_minutes": 30,
                "monitor_interval_minutes": 5,
            },
            {
                "name": "常规组装线",
                "tier": FactoryTier.TIER_2_ASSEMBLY,
                "duration_minutes": 60,
                "monitor_interval_minutes": 5,
            },
            {
                "name": "无菌/高值耗材产线",
                "tier": FactoryTier.TIER_1_STERILE,
                "duration_minutes": 120,
                "monitor_interval_minutes": 5,
            },
        ],
        "hotfix_phases_count": 1,
    },

    "circuit_breaker": {
        "deviation_rate_threshold": 2.0,
        "anomaly_delay_rate_threshold": 5.0,
        "approval_block_rate_threshold": 10.0,
        "consecutive_failures_trigger": 3,
        "auto_rollback_enabled": True,
        "rollback_timeout_minutes": 30,
    },

    "monitoring": {
        "metrics_source": "qms_api",
        "default_interval_minutes": 5,
        "retention_days": 90,
        "metrics": [
            {"key": "deviation_rate", "name": "偏差发生率", "unit": "%"},
            {"key": "anomaly_delay_rate", "name": "异常单处理延迟率", "unit": "%"},
            {"key": "approval_block_rate", "name": "审批流程阻塞率", "unit": "%"},
        ],
    },

    "reporting": {
        "weekly_report_enabled": True,
        "weekly_report_day": "monday",
        "weekly_report_time": "09:00",
        "formats": ["pdf", "excel"],
        "retention_days": 365,
    },

    "drill": {
        "monthly_drill_enabled": False,
        "drill_day_of_month": 15,
        "drill_time": "02:00",
        "drill_zones": ["tier3_rd_01", "tier3_office_01"],
        "auto_archive_results": True,
    },

    "storage": {
        "type": "local",
        "data_dir": "./data",
        "audit_log_file": "./data/audit_log.jsonl",
        "releases_dir": "./data/releases",
        "reports_dir": "./data/reports",
    },

    "factory_zones": [
        {
            "zone_id": "tier3_rd_01",
            "name": "研发中心测试环境",
            "tier": FactoryTier.TIER_3_NON_CORE,
            "description": "非核心研发测试厂区",
            "current_version": "v2.3.0",
        },
        {
            "zone_id": "tier3_office_01",
            "name": "行政办公区系统",
            "tier": FactoryTier.TIER_3_NON_CORE,
            "description": "非核心办公系统厂区",
            "current_version": "v2.3.0",
        },
        {
            "zone_id": "tier2_assembly_01",
            "name": "组装一车间",
            "tier": FactoryTier.TIER_2_ASSEMBLY,
            "description": "常规产品组装产线",
            "current_version": "v2.3.0",
        },
        {
            "zone_id": "tier2_assembly_02",
            "name": "组装二车间",
            "tier": FactoryTier.TIER_2_ASSEMBLY,
            "description": "常规产品组装产线",
            "current_version": "v2.3.0",
        },
        {
            "zone_id": "tier1_sterile_01",
            "name": "无菌生产车间",
            "tier": FactoryTier.TIER_1_STERILE,
            "description": "无菌高值耗材产线",
            "current_version": "v2.3.0",
        },
        {
            "zone_id": "tier1_sterile_02",
            "name": "洁净包装车间",
            "tier": FactoryTier.TIER_1_STERILE,
            "description": "洁净区包装产线",
            "current_version": "v2.3.0",
        },
    ],
}


def get_circuit_breaker_config() -> CircuitBreakerConfig:
    cb = CONFIG["circuit_breaker"]
    return CircuitBreakerConfig(
        deviation_rate_threshold=cb["deviation_rate_threshold"],
        anomaly_delay_rate_threshold=cb["anomaly_delay_rate_threshold"],
        approval_block_rate_threshold=cb["approval_block_rate_threshold"],
        consecutive_failures_trigger=cb["consecutive_failures_trigger"],
        auto_rollback_enabled=cb["auto_rollback_enabled"],
    )


def get_factory_zones():
    from models import FactoryZone
    return [
        FactoryZone(
            zone_id=z["zone_id"],
            name=z["name"],
            tier=z["tier"],
            description=z["description"],
            current_version=z["current_version"],
        )
        for z in CONFIG["factory_zones"]
    ]
