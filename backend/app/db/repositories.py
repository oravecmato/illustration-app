from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Illustration, Run, Session, SessionMessage


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
        story_title: str,
        story_blocks_json: str,
        style_guide_json: str,
        illustration_count: int,
    ) -> Run:
        run = Run(
            session_id=session_id,
            story_title=story_title,
            story_blocks_json=story_blocks_json,
            style_guide_json=style_guide_json,
            illustration_count=illustration_count,
        )
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
        character_role: str,
        companion_description: str | None = None,
        companion_interaction: str | None = None,
    ) -> Illustration:
        ill = Illustration(
            run_id=run_id,
            scene_index=scene_index,
            scene_excerpt=scene_excerpt,
            paragraph_index=paragraph_index,
            character_role=character_role,
            initial_concept=concept,
            current_concept=concept,
            companion_description=companion_description,
            companion_interaction=companion_interaction,
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
