"""Synthetic event setup and read-only key assertions for the live browser run."""

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import timedelta
from uuid import UUID

from aegis_api.auth import now
from aegis_api.db.enums import Completeness, ScanMode, ScanState, Severity
from aegis_api.db.models import (
    APIKey,
    NotificationDelivery,
    Organization,
    OrganizationMember,
    Project,
    Scan,
    ScanPolicy,
    Target,
)
from aegis_api.db.session import database
from aegis_api.settings import get_settings
from sqlalchemy import select


async def main():
    engine, sessions = database(get_settings())
    async with sessions.begin() as db:
        command, identity = sys.argv[1:3]
        if command == "diagnostics":
            deliveries = (await db.scalars(select(NotificationDelivery))).all()
            print(
                json.dumps(
                    {
                        "reporting_enabled": get_settings().reporting_enabled,
                        "deliveries": [
                            {"state": row.state, "attempts": row.attempts}
                            for row in deliveries
                        ],
                    }
                )
            )
        elif command == "reject-invalid-signature":
            request = urllib.request.Request(
                "https://webhook.receiver.test/hook",
                data=b"{}",
                headers={
                    "X-Aegis-Timestamp": str(int(time.time())),
                    "X-Aegis-Signature": "sha256=" + "0" * 64,
                },
            )
            try:
                await asyncio.to_thread(urllib.request.urlopen, request, timeout=10)
            except urllib.error.HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError("Receiver accepted invalid HMAC")
        elif command == "set-key-hash":
            key = await db.get(APIKey, UUID(identity))
            assert len(sys.argv[3]) == 64
            key.key_hash = sys.argv[3]
        elif command == "inspect-key":
            key = await db.get(APIKey, UUID(identity))
            assert key.key_hash == sys.argv[3]
            assert len(key.key_hash) == 64
            assert not any("secret" in c.name for c in APIKey.__table__.columns)
            assert key.last_used_at is not None
            print(json.dumps({"hash_only": True, "usage_recorded": True}))
        elif command == "seed-failure":
            org = await db.get(Organization, UUID(identity))
            member = await db.scalar(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org.id
                )
            )
            project = Project(
                organization_id=org.id,
                name="Explicit synthetic webhook fixture",
                created_by_id=member.id,
            )
            db.add(project)
            await db.flush()
            target = Target(
                organization_id=org.id,
                project_id=project.id,
                canonical_url="https://synthetic.invalid",
                kind="web",
                scope_hosts=["synthetic.invalid"],
                scope_paths=["/"],
            )
            policy = ScanPolicy(
                organization_id=org.id,
                name="Synthetic notification event",
                version=1,
                mode=ScanMode.PASSIVE,
                fail_severity=Severity.HIGH,
                max_duration_seconds=60,
                max_requests=1,
                max_depth=1,
                require_enrichment=False,
                require_report=False,
                allow_waivers=False,
                required_coverage=["passive"],
                schema_version="test-v1",
                rules_snapshot={},
            )
            db.add_all([target, policy])
            await db.flush()
            scan = Scan(
                organization_id=org.id,
                target_id=target.id,
                policy_id=policy.id,
                mode=ScanMode.PASSIVE,
                snapshot_schema_version="test-v1",
                config_snapshot={
                    "synthetic": True,
                    "response_body": "SECRET_BODY_CANARY",
                },
                authorization_snapshot={"synthetic": True},
                authorization_actor_id=member.id,
                authorized_until=now() + timedelta(hours=1),
                authorization_scope_digest="0" * 64,
                deadline_at=now() + timedelta(minutes=1),
                is_demo=True,
                state=ScanState.FAILED,
                completeness=Completeness.PARTIAL,
                finished_at=now(),
            )
            db.add(scan)
        else:
            raise ValueError("Unknown fixture command")
    await engine.dispose()


asyncio.run(main())
