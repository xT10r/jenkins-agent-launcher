"""
Runtime metadata приложения.

Основной источник версии - config/build.json. Во время сборки PyInstaller
дополнительно вшивает src._build_info, чтобы packaged-приложение не зависело
от внешнего build.json.
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


def _read_embedded_build_info() -> dict:
    try:
        from . import _build_info
    except Exception:
        return {}

    info = getattr(_build_info, "BUILD_INFO", {})
    return info if isinstance(info, dict) else {}


def get_app_version(project_dir: Path | None = None) -> str:
    """Версия приложения для runtime-логов и GUI."""
    build_json = _build_json_path(project_dir)
    cfg = {}
    if build_json.exists():
        try:
            with open(build_json, encoding="utf-8") as f:
                loaded = json.load(f)
                cfg = loaded if isinstance(loaded, dict) else {}
        except Exception:
            cfg = {}

    if not cfg:
        cfg = _read_embedded_build_info()

    version = str(cfg.get("version") or "").strip()
    return version or DEFAULT_APP_VERSION
