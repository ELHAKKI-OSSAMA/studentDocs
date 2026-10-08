"""Object storage abstraction (S3-compatible). Business code never talks to boto3 directly."""

import asyncio
import uuid
from dataclasses import dataclass

from botocore.client import BaseClient
from botocore.exceptions import ClientError


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class ObjectStorage:
    client: BaseClient
    bucket: str

    @staticmethod
    def new_key(prefix: str) -> str:
        # Random keys: never derived from user input (no path traversal, no name leaks).
        return f"{prefix}/{uuid.uuid4().hex}"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        def _read() -> bytes:
            try:
                return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except ClientError as exc:
                raise StorageError(f"Cannot read object {key}") from exc

        return await asyncio.to_thread(_read)

    async def delete_quietly(self, keys: list[str]) -> None:
        """Best-effort cleanup after a failed transaction (orphans are harmless and listable)."""
        for key in keys:
            try:
                await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
            except ClientError:
                continue
