import json
from unittest.mock import MagicMock

from src.config import resolve_config
from src.jnlp import JnlpSecretResolver, default_jnlp_url, parse_secret_from_jnlp


TEST_SECRET = "a" * 64


def test_default_jnlp_url_encodes_agent_name():
    assert default_jnlp_url("https://jenkins.example.com/", "win agent 1") == (
        "https://jenkins.example.com/computer/win%20agent%201/jenkins-agent.jnlp"
    )


def test_parse_secret_from_modern_jnlp_argument():
    text = f"""
    <jnlp>
      <application-desc>
        <argument>{TEST_SECRET}</argument>
        <argument>windows-agent-1</argument>
      </application-desc>
    </jnlp>
    """

    assert parse_secret_from_jnlp(text) == TEST_SECRET


def test_parse_secret_after_secret_flag():
    text = f"""
    <jnlp>
      <application-desc>
        <argument>-secret</argument>
        <argument>{TEST_SECRET}</argument>
      </application-desc>
    </jnlp>
    """

    assert parse_secret_from_jnlp(text) == TEST_SECRET


def test_jnlp_resolver_fetches_missing_secret_and_saves_config(tmp_path):
    cfg_path = tmp_path / "config" / "config.json"
    cfg_path.parent.mkdir()
    cfg_path.write_text(json.dumps({
        "agent": {
            "jenkinsUrl": "https://jenkins.demo.test",
            "agentName": "windows-agent-1",
            "secret": "CHANGE_ME_SECRET",  # pragma: allowlist secret
        },
        "jnlp": {
            "enabled": True,
            "saveSecret": True,
        },
    }), encoding="utf-8")

    cfg, errors = resolve_config(tmp_path)
    assert not errors

    response = MagicMock()
    response.text = f"<jnlp><application-desc><argument>{TEST_SECRET}</argument></application-desc></jnlp>"
    response.raise_for_status = MagicMock()
    http = MagicMock()
    http.get.return_value = response

    resolver = JnlpSecretResolver(cfg, http_client=http)

    assert resolver.ensure_secret() is True
    assert cfg.agent.secret == TEST_SECRET

    saved = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert saved["agent"]["secret"] == TEST_SECRET
    assert http.get.call_args.args[0] == (
        "https://jenkins.demo.test/computer/windows-agent-1/jenkins-agent.jnlp"
    )


def test_config_reads_jnlp_options(tmp_path):
    cfg_path = tmp_path / "config" / "config.json"
    cfg_path.parent.mkdir()
    cfg_path.write_text(json.dumps({
        "agent": {
            "jenkinsUrl": "https://jenkins.demo.test",
            "agentName": "windows-agent-1",
            "secret": "CHANGE_ME_SECRET",  # pragma: allowlist secret
        },
        "jnlp": {
            "enabled": True,
            "url": "https://jenkins.demo.test/custom.jnlp",
            "refreshSecret": True,
            "saveSecret": True,
        },
    }), encoding="utf-8")

    cfg, errors = resolve_config(tmp_path)

    assert not errors
    assert cfg.jnlp.enabled is True
    assert cfg.jnlp.url == "https://jenkins.demo.test/custom.jnlp"
    assert cfg.jnlp.refresh_secret is True
    assert cfg.jnlp.save_secret is True
