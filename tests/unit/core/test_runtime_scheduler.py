from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from xbot.core.timeutils import utc_now
from xbot.messaging.models import Reply
from xbot.runtime.scheduler import Scheduler, enqueue_reply
from xbot.storage.models import Base, ReplyOutboxRecord, RuntimeScheduledJobRecord


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def _reply() -> Reply:
    return Reply(
        platform="qq",
        adapter="qq",
        conversation_id="qq:group:test",
        type="text",
        content="定时公告",
    )


@pytest.mark.asyncio
async def test_outbox_enqueue_is_idempotent_and_marks_sent(session_factory):
    async with session_factory() as session, session.begin():
        first = await enqueue_reply(
            session,
            _reply(),
            idempotency_key="community:test:1",
            source="test",
        )
        repeated = await enqueue_reply(
            session,
            _reply(),
            idempotency_key="community:test:1",
            source="test",
        )

    sent = []

    async def sender(reply):
        sent.append(reply)
        return {"message_id": "platform-1"}

    scheduler = Scheduler(session_factory, sender)
    assert await scheduler.dispatch_outbox_once() == 1

    async with session_factory() as session:
        rows = (await session.execute(select(ReplyOutboxRecord))).scalars().all()
    assert first is True
    assert repeated is False
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].attempt_count == 1
    assert rows[0].platform_message_id == "platform-1"
    assert [item.content for item in sent] == ["定时公告"]


@pytest.mark.asyncio
async def test_outbox_failure_is_persisted_for_retry(session_factory):
    async with session_factory() as session, session.begin():
        await enqueue_reply(
            session,
            _reply(),
            idempotency_key="community:test:failure",
            source="test",
            max_attempts=2,
        )

    async def sender(reply):
        raise RuntimeError("channel unavailable")

    scheduler = Scheduler(session_factory, sender)
    assert await scheduler.dispatch_outbox_once() == 1

    async with session_factory() as session:
        record = await session.scalar(select(ReplyOutboxRecord))
    assert record.status == "failed"
    assert record.attempt_count == 1
    assert record.available_at > utc_now()
    assert "RuntimeError" in record.last_error


@pytest.mark.asyncio
async def test_persistent_job_lease_prevents_second_owner(session_factory):
    async def handler():
        return None

    first = Scheduler(session_factory)
    second = Scheduler(session_factory)
    first.register("community-settlement", interval_seconds=60, handler=handler)
    second.register("community-settlement", interval_seconds=60, handler=handler)
    job = first._jobs["community-settlement"]
    await first._ensure_job(job)

    assert await first._claim_job(job) is True
    assert await second._claim_job(second._jobs["community-settlement"]) is False


@pytest.mark.asyncio
async def test_scheduled_job_result_is_persisted(session_factory):
    calls = []

    async def handler():
        calls.append("ran")

    scheduler = Scheduler(session_factory)
    scheduler.register("community-settlement", interval_seconds=60, handler=handler)
    job = scheduler._jobs["community-settlement"]
    await scheduler._ensure_job(job)
    assert await scheduler._claim_job(job) is True

    await scheduler._execute_job(job)

    async with session_factory() as session:
        record = await session.get(RuntimeScheduledJobRecord, job.name)
    assert calls == ["ran"]
    assert record.last_status == "success"
    assert record.last_finished_at is not None
    assert record.lease_owner is None
    assert record.next_run_at <= utc_now() + timedelta(seconds=60)
