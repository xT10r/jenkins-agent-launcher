"""
SSL-диагностика: подключение к HTTPS-порту, извлечение информации о сертификате.
"""

from __future__ import annotations

import datetime
import socket
import ssl
from urllib.parse import urlparse

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes


def check_ssl(url: str, timeout: int = 10) -> dict:
    """
    Подключиться к HTTPS-порту и получить информацию о сертификате.

    Returns:
        {"https": bool, "info": dict|None, "error": str|None}
    """
    u = urlparse(url)
    if u.scheme != "https":
        return {"https": False}

    host = u.hostname
    port = u.port or 443
    result: dict = {"https": True, "info": None, "error": None}

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, port), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                der = ss.getpeercert(binary_form=True)
                if der:
                    result["info"] = _parse_cert(der)
    except ssl.SSLError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)

    return result


def _parse_cert(der: bytes) -> dict:
    """Извлечь читабельную информацию из DER-сертификата."""
    try:
        cert = x509.load_der_x509_certificate(der)
        cn_a = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cn = cn_a[0].value if cn_a else str(cert.subject)
        is_a = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
        iss = is_a[0].value if is_a else str(cert.issuer)

        san = []
        try:
            ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            san = ext.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            pass

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        nb = cert.not_valid_before_utc
        na = cert.not_valid_after_utc
        days = (na - now).days

        if now < nb:
            status = "СЕРТИФИКАТ ЕЩЁ НЕ ДЕЙСТВИТЕЛЕН"
        elif now > na:
            status = "СЕРТИФИКАТ ИСТЁК"
        elif days < 30:
            status = f"ИСТЕКАЕТ ЧЕРЕЗ {days} ДНЕЙ"
        else:
            status = "OK"

        return {
            "subject": cn,
            "issuer": iss,
            "thumbprint": cert.fingerprint(hashes.SHA1()).hex().upper(),
            "serial": hex(cert.serial_number),
            "not_before": nb.strftime("%Y-%m-%d %H:%M:%S"),
            "not_after": na.strftime("%Y-%m-%d %H:%M:%S"),
            "dns": ", ".join(san) if san else cn,
            "days_left": days,
            "status": status,
            "valid": status == "OK",
        }
    except ImportError:
        return {"subject": "?", "status": "cryptography не установлен", "valid": False}
    except Exception as e:
        return {"subject": "?", "status": str(e), "valid": False}
