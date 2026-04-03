from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Iterable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class TLSMaterial:
    cert_dir: Path
    ca_cert_path: Path
    ca_key_path: Path
    server_cert_path: Path
    server_key_path: Path


def default_tls_dir(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parent.parent
    return root / 'certs' / 'dev'


def _material_paths(cert_dir: Path) -> TLSMaterial:
    return TLSMaterial(
        cert_dir=cert_dir,
        ca_cert_path=cert_dir / 'ca_cert.pem',
        ca_key_path=cert_dir / 'ca_key.pem',
        server_cert_path=cert_dir / 'server_cert.pem',
        server_key_path=cert_dir / 'server_key.pem',
    )


def ensure_dev_tls_materials(cert_dir: Path, hostnames: Iterable[str]) -> TLSMaterial:
    cert_dir.mkdir(parents=True, exist_ok=True)
    material = _material_paths(cert_dir)
    if (
        material.ca_cert_path.exists()
        and material.ca_key_path.exists()
        and material.server_cert_path.exists()
        and material.server_key_path.exists()
    ):
        return material

    normalized_hostnames = _normalize_hostnames(hostnames)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    now = datetime.now(timezone.utc)
    ca_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'HK'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'COMP3334 IM Dev CA'),
            x509.NameAttribute(NameOID.COMMON_NAME, 'COMP3334 IM Local Dev Root CA'),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                key_encipherment=False,
                key_cert_sign=True,
                key_agreement=False,
                content_commitment=False,
                data_encipherment=False,
                encipher_only=False,
                decipher_only=False,
                crl_sign=True,
            ),
            critical=True,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    san_entries: list[x509.GeneralName] = []
    for hostname in normalized_hostnames:
        try:
            san_entries.append(x509.IPAddress(ip_address(hostname)))
        except ValueError:
            san_entries.append(x509.DNSName(hostname))

    server_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'HK'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'COMP3334 IM Dev Server'),
            x509.NameAttribute(NameOID.COMMON_NAME, normalized_hostnames[0]),
        ]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                key_agreement=True,
                content_commitment=False,
                data_encipherment=False,
                encipher_only=False,
                decipher_only=False,
                crl_sign=False,
            ),
            critical=True,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    material.ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    material.ca_key_path.write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    material.server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    material.server_key_path.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return material


def _normalize_hostnames(hostnames: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for item in ('localhost', '127.0.0.1', *hostnames):
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen
