"""Unit tests for RunPod client (§11.1) with HTTP mocked via respx."""

import base64

import httpx
import pytest
import respx

from app.services.runpod import RunPodClient, RunPodError

ENDPOINT_ID = "test-endpoint-123"
API_KEY = "test-api-key"
BASE_URL = f"https://api.runpod.ai/v2/{ENDPOINT_ID}"

IMAGE_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()


@pytest.fixture
def client():
    return RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout=1.0,
    )


@pytest.mark.asyncio
@respx.mock
async def test_run_returns_job_id(client):
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": "job-abc-123"}))
    respx.get(f"{BASE_URL}/status/job-abc-123").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                },
            },
        )
    )
    result = await client.run_workflow({"node": "workflow"})
    assert isinstance(result, bytes)
    assert result[:4] == b"\x89PNG"


@pytest.mark.asyncio
@respx.mock
async def test_status_polled_until_completed(client):
    job_id = "job-polling"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    # First call returns IN_QUEUE, second returns COMPLETED
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        side_effect=[
            httpx.Response(200, json={"status": "IN_QUEUE"}),
            httpx.Response(200, json={"status": "IN_PROGRESS"}),
            httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "output": {
                        "images": [{"filename": "out.png", "type": "base64", "data": IMAGE_B64}]
                    },
                },
            ),
        ]
    )
    result = await client.run_workflow({"node": "workflow"})
    assert isinstance(result, bytes)


@pytest.mark.asyncio
@respx.mock
async def test_timeout_raises_error():
    client = RunPodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval=0.01,
        poll_timeout=0.05,  # Very short timeout
    )
    job_id = "job-timeout"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "IN_PROGRESS"})
    )
    with pytest.raises(RunPodError, match="timed out"):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_failed_status_raises_error(client):
    job_id = "job-failed"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "FAILED", "error": "OOM"})
    )
    with pytest.raises(RunPodError):
        await client.run_workflow({"node": "workflow"})


@pytest.mark.asyncio
@respx.mock
async def test_cancelled_status_raises_error(client):
    job_id = "job-cancelled"
    respx.post(f"{BASE_URL}/run").mock(return_value=httpx.Response(200, json={"id": job_id}))
    respx.get(f"{BASE_URL}/status/{job_id}").mock(
        return_value=httpx.Response(200, json={"status": "CANCELLED"})
    )
    with pytest.raises(RunPodError):
        await client.run_workflow({"node": "workflow"})
