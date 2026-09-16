"""Credential-free object I/O for the engine pod (task T-07).

Engine pods hold no object-store credentials (architecture decision D11). Every input and output is a
presigned MinIO/S3 URL issued per job by the orchestrator: the engine GETs inputs and PUTs outputs over
plain HTTP with no signing of its own. `HttpObjectStore` implements the runner's `ObjectStore` protocol
using only the standard library, so nothing here can read the object store beyond the exact objects and
window the presigned URLs allow. Integrity is enforced by the runner, which verifies every input's
sha256 after download.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path


class ObjectTransferError(Exception):
    """A presigned GET/PUT failed (network error, expired or forbidden URL, unexpected status)."""


class HttpObjectStore:
    """Downloads and uploads objects through presigned http(s) URLs. Holds no credentials."""

    def __init__(self, *, timeout_s: float = 300.0):
        self._timeout = timeout_s

    def download(self, uri: str, destination: Path) -> None:
        _require_http(uri, "download")
        request = urllib.request.Request(uri, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response, destination.open("wb") as out:
                shutil.copyfileobj(response, out)
        except urllib.error.HTTPError as exc:  # expired/forbidden presigned URL -> retryable by the caller
            raise ObjectTransferError(f"GET {_redact(uri)} failed: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ObjectTransferError(f"GET {_redact(uri)} failed: {exc.reason}") from exc

    def upload(self, source: Path, uri: str) -> None:
        _require_http(uri, "upload")
        data = source.read_bytes()
        request = urllib.request.Request(
            uri, data=data, method="PUT", headers={"Content-Length": str(len(data)), "Content-Type": "application/octet-stream"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if response.status not in (200, 201, 204):
                    raise ObjectTransferError(f"PUT {_redact(uri)} returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise ObjectTransferError(f"PUT {_redact(uri)} failed: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ObjectTransferError(f"PUT {_redact(uri)} failed: {exc.reason}") from exc


def _require_http(uri: str, op: str) -> None:
    if not uri.startswith(("http://", "https://")):
        raise ObjectTransferError(f"HttpObjectStore can only {op} http(s) URLs, got {_redact(uri)}")


def _redact(uri: str) -> str:
    """Drop the query string so presigned signatures never reach logs."""
    return uri.split("?", 1)[0]
