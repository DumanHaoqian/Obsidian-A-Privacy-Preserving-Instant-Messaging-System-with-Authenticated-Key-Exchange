from __future__ import annotations

import os
import ssl
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEV_CA_CERT = ROOT / 'certs' / 'dev' / 'ca_cert.pem'
TLS_CA_CERT_ENV = 'IM_TLS_CA_CERT'


def default_ca_cert_path() -> Optional[Path]:
    env_value = os.getenv(TLS_CA_CERT_ENV)
    if env_value:
        path = Path(env_value).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f'TLS CA certificate not found: {path}')
        return path
    if DEFAULT_DEV_CA_CERT.exists():
        return DEFAULT_DEV_CA_CERT.resolve()
    return None


def resolve_ca_cert_path(ca_cert_path: Optional[str]) -> Optional[Path]:
    if ca_cert_path:
        path = Path(ca_cert_path).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f'TLS CA certificate not found: {path}')
        return path
    return default_ca_cert_path()


def normalize_base_url(base_url: str, *, allow_insecure_http: bool = False) -> str:
    normalized = base_url.rstrip('/')
    parsed = urlparse(normalized)
    if parsed.scheme not in {'http', 'https'}:
        raise RuntimeError('server URL must start with http:// or https://')
    if not parsed.netloc:
        raise RuntimeError('server URL must include a host and port')
    if parsed.scheme != 'https' and not allow_insecure_http:
        raise RuntimeError(
            'TLS is required by Project.pdf; use an https:// server URL or pass --allow-insecure-http for legacy debugging only'
        )
    return normalized


def create_ssl_context(base_url: str, ca_cert_path: Optional[str]) -> Optional[ssl.SSLContext]:
    parsed = urlparse(base_url)
    if parsed.scheme != 'https':
        return None

    resolved_ca_path = resolve_ca_cert_path(ca_cert_path)
    context = ssl.create_default_context(cafile=str(resolved_ca_path) if resolved_ca_path else None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
