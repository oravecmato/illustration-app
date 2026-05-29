from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Illustration,
    ManualIllustrationSession,
    ManualMessage,
    Run,
    Session,
    SessionMessage,
)


class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self) -> Session:
        s = Session()
        self.session.add(s)
        await self.session.commit()
        await self.session.refresh(s)
        return s

    async def get_session(self, session_id: str) -> Session | None:
        result = await self.session.execute(select(Session).where(Session.id == session_id))
        return result.scalar_one_or_none()

    async def update_session(self, session_obj: Session, **kwargs) -> Session:
        for key, value in kwargs.items():
            setattr(session_obj, key, value)
        session_obj.updated_at = datetime.now(UTC)
        self.session.add(session_obj)
        await self.session.commit()
        await self.session.refresh(session_obj)
        return session_obj

    async def add_message(self, session_id: str, role: str, content: str) -> SessionMessage:
        msg = SessionMessage(session_id=session_id, role=role, content=content)
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def get_messages(self, session_id: str) -> list[SessionMessage]:
        result = await self.session.execute(
            select(SessionMessage)
            .where(SessionMessage.session_id == session_id)
            .order_by(SessionMessage.created_at)
        )
        return list(result.scalars().all())


class RunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(
        self,
        *,
        session_id: str,
        source_language: str,
        topic_short: str,
        story_title: str,
        story_topic_description: str,
        story_blocks_json: str,
        style_guide_json: str,
        illustration_count: int,
        main_character_role: str | None = None,
        environments_json: str | None = None,
        narrative_entities_json: str | None = None,
        id: str | None = None,
    ) -> Run:
        kwargs: dict = dict(
            session_id=session_id,
            source_language=source_language,
            topic_short=topic_short,
            story_title=story_title,
            story_topic_description=story_topic_description,
            story_blocks_json=story_blocks_json,
            style_guide_json=style_guide_json,
            illustration_count=illustration_count,
            main_character_role=main_character_role,
            environments_json=environments_json,
            narrative_entities_json=narrative_entities_json,
        )
        if id is not None:
            kwargs["id"] = id
        run = Run(**kwargs)
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        result = await self.session.execute(select(Run).where(Run.id == run_id))
        return result.scalar_one_or_none()

    async def update_run(self, run: Run, **kwargs) -> Run:
        for key, value in kwargs.items():
            setattr(run, key, value)
        run.updated_at = datetime.now(UTC)
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def create_illustration(
        self,
        run_id: str,
        scene_index: int,
        scene_excerpt: str,
        paragraph_index: int,
        concept: str,
        character_role: str | None,
        contains_entity_label: str | None = None,
        environment_label: str | None = None,
        environment_aspect: str | None = None,
    ) -> Illustration:
        ill = Illustration(
            run_id=run_id,
            scene_index=scene_index,
            scene_excerpt=scene_excerpt,
            paragraph_index=paragraph_index,
            character_role=character_role,
            current_workflow=None,  # Will be set by Agent 1
            initial_concept=concept,
            current_concept=concept,
            contains_entity_label=contains_entity_label,
            environment_label=environment_label,
            environment_aspect=environment_aspect,
        )
        self.session.add(ill)
        await self.session.commit()
        await self.session.refresh(ill)
        return ill

    async def update_illustration(self, illustration: Illustration, **kwargs) -> Illustration:
        for key, value in kwargs.items():
            setattr(illustration, key, value)
        illustration.updated_at = datetime.now(UTC)
        self.session.add(illustration)
        await self.session.commit()
        await self.session.refresh(illustration)
        return illustration

    async def get_illustrations_for_run(self, run_id: str) -> list[Illustration]:
        result = await self.session.execute(
            select(Illustration)
            .where(Illustration.run_id == run_id)
            .order_by(Illustration.scene_index)
        )
        return list(result.scalars().all())

    async def get_illustration(self, illustration_id: str) -> Illustration | None:
        result = await self.session.execute(
            select(Illustration).where(Illustration.id == illustration_id)
        )
        return result.scalar_one_or_none()


class ManualRepository:
    """Persistence for the § 6A manual chat fallback."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_manual_session(self, illustration_id: str) -> ManualIllustrationSession:
        ms = ManualIllustrationSession(illustration_id=illustration_id)
        self.session.add(ms)
        await self.session.commit()
        await self.session.refresh(ms)
        return ms

    async def get_manual_session(self, illustration_id: str) -> ManualIllustrationSession | None:
        result = await self.session.execute(
            select(ManualIllustrationSession).where(
                ManualIllustrationSession.illustration_id == illustration_id
            )
        )
        return result.scalar_one_or_none()

    async def update_manual_session(
        self, ms: ManualIllustrationSession, **kwargs
    ) -> ManualIllustrationSession:
        for key, value in kwargs.items():
            setattr(ms, key, value)
        ms.updated_at = datetime.now(UTC)
        self.session.add(ms)
        await self.session.commit()
        await self.session.refresh(ms)
        return ms

    async def add_message(
        self,
        illustration_id: str,
        role: str,
        content: str,
        image_url: str | None = None,
        manual_attempt_index: int | None = None,
        concept_used: str | None = None,
        positive_prompt: str | None = None,
        negative_prompt: str | None = None,
    ) -> ManualMessage:
        msg = ManualMessage(
            illustration_id=illustration_id,
            role=role,
            content=content,
            image_url=image_url,
            manual_attempt_index=manual_attempt_index,
            concept_used=concept_used,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def get_messages(self, illustration_id: str) -> list[ManualMessage]:
        result = await self.session.execute(
            select(ManualMessage)
            .where(ManualMessage.illustration_id == illustration_id)
            .order_by(ManualMessage.created_at)
        )
        return list(result.scalars().all())

    async def get_image_message(
        self, illustration_id: str, manual_attempt_index: int
    ) -> ManualMessage | None:
        """Look up the image-row for a specific manual attempt."""
        result = await self.session.execute(
            select(ManualMessage)
            .where(ManualMessage.illustration_id == illustration_id)
            .where(ManualMessage.role == "image")
            .where(ManualMessage.manual_attempt_index == manual_attempt_index)
        )
        return result.scalar_one_or_none()
