"""Unit tests for the access-key consume/refund lifecycle (§ 8.11).

Covers the four primitives in ``app/api/auth.py`` that bookend every
paid request:

- :func:`consume_run_quota` — atomic conditional UPDATE that
  guarantees a finite-quota key cannot oversubscribe even under
  concurrent finalisations.
- :func:`refund_run_quota` — idempotent flag-flip on ``runs`` so the
  orphan reaper and the orchestrator's terminal failure handler can
  both call it without double-decrementing.
- :func:`decrement_runs_used` — direct decrement helper used on the
  pre-Run-row failure path; clamped at zero.
- :func:`stamp_run_access_key` — pins the consuming key onto the Run
  row so :func:`refund_run_quota` can find it later.

All tests run against a fresh in-process SQLite file so the atomicity
guarantees that hold in production (single-writer lock) hold here too.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.api.auth import (
    QuotaExhausted,
    consume_run_quota,
    decrement_runs_used,
    refund_run_quota,
    stamp_run_access_key,
)
from app.db.migrations import upgrade_to_head_async
from app.db.models import AccessKey, Run, RunStatus
from app.db.session import get_session_factory, init_db


@pytest.fixture
async def db_factory(tmp_path):
    db_path = tmp_path / "auth.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await upgrade_to_head_async(url)
    init_db(url)
    return get_session_factory()


async def _make_key(factory, *, key: str, allowed: int | None, used: int = 0) -> None:
    async with factory() as session:
        session.add(
            AccessKey(
                key=key,
                label="test",
                runs_allowed=allowed,
                runs_used=used,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def _make_run(factory, *, run_id: str, access_key: str | None) -> None:
    # Insert a parent session row first to satisfy the FK on runs.session_id.
    from app.db.models import Session as SessionModel

    async with factory() as session:
        sess = SessionModel()
        session.add(sess)
        await session.commit()
        await session.refresh(sess)

        session.add(
            Run(
                id=run_id,
                session_id=sess.id,
                status=RunStatus.RUNNING,
                source_language="sk",
                topic_short="t",
                story_title="t",
                story_topic_description="t",
                story_blocks_json="[]",
                style_guide_json="{}",
                access_key=access_key,
                quota_refunded=False,
            )
        )
        await session.commit()


async def _get_key(factory, key: str) -> AccessKey:
    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(select(AccessKey).where(AccessKey.key == key))
        return result.scalar_one()


async def _get_run(factory, run_id: str) -> Run:
    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(select(Run).where(Run.id == run_id))
        return result.scalar_one()


# ── consume_run_quota ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_increments_runs_used(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=0)

    async with factory() as session:
        await consume_run_quota(session, "k1", run_id="run-a")

    row = await _get_key(factory, "k1")
    assert row.runs_used == 1


@pytest.mark.asyncio
async def test_consume_admin_key_always_succeeds(db_factory):
    factory = db_factory
    # Admin keys have runs_allowed=None and should bypass the quota cap.
    await _make_key(factory, key="admin", allowed=None, used=100)

    async with factory() as session:
        await consume_run_quota(session, "admin", run_id="run-a")
        await consume_run_quota(session, "admin", run_id="run-b")

    row = await _get_key(factory, "admin")
    assert row.runs_used == 102


@pytest.mark.asyncio
async def test_consume_raises_when_exhausted(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=2, used=2)

    async with factory() as session:
        with pytest.raises(QuotaExhausted):
            await consume_run_quota(session, "k1", run_id="run-a")

    # No mutation on the loser.
    row = await _get_key(factory, "k1")
    assert row.runs_used == 2


@pytest.mark.asyncio
async def test_consume_stops_exactly_at_cap(db_factory):
    factory = db_factory
    # 2 of 3 slots used; the third consume succeeds, the fourth fails.
    await _make_key(factory, key="k1", allowed=3, used=2)

    async with factory() as session:
        await consume_run_quota(session, "k1", run_id="run-a")

    row = await _get_key(factory, "k1")
    assert row.runs_used == 3

    async with factory() as session:
        with pytest.raises(QuotaExhausted):
            await consume_run_quota(session, "k1", run_id="run-b")


# ── stamp_run_access_key ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stamp_writes_access_key(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=1)
    await _make_run(factory, run_id="run-a", access_key=None)

    async with factory() as session:
        await stamp_run_access_key(session, "run-a", "k1")

    run = await _get_run(factory, "run-a")
    assert run.access_key == "k1"


# ── refund_run_quota ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refund_decrements_runs_used(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=2)
    await _make_run(factory, run_id="run-a", access_key="k1")

    async with factory() as session:
        ok = await refund_run_quota(session, "run-a")
    assert ok is True

    row = await _get_key(factory, "k1")
    assert row.runs_used == 1
    run = await _get_run(factory, "run-a")
    assert run.quota_refunded is True


@pytest.mark.asyncio
async def test_refund_is_idempotent(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=2)
    await _make_run(factory, run_id="run-a", access_key="k1")

    async with factory() as session:
        first = await refund_run_quota(session, "run-a")
    async with factory() as session:
        second = await refund_run_quota(session, "run-a")

    assert first is True
    assert second is False
    # Only one decrement applied.
    row = await _get_key(factory, "k1")
    assert row.runs_used == 1


@pytest.mark.asyncio
async def test_refund_clamps_at_zero(db_factory):
    factory = db_factory
    # Edge case: refund a run when the key's runs_used is already 0
    # (could happen under manual DB edits). MAX(runs_used - 1, 0) must
    # not produce a negative number.
    await _make_key(factory, key="k1", allowed=3, used=0)
    await _make_run(factory, run_id="run-a", access_key="k1")

    async with factory() as session:
        ok = await refund_run_quota(session, "run-a")
    assert ok is True

    row = await _get_key(factory, "k1")
    assert row.runs_used == 0


@pytest.mark.asyncio
async def test_refund_returns_false_for_unknown_run(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=2)

    async with factory() as session:
        ok = await refund_run_quota(session, "no-such-run")
    assert ok is False

    row = await _get_key(factory, "k1")
    assert row.runs_used == 2


@pytest.mark.asyncio
async def test_refund_without_access_key_is_no_op(db_factory):
    factory = db_factory
    # Legacy run created before gating: refund must still flip the flag
    # so future calls are no-ops, but must not touch any key.
    await _make_key(factory, key="k1", allowed=3, used=2)
    await _make_run(factory, run_id="legacy", access_key=None)

    async with factory() as session:
        ok = await refund_run_quota(session, "legacy")
    assert ok is True

    row = await _get_key(factory, "k1")
    assert row.runs_used == 2
    run = await _get_run(factory, "legacy")
    assert run.quota_refunded is True


# ── decrement_runs_used ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decrement_runs_used_decrements(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=2)

    async with factory() as session:
        await decrement_runs_used(session, "k1")

    row = await _get_key(factory, "k1")
    assert row.runs_used == 1


@pytest.mark.asyncio
async def test_decrement_runs_used_clamps_at_zero(db_factory):
    factory = db_factory
    await _make_key(factory, key="k1", allowed=3, used=0)

    async with factory() as session:
        await decrement_runs_used(session, "k1")

    row = await _get_key(factory, "k1")
    assert row.runs_used == 0
