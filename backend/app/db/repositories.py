from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Illustration, Run


class RunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_run(self, story_text: str) -> Run:
        run = Run(story_text=story_text)
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
        concept: str,
        character_role: str,
    ) -> Illustration:
        ill = Illustration(
            run_id=run_id,
            scene_index=scene_index,
            scene_excerpt=scene_excerpt,
            character_role=character_role,
            initial_concept=concept,
            current_concept=concept,
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
