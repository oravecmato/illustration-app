"""FastAPI application: CORS, routers, startup."""

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import illustrations as illustrations_api
from app.api import runs as runs_api
from app.api import sessions as sessions_api
from app.config import Settings, get_settings
from app.db.migrations import upgrade_to_head_async
from app.db.session import init_db
from app.services.character_config import CharacterConfigError, load_character_config
from app.services.claude import ClaudeClient, ClaudeError, load_agent_prompts
from app.services.runpod import RunPodClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_relative_path(path: str) -> str:
    """Resolve a path relative to the project's ``backend/`` root."""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", path))


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Apply any pending Alembic migrations before serving traffic.
        await upgrade_to_head_async(settings.database_url)
        init_db(settings.database_url)

        os.makedirs(settings.output_dir, exist_ok=True)

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
            api_key=settings.anthropic_api_key, agent_prompts=agent_prompts
        )
        runpod_client = RunPodClient(
            api_key=settings.runpod_api_key,
            endpoint_id=settings.runpod_endpoint_id,
        )

        runs_api.set_clients(
            claude=claude_client,
            runpod=runpod_client,
            workflow=workflow_template,
            output_dir=settings.output_dir,
            character_config=character_config,
        )

        yield

    app = FastAPI(title="Anime Illustrator", lifespan=lifespan)

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
