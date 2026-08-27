import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from docx import Document as DocxDocument
from sqlalchemy import delete

ISSUER = "http://host.docker.internal:8765"
AUDIENCE = "production-rag-assistant-api"
TOKEN_LIFETIME_SECONDS = 300
REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "backend"))


def public_jwk(private_key: object, kid: str) -> dict[str, object]:
    value = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    value.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return value


def token(
    private_key: object,
    kid: str,
    subject: str,
    *,
    audience: str = AUDIENCE,
    expires_in: int = TOKEN_LIFETIME_SECONDS,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": subject,
            "aud": audience,
            "iat": now,
            "nbf": now - 1,
            "exp": now + expires_in,
            "scope": "rag:access",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid, "typ": "at+jwt"},
    )


class QuietJWKSHandler(BaseHTTPRequestHandler):
    jwks: dict[str, object] = {"keys": []}

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/jwks":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.jwks).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return None


def docker_environment() -> dict[str, str]:
    return {
        **os.environ,
        "POSTGRES_PORT": "25432",
        "DATABASE_URL": (
            "postgresql+asyncpg://rag_assistant_dev:rag_assistant_dev@"
            "postgres:5432/rag_assistant_dev"
        ),
        "APP_ENV": "test",
        "AUTH_ENABLED": "true",
        "AUTH_ISSUER": ISSUER,
        "AUTH_AUDIENCE": AUDIENCE,
        "AUTH_JWKS_URL": f"{ISSUER}/jwks",
        "AUTH_ALLOW_INSECURE_HTTP": "true",
        "AUTH_JWKS_CACHE_SECONDS": "300",
        "EMBEDDING_PROVIDER": "fake",
        "RERANKER_PROVIDER": "fake",
        "DOWNLOAD_RERANKER": "false",
        "OPENAI_API_KEY": "",
    }


def recreate_stack() -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "up",
            "--build",
            "-d",
            "--force-recreate",
            "api",
            "worker",
        ],
        cwd=REPOSITORY,
        env=docker_environment(),
        check=True,
    )


def wait_for_api() -> None:
    with httpx.Client(timeout=2) as client:
        for _ in range(60):
            try:
                if client.get("http://127.0.0.1:8000/health/live").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError("API did not become live within the smoke-test budget")


async def seed() -> dict[str, object]:
    from app.db.models import (
        Collection,
        Membership,
        MembershipRole,
        Organization,
        User,
    )
    from app.db.session import session_factory

    tenant_a, tenant_b = uuid4(), uuid4()
    collection_a, collection_b = uuid4(), uuid4()
    subjects = {
        name: f"m10-{name}-{uuid4()}"
        for name in ("viewer", "editor", "admin", "none")
    }
    users = {name: uuid4() for name in subjects}
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Organization(
                    id=tenant_a, name="M10 tenant A", slug=f"m10-a-{tenant_a}"
                ),
                Organization(
                    id=tenant_b, name="M10 tenant B", slug=f"m10-b-{tenant_b}"
                ),
            ]
        )
        session.add_all(
            [
                User(
                    id=users[name],
                    issuer=ISSUER,
                    subject=subject,
                    enabled=True,
                )
                for name, subject in subjects.items()
            ]
        )
        await session.flush()
        session.add_all(
            [
                Membership(
                    tenant_id=tenant_a,
                    user_id=users["viewer"],
                    role=MembershipRole.VIEWER,
                ),
                Membership(
                    tenant_id=tenant_a,
                    user_id=users["editor"],
                    role=MembershipRole.EDITOR,
                ),
                Membership(
                    tenant_id=tenant_a,
                    user_id=users["admin"],
                    role=MembershipRole.ADMIN,
                ),
            ]
        )
        session.add_all(
            [
                Collection(id=collection_a, tenant_id=tenant_a, name="M10 A"),
                Collection(id=collection_b, tenant_id=tenant_b, name="M10 B"),
            ]
        )
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "collection_a": collection_a,
        "collection_b": collection_b,
        "subjects": subjects,
        "users": users,
    }


async def cleanup(state: dict[str, object]) -> None:
    from app.db.models import Organization, User
    from app.db.session import dispose_engine, session_factory

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(Organization).where(
                Organization.id.in_([state["tenant_a"], state["tenant_b"]])
            )
        )
        await session.execute(
            delete(User).where(User.id.in_(list(state["users"].values())))
        )
    await dispose_engine()


async def verify(private_one: object, private_two: object) -> None:
    state = await seed()
    subjects = state["subjects"]
    headers = {
        name: {"Authorization": f"Bearer {token(private_one, 'key-1', subject)}"}
        for name, subject in subjects.items()
    }
    api = "http://127.0.0.1:8000"
    try:
        async with httpx.AsyncClient(base_url=api, timeout=30) as client:
            viewer_me = await client.get("/auth/me", headers=headers["viewer"])
            viewer_search = await client.post(
                f"/collections/{state['collection_a']}/keyword-search",
                headers=headers["viewer"],
                json={"query": "synthetic", "top_k": 5},
            )
            viewer_ask = await client.post(
                f"/collections/{state['collection_a']}/ask",
                headers=headers["viewer"],
                json={"query": "synthetic absent question", "retrieval_count": 5},
            )
            conversation = await client.post(
                f"/collections/{state['collection_a']}/conversations",
                headers=headers["viewer"],
            )
            conversation_id = conversation.json()["id"]
            conversation_path = (
                f"/collections/{state['collection_a']}/conversations/"
                f"{conversation_id}/messages"
            )
            first_turn = await client.post(
                conversation_path,
                headers={**headers["viewer"], "Idempotency-Key": "m11-first"},
                json={"query": "synthetic absent question", "top_k": 5},
            )
            replayed_turn = await client.post(
                conversation_path,
                headers={**headers["viewer"], "Idempotency-Key": "m11-first"},
                json={"query": "synthetic absent question", "top_k": 5},
            )
            viewer_upload = await client.post(
                f"/collections/{state['collection_a']}/documents",
                headers=headers["viewer"],
                files={
                    "file": (
                        "denied.docx",
                        b"not-used",
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document",
                    )
                },
            )
            no_membership = await client.get(
                "/collections",
                headers=headers["none"],
                params={"tenant_id": state["tenant_a"]},
            )
            cross_collection = await client.post(
                f"/collections/{state['collection_b']}/keyword-search",
                headers=headers["viewer"],
                json={"query": "synthetic"},
            )
            admin_create = await client.post(
                "/collections",
                headers=headers["admin"],
                json={"tenant_id": str(state["tenant_a"]), "name": "M10 created"},
            )

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "m10-synthetic.docx"
                document = DocxDocument()
                document.add_paragraph("Synthetic authentication smoke content.")
                document.save(path)
                with path.open("rb") as upload:
                    editor_upload = await client.post(
                        f"/collections/{state['collection_a']}/documents",
                        headers=headers["editor"],
                        files={
                            "file": (
                                path.name,
                                upload,
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            )
                        },
                    )
            assert editor_upload.status_code == 202
            job_id = editor_upload.json()["job_id"]
            for _ in range(60):
                job = await client.get(
                    f"/processing-jobs/{job_id}", headers=headers["editor"]
                )
                if job.json()["status"] in {"succeeded", "failed"}:
                    break
                await asyncio.sleep(0.25)

            expired = await client.get(
                "/auth/me",
                headers={
                    "Authorization": "Bearer "
                    + token(
                        private_one,
                        "key-1",
                        subjects["viewer"],
                        expires_in=-60,
                    )
                },
            )
            wrong_audience = await client.get(
                "/auth/me",
                headers={
                    "Authorization": "Bearer "
                    + token(
                        private_one,
                        "key-1",
                        subjects["viewer"],
                        audience="wrong",
                    )
                },
            )
            invalid_signature = await client.get(
                "/auth/me",
                headers={
                    "Authorization": "Bearer "
                    + token(
                        rsa.generate_private_key(public_exponent=65537, key_size=2048),
                        "key-1",
                        subjects["viewer"],
                    )
                },
            )

            QuietJWKSHandler.jwks = {"keys": [public_jwk(private_two, "key-2")]}
            rotated = await client.get(
                "/auth/me",
                headers={
                    "Authorization": "Bearer "
                    + token(private_two, "key-2", subjects["viewer"])
                },
            )

        assert viewer_me.status_code == 200
        assert viewer_search.status_code == 200
        assert viewer_ask.status_code == 200
        assert viewer_ask.json()["status"] == "insufficient_context"
        assert conversation.status_code == 201
        assert first_turn.status_code == 200
        assert first_turn.json()["answer"]["status"] == "insufficient_context"
        assert replayed_turn.json() == first_turn.json()
        assert viewer_upload.status_code == 403
        assert no_membership.status_code == 403
        assert cross_collection.status_code == 404
        assert admin_create.status_code == 201
        assert job.json()["status"] == "succeeded"
        assert expired.status_code == 401
        assert wrong_audience.status_code == 401
        assert invalid_signature.status_code == 401
        assert rotated.status_code == 200
        print(
            "algorithm=RS256 issuer=ephemeral-local "
            "audience=production-rag-assistant-api"
        )
        print(
            "token_lifetime_seconds=300 jwks_initial_fetch=passed "
            "rotation_refresh=passed"
        )
        print("viewer_search=200 viewer_ask=200 viewer_upload=403 editor_upload=202")
        print("conversation_create=201 first_turn=200 idempotent_replay=identical")
        print("no_membership=403 cross_tenant_resource=404 admin_collection_create=201")
        print(
            "expired=401 wrong_audience=401 invalid_signature=401 "
            "processing=succeeded"
        )
        print("paid_openai_calls=0")
    finally:
        await cleanup(state)


def main() -> None:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://rag_assistant_dev:rag_assistant_dev@"
        "127.0.0.1:25432/rag_assistant_dev"
    )
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    QuietJWKSHandler.jwks = {"keys": [public_jwk(first, "key-1")]}
    server = ThreadingHTTPServer(("0.0.0.0", 8765), QuietJWKSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        recreate_stack()
        wait_for_api()
        asyncio.run(verify(first, second))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
