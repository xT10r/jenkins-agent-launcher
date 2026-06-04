"""
Получение Jenkins agent secret из JNLP-файла.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from .config import AppConfig, _PLACEHOLDERS


_SECRET_RE = re.compile(r"^[A-Fa-f0-9]{32,128}$")


def is_missing_or_placeholder_secret(secret: str) -> bool:
    value = str(secret or "")
    return not value or any(item in value for item in _PLACEHOLDERS)


def default_jnlp_url(jenkins_url: str, agent_name: str) -> str:
    base = str(jenkins_url or "").rstrip("/")
    name = quote(str(agent_name or "").strip(), safe="")
    return f"{base}/computer/{name}/jenkins-agent.jnlp"


def parse_secret_from_jnlp(text: str) -> str:
    root = ET.fromstring(text)
    args = [
        (node.text or "").strip()
        for node in root.findall(".//argument")
        if (node.text or "").strip()
    ]

    for idx, arg in enumerate(args[:-1]):
        if arg == "-secret" and args[idx + 1]:
            return args[idx + 1]

    for arg in args:
        if _SECRET_RE.fullmatch(arg):
            return arg

    raise ValueError("JNLP не содержит Jenkins secret")


class JnlpSecretResolver:
    def __init__(
        self,
        config: AppConfig,
        log_fn: Callable[..., None] | None = None,
        http_client: Any = None,
    ):
        self.config = config
        self.log = log_fn or (lambda *a, **kw: None)
        self._http = http_client or requests

    def ensure_secret(self) -> bool:
        if not self.config.jnlp.enabled:
            return bool(self.config.agent.secret)

        should_fetch = (
            self.config.jnlp.refresh_secret
            or is_missing_or_placeholder_secret(self.config.agent.secret)
        )
        if not should_fetch:
            return True

        url = self.config.jnlp.url or default_jnlp_url(
            self.config.agent.jenkins_url,
            self.config.agent.agent_name,
        )
        try:
            self.log("Получение Jenkins secret из JNLP...", comp="JNLP")
            response = self._http.get(
                url,
                timeout=self.config.download.timeout,
                verify=self.config.effective_agent_verify_ssl(),
            )
            response.raise_for_status()
            resolved_value = parse_secret_from_jnlp(response.text)
            setattr(self.config.agent, "secret", resolved_value)
            self.log("Jenkins secret получен из JNLP", comp="JNLP")
            if self.config.jnlp.save_secret:
                self._save_secret(resolved_value)
            return True
        except Exception as exc:
            self.log(f"Не удалось получить Jenkins secret из JNLP: {exc}", level="ERROR", comp="JNLP")
            return False

    def _save_secret(self, secret: str) -> None:
        config_path = Path(self.config.config_path) if self.config.config_path else None
        if config_path is None:
            self.log("Секрет не записан: путь config.json неизвестен", level="WARN", comp="JNLP")
            return

        raw: dict[str, Any] = {}
        if config_path.exists():
            loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                raw = loaded

        agent = raw.get("agent")
        if not isinstance(agent, dict):
            agent = {}
        agent.update({"secret": secret})
        raw["agent"] = agent

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.log("Jenkins secret записан в config.json", comp="JNLP")
