"""Backend integration tests (§11.2).

Anthropic and RunPod are mocked at the HTTP layer (respx).
SQLite uses a temporary file per test.
"""

import asyncio
import base64
import json
import os
import uuid

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.api import runs as runs_api
from app.config import Settings
from app.constants import CONFIRMED_ACK, MANUAL_ITERATE_PROMPT
from app.db.migrations import upgrade_to_head_async
from app.db.models import (
    AccessKey,
    Illustration,
    IllustrationState,
    ManualIllustrationSession,
    ManualMessage,
    ManualMessageRole,
    Run,
    RunStatus,
)
from app.db.models import Session as SessionModel
from app.db.session import get_session_factory, init_db
from app.main import create_app
from app.services.character_config import load_character_config
from app.services.claude import ClaudeClient, load_agent_prompts, load_reference_docs
from app.services.runpod import RunPodClient
from app.services.storage import LocalImageStore

IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()
ENDPOINT_ID = "test-endpoint"
RUNPOD_BASE = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
ANTHROPIC_BASE = "https://api.anthropic.com/v1/messages"

RUNPOD_JOB_ID = "rp-job-12345"

BRIEF = {
    "characters": [
        {
            "role": "female",
            "name_in_story": "Mia",
            "short_description": "A determined young woman",
        }
    ],
    "topic": "A short story about overcoming stage fright.",
    "notes": "Warm tone, gentle ending.",
    "main_character_role": "female",
}

STORY_BLOCKS = [
    {"type": "paragraph", "text": "Stála pri okne a hlboko sa nadýchla."},
    {"type": "illustration", "scene_index": 0},
    {"type": "paragraph", "text": "Sadla si a zviazala si vlasy do drdolu."},
    {"type": "illustration", "scene_index": 1},
    {"type": "paragraph", "text": "Pred zrkadlom si upravila kostým a usmiala sa."},
    {"type": "illustration", "scene_index": 2},
    {"type": "paragraph", "text": "Potom otvorila dvere a vyšla na pódium."},
    {"type": "illustration", "scene_index": 3},
    {"type": "paragraph", "text": "Tlieskanie ju objalo ako vlna."},
    {"type": "illustration", "scene_index": 4},
    {"type": "paragraph", "text": "Cestou domov ešte stále počula ten potlesk."},
]

BUILD_STORY_RESULT = {
    "story_title": "Prvý krok na pódium",
    "story_topic_description": "Príbeh o prekonaní trému",
    "story_blocks": STORY_BLOCKS,
    "style_guide": {
        "overall_style_positive": "anime, mha style, soft shading",
        "overall_style_negative": "photorealistic",
        "character_lora": "",
        "character_baseline_description": "Warm afternoon lighting.",
    },
    "illustrations": [
        {
            "scene_index": 0,
            "scene_excerpt": "Stála pri okne a hlboko sa nadýchla.",
            "concept": "young woman at window, eyes closed, deep breath",
            "character_role": "female",
        },
        {
            "scene_index": 1,
            "scene_excerpt": "Sadla si a zviazala si vlasy do drdolu.",
            "concept": "young woman tying her hair into a bun, focused",
            "character_role": "female",
        },
        {
            "scene_index": 2,
            "scene_excerpt": "Pred zrkadlom si upravila kostým a usmiala sa.",
            "concept": "young woman adjusting her costume in front of a mirror, gentle smile",
            "character_role": "female",
        },
        {
            "scene_index": 3,
            "scene_excerpt": "Potom otvorila dvere a vyšla na pódium.",
            "concept": "young woman pushing open a door, determined expression",
            "character_role": "female",
        },
        {
            "scene_index": 4,
            "scene_excerpt": "Tlieskanie ju objalo ako vlna.",
            "concept": "young woman on stage taking a bow, eyes shining",
            "character_role": "female",
        },
    ],
    "environments": [
        {"label": "obývačka", "kind": "indoor", "aspect": "single"},
        {"label": "spálňa", "kind": "indoor", "aspect": "single"},
        {"label": "šatňa pred zrkadlom", "kind": "indoor", "aspect": "single"},
        {"label": "zákulisie", "kind": "indoor", "aspect": "single"},
        {"label": "javisko", "kind": "indoor", "aspect": "single"},
    ],
    "reserved_entities": [],
}


def _wrap(payload: dict) -> dict:
    """Wrap a JSON payload as an Anthropic Messages API response body."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 50, "output_tokens": 50},
    }


def _classify(request) -> str:
    """Identify which agent is being called from the request payload."""
    body = json.loads(request.content)
    system = body.get("system", "")
    if isinstance(system, list):
        system = " ".join(s.get("text", "") for s in system if isinstance(s, dict))

    # Check for image content first — only evaluate sends images.
    messages = body.get("messages", [])
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "image":
                    return "evaluate"

    if "Agent 0a" in system:
        return "chat"
    if "Agent 0b" in system:
        return "build_story"
    if "ComfyUI Danbooru-tag prompt engineer" in system:
        return "prompt_engineer"
    if "quality-control evaluator" in system:
        return "evaluate"
    if "creative concept writer" in system:
        return "rethink"
    return "unknown"


def make_settings(db_path: str, output_dir: str) -> Settings:
    return Settings(
        anthropic_api_key="test-anthropic-key",
        runpod_api_key="test-runpod-key",
        runpod_endpoint_id=ENDPOINT_ID,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        output_dir=output_dir,
        workflow_path="./app/workflows/default.json",
        agents_dir="./app/agents",
        allowed_origin="http://localhost:5173",
    )


@pytest.fixture
async def app_client(tmp_path):
    db_file = str(tmp_path / "test.db")
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)

    settings = make_settings(db_file, output_dir)

    # Manually boot the app components (bypassing lifespan for tests).
    # Schema is applied via Alembic to exercise the same DDL path as
    # production.
    await upgrade_to_head_async(settings.database_url)
    init_db(settings.database_url)

    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    agents_dir = os.path.join(backend_root, "app", "agents")
    agent_prompts = load_agent_prompts(agents_dir)
    reference_docs = load_reference_docs(agents_dir)

    claude_client = ClaudeClient(
        api_key=settings.anthropic_api_key,
        agent_prompts=agent_prompts,
        reference_docs=reference_docs,
    )
    runpod_client = RunPodClient(
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
    )
    workflow_path = os.path.join(backend_root, "app", "workflows", "default.json")
    with open(workflow_path) as f:
        workflow_template = json.load(f)

    char_config_path = os.path.join(backend_root, "app", "character_config.json")
    character_config = load_character_config(char_config_path)

    runs_api.set_clients(
        claude=claude_client,
        runpod=runpod_client,
        workflow=workflow_template,
        image_store=LocalImageStore(output_dir),
        character_config=character_config,
    )

    # Seed an admin access key so every paid endpoint passes the gate
    # uniformly. The integration tests exercise functional behaviour
    # downstream of authentication — the gating itself is covered in
    # dedicated unit/integration tests.
    factory = get_session_factory()
    async with factory() as db:
        db.add(AccessKey(key="test-admin-key", label="test", runs_allowed=None, runs_used=0))
        await db.commit()

    app = create_app(settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Access-Key": "test-admin-key"},
    ) as client:
        yield client, settings


def _install_anthropic_router(chat_responses: list[dict], build_story_response: dict) -> None:
    """Install a respx route on Anthropic that dispatches per agent.

    Chat calls are consumed in order from ``chat_responses``. Build-story
    returns the single ``build_story_response``. Prompt and evaluate are
    canned per call.
    """
    chat_iter = iter(chat_responses)

    def handler(request):
        kind = _classify(request)
        if kind == "chat":
            try:
                return httpx.Response(200, json=_wrap(next(chat_iter)))
            except StopIteration:
                return httpx.Response(500, json={"error": "unexpected extra chat call"})
        if kind == "build_story":
            return httpx.Response(200, json=_wrap(build_story_response))
        if kind == "prompt_engineer":
            return httpx.Response(
                200,
                json=_wrap(
                    {
                        "workflow": "single-lora",
                        "positive": "1girl, jirou kyouka, school uniform, determined, indoors",
                        "negative": (
                            "nsfw, suggestive, revealing clothing, lingerie, nudity, "
                            "cleavage, underwear, sexualized, bad anatomy, extra fingers, "
                            "missing fingers, fused fingers, malformed hands, extra limbs, "
                            "distorted face, asymmetric eyes, low quality, blurry, watermark, "
                            "signature, text, jpeg artifacts, multiple characters, crowd, "
                            "two girls, two boys, 2girls, 2boys, group, ear jacks, "
                            "earphone jack, headphone jack, jack plug, mechanical ears"
                        ),
                    }
                ),
            )
        if kind == "evaluate":
            return httpx.Response(
                200,
                json=_wrap(
                    {
                        "ok": True,
                        "problem": None,
                        "reasoning": "Looks good.",
                        "suggestion": "",
                    }
                ),
            )
        if kind == "rethink":
            return httpx.Response(
                200,
                json=_wrap({"concept": "different approach to the same moment"}),
            )
        return httpx.Response(500, json={"error": f"unhandled agent: {kind}"})

    respx.post(ANTHROPIC_BASE).mock(side_effect=handler)


async def _wait_terminal(client: AsyncClient, run_id: str) -> dict:
    for _ in range(60):
        await asyncio.sleep(0.2)
        resp = await client.get(f"/api/runs/{run_id}")
        if resp.status_code != 200:
            continue
        data = resp.json()
        if data["run"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return data
    final = await client.get(f"/api/runs/{run_id}")
    return final.json()


@pytest.mark.asyncio
@respx.mock
async def test_end_to_end_happy_path(app_client):
    """Session → chat (awaiting → confirmed) → messages returns run_id → pipeline COMPLETED."""
    client, _ = app_client

    chat_responses = [
        {
            "reply": "Skvele. Súhlasíš s týmto plánom?",
            "phase": "awaiting_confirmation",
            "language": "sk",
            "collected_brief": BRIEF,
        },
        {
            "reply": "Pripravujem príbeh a ilustrácie...",
            "phase": "confirmed",
            "language": "sk",
            "topic_short": "Prekonanie trému",
            "collected_brief": BRIEF,
        },
    ]
    _install_anthropic_router(chat_responses, BUILD_STORY_RESULT)

    respx.post(f"{RUNPOD_BASE}/run").mock(
        return_value=httpx.Response(200, json={"id": RUNPOD_JOB_ID})
    )
    respx.get(f"{RUNPOD_BASE}/status/{RUNPOD_JOB_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "images": [{"filename": "scene.png", "type": "base64", "data": IMAGE_B64}]
                },
            },
        )
    )

    # 1. Create session — no messages initially (welcome is frontend-only), state CHATTING
    resp = await client.post("/api/sessions")
    assert resp.status_code == 201
    session = resp.json()
    session_id = session["id"]
    assert session["state"] == "CHATTING"
    assert len(session["messages"]) == 0  # Welcome message is frontend-only for i18n

    # 2. Post first user message → Claude chat returns awaiting_confirmation
    resp = await client.post(
        f"/api/sessions/{session_id}/messages",
        json={"content": "Chcem krátky príbeh o dievčati, ktoré prekoná trému."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phase"] == "awaiting_confirmation"
    assert body["session"]["state"] == "AWAITING_CONFIRMATION"
    assert body["session"]["collected_brief"] is not None

    # 3. User confirms → phase = confirmed; server must normalise the
    #    assistant reply to the canonical CONFIRMED_ACK_SK constant
    #    regardless of what the agent returned in `reply`. The last
    #    message in the session transcript is the assistant's confirmed
    #    acknowledgement.
    resp = await client.post(f"/api/sessions/{session_id}/messages", json={"content": "áno"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "confirmed"
    last_msg = body["session"]["messages"][-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["content"] == CONFIRMED_ACK["sk"]

    # 4. The messages endpoint pre-allocated a run_id and scheduled
    #    Agent 0b + the pipeline as a background task. No separate
    #    finalize call.
    run_id = body["run_id"]
    assert run_id is not None
    assert body["session"]["run_id"] == run_id

    # 5. Pipeline runs to completion
    data = await _wait_terminal(client, run_id)
    assert data["run"]["status"] == "COMPLETED", data
    assert data["run"]["completed_count"] == 5
    assert data["run"]["story_title"] == "Prvý krok na pódium"
    assert len(data["illustrations"]) == 5


@pytest.mark.asyncio
async def test_post_message_returns_400_on_empty(app_client):
    client, _ = app_client
    resp = await client.post("/api/sessions")
    session_id = resp.json()["id"]

    resp = await client.post(f"/api/sessions/{session_id}/messages", json={"content": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_message_returns_400_on_too_long(app_client):
    client, _ = app_client
    resp = await client.post("/api/sessions")
    session_id = resp.json()["id"]

    resp = await client.post(f"/api/sessions/{session_id}/messages", json={"content": "x" * 5000})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_session_returns_404_for_unknown(app_client):
    client, _ = app_client
    resp = await client.get(f"/api/sessions/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_returns_404_for_unknown(app_client):
    client, _ = app_client
    resp = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_cancel_active_run(app_client):
    """Cancel a run that's still RUNNING returns 200."""
    client, _ = app_client

    chat_responses = [
        {
            "reply": "Súhlasíš?",
            "phase": "awaiting_confirmation",
            "collected_brief": BRIEF,
        },
        {
            "reply": "Pripravujem...",
            "phase": "confirmed",
            "collected_brief": BRIEF,
            "topic_short": "Príbeh",
        },
    ]
    _install_anthropic_router(chat_responses, BUILD_STORY_RESULT)

    # Make RunPod hang in IN_PROGRESS so the run stays active long enough to cancel.
    respx.post(f"{RUNPOD_BASE}/run").mock(
        return_value=httpx.Response(200, json={"id": RUNPOD_JOB_ID})
    )
    respx.get(f"{RUNPOD_BASE}/status/{RUNPOD_JOB_ID}").mock(
        return_value=httpx.Response(200, json={"status": "IN_PROGRESS"})
    )

    resp = await client.post("/api/sessions")
    session_id = resp.json()["id"]
    await client.post(
        f"/api/sessions/{session_id}/messages", json={"content": "Príbeh o dievčati."}
    )
    resp = await client.post(f"/api/sessions/{session_id}/messages", json={"content": "áno"})
    body = resp.json()
    assert body["phase"] == "confirmed"
    run_id = body["run_id"]
    assert run_id is not None

    # Wait briefly for the background task to create the run row so cancel
    # can find it. The pipeline polls RunPod which keeps the run RUNNING.
    for _ in range(50):
        get_resp = await client.get(f"/api/runs/{run_id}")
        if get_resp.status_code == 200:
            break
        await asyncio.sleep(0.05)

    cancel_resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code in (200, 409)


# ── § 6A.10 Manual image card endpoints ──────────────────────────────────────

MANUAL_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


async def _seed_manual_illustration(
    *,
    settings: Settings,
    attempts: int = 1,
    write_files: bool = True,
    state: IllustrationState = IllustrationState.MANUAL_CHATTING,
    error_message: str | None = None,
) -> tuple[str, str, str]:
    """Seed a MANUAL_CHATTING illustration with N image-row attempts.

    Returns ``(run_id, illustration_id, run_output_subdir)``.
    """
    factory = get_session_factory()
    async with factory() as db:
        sess = SessionModel()
        db.add(sess)
        await db.flush()
        run = Run(
            session_id=sess.id,
            status=RunStatus.RUNNING,
            source_language="sk",
            topic_short="Test",
            story_title="Test Story",
            story_topic_description="A test",
            story_blocks_json=json.dumps([{"type": "paragraph", "text": "Once."}]),
            style_guide_json=json.dumps(
                {
                    "overall_style_positive": "anime",
                    "overall_style_negative": "blurry",
                    "character_lora": "",
                    "character_baseline_description": "",
                }
            ),
            illustration_count=1,
        )
        db.add(run)
        await db.flush()
        ill = Illustration(
            run_id=run.id,
            scene_index=0,
            scene_excerpt="Once.",
            paragraph_index=0,
            character_role="female",
            initial_concept="A girl on a stage",
            current_concept="A girl on a stage",
            state=state,
            manual_attempts=attempts,
            error_message=error_message,
        )
        db.add(ill)
        await db.flush()
        ms = ManualIllustrationSession(
            illustration_id=ill.id,
            sub_phase="feedback_gathering",
            last_agreed_concept="A girl on a stage",
            last_manual_image_path=f"runs/{run.id}/manual_0_{attempts}.png",
        )
        db.add(ms)
        for k in range(1, attempts + 1):
            db.add(
                ManualMessage(
                    illustration_id=ill.id,
                    role=ManualMessageRole.IMAGE,
                    content="",
                    image_url=f"/static/runs/{run.id}/manual_0_{k}.png",
                    manual_attempt_index=k,
                    concept_used="A girl on a stage",
                    positive_prompt="brave girl, stage",
                    negative_prompt="blurry",
                )
            )
        await db.commit()
        run_id, ill_id = run.id, ill.id

    if write_files:
        run_dir = os.path.join(settings.output_dir, "runs", run_id)
        os.makedirs(run_dir, exist_ok=True)
        for k in range(1, attempts + 1):
            with open(os.path.join(run_dir, f"manual_0_{k}.png"), "wb") as f:
                f.write(MANUAL_PNG)
    return run_id, ill_id, f"runs/{run_id}"


@pytest.mark.asyncio
async def test_accept_attempt_promotes_latest(app_client):
    client, settings = app_client
    _, ill_id, run_subdir = await _seed_manual_illustration(settings=settings, attempts=1)

    resp = await client.post(
        f"/api/illustrations/{ill_id}/accept", json={"manual_attempt_index": 1}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == IllustrationState.COMPLETED
    canonical = os.path.join(settings.output_dir, run_subdir, "scene_0.png")
    assert os.path.exists(canonical)


@pytest.mark.asyncio
async def test_accept_attempt_promotes_older(app_client):
    client, settings = app_client
    _, ill_id, run_subdir = await _seed_manual_illustration(settings=settings, attempts=3)

    resp = await client.post(
        f"/api/illustrations/{ill_id}/accept", json={"manual_attempt_index": 1}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == IllustrationState.COMPLETED
    canonical = os.path.join(settings.output_dir, run_subdir, "scene_0.png")
    assert os.path.exists(canonical)


@pytest.mark.asyncio
async def test_accept_attempt_bad_index_returns_404(app_client):
    client, settings = app_client
    _, ill_id, _ = await _seed_manual_illustration(settings=settings, attempts=1)

    resp = await client.post(
        f"/api/illustrations/{ill_id}/accept", json={"manual_attempt_index": 9}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_accept_attempt_missing_file_returns_410(app_client):
    client, settings = app_client
    _, ill_id, _ = await _seed_manual_illustration(settings=settings, attempts=1, write_files=False)

    resp = await client.post(
        f"/api/illustrations/{ill_id}/accept", json={"manual_attempt_index": 1}
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_accept_attempt_from_failed_state(app_client):
    """§ 6A.10 post-exhaustion recovery: FAILED illustrations can be
    healed by promoting a prior attempt to canonical."""
    client, settings = app_client
    _, ill_id, run_subdir = await _seed_manual_illustration(
        settings=settings,
        attempts=5,
        state=IllustrationState.FAILED,
        error_message="Manual attempts exhausted",
    )

    resp = await client.post(
        f"/api/illustrations/{ill_id}/accept", json={"manual_attempt_index": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == IllustrationState.COMPLETED
    canonical = os.path.join(settings.output_dir, run_subdir, "scene_0.png")
    assert os.path.exists(canonical)


@pytest.mark.asyncio
async def test_manual_iterate_appends_localized_bubble(app_client):
    client, settings = app_client
    _, ill_id, _ = await _seed_manual_illustration(settings=settings, attempts=1)

    resp = await client.post(f"/api/illustrations/{ill_id}/manual/iterate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Last message is the localized iterate prompt (Slovak).
    last = body["messages"][-1]
    assert last["role"] == ManualMessageRole.ASSISTANT
    assert last["content"] == MANUAL_ITERATE_PROMPT["sk"]


@pytest.mark.asyncio
async def test_manual_iterate_is_idempotent(app_client):
    client, settings = app_client
    _, ill_id, _ = await _seed_manual_illustration(settings=settings, attempts=1)

    first = await client.post(f"/api/illustrations/{ill_id}/manual/iterate")
    assert first.status_code == 200
    count_after_first = len(first.json()["messages"])
    second = await client.post(f"/api/illustrations/{ill_id}/manual/iterate")
    assert second.status_code == 200
    assert len(second.json()["messages"]) == count_after_first
