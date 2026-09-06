from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from aegis_api.conventions import (
    APIError,
    Cursor,
    CursorCodec,
    EventQuery,
    FindingQuery,
    ListQuery,
    Page,
)
from aegis_api.db.models import Finding, ScanEvent, Target, TenantRecord


@dataclass(frozen=True)
class TenantScope:
    """Internal capability supplied by future verified identity/job dependencies.

    Never deserialize this from an HTTP body, header or unverified claim.
    This foundation enforces tenant boundaries, not project/role permissions.
    """

    organization_id: UUID


class Repository[T: TenantRecord]:
    def __init__(
        self, session: AsyncSession, scope: TenantScope, model: type[T]
    ) -> None:
        self._session, self._scope, self._model = session, scope, model

    async def get(self, resource_id: UUID) -> T:
        result = await self._session.scalar(
            select(self._model).where(
                self._model.organization_id == self._scope.organization_id,
                self._model.id == resource_id,
            )
        )
        if result is None:
            raise APIError(404, "not_found", "Resource not found.")
        return result

    async def add(self, record: T) -> T:
        if record.organization_id != self._scope.organization_id:
            raise APIError(404, "not_found", "Resource not found.")
        self._session.add(record)
        await self._session.flush()
        return record


class TimelineRepository[T: Finding | ScanEvent](Repository[T]):
    async def page(self, query: ListQuery, codec: CursorCodec) -> tuple[list[T], Page]:
        model = self._model
        statement = select(model).where(
            model.organization_id == self._scope.organization_id
        )
        if model is Finding and isinstance(query, FindingQuery):
            for field, value in [
                ("target_id", query.target_id),
                ("scanner_severity", query.severity),
                ("state", query.state),
                ("cwe", query.cwe),
            ]:
                if value is not None:
                    statement = statement.where(getattr(model, field) == value)
        elif model is ScanEvent and isinstance(query, EventQuery):
            statement = statement.where(ScanEvent.scan_id == query.scan_id)
        else:
            raise ValueError("Use the matching allowlisted query schema")
        binding = codec.binding(model.__tablename__, query)
        descending = query.order.startswith("-")
        if query.cursor:
            cursor = codec.decode(query.cursor, self._scope.organization_id, binding)
            position = tuple_(model.created_at, model.id)
            boundary = tuple_(literal(cursor.created_at), literal(cursor.id))
            statement = statement.where(
                position < boundary if descending else position > boundary
            )
        if descending:
            statement = statement.order_by(model.created_at.desc(), model.id.desc())
        else:
            statement = statement.order_by(model.created_at.asc(), model.id.asc())
        rows = list(
            (await self._session.scalars(statement.limit(query.limit + 1))).all()
        )
        has_more = len(rows) > query.limit
        rows = rows[: query.limit]
        next_cursor = (
            codec.encode(
                Cursor(
                    organization_id=self._scope.organization_id,
                    binding=binding,
                    created_at=rows[-1].created_at,
                    id=rows[-1].id,
                )
            )
            if has_more
            else None
        )
        return rows, Page(next_cursor=next_cursor, has_more=has_more)


class TargetRepository(Repository[Target]):
    def __init__(self, session: AsyncSession, scope: TenantScope) -> None:
        super().__init__(session, scope, Target)

    async def deactivate(self, resource_id: UUID, version: int) -> Target:
        # Tenant lookup first gives identical 404 for absent/foreign IDs.
        await self.get(resource_id)
        from aegis_api.db.enums import RecordState

        result = await self._session.scalar(
            update(Target)
            .where(
                Target.organization_id == self._scope.organization_id,
                Target.id == resource_id,
                Target.version == version,
            )
            .values(
                status=RecordState.DEACTIVATED,
                version=Target.version + 1,
                authorized_until=None,
                authorized_scope_digest=None,
                authorization_actor_id=None,
                authorization_method=None,
                authorization_evidence_ref=None,
                verified_at=None,
            )
            .returning(Target)
            .execution_options(populate_existing=True)
        )
        if result is None:
            raise APIError(
                412, "version_conflict", "Resource changed; reload before editing."
            )
        return result
