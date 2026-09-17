"""MinIO client wrapper for artifact storage."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "factory-artifacts"


class MinIOClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = DEFAULT_BUCKET

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"MinIO bucket error: {e}")

    def artifact_key(self, run_id: int, filename: str) -> str:
        """Build the MinIO object key for an artifact."""
        return f"runs/{run_id}/artifacts/{filename}"

    def upload_file(self, run_id: int, filename: str, file_path: Path) -> str:
        """Upload a local file to MinIO. Returns the object key."""
        key = self.artifact_key(run_id, filename)
        self.client.fput_object(self.bucket, key, str(file_path))
        return key

    def upload_bytes(self, run_id: int, filename: str, data: bytes) -> str:
        """Upload bytes to MinIO. Returns the object key."""
        key = self.artifact_key(run_id, filename)
        self.client.put_object(
            self.bucket, key, io.BytesIO(data), length=len(data),
        )
        return key

    def upload_text(self, run_id: int, filename: str, text: str) -> str:
        """Upload text content to MinIO. Returns the object key."""
        return self.upload_bytes(run_id, filename, text.encode("utf-8"))

    def download_text(self, run_id: int, filename: str) -> str | None:
        """Download text content from MinIO. Returns None if not found."""
        key = self.artifact_key(run_id, filename)
        try:
            response = self.client.get_object(self.bucket, key)
            data = response.read().decode("utf-8")
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise

    def upload_diff(self, run_id: int, diff_text: str) -> str:
        """Upload git diff to MinIO."""
        key = f"runs/{run_id}/diff.patch"
        data = diff_text.encode("utf-8")
        self.client.put_object(self.bucket, key, io.BytesIO(data), length=len(data))
        return key

    def download_diff(self, run_id: int) -> str | None:
        """Download git diff from MinIO."""
        key = f"runs/{run_id}/diff.patch"
        try:
            response = self.client.get_object(self.bucket, key)
            data = response.read().decode("utf-8")
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise

    def list_artifacts(self, run_id: int) -> list[str]:
        """List all artifact filenames for a run."""
        prefix = f"runs/{run_id}/artifacts/"
        objects = self.client.list_objects(self.bucket, prefix=prefix)
        return [obj.object_name.replace(prefix, "") for obj in objects]

    def upload_directory(self, run_id: int, factory_dir: Path) -> list[str]:
        """Upload all files from .factory/ directory to MinIO. Returns list of uploaded filenames."""
        uploaded = []
        if not factory_dir.exists():
            return uploaded
        for file_path in sorted(factory_dir.rglob("*")):
            if file_path.is_file():
                filename = str(file_path.relative_to(factory_dir))
                self.upload_file(run_id, filename, file_path)
                uploaded.append(filename)
        return uploaded
