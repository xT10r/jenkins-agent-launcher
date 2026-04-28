"""Тесты runtime-версии приложения."""

import json

from src.version import DEFAULT_APP_VERSION, get_app_version


class TestAppVersion:
    def test_reads_version_from_build_json(self, tmp_path):
        build_json = tmp_path / "config" / "build.json"
        build_json.parent.mkdir(parents=True, exist_ok=True)
        build_json.write_text(json.dumps({"version": "3.2.1.4"}), encoding="utf-8")

        assert get_app_version(tmp_path) == "3.2.1.4"

    def test_returns_default_when_build_json_missing(self, tmp_path):
        assert get_app_version(tmp_path) == DEFAULT_APP_VERSION

    def test_returns_default_when_build_json_is_broken(self, tmp_path):
        build_json = tmp_path / "config" / "build.json"
        build_json.parent.mkdir(parents=True, exist_ok=True)
        build_json.write_text("{broken", encoding="utf-8")

        assert get_app_version(tmp_path) == DEFAULT_APP_VERSION
