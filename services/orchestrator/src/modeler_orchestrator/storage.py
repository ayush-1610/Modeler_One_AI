"""Credentialed object store and per-job presigned URLs (task T-07).

The orchestrator holds the MinIO/S3 credentials; engine pods never do. For each job the orchestrator
mints short-lived presigned GET URLs for inputs and presigned PUT URLs for outputs (default two hours,
architecture decision D11), and the engine transfers bytes over those URLs with `HttpObjectStore`. Keys
are namespaced per tenant so a presigned URL can only ever reach one tenant's prefix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.client import Config

DEFAULT_EXPIRY_SECONDS = 7200  # two hours


@dataclass(frozen=True)
class S3Settings:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"

    @classmethod
    def from_env(cls) -> S3Settings:
        return cls(
            endpoint_url=os.environ["MODELER_S3_ENDPOINT"],
            access_key=os.environ["MODELER_S3_ACCESS_KEY"],
            secret_key=os.environ["MODELER_S3_SECRET_KEY"],
            bucket=os.environ.get("MODELER_S3_BUCKET", "modeler"),
            region=os.environ.get("MODELER_S3_REGION", "us-east-1"),
        )


class S3ObjectStore:
    """MinIO/S3 access for the credentialed control plane, plus presigned URL minting."""

    def __init__(self, settings: S3Settings):
        self._bucket = settings.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
            region_name=settings.region,
            config=Config(signature_version="s3v4"),  # required for MinIO presigned URLs
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def _key(self, uri_or_key: str) -> str:
        """Accept either an ``s3://bucket/key`` URI or a bare key and return the key."""
        parsed = urlparse(uri_or_key)
        if parsed.scheme == "s3":
            return parsed.path.lstrip("/")
        return uri_or_key.lstrip("/")

    # --- ObjectStore protocol (credentialed side, used by the API/tests) -------------------------

    def upload(self, source: Path, uri_or_key: str) -> None:
        self._client.upload_file(str(source), self._bucket, self._key(uri_or_key))

    def download(self, uri_or_key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, self._key(uri_or_key), str(destination))

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._key(key), Body=data)

    # --- presigning (for engine jobs) ------------------------------------------------------------

    def presign_get(self, key: str, *, expires_in: int = DEFAULT_EXPIRY_SECONDS) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": self._key(key)}, ExpiresIn=expires_in
        )

    def presign_put(self, key: str, *, expires_in: int = DEFAULT_EXPIRY_SECONDS) -> str:
        return self._client.generate_presigned_url(
            "put_object", Params={"Bucket": self._bucket, "Key": self._key(key)}, ExpiresIn=expires_in
        )


def tenant_key(tenant_id: str, *parts: str) -> str:
    """Namespace an object key under a tenant prefix so presigned URLs cannot cross tenants."""
    return "/".join(("tenants", tenant_id, *parts))
