"""
Runtime metadata приложения.

Основной источник версии — config/build.json, чтобы runtime и сборка
использовали одно и то же значение.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_APP_VERSION = "0.0.0.0"


def get_project_dir() -> Path:
    """Корневая директория проекта или каталога frozen-приложения."""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _build_json_path(project_dir: Path | None = None) -> Path:
    base_dir = project_dir or get_project_dir()
    return base_dir / "config" / "build.json"


def get_app_version(project_dir: Path | None = None) -> str:
    """Версия приложения для runtime-логов и GUI."""
    build_json = _build_json_path(project_dir)
    if not build_json.exists():
        return DEFAULT_APP_VERSION

    try:
        with open(build_json, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return DEFAULT_APP_VERSION

    version = str(cfg.get("version") or "").strip()
    return version or DEFAULT_APP_VERSION
