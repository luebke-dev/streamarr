import uuid
from datetime import UTC, datetime, timedelta

import pytest

from streamarr.models.activity_log import ActivityLog
from streamarr.workers.library_scan_worker import _scan_is_due


@pytest.mark.asyncio
async def test_scan_due_uses_existing_activity_log(db_session):
    library_guid = uuid.uuid4()
    assert await _scan_is_due(db_session, library_guid, 12) is True

    db_session.add(
        ActivityLog(
            event_type="library.scan",
            message="scan",
            entity_type="library",
            entity_guid=library_guid,
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    assert await _scan_is_due(db_session, library_guid, 12) is False


@pytest.mark.asyncio
async def test_failed_scan_does_not_delay_next_attempt(db_session):
    library_guid = uuid.uuid4()
    db_session.add(
        ActivityLog(
            event_type="library.scan_failed",
            message="failed",
            severity="error",
            entity_type="library",
            entity_guid=library_guid,
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    assert await _scan_is_due(db_session, library_guid, 12) is True
