"""Development-only real HTTP ingestion smoke test; prints no file bytes or full IDs."""

import json
import os
import time
import urllib.request


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


base_url = os.environ.get("E2E_API_URL", "http://localhost:8000")
collection_id = os.environ["E2E_COLLECTION_ID"]
boundary = "safe-e2e-boundary"
pdf = b"%PDF-1.7\n% Milestone 4 smoke test\n"
body = (
    (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="../safe.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    + pdf
    + f"\r\n--{boundary}--\r\n".encode()
)
created = request(
    f"{base_url}/collections/{collection_id}/documents",
    "POST",
    body,
    f"multipart/form-data; boundary={boundary}",
)
job_id = created["job_id"]
terminal: dict[str, object] = {}
for _ in range(30):
    terminal = request(f"{base_url}/processing-jobs/{job_id}")
    if terminal["status"] in {"succeeded", "failed"}:
        break
    time.sleep(1)
if terminal.get("status") != "succeeded":
    raise RuntimeError(f"Unexpected terminal status: {terminal.get('status')}")
print(
    json.dumps(
        {
            "upload_status": created["processing_status"],
            "terminal_status": terminal["status"],
            "attempt_count": terminal["attempt_count"],
            "filename": created["original_filename"],
        }
    )
)
