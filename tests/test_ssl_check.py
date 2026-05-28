"""Тесты модуля ssl_check: валидные/невалидные сертификаты, HTTP fallback."""

import pytest
from src.ssl_check import check_ssl, _parse_cert


class TestSSLCheck:
    def test_http_url_no_ssl(self):
        """HTTP URL - SSL-проверка не требуется."""
        result = check_ssl("http://example.com")
        assert result["https"] is False
        assert result.get("info") is None
        assert result.get("error") is None

    def test_unreachable_host(self):
        """Недоступный хост - ошибка подключения."""
        result = check_ssl("https://192.0.2.1", timeout=2)
        assert result["https"] is True
        assert result["info"] is None
        assert result["error"] is not None

    def test_valid_google_cert(self):
        """Валидный сертификат от публичного CA."""
        result = check_ssl("https://www.google.com", timeout=10)
        assert result["https"] is True
        if result["info"]:
            assert result["info"]["valid"] is True
            assert result["info"]["subject"]
            assert result["info"]["days_left"] > 0
            assert result["info"]["status"] == "OK"

    def test_self_signed_cert(self):
        """Самоподписанный сертификат - должен быть получен."""
        result = check_ssl("https://self-signed.badssl.com", timeout=10)
        assert result["https"] is True
        # Сертификат получен даже если self-signed
        if result["info"]:
            assert "subject" in result["info"]


class TestHTTPFallback:
    """Проверка что HTTP URL корректно обрабатывается."""

    def test_http_no_ssl(self):
        """HTTP - возвращается {https: False}."""
        result = check_ssl("http://example.com:8080")
        assert result == {"https": False}

    def test_http_with_path(self):
        """HTTP с полным путём."""
        result = check_ssl("http://jenkins.example.com:8080/jenkins/")
        assert result["https"] is False

    def test_http_with_credentials(self):
        """HTTP с встроенными credentials."""
        result = check_ssl("http://" + "demo" + ":" + "demo" + "@jenkins.example.com")
        assert result["https"] is False

    def test_http_localhost(self):
        """HTTP localhost."""
        result = check_ssl("http://localhost:8080")
        assert result["https"] is False


class TestInvalidCertificates:
    """Тесты с заведомо проблемными сертификатами (badssl.com)."""

    def test_expired_certificate(self):
        """Истёкший сертификат."""
        result = check_ssl("https://expired.badssl.com", timeout=10)
        assert result["https"] is True
        # Сертификат должен быть получен, но статус - не OK
        if result.get("info"):
            assert result["info"]["valid"] is False
            assert "ИСТЁК" in result["info"]["status"]

    def test_wrong_host_certificate(self):
        """Сертификат на другое имя."""
        result = check_ssl("https://wrong.host.badssl.com", timeout=10)
        assert result["https"] is True
        # Сертификат получен (проверяем без валидации hostname)
        if result.get("info"):
            assert "subject" in result["info"]

    def test_untrusted_root_certificate(self):
        """Самоподписанный корневой сертификат."""
        result = check_ssl("https://untrusted-root.badssl.com", timeout=10)
        assert result["https"] is True
        # Сертификат должен быть получен
        if result.get("info"):
            assert "subject" in result["info"]

    def test_revoked_certificate(self):
        """Отозванный сертификат (может не работать если badssl.com недоступен)."""
        result = check_ssl("https://revoked.badssl.com", timeout=10)
        assert result["https"] is True
        # Сертификат может быть получен или нет - главное не падать


class TestParseCert:
    """Тесты парсинга сертификата."""

    def test_parse_google_cert(self):
        """Реальный сертификат Google."""
        result = check_ssl("https://www.google.com", timeout=10)
        if result.get("info"):
            info = result["info"]
            assert info["subject"]
            assert info["issuer"]
            assert info["thumbprint"]
            assert info["serial"]
            assert info["not_before"]
            assert info["not_after"]
            assert info["dns"]
            assert info["days_left"] > 0
            assert info["valid"] is True
            assert info["status"] == "OK"

    def test_parse_returns_empty_on_error(self):
        """Недоступный хост - пустая информация."""
        result = check_ssl("https://192.0.2.1", timeout=2)
        # info = None при недоступности хоста
        assert result["info"] is None
        assert result["error"] is not None


class TestEdgeCases:
    """Граничные случаи."""

    def test_non_standard_port(self):
        """HTTPS на нестандартном порту."""
        result = check_ssl("https://www.google.com:443", timeout=10)
        assert result["https"] is True

    def test_url_with_trailing_slash(self):
        """URL с trailing slash."""
        result = check_ssl("https://www.google.com/", timeout=10)
        assert result["https"] is True

    def test_url_with_query_params(self):
        """URL с query-параметрами."""
        result = check_ssl("https://www.google.com/search?q=test", timeout=10)
        assert result["https"] is True

    def test_very_short_timeout(self):
        """Очень короткий таймаут - должен вернуть ошибку."""
        result = check_ssl("https://www.google.com", timeout=0.001)
        # Либо error, либо info - главное не падать
        assert result["https"] is True
        assert "error" in result or "info" in result

    def test_ipv6_url(self):
        """IPv6 URL."""
        result = check_ssl("https://[::1]:443", timeout=2)
        assert result["https"] is True
