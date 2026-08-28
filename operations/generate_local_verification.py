"""Generate short-lived local TLS/OIDC material without printing secret values."""
from __future__ import annotations

import argparse
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def private_key(path: Path) -> rsa.RSAPrivateKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    ca_key = private_key(directory / "ca.key")
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Milestone 15 Local Verification CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    (directory / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    tls_key = private_key(directory / "tls.key")
    tls_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    leaf = (x509.CertificateBuilder().subject_name(tls_name).issuer_name(ca_name)
            .public_key(tls_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.DNSName("host.docker.internal"), x509.DNSName("m15.local")
            ]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (directory / "tls.crt").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    private_key(directory / "oidc-signing.key")
    names = ("postgres_password", "session_secret", "oidc_client_secret",
             "metrics_bearer_token", "grafana_admin_password", "openai_api_key")
    values = {name: secrets.token_hex(32) for name in names}
    for name, value in values.items():
        (directory / name).write_text(value, encoding="utf-8")
    (directory / "database_url").write_text(
        "postgresql+asyncpg://rag_assistant_dev:"
        f"{values['postgres_password']}@postgres:5432/rag_assistant_dev",
        encoding="utf-8",
    )
    if os.name != "nt":
        directory.chmod(0o700)
        for path in directory.iterdir():
            if path.is_file():
                path.chmod(0o600)
    print("generated restricted short-lived local verification material; values not printed")


if __name__ == "__main__":
    main()
