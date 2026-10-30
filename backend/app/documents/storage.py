"""Object storage abstraction (S3-compatible). Business code never talks to boto3 directly.

The bucket is private: objects are only reachable with the backend's credentials. Keys never contain
user input (no original file name, no path traversal) and are not guessable:

    tenants/<tenant>/requests/<request id>/<random uuid>        regular files
    tenants/<tenant>/emails/<email case id>/<random uuid>        email attachments
    tenants/<tenant>/emails/raw/<random uuid>                    raw received messages (.eml)
    quarantine/tenants/<tenant>/requests/<request id>/<uuid>     infected files, moved after the scan
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from botocore.client import BaseClient
from botocore.exceptions import ClientError

QUARANTINE_PREFIX = "quarantine/"
READ_CHUNK_SIZE = 64 * 1024


class StorageError(Exception):
    pass


class StorageObjectMissing(StorageError):
    pass


def _missing(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound")


@dataclass(frozen=True)
class ObjectStorage:
    client: BaseClient
    bucket: str
    tenant: str = "default"

    def new_key(self, request_id: uuid.UUID) -> str:
        return f"tenants/{self.tenant}/requests/{request_id}/{uuid.uuid4().hex}"

    def new_email_attachment_key(self, email_case_id: uuid.UUID) -> str:
        return f"tenants/{self.tenant}/emails/{email_case_id}/{uuid.uuid4().hex}"

    def new_raw_email_key(self) -> str:
        return f"tenants/{self.tenant}/emails/raw/{uuid.uuid4().hex}"

    @staticmethod
    def quarantine_key(key: str) -> str:
        return key if key.startswith(QUARANTINE_PREFIX) else f"{QUARANTINE_PREFIX}{key}"

    async def put_stream(self, key: str, stream: BinaryIO, content_type: str) -> None:
        """Streams a file to storage (multipart upload for large files, bounded memory)."""
        stream.seek(0)
        await asyncio.to_thread(
            self.client.upload_fileobj,
            stream,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def open_chunks(self, key: str, chunk_size: int = READ_CHUNK_SIZE) -> Iterator[bytes]:
        """Opens the object now (a missing object raises here) and returns a blocking chunk iterator."""
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as exc:
            if _missing(exc):
                raise StorageObjectMissing(key) from exc
            raise StorageError(f"Cannot read object {key}") from exc

        def chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(chunk_size)
            finally:
                body.close()

        return chunks()

    async def open(self, key: str) -> Iterator[bytes]:
        return await asyncio.to_thread(self.open_chunks, key)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(lambda: b"".join(self.open_chunks(key)))

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if _missing(exc):
                return False
            raise

    async def move(self, key: str, new_key: str) -> None:
        """Copy then delete (S3 has no rename). The copy happens server side."""
        await asyncio.to_thread(
            self.client.copy_object,
            Bucket=self.bucket,
            Key=new_key,
            CopySource={"Bucket": self.bucket, "Key": key},
        )
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def delete_quietly(self, keys: list[str]) -> None:
        """Best-effort cleanup after a failed transaction (orphans are harmless and listable)."""
        for key in keys:
            try:
                await self.delete(key)
            except ClientError:
                continue
