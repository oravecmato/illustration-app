"""FastAPI application: CORS, routers, startup."""

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from app.api import illustrations as illustrations_api
from app.api import runs as runs_api
from app.api import sessions as sessions_api
from app.config import Settings, get_settings
from app.db.migrations import upgrade_to_head_async
from app.db.models import Illustration, IllustrationState, Run, RunStatus
from app.db.session import get_session_factory, init_db
from app.services.character_config import CharacterConfigError, load_character_config
from app.services.claude import (
    ClaudeClient,
    ClaudeError,
    load_agent_prompts,
    load_reference_docs,
)
from app.services.runpod import RunPodClient
from app.services.storage import ConfigurationError, get_image_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_relative_path(path: str) -> str:
    """Resolve a path relative to the project's ``backend/`` root."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", path))


_NON_TERMINAL_ILLUSTRATION_STATES = tuple(
    s
    for s in IllustrationState
    if s
    not in (
        IllustrationState.COMPLETED,
        IllustrationState.FAILED,
        IllustrationState.CANCELLED,
    )
)


async def _reap_orphan_runs() -> None:
    """Mark RUNNING runs (and their non-terminal illustrations) as FAILED.

    The auto-pipeline orchestrator lives in-process and does NOT survive a
    process restart, so any run found in RUNNING state at startup belongs to a
    previous process and can never make progress. We fail them deterministically
    so the UI shows the correct terminal state instead of an infinite spinner.

    Scope of illustration reap is limited to children of the reaped runs:
    illustrations in MANUAL_* / SALVAGE_REVIEW under an already-terminal parent
    run are legitimate resumable user state and must NOT be touched.
    """
    session_factory = get_session_factory()
    async with session_factory() as s:
        orphan_run_ids = (
            (await s.execute(select(Run.id).where(Run.status == RunStatus.RUNNING))).scalars().all()
        )
        if not orphan_run_ids:
            return

        await s.execute(
            update(Run)
            .where(Run.id.in_(orphan_run_ids))
            .values(
                status=RunStatus.FAILED,
                error_code="INTERNAL_ERROR",
                error_message="Run orphaned by server restart",
            )
        )
        ill_result = await s.execute(
            update(Illustration)
            .where(
                Illustration.run_id.in_(orphan_run_ids),
                Illustration.state.in_(_NON_TERMINAL_ILLUSTRATION_STATES),
            )
            .values(state=IllustrationState.FAILED)
        )
        await s.commit()
        logger.warning(
            "Startup reap: %d orphan run(s), %d orphan illustration(s) → FAILED",
            len(orphan_run_ids),
            ill_result.rowcount,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Apply any pending Alembic migrations before serving traffic.
        await upgrade_to_head_async(settings.database_url)
        init_db(settings.database_url)

        # Reap orphaned runs left in RUNNING state by a previous process
        # (e.g. uvicorn killed mid-pipeline). The in-process orchestrator
        # doesn't survive restarts, so these would otherwise hang forever.
        # See MEMORY.md → "Orphan RUNNING runs".
        await _reap_orphan_runs()

        # Construct the configured image-store backend. With the local
        # backend this is a no-op wrapper around `output_dir`; with `r2`
        # it validates the credential block and raises ConfigurationError
        # before any traffic is served. `output_dir` is still touched here
        # because the `/static` mount below depends on it existing even
        # when no images are ever written there (R2 deploys).
        os.makedirs(settings.output_dir, exist_ok=True)
        try:
            image_store = get_image_store(settings)
        except ConfigurationError as e:
            logger.error("Startup failed: %s", e)
            raise

        # Load character_config.json — refuse to start if missing or malformed
        char_config_path = os.path.join(os.path.dirname(__file__), "character_config.json")
        try:
            character_config = load_character_config(char_config_path)
        except CharacterConfigError as e:
            logger.error("Startup failed: %s", e)
            raise

        # Load agent system prompts from .md files — refuse to start if any
        # are missing or empty.
        agents_dir = _resolve_relative_path(settings.agents_dir)
        try:
            agent_prompts = load_agent_prompts(agents_dir)
            reference_docs = load_reference_docs(agents_dir)
        except ClaudeError as e:
            logger.error("Startup failed: %s", e)
            raise

        # Load workflow template
        workflow_path = _resolve_relative_path(settings.workflow_path)
        if os.path.exists(workflow_path):
            with open(workflow_path) as f:
                workflow_template = json.load(f)
        else:
            logger.warning("Workflow file not found at %s, using empty template", workflow_path)
            workflow_template = {}

        claude_client = ClaudeClient(
            api_key=settings.anthropic_api_key,
            agent_prompts=agent_prompts,
            reference_docs=reference_docs,
        )
        runpod_client = RunPodClient(
            api_key=settings.runpod_api_key,
            endpoint_id=settings.runpod_endpoint_id,
        )

        runs_api.set_clients(
            claude=claude_client,
            runpod=runpod_client,
            workflow=workflow_template,
            image_store=image_store,
            character_config=character_config,
        )

        yield

    app = FastAPI(title="Anime Illustrator", lifespan=lifespan)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        # Cheap liveness probe for Fly health checks + the Docker HEALTHCHECK.
        # Intentionally does NOT touch the DB or external APIs — those have
        # their own retry/timeout semantics inside request handlers.
        return {"status": "ok"}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.allowed_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files for generated images
    os.makedirs(settings.output_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=settings.output_dir), name="static")

    app.include_router(sessions_api.router)
    app.include_router(runs_api.router)
    app.include_router(illustrations_api.router)

    return app


try:
    app = create_app()
except Exception as _startup_err:
    import sys

    print(f"ERROR: Could not start application: {_startup_err}", file=sys.stderr)
    raise
