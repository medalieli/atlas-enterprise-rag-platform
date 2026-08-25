"""Development-only PDF/DOCX HTTP smoke test; prints no document text or IDs."""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixture_builders import docx_bytes, pdf_bytes


def request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> dict[str, object]:
    headers = {"Content-Type": content_type} if content_type else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=body, method=method, headers=headers),
        timeout=10,
    ) as response:
        return json.loads(response.read())


def upload_and_wait(filename: str, mime: str, content: bytes) -> dict[str, object]:
    boundary = f"safe-{filename.replace('.', '-')}-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    created = request(
        f"{base_url}/collections/{collection_id}/documents",
        "POST",
        body,
        f"multipart/form-data; boundary={boundary}",
    )
    terminal: dict[str, object] = {}
    for _ in range(45):
        terminal = request(f"{base_url}/processing-jobs/{created['job_id']}")
        if terminal["status"] in {"succeeded", "failed"}:
            break
        time.sleep(1)
    if terminal.get("status") != "succeeded":
        raise RuntimeError(f"Unexpected {filename} status: {terminal.get('status')}")
    return {
        "type": filename.rsplit(".", 1)[-1],
        "status": terminal["status"],
        "attempts": terminal["attempt_count"],
    }


base_url = os.environ.get("E2E_API_URL", "http://localhost:8000")
collection_id = os.environ["E2E_COLLECTION_ID"]
results = [
    upload_and_wait(
        "traceable.pdf",
        "application/pdf",
        pdf_bytes(["First page trace.", "Second page trace."]),
    ),
    upload_and_wait(
        "traceable.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx_bytes(),
    ),
]
print(json.dumps(results))
