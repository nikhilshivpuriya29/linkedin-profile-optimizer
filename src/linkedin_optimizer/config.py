"""Configuration management for the LinkedIn Profile Optimizer pipeline."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import ScheduleInterval


@dataclass
class HFModelConfig:
    """Configuration for Hugging Face model access."""

    model_id: str
    fallback_model_id: str
    api_token: str
    timeout_seconds: int = 30
    max_retries: int = 3
    backoff_base_seconds: int = 2

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "fallback_model_id": self.fallback_model_id,
            "api_token": self.api_token,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "backoff_base_seconds": self.backoff_base_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HFModelConfig":
        return cls(
            model_id=data["model_id"],
            fallback_model_id=data["fallback_model_id"],
            api_token=data.get("api_token", ""),
            timeout_seconds=data.get("timeout_seconds", 30),
            max_retries=data.get("max_retries", 3),
            backoff_base_seconds=data.get("backoff_base_seconds", 2),
        )


@dataclass
class NotificationConfig:
    """Configuration for user notifications."""

    enabled: bool = True
    method: str = "terminal_bell"


@dataclass
class PipelineConfig:
    """Main pipeline configuration."""

    linkedin_profile_url: str
    github_username: Optional[str]
    schedule_interval: Optional[ScheduleInterval]
    analyzer_model_id: str
    content_model_id: str
    fallback_model_id: str
    data_dir: str
    hf_api_token: str
    hf_timeout_seconds: int = 30
    hf_max_retries: int = 3
    notifications: NotificationConfig = None
    approval_expiry_days: int = 7

    def __post_init__(self):
        if self.notifications is None:
            self.notifications = NotificationConfig()

    def to_dict(self) -> dict:
        return {
            "linkedin_profile_url": self.linkedin_profile_url,
            "github_username": self.github_username,
            "schedule_interval": self.schedule_interval.value if self.schedule_interval else None,
            "analyzer_model_id": self.analyzer_model_id,
            "content_model_id": self.content_model_id,
            "fallback_model_id": self.fallback_model_id,
            "data_dir": self.data_dir,
            "hf_api_token": self.hf_api_token,
            "hf_timeout_seconds": self.hf_timeout_seconds,
            "hf_max_retries": self.hf_max_retries,
            "notifications": {
                "enabled": self.notifications.enabled,
                "method": self.notifications.method,
            },
            "approval_expiry_days": self.approval_expiry_days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineConfig":
        schedule_interval = None
        if data.get("schedule_interval") is not None:
            schedule_interval = ScheduleInterval(data["schedule_interval"])
        notif_data = data.get("notifications", {})
        notifications = NotificationConfig(
            enabled=notif_data.get("enabled", True),
            method=notif_data.get("method", "terminal_bell"),
        )
        return cls(
            linkedin_profile_url=data["linkedin_profile_url"],
            github_username=data.get("github_username"),
            schedule_interval=schedule_interval,
            analyzer_model_id=data.get("analyzer_model_id", ""),
            content_model_id=data.get("content_model_id", ""),
            fallback_model_id=data.get("fallback_model_id", ""),
            data_dir=data.get("data_dir", "./data"),
            hf_api_token=data.get("hf_api_token", ""),
            hf_timeout_seconds=data.get("hf_timeout_seconds", 30),
            hf_max_retries=data.get("hf_max_retries", 3),
            notifications=notifications,
            approval_expiry_days=data.get("approval_expiry_days", 7),
        )


def _resolve_env_vars(value: str) -> str:
    """Resolve environment variable references like ${VAR_NAME}."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def load_config(config_path: str | Path) -> PipelineConfig:
    """Load pipeline configuration from a JSON file.

    Args:
        config_path: Path to the config.json file.

    Returns:
        PipelineConfig instance.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config file is invalid.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r") as f:
        raw = json.load(f)

    # Resolve environment variables
    hf_token = _resolve_env_vars(raw.get("huggingface", {}).get("api_token", ""))

    # Parse schedule interval
    schedule_str = raw.get("schedule_interval")
    schedule_interval = None
    if schedule_str:
        try:
            schedule_interval = ScheduleInterval(schedule_str)
        except ValueError:
            raise ValueError(
                f"Invalid schedule_interval: {schedule_str}. "
                f"Must be one of: daily, weekly, monthly"
            )

    # Parse notifications
    notif_raw = raw.get("notifications", {})
    notifications = NotificationConfig(
        enabled=notif_raw.get("enabled", True),
        method=notif_raw.get("method", "terminal_bell"),
    )

    models = raw.get("models", {})

    return PipelineConfig(
        linkedin_profile_url=raw["linkedin_profile_url"],
        github_username=raw.get("github_username"),
        schedule_interval=schedule_interval,
        analyzer_model_id=models.get("analyzer_model_id", ""),
        content_model_id=models.get("content_model_id", ""),
        fallback_model_id=models.get("fallback_model_id", ""),
        data_dir=raw.get("data_dir", "./data"),
        hf_api_token=hf_token,
        hf_timeout_seconds=raw.get("huggingface", {}).get("timeout_seconds", 30),
        hf_max_retries=raw.get("huggingface", {}).get("max_retries", 3),
        notifications=notifications,
        approval_expiry_days=raw.get("approval_expiry_days", 7),
    )
