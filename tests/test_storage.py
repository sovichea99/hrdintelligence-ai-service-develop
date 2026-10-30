import pytest

from app.core.config import Settings
from app.storage import LocalFileStorage, S3FileStorage, StorageError, parse_storage_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("s3://hrd-files-dev/uploads/a.pdf", ("hrd-files-dev", "uploads/a.pdf")),
        ("http://rustfs:9000/hrd-files/uploads/a.pdf", ("hrd-files", "uploads/a.pdf")),
        ("https://storage.example/hrd-files/a b.pdf", ("hrd-files", "a b.pdf")),
        ("uploads/a.pdf", ("default-bucket", "uploads/a.pdf")),
        ("/uploads/a.pdf", ("default-bucket", "uploads/a.pdf")),
    ],
)
def test_storage_url_formats(url, expected):
    assert parse_storage_url(url, "default-bucket") == expected


@pytest.mark.parametrize(
    "url", ["", "s3://hrd-files/", "s3:///key", "http://host/only-bucket", "uploads/../other-bucket/x", "../x"]
)
def test_storage_url_without_bucket_or_key_or_escaping_is_rejected(url):
    with pytest.raises(StorageError):
        parse_storage_url(url, "")


def s3_settings(**overrides):
    values = {"_env_file": None, "storage_endpoint_url": "http://rustfs:9000", "storage_bucket": "hrd-files",
              "storage_access_key": "test-access", "storage_secret_key": "test-secret"}
    return Settings(**(values | overrides))


@pytest.mark.parametrize(
    "missing", ["storage_endpoint_url", "storage_bucket", "storage_access_key", "storage_secret_key"]
)
def test_s3_storage_refuses_to_start_without_full_config(missing):
    with pytest.raises(StorageError, match=missing.upper()):
        S3FileStorage(s3_settings(**{missing: ""}))


def test_s3_storage_never_reads_another_bucket():
    storage = S3FileStorage(s3_settings())  # no request is made: the bucket check comes first
    for url in ("s3://other-bucket/a.pdf", "http://evil.example/other-bucket/a.pdf"):
        with pytest.raises(StorageError, match="different bucket"):
            storage.read(url, max_bytes=10)


def test_local_storage_reads_a_file(tmp_path):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "a.txt").write_bytes(b"hello")
    assert LocalFileStorage(str(tmp_path)).read("uploads/a.txt", max_bytes=10) == b"hello"


def test_local_storage_errors(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 11)
    storage = LocalFileStorage(str(tmp_path))
    with pytest.raises(StorageError, match="not found"):
        storage.read("missing.pdf", max_bytes=10)
    with pytest.raises(StorageError, match="larger"):
        storage.read("big.bin", max_bytes=10)
    with pytest.raises(StorageError, match="outside"):
        storage.read("../secret.txt", max_bytes=10)


def test_local_storage_needs_a_root():
    with pytest.raises(StorageError, match="not configured"):
        LocalFileStorage("")
