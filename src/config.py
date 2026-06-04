"""
Конфигурация приложения.
State, чтение config.json, разрешение параметров, валидация.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Допустимые placeholder-значения, которые считаются «не заданными»
_PLACEHOLDERS = ("example.com", "example.org", "CHANGE_ME", "changeme")

DEFAULT_IGNORED_ENV_VARS = (
    {
        "name": "JENKINS_SECRET",
        "reason": "Секрет хранится в ENV launcher и не должен попадать в java-процесс.",
    },
    {
        "name": "JENKINS_AGENT_NAME",
        "reason": "Имя агента может переопределяться launcher и не должно утекать в дочерний процесс через общий ENV.",
    },
    {
        "name": "JENKINS_TUNNEL",
        "reason": "Сетевые параметры launcher не должны автоматически наследоваться java-процессом.",
    },
    {
        "name": "JENKINS_WEB_SOCKET",
        "reason": "Флаг режима подключения должен передаваться только явно собранной командой launcher.",
    },
    {
        "name": "JENKINS_DIRECT_CONNECTION",
        "reason": "Параметры прямого подключения должны контролироваться launcher, а не общим ENV.",
    },
    {
        "name": "JENKINS_INSTANCE_IDENTITY",
        "reason": "Идентификаторы подключения могут быть чувствительными и не должны безусловно наследоваться java-процессом.",
    },
    {
        "name": "JENKINS_PROTOCOLS",
        "reason": "Список протоколов должен пробрасываться только через явные аргументы launcher.",
    },
    {
        "name": "JENKINS_JAVA_OPTS",
        "reason": "JVM-параметры launcher не должны утекать в дочерний процесс через общий ENV.",
    },
    {
        "name": "JENKINS_TEMP_DIR",
        "reason": "Временный каталог должен передаваться только явно собранными JVM-параметрами launcher.",
    },
    {
        "name": "JENKINS_FALLBACK_JAR_PATH",
        "reason": "Резервный URL управляется конфигом launcher и не должен оставаться в ENV дочернего процесса.",
    },
)


@dataclass
class AgentConfig:
    """Конфигурация подключения."""
    jenkins_url: str = ""
    agent_name: str = ""
    secret: str = ""
    verify_ssl: bool | None = None
    tunnel: str = ""
    websocket: bool = False
    direct: str = ""
    instance_identity: str = ""
    protocols: str = ""
    java_opts: str = ""
    java_home: str = ""
    temp_dir: str = ""
    fallback_jar_url: str = ""
    workdir: str = ""
    agent_jar_path: str = ""
    log_path: str = ""


@dataclass
class BehaviorConfig:
    """Параметры поведения."""
    max_restarts: int = -1
    restart_delay: int = 5
    auto_update: bool = True
    jenkins_timeout: int = 10


@dataclass
class LoggingConfig:
    """Настройки логирования."""
    dir: str = "logs"
    rotation: str = "daily"        # daily | weekly | never | size
    max_days: int = 14
    max_size_mb: int = 50

    def validate(self) -> list[str]:
        """Проверить допустимые значения."""
        errs: list[str] = []
        valid_rotations = ("daily", "weekly", "never", "size")
        if self.rotation not in valid_rotations:
            errs.append(f"Недопустимый rotation='{self.rotation}' (ожидается: {', '.join(valid_rotations)})")
        if self.max_days < 0:
            errs.append("maxDays не может быть отрицательным")
        if self.max_size_mb < 0:
            errs.append("maxSizeMB не может быть отрицательным")
        return errs


@dataclass
class DownloadConfig:
    """Настройки скачивания."""
    timeout: int = 120
    max_retries: int = 3
    retry_delay: int = 5
    chunk_size: int = 8192
    fallback_verify_ssl: bool = True

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.timeout <= 0:
            errs.append("timeout должен быть > 0")
        if self.max_retries < 0:
            errs.append("maxRetries не может быть отрицательным")
        if self.retry_delay <= 0:
            errs.append("retryDelay должен быть > 0")
        return errs


@dataclass
class JnlpConfig:
    """Настройки получения данных агента из JNLP."""
    enabled: bool = False
    url: str = ""
    refresh_secret: bool = False
    save_secret: bool = False


@dataclass
class UpdateConfig:
    """Настройки автообновления."""
    enabled: bool = False
    url: str = ""
    local_path: str = ""
    check_url: str = ""
    version: str = ""
    sha256: str = ""
    signature: str = ""
    publisher: str = ""
    allow_downgrade: bool = False
    allow_same_version: bool = False
    interval_hours: int = 24

    def effective_url(self) -> str:
        return self.url.strip() or self.check_url.strip()

    def source_count(self) -> int:
        count = 0
        if self.url.strip():
            count += 1
        if self.check_url.strip():
            count += 1
        if self.local_path.strip():
            count += 1
        return count

    def source_type(self) -> str:
        if self.local_path.strip():
            return "localPath"
        if self.url.strip() or self.check_url.strip():
            return "url"
        return ""

    def source_location(self) -> str:
        if self.local_path.strip():
            return self.local_path.strip()
        return self.effective_url()

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.enabled and self.source_count() == 0:
            errs.append("update.source.location, update.url/checkUrl или update.localPath должен быть задан при включённом обновлении")
        if self.source_count() > 1:
            errs.append("update.source.location, update.url/checkUrl и update.localPath нельзя задавать одновременно")
        if self.enabled and not self.version.strip():
            errs.append("update.version должен быть задан при включённом обновлении")
        if self.enabled and not self.sha256.strip():
            errs.append("update.sha256 должен быть задан при включённом обновлении")
        if self.sha256.strip() and not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256.strip()):
            errs.append("update.sha256 должен содержать 64 hex-символа")
        if self.interval_hours < 1:
            errs.append("update.intervalHours должен быть >= 1")
        return errs


@dataclass
class UIConfig:
    """Настройки интерфейса."""
    theme: str = "light"
    start_minimized: bool = True

    def validate(self) -> list[str]:
        errs: list[str] = []
        valid_themes = ("light", "dark")
        if self.theme not in valid_themes:
            errs.append(f"Недопустимая тема '{self.theme}' (ожидается: {', '.join(valid_themes)})")
        return errs


@dataclass
class IgnoredEnvVar:
    """Переменная окружения, которую launcher скроет от java-процесса."""
    name: str
    reason: str = ""


@dataclass
class EnvironmentConfig:
    """Настройки фильтрации окружения для дочернего java-процесса."""
    ignored_vars: list[IgnoredEnvVar] = field(default_factory=list)

    def validate(self) -> list[str]:
        errs: list[str] = []
        seen: set[str] = set()

        for idx, item in enumerate(self.ignored_vars, start=1):
            name = item.name.strip()
            reason = item.reason.strip()

            if not name:
                errs.append(f"environment.ignoredVars[{idx}] должен содержать name")
                continue

            item.name = name
            item.reason = reason

            if name in seen:
                errs.append(f"environment.ignoredVars содержит дубликат: {name}")
                continue

            seen.add(name)

        return errs


@dataclass
class AppConfig:
    """Полная конфигурация приложения."""
    agent: AgentConfig = field(default_factory=AgentConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    jnlp: JnlpConfig = field(default_factory=JnlpConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    config_path: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Полная валидация конфигурации."""
        errs: list[str] = []

        # Нормализация типов - защитить от wrong types
        url = str(self.agent.jenkins_url) if self.agent.jenkins_url else ""
        name = str(self.agent.agent_name) if self.agent.agent_name else ""
        secret = str(self.agent.secret) if self.agent.secret else ""

        self.agent.jenkins_url = url
        self.agent.agent_name = name
        self.agent.secret = secret

        # Проверка обязательных полей агента
        if not url:
            errs.append("JenkinsUrl не задан - укажите URL Jenkins-сервера")
        elif any(p in url for p in _PLACEHOLDERS):
            errs.append("JenkinsUrl не задан - в config.json пример (example.com)")

        if not name:
            errs.append("AgentName не задан - укажите имя агента")

        if not secret and not self.jnlp.enabled:
            errs.append("Secret не задан - укажите секрет из Jenkins UI")
        elif secret and any(p in secret for p in _PLACEHOLDERS) and not self.jnlp.enabled:
            errs.append("Secret не задан - в config.json пример (CHANGE_ME)")

        # Проверка настроек логов
        errs.extend(self.logging.validate())
        errs.extend(self.update.validate())
        errs.extend(self.ui.validate())
        errs.extend(self.environment.validate())

        return errs

    def effective_agent_verify_ssl(self) -> bool:
        """
        Итоговая политика TLS-проверки для Jenkins URL.

        Если флаг явно задан - использовать его.
        Иначе для HTTPS включать проверку, для незащищённых адресов выключать.
        """
        if self.agent.verify_ssl is not None:
            return self.agent.verify_ssl

        scheme = urlparse(self.agent.jenkins_url).scheme.lower()
        return scheme == "https"


def get_project_dir() -> Path:
    """Корневая директорория проекта."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _defaults(project_dir: Path) -> AppConfig:
    """Значения по умолчанию."""
    home = Path.home()
    cfg = AppConfig()
    cfg.agent.workdir = str(home / "jenkins-agent")
    cfg.agent.agent_jar_path = str(project_dir / "agent.jar")
    cfg.environment.ignored_vars = [
        IgnoredEnvVar(name=item["name"], reason=item["reason"])
        for item in DEFAULT_IGNORED_ENV_VARS
    ]
    return cfg


def _config_json_candidates(project_dir: Path) -> list[Path]:
    """Кандидаты для поиска runtime-конфига в порядке приоритета."""
    return [
        project_dir / "config" / "config.json",
        project_dir / "config.json",
    ]


def _config_json_path(project_dir: Path) -> Path:
    """Путь к основному config.json."""
    for candidate in _config_json_candidates(project_dir):
        if candidate.exists():
            return candidate
    return _config_json_candidates(project_dir)[0]


def _config_template_candidates(project_dir: Path) -> list[Path]:
    """Кандидаты для шаблона runtime-конфига."""
    return [
        project_dir / "config" / "config.template.json",
        project_dir / "config" / "config.json.example",
        project_dir / "config" / "config.json.exmple",
    ]


def _bootstrap_runtime_config(project_dir: Path) -> Path | None:
    """Создать локальный runtime-конфиг из шаблона, если реальный конфиг отсутствует."""
    for candidate in _config_json_candidates(project_dir):
        if candidate.exists():
            return None

    template = next((item for item in _config_template_candidates(project_dir) if item.exists()), None)
    if template is None:
        return None

    target = project_dir / "config" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return target


def _read_json_file(path: Path) -> tuple[Any | None, list[str]]:
    """Прочитать JSON с поддержкой UTF-8 BOM и диагностикой."""
    diagnostics: list[str] = []
    raw_bytes = path.read_bytes()
    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    text = raw_bytes.decode("utf-8-sig")

    if has_bom:
        diagnostics.append(f"config.json содержит UTF-8 BOM: {path}")
        path.write_text(text, encoding="utf-8")
        diagnostics.append(f"config.json перезаписан без BOM: {path}")

    return json.loads(text), diagnostics


def _resolve_path(value: str, base_dir: Path) -> str:
    """Разрешить путь из конфига: абсолютный сохранить, относительный привязать к base_dir."""
    raw = str(value).strip()
    if not raw:
        return ""

    expanded = Path(os.path.expandvars(raw)).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    return str((base_dir / expanded).resolve(strict=False))


def _resolve_log_path(project_dir: Path, logging_dir: str, log_file_name: str) -> str:
    """
    Разрешить путь к логу.

    Простое имя файла складываем в logging.dir, относительный путь с каталогами
    оставляем относительным к project_dir для обратной совместимости.
    """
    raw_name = str(log_file_name).strip()
    if not raw_name:
        return ""

    expanded = Path(os.path.expandvars(raw_name)).expanduser()
    if expanded.is_absolute():
        return str(expanded)

    if expanded.parent == Path("."):
        return str((project_dir / logging_dir / expanded.name).resolve(strict=False))

    return str((project_dir / expanded).resolve(strict=False))


def save_ui_theme(project_dir: Path, theme: str):
    """Сохранить тему интерфейса в config.json."""
    if theme not in ("light", "dark"):
        raise ValueError(f"Unsupported theme: {theme}")

    json_path = _config_json_path(project_dir)
    raw: dict[str, Any] = {}

    if json_path.exists():
        loaded, _ = _read_json_file(json_path)
        if isinstance(loaded, dict):
            raw = loaded

    ui = raw.get("ui")
    if not isinstance(ui, dict):
        ui = {}
    ui["theme"] = theme
    raw["ui"] = ui

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_config(
    project_dir: Path | None = None,
    cli_args: dict[str, Any] | None = None,
) -> tuple[AppConfig, list[str]]:
    """
    Разрешить конфигурацию: defaults → config.json → CLI → ENV.

    Возвращает (AppConfig, список_ошибок_валидации).
    """
    if project_dir is None:
        project_dir = get_project_dir()

    cli_args = cli_args or {}
    cfg = _defaults(project_dir)

    bootstrapped_path = _bootstrap_runtime_config(project_dir)
    if bootstrapped_path is not None:
        cfg.diagnostics.append(f"Создан локальный runtime-конфиг из шаблона: {bootstrapped_path}")

    # 1. config.json (ищем сначала в config/, потом в корне)
    json_path = _config_json_path(project_dir)
    cfg.diagnostics.extend(
        [f"Поиск config.json: {candidate}" for candidate in _config_json_candidates(project_dir)]
    )
    cfg.diagnostics.append(f"Выбранный путь config.json: {json_path}")

    if json_path.exists():
        try:
            raw, diagnostics = _read_json_file(json_path)
            cfg.diagnostics.extend(diagnostics)
            cfg.config_path = str(json_path)

            if not isinstance(raw, dict):
                cfg.diagnostics.append(
                    f"config.json должен содержать JSON-объект, получено: {type(raw).__name__}"
                )
                raw = {}

            a = raw.get("agent", {})
            if not isinstance(a, dict):
                a = {}
            if not cfg.agent.jenkins_url:
                cfg.agent.jenkins_url = str(a.get("jenkinsUrl") or "")
            if not cfg.agent.agent_name:
                cfg.agent.agent_name = str(a.get("agentName") or "")
            if not cfg.agent.secret:
                cfg.agent.secret = str(a.get("secret") or "")
            if a.get("verifySsl") is not None:
                cfg.agent.verify_ssl = bool(a["verifySsl"])
            if not cfg.agent.tunnel:
                cfg.agent.tunnel = a.get("tunnel", "")
            if a.get("javaHome"):
                cfg.agent.java_home = _resolve_path(str(a["javaHome"]), project_dir)
            if a.get("tempDir"):
                cfg.agent.temp_dir = _resolve_path(str(a["tempDir"]), project_dir)
            if a.get("workDir"):
                cfg.agent.workdir = os.path.expandvars(a["workDir"])
            if a.get("agentJarName"):
                cfg.agent.agent_jar_path = _resolve_path(str(a["agentJarName"]), project_dir)

            bh = raw.get("behavior", {})
            if bh.get("maxRestarts") is not None:
                cfg.behavior.max_restarts = int(bh["maxRestarts"])
            if bh.get("restartDelaySeconds"):
                cfg.behavior.restart_delay = int(bh["restartDelaySeconds"])
            if bh.get("autoUpdateJar") is not None:
                cfg.behavior.auto_update = bool(bh["autoUpdateJar"])

            fb = raw.get("fallback", {})
            if fb.get("agentJarUrl"):
                cfg.agent.fallback_jar_url = fb["agentJarUrl"]
            if fb.get("verifySsl") is not None:
                cfg.download.fallback_verify_ssl = bool(fb["verifySsl"])

            lg = raw.get("logging", {})
            if lg.get("dir"):
                cfg.logging.dir = lg["dir"]
            if lg.get("rotation"):
                cfg.logging.rotation = lg["rotation"]
            if lg.get("maxDays") is not None:
                cfg.logging.max_days = int(lg["maxDays"])
            if lg.get("maxSizeMB") is not None:
                cfg.logging.max_size_mb = int(lg["maxSizeMB"])
            if a.get("logFileName"):
                cfg.agent.log_path = _resolve_log_path(
                    project_dir=project_dir,
                    logging_dir=cfg.logging.dir,
                    log_file_name=str(a["logFileName"]),
                )

            dl = raw.get("download", {})
            if dl.get("timeout") is not None:
                cfg.download.timeout = int(dl["timeout"])
            if dl.get("maxRetries") is not None:
                cfg.download.max_retries = int(dl["maxRetries"])
            if dl.get("retryDelaySeconds") is not None:
                cfg.download.retry_delay = int(dl["retryDelaySeconds"])
            if dl.get("chunkSize") is not None:
                cfg.download.chunk_size = int(dl["chunkSize"])

            jnlp = raw.get("jnlp", {})
            if isinstance(jnlp, dict):
                if jnlp.get("enabled") is not None:
                    cfg.jnlp.enabled = bool(jnlp["enabled"])
                if jnlp.get("url"):
                    cfg.jnlp.url = str(jnlp["url"]).strip()
                if jnlp.get("refreshSecret") is not None:
                    cfg.jnlp.refresh_secret = bool(jnlp["refreshSecret"])
                if jnlp.get("saveSecret") is not None:
                    cfg.jnlp.save_secret = bool(jnlp["saveSecret"])

            up = raw.get("update", {})
            if up.get("enabled") is not None:
                cfg.update.enabled = bool(up["enabled"])
            source = up.get("source", {})
            if isinstance(source, dict):
                source_type = str(source.get("type") or "").strip()
                source_location = str(source.get("location") or "").strip()
                if source_location and source_type == "localPath":
                    cfg.update.local_path = _resolve_path(source_location, project_dir)
                elif source_location and source_type == "url":
                    cfg.update.url = source_location
            if up.get("url"):
                cfg.update.url = str(up["url"]).strip()
            if up.get("checkUrl"):
                cfg.update.check_url = str(up["checkUrl"]).strip()
            if up.get("localPath"):
                cfg.update.local_path = _resolve_path(str(up["localPath"]), project_dir)
            if up.get("version"):
                cfg.update.version = str(up["version"]).strip()
            if up.get("sha256"):
                cfg.update.sha256 = str(up["sha256"]).strip()
            if up.get("signature"):
                cfg.update.signature = str(up["signature"]).strip()
            if up.get("publisher"):
                cfg.update.publisher = str(up["publisher"]).strip()
            if up.get("allowDowngrade") is not None:
                cfg.update.allow_downgrade = bool(up["allowDowngrade"])
            if up.get("allowSameVersion") is not None:
                cfg.update.allow_same_version = bool(up["allowSameVersion"])
            if up.get("intervalHours") is not None:
                cfg.update.interval_hours = int(up["intervalHours"])

            ui = raw.get("ui", {})
            if isinstance(ui, dict):
                if ui.get("theme") is not None:
                    cfg.ui.theme = str(ui["theme"]).lower()
                if ui.get("startMinimized") is not None:
                    cfg.ui.start_minimized = bool(ui["startMinimized"])

            env_cfg = raw.get("environment", {})
            if isinstance(env_cfg, dict) and "ignoredVars" in env_cfg:
                ignored_vars = env_cfg.get("ignoredVars")
                parsed_items: list[IgnoredEnvVar] = []
                if isinstance(ignored_vars, list):
                    for item in ignored_vars:
                        if isinstance(item, str):
                            parsed_items.append(IgnoredEnvVar(name=item))
                        elif isinstance(item, dict):
                            parsed_items.append(
                                IgnoredEnvVar(
                                    name=str(item.get("name") or ""),
                                    reason=str(item.get("reason") or ""),
                                )
                            )
                cfg.environment.ignored_vars = parsed_items

        except Exception as exc:
            cfg.diagnostics.append(f"Ошибка чтения config.json ({json_path}): {exc}")
    else:
        cfg.diagnostics.append("config.json не найден")

    # 2. CLI overrides
    for key, attr in [
        ("jenkins_url", "jenkins_url"),
        ("agent_name", "agent_name"),
        ("secret", "secret"),
        ("tunnel", "tunnel"),
        ("direct", "direct"),
        ("instance_identity", "instance_identity"),
        ("protocols", "protocols"),
        ("java_opts", "java_opts"),
        ("java_home", "java_home"),
        ("temp_dir", "temp_dir"),
        ("fallback_jar_url", "fallback_jar_url"),
        ("work_dir", "workdir"),
        ("agent_jar_path", "agent_jar_path"),
        ("log_path", "log_path"),
    ]:
        val = cli_args.get(key)
        if val:
            setattr(cfg.agent, attr, val)

    if not cfg.agent.log_path:
        cfg.agent.log_path = ""

    if cli_args.get("websocket"):
        cfg.agent.websocket = True

    if cli_args.get("jnlp"):
        cfg.jnlp.enabled = True
    if cli_args.get("jnlp_url"):
        cfg.jnlp.url = str(cli_args["jnlp_url"]).strip()
        cfg.jnlp.enabled = True
    if cli_args.get("jnlp_refresh_secret"):
        cfg.jnlp.refresh_secret = True
        cfg.jnlp.enabled = True
    if cli_args.get("jnlp_save_secret"):
        cfg.jnlp.save_secret = True
        cfg.jnlp.enabled = True

    if cli_args.get("no_auto_update"):
        cfg.behavior.auto_update = False
    elif cli_args.get("auto_update") is not None:
        cfg.behavior.auto_update = bool(cli_args["auto_update"])

    if cli_args.get("max_restarts") is not None:
        cfg.behavior.max_restarts = int(cli_args["max_restarts"])
    if cli_args.get("restart_delay") is not None:
        cfg.behavior.restart_delay = int(cli_args["restart_delay"])
    if cli_args.get("jenkins_timeout") is not None:
        cfg.behavior.jenkins_timeout = int(cli_args["jenkins_timeout"])

    # 3. ENV (наивысший приоритет)
    env_map = {
        "JENKINS_SECRET": ("agent", "secret"),
        "JENKINS_AGENT_NAME": ("agent", "agent_name"),
        "JENKINS_TUNNEL": ("agent", "tunnel"),
        "JENKINS_DIRECT_CONNECTION": ("agent", "direct"),
        "JENKINS_INSTANCE_IDENTITY": ("agent", "instance_identity"),
        "JENKINS_PROTOCOLS": ("agent", "protocols"),
        "JENKINS_JAVA_OPTS": ("agent", "java_opts"),
        "JENKINS_TEMP_DIR": ("agent", "temp_dir"),
        "JENKINS_FALLBACK_JAR_PATH": ("agent", "fallback_jar_url"),
    }
    for var, (section, attr) in env_map.items():
        val = os.environ.get(var)
        if val:
            setattr(getattr(cfg, section), attr, val)

    ws = os.environ.get("JENKINS_WEB_SOCKET", "").lower()
    if ws in ("true", "1", "yes", "on"):
        cfg.agent.websocket = True

    if cfg.agent.temp_dir:
        cfg.agent.temp_dir = _resolve_path(cfg.agent.temp_dir, project_dir)

    # Валидация
    errors = cfg.validate()
    return cfg, errors
