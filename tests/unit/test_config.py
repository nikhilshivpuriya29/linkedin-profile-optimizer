"""Unit tests for configuration loading."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from linkedin_optimizer.config import load_config, PipelineConfig
from linkedin_optimizer.models import ScheduleInterval


def _write_config(tmp_path: Path, config: dict) -> Path:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    return config_file


@pytest.fixture
def sample_config():
    return {
        "linkedin_profile_url": "https://www.linkedin.com/in/testuser",
        "github_username": "testuser",
        "schedule_interval": "weekly",
        "models": {
            "analyzer_model_id": "mistralai/Mistral-7B-Instruct-v0.3",
            "content_model_id": "mistralai/Mistral-7B-Instruct-v0.3",
            "fallback_model_id": "google/gemma-2-9b-it",
        },
        "huggingface": {
            "api_token": "${HF_TOKEN}",
            "timeout_seconds": 30,
            "max_retries": 3,
        },
        "notifications": {"enabled": True, "method": "terminal_bell"},
        "data_dir": "./data",
        "approval_expiry_days": 7,
    }


def test_load_config_success(tmp_path, sample_config):
    os.environ["HF_TOKEN"] = "test-token-123"
    config_file = _write_config(tmp_path, sample_config)

    config = load_config(config_file)

    assert config.linkedin_profile_url == "https://www.linkedin.com/in/testuser"
    assert config.github_username == "testuser"
    assert config.schedule_interval == ScheduleInterval.WEEKLY
    assert config.analyzer_model_id == "mistralai/Mistral-7B-Instruct-v0.3"
    assert config.fallback_model_id == "google/gemma-2-9b-it"
    assert config.hf_api_token == "test-token-123"
    assert config.hf_timeout_seconds == 30
    assert config.hf_max_retries == 3
    assert config.notifications.enabled is True
    assert config.approval_expiry_days == 7

    del os.environ["HF_TOKEN"]


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.json")


def test_load_config_invalid_schedule(tmp_path, sample_config):
    sample_config["schedule_interval"] = "hourly"
    config_file = _write_config(tmp_path, sample_config)

    with pytest.raises(ValueError, match="Invalid schedule_interval"):
        load_config(config_file)


def test_load_config_no_schedule(tmp_path, sample_config):
    sample_config["schedule_interval"] = None
    config_file = _write_config(tmp_path, sample_config)

    config = load_config(config_file)
    assert config.schedule_interval is None


def test_load_config_env_var_not_set(tmp_path, sample_config):
    # Ensure HF_TOKEN is not set
    os.environ.pop("HF_TOKEN", None)
    config_file = _write_config(tmp_path, sample_config)

    config = load_config(config_file)
    assert config.hf_api_token == ""
