"""Access-gating dependency + quota lifecycle helpers (§ 8.11).

This module is the single seam between every paid HTTP endpoint and the
``access_keys`` table. Endpoints listed in ``constants.PAID_ENDPOINTS``
mount :func:`require_access_key` as a FastAPI dependency; the
orchestrator / finalize path calls :func:`consume_run_quota` after a
session reaches ``phase="confirmed"``; the orphan-reap path and the
orchestrator failure path both call :func:`refund_run_quota` which is
idempotent under concurrent invocation.

The design assumes a *single backend instance* (the deployment pins
``min_machines_running = 1`` in ``fly.toml`` because the orchestrator
runs in-process). All atomicity guarantees rest on SQLite's
single-writer semantics; no distributed coordination is needed.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ERROR_CODE_ACCESS_KEY_REVOKED,
    ERROR_CODE_MISSING_ACCESS_KEY,
    ERROR_CODE_QUOTA_EXHAUSTED,
)
from app.db.models import AccessKey, Run
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)


# A local copy of the request-scoped session dependency to avoid an
# import cycle through ``app.api.sessions`` / ``app.api.runs``. The
# behaviour is identical to those modules' private ``get_session``.
async def _get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _raise(status_code: int, error_code: str, message: str) -> None:
    """Raise an HTTPException whose body is the JSON object
    ``{"error_code": ..., "detail": ...}``. The frontend
    ``AccessGate.vue`` branches deterministically on ``error_code``."""
    raise HTTPException(
        status_code=status_code,
        detail={"error_code": error_code, "message": message},
    )


async def require_access_key(
    x_access_key: str | None = Header(None, alias="X-Access-Key"),
    session: AsyncSession = Depends(_get_session),  # noqa: B008 - FastAPI Depends
) -> AccessKey:
    """Validate the ``X-Access-Key`` header.

    - Missing header → 401 ``MISSING_ACCESS_KEY``.
    - Unknown key → 401 ``MISSING_ACCESS_KEY`` (do NOT distinguish
      "unknown" from "missing" to keep enumeration cheap and uniform).
    - Revoked key → 403 ``ACCESS_KEY_REVOKED``.
    - Exhausted quota (``runs_used >= runs_allowed`` for a non-admin
      key) → 402 ``QUOTA_EXHAUSTED``. Admin keys
      (``runs_allowed IS NULL``) skip this branch unconditionally.

    On success, the row's ``last_used_at`` is touched and the
    AccessKey ORM object is returned so downstream handlers can attach
    it to the run row at consume time.
    """
    if not x_access_key:
        _raise(401, ERROR_CODE_MISSING_ACCESS_KEY, "Missing X-Access-Key header.")

    result = await session.execute(select(AccessKey).where(AccessKey.key == x_access_key))
    key_row = result.scalar_one_or_none()
    if key_row is None:
        # Same code as missing to avoid confirming key existence to
        # arbitrary callers; the frontend treats both as "show gate".
        _raise(401, ERROR_CODE_MISSING_ACCESS_KEY, "Unknown access key.")

    if key_row.revoked_at is not None:
        _raise(403, ERROR_CODE_ACCESS_KEY_REVOKED, "This access key has been revoked.")

    if key_row.runs_allowed is not None and key_row.runs_used >= key_row.runs_allowed:
        _raise(402, ERROR_CODE_QUOTA_EXHAUSTED, "Run quota exhausted for this access key.")

    # last_used_at is best-effort telemetry; if the request later 5xx's
    # we still want this touched so the admin CLI sees the activity.
    key_row.last_used_at = datetime.now(UTC)
    await session.commit()
    return key_row


class QuotaExhausted(RuntimeError):
    """Raised when an atomic ``consume_run_quota`` loses the
    conditional UPDATE. Indicates that another concurrent request
    consumed the last available slot between the gate and the consume
    call. Callers should map this to HTTP 402 with
    ``QUOTA_EXHAUSTED``."""


async def consume_run_quota(session: AsyncSession, key: str, run_id: str) -> None:
    """Atomically consume one slot from ``access_keys.runs_used``.

    The conditional UPDATE
    ``WHERE key = ? AND (runs_allowed IS NULL OR runs_used < runs_allowed)``
    guarantees that two concurrent finalisations cannot both succeed
    against the same final slot — exactly one will see ``rowcount == 1``;
    the loser raises :class:`QuotaExhausted`.

    The ``run_id`` is currently informational (logged for traceability);
    the Run row does not yet exist at this point in the lifecycle, so
    we cannot stamp ``runs.access_key`` here. :func:`stamp_run_access_key`
    must be called by the finalize background task once Agent 0b has
    created the Run row.

    For admin keys (``runs_allowed IS NULL``) the conditional is
    trivially satisfied, ``runs_used`` increments harmlessly, and the
    same code path is exercised — no parallel admin-only branch.
    """
    stmt = (
        update(AccessKey)
        .where(
            AccessKey.key == key,
            (AccessKey.runs_allowed.is_(None)) | (AccessKey.runs_used < AccessKey.runs_allowed),
        )
        .values(runs_used=AccessKey.runs_used + 1)
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        raise QuotaExhausted(f"access key {key!r} has no remaining run slots")
    await session.commit()
    logger.info("consume_run_quota: key=%s run_id=%s", key[:8] + "...", run_id)


async def stamp_run_access_key(session: AsyncSession, run_id: str, key: str) -> None:
    """Pin the consuming access key onto the Run row.

    Called by the finalize background task immediately after
    ``SessionService.finalize`` has created the Run row, so that the
    Run-anchored refund path (:func:`refund_run_quota`) can locate the
    key later without a session-table hop. Idempotent — a second call
    with the same key is a no-op overwrite.
    """
    await session.execute(update(Run).where(Run.id == run_id).values(access_key=key))
    await session.commit()


async def decrement_runs_used(session: AsyncSession, key: str) -> None:
    """Direct-decrement helper for the pre-Run-row refund path.

    Used by the finalize background task when Agent 0b fails before
    creating the Run row, so :func:`refund_run_quota` (which keys off
    ``runs.quota_refunded``) has nothing to flip against. Clamped at
    zero. NOT idempotent; the caller is responsible for invoking this
    at most once per consumed slot — in practice only the single
    SessionError branch in the background task reaches here.
    """
    from sqlalchemy import func

    await session.execute(
        update(AccessKey)
        .where(AccessKey.key == key)
        .values(runs_used=func.max(AccessKey.runs_used - 1, 0))
    )
    await session.commit()


async def refund_run_quota(session: AsyncSession, run_id: str) -> bool:
    """Refund the run's slot exactly once.

    Returns True if this call performed the refund, False if it was
    already refunded by a concurrent caller (idempotency). The
    conditional ``WHERE quota_refunded = False`` makes the flag-flip
    atomic against SQLite's single-writer lock; the loser sees
    rowcount == 0 and returns False without touching ``runs_used``.

    Used by the orphan reaper and by the orchestrator's terminal
    failure handler when every illustration ended in an infra-noise
    bucket (RENDER_TIMEOUT / OOM_REAPED) or the parent run carries
    ``error_code = INTERNAL_ERROR``. Successful runs MUST NOT call
    this; the slot stays consumed.
    """
    flip_stmt = (
        update(Run)
        .where(Run.id == run_id, Run.quota_refunded.is_(False))
        .values(quota_refunded=True)
    )
    flip_result = await session.execute(flip_stmt)
    if flip_result.rowcount == 0:
        # Either the run does not exist or it was already refunded by
        # a concurrent caller. Either way: nothing to do.
        return False

    # Lookup the consuming key. Done AFTER the flip so we never
    # decrement without owning the refund.
    key_result = await session.execute(select(Run.access_key).where(Run.id == run_id))
    access_key = key_result.scalar_one_or_none()
    if not access_key:
        # Legacy / pre-gating run: no key to refund against. The
        # quota_refunded flag is still set so a retry of this code
        # path is a no-op.
        await session.commit()
        return True

    # Clamp at 0 so a double-refund bug (caught by the flag in
    # production but possible under manual DB edits) never goes negative.
    # SQLite's MAX is available via SQL; use it inside the UPDATE so the
    # whole adjustment is atomic.
    from sqlalchemy import func

    await session.execute(
        update(AccessKey)
        .where(AccessKey.key == access_key)
        .values(runs_used=func.max(AccessKey.runs_used - 1, 0))
    )
    await session.commit()
    return True
