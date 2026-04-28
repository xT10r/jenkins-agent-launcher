"""Тесты модуля config."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.config import (
    AgentConfig, AppConfig, BehaviorConfig, LoggingConfig,
    resolve_config, save_ui_theme, _PLACEHOLDERS, DEFAULT_IGNORED_ENV_VARS,
)

TEST_VALUE = "test-value"


@pytest.fixture
def tmp_project(tmp_path):
    """Создать временную директорию проекта."""
    return tmp_path


@pytest.fixture
def valid_config_json():
    return {
        "agent": {
            "jenkinsUrl": "https://jenkins.demo.test",
            "agentName": "test-agent",
            "secret": (TEST_VALUE),
        },
        "behavior": {"maxRestarts": 3, "restartDelaySeconds": 10},
        "logging": {"dir": "mylogs", "rotation": "weekly", "maxDays": 7, "maxSizeMB": 25},
    }


class TestValidConfig:
    """Нормальная валидная конфигурация."""

    def test_resolve_from_json(self, tmp_project, valid_config_json):
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert cfg.agent.jenkins_url == "https://jenkins.demo.test"
        assert cfg.agent.agent_name == "test-agent"
        assert cfg.behavior.max_restarts == 3
        assert cfg.behavior.restart_delay == 10
        assert cfg.logging.dir == "mylogs"
        assert cfg.logging.rotation == "weekly"
        assert cfg.logging.max_days == 7
        assert cfg.config_path == str(cfg_path)
        assert any("Поиск config.json" in note for note in cfg.diagnostics)

    def test_template_bootstraps_local_config_when_real_config_missing(self, tmp_project):
        template = tmp_project / "config" / "config.template.json"
        template.parent.mkdir(exist_ok=True)
        template.write_text(json.dumps({
            "agent": {
                "jenkinsUrl": "https://jenkins.demo.test",
                "agentName": "windows-agent-1",
                "secret": "CHANGE_ME_SECRET",  # pragma: allowlist secret
            }
        }), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        bootstrapped = tmp_project / "config" / "config.json"
        assert bootstrapped.exists()
        assert cfg.config_path == str(bootstrapped)
        assert any("Создан локальный runtime-конфиг из шаблона" in note for note in cfg.diagnostics)
        assert any("CHANGE_ME" in error for error in errors)

    def test_cli_overrides_json(self, tmp_project, valid_config_json):
        cfg_path = tmp_project / "config.json"
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "https://override.com",
            "max_restarts": 99,
        })
        assert not errors
        assert cfg.agent.jenkins_url == "https://override.com"
        assert cfg.behavior.max_restarts == 99

    def test_env_overrides_json(self, tmp_project, valid_config_json, monkeypatch):
        cfg_path = tmp_project / "config.json"
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        monkeypatch.setenv("JENKINS_SECRET", TEST_VALUE)
        monkeypatch.setenv("JENKINS_WEB_SOCKET", "true")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert cfg.agent.secret == TEST_VALUE
        assert cfg.agent.websocket is True

    def test_defaults_without_json(self, tmp_project):
        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
        })
        assert not errors
        assert cfg.behavior.max_restarts == -1
        assert cfg.logging.rotation == "daily"
        assert cfg.logging.max_days == 14
        assert cfg.ui.theme == "light"
        assert [item.name for item in cfg.environment.ignored_vars] == [
            item["name"] for item in DEFAULT_IGNORED_ENV_VARS
        ]

    def test_environment_ignored_vars_from_json(self, tmp_project, valid_config_json):
        valid_config_json["environment"] = {
            "ignoredVars": [
                {
                    "name": "CUSTOM_SECRET",
                    "reason": "Пользовательский секрет не должен попасть в java.",
                },
                "CUSTOM_TOKEN",
            ]
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert [item.name for item in cfg.environment.ignored_vars] == [
            "CUSTOM_SECRET",
            "CUSTOM_TOKEN",
        ]
        assert cfg.environment.ignored_vars[0].reason == "Пользовательский секрет не должен попасть в java."

    def test_agent_verify_ssl_defaults_to_true_for_https(self, tmp_project):
        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
        })
        assert not errors
        assert cfg.effective_agent_verify_ssl() is True

    def test_agent_verify_ssl_defaults_to_false_for_http(self, tmp_project):
        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "http://jenkins.demo.test:8080",
            "agent_name": "a",
            "secret": "s",
        })
        assert not errors
        assert cfg.effective_agent_verify_ssl() is False

    def test_agent_and_fallback_verify_ssl_from_json(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["verifySsl"] = False
        valid_config_json["fallback"] = {
            "agentJarUrl": "https://fallback.example.com/agent.jar",
            "verifySsl": False,
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert cfg.agent.verify_ssl is False
        assert cfg.effective_agent_verify_ssl() is False
        assert cfg.download.fallback_verify_ssl is False

    def test_ui_theme_from_json(self, tmp_project, valid_config_json):
        valid_config_json["ui"] = {"theme": "dark"}
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert cfg.ui.theme == "dark"

    def test_ui_start_minimized_defaults_to_true(self, tmp_project):
        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
        })
        assert not errors
        assert cfg.ui.start_minimized is True

    def test_ui_start_minimized_from_json(self, tmp_project, valid_config_json):
        valid_config_json["ui"] = {"theme": "dark", "startMinimized": False}
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)
        assert not errors
        assert cfg.ui.theme == "dark"
        assert cfg.ui.start_minimized is False

    def test_update_uses_explicit_url(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "url": "https://downloads.example.com/agent-launcher.exe",
            "version": "1.2.0.0",
            "sha256": "a" * 64,
            "intervalHours": 6,
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.update.url == "https://downloads.example.com/agent-launcher.exe"
        assert cfg.update.effective_url() == "https://downloads.example.com/agent-launcher.exe"
        assert cfg.update.version == "1.2.0.0"
        assert cfg.update.sha256 == "a" * 64

    def test_update_local_path_is_resolved_relative_to_project(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "localPath": "artifacts/agent-launcher.exe",
            "version": "1.2.0.0",
            "sha256": "b" * 64,
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.update.local_path == str((tmp_project / "artifacts" / "agent-launcher.exe").resolve())

    def test_update_check_url_remains_legacy_alias(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "checkUrl": "https://legacy.example.com/launcher.exe",
            "version": "1.2.0.0",
            "sha256": "c" * 64,
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.update.check_url == "https://legacy.example.com/launcher.exe"
        assert cfg.update.effective_url() == "https://legacy.example.com/launcher.exe"

    def test_update_source_object_is_supported(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "source": {
                "type": "localPath",
                "location": "artifacts/agent-launcher.exe",
            },
            "version": "1.2.0.0",
            "sha256": "d" * 64,
            "publisher": "Jenkins Agent Launcher Contributors",
        }
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.update.local_path == str((tmp_project / "artifacts" / "agent-launcher.exe").resolve())
        assert cfg.update.publisher == "Jenkins Agent Launcher Contributors"

    def test_save_ui_theme(self, tmp_project, valid_config_json):
        cfg_path = tmp_project / "config" / "config.json"
        cfg_path.parent.mkdir(exist_ok=True)
        cfg_path.write_text(json.dumps(valid_config_json), encoding="utf-8")

        save_ui_theme(tmp_project, "dark")

        saved = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert saved["ui"]["theme"] == "dark"
        assert saved["agent"]["agentName"] == "test-agent"

    def test_agent_jar_name_accepts_absolute_path(self, tmp_project, valid_config_json):
        absolute_jar = tmp_project / "artifacts" / "agent.jar"
        valid_config_json["agent"]["agentJarName"] = str(absolute_jar)
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.agent.agent_jar_path == str(absolute_jar)

    def test_java_home_accepts_absolute_path(self, tmp_project, valid_config_json):
        absolute_java_home = tmp_project / "jdk-17"
        valid_config_json["agent"]["javaHome"] = str(absolute_java_home)
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.agent.java_home == str(absolute_java_home)

    def test_log_file_name_uses_logging_dir_for_simple_filename(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["logFileName"] = "runtime.log"
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.agent.log_path == str((tmp_project / "mylogs" / "runtime.log").resolve())

    def test_log_file_name_accepts_absolute_path(self, tmp_project, valid_config_json):
        absolute_log = tmp_project / "runtime" / "launcher.log"
        valid_config_json["agent"]["logFileName"] = str(absolute_log)
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.agent.log_path == str(absolute_log)

    def test_bom_is_detected_and_rewritten(self, tmp_project, valid_config_json):
        cfg_path = tmp_project / "config.json"
        cfg_path.write_text("\ufeff" + json.dumps(valid_config_json), encoding="utf-8")

        cfg, errors = resolve_config(tmp_project)

        assert not errors
        assert cfg.agent.agent_name == "test-agent"
        assert any("UTF-8 BOM" in note for note in cfg.diagnostics)
        assert not cfg_path.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_invalid_json_is_reported_in_diagnostics(self, tmp_project):
        cfg_path = tmp_project / "config.json"
        cfg_path.write_text("{invalid", encoding="utf-8")

        cfg, errors = resolve_config(tmp_project, {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
        })

        assert not errors
        assert any("Ошибка чтения config.json" in note for note in cfg.diagnostics)


class TestInvalidConfig:
    """Невалидная конфигурация — placeholder, пустые поля."""

    def test_missing_url(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["jenkinsUrl"] = ""
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("JenkinsUrl" in e for e in errors)

    def test_missing_name(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["agentName"] = ""
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("AgentName" in e for e in errors)

    def test_missing_secret(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["secret"] = ""
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("Secret" in e for e in errors)

    def test_placeholder_url(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["jenkinsUrl"] = "http://jenkins.example.com:8080"
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("example.com" in e for e in errors)

    def test_placeholder_secret(self, tmp_project, valid_config_json):
        valid_config_json["agent"]["secret"] = "CHANGE_ME_SECRET"  # pragma: allowlist secret
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("CHANGE_ME" in e for e in errors)

    def test_update_requires_source_when_enabled(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "version": "1.2.0.0",
            "sha256": "e" * 64,
        }
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))

        cfg, errors = resolve_config(tmp_project)

        assert any("update.source.location" in error for error in errors)

    def test_update_rejects_multiple_sources(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "url": "https://downloads.example.com/launcher.exe",
            "localPath": "artifacts/agent-launcher.exe",
            "version": "1.2.0.0",
            "sha256": "f" * 64,
        }
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))

        cfg, errors = resolve_config(tmp_project)

        assert any("нельзя задавать одновременно" in error for error in errors)

    def test_update_requires_version_when_enabled(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "url": "https://downloads.example.com/launcher.exe",
            "sha256": "1" * 64,
        }
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))

        _, errors = resolve_config(tmp_project)

        assert any("update.version" in error for error in errors)

    def test_update_requires_sha256_when_enabled(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "url": "https://downloads.example.com/launcher.exe",
            "version": "1.2.0.0",
        }
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))

        _, errors = resolve_config(tmp_project)

        assert any("update.sha256" in error for error in errors)

    def test_update_rejects_invalid_sha256(self, tmp_project, valid_config_json):
        valid_config_json["update"] = {
            "enabled": True,
            "url": "https://downloads.example.com/launcher.exe",
            "version": "1.2.0.0",
            "sha256": "broken",
        }
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))

        _, errors = resolve_config(tmp_project)

        assert any("64 hex" in error for error in errors)


class TestLoggingConfig:
    """Валидация настроек логирования."""

    def test_invalid_rotation(self, tmp_project, valid_config_json):
        valid_config_json["logging"]["rotation"] = "hourly"
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("rotation" in e.lower() for e in errors)

    def test_negative_max_days(self, tmp_project, valid_config_json):
        valid_config_json["logging"]["maxDays"] = -5
        (tmp_project / "config.json").write_text(json.dumps(valid_config_json))
        cfg, errors = resolve_config(tmp_project)
        assert any("maxDays" in e or "max_days" in e for e in errors) or len(errors) > 0
