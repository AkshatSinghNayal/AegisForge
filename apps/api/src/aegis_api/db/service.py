"""Atomic command deduplication; caller owns the transaction and authorization."""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.conventions import APIError
from aegis_api.db.models import IdempotencyRecord
from aegis_api.db.repository import TenantScope


@dataclass(frozen=True)
class CommandResult:
    resource_id: UUID
    status: int
    replayed: bool


class CommandService:
    def __init__(
        self, session: AsyncSession, scope: TenantScope, actor_id: UUID
    ) -> None:
        self._session, self._scope, self._actor = session, scope, actor_id

    async def execute(
        self,
        *,
        operation: str,
        key: str | None,
        digest: str,
        resource_id: UUID,
        status: int,
        create: Callable[[UUID], Awaitable[None]],
    ) -> CommandResult:
        """Use only inside session.begin(); callback must not commit or send effects.

        operation is a server-owned method + route + concrete resource binding.
        actor_id is a verified member/integration principal, not a client claim.
        Callback and receipt commit together; failure rolls both back. No responses,
        request payloads, headers or raw idempotency keys are stored.
        """
        if not self._session.in_transaction():
            raise RuntimeError("Command requires an explicit transaction")
        if (
            key is None
            or not 1 <= len(key) <= 200
            or not key.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in key)
        ):
            raise APIError(
                400,
                "invalid_idempotency_key",
                "Idempotency-Key must contain 1–200 printable ASCII characters.",
            )
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Expected SHA-256 request digest")
        # Roll back the receipt and callback writes even when the caller catches
        # the error and commits unrelated work in its outer transaction.
        async with self._session.begin_nested():
            return await self._execute(
                operation=operation,
                key=key,
                digest=digest,
                resource_id=resource_id,
                status=status,
                create=create,
            )

    async def _execute(
        self,
        *,
        operation: str,
        key: str,
        digest: str,
        resource_id: UUID,
        status: int,
        create: Callable[[UUID], Awaitable[None]],
    ) -> CommandResult:
        now = await self._session.scalar(select(func.clock_timestamp()))
        assert now is not None
        values = dict(
            organization_id=self._scope.organization_id,
            actor_id=self._actor,
            operation=operation,
            key_hash=hashlib.sha256(key.encode()).hexdigest(),
            request_digest=digest,
            resource_id=resource_id,
            response_status=status,
            expires_at=now + timedelta(hours=24),
        )
        statement = (
            insert(IdempotencyRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["organization_id", "actor_id", "operation", "key_hash"]
            )
            .returning(IdempotencyRecord.id)
        )
        inserted = await self._session.scalar(statement)
        if inserted is None:
            existing = await self._session.scalar(
                select(IdempotencyRecord)
                .where(
                    IdempotencyRecord.organization_id == self._scope.organization_id,
                    IdempotencyRecord.actor_id == self._actor,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.key_hash == values["key_hash"],
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert existing is not None
            # Row locking can wait; compare expiry against the time after the
            # lock and read refreshed values, not the session identity map.
            now = await self._session.scalar(select(func.clock_timestamp()))
            assert now is not None
            if existing.expires_at > now:
                if existing.request_digest != digest:
                    raise APIError(
                        409,
                        "idempotency_conflict",
                        "Key was used for a different request.",
                    )
                return CommandResult(
                    existing.resource_id, existing.response_status, True
                )
            existing.request_digest, existing.resource_id = digest, resource_id
            existing.response_status, existing.expires_at = (
                status,
                now + timedelta(hours=24),
            )
        await create(resource_id)
        await self._session.flush()
        return CommandResult(resource_id, status, False)
