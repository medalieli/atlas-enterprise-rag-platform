"""Standards-oriented ephemeral RS256/OIDC issuer for local verification only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import ssl
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives import serialization


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class Issuer(BaseHTTPRequestHandler):
    issuer = ""
    client_id = ""
    client_secret = ""
    redirect_uri = "https://localhost/api/auth/callback"
    subject = "m15-admin"
    email = "atlas-admin@example.test"
    private_key: object
    jwks: dict[str, object]
    codes: dict[str, tuple[str, str, float, str, str]] = {}
    interactive_identities = False
    identities: dict[str, tuple[str, str]] = {
        "owner": ("local-owner", "owner@atlas.example.test"),
        "admin": ("local-admin", "admin@atlas.example.test"),
        "editor": ("local-editor", "editor@atlas.example.test"),
        "invitee": ("local-invitee", "invitee@atlas.example.test"),
    }

    def send_json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/.well-known/openid-configuration":
            self.send_json(
                200,
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": f"{self.issuer}/authorize",
                    "token_endpoint": f"{self.issuer}/token",
                    "jwks_uri": f"{self.issuer}/jwks",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code"],
                    "code_challenge_methods_supported": ["S256"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "scopes_supported": ["openid", "profile", "email", "rag:access"],
                },
            )
            return
        if parsed.path == "/jwks":
            self.send_json(200, self.jwks)
            return
        if parsed.path != "/authorize":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        required = ("client_id", "redirect_uri", "state", "code_challenge")
        if any(not query.get(name) for name in required):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if query["client_id"][0] != self.client_id or query.get(
            "code_challenge_method"
        ) != ["S256"]:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        redirect = query["redirect_uri"][0]
        if redirect != self.redirect_uri:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        identity_name = query.get("identity", [""])[0]
        if self.interactive_identities and identity_name not in self.identities:
            choices = []
            for name in self.identities:
                parameters = {key: values[0] for key, values in query.items()}
                parameters["identity"] = name
                href = html.escape(urlencode(parameters), quote=True)
                choices.append(
                    f'<li><a href="/authorize?{href}">'
                    f'{html.escape(name.title())}</a></li>'
                )
            body = (
                "<!doctype html><html><head>"
                '<meta name="referrer" content="no-referrer">'
                "<title>Local synthetic identity</title></head><body><main>"
                "<h1>Select a synthetic identity</h1>"
                "<p>Local verification only. No passwords are used.</p>"
                f"<ul>{''.join(choices)}</ul></main></body></html>"
            ).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        selected_subject, selected_email = self.identities.get(
            identity_name, (self.subject, self.email)
        )
        code = secrets.token_urlsafe(32)
        self.codes[code] = (
            query["code_challenge"][0],
            redirect,
            time.time() + 120,
            selected_subject,
            selected_email,
        )
        location = f"{redirect}?{urlencode({'code': code, 'state': query['state'][0]})}"
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/token":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 16384)
        form = parse_qs(self.rfile.read(length).decode())
        code = form.get("code", [""])[0]
        record = self.codes.pop(code, None)
        verifier = form.get("code_verifier", [""])[0]
        challenge = b64url(hashlib.sha256(verifier.encode()).digest())
        valid = (
            form.get("grant_type") == ["authorization_code"]
            and form.get("client_id") == [self.client_id]
            and secrets.compare_digest(
                form.get("client_secret", [""])[0], self.client_secret
            )
            and record is not None
            and record[0] == challenge
            and record[1] == form.get("redirect_uri", [""])[0]
            and record[2] >= time.time()
        )
        if not valid:
            self.send_json(400, {"error": "invalid_grant"})
            return
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": record[3],
            "aud": "production-rag-assistant-api",
            "iat": now,
            "nbf": now - 1,
            "exp": now + 900,
            "scope": "openid profile email rag:access",
            "email": record[4],
            "email_verified": True,
        }
        token = jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "m15", "typ": "at+jwt"},
        )
        self.send_json(
            200,
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 900,
                "scope": "openid profile email rag:access",
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--client-secret-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9444)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--insecure-http", action="store_true")
    parser.add_argument("--subject", default="m15-admin")
    parser.add_argument("--email", default="atlas-admin@example.test")
    parser.add_argument("--interactive-identities", action="store_true")
    parser.add_argument("--redirect-uri", default="https://localhost/api/auth/callback")
    args = parser.parse_args()
    if args.bind not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("the synthetic issuer must bind to a loopback address")
    private_key = serialization.load_pem_private_key(
        args.signing_key.read_bytes(), password=None
    )
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public.update({"kid": "m15", "alg": "RS256", "use": "sig"})
    Issuer.private_key = private_key
    Issuer.jwks = {"keys": [public]}
    scheme = "http" if args.insecure_http else "https"
    Issuer.issuer = f"{scheme}://host.docker.internal:{args.port}"
    Issuer.client_id = "m15-local-client"
    Issuer.client_secret = args.client_secret_file.read_text().strip()
    Issuer.redirect_uri = args.redirect_uri
    Issuer.subject = args.subject
    Issuer.email = args.email.strip().lower()
    Issuer.identities = {
        **Issuer.identities,
        "owner": (Issuer.subject, Issuer.email),
    }
    Issuer.interactive_identities = args.interactive_identities
    server = ThreadingHTTPServer((args.bind, args.port), Issuer)
    if not args.insecure_http:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print("ephemeral_oidc_ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
