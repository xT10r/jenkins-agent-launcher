"""Тесты модуля downloader."""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.downloader import AgentJarDownloader


class TestDownloader:
    def test_file_already_exists(self, tmp_path):
        jar = tmp_path / "agent.jar"
        jar.write_bytes(b"existing")

        dl = AgentJarDownloader(
            jenkins_url="https://example.com",
            dest_path=str(jar),
        )
        assert dl.ensure_jar() is True

    def test_successful_download(self, tmp_path):
        jar = tmp_path / "agent.jar"

        import requests
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = [b"jar content"]

        with patch.object(requests, 'get', return_value=mock_resp):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
            )
            assert dl.ensure_jar() is True
            assert jar.exists()

    def test_https_primary_uses_ssl_verification_by_default(self, tmp_path):
        jar = tmp_path / "agent.jar"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = [b"jar content"]
        mock_resp.headers = {"content-length": "11"}

        mock_http = MagicMock()
        mock_http.get.return_value = mock_resp

        dl = AgentJarDownloader(
            jenkins_url="https://jenkins.example.com",
            dest_path=str(jar),
            http_client=mock_http,
        )
        assert dl.ensure_jar() is True
        assert mock_http.get.call_args.kwargs["verify"] is True

    def test_http_primary_can_run_without_ssl_verification(self, tmp_path):
        jar = tmp_path / "agent.jar"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = [b"jar content"]
        mock_resp.headers = {"content-length": "11"}

        mock_http = MagicMock()
        mock_http.get.return_value = mock_resp

        dl = AgentJarDownloader(
            jenkins_url="http://example.com:8080",
            dest_path=str(jar),
            jenkins_verify_ssl=False,
            http_client=mock_http,
        )
        assert dl.ensure_jar() is True
        assert mock_http.get.call_args.kwargs["verify"] is False

    def test_download_uses_configured_timeout_and_chunk_size(self, tmp_path):
        jar = tmp_path / "agent.jar"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_content.return_value = [b"jar content"]
        mock_resp.headers = {"content-length": "11"}

        mock_http = MagicMock()
        mock_http.get.return_value = mock_resp

        dl = AgentJarDownloader(
            jenkins_url="https://jenkins.example.com",
            dest_path=str(jar),
            timeout=33,
            chunk_size=4096,
            http_client=mock_http,
        )
        assert dl.ensure_jar() is True
        assert mock_http.get.call_args.kwargs["timeout"] == 33
        mock_resp.iter_content.assert_called_with(4096)

    def test_fallback_download(self, tmp_path):
        jar = tmp_path / "agent.jar"

        import requests
        mock_resp_fail = MagicMock()
        mock_resp_fail.raise_for_status.side_effect = Exception("fail")

        with patch.object(requests, 'get', return_value=mock_resp_fail):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
                fallback_url="https://fallback.com/agent.jar",
            )
            # Оба запроса падают
            assert dl.ensure_jar() is False

    def test_fallback_verify_ssl_defaults_to_true(self, tmp_path):
        jar = tmp_path / "agent.jar"

        mock_resp_fail = MagicMock()
        mock_resp_fail.raise_for_status.side_effect = Exception("fail")
        mock_resp_ok = MagicMock()
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.iter_content.return_value = [b"jar content"]
        mock_resp_ok.headers = {"content-length": "11"}

        calls = []

        def mock_get(*args, **kwargs):
            calls.append(kwargs["verify"])
            if len(calls) == 1:
                return mock_resp_fail
            return mock_resp_ok

        import requests
        with patch.object(requests, 'get', side_effect=mock_get):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
                fallback_url="https://fallback.com/agent.jar",
            )
            assert dl.ensure_jar() is True

        assert calls == [True, True]

    def test_fallback_verify_ssl_can_be_disabled(self, tmp_path):
        jar = tmp_path / "agent.jar"

        mock_resp_fail = MagicMock()
        mock_resp_fail.raise_for_status.side_effect = Exception("fail")
        mock_resp_ok = MagicMock()
        mock_resp_ok.raise_for_status = MagicMock()
        mock_resp_ok.iter_content.return_value = [b"jar content"]
        mock_resp_ok.headers = {"content-length": "11"}

        calls = []

        def mock_get(*args, **kwargs):
            calls.append(kwargs["verify"])
            if len(calls) == 1:
                return mock_resp_fail
            return mock_resp_ok

        import requests
        with patch.object(requests, 'get', side_effect=mock_get):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
                fallback_url="https://fallback.com/agent.jar",
                fallback_verify_ssl=False,
                max_retries=1,
            )
            assert dl.ensure_jar() is True

        assert calls == [True, False]

    def test_download_timeout(self, tmp_path):
        jar = tmp_path / "agent.jar"

        import requests
        mock_resp_timeout = MagicMock()
        mock_resp_timeout.raise_for_status.side_effect = requests.exceptions.Timeout("timeout")

        with patch.object(requests, 'get', side_effect=requests.exceptions.Timeout("timeout")):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
            )
            # Должно сделать 3 попытки и вернуть False
            assert dl.ensure_jar() is False

    def test_download_retry(self, tmp_path):
        jar = tmp_path / "agent.jar"
        call_count = [0]

        import requests
        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise requests.exceptions.ConnectionError("connection refused")
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content.return_value = [b"jar content"]
            return mock_resp

        with patch.object(requests, 'get', side_effect=mock_get):
            dl = AgentJarDownloader(
                jenkins_url="https://jenkins.example.com",
                dest_path=str(jar),
            )
            dl.RETRY_DELAY = 0.01  # Ускорить тест
            # Должно succeed на 3-й попытке
            assert dl.ensure_jar() is True
            assert call_count[0] == 3
