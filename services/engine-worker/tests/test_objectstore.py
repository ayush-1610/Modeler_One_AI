"""Integration tests for presigned object I/O against a real MinIO (task T-07).

Requires Docker; skipped otherwise. The credentialed S3ObjectStore mints presigned URLs; the engine's
HttpObjectStore transfers bytes over them with no credentials of its own. Covers the acceptance criteria:
a tampered object fails the runner's integrity check, an expired URL errors (a retryable failure), and
uploads/downloads work with only a URL.
"""

from __future__ import annotations

import hashlib
import sys
import time
import uuid

import pytest

try:
    import boto3  # noqa: F401
    from botocore.exceptions import ClientError  # noqa: F401
    from testcontainers.core.container import DockerContainer

    _HAVE_DEPS = True
except ImportError:  # pragma: no cover
    _HAVE_DEPS = False

from modeler_contracts.runs import EngineInput, EngineJob
from modeler_engine.objectstore import HttpObjectStore, ObjectTransferError
from modeler_engine.runner import EngineRunner, InputIntegrityError

FAKE_ENGINE = """
import json, sys
job = json.load(open(sys.argv[1]))
# prove the staged input is present and readable, then finish with no outputs
for item in job["inputs"]:
    assert open(item["path"], "rb").read(), item["name"]
print("PROGRESS 1.000")
"""


def _s3(endpoint: str):
    from modeler_orchestrator.storage import S3ObjectStore, S3Settings

    return S3ObjectStore(S3Settings(endpoint_url=endpoint, access_key="minioadmin", secret_key="minioadmin", bucket="modeler"))


@pytest.fixture(scope="module")
def minio():
    if not _HAVE_DEPS:
        pytest.skip("docker/testcontainers not available")
    try:
        container = (
            DockerContainer("minio/minio:latest")
            .with_env("MINIO_ROOT_USER", "minioadmin")
            .with_env("MINIO_ROOT_PASSWORD", "minioadmin")
            .with_exposed_ports(9000)
            .with_command("server /data")
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - docker missing/unhealthy: skip, don't fail
        pytest.skip(f"cannot start MinIO container: {exc}")
    endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
    try:
        store = _s3(endpoint)
        # create the bucket, retrying until MinIO is accepting connections (readiness signal)
        for attempt in range(40):
            try:
                store._client.create_bucket(Bucket="modeler")
                break
            except Exception:
                if attempt == 39:
                    raise
                time.sleep(0.5)
        yield store
    finally:
        container.stop()


def _put(store, key: str, data: bytes) -> str:
    store.put_bytes(key, data)
    return hashlib.sha256(data).hexdigest()


def test_presigned_get_download_preserves_bytes(minio, tmp_path):
    key = f"tenants/t1/inputs/{uuid.uuid4()}.bin"
    digest = _put(minio, key, b"snapshot-bytes-123")
    url = minio.presign_get(key)
    dest = tmp_path / "got.bin"
    HttpObjectStore().download(url, dest)
    assert dest.read_bytes() == b"snapshot-bytes-123"
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest


def test_runner_rejects_tampered_input(minio, tmp_path):
    key = f"tenants/t1/inputs/{uuid.uuid4()}.json"
    _put(minio, key, b"the-real-object")
    url = minio.presign_get(key)
    job = EngineJob(
        job_id="j1", tenant_id="t1", task="dry_run",
        inputs=[EngineInput(name="snapshot.json", uri=url, sha256="0" * 64)],  # declared hash != actual
        outputs_uri="unused",
    )
    runner = EngineRunner(command=["true"], store=HttpObjectStore(), engine_id="e", image_digest="sha256:x")
    with pytest.raises(InputIntegrityError, match="sha256"):
        runner.run(job)


def test_expired_url_errors(minio, tmp_path):
    key = f"tenants/t1/inputs/{uuid.uuid4()}.bin"
    _put(minio, key, b"x")
    url = minio.presign_get(key, expires_in=1)
    time.sleep(2)
    with pytest.raises(ObjectTransferError):
        HttpObjectStore().download(url, tmp_path / "x.bin")


def test_credential_free_put_roundtrip(minio, tmp_path):
    key = f"tenants/t1/outputs/{uuid.uuid4()}.csv"
    src = tmp_path / "out.csv"
    src.write_bytes(b"time,conc\n0,0\n1,5\n")
    # engine-side upload with only a presigned URL, no credentials
    HttpObjectStore().upload(src, minio.presign_put(key))
    back = tmp_path / "back.csv"
    minio.download(key, back)
    assert back.read_bytes() == src.read_bytes()


def test_runner_downloads_and_runs_over_presigned_url(minio, tmp_path):
    engine = tmp_path / "fake_engine.py"
    engine.write_text(FAKE_ENGINE)
    key = f"tenants/t1/inputs/{uuid.uuid4()}.json"
    data = b'{"Version": 80}'
    digest = _put(minio, key, data)
    job = EngineJob(
        job_id="j2", tenant_id="t1", task="simulate",
        inputs=[EngineInput(name="snapshot.json", uri=minio.presign_get(key), sha256=digest)],
        outputs_uri="unused",  # fake engine writes no outputs, so nothing is uploaded
    )
    runner = EngineRunner(command=[sys.executable, str(engine)], store=HttpObjectStore(), engine_id="e", image_digest="sha256:x")
    manifest = runner.run(job)
    assert manifest.status == "SUCCEEDED"
    assert manifest.inputs["snapshot.json"] == digest
