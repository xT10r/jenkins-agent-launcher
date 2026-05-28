"""Ломающие тесты модуля config."""

import json
import pytest
from pathlib import Path

from src.config import resolve_config


class TestBrokenJSON:
    """Сломанный JSON - должно не падать, а возвращать ошибки валидации."""

    def test_empty_file(self, tmp_path):
        (tmp_path / "config.json").write_text("")
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com", "agent_name": "a", "secret": "s"
        })
        # Без валидного JSON - должны быть дефолты
        assert isinstance(cfg.behavior.max_restarts, int)

    def test_not_json(self, tmp_path):
        (tmp_path / "config.json").write_text("this is not json")
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com", "agent_name": "a", "secret": "s"
        })
        # BOM ����, �� JSON ���������\n        assert cfg is not None

    def test_truncated_json(self, tmp_path):
        (tmp_path / "config.json").write_text('{"agent": {"jenkinsUrl": "https://ok.com"')
        cfg, errors = resolve_config(tmp_path, {
            "agent_name": "a", "secret": "s"
        })
        # Должно обработать ошибку и продолжить с CLI
        assert cfg.agent.agent_name == "a"

    def test_null_fields(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {"jenkinsUrl": None, "agentName": "a", "secret": "s"},
        }))
        cfg, errors = resolve_config(tmp_path)
        # null = �� �����, ������ ��������\n        assert len(errors) >= 1

    def test_wrong_types(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {"jenkinsUrl": 12345, "agentName": True, "secret": []},
            "behavior": {"maxRestarts": "not_a_number"},
        }))
        # Должно gracefully обработать - не упасть
        cfg, errors = resolve_config(tmp_path)
        assert cfg is not None

    def test_unicode_bomb(self, tmp_path):
        bom = "\ufeff"
        (tmp_path / "config.json").write_text(bom + json.dumps({
            "agent": {"jenkinsUrl": "https://ok.com", "agentName": "a", "secret": "s"},
        }), encoding="utf-8")
        cfg, errors = resolve_config(tmp_path)
        # BOM ����, �� JSON ���������\n        assert cfg is not None

    def test_deeply_nested(self, tmp_path):
        data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        (tmp_path / "config.json").write_text(json.dumps(data))
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com", "agent_name": "a", "secret": "s"
        })
        # BOM ����, �� JSON ���������\n        assert cfg is not None

    def test_huge_json(self, tmp_path):
        # 1MB JSON - должно обработать без OOM
        big = {"padding": "x" * 1_000_000, "agent": {"jenkinsUrl": "https://ok.com", "agentName": "a", "secret": "s"}}
        (tmp_path / "config.json").write_text(json.dumps(big))
        cfg, errors = resolve_config(tmp_path)
        # BOM ����, �� JSON ���������\n        assert cfg is not None

    def test_json_array_instead_of_object(self, tmp_path):
        (tmp_path / "config.json").write_text('[1, 2, 3]')
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com", "agent_name": "a", "secret": "s"
        })
        # Массив вместо объекта - fallback на CLI
        # BOM ����, �� JSON ���������\n        assert cfg is not None


class TestEnvInjection:
    """Инъекции через переменные окружения."""

    def test_empty_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JENKINS_SECRET", "")
        monkeypatch.setenv("JENKINS_AGENT_NAME", "")
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {"jenkinsUrl": "https://ok.com", "agentName": "a", "secret": "s"},
        }))
        cfg, errors = resolve_config(tmp_path)
        assert cfg.agent.secret == "s"  # Не перезаписано пустым ENV

    def test_env_with_special_chars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JENKINS_SECRET", "secret=with$pecial&chars")
        monkeypatch.setenv("JENKINS_AGENT_NAME", "name with spaces")
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {"jenkinsUrl": "https://ok.com"},
        }))
        cfg, errors = resolve_config(tmp_path)
        assert cfg.agent.secret == "secret=with$pecial&chars"
        assert cfg.agent.agent_name == "name with spaces"


class TestMissingConfig:
    """Отсутствующий config.json."""

    def test_no_config_at_all(self, tmp_path):
        # Нет config.json - только CLI
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
        })
        # Полный набор обязательных полей пришёл через CLI, значит конфиг валиден.
        assert errors == []
        # Конфиг как объект всё равно создаётся.
        assert cfg is not None

    def test_no_config_no_cli(self, tmp_path):
        cfg, errors = resolve_config(tmp_path)
        assert len(errors) >= 3  # Минимум 3 обязательных поля
