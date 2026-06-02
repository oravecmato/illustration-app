"""Per-session user-message cap (§ 7.2, § 13 AC 20).

``SESSION_USER_MESSAGES_MAX`` (20) bounds how many turns a single
chat session can pay for. The check lives in
``SessionService.post_message`` BEFORE any Anthropic call, so a 21st
user message is refused without spending tokens. Assistant messages
do not count — only ``MessageRole.USER`` rows.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.constants import (
    ERROR_CODE_SESSION_USER_MESSAGE_LIMIT,
    SESSION_USER_MESSAGES_MAX,
)
from app.db.migrations import upgrade_to_head_async
from app.db.models import MessageRole, SessionState
from app.db.repositories import SessionRepository
from app.db.session import get_session_factory, init_db
from app.schemas.claude import ChatResponse
from app.services.session import SessionError, SessionService


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "cap.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await upgrade_to_head_async(url)
    init_db(url)
    return get_session_factory()


def _stub_claude() -> AsyncMock:
    """Return a ClaudeClient stub that satisfies SessionService.chat
    with a minimal gathering-phase reply. Each call returns a fresh
    ChatResponse so we can drive the cap without touching the network."""
    stub = AsyncMock()
    stub.chat = AsyncMock(
        return_value=ChatResponse(
            reply="ok",
            phase="gathering",
            language="sk",
            collected_brief=None,
            topic_short=None,
        )
    )
    return stub


@pytest.mark.asyncio
async def test_user_can_send_max_messages(session_factory):
    """SESSION_USER_MESSAGES_MAX user turns are all accepted; the cap
    is inclusive."""
    factory = session_factory
    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        session = await service.create_session()

    # The fixture's stub returns gathering on every turn, so the
    # session stays in CHATTING.
    for i in range(SESSION_USER_MESSAGES_MAX):
        async with factory() as db:
            repo = SessionRepository(db)
            service = SessionService(repo, _stub_claude())
            await service.post_message(session.id, f"msg {i}")

    # Inspect persisted state.
    async with factory() as db:
        repo = SessionRepository(db)
        msgs = await repo.get_messages(session.id)
    user_msgs = [m for m in msgs if m.role == MessageRole.USER]
    assert len(user_msgs) == SESSION_USER_MESSAGES_MAX


@pytest.mark.asyncio
async def test_user_message_over_cap_rejected(session_factory):
    """The (MAX+1)th user turn raises SessionError with the structured
    code so the API layer can translate it to HTTP 429."""
    factory = session_factory
    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        session = await service.create_session()

    # Pre-seed exactly the maximum number of user messages via the
    # repo so we don't need to chain SessionService through every
    # turn. We also append assistant rows because that's the realistic
    # transcript shape — the cap must NOT count them.
    async with factory() as db:
        repo = SessionRepository(db)
        for i in range(SESSION_USER_MESSAGES_MAX):
            await repo.add_message(session.id, MessageRole.USER, f"u{i}")
            await repo.add_message(session.id, MessageRole.ASSISTANT, f"a{i}")
        # Total messages now far exceeds the user cap but the
        # assistant rows are noise — only user rows count.

    # The next user turn must be rejected.
    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        with pytest.raises(SessionError) as excinfo:
            await service.post_message(session.id, "one too many")

    assert excinfo.value.code == ERROR_CODE_SESSION_USER_MESSAGE_LIMIT


@pytest.mark.asyncio
async def test_assistant_messages_do_not_count(session_factory):
    """A session with mostly assistant rows still accepts new user
    turns as long as the user count is below the cap."""
    from app.constants import SESSION_MAX_MESSAGES

    factory = session_factory
    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        session = await service.create_session()

    # 1 user + (SESSION_MAX_MESSAGES - 3) assistant rows, leaving room
    # for the next user turn AND its assistant reply.
    fill = SESSION_MAX_MESSAGES - 3
    async with factory() as db:
        repo = SessionRepository(db)
        await repo.add_message(session.id, MessageRole.USER, "u0")
        for i in range(fill):
            await repo.add_message(session.id, MessageRole.ASSISTANT, f"a{i}")

    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        # Must NOT raise — user count is still 1, well below 20.
        await service.post_message(session.id, "second user msg")

    async with factory() as db:
        repo = SessionRepository(db)
        msgs = await repo.get_messages(session.id)
    user_msgs = [m for m in msgs if m.role == MessageRole.USER]
    assert len(user_msgs) == 2


@pytest.mark.asyncio
async def test_state_unchanged_when_cap_hit(session_factory):
    """When the cap rejects the request, the session state is NOT
    flipped to FAILED — the user can still start a fresh session and
    the existing one stays browsable in its current chatting state."""
    factory = session_factory
    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        session = await service.create_session()

    async with factory() as db:
        repo = SessionRepository(db)
        for i in range(SESSION_USER_MESSAGES_MAX):
            await repo.add_message(session.id, MessageRole.USER, f"u{i}")

    async with factory() as db:
        repo = SessionRepository(db)
        service = SessionService(repo, _stub_claude())
        with pytest.raises(SessionError):
            await service.post_message(session.id, "blocked")

    async with factory() as db:
        repo = SessionRepository(db)
        s = await repo.get_session(session.id)
    assert s is not None
    assert s.state == SessionState.CHATTING
