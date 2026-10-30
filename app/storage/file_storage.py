"""Uploaded files behind one small interface, so ingestion does not care where they live.

- S3FileStorage: RustFS (or any S3-compatible store) through boto3, with a read-only key
- LocalFileStorage: a folder on disk, for development and tests

Both are synchronous: call them via asyncio.to_thread. Errors become StorageError with a
short message; only the exception type is logged, because messages can hold keys, paths or URLs.
"""

import logging
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from app.core.config import Settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """The file could not be read from storage."""


class StorageUnavailableError(StorageError):
    """Storage could not be reached: worth retrying later, unlike a missing file."""


class FileStorage(Protocol):
    def read(self, storage_url: str, max_bytes: int) -> bytes:
        """The file's bytes. Raises StorageError, also when the file is larger than max_bytes."""
        ...


def parse_storage_url(storage_url: str, default_bucket: str) -> tuple[str, str]:
    """(bucket, key) from "s3://bucket/key", "http(s)://host/bucket/key" or a plain key.
    The host of an http(s) URL is ignored: files are only ever read from the configured endpoint."""
    url = storage_url.strip()
    parsed = urlparse(url)
    if parsed.scheme == "s3":
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
    elif parsed.scheme in ("http", "https"):
        bucket, _, key = parsed.path.lstrip("/").partition("/")
    else:
        bucket, key = default_bucket, url.lstrip("/")
    if not bucket or not key:
        raise StorageError("storage_url has no bucket or key")
    if ".." in key.split("/"):
        raise StorageError("storage_url points outside the storage folder")
    return bucket, key


class S3FileStorage:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        missing = [
            name
            for name, value in (
                ("STORAGE_ENDPOINT_URL", settings.storage_endpoint_url),
                ("STORAGE_BUCKET", settings.storage_bucket),
                ("STORAGE_ACCESS_KEY", settings.storage_access_key.get_secret_value()),
                ("STORAGE_SECRET_KEY", settings.storage_secret_key.get_secret_value()),
            )
            if not value
        ]
        if missing:
            raise StorageError(f"storage not configured ({', '.join(missing)})")
        self._bucket = settings.storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key.get_secret_value(),
            aws_secret_access_key=settings.storage_secret_key.get_secret_value(),
            region_name=settings.storage_region,
            config=Config(
                connect_timeout=settings.storage_timeout_seconds,
                read_timeout=settings.storage_timeout_seconds,
                retries={"max_attempts": 2},
                s3={"addressing_style": "path"},  # RustFS/MinIO style: host/bucket/key
            ),
        )

    def read(self, storage_url: str, max_bytes: int) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        bucket, key = parse_storage_url(storage_url, self._bucket)
        if bucket != self._bucket:  # never read another bucket, whatever storage_url says
            raise StorageError("storage_url names a different bucket")
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            try:
                if response.get("ContentLength", 0) > max_bytes:
                    raise StorageError("file is larger than the allowed size")
                data = body.read(max_bytes + 1)
            finally:
                body.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "unknown")
            logger.warning("Storage read failed: %s", code)
            if code in ("NoSuchKey", "NoSuchBucket", "404"):
                raise StorageError("file not found in storage") from exc
            raise StorageError("storage refused the request") from exc
        except BotoCoreError as exc:
            logger.warning("Storage unreachable: %s", type(exc).__name__)
            raise StorageUnavailableError("storage unreachable") from exc
        if len(data) > max_bytes:
            raise StorageError("file is larger than the allowed size")
        return data


class LocalFileStorage:
    def __init__(self, root: str) -> None:
        if not root:
            raise StorageError("storage not configured (STORAGE_LOCAL_ROOT)")
        self._root = Path(root).resolve()

    def read(self, storage_url: str, max_bytes: int) -> bytes:
        _, key = parse_storage_url(storage_url, "local")
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):  # "../" must not escape the folder
            raise StorageError("storage_url points outside the storage folder")
        if not path.is_file():
            raise StorageError("file not found in storage")
        with path.open("rb") as file:
            data = file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise StorageError("file is larger than the allowed size")
        return data


def get_file_storage(settings: Settings) -> FileStorage:
    if settings.storage_backend == "local":
        return LocalFileStorage(settings.storage_local_root)
    return S3FileStorage(settings)
