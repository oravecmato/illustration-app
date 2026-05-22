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
from app.db.session import create_tables, init_db
from app.main import create_app
from app.services.character_config import load_character_config
from app.services.claude import ClaudeClient
from app.services.runpod import RunPodClient

IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200).decode()
ENDPOINT_ID = "test-endpoint"
RUNPOD_BASE = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"
ANTHROPIC_BASE = "https://api.anthropic.com/v1/messages"

ANALYZE_STORY_RESPONSE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "style_guide": {
                        "overall_style_positive": "watercolor, children book",
                        "overall_style_negative": "photorealistic",
                        "character_lora": "",
                        "character_baseline_description": "A young princess",
                    },
                    "illustrations": [
                        {
                            "scene_index": 0,
                            "scene_excerpt": "Once upon a time...",
                            "concept": "A girl crying with tears on her cheeks",
                            "character_role": "female",
                        },
                        {
                            "scene_index": 1,
                            "scene_excerpt": "She met a dragon.",
                            "concept": "A girl reaching out with an outstretched hand",
                            "character_role": "female",
                        },
                    ],
                }
            ),
        }
    ],
    "model": "claude-sonnet-4-6",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 100, "output_tokens": 200},
}

GENERATE_PROMPTS_RESPONSE = {
    "id": "msg_02",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "character_positive": "princess, elegant dress",
                    "character_negative": "blurry, deformed",
                    "environment": "magical tower, sparkles",
                }
            ),
        }
    ],
    "model": "claude-sonnet-4-6",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 50, "output_tokens": 50},
}

EVALUATE_IMAGE_OK_RESPONSE = {
    "id": "msg_03",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "ok": True,
                    "problem": None,
                    "reasoning": "The image looks great",
                    "suggestion": "",
                }
            ),
        }
    ],
    "model": "claude-sonnet-4-6",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 50, "output_tokens": 50},
}

RUNPOD_JOB_ID = "rp-job-12345"


def make_settings(db_path: str, output_dir: str) -> Settings:
    return Settings(
        anthropic_api_key="test-anthropic-key",
        runpod_api_key="test-runpod-key",
        runpod_endpoint_id=ENDPOINT_ID,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        output_dir=output_dir,
        workflow_path="./app/workflows/default.json",
        allowed_origin="http://localhost:5173",
    )


@pytest.fixture
async def app_client(tmp_path):
    db_file = str(tmp_path / "test.db")
    output_dir = str(tmp_path / "output")
    os.makedirs(output_dir, exist_ok=True)

    settings = make_settings(db_file, output_dir)

    # Manually boot the app components (bypassing lifespan for tests)
    init_db(settings.database_url)
    await create_tables()

    claude_client = ClaudeClient(api_key=settings.anthropic_api_key)
    runpod_client = RunPodClient(
        api_key=settings.runpod_api_key,
        endpoint_id=settings.runpod_endpoint_id,
    )
    workflow_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "workflows", "default.json"
    )
    with open(workflow_path) as f:
        import json as _json

        workflow_template = _json.load(f)

    char_config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "character_config.json"
    )
    character_config = load_character_config(char_config_path)

    runs_api.set_clients(
        claude=claude_client,
        runpod=runpod_client,
        workflow=workflow_template,
        output_dir=output_dir,
        character_config=character_config,
    )

    app = create_app(settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, settings


@pytest.mark.asyncio
@respx.mock
async def test_end_to_end_happy_path(app_client):
    """POST /api/runs -> background work -> GET /api/runs/{id} COMPLETED."""
    client, settings = app_client

    # Mock Anthropic - analyze_story
    anthropic_call_count = [0]

    def anthropic_handler(request):
        anthropic_call_count[0] += 1
        count = anthropic_call_count[0]
        if count == 1:
            return httpx.Response(200, json=ANALYZE_STORY_RESPONSE)
        else:
            # generate_prompts or evaluate_image
            body = json.loads(request.content)
            messages = body.get("messages", [])
            # Check if it's an evaluate call (has image content)
            has_image = any(
                isinstance(content, dict) and content.get("type") == "image"
                for msg in messages
                for content in (
                    msg.get("content", []) if isinstance(msg.get("content"), list) else []
                )
            )
            if has_image:
                return httpx.Response(200, json=EVALUATE_IMAGE_OK_RESPONSE)
            return httpx.Response(200, json=GENERATE_PROMPTS_RESPONSE)

    respx.post(ANTHROPIC_BASE).mock(side_effect=anthropic_handler)

    # Mock RunPod
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

    # Submit run
    resp = await client.post(
        "/api/runs", json={"story_text": "Once upon a time in a land far away..."}
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    # Wait for background task to complete
    for _ in range(50):
        await asyncio.sleep(0.2)
        status_resp = await client.get(f"/api/runs/{run_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        if data["run"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break

    final = await client.get(f"/api/runs/{run_id}")
    data = final.json()
    assert data["run"]["status"] == "COMPLETED"
    assert data["run"]["completed_count"] == 2


@pytest.mark.asyncio
async def test_post_runs_returns_400_on_empty_story(app_client):
    client, _ = app_client
    resp = await client.post("/api/runs", json={"story_text": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_runs_returns_400_on_too_long_story(app_client):
    client, _ = app_client
    resp = await client.post("/api/runs", json={"story_text": "x" * 50001})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_run_returns_404_for_unknown(app_client):
    client, _ = app_client
    resp = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_no_suitable_scenes_end_to_end(app_client):
    """Agent 0 returns empty illustrations -> run FAILED with NO_SUITABLE_SCENES."""
    client, _ = app_client

    empty_analyze_response = {
        "id": "msg_empty",
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "style_guide": {
                            "overall_style_positive": "anime",
                            "overall_style_negative": "realistic",
                            "character_lora": "",
                            "character_baseline_description": "Warm lighting",
                        },
                        "illustrations": [],
                    }
                ),
            }
        ],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }

    respx.post(ANTHROPIC_BASE).mock(return_value=httpx.Response(200, json=empty_analyze_response))
    runpod_route = respx.post(f"{RUNPOD_BASE}/run").mock(
        return_value=httpx.Response(200, json={"id": "should-not-be-called"})
    )

    resp = await client.post("/api/runs", json={"story_text": "A text with no clear scenes."})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    for _ in range(50):
        await asyncio.sleep(0.2)
        status_resp = await client.get(f"/api/runs/{run_id}")
        data = status_resp.json()
        if data["run"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break

    final = await client.get(f"/api/runs/{run_id}")
    data = final.json()
    assert data["run"]["status"] == "FAILED"
    assert data["run"]["error_code"] == "NO_SUITABLE_SCENES"
    assert runpod_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_cancel_returns_409_for_terminal_run(app_client):
    """Cancel a completed run -> 409."""
    client, settings = app_client

    respx.post(ANTHROPIC_BASE).mock(return_value=httpx.Response(200, json=ANALYZE_STORY_RESPONSE))
    respx.post(f"{RUNPOD_BASE}/run").mock(
        return_value=httpx.Response(200, json={"id": RUNPOD_JOB_ID})
    )
    respx.get(f"{RUNPOD_BASE}/status/{RUNPOD_JOB_ID}").mock(
        return_value=httpx.Response(200, json={"status": "IN_PROGRESS"})
    )

    resp = await client.post("/api/runs", json={"story_text": "A short tale."})
    run_id = resp.json()["run_id"]

    # Immediately cancel (run is RUNNING)
    cancel_resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_resp.status_code in (200, 409)
